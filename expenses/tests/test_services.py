"""Unit tests: expense approval workflow."""

import pytest
from django.core.exceptions import ValidationError

from expenses.models import Expense, ExpenseLocked
from expenses.services import approve, reject, submit
from expenses.tests.factories import ExpenseFactory, UserFactory

pytestmark = pytest.mark.django_db


@pytest.fixture
def approver():
    return UserFactory(username="approver")


@pytest.fixture
def submitted():
    e = ExpenseFactory()
    submit(e, e.created_by)
    return e


def test_submit_moves_draft_to_submitted():
    e = ExpenseFactory()
    submit(e, e.created_by)
    e.refresh_from_db()
    assert e.status == Expense.Status.SUBMITTED
    assert e.submitted_at is not None


def test_submit_requires_receipt():
    e = ExpenseFactory(receipt="")
    with pytest.raises(ValidationError) as exc:
        submit(e, e.created_by)
    assert "receipt" in exc.value.message_dict


def test_cannot_submit_twice(submitted):
    with pytest.raises(ValidationError):
        submit(submitted, submitted.created_by)


def test_approve(submitted, approver):
    approve(submitted, approver)
    submitted.refresh_from_db()
    assert submitted.status == Expense.Status.APPROVED
    assert submitted.decided_by == approver
    assert submitted.decided_at is not None


def test_cannot_approve_own_expense(submitted):
    with pytest.raises(ValidationError):
        approve(submitted, submitted.created_by)


def test_cannot_approve_draft(approver):
    with pytest.raises(ValidationError):
        approve(ExpenseFactory(), approver)


def test_cannot_approve_twice(submitted, approver):
    approve(submitted, approver)
    with pytest.raises((ValidationError, ExpenseLocked)):
        approve(submitted, approver)


def test_reject_needs_reason(submitted, approver):
    with pytest.raises(ValidationError):
        reject(submitted, approver, reason="   ")


def test_reject(submitted, approver):
    reject(submitted, approver, reason="Receipt unreadable")
    submitted.refresh_from_db()
    assert submitted.status == Expense.Status.REJECTED
    assert submitted.rejection_reason == "Receipt unreadable"
    assert submitted.decided_by == approver


def test_cannot_reject_own_expense(submitted):
    with pytest.raises(ValidationError):
        reject(submitted, submitted.created_by, reason="no")


def test_resubmit_after_rejection_clears_reason(submitted, approver):
    reject(submitted, approver, reason="Wrong amount")
    submit(submitted, submitted.created_by)
    submitted.refresh_from_db()
    assert submitted.status == Expense.Status.SUBMITTED
    assert submitted.rejection_reason == ""
    assert submitted.decided_by is None


def test_cannot_reject_draft(approver):
    with pytest.raises(ValidationError):
        reject(ExpenseFactory(), approver, reason="no")
