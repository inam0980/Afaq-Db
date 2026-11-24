"""Receivables: invoice balances, customer balance, statements and aging.

balance of an invoice = total - payments - issued credit notes against it.
Only issued documents count; drafts never affect what a customer owes.
"""

import datetime as dt
from dataclasses import dataclass, field
from decimal import Decimal

from django.db.models import DecimalField, F, OuterRef, Subquery, Sum, Value
from django.db.models.functions import Coalesce
from django.utils import timezone

from core.money import money
from invoicing.models import Invoice, Payment

ZERO = Decimal("0")
_DEC = DecimalField(max_digits=14, decimal_places=2)

BUCKETS = ("current", "1_30", "31_60", "61_90", "90_plus")


def with_balances(qs):
    paid = (
        Payment.objects.filter(invoice=OuterRef("pk"))
        .values("invoice").annotate(s=Sum("amount")).values("s")
    )
    credited = (
        Invoice.objects.filter(
            original=OuterRef("pk"), kind=Invoice.Kind.CREDIT_NOTE, status=Invoice.Status.ISSUED
        )
        .values("original").annotate(s=Sum("total")).values("s")
    )
    return qs.annotate(
        paid=Coalesce(Subquery(paid, output_field=_DEC), Value(ZERO), output_field=_DEC),
        credited=Coalesce(Subquery(credited, output_field=_DEC), Value(ZERO), output_field=_DEC),
    ).annotate(balance=F("total") - F("paid") - F("credited"))


def open_invoices(customer=None):
    """Issued invoices (not credit notes) that still have money owing."""
    qs = Invoice.objects.filter(status=Invoice.Status.ISSUED, kind=Invoice.Kind.INVOICE)
    if customer is not None:
        qs = qs.filter(customer=customer)
    return with_balances(qs).filter(balance__gt=0)


def customer_balance(customer) -> Decimal:
    return money(open_invoices(customer).aggregate(s=Sum("balance"))["s"] or ZERO)


# --- statement -----------------------------------------------------------------

@dataclass
class StatementEntry:
    date: dt.date
    kind: str                     # "invoice" | "credit_note" | "payment"
    reference: str
    description: str
    debit: Decimal | None
    credit: Decimal | None
    balance: Decimal = ZERO


@dataclass
class Statement:
    customer: object
    start: dt.date
    end: dt.date
    opening_balance: Decimal
    entries: list = field(default_factory=list)
    closing_balance: Decimal = ZERO
    total_debits: Decimal = ZERO
    total_credits: Decimal = ZERO


_KIND_ORDER = {"invoice": 0, "credit_note": 1, "payment": 2}


def statement(customer, start: dt.date, end: dt.date) -> Statement:
    docs = Invoice.objects.filter(customer=customer, status=Invoice.Status.ISSUED)
    invoices = docs.filter(kind=Invoice.Kind.INVOICE)
    credit_notes = docs.filter(kind=Invoice.Kind.CREDIT_NOTE)
    payments = Payment.objects.filter(invoice__customer=customer).select_related("invoice")

    def total(qs, date_field, amount_field):
        return qs.filter(**{f"{date_field}__lt": start}).aggregate(s=Sum(amount_field))["s"] or ZERO

    opening = money(
        total(invoices, "issue_date", "total")
        - total(credit_notes, "issue_date", "total")
        - total(payments, "date", "amount")
    )

    entries = [
        StatementEntry(i.issue_date, "invoice", i.number, "Invoice", i.total, None)
        for i in invoices.filter(issue_date__range=(start, end))
    ] + [
        StatementEntry(c.issue_date, "credit_note", c.number, f"Credit note ({c.original.number})", None, c.total)
        for c in credit_notes.filter(issue_date__range=(start, end)).select_related("original")
    ] + [
        StatementEntry(p.date, "payment", p.invoice.number, f"Payment - {p.get_method_display()}"
                       + (f" ({p.reference})" if p.reference else ""), None, p.amount)
        for p in payments.filter(date__range=(start, end))
    ]
    entries.sort(key=lambda e: (e.date, _KIND_ORDER[e.kind], e.reference))

    running = opening
    for e in entries:
        running = money(running + (e.debit or ZERO) - (e.credit or ZERO))
        e.balance = running

    return Statement(
        customer, start, end, opening, entries,
        closing_balance=running,
        total_debits=money(sum((e.debit or ZERO for e in entries), ZERO)),
        total_credits=money(sum((e.credit or ZERO for e in entries), ZERO)),
    )


# --- aging -----------------------------------------------------------------------

def bucket_for(days_late: int) -> str:
    if days_late <= 0:
        return "current"
    if days_late <= 30:
        return "1_30"
    if days_late <= 60:
        return "31_60"
    if days_late <= 90:
        return "61_90"
    return "90_plus"


@dataclass
class AgingRow:
    customer: object
    buckets: dict
    total: Decimal = ZERO
    overdue: Decimal = ZERO


@dataclass
class AgingReport:
    as_of: dt.date
    rows: list
    totals: dict


def aging(as_of: dt.date | None = None) -> AgingReport:
    as_of = as_of or timezone.localdate()
    rows: dict = {}
    for inv in open_invoices().select_related("customer"):
        row = rows.setdefault(inv.customer_id, AgingRow(inv.customer, {b: ZERO for b in BUCKETS}))
        bucket = bucket_for((as_of - inv.due_date).days)
        row.buckets[bucket] = money(row.buckets[bucket] + inv.balance)
        row.total = money(row.total + inv.balance)
        if bucket != "current":
            row.overdue = money(row.overdue + inv.balance)

    ordered = sorted(rows.values(), key=lambda r: (-r.overdue, -r.total, r.customer.name))
    totals = {b: money(sum((r.buckets[b] for r in ordered), ZERO)) for b in BUCKETS}
    totals["total"] = money(sum((r.total for r in ordered), ZERO))
    totals["overdue"] = money(sum((r.overdue for r in ordered), ZERO))
    return AgingReport(as_of, ordered, totals)
