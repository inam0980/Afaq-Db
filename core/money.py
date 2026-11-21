"""Money helpers shared by every module. All amounts are Decimal SAR."""

from decimal import ROUND_HALF_UP, Decimal

CENT = Decimal("0.01")


def money(value) -> Decimal:
    """Round to halalas (2 places), half-up — the convention on Saudi invoices."""
    return Decimal(str(value)).quantize(CENT, rounding=ROUND_HALF_UP)
