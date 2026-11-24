"""End-to-end: a real pg_dump / pg_restore round trip.

Runs against a throw-away scratch database, never the Django test database:
a transactional test there would leave it flushed (data-migration rows such
as GOSI rates gone) for every later run that uses --reuse-db.
Skipped where the PostgreSQL client tools are not installed."""

import uuid

import psycopg
import pytest
from django.db import connections

from backups import services


def _tools_available():
    try:
        services.pg_tool("pg_dump")
        services.pg_tool("pg_restore")
    except services.BackupError:
        return False
    return True


def _connect(db, dbname):
    return psycopg.connect(host=db["HOST"] or None, port=db["PORT"] or None, user=db["USER"],
                           password=db["PASSWORD"], dbname=dbname, autocommit=True)


@pytest.fixture
def scratch_db(monkeypatch):
    db = dict(connections["default"].settings_dict)
    name = f"afaq_backup_test_{uuid.uuid4().hex[:8]}"
    with _connect(db, "postgres") as admin:
        admin.execute(f'CREATE DATABASE "{name}"')
    monkeypatch.setattr(services, "_db", lambda: dict(db, NAME=name))
    try:
        with _connect(db, name) as conn:
            yield conn
    finally:
        with _connect(db, "postgres") as admin:
            admin.execute(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)')


def rows(conn):
    return [r[0] for r in conn.execute("SELECT note FROM notes ORDER BY note").fetchall()]


def test_backup_then_restore_brings_data_back(scratch_db):
    if not _tools_available():
        pytest.skip("PostgreSQL client tools not installed")
    scratch_db.execute("CREATE TABLE notes (note text)")
    scratch_db.execute("INSERT INTO notes VALUES ('before backup')")
    backup = services.create_backup()
    assert backup.dump.stat().st_size > 100

    scratch_db.execute("DELETE FROM notes")
    scratch_db.execute("INSERT INTO notes VALUES ('after backup')")
    services.restore_backup(backup)

    assert rows(scratch_db) == ["before backup"]
