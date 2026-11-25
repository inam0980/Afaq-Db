"""Integration tests: EGS unit, document chain (ICV + previous hash), local validation."""

import datetime as dt

import pytest
from django.core.exceptions import ValidationError
from django.core.management import call_command
from django.utils import timezone

from customers.tests.factories import BusinessCustomerFactory
from invoicing.tests.factories import invoice_with_lines, issued_invoice
from zatca import services
from zatca.constants import FIRST_PIH
from zatca.models import EgsUnit, ZatcaDocument

pytestmark = pytest.mark.django_db


@pytest.fixture
def egs():
    return services.setup_demo_egs()


def test_demo_egs_is_created_once_and_key_is_encrypted(egs):
    assert services.setup_demo_egs() == egs
    assert EgsUnit.objects.count() == 1
    assert egs.environment == EgsUnit.Environment.DEMO
    raw = EgsUnit.objects.values_list("private_key", flat=True).get()
    assert "PRIVATE KEY" not in raw                       # stored encrypted
    assert "BEGIN PRIVATE KEY" in egs.private_key_pem      # decrypted on use
    assert "BEGIN CERTIFICATE" in egs.certificate_pem


def test_encryption_depends_on_secret_key(egs, settings):
    settings.SECRET_KEY = "a-completely-different-secret-key-for-this-test-0123456789"
    with pytest.raises(ValueError):
        EgsUnit.objects.get().private_key_pem


def test_first_document_starts_the_chain(egs):
    doc = services.generate(issued_invoice(customer=BusinessCustomerFactory()))
    assert (doc.icv, doc.previous_hash) == (1, FIRST_PIH)
    assert doc.status == ZatcaDocument.Status.GENERATED
    assert doc.xml.startswith("<?xml")
    egs.refresh_from_db()
    assert (egs.last_icv, egs.last_hash) == (1, doc.invoice_hash)


def test_next_document_links_to_the_previous_hash(egs):
    first = services.generate(issued_invoice())
    second = services.generate(issued_invoice())
    assert (second.icv, second.previous_hash) == (2, first.invoice_hash)
    assert first.uuid != second.uuid


def test_one_document_per_invoice(egs):
    inv = issued_invoice()
    services.generate(inv)
    with pytest.raises(ValidationError):
        services.generate(inv)
    assert ZatcaDocument.objects.count() == 1


def test_drafts_are_refused(egs):
    with pytest.raises(ValidationError):
        services.generate(invoice_with_lines())
    egs.refresh_from_db()
    assert egs.last_icv == 0


def test_without_an_egs_unit():
    with pytest.raises(ValidationError) as err:
        services.generate(issued_invoice())
    assert "zatca_demo_setup" in str(err.value)


def test_local_check_passes_and_catches_tampering(egs):
    doc = services.generate(issued_invoice(customer=BusinessCustomerFactory()))
    assert services.local_check(doc) == []
    doc.xml = doc.xml.replace("1150.00", "1.00")
    assert services.local_check(doc)


def test_file_name_follows_the_standard(egs, settings):
    inv = issued_invoice()
    doc = services.generate(inv)
    local = timezone.localtime(inv.issued_at)
    assert doc.file_name == (f"{settings.COMPANY_VAT_NUMBER}_{inv.issue_date:%Y%m%d}T{local:%H%M%S}_"
                             f"{inv.number.replace('/', '-')}.xml")


def test_file_name_replaces_non_alphanumerics(egs):
    doc = services.generate(issued_invoice())
    doc.invoice.number = "INV/2026_0001"
    assert doc.file_name.endswith("_INV-2026-0001.xml")


def test_management_command(capsys):
    call_command("zatca_demo_setup")
    assert EgsUnit.objects.count() == 1
    assert "demo" in capsys.readouterr().out.lower()
    call_command("zatca_demo_setup")
    assert EgsUnit.objects.count() == 1


def test_str():
    egs = services.setup_demo_egs()
    doc = services.generate(issued_invoice())
    assert str(egs) == "AFAQ-EGS-DEMO (Demo)"
    assert str(doc) == f"{doc.invoice.number} · ICV 1"
