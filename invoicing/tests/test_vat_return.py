"""Unit tests: VAT return (ZATCA boxes) built from invoices, credit notes and expenses."""

import datetime as dt
from decimal import Decimal as D

import pytest

from expenses.models import Expense
from expenses.tests.factories import ExpenseFactory, UserFactory
from invoicing.models import Invoice, InvoiceLine
from invoicing.services import create_credit_note, issue, recalculate
from invoicing.tests.factories import InvoiceFactory, invoice_with_lines, issued_invoice
from invoicing.vat_return import parse_period, vat_return

pytestmark = pytest.mark.django_db

Q4 = (dt.date(2025, 10, 1), dt.date(2025, 12, 31))
IN_Q4 = dt.date(2025, 11, 15)
BEFORE_Q4 = dt.date(2025, 9, 30)
AFTER_Q4 = dt.date(2026, 1, 1)


@pytest.fixture
def user():
    return UserFactory()


# --- periods ---------------------------------------------------------------------

@pytest.mark.parametrize(
    "raw, expected",
    [
        ("2025-Q4", (dt.date(2025, 10, 1), dt.date(2025, 12, 31), "2025-Q4")),
        ("2026-Q1", (dt.date(2026, 1, 1), dt.date(2026, 3, 31), "2026-Q1")),
        ("2028-02", (dt.date(2028, 2, 1), dt.date(2028, 2, 29), "2028-02")),
        ("2025-11", (dt.date(2025, 11, 1), dt.date(2025, 11, 30), "2025-11")),
    ],
)
def test_parse_period(raw, expected):
    assert parse_period(raw, today=dt.date(2026, 5, 5)) == expected


@pytest.mark.parametrize("raw", ["", "2025-Q5", "2025-13", "nonsense", None])
def test_invalid_period_defaults_to_current_quarter(raw):
    assert parse_period(raw, today=dt.date(2026, 5, 5)) == (dt.date(2026, 4, 1), dt.date(2026, 6, 30), "2026-Q2")


# --- sales -------------------------------------------------------------------------

def sale(user, day, *lines):
    """Issued invoice dated `day` with (price, vat_rate) lines."""
    inv = InvoiceFactory(issue_date=day, due_date=day + dt.timedelta(days=30))
    for price, rate in lines:
        InvoiceLine.objects.create(invoice=inv, description="Work", unit_price=D(price), vat_rate=D(rate))
    recalculate(inv)
    issue(inv, user)
    inv.refresh_from_db()
    return inv


def test_standard_and_zero_rated_sales(user):
    sale(user, IN_Q4, ("1000", "15"), ("200", "0"))
    sale(user, IN_Q4, ("500", "15"))

    r = vat_return(*Q4)

    assert (r.sales_standard.amount, r.sales_standard.adjustment, r.sales_standard.vat) == (
        D("1500.00"), D("0.00"), D("225.00"),
    )
    assert (r.sales_zero.amount, r.sales_zero.vat) == (D("200.00"), D("0.00"))
    assert r.total_sales.amount == D("1700.00") and r.total_sales.vat == D("225.00")


def test_only_issued_invoices_inside_the_period_count(user):
    sale(user, BEFORE_Q4, ("1000", "15"))
    invoice_with_lines("9999", issue_date=IN_Q4, due_date=IN_Q4)        # draft
    r = vat_return(*Q4)
    assert r.sales_standard.amount == D("0.00")
    assert r.warnings["draft_invoices"] == 1


def test_credit_notes_are_adjustments_in_the_period_they_are_issued(user):
    old = sale(user, BEFORE_Q4, ("1000", "15"))                         # Q3 invoice
    cn = create_credit_note(old, user, reason="Discount")
    line = cn.lines.get(); line.unit_price = D("100"); line.save(); recalculate(cn)
    Invoice.objects.filter(pk=cn.pk).update(issue_date=IN_Q4, due_date=IN_Q4)
    issue(cn, user)                                                     # issued in Q4

    r = vat_return(*Q4)

    assert r.sales_standard.amount == D("0.00")
    assert r.sales_standard.adjustment == D("-100.00")
    assert r.sales_standard.vat == D("-15.00")


# --- purchases ---------------------------------------------------------------------

def expense(day, total, rate, status):
    e = ExpenseFactory(date=day, total=D(total), vat_rate=D(rate),
                       vendor_vat_number="300000000000003" if rate else "")
    Expense.objects.filter(pk=e.pk).update(status=status)
    return e


def test_purchases_use_approved_expenses_only(user):
    expense(IN_Q4, "115", "15", Expense.Status.APPROVED)               # 100 + 15
    expense(IN_Q4, "230", "15", Expense.Status.APPROVED)               # 200 + 30
    expense(IN_Q4, "50", "0", Expense.Status.APPROVED)                 # no VAT
    expense(IN_Q4, "1150", "15", Expense.Status.SUBMITTED)             # not yet approved
    expense(AFTER_Q4, "115", "15", Expense.Status.APPROVED)            # next period

    r = vat_return(*Q4)

    assert (r.purchases_standard.amount, r.purchases_standard.vat) == (D("300.00"), D("45.00"))
    assert (r.purchases_zero.amount, r.purchases_zero.vat) == (D("50.00"), D("0.00"))
    assert r.total_purchases.amount == D("350.00")
    assert r.warnings["unapproved_expenses"] == 1


# --- net ---------------------------------------------------------------------------

def test_net_vat_due(user):
    sale(user, IN_Q4, ("1000", "15"))                                   # output 150
    expense(IN_Q4, "115", "15", Expense.Status.APPROVED)               # input 15
    r = vat_return(*Q4)
    assert (r.output_vat, r.input_vat, r.net_vat) == (D("150.00"), D("15.00"), D("135.00"))
    assert r.is_refund is False


def test_net_vat_refundable(user):
    expense(IN_Q4, "1150", "15", Expense.Status.APPROVED)              # input 150
    r = vat_return(*Q4)
    assert r.net_vat == D("-150.00")
    assert r.is_refund is True


def test_empty_period():
    r = vat_return(*Q4)
    assert (r.output_vat, r.input_vat, r.net_vat) == (D("0.00"), D("0.00"), D("0.00"))
    assert r.documents == []
    assert r.is_refund is False            # nothing to pay is not a refund


# --- drill-down & CSV ----------------------------------------------------------------

def test_documents_list_every_counted_item(user):
    inv = sale(user, IN_Q4, ("1000", "15"))
    e = expense(IN_Q4, "115", "15", Expense.Status.APPROVED)
    r = vat_return(*Q4)
    refs = {(d.kind, d.reference) for d in r.documents}
    assert refs == {("invoice", inv.number), ("expense", e.number)}
    doc = next(d for d in r.documents if d.kind == "invoice")
    assert (doc.amount, doc.vat) == (D("1000.00"), D("150.00"))


def test_csv_rows(user):
    from invoicing.vat_return import csv_rows

    sale(user, IN_Q4, ("1000", "15"))
    rows = list(csv_rows(vat_return(*Q4)))
    assert rows[0] == ["Type", "Date", "Reference", "Party", "VAT rate", "Amount excl. VAT", "VAT"]
    assert rows[1][0] == "invoice" and rows[1][5:] == ["1000.00", "150.00"]


def test_credit_notes_are_negative_in_the_document_list(user):
    old = sale(user, BEFORE_Q4, ("1000", "15"))
    cn = create_credit_note(old, user, reason="Discount")
    line = cn.lines.get(); line.unit_price = D("100"); line.save(); recalculate(cn)
    Invoice.objects.filter(pk=cn.pk).update(issue_date=IN_Q4, due_date=IN_Q4)
    issue(cn, user)

    doc = vat_return(*Q4).documents[0]

    assert doc.kind == "credit_note"
    assert (doc.amount, doc.vat) == (D("-100.00"), D("-15.00"))
