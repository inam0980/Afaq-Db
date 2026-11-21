"""Saudi-specific validators shared by several modules."""

import re

from django.core.exceptions import ValidationError
from django.utils.translation import gettext_lazy as _

# ZATCA VAT registration number: 15 digits, starts and ends with 3.
_VAT_NUMBER_RE = re.compile(r"^3\d{13}3$")
# Saudi National Address: 5-digit postal code, 4-digit building number.
_POSTAL_CODE_RE = re.compile(r"^\d{5}$")
_BUILDING_NUMBER_RE = re.compile(r"^\d{4}$")


def validate_saudi_vat_number(value: str) -> None:
    if not _VAT_NUMBER_RE.match(value or ""):
        raise ValidationError(
            _("A Saudi VAT number has 15 digits and starts and ends with 3."),
            code="invalid_vat_number",
        )


def validate_postal_code(value: str) -> None:
    if not _POSTAL_CODE_RE.match(value or ""):
        raise ValidationError(_("Postal code must be 5 digits."), code="invalid_postal_code")


def validate_building_number(value: str) -> None:
    if not _BUILDING_NUMBER_RE.match(value or ""):
        raise ValidationError(_("Building number must be 4 digits."), code="invalid_building_number")
