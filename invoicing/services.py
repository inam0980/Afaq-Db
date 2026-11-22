"""Invoice workflow: draft -> issue (numbered, frozen). Credit notes follow in part B."""

import datetime as dt
from decimal import Decimal

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import connection, transaction
from django.db.models import Sum
from django.utils import timezone
from django.utils.translation import gettext as _

from core.money import money
from invoicing.models import INVOICE_NO_SEQUENCE, Invoice, InvoiceLine
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


def _next_number() -> str:
    with connection.cursor() as cursor:
        cursor.execute("SELECT nextval(%s)", [INVOICE_NO_SEQUENCE])
        (value,) = cursor.fetchone()
    return f"INV-{value:05d}"


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
    inv.invoice_type = Invoice.Type.STANDARD if customer.vat_number else Invoice.Type.SIMPLIFIED
    inv.buyer_name = customer.name
    inv.buyer_vat_number = customer.vat_number
    inv.buyer_address = customer.address_line

    inv.number = _next_number()
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
