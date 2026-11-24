from django.conf import settings
from django.db import models
from django.db.models import Q
from django.urls import reverse
from django.utils.translation import gettext_lazy as _
from simple_history.models import HistoricalRecords

from expenses.validators import validate_receipt_file
from hr.models import Employee


class LeaveType(models.Model):
    code = models.CharField(_("code"), max_length=20, unique=True)
    name_en = models.CharField(_("name (English)"), max_length=100)
    name_ar = models.CharField(_("name (Arabic)"), max_length=100, blank=True)
    is_paid = models.BooleanField(_("paid"), default=True)
    deducts_salary = models.BooleanField(_("deducted from salary"), default=False)
    uses_annual_balance = models.BooleanField(_("uses annual leave balance"), default=False)
    counts_calendar_days = models.BooleanField(
        _("counts calendar days"), default=False,
        help_text=_("Otherwise only working days (Sunday to Thursday) are counted."),
    )
    max_days = models.PositiveSmallIntegerField(_("max days per request"), null=True, blank=True)
    requires_attachment = models.BooleanField(_("needs a document"), default=False)
    is_active = models.BooleanField(_("active"), default=True)

    class Meta:
        ordering = ["name_en"]
        verbose_name = _("leave type")
        verbose_name_plural = _("leave types")

    def __str__(self):
        return self.name_en


class LeaveRequestQuerySet(models.QuerySet):
    def blocking(self):
        """Requests that hold the dates: pending or approved."""
        return self.filter(status__in=[LeaveRequest.Status.PENDING, LeaveRequest.Status.APPROVED])

    def on_leave(self, day):
        return self.filter(status=LeaveRequest.Status.APPROVED, start_date__lte=day, end_date__gte=day)

    def overlapping(self, start, end):
        return self.filter(Q(start_date__lte=end) & Q(end_date__gte=start))


class LeaveRequest(models.Model):
    class Status(models.TextChoices):
        PENDING = "pending", _("Pending")
        APPROVED = "approved", _("Approved")
        REJECTED = "rejected", _("Rejected")
        CANCELLED = "cancelled", _("Cancelled")

    employee = models.ForeignKey(
        Employee, on_delete=models.PROTECT, related_name="leave_requests", verbose_name=_("employee")
    )
    leave_type = models.ForeignKey(
        LeaveType, on_delete=models.PROTECT, related_name="requests", verbose_name=_("leave type")
    )
    start_date = models.DateField(_("from"))
    end_date = models.DateField(_("to"))
    days = models.PositiveSmallIntegerField(_("days"), editable=False)
    reason = models.CharField(_("reason"), max_length=300, blank=True)
    attachment = models.FileField(
        _("document"), upload_to="leave/%Y/%m/", blank=True, validators=[validate_receipt_file],
        help_text=_("Medical certificate or other supporting document (PDF, JPG or PNG)."),
    )
    status = models.CharField(_("status"), max_length=10, choices=Status.choices, default=Status.PENDING)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, null=True, blank=True, related_name="+"
    )
    created_at = models.DateTimeField(auto_now_add=True)
    decided_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, null=True, blank=True, related_name="+"
    )
    decided_at = models.DateTimeField(null=True, blank=True)
    decision_note = models.CharField(_("decision note"), max_length=300, blank=True)

    history = HistoricalRecords()
    objects = LeaveRequestQuerySet.as_manager()

    class Meta:
        ordering = ["-start_date", "-pk"]
        permissions = [("approve_leaverequest", "Can approve or reject leave requests")]
        verbose_name = _("leave request")
        verbose_name_plural = _("leave requests")

    def __str__(self):
        return f"{self.employee.full_name}: {self.leave_type} {self.start_date} → {self.end_date}"

    def get_absolute_url(self):
        return reverse("leave:detail", args=[self.pk])
