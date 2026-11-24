"""Arabic translation catalogue without GNU gettext (works on Windows, the
Ubuntu server and CI alike).

    python tools/i18n.py update    # extract strings from code + templates, merge into the .po
    python tools/i18n.py translate # fill the .po from tools/ar_translations.py
    python tools/i18n.py compile   # write the .mo that Django loads

Strings are found exactly like Django's makemessages: Python files via the
gettext keywords, templates via django.utils.translation.template.templatize.
Existing translations are kept; strings no longer in the code are dropped.
"""

import io
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")

import django  # noqa: E402
from django.apps import apps  # noqa: E402

if not apps.ready:
    django.setup()

from babel.messages.catalog import Catalog  # noqa: E402
from babel.messages.extract import extract as babel_extract  # noqa: E402
from babel.messages.mofile import write_mo  # noqa: E402
from babel.messages.pofile import read_po, write_po  # noqa: E402
from django.utils.translation.template import templatize  # noqa: E402

PO = ROOT / "locale" / "ar" / "LC_MESSAGES" / "django.po"
MO = PO.with_suffix(".mo")

KEYWORDS = {
    "_": None,
    "gettext": None,
    "gettext_lazy": None,
    "gettext_noop": None,
    "ngettext": (1, 2),
    "ngettext_lazy": (1, 2),
    "pgettext": ((1, "c"), 2),
    "pgettext_lazy": ((1, "c"), 2),
    "npgettext": ((1, "c"), 2, 3),
}
SKIP_DIRS = {
    "venv", ".venv", ".git", "migrations", "tests", "tools", "locale",
    "static", "staticfiles", "media", "node_modules", "__pycache__",
}
# Django's own Arabic plural rule (CLDR: zero, one, two, few 3-10, many 11-99, other).
# Babel's generated rule maps 100, 200, ... to "many", which is wrong.
ARABIC_PLURAL_EXPR = (
    "n==0 ? 0 : n==1 ? 1 : n==2 ? 2 : n%100>=3 && n%100<=10 ? 3 : n%100>=11 && n%100<=99 ? 4 : 5"
)
# Translations that are intentionally identical in Arabic (pure numbers / symbols).
KEEP_AS_IS = {"0%", "15%"}


def _with_arabic_plurals(catalog: Catalog) -> Catalog:
    catalog._num_plurals = 6                 # Babel has no public setter for these
    catalog._plural_expr = ARABIC_PLURAL_EXPR
    return catalog


def _new_catalog() -> Catalog:
    return _with_arabic_plurals(Catalog(locale="ar", project="Afaq ERP", charset="utf-8", fuzzy=False))


def is_translated(message) -> bool:
    if isinstance(message.string, str):
        return bool(message.string)
    return bool(message.string) and all(message.string)


def source_files():
    for path in sorted(ROOT.rglob("*")):
        rel = path.relative_to(ROOT)
        if any(part in SKIP_DIRS for part in rel.parts) or not path.is_file():
            continue
        if path.suffix in {".py", ".html", ".txt"}:
            yield path


def extract() -> Catalog:
    catalog = _new_catalog()
    for path in source_files():
        text = path.read_text(encoding="utf-8")
        if path.suffix == ".py":
            code = text
        else:
            # templatize() output is only "Python-like" (fine for xgettext); drop the
            # indentation so Python's tokenizer accepts it. Line numbers are kept.
            code = "\n".join(line.lstrip() for line in templatize(text, origin=str(path)).splitlines())
        rel = path.relative_to(ROOT).as_posix()
        for lineno, message, _comments, context in babel_extract(
            "python", io.BytesIO(code.encode("utf-8")), keywords=KEYWORDS, options={"encoding": "utf-8"}
        ):
            catalog.add(message, locations=[(rel, lineno)], context=context)
    return catalog


def update(po_path: Path = PO) -> Catalog:
    template = extract()
    if po_path.exists():
        with po_path.open("rb") as fh:
            catalog = read_po(fh, locale="ar")
    else:
        catalog = _new_catalog()
    catalog.update(template, no_fuzzy_matching=True)
    _with_arabic_plurals(catalog)
    po_path.parent.mkdir(parents=True, exist_ok=True)
    with po_path.open("wb") as fh:
        write_po(fh, catalog, ignore_obsolete=True, sort_output=True, width=0)
    return catalog


def translate(po_path: Path = PO) -> tuple[list, list]:
    """Fill the .po from tools/ar_translations.AR. Returns (untranslated ids, unused keys)."""
    from tools.ar_translations import AR

    with po_path.open("rb") as fh:
        catalog = read_po(fh, locale="ar")
    _with_arabic_plurals(catalog)
    used, missing = set(), []
    for message in catalog:
        if not message.id:
            continue
        key = tuple(message.id) if isinstance(message.id, (list, tuple)) else message.id
        if key in AR:
            value = AR[key]
            message.string = tuple(value) if isinstance(value, list) else value
            used.add(key)
        elif not is_translated(message):
            missing.append(key)
    with po_path.open("wb") as fh:
        write_po(fh, catalog, ignore_obsolete=True, sort_output=True, width=0)
    return missing, sorted(set(AR) - used, key=str)


def compile_bytes(po_path: Path = PO) -> bytes:
    with po_path.open("rb") as fh:
        catalog = read_po(fh, locale="ar")
    buffer = io.BytesIO()
    write_mo(buffer, catalog, use_fuzzy=False)
    return buffer.getvalue()


def compile(po_path: Path = PO, mo_path: Path = MO) -> None:  # noqa: A001
    mo_path.write_bytes(compile_bytes(po_path))


if __name__ == "__main__":
    command = sys.argv[1] if len(sys.argv) > 1 else ""
    if command == "update":
        cat = update()
        missing = sum(1 for m in cat if m.id and not is_translated(m))
        print(f"{PO.relative_to(ROOT)}: {len([m for m in cat if m.id])} strings, {missing} untranslated")
    elif command == "translate":
        missing, unused = translate()
        print(f"untranslated: {len(missing)}", *missing[:20], sep="\n  ")
        print(f"unused translations: {len(unused)}", *unused[:20], sep="\n  ")
    elif command == "compile":
        compile()
        print(f"wrote {MO.relative_to(ROOT)}")
    else:
        sys.exit("usage: python tools/i18n.py update|translate|compile")
