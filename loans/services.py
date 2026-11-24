"""Loan workflow: request -> approve / reject. Deductions happen in payroll (loans.payroll)."""

from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone
from django.utils.translation import gettext as _

from hr.models import Employee
from loans.models import Loan


def request_loan(employee, kind, amount, installment, first_month, user, reason="") -> Loan:
    if employee.status == Employee.Status.TERMINATED:
        raise ValidationError(_("%(emp)s has left the company.") % {"emp": employee.full_name})
    if installment is None:
        if kind != Loan.Kind.ADVANCE:
            raise ValidationError({"installment": _("Enter the monthly installment.")})
        installment = amount                      # an advance comes back in one payroll
    loan = Loan(employee=employee, kind=kind, amount=amount, installment=installment,
                first_month=first_month.replace(day=1), reason=reason, requested_by=user)
    loan.full_clean()
    loan.save()
    return loan


def _decide(loan, user, status, note):
    with transaction.atomic():
        current = Loan.objects.select_for_update().get(pk=loan.pk)
        if current.status != Loan.Status.PENDING:
            raise ValidationError(_("This request has already been decided."))
        current.status, current.decided_by, current.decided_at = status, user, timezone.now()
        current.decision_note = note
        current.save()
    loan.refresh_from_db()
    return loan


def approve(loan, user, note="") -> Loan:
    if loan.requested_by_id == user.pk:
        raise ValidationError(_("You cannot approve a request you entered yourself."))
    return _decide(loan, user, Loan.Status.APPROVED, note.strip())


def reject(loan, user, note) -> Loan:
    if not note.strip():
        raise ValidationError(_("Give a reason for rejecting."))
    return _decide(loan, user, Loan.Status.REJECTED, note.strip())
