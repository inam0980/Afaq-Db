"""Unit tests: invoice lines, totals, numbering at issue, locking, snapshots."""

import datetime as dt
import re
from decimal import Decimal as D

import pytest
from django.core.exceptions import ValidationError
from django.utils import timezone

from customers.tests.factories import BusinessCustomerFactory, CustomerFactory
from expenses.tests.factories import UserFactory
from invoicing.models import Invoice, InvoiceLine, InvoiceLocked
from invoicing.services import issue, recalculate
from invoicing.tests.factories import InvoiceFactory, InvoiceLineFactory, invoice_with_lines

pytestmark = pytest.mark.django_db


@pytest.fixture
def user():
    return UserFactory()


# --- lines & totals ----------------------------------------------------------

def test_line_amounts():
    line = InvoiceLineFactory(quantity=D("3"), unit_price=D("99.99"), vat_rate=D("15"))
    assert (line.subtotal, line.vat, line.total) == (D("299.97"), D("45.00"), D("344.97"))


def test_zero_rated_line():
    line = InvoiceLineFactory(unit_price=D("500"), vat_rate=D("0"))
    assert (line.vat, line.total) == (D("0.00"), D("500.00"))


@pytest.mark.parametrize("field, bad", [("quantity", D("0")), ("unit_price", D("-1"))])
def test_line_validation(field, bad):
    line = InvoiceLineFactory()
    setattr(line, field, bad)
    with pytest.raises(ValidationError):
        line.full_clean()


def test_invoice_totals_are_sum_of_lines():
    inv = invoice_with_lines("1000", "250.50")
    assert (inv.subtotal, inv.vat_amount, inv.total) == (D("1250.50"), D("187.58"), D("1438.08"))


def test_due_date_cannot_be_before_issue_date():
    inv = InvoiceFactory()
    inv.due_date = inv.issue_date - dt.timedelta(days=1)
    with pytest.raises(ValidationError) as exc:
        inv.full_clean()
    assert "due_date" in exc.value.message_dict


# --- numbering ---------------------------------------------------------------

def test_draft_has_no_number():
    assert invoice_with_lines().number == ""


def test_numbers_are_assigned_at_issue_in_sequence(user):
    a, b = invoice_with_lines(), invoice_with_lines()
    draft_only = invoice_with_lines()                      # never issued: must not consume a number
    issue(b, user)
    issue(a, user)
    b.refresh_from_db(); a.refresh_from_db(); draft_only.refresh_from_db()

    assert re.fullmatch(r"INV-\d{5}", b.number)
    assert int(a.number[4:]) == int(b.number[4:]) + 1      # issue order, not creation order
    assert draft_only.number == ""


# --- locking -----------------------------------------------------------------

@pytest.fixture
def issued(user):
    inv = invoice_with_lines()
    issue(inv, user)
    inv.refresh_from_db()
    return inv


def test_issued_invoice_cannot_be_saved(issued):
    issued.notes = "changed"
    with pytest.raises(InvoiceLocked):
        issued.save()


def test_issued_invoice_cannot_be_deleted(issued):
    with pytest.raises(InvoiceLocked):
        issued.delete()


def test_issued_invoice_lines_are_locked(issued):
    line = issued.lines.first()
    line.unit_price = D("1")
    with pytest.raises(InvoiceLocked):
        line.save()
    with pytest.raises(InvoiceLocked):
        line.delete()
    with pytest.raises(InvoiceLocked):
        InvoiceLineFactory(invoice=issued)


def test_draft_can_be_deleted_with_lines():
    inv = invoice_with_lines()
    inv.delete()
    assert not InvoiceLine.objects.exists()


# --- issue rules & snapshots ---------------------------------------------------

def test_issue_requires_lines(user):
    with pytest.raises(ValidationError, match="at least one line"):
        issue(InvoiceFactory(), user)


def test_issue_recalculates_totals_from_current_lines(user):
    inv = invoice_with_lines("1000")
    line = inv.lines.get()
    line.unit_price = D("2000")          # edited after the last recalculation
    line.save()
    issue(inv, user)
    inv.refresh_from_db()
    assert inv.total == D("2300.00")


def test_issue_requires_positive_total(user):
    inv = InvoiceFactory()
    InvoiceLineFactory(invoice=inv, unit_price=D("0"))
    recalculate(inv)
    with pytest.raises(ValidationError):
        issue(inv, user)


def test_cannot_issue_twice(issued, user):
    with pytest.raises(ValidationError):
        issue(issued, user)


def test_cannot_issue_with_future_date(user):
    inv = invoice_with_lines()
    Invoice.objects.filter(pk=inv.pk).update(
        issue_date=timezone.localdate() + dt.timedelta(days=1),
        due_date=timezone.localdate() + dt.timedelta(days=31),
    )
    with pytest.raises(ValidationError):
        issue(inv, user)


def test_b2b_customer_gets_standard_tax_invoice(user):
    inv = invoice_with_lines(customer=BusinessCustomerFactory())
    issue(inv, user)
    inv.refresh_from_db()
    assert inv.invoice_type == Invoice.Type.STANDARD


def test_individual_gets_simplified_invoice(user):
    inv = invoice_with_lines(customer=CustomerFactory())
    issue(inv, user)
    inv.refresh_from_db()
    assert inv.invoice_type == Invoice.Type.SIMPLIFIED


def test_b2b_customer_with_incomplete_address_cannot_be_invoiced(user):
    customer = BusinessCustomerFactory()
    customer.__class__.objects.filter(pk=customer.pk).update(postal_code="")
    with pytest.raises(ValidationError):
        issue(invoice_with_lines(customer=customer), user)


def test_buyer_details_are_frozen_at_issue(user):
    customer = BusinessCustomerFactory(name="Old Name LLC")
    inv = invoice_with_lines(customer=customer)
    issue(inv, user)
    customer.name = "New Name LLC"
    customer.save()
    inv.refresh_from_db()

    assert inv.buyer_name == "Old Name LLC"
    assert inv.buyer_vat_number == customer.vat_number
    assert inv.buyer_address == customer.address_line
    assert inv.issued_by == user and inv.issued_at is not None


def test_str_and_search(user):
    inv = invoice_with_lines(customer=CustomerFactory(name="Zahra"))
    assert str(inv) == "Draft invoice"
    issue(inv, user)
    inv.refresh_from_db()
    assert str(inv) == inv.number
    assert list(Invoice.objects.search("zahr")) == [inv]
    assert list(Invoice.objects.search(inv.number)) == [inv]


def test_changes_are_audited(user):
    inv = invoice_with_lines()
    issue(inv, user)
    assert inv.history.count() >= 2


def test_draft_line_can_be_deleted_and_str():
    inv = invoice_with_lines("100", "200")
    line = inv.lines.first()
    assert str(line) == "AC maintenance"
    line.delete()
    assert inv.lines.count() == 1
