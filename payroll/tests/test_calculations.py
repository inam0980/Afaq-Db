"""Unit tests: pure payroll math (no database).

Rules implemented (Saudi Labour Law / GOSI):
- Daily wage = monthly / 30, hourly wage = monthly / 30 / 8.
- Overtime (Art. 107): per hour = full hourly wage + 50% of basic hourly wage.
- Absence: full daily wage (basic + allowances) per absent day.
- GOSI base = basic + housing, capped (default SAR 45,000).
- EOSB (Art. 84): half a month per year for the first 5 years, a full month
  per year after that, pro-rata by days. Resignation (Art. 85): <2 years none,
  2-5 years 1/3, 5-10 years 2/3, 10+ years full.
"""

import datetime as dt
from decimal import Decimal as D
from types import SimpleNamespace

import pytest

from payroll.calculations import (
    EosbReason,
    absence_deduction,
    calculate_eosb,
    compute_payslip,
    gosi_contribution,
    hourly_rate,
    money,
    overtime_amount,
)

SAUDI_RATE = SimpleNamespace(employee_rate=D("9.75"), employer_rate=D("11.75"), salary_cap=D("45000"))
EXPAT_RATE = SimpleNamespace(employee_rate=D("0"), employer_rate=D("2"), salary_cap=D("45000"))


def years_later(start, years, extra_days=0):
    return start + dt.timedelta(days=365 * years + extra_days)


# --- helpers -----------------------------------------------------------------

def test_money_rounds_half_up_to_two_places():
    assert money("10.005") == D("10.01")
    assert money("10.004") == D("10.00")
    assert money(3) == D("3.00")


def test_hourly_rate_is_monthly_over_240_hours():
    assert hourly_rate(D("2400")) == D("10")


# --- overtime ----------------------------------------------------------------

def test_overtime_is_full_hourly_plus_half_basic_hourly():
    # gross 7200 -> 30/h, basic 4800 -> 20/h, half = 10/h => 40/h
    assert overtime_amount(basic=D("4800"), gross_fixed=D("7200"), hours=D("10")) == D("400.00")


def test_overtime_zero_hours_is_zero():
    assert overtime_amount(basic=D("4800"), gross_fixed=D("7200"), hours=D("0")) == D("0.00")


def test_overtime_negative_hours_rejected():
    with pytest.raises(ValueError):
        overtime_amount(basic=D("4800"), gross_fixed=D("7200"), hours=D("-1"))


# --- absence -----------------------------------------------------------------

def test_absence_deducts_full_daily_wage():
    assert absence_deduction(gross_fixed=D("6000"), days=D("3")) == D("600.00")


@pytest.mark.parametrize("days", [D("-1"), D("31")])
def test_absence_days_out_of_range_rejected(days):
    with pytest.raises(ValueError):
        absence_deduction(gross_fixed=D("6000"), days=days)


# --- GOSI --------------------------------------------------------------------

def test_gosi_saudi_on_basic_plus_housing():
    employee, employer = gosi_contribution(basic=D("10000"), housing=D("2500"), rate=SAUDI_RATE)
    assert employee == D("1218.75")   # 12,500 x 9.75%
    assert employer == D("1468.75")   # 12,500 x 11.75%


def test_gosi_base_is_capped():
    employee, employer = gosi_contribution(basic=D("50000"), housing=D("12500"), rate=SAUDI_RATE)
    assert employee == D("4387.50")   # 45,000 x 9.75%
    assert employer == D("5287.50")   # 45,000 x 11.75%


def test_gosi_non_saudi_employer_hazards_only():
    employee, employer = gosi_contribution(basic=D("10000"), housing=D("2500"), rate=EXPAT_RATE)
    assert employee == D("0.00")
    assert employer == D("250.00")


# --- End of service benefit ----------------------------------------------------

START = dt.date(2015, 1, 1)
WAGE = D("10000")


@pytest.mark.parametrize(
    "years, expected",
    [
        (3, D("15000.00")),    # 3 x 0.5
        (5, D("25000.00")),    # 5 x 0.5
        (7, D("45000.00")),    # 5 x 0.5 + 2 x 1
    ],
)
def test_eosb_on_termination(years, expected):
    end = years_later(START, years)
    assert calculate_eosb(WAGE, START, end, EosbReason.TERMINATION) == expected


def test_eosb_is_pro_rata_for_partial_years():
    end = START + dt.timedelta(days=548)   # 548/365 years
    assert calculate_eosb(WAGE, START, end, EosbReason.TERMINATION) == D("7506.85")


@pytest.mark.parametrize(
    "years, expected",
    [
        (1, D("0.00")),        # < 2 years: nothing
        (3, D("5000.00")),     # 1/3 of 15,000
        (7, D("30000.00")),    # 2/3 of 45,000
        (12, D("95000.00")),   # full: 5 x 0.5 + 7 x 1 = 9.5 months
    ],
)
def test_eosb_on_resignation(years, expected):
    end = years_later(START, years)
    assert calculate_eosb(WAGE, START, end, EosbReason.RESIGNATION) == expected


@pytest.mark.parametrize("extra_days, expected", [(-1, D("0.00")), (0, D("3333.33"))])
def test_eosb_resignation_two_year_boundary(extra_days, expected):
    end = years_later(START, 2, extra_days)
    assert calculate_eosb(WAGE, START, end, EosbReason.RESIGNATION) == expected


@pytest.mark.parametrize(
    "years, extra_days, fraction",
    [(5, -1, D(1) / 3), (5, 0, D(2) / 3), (10, -1, D(2) / 3), (10, 0, D(1))],
)
def test_eosb_resignation_five_and_ten_year_boundaries(years, extra_days, fraction):
    end = years_later(START, years, extra_days)
    full = calculate_eosb(WAGE, START, end, EosbReason.TERMINATION)
    assert calculate_eosb(WAGE, START, end, EosbReason.RESIGNATION) == money(full * fraction)


def test_eosb_end_before_start_rejected():
    with pytest.raises(ValueError):
        calculate_eosb(WAGE, START, START - dt.timedelta(days=1), EosbReason.TERMINATION)


# --- Payslip -----------------------------------------------------------------

STRUCTURE = SimpleNamespace(
    basic=D("4800"), housing=D("1200"), transport=D("600"), other=D("600")
)


def test_compute_payslip_full_example():
    slip = compute_payslip(
        STRUCTURE,
        SAUDI_RATE,
        overtime_hours=D("10"),
        absence_days=D("1"),
        additions=D("100"),
        deductions=D("50"),
    )

    assert slip.gross_fixed == D("7200.00")
    assert slip.overtime == D("400.00")
    assert slip.absence == D("240.00")
    assert slip.gosi_employee == D("585.00")     # (4800 + 1200) x 9.75%
    assert slip.gosi_employer == D("705.00")     # (4800 + 1200) x 11.75%
    assert slip.gross == D("7700.00")            # 7200 + 400 + 100
    assert slip.total_deductions == D("875.00")  # 240 + 50 + 585
    assert slip.net == D("6825.00")


def test_compute_payslip_defaults_to_fixed_salary_minus_gosi():
    slip = compute_payslip(STRUCTURE, EXPAT_RATE)
    assert slip.gross == D("7200.00")
    assert slip.net == D("7200.00")
    assert slip.gosi_employer == D("120.00")     # 6000 x 2%


def test_compute_payslip_negative_net_rejected():
    with pytest.raises(ValueError):
        compute_payslip(STRUCTURE, EXPAT_RATE, deductions=D("8000"))
