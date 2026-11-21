from decimal import Decimal

from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.validators import MinValueValidator
from django.db import connection, models
from django.db.models import Count, Q, Sum
from django.urls import reverse
from django.utils import timezone
from django.utils.translation import gettext_lazy as _
from simple_history.models import HistoricalRecords

from expenses.validators import split_vat, validate_receipt_file, validate_saudi_vat_number

ZERO = Decimal("0")
EXPENSE_NO_SEQUENCE = "expenses_expense_no_seq"


class ExpenseLocked(Exception):
    """Raised on any attempt to change or delete an approved expense."""


class ExpenseCategory(models.Model):
    code = models.CharField(_("code"), max_length=20, unique=True)
    name_en = models.CharField(_("name (English)"), max_length=100)
    name_ar = models.CharField(_("name (Arabic)"), max_length=100, blank=True)
    is_active = models.BooleanField(_("active"), default=True)

    class Meta:
        ordering = ["name_en"]
        verbose_name = _("expense category")
        verbose_name_plural = _("expense categories")

    def __str__(self):
        return self.name_en


class ExpenseQuerySet(models.QuerySet):
    def for_month(self, year: int, month: int):
        return self.filter(date__year=year, date__month=month)

    def approved(self):
        return self.filter(status=Expense.Status.APPROVED)

    def search(self, query: str):
        qs = self
        for term in (query or "").split():
            qs = qs.filter(
                Q(number__icontains=term)
                | Q(description__icontains=term)
                | Q(vendor_name__icontains=term)
                | Q(invoice_number__icontains=term)
            )
        return qs

    def totals(self) -> dict:
        agg = self.aggregate(
            count=Count("id"), total=Sum("total"), vat=Sum("vat_amount"), excl=Sum("amount_excl_vat")
        )
        return {k: (v if v is not None else ZERO) for k, v in agg.items()}

    def by_category(self):
        return (
            self.values("category__name_en")
            .annotate(amount=Sum("total"), count=Count("id"))
            .order_by("-amount", "category__name_en")
        )


class Expense(models.Model):
    class Status(models.TextChoices):
        DRAFT = "draft", _("Draft")
        SUBMITTED = "submitted", _("Submitted")
        APPROVED = "approved", _("Approved")
        REJECTED = "rejected", _("Rejected")

    class PaymentMethod(models.TextChoices):
        CASH = "cash", _("Cash")
        BANK = "bank", _("Bank transfer")
        CARD = "card", _("Card")

    class VatRate(models.IntegerChoices):
        STANDARD = 15, _("15% (standard)")
        ZERO = 0, _("0% / exempt / no VAT invoice")

    number = models.CharField(_("number"), max_length=20, unique=True, editable=False, blank=True)
    date = models.DateField(_("date"))
    category = models.ForeignKey(
        ExpenseCategory, on_delete=models.PROTECT, related_name="expenses", verbose_name=_("category")
    )
    description = models.CharField(_("description"), max_length=200)
    vendor_name = models.CharField(_("vendor"), max_length=150, blank=True)
    vendor_vat_number = models.CharField(
        _("vendor VAT number"), max_length=15, blank=True, validators=[validate_saudi_vat_number]
    )
    invoice_number = models.CharField(_("vendor invoice no."), max_length=50, blank=True)

    total = models.DecimalField(
        _("total incl. VAT"), max_digits=12, decimal_places=2,
        validators=[MinValueValidator(Decimal("0.01"))],
    )
    vat_rate = models.DecimalField(
        _("VAT rate"), max_digits=5, decimal_places=2, choices=VatRate.choices, default=Decimal("15")
    )
    vat_amount = models.DecimalField(_("VAT"), max_digits=12, decimal_places=2, default=ZERO, editable=False)
    amount_excl_vat = models.DecimalField(
        _("amount excl. VAT"), max_digits=12, decimal_places=2, default=ZERO, editable=False
    )
    payment_method = models.CharField(
        _("paid by"), max_length=20, choices=PaymentMethod.choices, default=PaymentMethod.CASH
    )
    receipt = models.FileField(
        _("receipt"), upload_to="receipts/%Y/%m/", blank=True, validators=[validate_receipt_file]
    )

    status = models.CharField(_("status"), max_length=20, choices=Status.choices, default=Status.DRAFT)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="+", verbose_name=_("created by")
    )
    created_at = models.DateTimeField(auto_now_add=True)
    submitted_at = models.DateTimeField(null=True, blank=True)
    decided_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, null=True, blank=True, related_name="+",
    )
    decided_at = models.DateTimeField(null=True, blank=True)
    rejection_reason = models.CharField(_("rejection reason"), max_length=300, blank=True)

    history = HistoricalRecords()
    objects = ExpenseQuerySet.as_manager()

    class Meta:
        ordering = ["-date", "-number"]
        permissions = [("approve_expense", "Can approve or reject expenses")]
        verbose_name = _("expense")
        verbose_name_plural = _("expenses")

    def __str__(self):
        return f"{self.number} - {self.description}"

    def get_absolute_url(self):
        return reverse("expenses:detail", args=[self.pk])

    @property
    def is_editable(self) -> bool:
        return self.status in (self.Status.DRAFT, self.Status.REJECTED)

    def clean(self):
        errors = {}
        if self.vat_rate and not self.vendor_vat_number:
            errors["vendor_vat_number"] = _(
                "VAT can only be claimed with the vendor's VAT number. Enter it or choose 0% VAT."
            )
        if self.date and self.date > timezone.localdate():
            errors["date"] = _("Expense date cannot be in the future.")
        if errors:
            raise ValidationError(errors)

    def _ensure_unlocked(self):
        # Check the DB, not the possibly stale in-memory status.
        if self.pk and Expense.objects.filter(pk=self.pk, status=self.Status.APPROVED).exists():
            raise ExpenseLocked(f"Expense {self.number} is approved and locked.")

    def save(self, *args, **kwargs):
        self._ensure_unlocked()
        if self.total is not None:
            self.amount_excl_vat, self.vat_amount = split_vat(self.total, Decimal(self.vat_rate))
        if not self.number:
            self.number = self._next_number()
        super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        self._ensure_unlocked()
        return super().delete(*args, **kwargs)

    @staticmethod
    def _next_number() -> str:
        with connection.cursor() as cursor:
            cursor.execute("SELECT nextval(%s)", [EXPENSE_NO_SEQUENCE])
            (value,) = cursor.fetchone()
        return f"EXP-{value:05d}"
