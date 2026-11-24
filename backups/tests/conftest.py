import subprocess
from pathlib import Path

import pytest


class FakePostgres:
    """Stands in for pg_dump / pg_restore: records every call, writes a dump file."""

    def __init__(self):
        self.calls = []
        self.fail = {}           # program -> stderr text

    def __call__(self, args, env=None, **kwargs):
        program = Path(args[0]).stem
        self.calls.append({"program": program, "args": args, "env": env})
        if program in self.fail:
            return subprocess.CompletedProcess(args, 1, "", self.fail[program])
        if program == "pg_dump":
            Path(args[args.index("--file") + 1]).write_bytes(b"PGDMP fake dump")
        return subprocess.CompletedProcess(args, 0, "", "")

    def programs(self):
        return [c["program"] for c in self.calls]


@pytest.fixture(autouse=True)
def isolated_backup_dir(settings, tmp_path):
    settings.BACKUP_DIR = str(tmp_path / "backups")


@pytest.fixture
def fake_pg(monkeypatch, settings, tmp_path):
    bin_dir = tmp_path / "pgbin"
    bin_dir.mkdir()
    for name in ("pg_dump.exe", "pg_restore.exe"):
        (bin_dir / name).write_text("")
    settings.PG_BIN_DIR = str(bin_dir)
    fake = FakePostgres()
    monkeypatch.setattr("backups.services.subprocess.run", fake)
    return fake
