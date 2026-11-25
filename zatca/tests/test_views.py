"""Integration tests: ZATCA panel on the invoice page, generate + download."""

import pytest
from django.urls import reverse

from customers.tests.factories import BusinessCustomerFactory
from invoicing.tests.factories import invoice_with_lines, issued_invoice
from zatca import services
from zatca.models import ZatcaDocument

pytestmark = pytest.mark.django_db


@pytest.fixture
def accountant(client_with_perms):
    return client_with_perms("view_invoice", "issue_invoice")


@pytest.fixture
def viewer(client_with_perms):
    return client_with_perms("view_invoice")


@pytest.fixture
def egs():
    return services.setup_demo_egs()


def detail(inv):
    return reverse("invoicing:detail", args=[inv.pk])


def gen_url(inv):
    return reverse("zatca:generate", args=[inv.pk])


def test_panel_offers_generation_to_issuers(accountant, egs):
    inv = issued_invoice()
    html = accountant.get(detail(inv)).content.decode()
    assert "ZATCA e-invoice (Phase 2)" in html and gen_url(inv) in html


def test_panel_hides_button_from_viewers(viewer, egs):
    inv = issued_invoice()
    html = viewer.get(detail(inv)).content.decode()
    assert gen_url(inv) not in html


def test_no_panel_on_drafts(accountant, egs):
    inv = invoice_with_lines()
    assert "ZATCA e-invoice (Phase 2)" not in accountant.get(detail(inv)).content.decode()


def test_panel_explains_missing_setup(accountant):
    inv = issued_invoice()
    html = accountant.get(detail(inv)).content.decode()
    assert "zatca_demo_setup" in html and gen_url(inv) not in html


def test_generate_and_show_result(accountant, egs):
    inv = issued_invoice(customer=BusinessCustomerFactory())
    response = accountant.post(gen_url(inv))
    assert response.status_code == 302 and response["Location"] == detail(inv)
    doc = ZatcaDocument.objects.get(invoice=inv)
    html = accountant.get(detail(inv)).content.decode()
    assert "ICV 1" in html and doc.invoice_hash in html
    assert "Signature and hash verified locally" in html
    assert reverse("zatca:download", args=[doc.pk]) in html
    assert "DEMO certificate" in html


def test_generated_invoice_prints_the_phase2_qr(accountant, egs):
    inv = issued_invoice()
    accountant.post(gen_url(inv))
    doc = ZatcaDocument.objects.get(invoice=inv)
    response = accountant.get(detail(inv))
    assert response.context["qr_payload"] == doc.qr


def test_generate_twice_shows_error(accountant, egs):
    inv = issued_invoice()
    accountant.post(gen_url(inv))
    response = accountant.post(gen_url(inv), follow=True)
    assert any(m.level_tag == "error" for m in response.context["messages"])
    assert ZatcaDocument.objects.count() == 1


def test_generate_requires_permission_and_post(viewer, egs):
    inv = issued_invoice()
    assert viewer.post(gen_url(inv)).status_code == 403
    assert not ZatcaDocument.objects.exists()


def test_generate_rejects_get(accountant, egs):
    assert accountant.get(gen_url(issued_invoice())).status_code == 405


def test_download_xml(viewer, egs):
    inv = issued_invoice()
    doc = services.generate(inv)
    response = viewer.get(reverse("zatca:download", args=[doc.pk]))
    assert response["Content-Type"] == "application/xml"
    assert response["Content-Disposition"] == f'attachment; filename="{doc.file_name}"'
    assert response.content.decode() == doc.xml


def test_download_requires_permission(no_perm_client, egs):
    doc = services.generate(issued_invoice())
    assert no_perm_client.get(reverse("zatca:download", args=[doc.pk])).status_code == 403


def test_admin_documents_are_read_only(admin_client, egs):
    doc = services.generate(issued_invoice())
    assert admin_client.get(reverse("admin:zatca_zatcadocument_change", args=[doc.pk])).status_code == 200
    assert admin_client.get(reverse("admin:zatca_zatcadocument_add")).status_code == 403
    assert admin_client.get(reverse("admin:zatca_zatcadocument_delete", args=[doc.pk])).status_code == 403
    assert admin_client.get(reverse("admin:zatca_egsunit_change", args=[egs.pk])).status_code == 200
