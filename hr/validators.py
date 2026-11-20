"""Validators for Saudi-specific HR data."""

import re

from django.core.exceptions import ValidationError
from django.utils.translation import gettext_lazy as _

# Saudi IBAN: "SA" + 2 check digits + 2-digit bank code + 18 alphanumeric account.
_SAUDI_IBAN_RE = re.compile(r"^SA\d{2}\d{2}[A-Z0-9]{18}$")
_SAUDI_MOBILE_RE = re.compile(r"^05\d{8}$")
# National ID (Saudi) starts with 1, Iqama (resident) starts with 2; 10 digits.
_ID_NUMBER_RE = re.compile(r"^[12]\d{9}$")


def normalize_iban(value: str) -> str:
    return (value or "").replace(" ", "").upper()


def _iban_checksum_ok(iban: str) -> bool:
    rearranged = iban[4:] + iban[:4]
    digits = "".join(str(int(ch, 36)) for ch in rearranged)
    return int(digits) % 97 == 1


def validate_saudi_iban(value: str) -> None:
    iban = normalize_iban(value)
    if not _SAUDI_IBAN_RE.match(iban) or not _iban_checksum_ok(iban):
        raise ValidationError(
            _("Enter a valid Saudi IBAN (SA followed by 22 characters)."),
            code="invalid_iban",
        )


def validate_saudi_mobile(value: str) -> None:
    if not _SAUDI_MOBILE_RE.match(value or ""):
        raise ValidationError(
            _("Enter a Saudi mobile number in the format 05XXXXXXXX."),
            code="invalid_mobile",
        )


def validate_id_number(value: str) -> None:
    if not _ID_NUMBER_RE.match(value or ""):
        raise ValidationError(
            _("ID must be 10 digits starting with 1 (National ID) or 2 (Iqama)."),
            code="invalid_id_number",
        )
