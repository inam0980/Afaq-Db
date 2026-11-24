"""Integration: loans deducted by the payroll run, repayments recorded on approval."""

import datetime as dt
from decimal import Decimal as D

import pytest

from expenses.tests.factories import UserFactory
from hr.tests.factories import EmployeeFactory
from loans.models import Loan, LoanRepayment
from loans.payroll import deduction_limit
from loans.tests.factories import make_loan
from payroll import services
from payroll.models import PayrollRun
from payroll.tests.factories import PayrollRunFactory, SalaryStructureFactory

pytestmark = pytest.mark.django_db


@pytest.fixture
def emp():
    e = EmployeeFactory(hire_date=dt.date(2015, 1, 1), nationality="IN", id_number="2123456789")
    SalaryStructureFactory(employee=e)               # fixed wage 7200 -> 10% = 720
    return e


def slip_in(emp, year=2026, month=1):
    run = PayrollRunFactory(year=year, month=month)
    services.generate_payslips(run)
    return run, run.payslips.get(employee=emp)


def approve(run):
    return services.approve_run(run, UserFactory())


def test_limit_is_ten_percent_by_default(settings):
    assert deduction_limit(D("7200")) == D("720.00")
    settings.LOAN_MAX_DEDUCTION_PERCENT = 25
    assert deduction_limit(D("7200")) == D("1800.00")


def test_installment_deducted_from_payslip(emp):
    make_loan(emp, amount="3000", installment="500")
    _, slip = slip_in(emp)
    assert slip.loan_deduction == D("500")
    assert slip.total_deductions == slip.absence + slip.gosi_employee + D("500")
    assert slip.net == slip.gross - slip.total_deductions


def test_no_deduction_before_first_month_or_unless_approved(emp):
    make_loan(emp, first_month=dt.date(2026, 2, 1))
    make_loan(emp, status=Loan.Status.PENDING)
    make_loan(emp, status=Loan.Status.REJECTED)
    _, slip = slip_in(emp, month=1)
    assert slip.loan_deduction == D("0")


def test_capped_at_ten_percent_and_oldest_first(emp):
    older = make_loan(emp, amount="5000", installment="600", first_month=dt.date(2025, 12, 1))
    newer = make_loan(emp, amount="5000", installment="600", first_month=dt.date(2026, 1, 1))
    run, slip = slip_in(emp)
    assert slip.loan_deduction == D("720.00")
    approve(run)
    assert [(r.loan, r.amount) for r in LoanRepayment.objects.order_by("loan__first_month")] == [
        (older, D("600")), (newer, D("120.00")),
    ]


def test_last_installment_is_only_the_balance(emp):
    loan = make_loan(emp, amount="700", installment="500")
    run1, slip1 = slip_in(emp, month=1)
    approve(run1)
    run2, slip2 = slip_in(emp, month=2)
    assert slip2.loan_deduction == D("200")
    approve(run2)
    assert loan.outstanding == D("0") and loan.is_settled
    _, slip3 = slip_in(emp, month=3)
    assert slip3.loan_deduction == D("0")


def test_draft_recalculation_records_nothing(emp):
    make_loan(emp)
    run, slip = slip_in(emp)
    services.regenerate(run)
    services.update_payslip_inputs(slip, overtime_hours=D("2"))
    assert not LoanRepayment.objects.exists()


def test_repayments_recorded_once_on_approval(emp):
    loan = make_loan(emp)
    run, slip = slip_in(emp)
    approve(run)
    services.mark_paid(PayrollRun.objects.get(pk=run.pk), UserFactory())
    (rep,) = LoanRepayment.objects.all()
    assert (rep.loan, rep.payslip, rep.amount) == (loan, slip, D("500"))
    assert loan.outstanding == D("2500")


def test_loan_never_makes_net_negative(emp):
    make_loan(emp, amount="3000", installment="500")
    run, slip = slip_in(emp)
    # 28 days absence: 7200 - 6720 = 480 left (no employee GOSI for non-Saudis) < 500 installment
    slip = services.update_payslip_inputs(slip, absence_days=D("28"))
    assert (slip.loan_deduction, slip.net) == (D("480.00"), D("0.00"))


def test_other_employees_loans_ignored(emp):
    make_loan()                                       # someone else's loan
    _, slip = slip_in(emp)
    assert slip.loan_deduction == D("0")


def test_plan_for_an_approved_payslip_is_stable(emp):
    """Re-planning a payslip must not count its own repayments as already paid."""
    from loans.payroll import deduction_plan

    loan = make_loan(emp, amount="500", installment="500")
    run, slip = slip_in(emp)
    approve(run)
    slip.refresh_from_db()
    assert deduction_plan(slip, slip.loan_deduction) == [(loan, D("500"))]


def test_loans_beyond_the_cap_wait(emp):
    make_loan(emp, amount="5000", installment="720", first_month=dt.date(2025, 12, 1))
    later = make_loan(emp, amount="5000", installment="100", first_month=dt.date(2026, 1, 1))
    run, slip = slip_in(emp)
    assert slip.loan_deduction == D("720.00")              # the cap is used up by the older loan
    approve(run)
    assert not later.repayments.exists()
