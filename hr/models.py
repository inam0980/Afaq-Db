import datetime as dt

from django.core.exceptions import ValidationError
from django.db import connection, models
from django.db.models import Q
from django.db.models.functions import Least
from django.urls import reverse
from django.utils import timezone
from django.utils.translation import gettext_lazy as _
from simple_history.models import HistoricalRecords

from hr.constants import NATIONALITY_CHOICES, SAUDI
from hr.validators import (
    normalize_iban,
    validate_id_number,
    validate_saudi_iban,
    validate_saudi_mobile,
)

# PostgreSQL sequence (created in migration 0002) — race-free employee numbers.
EMPLOYEE_NO_SEQUENCE = "hr_employee_no_seq"


class Department(models.Model):
    code = models.CharField(_("code"), max_length=20, unique=True)
    name_en = models.CharField(_("name (English)"), max_length=100)
    name_ar = models.CharField(_("name (Arabic)"), max_length=100, blank=True)

    class Meta:
        ordering = ["name_en"]
        verbose_name = _("department")
        verbose_name_plural = _("departments")

    def __str__(self):
        return self.name_en


class EmployeeQuerySet(models.QuerySet):
    def active(self):
        return self.exclude(status=Employee.Status.TERMINATED)

    def search(self, query: str):
        qs = self
        for term in (query or "").split():
            qs = qs.filter(
                Q(first_name__icontains=term)
                | Q(last_name__icontains=term)
                | Q(name_ar__icontains=term)
                | Q(employee_no__icontains=term)
                | Q(id_number__icontains=term)
                | Q(job_title__icontains=term)
            )
        return qs

    def with_expiring_documents(self, within_days: int = 30, today: dt.date | None = None):
        """Active employees whose iqama/ID or passport expires within the window
        (already-expired included), soonest-expiring document first."""
        today = today or timezone.localdate()
        cutoff = today + dt.timedelta(days=within_days)
        return (
            self.active()
            .filter(Q(id_expiry__lte=cutoff) | Q(passport_expiry__lte=cutoff))
            .annotate(next_expiry=Least("id_expiry", "passport_expiry"))
            .order_by("next_expiry", "employee_no")
        )


class Employee(models.Model):
    class Gender(models.TextChoices):
        MALE = "M", _("Male")
        FEMALE = "F", _("Female")

    class Status(models.TextChoices):
        ACTIVE = "active", _("Active")
        ON_LEAVE = "on_leave", _("On leave")
        TERMINATED = "terminated", _("Terminated")

    employee_no = models.CharField(
        _("employee no."), max_length=20, unique=True, editable=False
    )

    # Personal
    first_name = models.CharField(_("first name"), max_length=100)
    last_name = models.CharField(_("last name"), max_length=100)
    name_ar = models.CharField(_("full name (Arabic)"), max_length=200, blank=True)
    nationality = models.CharField(
        _("nationality"), max_length=2, choices=NATIONALITY_CHOICES, default=SAUDI
    )
    date_of_birth = models.DateField(_("date of birth"))
    gender = models.CharField(_("gender"), max_length=1, choices=Gender.choices)

    # Identity documents
    id_number = models.CharField(
        _("national ID / iqama no."),
        max_length=10,
        unique=True,
        validators=[validate_id_number],
    )
    id_expiry = models.DateField(_("ID / iqama expiry"))
    passport_no = models.CharField(_("passport no."), max_length=20, blank=True)
    passport_expiry = models.DateField(_("passport expiry"), null=True, blank=True)

    # Employment
    department = models.ForeignKey(
        Department,
        on_delete=models.PROTECT,
        related_name="employees",
        null=True,
        blank=True,
        verbose_name=_("department"),
    )
    job_title = models.CharField(_("job title"), max_length=100)
    hire_date = models.DateField(_("hire date"))
    termination_date = models.DateField(_("termination date"), null=True, blank=True)
    status = models.CharField(
        _("status"), max_length=20, choices=Status.choices, default=Status.ACTIVE
    )

    # Contact
    mobile = models.CharField(
        _("mobile"), max_length=10, blank=True, validators=[validate_saudi_mobile]
    )
    email = models.EmailField(_("email"), blank=True)

    # Bank (needed for WPS salary transfer)
    bank_name = models.CharField(_("bank name"), max_length=100, blank=True)
    iban = models.CharField(
        _("IBAN"), max_length=34, blank=True, validators=[validate_saudi_iban]
    )

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    history = HistoricalRecords()
    objects = EmployeeQuerySet.as_manager()

    class Meta:
        ordering = ["employee_no"]
        verbose_name = _("employee")
        verbose_name_plural = _("employees")

    def __str__(self):
        return f"{self.employee_no} - {self.full_name}"

    def get_absolute_url(self):
        return reverse("hr:employee_detail", args=[self.pk])

    @property
    def full_name(self) -> str:
        return f"{self.first_name} {self.last_name}".strip()

    @property
    def is_saudi(self) -> bool:
        return self.nationality == SAUDI

    def clean(self):
        errors = {}

        if self.id_number and self.nationality:
            expected = "1" if self.is_saudi else "2"
            if not self.id_number.startswith(expected):
                errors["id_number"] = (
                    _("Saudi nationals must have a National ID starting with 1.")
                    if self.is_saudi
                    else _("Non-Saudi employees must have an Iqama number starting with 2.")
                )

        if self.date_of_birth and self.hire_date and self.date_of_birth > self.hire_date:
            errors["date_of_birth"] = _("Date of birth must be before the hire date.")

        if self.termination_date and self.hire_date and self.termination_date < self.hire_date:
            errors["termination_date"] = _("Termination date cannot be before the hire date.")
        elif self.status == self.Status.TERMINATED and not self.termination_date:
            errors["termination_date"] = _("A terminated employee needs a termination date.")

        if self.termination_date and self.status != self.Status.TERMINATED:
            errors["status"] = _("Set status to Terminated when a termination date is given.")

        if errors:
            raise ValidationError(errors)

    def save(self, *args, **kwargs):
        self.iban = normalize_iban(self.iban)
        if not self.employee_no:
            self.employee_no = self._next_employee_no()
        super().save(*args, **kwargs)

    @staticmethod
    def _next_employee_no() -> str:
        with connection.cursor() as cursor:
            cursor.execute("SELECT nextval(%s)", [EMPLOYEE_NO_SEQUENCE])
            (value,) = cursor.fetchone()
        return f"EMP-{value:05d}"
