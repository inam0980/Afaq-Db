"""Expense workflow: draft -> submitted -> approved | rejected (-> resubmitted)."""

from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone
from django.utils.translation import gettext as _

from expenses.models import Expense


def _lock(expense: Expense) -> Expense:
    return Expense.objects.select_for_update().get(pk=expense.pk)


def _ensure_not_own(expense: Expense, user):
    if expense.created_by_id == user.pk:
        raise ValidationError(_("You cannot approve or reject your own expense."))


@transaction.atomic
def submit(expense: Expense, user) -> Expense:
    e = _lock(expense)
    if not e.is_editable:
        raise ValidationError(_("Only draft or rejected expenses can be submitted."))
    if not e.receipt:
        raise ValidationError({"receipt": _("Attach the receipt before submitting.")})
    e.status = Expense.Status.SUBMITTED
    e.submitted_at = timezone.now()
    e.rejection_reason = ""
    e.decided_by = None
    e.decided_at = None
    e.save()
    return e


@transaction.atomic
def approve(expense: Expense, user) -> Expense:
    e = _lock(expense)
    if e.status != Expense.Status.SUBMITTED:
        raise ValidationError(_("Only submitted expenses can be approved."))
    _ensure_not_own(e, user)
    e.status = Expense.Status.APPROVED
    e.decided_by = user
    e.decided_at = timezone.now()
    e.save()
    return e


@transaction.atomic
def reject(expense: Expense, user, reason: str) -> Expense:
    e = _lock(expense)
    if e.status != Expense.Status.SUBMITTED:
        raise ValidationError(_("Only submitted expenses can be rejected."))
    _ensure_not_own(e, user)
    reason = (reason or "").strip()
    if not reason:
        raise ValidationError({"reason": _("Give a reason so the submitter can fix it.")})
    e.status = Expense.Status.REJECTED
    e.rejection_reason = reason
    e.decided_by = user
    e.decided_at = timezone.now()
    e.save()
    return e
