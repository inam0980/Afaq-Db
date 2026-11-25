"""Generate signed ZATCA documents in a strict chain: each invoice gets the next
counter (ICV) and carries the hash of the previous one (PIH)."""

import uuid

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils.translation import gettext as _

from invoicing.models import Invoice
from zatca import signing
from zatca.constants import FIRST_PIH
from zatca.models import EgsUnit, ZatcaDocument
from zatca.xml_builder import build_invoice

DEMO_NAME = "AFAQ-EGS-DEMO"


def setup_demo_egs() -> EgsUnit:
    """An offline demo unit with a self-signed certificate (not valid with ZATCA)."""
    existing = EgsUnit.objects.first()
    if existing:
        return existing
    key = signing.generate_private_key(settings.ZATCA_CURVE)
    egs = EgsUnit(name=DEMO_NAME, environment=EgsUnit.Environment.DEMO,
                  certificate=signing.demo_certificate(key, common_name=DEMO_NAME,
                                                       vat_number=settings.COMPANY_VAT_NUMBER))
    egs.private_key_pem = key
    egs.save()
    return egs


@transaction.atomic
def generate(invoice: Invoice) -> ZatcaDocument:
    inv = (Invoice.objects.select_for_update(of=("self",)).select_related("customer", "original")
           .get(pk=invoice.pk))
    if inv.is_draft:
        raise ValidationError(_("Issue the invoice before generating its ZATCA XML."))
    if ZatcaDocument.objects.filter(invoice=inv).exists():
        raise ValidationError(_("The ZATCA XML for this invoice has already been generated."))
    egs = EgsUnit.objects.select_for_update().first()
    if egs is None:
        raise ValidationError(_("No ZATCA e-invoicing unit is set up. Run: python manage.py zatca_demo_setup"))

    icv, pih = egs.last_icv + 1, egs.last_hash or FIRST_PIH
    doc_uuid = uuid.uuid4()
    root = build_invoice(inv, uuid=str(doc_uuid), icv=icv, pih=pih)
    result = signing.sign_invoice(root, egs.private_key_pem, egs.certificate_pem,
                                  simplified=inv.invoice_type == Invoice.Type.SIMPLIFIED)
    doc = ZatcaDocument.objects.create(
        invoice=inv, egs=egs, uuid=doc_uuid, icv=icv, previous_hash=pih, invoice_hash=result.invoice_hash,
        xml=result.xml.decode("utf-8"), qr=result.qr,
    )
    egs.last_icv, egs.last_hash = icv, result.invoice_hash
    egs.save(update_fields=["last_icv", "last_hash"])
    return doc


def local_check(doc: ZatcaDocument) -> list[str]:
    return signing.verify(doc.xml.encode("utf-8"), doc.egs.certificate_pem)
