"""Pure payroll calculations (no database). All money is Decimal, SAR.

Rules (Saudi Labour Law / GOSI) — see payroll/tests/test_calculations.py:
- Daily wage = monthly / 30; hourly wage = monthly / 30 / 8.
- Overtime (Art. 107): full hourly wage + 50% of basic hourly wage, per hour.
- Absence: full daily wage per absent day.
- GOSI base = basic + housing, capped at the rate's salary_cap.
- EOSB (Art. 84/85): see calculate_eosb.
"""

import datetime as dt
from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal

from django.db import models
from django.utils.translation import gettext_lazy as _

CENT = Decimal("0.01")
DAYS_PER_MONTH = Decimal(30)
HOURS_PER_DAY = Decimal(8)
DAYS_PER_YEAR = Decimal(365)
ZERO = Decimal(0)


def money(value) -> Decimal:
    return Decimal(str(value)).quantize(CENT, rounding=ROUND_HALF_UP)


def daily_rate(monthly: Decimal) -> Decimal:
    return monthly / DAYS_PER_MONTH


def hourly_rate(monthly: Decimal) -> Decimal:
    return monthly / DAYS_PER_MONTH / HOURS_PER_DAY


def overtime_amount(*, basic: Decimal, gross_fixed: Decimal, hours: Decimal) -> Decimal:
    if hours < 0:
        raise ValueError("Overtime hours cannot be negative.")
    per_hour = hourly_rate(gross_fixed) + hourly_rate(basic) / 2
    return money(per_hour * hours)


def absence_deduction(*, gross_fixed: Decimal, days: Decimal) -> Decimal:
    if not 0 <= days <= DAYS_PER_MONTH:
        raise ValueError("Absence days must be between 0 and 30.")
    return money(daily_rate(gross_fixed) * days)


def gosi_contribution(*, basic: Decimal, housing: Decimal, rate) -> tuple[Decimal, Decimal]:
    """Return (employee share, employer share). `rate` has percentages
    employee_rate / employer_rate and a salary_cap."""
    base = min(basic + housing, rate.salary_cap)
    return (
        money(base * rate.employee_rate / 100),
        money(base * rate.employer_rate / 100),
    )


# --- End of service benefit ----------------------------------------------------

class EosbReason(models.TextChoices):
    TERMINATION = "termination", _("Termination by employer / contract end")
    RESIGNATION = "resignation", _("Resignation")


_FIRST_TIER_DAYS = 5 * 365


def _resignation_fraction(service_days: int) -> Decimal:
    if service_days < 2 * 365:
        return ZERO
    if service_days < 5 * 365:
        return Decimal(1) / 3
    if service_days < 10 * 365:
        return Decimal(2) / 3
    return Decimal(1)


def calculate_eosb(
    monthly_wage: Decimal, start: dt.date, end: dt.date, reason: str
) -> Decimal:
    """Art. 84: half a month's wage per year for the first five years, one
    month's wage per year after that, pro-rata by days (365-day years).
    Art. 85 (resignation): <2y none, 2-5y one third, 5-10y two thirds, 10y+ full.
    """
    if end < start:
        raise ValueError("End date cannot be before start date.")
    service_days = (end - start).days

    first_tier = min(service_days, _FIRST_TIER_DAYS)
    second_tier = service_days - first_tier
    full = money(
        monthly_wage / 2 * first_tier / DAYS_PER_YEAR
        + monthly_wage * second_tier / DAYS_PER_YEAR
    )

    if reason == EosbReason.RESIGNATION:
        return money(full * _resignation_fraction(service_days))
    return full


# --- Payslip -----------------------------------------------------------------

@dataclass(frozen=True)
class PayslipResult:
    basic: Decimal
    housing: Decimal
    transport: Decimal
    other: Decimal
    gross_fixed: Decimal
    overtime: Decimal
    additions: Decimal
    absence: Decimal
    deductions: Decimal
    gosi_employee: Decimal
    gosi_employer: Decimal
    gross: Decimal
    total_deductions: Decimal
    net: Decimal


def compute_payslip(
    structure,
    rate,
    *,
    overtime_hours: Decimal = ZERO,
    absence_days: Decimal = ZERO,
    additions: Decimal = ZERO,
    deductions: Decimal = ZERO,
) -> PayslipResult:
    """`structure` has basic/housing/transport/other; `rate` is a GOSI rate."""
    gross_fixed = money(
        structure.basic + structure.housing + structure.transport + structure.other
    )
    overtime = overtime_amount(basic=structure.basic, gross_fixed=gross_fixed, hours=overtime_hours)
    absence = absence_deduction(gross_fixed=gross_fixed, days=absence_days)
    gosi_employee, gosi_employer = gosi_contribution(
        basic=structure.basic, housing=structure.housing, rate=rate
    )

    gross = money(gross_fixed + overtime + additions)
    total_deductions = money(absence + deductions + gosi_employee)
    net = money(gross - total_deductions)
    if net < 0:
        raise ValueError("Deductions exceed gross pay; net salary would be negative.")

    return PayslipResult(
        basic=money(structure.basic),
        housing=money(structure.housing),
        transport=money(structure.transport),
        other=money(structure.other),
        gross_fixed=gross_fixed,
        overtime=overtime,
        additions=money(additions),
        absence=absence,
        deductions=money(deductions),
        gosi_employee=gosi_employee,
        gosi_employer=gosi_employer,
        gross=gross,
        total_deductions=total_deductions,
        net=net,
    )
