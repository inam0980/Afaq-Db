import datetime as dt
from decimal import Decimal as D

import pytest
from django.core.exceptions import ValidationError

from expenses.tests.factories import UserFactory
from hr.models import Employee
from hr.tests.factories import EmployeeFactory
from loans import services
from loans.models import Loan
from loans.tests.factories import make_loan

pytestmark = pytest.mark.django_db


@pytest.fixture
def emp():
    return EmployeeFactory(hire_date=dt.date(2015, 1, 1))


def test_request_creates_pending_loan(emp):
    user = UserFactory()
    loan = services.request_loan(emp, Loan.Kind.LOAN, D("3000"), D("500"), dt.date(2026, 2, 10), user,
                                 reason="Family emergency")
    assert (loan.status, loan.requested_by, loan.first_month, loan.reason) == (
        Loan.Status.PENDING, user, dt.date(2026, 2, 1), "Family emergency")


def test_advance_without_installment_is_repaid_in_one_month(emp):
    loan = services.request_loan(emp, Loan.Kind.ADVANCE, D("1500"), None, dt.date(2026, 2, 1), UserFactory())
    assert loan.installment == D("1500")


def test_loan_needs_an_installment(emp):
    with pytest.raises(ValidationError) as err:
        services.request_loan(emp, Loan.Kind.LOAN, D("3000"), None, dt.date(2026, 2, 1), UserFactory())
    assert "installment" in err.value.message_dict


def test_request_validates(emp):
    with pytest.raises(ValidationError):
        services.request_loan(emp, Loan.Kind.LOAN, D("100"), D("500"), dt.date(2026, 2, 1), UserFactory())
    assert not Loan.objects.exists()


def test_terminated_employee_cannot_get_a_loan(emp):
    emp.status, emp.termination_date = Employee.Status.TERMINATED, dt.date(2025, 12, 31)
    emp.save()
    with pytest.raises(ValidationError):
        services.request_loan(emp, Loan.Kind.LOAN, D("1000"), D("500"), dt.date(2026, 2, 1), UserFactory())


def test_approve_and_reject():
    approver = UserFactory()
    loan = make_loan(status=Loan.Status.PENDING)
    services.approve(loan, approver, note="OK")
    loan.refresh_from_db()
    assert (loan.status, loan.decided_by, loan.decision_note) == (Loan.Status.APPROVED, approver, "OK")
    assert loan.decided_at is not None

    other = make_loan(status=Loan.Status.PENDING)
    services.reject(other, approver, note="Already has a loan")
    other.refresh_from_db()
    assert (other.status, other.decision_note) == (Loan.Status.REJECTED, "Already has a loan")


def test_only_pending_can_be_decided():
    approver = UserFactory()
    for status in (Loan.Status.APPROVED, Loan.Status.REJECTED):
        loan = make_loan(status=status)
        with pytest.raises(ValidationError):
            services.approve(loan, approver)
        with pytest.raises(ValidationError):
            services.reject(loan, approver, note="x")


def test_reject_needs_a_reason():
    with pytest.raises(ValidationError):
        services.reject(make_loan(status=Loan.Status.PENDING), UserFactory(), note="  ")


def test_cannot_approve_own_request():
    user = UserFactory()
    loan = make_loan(status=Loan.Status.PENDING, requested_by=user)
    with pytest.raises(ValidationError):
        services.approve(loan, user)
    loan.refresh_from_db()
    assert loan.status == Loan.Status.PENDING


def test_stale_object_cannot_be_decided_twice():
    loan = make_loan(status=Loan.Status.PENDING)
    stale = Loan.objects.get(pk=loan.pk)
    services.approve(loan, UserFactory())
    with pytest.raises(ValidationError):
        services.reject(stale, UserFactory(), note="late")
