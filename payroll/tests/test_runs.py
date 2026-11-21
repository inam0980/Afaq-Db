"""Unit tests: payroll run lifecycle, payslip generation, pro-rata, locking.

Rules:
- Eligible: hired on/before the last day of the month and not terminated
  before the first day of the month.
- Paid days = calendar days employed in the month, max 30; a full month is 30.
  Days not employed are deducted like unpaid absence.
- The salary structure in force on the last day of the month is used.
- Once a run is APPROVED nothing in it can change (or be deleted).
"""

import datetime as dt
from decimal import Decimal as D

import pytest
from django.core.exceptions import ValidationError
from django.db import IntegrityError

from hr.models import Employee
from hr.tests.factories import EmployeeFactory
from payroll.models import PayrollLocked, PayrollRun, Payslip
from payroll.services import (
    approve_run,
    generate_payslips,
    mark_paid,
    missing_structures,
    paid_days,
    update_payslip_inputs,
)
from payroll.tests.factories import PayrollRunFactory, SalaryStructureFactory

pytestmark = pytest.mark.django_db

JAN = dict(year=2026, month=1)


def employee_with_salary(**emp_kwargs):
    emp = EmployeeFactory(**emp_kwargs)
    SalaryStructureFactory(employee=emp)   # gross 7,200; expat GOSI employer 2%
    return emp


# --- PayrollRun basics ----------------------------------------------------------

def test_period_dates_handle_leap_february():
    run = PayrollRunFactory(year=2028, month=2)
    assert run.period_start == dt.date(2028, 2, 1)
    assert run.period_end == dt.date(2028, 2, 29)


def test_run_str_is_year_month():
    assert str(PayrollRunFactory.build(year=2026, month=3)) == "2026-03"


def test_one_run_per_month():
    PayrollRun.objects.create(**JAN)
    with pytest.raises(IntegrityError):
        PayrollRun.objects.create(**JAN)


@pytest.mark.parametrize("month", [0, 13])
def test_month_must_be_1_to_12(month):
    with pytest.raises(ValidationError):
        PayrollRun(year=2026, month=month).full_clean()


def test_new_run_is_draft():
    assert PayrollRunFactory().status == PayrollRun.Status.DRAFT


# --- paid days ----------------------------------------------------------------

@pytest.mark.parametrize(
    "hire, termination, expected",
    [
        (dt.date(2020, 1, 1), None, 30),                    # full 31-day month
        (dt.date(2026, 1, 16), None, 16),                   # joined 16th: 16..31
        (dt.date(2020, 1, 1), dt.date(2026, 1, 10), 10),    # left 10th: 1..10
        (dt.date(2026, 1, 5), dt.date(2026, 1, 14), 10),    # joined and left
        (dt.date(2026, 1, 1), dt.date(2026, 1, 31), 30),    # exactly the month
    ],
)
def test_paid_days(hire, termination, expected):
    status = Employee.Status.TERMINATED if termination else Employee.Status.ACTIVE
    emp = EmployeeFactory.build(hire_date=hire, termination_date=termination, status=status)
    assert paid_days(emp, PayrollRunFactory.build(**JAN)) == expected


def test_full_february_is_30_paid_days():
    emp = EmployeeFactory.build(hire_date=dt.date(2020, 1, 1))
    assert paid_days(emp, PayrollRunFactory.build(year=2026, month=2)) == 30


# --- generation ---------------------------------------------------------------

def test_generate_creates_payslip_with_calculated_values():
    emp = employee_with_salary()
    run = PayrollRunFactory()

    result = generate_payslips(run)

    slip = run.payslips.get()
    assert result.created == 1
    assert slip.employee == emp
    assert slip.gross_fixed == D("7200.00")
    assert slip.gosi_employer == D("120.00")
    assert slip.net == D("7200.00")
    assert slip.iban == emp.iban


def test_generate_skips_ineligible_employees():
    employee_with_salary(hire_date=dt.date(2026, 2, 1))                      # joins later
    employee_with_salary(                                                   # left before
        termination_date=dt.date(2025, 12, 31), status=Employee.Status.TERMINATED
    )
    run = PayrollRunFactory()

    assert generate_payslips(run).created == 0


def test_generate_reports_employees_without_salary_structure():
    no_salary = EmployeeFactory()
    run = PayrollRunFactory()

    result = generate_payslips(run)

    assert result.created == 0
    assert result.skipped == [no_salary]
    assert missing_structures(run) == [no_salary]


def test_generate_is_idempotent():
    employee_with_salary()
    run = PayrollRunFactory()
    generate_payslips(run)

    assert generate_payslips(run).created == 0
    assert run.payslips.count() == 1


def test_structure_in_force_at_month_end_is_used():
    emp = employee_with_salary()
    SalaryStructureFactory(employee=emp, effective_from=dt.date(2026, 1, 15), basic=D("6000"))
    run = PayrollRunFactory()

    generate_payslips(run)

    assert run.payslips.get().basic == D("6000.00")


def test_joiner_is_paid_pro_rata():
    employee_with_salary(hire_date=dt.date(2026, 1, 16))
    run = PayrollRunFactory()

    generate_payslips(run)

    slip = run.payslips.get()
    assert slip.days_not_employed == 14
    assert slip.absence == D("3360.00")     # 14 x 240
    assert slip.net == D("3840.00")


def test_saudi_employee_pays_gosi():
    employee_with_salary(nationality="SA", id_number="1000000001")
    run = PayrollRunFactory()

    generate_payslips(run)

    slip = run.payslips.get()
    assert slip.gosi_employee == D("585.00")
    assert slip.net == D("6615.00")


# --- inputs -------------------------------------------------------------------

def test_update_inputs_recalculates():
    employee_with_salary()
    run = PayrollRunFactory()
    generate_payslips(run)
    slip = run.payslips.get()

    update_payslip_inputs(
        slip, overtime_hours=D("10"), absence_days=D("1"), additions=D("100"), deductions=D("50")
    )

    slip.refresh_from_db()
    assert slip.overtime == D("400.00")
    assert slip.absence == D("240.00")
    assert slip.net == D("7410.00")      # 7200 + 400 + 100 - 240 - 50
    assert slip.history.count() == 2


def test_absence_plus_days_not_employed_cannot_exceed_30():
    employee_with_salary(hire_date=dt.date(2026, 1, 16))   # 14 days not employed
    run = PayrollRunFactory()
    generate_payslips(run)

    with pytest.raises(ValidationError) as exc:
        update_payslip_inputs(run.payslips.get(), absence_days=D("17"))
    assert "absence_days" in exc.value.message_dict


def test_deductions_larger_than_pay_rejected():
    employee_with_salary()
    run = PayrollRunFactory()
    generate_payslips(run)

    with pytest.raises(ValidationError) as exc:
        update_payslip_inputs(run.payslips.get(), deductions=D("9000"))
    assert "deductions" in exc.value.message_dict


# --- approval & locking -------------------------------------------------------

def test_approve_sets_status_and_user(admin_user):
    employee_with_salary()
    run = PayrollRunFactory()
    generate_payslips(run)

    approve_run(run, admin_user)

    run.refresh_from_db()
    assert run.status == PayrollRun.Status.APPROVED
    assert run.approved_by == admin_user
    assert run.approved_at is not None


def test_cannot_approve_empty_run(admin_user):
    with pytest.raises(ValidationError):
        approve_run(PayrollRunFactory(), admin_user)


def test_cannot_approve_twice(admin_user):
    employee_with_salary()
    run = PayrollRunFactory()
    generate_payslips(run)
    approve_run(run, admin_user)

    with pytest.raises(PayrollLocked):
        approve_run(run, admin_user)


def test_approve_recalculates_with_latest_structure(admin_user):
    emp = employee_with_salary()
    run = PayrollRunFactory()
    generate_payslips(run)
    SalaryStructureFactory(employee=emp, effective_from=dt.date(2026, 1, 20), basic=D("6000"))

    approve_run(run, admin_user)

    assert run.payslips.get().basic == D("6000.00")


@pytest.fixture
def approved_run(admin_user):
    employee_with_salary()
    run = PayrollRunFactory()
    generate_payslips(run)
    approve_run(run, admin_user)
    run.refresh_from_db()
    return run


def test_approved_payslip_inputs_locked(approved_run):
    with pytest.raises(PayrollLocked):
        update_payslip_inputs(approved_run.payslips.get(), overtime_hours=D("5"))


def test_approved_payslip_cannot_be_saved(approved_run):
    slip = approved_run.payslips.get()
    slip.net = D("1")
    with pytest.raises(PayrollLocked):
        slip.save()


def test_approved_run_cannot_be_deleted(approved_run):
    with pytest.raises(PayrollLocked):
        approved_run.delete()
    assert PayrollRun.objects.filter(pk=approved_run.pk).exists()


def test_approved_run_cannot_generate(approved_run):
    employee_with_salary()
    with pytest.raises(PayrollLocked):
        generate_payslips(approved_run)


def test_draft_run_can_be_deleted_with_payslips():
    employee_with_salary()
    run = PayrollRunFactory()
    generate_payslips(run)

    run.delete()

    assert not Payslip.objects.exists()


def test_mark_paid_only_after_approval(admin_user, approved_run):
    with pytest.raises(ValidationError):
        mark_paid(PayrollRunFactory(month=2), admin_user)

    mark_paid(approved_run, admin_user)
    approved_run.refresh_from_db()
    assert approved_run.status == PayrollRun.Status.PAID
    assert approved_run.paid_at is not None


def test_run_totals():
    employee_with_salary()
    employee_with_salary(nationality="SA", id_number="1000000002")
    run = PayrollRunFactory()
    generate_payslips(run)

    totals = run.totals()

    assert totals["count"] == 2
    assert totals["gross"] == D("14400.00")
    assert totals["gosi_employee"] == D("585.00")
    assert totals["gosi_employer"] == D("825.00")   # 120 + 705
    assert totals["net"] == D("13815.00")


def test_payslip_str():
    emp = employee_with_salary()
    run = PayrollRunFactory()
    generate_payslips(run)
    assert str(run.payslips.get()) == f"2026-01 / {emp}"


def test_approved_payslip_cannot_be_deleted_individually(approved_run):
    with pytest.raises(PayrollLocked):
        approved_run.payslips.get().delete()


def test_recalculate_fails_clearly_if_structure_was_removed():
    from payroll.services import regenerate

    emp = employee_with_salary()
    run = PayrollRunFactory()
    generate_payslips(run)
    emp.salary_structures.all().delete()

    with pytest.raises(ValidationError):
        regenerate(run)


def test_update_inputs_rejects_unknown_fields():
    employee_with_salary()
    run = PayrollRunFactory()
    generate_payslips(run)
    with pytest.raises(TypeError):
        update_payslip_inputs(run.payslips.get(), net=D("99999"))


def test_draft_payslip_can_be_deleted_individually():
    employee_with_salary()
    run = PayrollRunFactory()
    generate_payslips(run)

    run.payslips.get().delete()

    assert not run.payslips.exists()


def test_approved_run_cannot_generate_even_with_no_new_employees(approved_run):
    # Must fail loudly, not silently return "0 created".
    with pytest.raises(PayrollLocked):
        generate_payslips(approved_run)


def test_locked_error_wins_over_validation_error(approved_run):
    # Even with an invalid value the user must be told the payroll is locked.
    with pytest.raises(PayrollLocked):
        update_payslip_inputs(approved_run.payslips.get(), absence_days=D("40"))


def test_approving_again_gives_clear_already_approved_message(admin_user, approved_run):
    with pytest.raises(PayrollLocked, match="already"):
        approve_run(approved_run, admin_user)
