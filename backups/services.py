"""Database + uploaded-files backups.

A backup is a pair of files sharing one timestamp in BACKUP_DIR:
    afaq-YYYYMMDD-HHMMSS.dump        PostgreSQL custom-format dump (pg_dump -Fc)
    afaq-YYYYMMDD-HHMMSS-media.zip   receipts, leave documents and other uploads

Every dump is checked with `pg_restore --list` before it is kept, so a
truncated or broken dump never replaces a good one. Old backups beyond
BACKUP_KEEP are pruned. Copy BACKUP_DIR off the server (USB / NAS / cloud) —
a backup on the same disk does not survive a disk failure.
"""

import datetime as dt
import os
import re
import shutil
import subprocess
import zipfile
from dataclasses import dataclass
from pathlib import Path

from django.conf import settings
from django.db import connections
from django.utils import timezone

PREFIX = "afaq-"
STAMP_FORMAT = "%Y%m%d-%H%M%S"
DUMP_RE = re.compile(r"^afaq-(\d{8}-\d{6})\.dump$")


class BackupError(Exception):
    pass


@dataclass
class Backup:
    stamp: str
    dump: Path
    media: Path | None

    @property
    def created(self) -> dt.datetime:
        naive = dt.datetime.strptime(self.stamp, STAMP_FORMAT)
        return timezone.make_aware(naive)

    @property
    def size(self) -> int:
        return self.dump.stat().st_size + (self.media.stat().st_size if self.media else 0)


def backup_dir() -> Path:
    return Path(settings.BACKUP_DIR)


def pg_tool(name: str) -> str:
    """Full path of a PostgreSQL client program (pg_dump / pg_restore)."""
    if settings.PG_BIN_DIR:
        for candidate in (Path(settings.PG_BIN_DIR) / name, Path(settings.PG_BIN_DIR) / f"{name}.exe"):
            if candidate.is_file():
                return str(candidate)
    else:
        found = shutil.which(name)
        if found:
            return found
    raise BackupError(f"{name} not found. Install the PostgreSQL client tools or set PG_BIN_DIR in .env.")


def _db():
    return connections["default"].settings_dict


def _connection_args() -> list[str]:
    db = _db()
    args = []
    for flag, key in (("--host", "HOST"), ("--port", "PORT"), ("--username", "USER")):
        if db.get(key):
            args += [flag, str(db[key])]
    return args


def _env() -> dict:
    env = dict(os.environ)
    if _db().get("PASSWORD"):
        env["PGPASSWORD"] = _db()["PASSWORD"]   # never on the command line (visible in process lists)
    return env


def _run(args: list[str]) -> subprocess.CompletedProcess:
    result = subprocess.run(args, env=_env(), capture_output=True, text=True, encoding="utf-8",
                            errors="replace")
    if result.returncode != 0:
        program = Path(args[0]).stem
        raise BackupError(f"{program} failed: {(result.stderr or result.stdout).strip()}")
    return result


def _zip_media(target: Path) -> Path | None:
    media = Path(settings.MEDIA_ROOT)
    files = [p for p in media.rglob("*") if p.is_file()] if media.is_dir() else []
    if not files:
        return None
    partial = target.with_name(target.name + ".part")
    with zipfile.ZipFile(partial, "w", zipfile.ZIP_DEFLATED) as archive:
        for path in files:
            archive.write(path, path.relative_to(media).as_posix())
    partial.replace(target)
    return target


def create_backup(now: dt.datetime | None = None, include_media: bool = True) -> Backup:
    folder = backup_dir()
    folder.mkdir(parents=True, exist_ok=True)
    stamp = timezone.localtime(now or timezone.now()).strftime(STAMP_FORMAT)
    dump = folder / f"{PREFIX}{stamp}.dump"
    partial = folder / f"{PREFIX}{stamp}.dump.part"
    try:
        _run([pg_tool("pg_dump"), *_connection_args(), "--format=custom", "--no-owner",
              "--file", str(partial), _db()["NAME"]])
        _run([pg_tool("pg_restore"), "--list", str(partial)])        # proves the dump is readable
        media = _zip_media(folder / f"{PREFIX}{stamp}-media.zip") if include_media else None
    except BaseException:
        partial.unlink(missing_ok=True)
        raise
    partial.replace(dump)
    return Backup(stamp, dump, media)


def list_backups() -> list[Backup]:
    folder = backup_dir()
    if not folder.is_dir():
        return []
    found = []
    for path in folder.iterdir():
        match = DUMP_RE.match(path.name)
        if match:
            media = path.with_name(f"{PREFIX}{match[1]}-media.zip")
            found.append(Backup(match[1], path, media if media.is_file() else None))
    return sorted(found, key=lambda b: b.stamp, reverse=True)


def latest_backup() -> Backup | None:
    backups = list_backups()
    return backups[0] if backups else None


def backup_overdue(now: dt.datetime | None = None) -> bool:
    """True when there is no backup newer than BACKUP_WARN_HOURS."""
    latest = latest_backup()
    if latest is None:
        return True
    return (now or timezone.now()) - latest.created > dt.timedelta(hours=settings.BACKUP_WARN_HOURS)


def prune(keep: int) -> list[Backup]:
    """Delete all but the newest `keep` backups; return what was deleted."""
    if keep < 1:
        raise BackupError("Refusing to delete every backup: keep must be at least 1.")
    removed = list_backups()[keep:]
    for backup in removed:
        backup.dump.unlink()
        if backup.media:
            backup.media.unlink()
    return removed


def _extract_media(archive_path: Path):
    media = Path(settings.MEDIA_ROOT).resolve()
    with zipfile.ZipFile(archive_path) as archive:
        for name in archive.namelist():
            target = (media / name).resolve()
            if not target.is_relative_to(media):
                raise BackupError(f"Unsafe path in media archive: {name}")
        media.mkdir(parents=True, exist_ok=True)
        archive.extractall(media)


def restore_backup(backup: Backup, include_media: bool = True):
    """Replace the current database (and add back uploaded files) from a backup."""
    _run([pg_tool("pg_restore"), *_connection_args(), "--clean", "--if-exists", "--no-owner",
          "--single-transaction", "--dbname", _db()["NAME"], str(backup.dump)])
    if include_media and backup.media:
        _extract_media(backup.media)


def find_backup(name: str) -> Backup:
    """Accept a stamp (20261125-020000), a file name or a full path."""
    wanted = Path(name).name
    for backup in list_backups():
        if wanted in (backup.stamp, backup.dump.name):
            return backup
    path = Path(name)
    match = DUMP_RE.match(path.name)
    if match and path.is_file():
        media = path.with_name(f"{PREFIX}{match[1]}-media.zip")
        return Backup(match[1], path, media if media.is_file() else None)
    raise BackupError(f"No backup called {name!r}.")
