"""Break & fix check.

For each app given on the command line, load `<app>/tests/mutations.py`,
apply every mutation (a deliberate bug) one at a time, run that app's tests,
and confirm at least one test FAILS.

Safety: before a file is mutated its original bytes are written to a journal
file. They are restored after the test run, on Ctrl+C or a crash, and — if the
process was killed outright — automatically at the start of the next run.

Usage:
    python tools/break_check.py hr core

Exit code is 0 only if every mutation was caught by the tests.
"""

import contextlib
import importlib
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
JOURNAL = ROOT / ".break_check_journal.json"
sys.path.insert(0, str(ROOT))


def _read_raw(path: Path) -> str:
    return path.read_bytes().decode("utf-8")


def _write_raw(path: Path, text: str) -> None:
    path.write_bytes(text.encode("utf-8"))   # no newline translation


def _match_eol(snippet: str, raw: str) -> str:
    return snippet.replace("\n", "\r\n") if "\r\n" in raw else snippet


def count_target(path: Path, old: str) -> int:
    raw = _read_raw(path)
    return raw.count(_match_eol(old, raw))


@contextlib.contextmanager
def mutated(path: Path, old: str, new: str, journal: Path = JOURNAL):
    """Apply one mutation for the duration of the block; always restore."""
    original = _read_raw(path)
    journal.write_text(json.dumps({"path": str(path), "original": original}), encoding="utf-8")
    try:
        _write_raw(path, original.replace(_match_eol(old, original), _match_eol(new, original), 1))
        yield
    finally:
        _write_raw(path, original)
        journal.unlink(missing_ok=True)


def recover(journal: Path = JOURNAL) -> Path | None:
    """Restore a file left mutated by a killed run. Returns the restored path."""
    if not journal.exists():
        return None
    data = json.loads(journal.read_text(encoding="utf-8"))
    path = Path(data["path"])
    _write_raw(path, data["original"])
    journal.unlink()
    return path


def run_tests(app: str, rebuild_db: bool) -> subprocess.CompletedProcess:
    # Reuse the test DB for speed; rebuild it when migrations are involved.
    db_flag = "--create-db" if rebuild_db else "--reuse-db"
    return subprocess.run(
        [sys.executable, "-m", "pytest", f"{app}/tests", "-x", "-q", "-p", "no:cacheprovider", db_flag],
        cwd=ROOT,
        capture_output=True,
        text=True,
    )


def check_app(app: str) -> tuple[int, int]:
    mutations = importlib.import_module(f"{app}.tests.mutations").MUTATIONS
    caught = 0
    db_dirty = True   # first run builds a fresh test DB from the real migrations
    print(f"\n=== {app}: {len(mutations)} mutations ===")
    for i, (title, rel_path, old, new) in enumerate(mutations, 1):
        path = ROOT / rel_path
        if count_target(path, old) != 1:
            print(f"[{i:>2}] SKIPPED (target text not found exactly once): {title}")
            continue
        mutates_migration = "/migrations/" in rel_path
        with mutated(path, old, new):
            result = run_tests(app, rebuild_db=db_dirty or mutates_migration)
        # A DB built from a mutated migration must not be reused afterwards.
        db_dirty = mutates_migration

        failed = [ln for ln in result.stdout.splitlines() if ln.startswith(("FAILED", "ERROR"))]
        if result.returncode != 0:
            caught += 1
            by = failed[0].split(" - ")[0].split("::")[-1] if failed else "collection/import error"
            print(f"[{i:>2}] CAUGHT     {title}\n       by: {by}")
        else:
            print(f"[{i:>2}] NOT CAUGHT {title}   <-- tests missing!")
    return caught, len(mutations)


def main(apps: list[str]) -> int:
    restored = recover()
    if restored:
        print(f"WARNING: previous run was killed; restored {restored}")
    total_caught = total = 0
    for app in apps:
        c, t = check_app(app)
        total_caught += c
        total += t
    print(f"\nResult: {total_caught}/{total} mutations caught")
    return 0 if total_caught == total else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:] or ["core"]))
