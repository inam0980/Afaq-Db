"""Unit tests: credit notes correct issued invoices without editing them."""

import re
from decimal import Decimal as D

import pytest
from django.core.exceptions import ValidationError
from django.utils import timezone

from expenses.tests.factories import UserFactory
from invoicing.balances import with_balances
from invoicing.models import Invoice
from invoicing.services import create_credit_note, issue, record_payment, recalculate
from invoicing.tests.factories import invoice_with_lines, issued_invoice

pytestmark = pytest.mark.django_db


@pytest.fixture
def user():
    return UserFactory()


def fresh(inv):
    return with_balances(Invoice.objects.filter(pk=inv.pk)).get()


def set_first_line_price(cn, price):
    line = cn.lines.first()
    line.unit_price = D(price)
    line.save()
    recalculate(cn)


def test_draft_credit_note_copies_original(user):
    original = issued_invoice("1000", "200")
    cn = create_credit_note(original, user, reason="Overcharged")

    assert cn.kind == Invoice.Kind.CREDIT_NOTE and cn.is_draft
    assert (cn.original, cn.customer, cn.job) == (original, original.customer, original.job)
    assert cn.reason == "Overcharged"
    assert cn.lines.count() == 2 and cn.total == original.total


def test_credit_note_needs_a_reason(user):
    with pytest.raises(ValidationError):
        create_credit_note(issued_invoice(), user, reason="  ")


def test_only_issued_invoices_can_be_credited(user):
    with pytest.raises(ValidationError):
        create_credit_note(invoice_with_lines(), user, reason="x")


def test_credit_note_cannot_be_credited(user):
    cn = create_credit_note(issued_invoice(), user, reason="x")
    issue(cn, user)
    with pytest.raises(ValidationError):
        create_credit_note(cn, user, reason="x")


def test_issued_credit_note_reduces_balance_and_has_its_own_numbers(user):
    original = issued_invoice()                       # 1150.00
    cn = create_credit_note(original, user, reason="Discount agreed")
    set_first_line_price(cn, "200")                   # 230.00
    issue(cn, user)
    cn.refresh_from_db()

    assert re.fullmatch(r"CN-\d{5}", cn.number)
    assert cn.invoice_type == original.invoice_type
    assert fresh(original).credited == D("230.00")
    assert fresh(original).balance == D("920.00")


def test_draft_credit_note_does_not_reduce_balance(user):
    original = issued_invoice()
    create_credit_note(original, user, reason="x")
    assert fresh(original).balance == D("1150.00")


def test_credit_cannot_exceed_unpaid_balance(user):
    original = issued_invoice()
    record_payment(original, user, amount=D("1035"), date=timezone.localdate(), method="cash", reference="")
    cn = create_credit_note(original, user, reason="x")          # copies 1150.00, balance is 115.00
    with pytest.raises(ValidationError):
        issue(cn, user)
    set_first_line_price(cn, "100")                              # 115.00 incl. VAT = balance
    issue(cn, user)
    assert fresh(original).balance == D("0.00")


def test_fully_paid_invoice_cannot_get_a_credit_note(user):
    original = issued_invoice()
    record_payment(original, user, amount=D("1150"), date=timezone.localdate(), method="cash", reference="")
    with pytest.raises(ValidationError):
        create_credit_note(original, user, reason="x")


def test_credit_note_str_before_and_after_issue(user):
    cn = create_credit_note(issued_invoice(), user, reason="x")
    assert str(cn) == "Draft credit note"
    issue(cn, user)
    cn.refresh_from_db()
    assert str(cn).startswith("CN-")


def test_payments_cannot_be_recorded_on_a_credit_note(user):
    cn = create_credit_note(issued_invoice(), user, reason="x")
    issue(cn, user)
    with pytest.raises(ValidationError):
        record_payment(cn, user, amount=D("1"), date=timezone.localdate(), method="cash", reference="")


def test_job_revenue_is_net_of_credit_notes(user):
    from invoicing.services import create_from_job
    from invoicing.tests.test_from_job import completed_job
    from jobs.costing import job_costing

    job = completed_job(quoted_amount=D("1000"))
    inv = create_from_job(job, user)
    issue(inv, user)
    cn = create_credit_note(inv, user, reason="Partial refund")
    set_first_line_price(cn, "100")
    issue(cn, user)

    assert job_costing(job).revenue == D("900.00")


def test_reason_cleared_while_editing_blocks_issue(user):
    cn = create_credit_note(issued_invoice(), user, reason="Original reason")
    Invoice.objects.filter(pk=cn.pk).update(reason="  ")
    with pytest.raises(ValidationError, match="reason"):
        issue(cn, user)


def test_invoice_with_only_a_credit_note_is_partially_settled(user):
    original = issued_invoice()
    cn = create_credit_note(original, user, reason="Discount")
    set_first_line_price(cn, "100")
    issue(cn, user)
    assert fresh(original).payment_status == "partial"
