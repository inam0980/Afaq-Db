"""Deliberate bugs for tools/break_check.py itself."""

BC = "tools/break_check.py"

MUTATIONS = [
    ("File not restored after the run", BC,
     "    finally:\n        _write_raw(path, original)\n", "    finally:\n        pass\n"),
    ("Journal not written before mutating", BC,
     '    journal.write_text(json.dumps({"path": str(path), "original": original}), encoding="utf-8")\n', ""),
    ("Journal left behind after restore", BC,
     "        journal.unlink(missing_ok=True)\n", "        pass\n"),
    ("recover() does not restore the file", BC,
     '    _write_raw(path, data["original"])\n    journal.unlink()', "    journal.unlink()"),
    ("Newlines translated on write", BC,
     'path.write_bytes(text.encode("utf-8"))', 'path.write_text(text, encoding="utf-8")'),
    ("CRLF files not matched", BC,
     r'return snippet.replace("\n", "\r\n") if "\r\n" in raw else snippet', "return snippet"),
]

MUTATIONS += [
    ("Test output decoded with the Windows code page", BC,
     '        encoding="utf-8",      # test output can contain Arabic\n        errors="replace",\n',
     "        text=True,\n"),
]
