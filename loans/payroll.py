"""How loans and advances are deducted in payroll.

Each month an approved loan whose first deduction month has arrived repays
its installment (or the smaller balance left). All loan deductions together
are capped at LOAN_MAX_DEDUCTION_PERCENT of the fixed monthly wage (Labour
Law Art. 92 allows loan recovery of at most 10% of the wage) and at what the
payslip can still pay without going negative. Whatever does not fit simply
waits for the following months — the loan takes longer, nothing is lost.
Oldest loans are repaid first.
"""

from decimal import Decimal

from django.conf import settings
from django.db.models import Sum

from core.money import money
from loans.models import Loan, LoanRepayment
from payroll.models import ZERO


def deduction_limit(gross_fixed: Decimal) -> Decimal:
    return money(gross_fixed * Decimal(settings.LOAN_MAX_DEDUCTION_PERCENT) / 100)


def deduction_plan(slip, room: Decimal) -> list[tuple[Loan, Decimal]]:
    """[(loan, amount)] this payslip repays, using at most `room`."""
    run = slip.run
    loans = Loan.objects.filter(
        employee=slip.employee, status=Loan.Status.APPROVED, first_month__lte=run.period_start
    ).order_by("first_month", "pk")
    plan = []
    for loan in loans:
        if room <= 0:
            break
        repaid = (LoanRepayment.objects.filter(loan=loan).exclude(payslip__run=run)
                  .aggregate(t=Sum("amount"))["t"] or ZERO)
        take = min(loan.installment, loan.amount - repaid, room)
        if take > 0:
            plan.append((loan, take))
            room -= take
    return plan


def record_repayments(slip):
    """Store what an approved payslip repaid (called when its run is approved)."""
    for loan, amount in deduction_plan(slip, slip.loan_deduction):
        LoanRepayment.objects.create(loan=loan, payslip=slip, amount=amount)
