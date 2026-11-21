"""Unit tests: shared Saudi validators."""

import pytest
from django.core.exceptions import ValidationError

from core.validators import validate_postal_code, validate_saudi_vat_number


def test_vat_number_shared_with_expenses():
    from expenses import validators as expense_validators

    assert expense_validators.validate_saudi_vat_number is validate_saudi_vat_number


def test_valid_vat_number():
    validate_saudi_vat_number("300000000000003")


@pytest.mark.parametrize("bad", ["200000000000003", "300000000000002", "30000000000003", ""])
def test_invalid_vat_number(bad):
    with pytest.raises(ValidationError):
        validate_saudi_vat_number(bad)


def test_valid_postal_code():
    validate_postal_code("12345")


@pytest.mark.parametrize("bad", ["1234", "123456", "1234a", ""])
def test_invalid_postal_code(bad):
    with pytest.raises(ValidationError):
        validate_postal_code(bad)
