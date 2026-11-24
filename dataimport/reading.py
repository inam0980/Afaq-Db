"""Reading uploaded spreadsheets (.xlsx / .csv) into plain row dicts, plus the
value cleaning needed for files that went through Excel: IDs stored as
floats, mobiles that lost their leading zero, dates as datetimes or text."""

import csv
import datetime as dt
import io
import re
from decimal import Decimal, InvalidOperation

from django.utils.translation import gettext as _
from openpyxl import load_workbook

MAX_ROWS = 2000
MAX_BYTES = 2 * 1024 * 1024
EXTENSIONS = (".xlsx", ".csv")
DATE_FORMATS = ("%Y-%m-%d", "%d/%m/%Y", "%Y-%m-%d %H:%M:%S")


class ImportFileError(Exception):
    """The file itself cannot be used (wrong type, corrupt, too big, empty)."""


def normalise_header(value) -> str:
    return re.sub(r"\s+", "_", str(value or "").strip().lower())


def _is_blank(value) -> bool:
    return value is None or (isinstance(value, str) and not value.strip())


def _xlsx_rows(uploaded):
    try:
        workbook = load_workbook(uploaded, read_only=True, data_only=True)
    except Exception as exc:     # openpyxl raises many types for a damaged/fake file
        raise ImportFileError(_("This is not a readable Excel (.xlsx) file.")) from exc
    try:
        yield from workbook.active.iter_rows(values_only=True)
    finally:
        workbook.close()


def _csv_rows(uploaded):
    raw = uploaded.read()
    try:
        text = raw.decode("utf-8-sig")
    except UnicodeDecodeError:
        text = raw.decode("cp1256", errors="replace")      # Arabic Windows "Save as CSV"
    yield from csv.reader(io.StringIO(text))


def read_table(uploaded) -> list[dict]:
    """Return the data rows as dicts keyed by normalised header (first row)."""
    name = (uploaded.name or "").lower()
    if not name.endswith(EXTENSIONS):
        raise ImportFileError(_("Upload an Excel (.xlsx) or CSV file."))
    rows = iter(_xlsx_rows(uploaded) if name.endswith(".xlsx") else _csv_rows(uploaded))

    header = next(rows, None)
    if not header or all(_is_blank(h) for h in header):
        raise ImportFileError(_("The first row must contain the column names."))
    keys = [normalise_header(h) for h in header]

    result = []
    for values in rows:
        if all(_is_blank(v) for v in values):
            continue
        if len(result) == MAX_ROWS:
            raise ImportFileError(
                _("Too many rows: the limit is %(limit)s per file. Split the file and import it in parts.")
                % {"limit": MAX_ROWS}
            )
        result.append({k: v for k, v in zip(keys, values) if k})
    return result


# --- value cleaning ----------------------------------------------------------------

def as_text(value, mobile: bool = False) -> str:
    if value is None:
        return ""
    if isinstance(value, float) and value.is_integer():
        value = int(value)
    text = str(value).strip()
    if mobile and len(text) == 9 and text.startswith("5"):
        text = "0" + text                      # Excel dropped the leading zero
    return text


def as_date(value) -> dt.date | None:
    if isinstance(value, dt.datetime):
        return value.date()
    if isinstance(value, dt.date):
        return value
    text = as_text(value)
    if not text:
        return None
    for fmt in DATE_FORMATS:
        try:
            return dt.datetime.strptime(text, fmt).date()
        except ValueError:
            continue
    raise ValueError(text)


def as_decimal(value) -> Decimal | None:
    text = as_text(value).replace(",", "")
    if not text:
        return None
    try:
        number = Decimal(text)
    except InvalidOperation as exc:
        raise ValueError(text) from exc
    if not number.is_finite():
        raise ValueError(text)
    return number
