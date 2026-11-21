"""VAT split and Saudi-specific validators for expenses."""

from decimal import Decimal
from pathlib import Path

from django.core.exceptions import ValidationError
from django.utils.translation import gettext_lazy as _

from core.money import money
from core.validators import validate_saudi_vat_number  # noqa: F401  (re-exported)

ALLOWED_RECEIPT_EXTENSIONS = {".pdf", ".jpg", ".jpeg", ".png"}
MAX_RECEIPT_BYTES = 5 * 1024 * 1024


def split_vat(total: Decimal, rate: Decimal) -> tuple[Decimal, Decimal]:
    """Split a VAT-inclusive total into (amount excl. VAT, VAT).
    The two parts always add up exactly to the total."""
    total = money(total)
    vat = money(total * rate / (100 + rate))
    return total - vat, vat


def validate_receipt_file(file) -> None:
    if Path(file.name).suffix.lower() not in ALLOWED_RECEIPT_EXTENSIONS:
        raise ValidationError(
            _("Upload a PDF, JPG or PNG receipt."), code="invalid_receipt_type"
        )
    if file.size > MAX_RECEIPT_BYTES:
        raise ValidationError(_("Receipt must be 5 MB or smaller."), code="receipt_too_large")
