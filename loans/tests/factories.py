import datetime as dt
from decimal import Decimal

from expenses.tests.factories import UserFactory
from hr.tests.factories import EmployeeFactory
from loans.models import Loan


def make_loan(employee=None, amount="3000", installment="500", first_month=dt.date(2026, 1, 1),
              status=Loan.Status.APPROVED, kind=Loan.Kind.LOAN, **kwargs) -> Loan:
    return Loan.objects.create(
        employee=employee or EmployeeFactory(hire_date=dt.date(2015, 1, 1)),
        kind=kind, amount=Decimal(amount), installment=Decimal(installment), first_month=first_month,
        status=status, requested_by=kwargs.pop("requested_by", None) or UserFactory(), **kwargs,
    )
