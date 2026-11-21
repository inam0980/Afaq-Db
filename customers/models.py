from django.core.exceptions import ValidationError
from django.db import models
from django.db.models import Q
from django.urls import reverse
from django.utils.translation import gettext_lazy as _
from simple_history.models import HistoricalRecords

from core.validators import validate_building_number, validate_postal_code, validate_saudi_vat_number
from hr.validators import validate_saudi_mobile

# Needed on a B2B (standard) ZATCA tax invoice for a VAT-registered buyer.
B2B_ADDRESS_FIELDS = ("street", "building_number", "city", "postal_code")


class CustomerQuerySet(models.QuerySet):
    def active(self):
        return self.filter(is_active=True)

    def search(self, query: str):
        qs = self
        for term in (query or "").split():
            qs = qs.filter(
                Q(name__icontains=term)
                | Q(name_ar__icontains=term)
                | Q(mobile__icontains=term)
                | Q(vat_number__icontains=term)
            )
        return qs


class Customer(models.Model):
    class Kind(models.TextChoices):
        INDIVIDUAL = "individual", _("Individual")
        BUSINESS = "business", _("Business")

    name = models.CharField(_("name"), max_length=150)
    name_ar = models.CharField(_("name (Arabic)"), max_length=150, blank=True)
    kind = models.CharField(_("type"), max_length=20, choices=Kind.choices, default=Kind.INDIVIDUAL)
    mobile = models.CharField(_("mobile"), max_length=10, validators=[validate_saudi_mobile])
    email = models.EmailField(_("email"), blank=True)
    vat_number = models.CharField(
        _("VAT number"), max_length=15, blank=True, validators=[validate_saudi_vat_number]
    )

    # Saudi National Address
    building_number = models.CharField(
        _("building no."), max_length=4, blank=True, validators=[validate_building_number]
    )
    street = models.CharField(_("street"), max_length=120, blank=True)
    district = models.CharField(_("district"), max_length=120, blank=True)
    city = models.CharField(_("city"), max_length=80, blank=True)
    postal_code = models.CharField(
        _("postal code"), max_length=5, blank=True, validators=[validate_postal_code]
    )

    is_active = models.BooleanField(_("active"), default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    history = HistoricalRecords()
    objects = CustomerQuerySet.as_manager()

    class Meta:
        ordering = ["name"]
        constraints = [
            models.UniqueConstraint(
                fields=["vat_number"],
                condition=~Q(vat_number=""),
                name="uniq_customer_vat_number",
                violation_error_code="unique",
                violation_error_message=_("Another customer already has this VAT number."),
            ),
        ]
        verbose_name = _("customer")
        verbose_name_plural = _("customers")

    def __str__(self):
        return self.name

    def get_absolute_url(self):
        return reverse("customers:detail", args=[self.pk])

    @property
    def address_line(self) -> str:
        street = " ".join(p for p in (self.building_number, self.street) if p)
        city = " ".join(p for p in (self.city, self.postal_code) if p)
        return ", ".join(p for p in (street, self.district, city) if p)

    def clean(self):
        errors = {}
        if self.vat_number and self.kind == self.Kind.INDIVIDUAL:
            errors["vat_number"] = _("Only business customers have a VAT number.")
        if self.vat_number and self.kind == self.Kind.BUSINESS:
            for field in B2B_ADDRESS_FIELDS:
                if not getattr(self, field):
                    errors[field] = _("Required for a VAT-registered business (shown on tax invoices).")
        if errors:
            raise ValidationError(errors)
