"""The e-invoice generation unit (EGS) and the signed documents it produced.

The EGS private key is stored encrypted with a key derived from SECRET_KEY
(Security standard §2.2.1 req. 8: protect the signing key). Changing
SECRET_KEY therefore makes the key unreadable — onboard a new unit then.
"""

import base64
import hashlib
import re

from cryptography.fernet import Fernet, InvalidToken
from django.conf import settings
from django.db import models
from django.utils import timezone
from django.utils.translation import gettext_lazy as _

from invoicing.models import Invoice


def _fernet() -> Fernet:
    digest = hashlib.sha256(f"zatca-egs-key:{settings.SECRET_KEY}".encode()).digest()
    return Fernet(base64.urlsafe_b64encode(digest))


def encrypt(text: str) -> str:
    return _fernet().encrypt(text.encode()).decode("ascii")


def decrypt(token: str) -> str:
    try:
        return _fernet().decrypt(token.encode("ascii")).decode()
    except InvalidToken as exc:
        raise ValueError("Cannot decrypt the ZATCA signing key: SECRET_KEY has changed since onboarding.") from exc


class EgsUnit(models.Model):
    class Environment(models.TextChoices):
        DEMO = "demo", _("Demo")
        SANDBOX = "sandbox", _("Developer sandbox")
        SIMULATION = "simulation", _("Simulation")
        PRODUCTION = "production", _("Production")

    name = models.CharField(_("name"), max_length=100)
    environment = models.CharField(_("environment"), max_length=20, choices=Environment.choices)
    private_key = models.TextField(editable=False)               # encrypted PEM
    certificate = models.TextField(_("certificate (PEM)"))
    last_icv = models.PositiveIntegerField(_("last invoice counter"), default=0)
    last_hash = models.CharField(_("last invoice hash"), max_length=88, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = _("ZATCA e-invoicing unit")
        verbose_name_plural = _("ZATCA e-invoicing units")

    def __str__(self):
        return f"{self.name} ({self.get_environment_display()})"

    @property
    def private_key_pem(self) -> str:
        return decrypt(self.private_key)

    @private_key_pem.setter
    def private_key_pem(self, pem: str):
        self.private_key = encrypt(pem)

    @property
    def certificate_pem(self) -> str:
        return self.certificate

    @property
    def is_demo(self) -> bool:
        return self.environment == self.Environment.DEMO


class ZatcaDocument(models.Model):
    class Status(models.TextChoices):
        GENERATED = "generated", _("Signed, not sent")
        CLEARED = "cleared", _("Cleared by ZATCA")
        REPORTED = "reported", _("Reported to ZATCA")
        REJECTED = "rejected", _("Rejected by ZATCA")

    invoice = models.OneToOneField(Invoice, on_delete=models.PROTECT, related_name="zatca_document")
    egs = models.ForeignKey(EgsUnit, on_delete=models.PROTECT, related_name="documents")
    uuid = models.UUIDField(unique=True)
    icv = models.PositiveIntegerField(_("invoice counter (ICV)"))
    previous_hash = models.CharField(_("previous invoice hash"), max_length=88)
    invoice_hash = models.CharField(_("invoice hash"), max_length=88)
    xml = models.TextField()
    qr = models.TextField()
    status = models.CharField(_("status"), max_length=20, choices=Status.choices, default=Status.GENERATED)
    response = models.JSONField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-icv"]
        constraints = [models.UniqueConstraint(fields=["egs", "icv"], name="uniq_icv_per_egs")]
        verbose_name = _("ZATCA document")
        verbose_name_plural = _("ZATCA documents")

    def __str__(self):
        return f"{self.invoice.number} · ICV {self.icv}"

    @property
    def file_name(self) -> str:
        """XML standard §14: VAT_YYYYMMDDTHHMMSS_number.xml"""
        inv = self.invoice
        time = timezone.localtime(inv.issued_at).strftime("%H%M%S")
        number = re.sub(r"[^A-Za-z0-9]", "-", inv.number)
        return f"{settings.COMPANY_VAT_NUMBER}_{inv.issue_date:%Y%m%d}T{time}_{number}.xml"
