"""Leave -> payroll: unpaid leave and sick-leave tiers (Labour Law Art. 117)
become salary deductions in the payslip month."""

import datetime as dt
from decimal import Decimal as D

import pytest
from django.urls import reverse

from expenses.tests.factories import UserFactory
from hr.tests.factories import EmployeeFactory
from leave.models import LeaveRequest
from leave.payroll import leave_deduction_days
from leave.tests.factories import make_request
from payroll.models import PayrollRun
from payroll.services import approve_run, generate_payslips
from payroll.tests.factories import SalaryStructureFactory

pytestmark = pytest.mark.django_db

S = LeaveRequest.Status
MARCH = (dt.date(2026, 3, 1), dt.date(2026, 3, 31))


@pytest.fixture
def emp():
    return EmployeeFactory(hire_date=dt.date(2015, 1, 1))


def approved(emp, code, start, end):
    return make_request(emp, code, start, end, status=S.APPROVED)


# --- unpaid leave ------------------------------------------------------------------

def test_no_leave_no_deduction(emp):
    assert leave_deduction_days(emp, *MARCH) == D("0.00")


def test_unpaid_leave_counts_calendar_days_in_the_month(emp):
    approved(emp, "UNPAID", dt.date(2026, 3, 5), dt.date(2026, 3, 7))     # Thu-Sat: 3 calendar days
    assert leave_deduction_days(emp, *MARCH) == D("3.00")


def test_unpaid_leave_spanning_two_months_is_split(emp):
    approved(emp, "UNPAID", dt.date(2026, 3, 30), dt.date(2026, 4, 2))
    assert leave_deduction_days(emp, *MARCH) == D("2.00")
    assert leave_deduction_days(emp, dt.date(2026, 4, 1), dt.date(2026, 4, 30)) == D("2.00")


def test_only_approved_leave_is_deducted(emp):
    make_request(emp, "UNPAID", dt.date(2026, 3, 5), dt.date(2026, 3, 6), status=S.PENDING)
    make_request(emp, "UNPAID", dt.date(2026, 3, 10), dt.date(2026, 3, 11), status=S.REJECTED)
    make_request(emp, "UNPAID", dt.date(2026, 3, 15), dt.date(2026, 3, 16), status=S.CANCELLED)
    assert leave_deduction_days(emp, *MARCH) == D("0.00")


def test_paid_leave_is_not_deducted(emp):
    approved(emp, "ANNUAL", dt.date(2026, 3, 1), dt.date(2026, 3, 12))
    approved(emp, "MARRIAGE", dt.date(2026, 3, 15), dt.date(2026, 3, 19))
    assert leave_deduction_days(emp, *MARCH) == D("0.00")


def test_other_employees_leave_is_ignored(emp):
    approved(EmployeeFactory(), "UNPAID", dt.date(2026, 3, 5), dt.date(2026, 3, 7))
    assert leave_deduction_days(emp, *MARCH) == D("0.00")


# --- sick leave tiers (Art. 117) ------------------------------------------------------

def test_first_30_sick_days_are_fully_paid(emp):
    approved(emp, "SICK", dt.date(2026, 3, 1), dt.date(2026, 3, 30))
    assert leave_deduction_days(emp, *MARCH) == D("0.00")


def test_sick_days_31_to_90_lose_a_quarter_of_the_day(emp):
    approved(emp, "SICK", dt.date(2026, 1, 1), dt.date(2026, 2, 15))      # 46 days
    jan = leave_deduction_days(emp, dt.date(2026, 1, 1), dt.date(2026, 1, 31))
    feb = leave_deduction_days(emp, dt.date(2026, 2, 1), dt.date(2026, 2, 28))
    assert jan == D("0.25")                                              # day 31
    assert feb == D("3.75")                                              # days 32-46: 15 x 0.25


def test_sick_days_after_90_are_unpaid(emp):
    approved(emp, "SICK", dt.date(2025, 10, 1), dt.date(2025, 12, 29))   # 90 days
    approved(emp, "SICK", dt.date(2026, 3, 1), dt.date(2026, 3, 3))      # days 91-93
    assert leave_deduction_days(emp, *MARCH) == D("3.00")


def test_sick_days_older_than_a_year_do_not_count(emp):
    approved(emp, "SICK", dt.date(2024, 11, 1), dt.date(2025, 1, 29))    # 90 days, long ago
    approved(emp, "SICK", dt.date(2026, 3, 1), dt.date(2026, 3, 3))
    assert leave_deduction_days(emp, *MARCH) == D("0.00")


def test_unpaid_and_sick_add_up(emp):
    approved(emp, "SICK", dt.date(2025, 12, 1), dt.date(2026, 2, 28))    # 90 days before March
    approved(emp, "SICK", dt.date(2026, 3, 1), dt.date(2026, 3, 2))      # 2 unpaid sick days
    approved(emp, "UNPAID", dt.date(2026, 3, 10), dt.date(2026, 3, 12))  # 3 days
    assert leave_deduction_days(emp, *MARCH) == D("5.00")


# --- payroll integration --------------------------------------------------------------

def run_for(year, month):
    return PayrollRun.objects.create(year=year, month=month)


def test_payslip_deducts_unpaid_leave(emp):
    SalaryStructureFactory(employee=emp)                  # gross 7,200 -> 240 a day
    approved(emp, "UNPAID", dt.date(2026, 3, 5), dt.date(2026, 3, 7))
    run = run_for(2026, 3)
    generate_payslips(run)

    slip = run.payslips.get()
    assert slip.leave_days == D("3.00")
    assert slip.absence == D("720.00")
    assert slip.net == D("6480.00")


def test_leave_approved_after_generation_is_picked_up_at_approval(emp):
    SalaryStructureFactory(employee=emp)
    run = run_for(2026, 3)
    generate_payslips(run)
    approved(emp, "UNPAID", dt.date(2026, 3, 5), dt.date(2026, 3, 5))

    approve_run(run, UserFactory())

    assert run.payslips.get().leave_days == D("1.00")


def test_total_unpaid_days_never_exceed_30(emp):
    SalaryStructureFactory(employee=emp)
    approved(emp, "UNPAID", dt.date(2026, 3, 1), dt.date(2026, 3, 31))  # 31 calendar days
    run = run_for(2026, 3)
    generate_payslips(run)
    slip = run.payslips.get()
    assert slip.absence == D("7200.00") and slip.net == D("0.00")


def test_payslip_page_shows_leave_days(admin_client, emp):
    SalaryStructureFactory(employee=emp)
    approved(emp, "UNPAID", dt.date(2026, 3, 5), dt.date(2026, 3, 7))
    run = run_for(2026, 3)
    generate_payslips(run)
    slip = run.payslips.get()

    html = admin_client.get(reverse("payroll:payslip_detail", args=[slip.pk])).content.decode()
    assert "3.00" in html and "Unpaid leave" in html
    run_html = admin_client.get(reverse("payroll:run_detail", args=[run.pk])).content.decode()
    assert "3.00" in run_html
