import datetime as dt
from decimal import Decimal as D

import pytest
from django.core.exceptions import ValidationError
from django.db import IntegrityError

from loans.models import Loan, LoanRepayment
from loans.tests.factories import make_loan
from payroll.models import Payslip
from payroll.tests.factories import PayrollRunFactory, SalaryStructureFactory

pytestmark = pytest.mark.django_db


def payslip_for(loan, year=2026, month=1):
    if not loan.employee.salary_structures.exists():
        SalaryStructureFactory(employee=loan.employee)
    return Payslip.objects.create(run=PayrollRunFactory(year=year, month=month), employee=loan.employee)


def test_first_month_is_normalised_to_the_first_day():
    assert make_loan(first_month=dt.date(2026, 3, 17)).first_month == dt.date(2026, 3, 1)


def test_installment_cannot_exceed_amount():
    loan = make_loan()
    loan.installment = D("3000.01")
    with pytest.raises(ValidationError) as err:
        loan.full_clean()
    assert "installment" in err.value.message_dict
    loan.installment = D("3000")
    loan.full_clean()


def test_balance_and_settled():
    loan = make_loan(amount="1000", installment="600")
    assert (loan.repaid, loan.outstanding, loan.is_settled) == (D("0"), D("1000"), False)
    LoanRepayment.objects.create(loan=loan, payslip=payslip_for(loan, month=1), amount=D("600"))
    LoanRepayment.objects.create(loan=loan, payslip=payslip_for(loan, month=2), amount=D("400"))
    assert (loan.repaid, loan.outstanding, loan.is_settled) == (D("1000"), D("0"), True)


def test_pending_loan_is_never_settled():
    loan = make_loan(status=Loan.Status.PENDING)
    loan.amount = D("0")
    assert not loan.is_settled


def test_schedule_length_and_last_month():
    loan = make_loan(amount="3000", installment="700", first_month=dt.date(2026, 11, 1))
    assert loan.months == 5                                   # 700 x 4 + 200
    assert loan.last_month == dt.date(2027, 3, 1)
    assert make_loan(amount="500", installment="500", first_month=dt.date(2026, 12, 1)).last_month == dt.date(2026, 12, 1)


def test_active_excludes_pending_rejected_and_repaid():
    open_loan = make_loan(amount="1000")
    make_loan(status=Loan.Status.PENDING)
    make_loan(status=Loan.Status.REJECTED)
    repaid = make_loan(amount="500", installment="500")
    LoanRepayment.objects.create(loan=repaid, payslip=payslip_for(repaid), amount=D("500"))
    assert list(Loan.objects.active()) == [open_loan]


def test_one_repayment_per_payslip():
    loan = make_loan()
    slip = payslip_for(loan)
    LoanRepayment.objects.create(loan=loan, payslip=slip, amount=D("100"))
    with pytest.raises(IntegrityError):
        LoanRepayment.objects.create(loan=loan, payslip=slip, amount=D("100"))


def test_str_and_url():
    loan = make_loan(kind=Loan.Kind.ADVANCE, amount="2000")
    assert str(loan) == f"Salary advance 2000 - {loan.employee.full_name}"
    assert loan.get_absolute_url() == f"/loans/{loan.pk}/"
    rep = LoanRepayment.objects.create(loan=loan, payslip=payslip_for(loan), amount=D("100"))
    assert str(rep) == f"{loan} / 2026-01: 100"
