"""Unit tests: Saudi-specific field validators (no database)."""

import pytest
from django.core.exceptions import ValidationError

from hr.tests.factories import make_saudi_iban
from hr.validators import (
    normalize_iban,
    validate_id_number,
    validate_saudi_iban,
    validate_saudi_mobile,
)

VALID_IBAN = "SA0380000000608010167519"


# --- IBAN -------------------------------------------------------------------

def test_known_valid_saudi_iban_passes():
    validate_saudi_iban(VALID_IBAN)


def test_generated_iban_with_alphanumeric_account_passes():
    validate_saudi_iban(make_saudi_iban(bank="10", account="ABC123456789012345"))


def test_iban_with_spaces_and_lowercase_passes():
    validate_saudi_iban("sa03 8000 0000 6080 1016 7519")


def test_normalize_iban_strips_spaces_and_uppercases():
    assert normalize_iban(" sa03 8000 0000 6080 1016 7519 ") == VALID_IBAN


@pytest.mark.parametrize(
    "bad",
    [
        "SA038000000060801016751",     # 23 chars, too short
        "SA03800000006080101675190",   # 25 chars, too long
        "AE0380000000608010167519",    # not a Saudi IBAN
        "SA0480000000608010167519",    # wrong check digits
        "SA0380000000608010167!19",    # illegal character
        "",
    ],
)
def test_invalid_iban_is_rejected(bad):
    with pytest.raises(ValidationError):
        validate_saudi_iban(bad)


# --- Mobile -----------------------------------------------------------------

def test_valid_saudi_mobile_passes():
    validate_saudi_mobile("0512345678")


@pytest.mark.parametrize(
    "bad", ["512345678", "0412345678", "05123456789", "+966512345678", "05-1234567"]
)
def test_invalid_saudi_mobile_is_rejected(bad):
    with pytest.raises(ValidationError):
        validate_saudi_mobile(bad)


# --- National ID / Iqama ------------------------------------------------------

@pytest.mark.parametrize("good", ["1234567890", "2234567890"])
def test_valid_id_number_passes(good):
    validate_id_number(good)


@pytest.mark.parametrize("bad", ["3234567890", "123456789", "12345678901", "12345abcde"])
def test_invalid_id_number_is_rejected(bad):
    with pytest.raises(ValidationError):
        validate_id_number(bad)
