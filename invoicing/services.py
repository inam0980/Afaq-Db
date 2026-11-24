"""Invoice workflow: draft -> issue (numbered, frozen); payments; credit notes."""

import datetime as dt
from decimal import Decimal

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import connection, transaction
from django.db.models import Sum
from django.utils import timezone
from django.utils.translation import gettext as _

from core.money import money
from invoicing.models import (
    CREDIT_NOTE_NO_SEQUENCE,
    INVOICE_NO_SEQUENCE,
    Invoice,
    InvoiceLine,
    Payment,
)
from invoicing.zatca import qr_payload
from jobs.models import Job

ZERO = Decimal("0")


def payment_terms_days() -> int:
    return getattr(settings, "INVOICE_PAYMENT_TERMS_DAYS", 30)


def recalculate(invoice: Invoice) -> Invoice:
    sums = invoice.lines.aggregate(s=Sum("subtotal"), v=Sum("vat"), t=Sum("total"))
    invoice.subtotal = money(sums["s"] or ZERO)
    invoice.vat_amount = money(sums["v"] or ZERO)
    invoice.total = money(sums["t"] or ZERO)
    invoice.save(update_fields=["subtotal", "vat_amount", "total"])
    return invoice


def _next_number(credit_note: bool = False) -> str:
    sequence, prefix = (CREDIT_NOTE_NO_SEQUENCE, "CN") if credit_note else (INVOICE_NO_SEQUENCE, "INV")
    with connection.cursor() as cursor:
        cursor.execute("SELECT nextval(%s)", [sequence])
        (value,) = cursor.fetchone()
    return f"{prefix}-{value:05d}"


def _balance_of(invoice: Invoice) -> Decimal:
    from invoicing.balances import with_balances

    return with_balances(Invoice.objects.filter(pk=invoice.pk)).get().balance


@transaction.atomic
def issue(invoice: Invoice, user) -> Invoice:
    inv = Invoice.objects.select_for_update().select_related("customer").get(pk=invoice.pk)
    if not inv.is_draft:
        raise ValidationError(_("This invoice is already issued."))
    recalculate(inv)
    if not inv.lines.exists():
        raise ValidationError(_("Add at least one line before issuing."))
    if inv.total <= 0:
        raise ValidationError(_("An invoice total must be more than zero."))
    if inv.issue_date > timezone.localdate():
        raise ValidationError(_("An invoice cannot be issued with a future date."))
    inv.full_clean(exclude=["created_by"])

    customer = inv.customer
    customer.full_clean()          # e.g. VAT-registered business must have a full address

    if inv.is_credit_note:
        if not inv.reason.strip():
            raise ValidationError(_("A credit note needs a reason."))
        balance = _balance_of(inv.original)
        if inv.total > balance:
            raise ValidationError(
                _("The credit note (%(cn)s) exceeds what is still owed on %(no)s (%(bal)s).")
                % {"cn": inv.total, "no": inv.original.number, "bal": balance}
            )
        inv.invoice_type = inv.original.invoice_type
        inv.due_date = inv.issue_date
    else:
        inv.invoice_type = Invoice.Type.STANDARD if customer.vat_number else Invoice.Type.SIMPLIFIED
    inv.buyer_name = customer.name
    inv.buyer_vat_number = customer.vat_number
    inv.buyer_address = customer.address_line

    inv.number = _next_number(credit_note=inv.is_credit_note)
    inv.status = Invoice.Status.ISSUED
    inv.issued_by = user
    inv.issued_at = timezone.now()
    inv.save()
    return inv


@transaction.atomic
def create_from_job(job: Job, user) -> Invoice:
    job = Job.objects.select_for_update().get(pk=job.pk)
    if job.status != Job.Status.COMPLETED:
        raise ValidationError(_("Only completed jobs can be invoiced."))
    if not job.quoted_amount:
        raise ValidationError(_("Set the job's quoted amount before invoicing it."))
    if job.invoices.exists():
        raise ValidationError(_("This job already has an invoice."))

    today = timezone.localdate()
    invoice = Invoice.objects.create(
        customer=job.customer,
        job=job,
        issue_date=today,
        due_date=today + dt.timedelta(days=payment_terms_days()),
        created_by=user,
    )
    InvoiceLine.objects.create(
        invoice=invoice,
        description=f"{job.get_service_type_display()}: {job.title} ({job.number})",
        quantity=Decimal("1"),
        unit_price=job.quoted_amount,
        vat_rate=Decimal("15"),
    )
    return recalculate(invoice)


def qr_for(invoice: Invoice) -> str | None:
    if invoice.is_draft:
        return None
    return qr_payload(
        seller_name=settings.COMPANY_NAME,
        vat_number=settings.COMPANY_VAT_NUMBER,
        timestamp=invoice.issued_at,
        total=invoice.total,
        vat_total=invoice.vat_amount,
    )


# --- credit notes -------------------------------------------------------------------

@transaction.atomic
def create_credit_note(original: Invoice, user, reason: str) -> Invoice:
    """Draft credit note copying the original's lines; reduce them, then issue."""
    original = Invoice.objects.select_for_update().get(pk=original.pk)
    reason = (reason or "").strip()
    if not reason:
        raise ValidationError(_("Give the reason for the credit note."))
    if original.is_draft or original.is_credit_note:
        raise ValidationError(_("Credit notes can only be raised against issued invoices."))
    if _balance_of(original) <= 0:
        raise ValidationError(_("Nothing is owed on this invoice any more; a refund is needed instead."))

    today = timezone.localdate()
    note = Invoice.objects.create(
        kind=Invoice.Kind.CREDIT_NOTE,
        original=original,
        reason=reason,
        customer=original.customer,
        job=original.job,
        issue_date=today,
        due_date=today,
        created_by=user,
    )
    for line in original.lines.all():
        InvoiceLine.objects.create(
            invoice=note, description=line.description, quantity=line.quantity,
            unit_price=line.unit_price, vat_rate=line.vat_rate,
        )
    return recalculate(note)


# --- payments -----------------------------------------------------------------------

@transaction.atomic
def record_payment(
    invoice: Invoice, user, *, amount: Decimal, date: dt.date, method: str, reference: str = "", note: str = ""
) -> Payment:
    invoice = Invoice.objects.select_for_update().get(pk=invoice.pk)
    if invoice.is_draft or invoice.is_credit_note:
        raise ValidationError(_("Payments can only be recorded against issued invoices."))
    if date < invoice.issue_date:
        raise ValidationError({"date": _("Payment date cannot be before the invoice date.")})
    if date > timezone.localdate():
        raise ValidationError({"date": _("Payment date cannot be in the future.")})
    balance = _balance_of(invoice)
    if amount > balance:
        raise ValidationError({"amount": _("Only %(bal)s is still owed on this invoice.") % {"bal": balance}})

    payment = Payment(
        invoice=invoice, date=date, amount=money(amount), method=method,
        reference=reference, note=note, received_by=user,
    )
    payment.full_clean()
    payment.save()
    return payment


@transaction.atomic
def delete_payment(payment: Payment) -> None:
    """Undo a wrongly entered payment (the deletion stays in the audit history)."""
    payment.delete()
