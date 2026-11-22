from decimal import Decimal

from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.validators import MinValueValidator
from django.db import models
from django.db.models import Q
from django.urls import reverse
from django.utils.translation import gettext_lazy as _
from simple_history.models import HistoricalRecords

from core.money import money
from customers.models import Customer
from jobs.models import Job

ZERO = Decimal("0")
INVOICE_NO_SEQUENCE = "invoicing_invoice_no_seq"
CREDIT_NOTE_NO_SEQUENCE = "invoicing_credit_note_no_seq"


class InvoiceLocked(Exception):
    """Raised on any attempt to change or delete an issued invoice (or its lines)."""


def _amount(label, **kwargs):
    return models.DecimalField(label, max_digits=14, decimal_places=2, default=ZERO, editable=False, **kwargs)


class InvoiceQuerySet(models.QuerySet):
    def search(self, query: str):
        qs = self
        for term in (query or "").split():
            qs = qs.filter(
                Q(number__icontains=term)
                | Q(customer__name__icontains=term)
                | Q(buyer_name__icontains=term)
                | Q(job__number__icontains=term)
            )
        return qs


class Invoice(models.Model):
    class Kind(models.TextChoices):
        INVOICE = "invoice", _("Invoice")
        CREDIT_NOTE = "credit_note", _("Credit note")

    class Status(models.TextChoices):
        DRAFT = "draft", _("Draft")
        ISSUED = "issued", _("Issued")

    class Type(models.TextChoices):
        STANDARD = "standard", _("Tax invoice (B2B)")
        SIMPLIFIED = "simplified", _("Simplified tax invoice (B2C)")

    kind = models.CharField(_("kind"), max_length=12, choices=Kind.choices, default=Kind.INVOICE, editable=False)
    number = models.CharField(_("invoice no."), max_length=20, blank=True, default="", editable=False)
    status = models.CharField(_("status"), max_length=10, choices=Status.choices, default=Status.DRAFT)
    invoice_type = models.CharField(_("type"), max_length=12, choices=Type.choices, blank=True, editable=False)

    customer = models.ForeignKey(
        Customer, on_delete=models.PROTECT, related_name="invoices", verbose_name=_("customer")
    )
    job = models.ForeignKey(
        Job, on_delete=models.PROTECT, null=True, blank=True, related_name="invoices", verbose_name=_("job")
    )
    issue_date = models.DateField(_("issue date"))
    due_date = models.DateField(_("due date"))
    notes = models.TextField(_("notes"), blank=True)
    # Credit notes only: the invoice being corrected and why (both printed, ZATCA KSA-10).
    original = models.ForeignKey(
        "self", on_delete=models.PROTECT, null=True, blank=True, related_name="credit_notes",
        editable=False, verbose_name=_("original invoice"),
    )
    reason = models.CharField(_("reason"), max_length=200, blank=True)

    subtotal = _amount(_("subtotal (excl. VAT)"))
    vat_amount = _amount(_("VAT"))
    total = _amount(_("total (incl. VAT)"))

    # Frozen at issue so later customer edits never change a legal document.
    buyer_name = models.CharField(max_length=150, blank=True, editable=False)
    buyer_vat_number = models.CharField(max_length=15, blank=True, editable=False)
    buyer_address = models.CharField(max_length=300, blank=True, editable=False)

    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="+")
    created_at = models.DateTimeField(auto_now_add=True)
    issued_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, null=True, blank=True, related_name="+"
    )
    issued_at = models.DateTimeField(null=True, blank=True, editable=False)

    history = HistoricalRecords()
    objects = InvoiceQuerySet.as_manager()

    class Meta:
        ordering = ["-issue_date", "-created_at"]
        constraints = [
            models.UniqueConstraint(fields=["number"], condition=~Q(number=""), name="uniq_invoice_number"),
        ]
        permissions = [
            ("issue_invoice", "Can issue (finalise) invoices"),
            ("view_vat_return", "Can see the VAT return"),
        ]
        verbose_name = _("invoice")
        verbose_name_plural = _("invoices")

    def __str__(self):
        if self.number:
            return self.number
        return "Draft credit note" if self.is_credit_note else "Draft invoice"

    @property
    def is_credit_note(self) -> bool:
        return self.kind == self.Kind.CREDIT_NOTE

    # The two properties below need the balance annotations from
    # invoicing.balances.with_balances(); they are computed on demand otherwise.
    def _balance(self) -> Decimal:
        if not hasattr(self, "balance"):
            from invoicing.balances import with_balances

            annotated = with_balances(Invoice.objects.filter(pk=self.pk)).get()
            self.paid, self.credited, self.balance = annotated.paid, annotated.credited, annotated.balance
        return self.balance

    @property
    def payment_status(self) -> str | None:
        if self.is_draft or self.is_credit_note:
            return None
        if self._balance() <= 0:
            return "paid"
        return "partial" if (self.paid + self.credited) > 0 else "unpaid"

    @property
    def is_overdue(self) -> bool:
        from django.utils import timezone

        return (
            not self.is_draft and not self.is_credit_note
            and self._balance() > 0 and self.due_date < timezone.localdate()
        )

    def get_absolute_url(self):
        return reverse("invoicing:detail", args=[self.pk])

    @property
    def is_draft(self) -> bool:
        return self.status == self.Status.DRAFT

    def clean(self):
        if self.issue_date and self.due_date and self.due_date < self.issue_date:
            raise ValidationError({"due_date": _("Due date cannot be before the issue date.")})

    def ensure_draft(self):
        # Check the DB, not the possibly stale in-memory status.
        if self.pk and Invoice.objects.filter(pk=self.pk, status=self.Status.ISSUED).exists():
            raise InvoiceLocked(f"Invoice {self.number} is issued and cannot be changed.")

    def save(self, *args, **kwargs):
        self.ensure_draft()
        super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        self.ensure_draft()
        return super().delete(*args, **kwargs)


class InvoiceLine(models.Model):
    class VatRate(models.IntegerChoices):
        STANDARD = 15, _("15%")
        ZERO = 0, _("0%")

    invoice = models.ForeignKey(Invoice, on_delete=models.CASCADE, related_name="lines")
    description = models.CharField(_("description"), max_length=200)
    quantity = models.DecimalField(
        _("qty"), max_digits=10, decimal_places=2, default=Decimal("1"),
        validators=[MinValueValidator(Decimal("0.01"))],
    )
    unit_price = models.DecimalField(
        _("unit price (excl. VAT)"), max_digits=12, decimal_places=2,
        validators=[MinValueValidator(ZERO)],
    )
    vat_rate = models.DecimalField(
        _("VAT"), max_digits=5, decimal_places=2, choices=VatRate.choices, default=Decimal("15")
    )
    subtotal = _amount(_("amount"))
    vat = _amount(_("VAT amount"))
    total = _amount(_("total"))

    class Meta:
        ordering = ["pk"]
        verbose_name = _("invoice line")
        verbose_name_plural = _("invoice lines")

    def __str__(self):
        return self.description

    def save(self, *args, **kwargs):
        Invoice(pk=self.invoice_id).ensure_draft()
        self.subtotal = money(self.quantity * self.unit_price)
        self.vat = money(self.subtotal * Decimal(self.vat_rate) / 100)
        self.total = self.subtotal + self.vat
        super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        Invoice(pk=self.invoice_id).ensure_draft()
        return super().delete(*args, **kwargs)


class Payment(models.Model):
    """Money received against an issued invoice. Partial payments are allowed;
    overpayment is not (see services.record_payment)."""

    class Method(models.TextChoices):
        CASH = "cash", _("Cash")
        BANK = "bank", _("Bank transfer")
        CARD = "card", _("Card")

    invoice = models.ForeignKey(
        Invoice, on_delete=models.PROTECT, related_name="payments", verbose_name=_("invoice")
    )
    date = models.DateField(_("date"))
    amount = models.DecimalField(
        _("amount"), max_digits=14, decimal_places=2, validators=[MinValueValidator(Decimal("0.01"))]
    )
    method = models.CharField(_("method"), max_length=10, choices=Method.choices, default=Method.BANK)
    reference = models.CharField(_("reference"), max_length=100, blank=True)
    note = models.CharField(_("note"), max_length=200, blank=True)
    received_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, null=True, blank=True, related_name="+"
    )
    created_at = models.DateTimeField(auto_now_add=True)

    history = HistoricalRecords()

    class Meta:
        ordering = ["date", "pk"]
        verbose_name = _("payment")
        verbose_name_plural = _("payments")

    def __str__(self):
        return f"{self.invoice.number}: {self.amount:.2f}"
