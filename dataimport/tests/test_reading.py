"""Unit tests: reading spreadsheets and cleaning Excel's typical value problems."""

import datetime as dt
from decimal import Decimal as D

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile

from dataimport.reading import MAX_ROWS, ImportFileError, as_date, as_decimal, as_text, read_table
from dataimport.tests.helpers import csv_file, xlsx_file


def test_reads_xlsx_with_normalised_headers():
    rows = read_table(xlsx_file([["  First Name ", "ID Number"], ["Ahmed", 2123456789]]))
    assert rows == [{"first_name": "Ahmed", "id_number": 2123456789}]


def test_reads_csv_with_bom_and_arabic():
    rows = read_table(csv_file([["name", "name_ar"], ["Ahmed", "أحمد"]]))
    assert rows == [{"name": "Ahmed", "name_ar": "أحمد"}]


def test_empty_rows_are_skipped():
    rows = read_table(xlsx_file([["name"], ["A"], [None], [""], ["B"]]))
    assert [r["name"] for r in rows] == ["A", "B"]


def test_unsupported_file_type():
    with pytest.raises(ImportFileError):
        read_table(SimpleUploadedFile("data.pdf", b"%PDF"))


def test_corrupt_xlsx_is_reported_not_crashing():
    with pytest.raises(ImportFileError):
        read_table(SimpleUploadedFile("data.xlsx", b"not really excel"))


def test_too_many_rows():
    with pytest.raises(ImportFileError):
        read_table(csv_file([["name"]] + [[f"n{i}"] for i in range(MAX_ROWS + 1)]))


def test_file_without_header_row():
    with pytest.raises(ImportFileError):
        read_table(csv_file([]))


# --- value cleaning ------------------------------------------------------------------

@pytest.mark.parametrize(
    "value, expected",
    [
        (2045678904, "2045678904"),
        (2045678904.0, "2045678904"),          # Excel stores IDs as floats
        ("  text  ", "text"),
        (None, ""),
        (D("12.50"), "12.50"),
    ],
)
def test_as_text(value, expected):
    assert as_text(value) == expected


def test_as_text_restores_mobile_leading_zero():
    assert as_text(512345678, mobile=True) == "0512345678"
    assert as_text("0512345678", mobile=True) == "0512345678"


@pytest.mark.parametrize(
    "value, expected",
    [
        (dt.datetime(2024, 1, 31, 0, 0), dt.date(2024, 1, 31)),
        (dt.date(2024, 1, 31), dt.date(2024, 1, 31)),
        ("2024-01-31", dt.date(2024, 1, 31)),
        ("31/01/2024", dt.date(2024, 1, 31)),
        ("", None),
        (None, None),
    ],
)
def test_as_date(value, expected):
    assert as_date(value) == expected


@pytest.mark.parametrize("bad", ["31-31-2024", "yesterday", "2024/13/01"])
def test_as_date_rejects_garbage(bad):
    with pytest.raises(ValueError):
        as_date(bad)


@pytest.mark.parametrize("value, expected", [(5000, D("5000")), ("1,250.50", D("1250.50")), ("", None), (None, None)])
def test_as_decimal(value, expected):
    assert as_decimal(value) == expected


def test_as_decimal_rejects_garbage():
    with pytest.raises(ValueError):
        as_decimal("five thousand")


def test_csv_saved_by_arabic_windows_excel():
    data = "name,name_ar\r\nAhmed,أحمد\r\n".encode("cp1256")
    rows = read_table(SimpleUploadedFile("data.csv", data))
    assert rows == [{"name": "Ahmed", "name_ar": "أحمد"}]


@pytest.mark.parametrize("bad", ["NaN", "Infinity"])
def test_as_decimal_rejects_non_finite(bad):
    with pytest.raises(ValueError):
        as_decimal(bad)


def test_exactly_max_rows_is_allowed():
    rows = read_table(csv_file([["name"]] + [[f"n{i}"] for i in range(MAX_ROWS)]))
    assert len(rows) == MAX_ROWS


def test_whitespace_only_rows_are_skipped():
    rows = read_table(csv_file([["name", "city"], ["A", "Riyadh"], ["   ", " "], ["B", ""]]))
    assert [r["name"] for r in rows] == ["A", "B"]


def test_blank_header_cells_are_not_a_header():
    with pytest.raises(ImportFileError):
        read_table(csv_file([["", " "], ["A", "B"]]))
