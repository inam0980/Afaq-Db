"""Employee loans and salary advances, repaid by monthly payroll deductions.

A request is approved by someone with `loans.approve_loan`; from its first
deduction month the installment is taken from each payroll until the balance
is zero. Repayments are recorded only when a payroll run is approved, so a
draft run can be recalculated freely without touching any balance."""

import datetime as dt
import math

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from django.db.models import Sum
from django.urls import reverse
from django.utils.translation import gettext_lazy as _
from simple_history.models import HistoricalRecords

from core.money import money
from hr.models import Employee
from payroll.models import ZERO, Payslip, money_field


class LoanQuerySet(models.QuerySet):
    def active(self):
        """Approved and not yet fully repaid."""
        return self.filter(status=Loan.Status.APPROVED).annotate(
            _repaid=models.functions.Coalesce(Sum("repayments__amount"), ZERO)
        ).filter(amount__gt=models.F("_repaid"))


class Loan(models.Model):
    class Kind(models.TextChoices):
        ADVANCE = "advance", _("Salary advance")
        LOAN = "loan", _("Loan")

    class Status(models.TextChoices):
        PENDING = "pending", _("Pending approval")
        APPROVED = "approved", _("Approved")
        REJECTED = "rejected", _("Rejected")

    employee = models.ForeignKey(Employee, on_delete=models.PROTECT, related_name="loans",
                                 verbose_name=_("employee"))
    kind = models.CharField(_("type"), max_length=20, choices=Kind.choices, default=Kind.LOAN)
    amount = money_field(_("amount"), min_value=money("0.01"))
    installment = money_field(_("monthly installment"), min_value=money("0.01"))
    first_month = models.DateField(
        _("first deduction month"), help_text=_("Deductions start with this month's payroll.")
    )
    reason = models.CharField(_("reason"), max_length=200, blank=True)
    status = models.CharField(_("status"), max_length=20, choices=Status.choices, default=Status.PENDING)

    requested_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="+")
    created_at = models.DateTimeField(auto_now_add=True)
    decided_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, null=True,
                                   blank=True, related_name="+")
    decided_at = models.DateTimeField(null=True, blank=True)
    decision_note = models.CharField(_("decision note"), max_length=200, blank=True)

    history = HistoricalRecords()
    objects = LoanQuerySet.as_manager()

    class Meta:
        ordering = ["-created_at"]
        permissions = [("approve_loan", "Can approve or reject loans and advances")]
        verbose_name = _("loan / advance")
        verbose_name_plural = _("loans and advances")

    def __str__(self):
        return f"{self.get_kind_display()} {self.amount} - {self.employee.full_name}"

    def get_absolute_url(self):
        return reverse("loans:detail", args=[self.pk])

    def clean(self):
        if self.amount and self.installment and self.installment > self.amount:
            raise ValidationError({"installment": _("The installment cannot be more than the amount.")})

    def save(self, *args, **kwargs):
        if self.first_month:
            self.first_month = self.first_month.replace(day=1)
        super().save(*args, **kwargs)

    @property
    def repaid(self):
        return self.repayments.aggregate(t=Sum("amount"))["t"] or ZERO

    @property
    def outstanding(self):
        return self.amount - self.repaid

    @property
    def is_settled(self) -> bool:
        return self.status == self.Status.APPROVED and self.outstanding <= 0

    @property
    def months(self) -> int:
        """Planned number of monthly installments."""
        return math.ceil(self.amount / self.installment)

    @property
    def last_month(self) -> dt.date:
        index = self.first_month.month - 1 + self.months - 1
        return dt.date(self.first_month.year + index // 12, index % 12 + 1, 1)


class LoanRepayment(models.Model):
    loan = models.ForeignKey(Loan, on_delete=models.PROTECT, related_name="repayments")
    payslip = models.ForeignKey(Payslip, on_delete=models.PROTECT, related_name="loan_repayments")
    amount = money_field(_("amount"), min_value=money("0.01"))

    class Meta:
        ordering = ["payslip__run__year", "payslip__run__month"]
        constraints = [
            models.UniqueConstraint(fields=["loan", "payslip"], name="uniq_repayment_per_payslip"),
        ]
        verbose_name = _("loan repayment")
        verbose_name_plural = _("loan repayments")

    def __str__(self):
        return f"{self.loan} / {self.payslip.run}: {self.amount}"
