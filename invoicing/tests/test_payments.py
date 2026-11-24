"""Unit tests: recording payments, balances and payment status."""

import datetime as dt
from decimal import Decimal as D

import pytest
from django.core.exceptions import ValidationError
from django.utils import timezone

from expenses.tests.factories import UserFactory
from invoicing.balances import with_balances
from invoicing.models import Invoice, Payment
from invoicing.services import delete_payment, record_payment
from invoicing.tests.factories import invoice_with_lines, issued_invoice

pytestmark = pytest.mark.django_db


@pytest.fixture
def user():
    return UserFactory()


@pytest.fixture
def today():
    return timezone.localdate()


def pay(inv, amount, user, date=None, **kw):
    return record_payment(inv, user, amount=D(amount), date=date or timezone.localdate(),
                          method=kw.pop("method", "bank"), reference=kw.pop("reference", "TRX-1"), **kw)


def fresh(inv):
    return with_balances(Invoice.objects.filter(pk=inv.pk)).get()


def test_new_issued_invoice_is_unpaid(today):
    inv = fresh(issued_invoice())
    assert (inv.paid, inv.balance) == (D("0.00"), D("1150.00"))
    assert inv.payment_status == "unpaid"


def test_partial_payment(user):
    inv = issued_invoice()
    pay(inv, "500", user)
    inv = fresh(inv)
    assert (inv.paid, inv.balance) == (D("500.00"), D("650.00"))
    assert inv.payment_status == "partial"


def test_paid_in_instalments(user):
    inv = issued_invoice()
    pay(inv, "500", user)
    pay(inv, "650", user)
    inv = fresh(inv)
    assert inv.balance == D("0.00")
    assert inv.payment_status == "paid"


def test_cannot_overpay(user):
    inv = issued_invoice()
    pay(inv, "1000", user)
    with pytest.raises(ValidationError) as exc:
        pay(inv, "150.01", user)
    assert "amount" in exc.value.message_dict


@pytest.mark.parametrize("amount", ["0", "-5"])
def test_amount_must_be_positive(user, amount):
    with pytest.raises(ValidationError):
        pay(issued_invoice(), amount, user)


def test_cannot_pay_a_draft(user):
    with pytest.raises(ValidationError):
        pay(invoice_with_lines(), "100", user)


def test_payment_date_not_before_invoice_or_in_future(user, today):
    inv = issued_invoice(issue_date=today - dt.timedelta(days=5))
    with pytest.raises(ValidationError):
        pay(inv, "100", user, date=today - dt.timedelta(days=6))
    with pytest.raises(ValidationError):
        pay(inv, "100", user, date=today + dt.timedelta(days=1))
    pay(inv, "100", user, date=today - dt.timedelta(days=5))       # same day is fine


def test_overdue_when_past_due_and_not_fully_paid(user, today):
    inv = issued_invoice(issue_date=today - dt.timedelta(days=40), due_date=today - dt.timedelta(days=10))
    assert fresh(inv).is_overdue is True
    pay(inv, "1150", user)
    assert fresh(inv).is_overdue is False


def test_not_overdue_on_the_due_date(today):
    inv = issued_invoice(issue_date=today - dt.timedelta(days=30), due_date=today)
    assert fresh(inv).is_overdue is False


def test_payment_records_who_received_it(user):
    p = pay(issued_invoice(), "100", user, reference="CHQ-9", note="Cheque")
    assert (p.received_by, p.reference, p.method) == (user, "CHQ-9", "bank")


def test_delete_payment_restores_balance(user):
    inv = issued_invoice()
    p = pay(inv, "500", user)
    payment_id = p.pk
    delete_payment(p)
    assert fresh(inv).balance == D("1150.00")
    assert Payment.history.filter(id=payment_id).count() == 2      # creation + deletion audited


def test_payment_str(user):
    inv = issued_invoice()
    p = pay(inv, "100", user)
    assert str(p) == f"{inv.number}: 100.00"


def test_payment_status_works_without_balance_annotations(user):
    inv = issued_invoice()                       # plain instance, no with_balances()
    assert inv.payment_status == "unpaid"
    assert inv.is_overdue is False


def test_no_payment_status_for_drafts_and_credit_notes(user):
    from invoicing.services import create_credit_note

    assert invoice_with_lines().payment_status is None
    assert create_credit_note(issued_invoice(), user, reason="x").payment_status is None
