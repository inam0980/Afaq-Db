from decimal import Decimal

from django.conf import settings
from django.core.validators import MinValueValidator
from django.db import connection, models
from django.db.models import Q
from django.urls import reverse
from django.utils.translation import gettext_lazy as _
from simple_history.models import HistoricalRecords

from customers.models import Customer
from hr.models import Employee

JOB_NO_SEQUENCE = "jobs_job_no_seq"


class JobQuerySet(models.QuerySet):
    def open(self):
        return self.filter(status__in=Job.OPEN_STATUSES)

    def search(self, query: str):
        qs = self
        for term in (query or "").split():
            qs = qs.filter(
                Q(number__icontains=term)
                | Q(title__icontains=term)
                | Q(customer__name__icontains=term)
                | Q(site_address__icontains=term)
            )
        return qs


class Job(models.Model):
    class Status(models.TextChoices):
        NEW = "new", _("New")
        SCHEDULED = "scheduled", _("Scheduled")
        IN_PROGRESS = "in_progress", _("In progress")
        COMPLETED = "completed", _("Completed")
        CANCELLED = "cancelled", _("Cancelled")

    class ServiceType(models.TextChoices):
        AC = "ac", _("AC maintenance")
        PLUMBING = "plumbing", _("Plumbing")
        ELECTRICAL = "electrical", _("Electrical")
        PAINTING = "painting", _("Painting")
        CARPENTRY = "carpentry", _("Carpentry")
        CLEANING = "cleaning", _("Cleaning")
        OTHER = "other", _("Other")

    class Priority(models.TextChoices):
        NORMAL = "normal", _("Normal")
        URGENT = "urgent", _("Urgent")

    OPEN_STATUSES = (Status.NEW, Status.SCHEDULED, Status.IN_PROGRESS)
    FINAL_STATUSES = (Status.COMPLETED, Status.CANCELLED)
    TRANSITIONS = {
        Status.NEW: (Status.SCHEDULED, Status.IN_PROGRESS, Status.CANCELLED),
        Status.SCHEDULED: (Status.IN_PROGRESS, Status.CANCELLED),
        Status.IN_PROGRESS: (Status.COMPLETED, Status.CANCELLED),
        Status.COMPLETED: (),
        Status.CANCELLED: (),
    }

    number = models.CharField(_("job no."), max_length=20, unique=True, editable=False, blank=True)
    customer = models.ForeignKey(
        Customer, on_delete=models.PROTECT, related_name="jobs", verbose_name=_("customer")
    )
    service_type = models.CharField(_("service"), max_length=20, choices=ServiceType.choices)
    title = models.CharField(_("title"), max_length=150)
    description = models.TextField(_("description"), blank=True)
    site_address = models.CharField(
        _("site address"), max_length=255, blank=True,
        help_text=_("Leave empty to use the customer's address."),
    )
    priority = models.CharField(_("priority"), max_length=10, choices=Priority.choices, default=Priority.NORMAL)
    status = models.CharField(_("status"), max_length=20, choices=Status.choices, default=Status.NEW)
    scheduled_date = models.DateField(_("scheduled date"), null=True, blank=True)
    technicians = models.ManyToManyField(
        Employee, related_name="jobs", blank=True, verbose_name=_("technicians")
    )
    quoted_amount = models.DecimalField(
        _("quoted amount (excl. VAT)"), max_digits=12, decimal_places=2, null=True, blank=True,
        validators=[MinValueValidator(Decimal("0"))],
    )
    cancel_reason = models.CharField(_("cancel reason"), max_length=300, blank=True)

    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="+", verbose_name=_("created by")
    )
    created_at = models.DateTimeField(auto_now_add=True)
    started_at = models.DateTimeField(null=True, blank=True)
    completed_at = models.DateTimeField(null=True, blank=True)

    history = HistoricalRecords()
    objects = JobQuerySet.as_manager()

    class Meta:
        ordering = ["-created_at", "-number"]
        verbose_name = _("job")
        verbose_name_plural = _("jobs")

    def __str__(self):
        return f"{self.number} - {self.title}"

    def get_absolute_url(self):
        return reverse("jobs:detail", args=[self.pk])

    @property
    def location(self) -> str:
        return self.site_address or self.customer.address_line

    @property
    def is_editable(self) -> bool:
        return self.status not in self.FINAL_STATUSES

    @property
    def next_statuses(self):
        return self.TRANSITIONS.get(self.status, ())

    def save(self, *args, **kwargs):
        if not self.number:
            self.number = self._next_number()
        super().save(*args, **kwargs)

    @staticmethod
    def _next_number() -> str:
        with connection.cursor() as cursor:
            cursor.execute("SELECT nextval(%s)", [JOB_NO_SEQUENCE])
            (value,) = cursor.fetchone()
        return f"JOB-{value:05d}"
