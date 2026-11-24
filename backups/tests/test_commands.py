"""Integration tests: the backup / restore management commands (PostgreSQL faked)."""

import datetime as dt
from io import StringIO
from pathlib import Path

import pytest
from django.core.management import call_command
from django.core.management.base import CommandError
from django.utils import timezone

from backups import services

pytestmark = pytest.mark.django_db


def run(*args):
    out = StringIO()
    call_command(*args, stdout=out)
    return out.getvalue()


def test_backup_command_saves_and_logs(fake_pg, settings):
    output = run("backup")
    (backup,) = services.list_backups()
    assert f"Backup saved: {backup.dump}" in output
    log = (Path(settings.BACKUP_DIR) / "backup.log").read_text(encoding="utf-8")
    assert f"OK {backup.dump.name}" in log


def test_backup_command_reports_media(fake_pg, settings):
    (Path(settings.MEDIA_ROOT) / "a.txt").parent.mkdir(parents=True, exist_ok=True)
    (Path(settings.MEDIA_ROOT) / "a.txt").write_text("A")
    assert "Uploaded files:" in run("backup")
    assert "Uploaded files:" not in run("backup", "--no-media")


def test_backup_command_prunes(fake_pg, settings):
    start = timezone.make_aware(dt.datetime(2026, 11, 1, 2, 0))
    for day in range(4):
        services.create_backup(now=start + dt.timedelta(days=day))
    output = run("backup", "--keep", "2")
    assert "Removed 3 old backup(s)." in output
    assert len(services.list_backups()) == 2


def test_backup_default_keep_from_settings(fake_pg, settings):
    settings.BACKUP_KEEP = 1
    services.create_backup(now=timezone.make_aware(dt.datetime(2026, 11, 1, 2, 0)))
    run("backup")
    assert len(services.list_backups()) == 1


def test_backup_failure_is_a_command_error_and_logged(fake_pg, settings):
    fake_pg.fail["pg_dump"] = "password authentication failed"
    with pytest.raises(CommandError, match="password authentication failed"):
        run("backup")
    log = (Path(settings.BACKUP_DIR) / "backup.log").read_text(encoding="utf-8")
    assert "FAILED pg_dump failed: password authentication failed" in log


def test_backup_list(fake_pg):
    assert "No backups yet." in run("backup", "--list")
    services.create_backup(now=timezone.make_aware(dt.datetime(2026, 11, 1, 2, 0)))
    output = run("backup", "--list")
    assert "20261101-020000" in output and "afaq-20261101-020000.dump" in output
    assert len(services.list_backups()) == 1          # --list does not back up


def test_restore_needs_yes(fake_pg):
    backup = services.create_backup(now=timezone.make_aware(dt.datetime(2026, 11, 1, 2, 0)))
    fake_pg.calls.clear()
    with pytest.raises(CommandError, match="--yes"):
        run("restore", backup.stamp)
    assert fake_pg.calls == []


def test_restore_takes_a_safety_backup_first(fake_pg):
    backup = services.create_backup(now=timezone.make_aware(dt.datetime(2026, 11, 1, 2, 0)))
    fake_pg.calls.clear()
    output = run("restore", backup.stamp, "--yes")
    assert fake_pg.programs() == ["pg_dump", "pg_restore", "pg_restore"]
    assert "--clean" in fake_pg.calls[-1]["args"]
    assert "Safety backup of the current data:" in output
    assert f"Restored backup {backup.stamp}." in output
    assert len(services.list_backups()) == 2


def test_restore_without_safety_backup(fake_pg):
    backup = services.create_backup(now=timezone.make_aware(dt.datetime(2026, 11, 1, 2, 0)))
    fake_pg.calls.clear()
    run("restore", backup.stamp, "--yes", "--no-safety-backup", "--no-media")
    assert fake_pg.programs() == ["pg_restore"]


def test_restore_unknown_backup(fake_pg):
    with pytest.raises(CommandError, match="No backup called"):
        run("restore", "20990101-000000", "--yes")
