"""Arabic translations: complete, placeholder-safe, compiled, and actually used.

The catalogue is built with tools/i18n.py (Babel; no GNU gettext needed).
"""

import re
from pathlib import Path

import pytest
from babel.messages.pofile import read_po
from django.conf import settings
from django.urls import reverse
from django.utils import translation

from tools import i18n

PO = Path(settings.BASE_DIR) / "locale" / "ar" / "LC_MESSAGES" / "django.po"
MO = PO.with_suffix(".mo")
PLACEHOLDER = re.compile(r"%\((\w+)\)[sd]|%[sd]|\{\{\s*\w+\s*\}\}")


@pytest.fixture(scope="module")
def catalog():
    with PO.open("rb") as fh:
        return read_po(fh, locale="ar")


def messages(catalog):
    return [m for m in catalog if m.id]


# --- extraction ------------------------------------------------------------------

def test_extraction_finds_strings_from_python_and_templates():
    ids = {m.id if isinstance(m.id, str) else m.id[0] for m in i18n.extract() if m.id}
    assert "Employees" in ids                                  # templates
    assert "Expiring documents" in ids
    assert "Saudi nationals must have a National ID starting with 1." in ids   # python
    assert "%(n)s completed job" in ids                       # blocktranslate count (singular)


def test_catalogue_is_up_to_date_with_the_code(catalog):
    extracted = {m.id if isinstance(m.id, str) else m.id[0] for m in i18n.extract() if m.id}
    in_po = {m.id if isinstance(m.id, str) else m.id[0] for m in messages(catalog)}
    missing = sorted(extracted - in_po)
    assert not missing, f"run `python tools/i18n.py update`; new strings: {missing[:10]}"


# --- completeness & safety -------------------------------------------------------

def test_every_string_is_translated(catalog):
    untranslated = [m.id for m in messages(catalog) if not i18n.is_translated(m)]
    assert not untranslated, untranslated[:15]


def test_no_fuzzy_translations(catalog):
    assert not [m.id for m in messages(catalog) if m.fuzzy]


def test_arabic_has_six_plural_forms(catalog):
    assert catalog.num_plurals == 6
    assert "n%100>=11 && n%100<=99 ? 4" in catalog.plural_expr    # Django's rule, not Babel's
    for m in messages(catalog):
        if m.pluralizable:
            assert len(m.string) == 6 and all(m.string), m.id


def test_placeholders_are_preserved(catalog):
    problems = []
    for m in messages(catalog):
        ids = m.id if isinstance(m.id, (list, tuple)) else (m.id,)
        strings = m.string if isinstance(m.string, (list, tuple)) else (m.string,)
        expected = {p for s in ids for p in PLACEHOLDER.findall(s)}
        for s in strings:
            if set(PLACEHOLDER.findall(s)) - expected:
                problems.append(m.id)  # pragma: no cover - only on failure
        # every named placeholder of the singular must survive in the main translation
        named = set(re.findall(r"%\((\w+)\)", ids[-1]))
        if strings and named - set(re.findall(r"%\((\w+)\)", strings[-1])):
            problems.append(m.id)  # pragma: no cover - only on failure
    assert not problems, problems[:10]


def test_translations_contain_arabic_script(catalog):
    latin_only = [
        m.id for m in messages(catalog)
        if isinstance(m.string, str) and m.string and not re.search(r"[؀-ۿ]", m.string)
        and m.string not in i18n.KEEP_AS_IS
    ]
    assert not latin_only, latin_only[:15]


def test_compiled_catalogue_matches_po():
    assert MO.exists(), "run `python tools/i18n.py compile`"
    assert i18n.compile_bytes(PO) == MO.read_bytes(), "run `python tools/i18n.py compile`"


# --- the running app ------------------------------------------------------------------

def test_gettext_returns_arabic():
    with translation.override("ar"):
        assert translation.gettext("Employees") == "الموظفون"


@pytest.mark.django_db
def test_dashboard_and_sidebar_render_in_arabic(admin_client):
    html = admin_client.get(reverse("home"), HTTP_ACCEPT_LANGUAGE="ar").content.decode()
    assert 'dir="rtl"' in html
    assert "لوحة التحكم" in html          # Dashboard
    assert "الموظفون" in html             # Employees
    assert ">Dashboard<" not in html


@pytest.mark.django_db
def test_model_choices_and_validation_messages_in_arabic():
    from hr.models import Employee

    with translation.override("ar"):
        assert str(Employee.Status.ACTIVE.label) == "نشط"
        assert "1" in translation.gettext("Saudi nationals must have a National ID starting with 1.")


@pytest.mark.django_db
def test_switching_language_back_to_english(admin_client):
    html = admin_client.get(reverse("home"), HTTP_ACCEPT_LANGUAGE="en").content.decode()
    assert "Dashboard" in html and 'dir="ltr"' in html


def test_po_matches_the_translation_source(catalog):
    """tools/ar_translations.py is the source; the .po must not drift from it."""
    from tools.ar_translations import AR

    by_id = {(tuple(m.id) if isinstance(m.id, (list, tuple)) else m.id): m for m in messages(catalog)}
    drift = []
    for key, value in AR.items():
        expected = tuple(value) if isinstance(value, list) else value
        actual = by_id[key].string
        if (tuple(actual) if isinstance(actual, (list, tuple)) else actual) != expected:
            drift.append(key)  # pragma: no cover - only on failure
    assert not drift, f"run `python tools/i18n.py translate`; changed: {drift[:5]}"
