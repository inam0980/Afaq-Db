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
    class Status(models.TextChoices):
        DRAFT = "draft", _("Draft")
        ISSUED = "issued", _("Issued")

    class Type(models.TextChoices):
        STANDARD = "standard", _("Tax invoice (B2B)")
        SIMPLIFIED = "simplified", _("Simplified tax invoice (B2C)")

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
        permissions = [("issue_invoice", "Can issue (finalise) invoices")]
        verbose_name = _("invoice")
        verbose_name_plural = _("invoices")

    def __str__(self):
        return self.number or "Draft invoice"

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
