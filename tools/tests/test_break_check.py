"""Unit tests: break_check never leaves a deliberate bug behind."""

import json

import pytest

from tools import break_check


@pytest.fixture
def target(tmp_path):
    f = tmp_path / "code.py"
    f.write_text("x = 1\n", encoding="utf-8")
    return f


def test_mutation_is_applied_then_restored(target, tmp_path):
    journal = tmp_path / "journal.json"

    with break_check.mutated(target, "x = 1", "x = 2", journal=journal):
        assert target.read_text(encoding="utf-8") == "x = 2\n"
        assert journal.exists()

    assert target.read_text(encoding="utf-8") == "x = 1\n"
    assert not journal.exists()


def test_file_restored_even_if_tests_crash(target, tmp_path):
    journal = tmp_path / "journal.json"

    with pytest.raises(RuntimeError):
        with break_check.mutated(target, "x = 1", "x = 2", journal=journal):
            raise RuntimeError("boom")

    assert target.read_text(encoding="utf-8") == "x = 1\n"
    assert not journal.exists()


def test_recover_restores_file_left_by_a_killed_run(target, tmp_path):
    target.write_text("x = 2\n", encoding="utf-8")          # leftover bug
    journal = tmp_path / "journal.json"
    journal.write_text(json.dumps({"path": str(target), "original": "x = 1\n"}), encoding="utf-8")

    assert break_check.recover(journal) == target
    assert target.read_text(encoding="utf-8") == "x = 1\n"
    assert not journal.exists()


def test_recover_without_journal_does_nothing(tmp_path):
    assert break_check.recover(tmp_path / "missing.json") is None


@pytest.mark.parametrize("eol", [b"\n", b"\r\n"])
def test_original_bytes_restored_exactly(tmp_path, eol):
    f = tmp_path / "code.py"
    original = b"a = 1" + eol + b"b = 2" + eol
    f.write_bytes(original)

    with break_check.mutated(f, "a = 1\nb = 2", "a = 9\nb = 9", journal=tmp_path / "j.json"):
        assert f.read_bytes() == b"a = 9" + eol + b"b = 9" + eol   # multi-line match works

    assert f.read_bytes() == original


def test_count_target_handles_crlf_files(tmp_path):
    f = tmp_path / "code.py"
    f.write_bytes(b"a = 1\r\nb = 2\r\n")
    assert break_check.count_target(f, "a = 1\nb = 2") == 1
