"""Break & fix check.

For each app given on the command line, load `<app>/tests/mutations.py`,
apply every mutation (a deliberate bug) one at a time, run that app's tests,
and confirm at least one test FAILS. The original file is always restored,
even on Ctrl+C or a crash.

Usage:
    python tools/break_check.py hr core

Exit code is 0 only if every mutation was caught by the tests.
"""

import importlib
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


def run_tests(app: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, "-m", "pytest", f"{app}/tests", "-x", "-q", "-p", "no:cacheprovider"],
        cwd=ROOT,
        capture_output=True,
        text=True,
    )


def check_app(app: str) -> tuple[int, int]:
    mutations = importlib.import_module(f"{app}.tests.mutations").MUTATIONS
    caught = 0
    print(f"\n=== {app}: {len(mutations)} mutations ===")
    for i, (title, rel_path, old, new) in enumerate(mutations, 1):
        path = ROOT / rel_path
        original = path.read_text(encoding="utf-8")
        if original.count(old) != 1:
            print(f"[{i:>2}] SKIPPED (target text not found exactly once): {title}")
            continue
        try:
            path.write_text(original.replace(old, new), encoding="utf-8")
            result = run_tests(app)
        finally:
            path.write_text(original, encoding="utf-8")

        failed = [ln for ln in result.stdout.splitlines() if ln.startswith(("FAILED", "ERROR"))]
        if result.returncode != 0:
            caught += 1
            by = failed[0].split(" - ")[0].split("::")[-1] if failed else "collection/import error"
            print(f"[{i:>2}] CAUGHT     {title}\n       by: {by}")
        else:
            print(f"[{i:>2}] NOT CAUGHT {title}   <-- tests missing!")
    return caught, len(mutations)


def main(apps: list[str]) -> int:
    total_caught = total = 0
    for app in apps:
        c, t = check_app(app)
        total_caught += c
        total += t
    print(f"\nResult: {total_caught}/{total} mutations caught")
    return 0 if total_caught == total else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:] or ["core"]))
