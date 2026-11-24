"""VAT return for a period, laid out like ZATCA's return form.

Sales  (output VAT): issued invoices dated in the period; credit notes issued in
                     the period are adjustments (negative), whenever the original was.
Purchases (input VAT): APPROVED expenses dated in the period.
Net VAT = output VAT - input VAT (negative = refundable / carried forward).
"""

import calendar
import datetime as dt
import re
from dataclasses import dataclass, field
from decimal import Decimal

from django.db.models import Sum
from django.urls import reverse

from core.money import money
from expenses.models import Expense
from invoicing.models import Invoice, InvoiceLine

ZERO = Decimal("0")
STANDARD_RATE = Decimal("15")
_QUARTER_RE = re.compile(r"^(\d{4})-Q([1-4])$")
_MONTH_RE = re.compile(r"^(\d{4})-(\d{2})$")


def _quarter(year: int, q: int):
    start = dt.date(year, 3 * q - 2, 1)
    end_month = 3 * q
    end = dt.date(year, end_month, calendar.monthrange(year, end_month)[1])
    return start, end, f"{year}-Q{q}"


def parse_period(raw, today: dt.date):
    """'2025-Q4' or '2025-11' -> (start, end, label); anything else -> current quarter."""
    raw = raw or ""
    if match := _QUARTER_RE.match(raw):
        return _quarter(int(match.group(1)), int(match.group(2)))
    if (match := _MONTH_RE.match(raw)) and 1 <= int(match.group(2)) <= 12:
        year, month = int(match.group(1)), int(match.group(2))
        return dt.date(year, month, 1), dt.date(year, month, calendar.monthrange(year, month)[1]), raw
    return _quarter(today.year, (today.month - 1) // 3 + 1)


@dataclass
class Box:
    amount: Decimal = ZERO
    adjustment: Decimal = ZERO
    vat: Decimal = ZERO


@dataclass
class Document:
    kind: str            # invoice | credit_note | expense
    date: dt.date
    reference: str
    party: str
    rate: Decimal
    amount: Decimal
    vat: Decimal
    url: str


@dataclass
class VatReturn:
    start: dt.date
    end: dt.date
    sales_standard: Box
    sales_zero: Box
    total_sales: Box
    purchases_standard: Box
    purchases_zero: Box
    total_purchases: Box
    output_vat: Decimal
    input_vat: Decimal
    net_vat: Decimal
    documents: list = field(default_factory=list)
    warnings: dict = field(default_factory=dict)

    @property
    def is_refund(self) -> bool:
        return self.net_vat < 0


def _line_sums(kind, start, end):
    """{vat_rate: (subtotal, vat)} for issued documents of `kind` dated in the period."""
    rows = (
        InvoiceLine.objects.filter(
            invoice__kind=kind, invoice__status=Invoice.Status.ISSUED,
            invoice__issue_date__range=(start, end),
        )
        .values("vat_rate")
        .annotate(amount=Sum("subtotal"), vat=Sum("vat"))
    )
    return {Decimal(r["vat_rate"]): (r["amount"], r["vat"]) for r in rows}


def _sales_box(invoices, credits, standard: bool) -> Box:
    def pick(sums):
        return [v for rate, v in sums.items() if (rate == STANDARD_RATE) == standard]

    amount = sum((a for a, _ in pick(invoices)), ZERO)
    vat = sum((v for _, v in pick(invoices)), ZERO)
    adj_amount = sum((a for a, _ in pick(credits)), ZERO)
    adj_vat = sum((v for _, v in pick(credits)), ZERO)
    return Box(money(amount), money(-adj_amount), money(vat - adj_vat))


def _documents(start, end, expenses):
    docs = []
    lines = (
        InvoiceLine.objects.filter(invoice__status=Invoice.Status.ISSUED, invoice__issue_date__range=(start, end))
        .values("invoice", "invoice__kind", "invoice__issue_date", "invoice__number", "invoice__buyer_name", "vat_rate")
        .annotate(amount=Sum("subtotal"), vat=Sum("vat"))
        .order_by("invoice__issue_date", "invoice__number", "vat_rate")
    )
    for row in lines:
        sign = -1 if row["invoice__kind"] == Invoice.Kind.CREDIT_NOTE else 1
        docs.append(Document(
            row["invoice__kind"], row["invoice__issue_date"], row["invoice__number"], row["invoice__buyer_name"],
            Decimal(row["vat_rate"]), money(sign * row["amount"]), money(sign * row["vat"]),
            reverse("invoicing:detail", args=[row["invoice"]]),
        ))
    for e in expenses.order_by("date", "number"):
        docs.append(Document(
            "expense", e.date, e.number, e.vendor_name, Decimal(e.vat_rate),
            e.amount_excl_vat, e.vat_amount, e.get_absolute_url(),
        ))
    return docs


def vat_return(start: dt.date, end: dt.date) -> VatReturn:
    invoices = _line_sums(Invoice.Kind.INVOICE, start, end)
    credits = _line_sums(Invoice.Kind.CREDIT_NOTE, start, end)
    sales_standard = _sales_box(invoices, credits, standard=True)
    sales_zero = _sales_box(invoices, credits, standard=False)
    total_sales = Box(
        sales_standard.amount + sales_zero.amount,
        sales_standard.adjustment + sales_zero.adjustment,
        sales_standard.vat + sales_zero.vat,
    )

    expenses = Expense.objects.approved().filter(date__range=(start, end))

    def purchase_box(qs):
        agg = qs.aggregate(a=Sum("amount_excl_vat"), v=Sum("vat_amount"))
        return Box(money(agg["a"] or ZERO), ZERO, money(agg["v"] or ZERO))

    purchases_standard = purchase_box(expenses.filter(vat_rate=STANDARD_RATE))
    purchases_zero = purchase_box(expenses.exclude(vat_rate=STANDARD_RATE))
    total_purchases = Box(
        purchases_standard.amount + purchases_zero.amount, ZERO, purchases_standard.vat + purchases_zero.vat
    )

    output_vat, input_vat = total_sales.vat, total_purchases.vat
    return VatReturn(
        start, end, sales_standard, sales_zero, total_sales,
        purchases_standard, purchases_zero, total_purchases,
        output_vat, input_vat, money(output_vat - input_vat),
        documents=_documents(start, end, expenses),
        warnings={
            "draft_invoices": Invoice.objects.filter(
                status=Invoice.Status.DRAFT, issue_date__range=(start, end)
            ).count(),
            "unapproved_expenses": Expense.objects.filter(
                status__in=[Expense.Status.DRAFT, Expense.Status.SUBMITTED], date__range=(start, end)
            ).count(),
        },
    )


def csv_rows(report: VatReturn):
    yield ["Type", "Date", "Reference", "Party", "VAT rate", "Amount excl. VAT", "VAT"]
    for d in report.documents:
        yield [d.kind, d.date.isoformat(), d.reference, d.party, f"{d.rate:.0f}%", f"{d.amount:.2f}", f"{d.vat:.2f}"]
