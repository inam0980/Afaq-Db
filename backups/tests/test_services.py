"""Unit tests: backup files, verification, retention, restore — PostgreSQL faked."""

import datetime as dt
import zipfile
from pathlib import Path

import pytest
from django.db import connections
from django.utils import timezone

from backups import services
from backups.services import BackupError

pytestmark = pytest.mark.django_db

NOW = timezone.make_aware(dt.datetime(2026, 11, 25, 2, 0, 0))


def make_media(settings, files):
    for name, data in files.items():
        path = Path(settings.MEDIA_ROOT) / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)


def test_backup_creates_a_verified_dump(fake_pg, settings):
    backup = services.create_backup(now=NOW)
    assert backup.dump == Path(settings.BACKUP_DIR) / "afaq-20261125-020000.dump"
    assert backup.dump.read_bytes() == b"PGDMP fake dump"
    assert fake_pg.programs() == ["pg_dump", "pg_restore"]
    dump_args = fake_pg.calls[0]["args"]
    assert "--format=custom" in dump_args and "--no-owner" in dump_args
    assert dump_args[-1] == connections["default"].settings_dict["NAME"]      # the test database
    assert fake_pg.calls[1]["args"][1:] == ["--list", str(backup.dump) + ".part"]
    assert not list(Path(settings.BACKUP_DIR).glob("*.part"))


def test_timestamp_is_riyadh_local_time(fake_pg):
    utc = dt.datetime(2026, 11, 24, 23, 30, tzinfo=dt.UTC)      # 02:30 in Riyadh
    assert services.create_backup(now=utc).stamp == "20261125-023000"


def test_password_goes_in_environment_not_arguments(fake_pg, settings):
    db = connections["default"].settings_dict
    services.create_backup(now=NOW)
    call = fake_pg.calls[0]
    assert call["env"]["PGPASSWORD"] == db["PASSWORD"]
    assert db["PASSWORD"] not in call["args"]
    assert call["args"][call["args"].index("--username") + 1] == db["USER"]
    assert call["args"][call["args"].index("--host") + 1] == db["HOST"]


def test_blank_connection_settings_are_left_out(fake_pg, monkeypatch):
    db = dict(connections["default"].settings_dict, HOST="", PORT="", PASSWORD="")
    monkeypatch.setattr(services, "_db", lambda: db)
    monkeypatch.delenv("PGPASSWORD", raising=False)
    services.create_backup(now=NOW)
    args, env = fake_pg.calls[0]["args"], fake_pg.calls[0]["env"]
    assert "--host" not in args and "--port" not in args and "PGPASSWORD" not in env


def test_failed_dump_leaves_no_file(fake_pg, settings):
    fake_pg.fail["pg_dump"] = "connection refused"
    with pytest.raises(BackupError, match="pg_dump failed: connection refused"):
        services.create_backup(now=NOW)
    assert not list(Path(settings.BACKUP_DIR).iterdir())


def test_unreadable_dump_is_not_kept(fake_pg, settings):
    fake_pg.fail["pg_restore"] = "input file appears to be corrupt"
    with pytest.raises(BackupError, match="pg_restore failed"):
        services.create_backup(now=NOW)
    assert services.list_backups() == []
    assert not list(Path(settings.BACKUP_DIR).iterdir())


def test_media_is_zipped_alongside(fake_pg, settings):
    make_media(settings, {"receipts/a.pdf": b"A", "leave/2026/b.jpg": b"B"})
    backup = services.create_backup(now=NOW)
    assert backup.media.name == "afaq-20261125-020000-media.zip"
    with zipfile.ZipFile(backup.media) as archive:
        assert sorted(archive.namelist()) == ["leave/2026/b.jpg", "receipts/a.pdf"]
    assert backup.size == backup.dump.stat().st_size + backup.media.stat().st_size


def test_no_media_zip_without_uploads_or_when_skipped(fake_pg, settings):
    assert services.create_backup(now=NOW).media is None
    make_media(settings, {"a.txt": b"A"})
    assert services.create_backup(now=NOW + dt.timedelta(seconds=1), include_media=False).media is None


def test_missing_pg_tools(settings, monkeypatch, tmp_path):
    settings.PG_BIN_DIR = str(tmp_path)
    with pytest.raises(BackupError, match="pg_dump not found"):
        services.pg_tool("pg_dump")
    settings.PG_BIN_DIR = ""
    monkeypatch.setattr(services.shutil, "which", lambda name: None)
    with pytest.raises(BackupError, match="PG_BIN_DIR"):
        services.pg_tool("pg_restore")
    monkeypatch.setattr(services.shutil, "which", lambda name: f"/usr/bin/{name}")
    assert services.pg_tool("pg_restore") == "/usr/bin/pg_restore"


def test_pg_tool_without_exe_suffix(settings, tmp_path):
    (tmp_path / "pg_dump").write_text("")                    # Linux
    settings.PG_BIN_DIR = str(tmp_path)
    assert services.pg_tool("pg_dump") == str(tmp_path / "pg_dump")


def test_list_and_prune_keep_the_newest(fake_pg, settings):
    make_media(settings, {"a.txt": b"A"})
    for hour in range(5):
        services.create_backup(now=NOW + dt.timedelta(hours=hour))
    (Path(settings.BACKUP_DIR) / "notes.txt").write_text("not a backup")
    stamps = [b.stamp for b in services.list_backups()]
    assert stamps == ["20261125-060000", "20261125-050000", "20261125-040000",
                      "20261125-030000", "20261125-020000"]
    removed = services.prune(keep=2)
    assert [b.stamp for b in removed] == ["20261125-040000", "20261125-030000", "20261125-020000"]
    left = sorted(p.name for p in Path(settings.BACKUP_DIR).iterdir())
    assert left == ["afaq-20261125-050000-media.zip", "afaq-20261125-050000.dump",
                    "afaq-20261125-060000-media.zip", "afaq-20261125-060000.dump", "notes.txt"]


def test_prune_never_deletes_everything(fake_pg):
    services.create_backup(now=NOW)
    with pytest.raises(BackupError):
        services.prune(keep=0)
    assert len(services.list_backups()) == 1


def test_list_without_folder(settings, tmp_path):
    settings.BACKUP_DIR = str(tmp_path / "missing")
    assert services.list_backups() == [] and services.latest_backup() is None


def test_backup_created_time(fake_pg):
    backup = services.create_backup(now=NOW)
    assert services.latest_backup().created == NOW == backup.created


def test_restore_runs_pg_restore_clean_in_one_transaction(fake_pg):
    backup = services.create_backup(now=NOW)
    fake_pg.calls.clear()
    services.restore_backup(backup)
    args = fake_pg.calls[0]["args"]
    assert fake_pg.programs() == ["pg_restore"]
    for flag in ("--clean", "--if-exists", "--single-transaction", "--no-owner"):
        assert flag in args
    assert args[args.index("--dbname") + 1] == connections["default"].settings_dict["NAME"]
    assert args[-1] == str(backup.dump)


def test_restore_brings_back_uploaded_files(fake_pg, settings):
    make_media(settings, {"receipts/a.pdf": b"original"})
    backup = services.create_backup(now=NOW)
    (Path(settings.MEDIA_ROOT) / "receipts/a.pdf").unlink()
    services.restore_backup(backup)
    assert (Path(settings.MEDIA_ROOT) / "receipts/a.pdf").read_bytes() == b"original"


def test_restore_can_skip_media(fake_pg, settings):
    make_media(settings, {"a.txt": b"A"})
    backup = services.create_backup(now=NOW)
    (Path(settings.MEDIA_ROOT) / "a.txt").unlink()
    services.restore_backup(backup, include_media=False)
    assert not (Path(settings.MEDIA_ROOT) / "a.txt").exists()


def test_restore_failure_raises(fake_pg):
    backup = services.create_backup(now=NOW)
    fake_pg.fail["pg_restore"] = "boom"
    with pytest.raises(BackupError, match="boom"):
        services.restore_backup(backup)


def test_media_archive_cannot_write_outside_media(fake_pg, settings, tmp_path):
    backup = services.create_backup(now=NOW)
    evil = backup.dump.with_name("afaq-20261125-020000-media.zip")
    with zipfile.ZipFile(evil, "w") as archive:
        archive.writestr("../../escaped.txt", "x")
    backup = services.find_backup("20261125-020000")
    with pytest.raises(BackupError, match="Unsafe path"):
        services.restore_backup(backup)
    assert not (tmp_path / "escaped.txt").exists()


def test_find_backup_by_stamp_name_or_path(fake_pg, settings, tmp_path):
    backup = services.create_backup(now=NOW)
    assert services.find_backup("20261125-020000").dump == backup.dump
    assert services.find_backup("afaq-20261125-020000.dump").dump == backup.dump
    elsewhere = tmp_path / "usb"
    elsewhere.mkdir()
    copy = elsewhere / "afaq-20261101-020000.dump"
    copy.write_bytes(b"PGDMP")
    found = services.find_backup(str(copy))
    assert (found.stamp, found.dump, found.media) == ("20261101-020000", copy, None)
    (elsewhere / "afaq-20261101-020000-media.zip").write_bytes(b"")
    assert services.find_backup(str(copy)).media is not None
    with pytest.raises(BackupError):
        services.find_backup("nope")
    with pytest.raises(BackupError):
        services.find_backup(str(elsewhere / "afaq-20200101-000000.dump"))


def test_backup_overdue(fake_pg, settings):
    settings.BACKUP_WARN_HOURS = 36
    assert services.backup_overdue(now=NOW)                         # never backed up
    services.create_backup(now=NOW)
    assert not services.backup_overdue(now=NOW + dt.timedelta(hours=36))
    assert services.backup_overdue(now=NOW + dt.timedelta(hours=36, seconds=1))
