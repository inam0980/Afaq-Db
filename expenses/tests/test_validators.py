"""Unit tests: VAT split and Saudi-specific validators (no database)."""

from decimal import Decimal as D

import pytest
from django.core.exceptions import ValidationError
from django.core.files.uploadedfile import SimpleUploadedFile

from expenses.validators import (
    MAX_RECEIPT_BYTES,
    split_vat,
    validate_receipt_file,
    validate_saudi_vat_number,
)


# --- VAT split (receipts show the VAT-inclusive total) -----------------------------

@pytest.mark.parametrize(
    "total, rate, excl, vat",
    [
        (D("115"), D("15"), D("100.00"), D("15.00")),
        (D("10"), D("15"), D("8.70"), D("1.30")),       # 1.3043 -> 1.30
        (D("100"), D("0"), D("100.00"), D("0.00")),
        (D("0.01"), D("15"), D("0.01"), D("0.00")),
    ],
)
def test_split_vat(total, rate, excl, vat):
    assert split_vat(total, rate) == (excl, vat)


@pytest.mark.parametrize("total", [D("0.01"), D("9.99"), D("1234.56"), D("99999.99")])
def test_split_vat_parts_always_add_up_to_total(total):
    excl, vat = split_vat(total, D("15"))
    assert excl + vat == total


# --- Saudi VAT registration number ---------------------------------------------------

def test_valid_vat_number():
    validate_saudi_vat_number("300000000000003")
    validate_saudi_vat_number("312345678900003")


@pytest.mark.parametrize(
    "bad",
    [
        "200000000000003",    # must start with 3
        "300000000000002",    # must end with 3
        "30000000000003",     # 14 digits
        "3000000000000003",   # 16 digits
        "30000000000000A",
        "",
    ],
)
def test_invalid_vat_number(bad):
    with pytest.raises(ValidationError):
        validate_saudi_vat_number(bad)


# --- Receipt upload ----------------------------------------------------------------

@pytest.mark.parametrize("name", ["bill.pdf", "photo.JPG", "scan.jpeg", "shot.png"])
def test_allowed_receipt_types(name):
    validate_receipt_file(SimpleUploadedFile(name, b"x"))


@pytest.mark.parametrize("name", ["virus.exe", "page.html", "notes.txt", "noext"])
def test_disallowed_receipt_types(name):
    with pytest.raises(ValidationError):
        validate_receipt_file(SimpleUploadedFile(name, b"x"))


def test_receipt_size_limit():
    validate_receipt_file(SimpleUploadedFile("ok.pdf", b"x" * MAX_RECEIPT_BYTES))
    with pytest.raises(ValidationError):
        validate_receipt_file(SimpleUploadedFile("big.pdf", b"x" * (MAX_RECEIPT_BYTES + 1)))
