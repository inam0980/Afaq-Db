import calendar
import datetime as dt
from decimal import Decimal

from django.conf import settings
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models
from django.db.models import Count, Sum
from django.utils.translation import gettext_lazy as _
from simple_history.models import HistoricalRecords

from hr.models import Employee

ZERO = Decimal("0")
MIN_BASIC = Decimal("0.01")


def money_field(label, min_value=ZERO, **kwargs):
    return models.DecimalField(
        label,
        max_digits=12,
        decimal_places=2,
        validators=[MinValueValidator(min_value)],
        **kwargs,
    )


class SalaryStructureQuerySet(models.QuerySet):
    def current_for(self, employee, on_date: dt.date):
        """The structure in force on `on_date`, or None."""
        return (
            self.filter(employee=employee, effective_from__lte=on_date)
            .order_by("-effective_from")
            .first()
        )


class SalaryStructure(models.Model):
    """An employee's fixed monthly pay from `effective_from` until the next one.
    Never edit an old structure for a raise — add a new one with a new date."""

    employee = models.ForeignKey(
        Employee,
        on_delete=models.PROTECT,
        related_name="salary_structures",
        verbose_name=_("employee"),
    )
    effective_from = models.DateField(_("effective from"))
    basic = money_field(_("basic salary"), min_value=MIN_BASIC)
    housing = money_field(_("housing allowance"), default=ZERO)
    transport = money_field(_("transport allowance"), default=ZERO)
    other = money_field(_("other allowances"), default=ZERO)

    history = HistoricalRecords()
    objects = SalaryStructureQuerySet.as_manager()

    class Meta:
        ordering = ["employee", "-effective_from"]
        constraints = [
            models.UniqueConstraint(
                fields=["employee", "effective_from"], name="uniq_salary_per_employee_date"
            ),
        ]
        verbose_name = _("salary structure")
        verbose_name_plural = _("salary structures")

    def __str__(self):
        return f"{self.employee} @ {self.effective_from}"

    @property
    def gross_fixed(self) -> Decimal:
        return self.basic + self.housing + self.transport + self.other


class GosiRate(models.Model):
    """GOSI contribution percentages, versioned by effective date so a rate
    change never alters past payrolls. Edit in admin when GOSI announces changes."""

    class Category(models.TextChoices):
        SAUDI = "saudi", _("Saudi")
        NON_SAUDI = "non_saudi", _("Non-Saudi")

    category = models.CharField(_("category"), max_length=20, choices=Category.choices)
    effective_from = models.DateField(_("effective from"))
    employee_rate = models.DecimalField(_("employee %"), max_digits=5, decimal_places=2)
    employer_rate = models.DecimalField(_("employer %"), max_digits=5, decimal_places=2)
    salary_cap = money_field(_("contribution salary cap"))

    history = HistoricalRecords()

    class Meta:
        ordering = ["category", "-effective_from"]
        constraints = [
            models.UniqueConstraint(
                fields=["category", "effective_from"], name="uniq_gosi_rate_per_date"
            ),
        ]
        verbose_name = _("GOSI rate")
        verbose_name_plural = _("GOSI rates")

    def __str__(self):
        return f"{self.get_category_display()} from {self.effective_from}"

    @classmethod
    def for_employee(cls, employee, on_date: dt.date) -> "GosiRate":
        category = cls.Category.SAUDI if employee.is_saudi else cls.Category.NON_SAUDI
        rate = (
            cls.objects.filter(category=category, effective_from__lte=on_date)
            .order_by("-effective_from")
            .first()
        )
        if rate is None:
            raise cls.DoesNotExist(f"No GOSI rate for {category} on {on_date}.")
        return rate


class PayrollLocked(Exception):
    """Raised on any attempt to change an approved (or paid) payroll."""


class PayrollRun(models.Model):
    class Status(models.TextChoices):
        DRAFT = "draft", _("Draft")
        APPROVED = "approved", _("Approved")
        PAID = "paid", _("Paid")

    year = models.PositiveSmallIntegerField(
        _("year"), validators=[MinValueValidator(2000), MaxValueValidator(2100)]
    )
    month = models.PositiveSmallIntegerField(
        _("month"), validators=[MinValueValidator(1), MaxValueValidator(12)]
    )
    status = models.CharField(
        _("status"), max_length=20, choices=Status.choices, default=Status.DRAFT
    )
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, null=True, blank=True,
        related_name="+",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    approved_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, null=True, blank=True,
        related_name="+",
    )
    approved_at = models.DateTimeField(null=True, blank=True)
    paid_at = models.DateTimeField(null=True, blank=True)

    history = HistoricalRecords()

    class Meta:
        ordering = ["-year", "-month"]
        constraints = [
            models.UniqueConstraint(fields=["year", "month"], name="uniq_payroll_run_month"),
        ]
        permissions = [("approve_payrollrun", "Can approve and mark payroll runs as paid")]
        verbose_name = _("payroll run")
        verbose_name_plural = _("payroll runs")

    def __str__(self):
        return f"{self.year}-{self.month:02d}"

    def get_absolute_url(self):
        from django.urls import reverse

        return reverse("payroll:run_detail", args=[self.pk])

    @property
    def period_start(self) -> dt.date:
        return dt.date(self.year, self.month, 1)

    @property
    def period_end(self) -> dt.date:
        return dt.date(self.year, self.month, calendar.monthrange(self.year, self.month)[1])

    @property
    def is_locked(self) -> bool:
        return self.status != self.Status.DRAFT

    def delete(self, *args, **kwargs):
        if self.is_locked:
            raise PayrollLocked(f"Payroll {self} is {self.status} and cannot be deleted.")
        return super().delete(*args, **kwargs)

    def totals(self) -> dict:
        result = self.payslips.aggregate(
            count=Count("id"),
            gross=Sum("gross"),
            total_deductions=Sum("total_deductions"),
            gosi_employee=Sum("gosi_employee"),
            gosi_employer=Sum("gosi_employer"),
            net=Sum("net"),
        )
        return {k: (v if v is not None else ZERO) for k, v in result.items()}


class Payslip(models.Model):
    run = models.ForeignKey(
        PayrollRun, on_delete=models.CASCADE, related_name="payslips", verbose_name=_("payroll run")
    )
    employee = models.ForeignKey(
        Employee, on_delete=models.PROTECT, related_name="payslips", verbose_name=_("employee")
    )

    # Inputs entered for the month
    overtime_hours = models.DecimalField(
        _("overtime hours"), max_digits=6, decimal_places=2, default=ZERO,
        validators=[MinValueValidator(ZERO)],
    )
    absence_days = models.DecimalField(
        _("absence days"), max_digits=4, decimal_places=1, default=ZERO,
        validators=[MinValueValidator(ZERO), MaxValueValidator(Decimal(30))],
    )
    additions = money_field(_("other additions"), default=ZERO)
    deductions = money_field(_("other deductions"), default=ZERO)
    note = models.CharField(_("note"), max_length=200, blank=True)

    # Snapshot of the calculation (kept as-is once the run is approved)
    days_not_employed = models.PositiveSmallIntegerField(default=0)
    leave_days = models.DecimalField(
        _("unpaid leave days"), max_digits=5, decimal_places=2, default=ZERO, editable=False,
        help_text=_("Unpaid leave and reduced-pay sick days from approved leave (Art. 117)."),
    )
    basic = money_field(_("basic"), default=ZERO)
    housing = money_field(_("housing"), default=ZERO)
    transport = money_field(_("transport"), default=ZERO)
    other = money_field(_("other allowances"), default=ZERO)
    gross_fixed = money_field(_("fixed salary"), default=ZERO)
    overtime = money_field(_("overtime"), default=ZERO)
    absence = money_field(_("absence deduction"), default=ZERO)
    loan_deduction = money_field(_("loan / advance repayment"), default=ZERO, editable=False)
    gosi_employee = money_field(_("GOSI (employee)"), default=ZERO)
    gosi_employer = money_field(_("GOSI (employer)"), default=ZERO)
    gross = money_field(_("gross pay"), default=ZERO)
    total_deductions = money_field(_("total deductions"), default=ZERO)
    net = money_field(_("net pay"), default=ZERO)
    bank_name = models.CharField(_("bank name"), max_length=100, blank=True)
    iban = models.CharField(_("IBAN"), max_length=34, blank=True)

    history = HistoricalRecords()

    class Meta:
        ordering = ["employee__employee_no"]
        constraints = [
            models.UniqueConstraint(fields=["run", "employee"], name="uniq_payslip_per_run"),
        ]
        verbose_name = _("payslip")
        verbose_name_plural = _("payslips")

    def __str__(self):
        return f"{self.run} / {self.employee}"

    def _ensure_unlocked(self):
        # Check the DB, not the possibly stale in-memory run.
        if PayrollRun.objects.filter(pk=self.run_id).exclude(status=PayrollRun.Status.DRAFT).exists():
            raise PayrollLocked(f"Payroll {self.run} is locked; payslips cannot change.")

    def save(self, *args, **kwargs):
        self._ensure_unlocked()
        super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        self._ensure_unlocked()
        return super().delete(*args, **kwargs)
