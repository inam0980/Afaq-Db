"""Integration tests: invoice pages, line formset, issue, print view, job button."""

from decimal import Decimal as D

import pytest
from django.urls import reverse

from customers.tests.factories import BusinessCustomerFactory, CustomerFactory
from invoicing.models import Invoice
from invoicing.services import issue
from invoicing.tests.factories import invoice_with_lines
from invoicing.tests.test_from_job import completed_job

pytestmark = pytest.mark.django_db

LIST_URL = reverse("invoicing:list")
CREATE_URL = reverse("invoicing:create")
CLERK = ("view_invoice", "add_invoice", "change_invoice", "view_customer", "view_job")


@pytest.fixture
def clerk(client_with_perms):
    """Prepares invoices but cannot issue them."""
    return client_with_perms(*CLERK)


@pytest.fixture
def issuer(client_with_perms):
    return client_with_perms(*CLERK, "issue_invoice")


def url(name, inv):
    return reverse(f"invoicing:{name}", args=[inv.pk])


def form_data(customer, lines, **overrides):
    data = {
        "customer": customer.pk,
        "job": "",
        "issue_date": "2026-01-10",
        "due_date": "2026-02-09",
        "notes": "",
        "lines-TOTAL_FORMS": str(len(lines) + 1),
        "lines-INITIAL_FORMS": "0",
        "lines-MIN_NUM_FORMS": "0",
        "lines-MAX_NUM_FORMS": "1000",
    }
    for i, (desc, qty, price, vat) in enumerate(lines):
        data.update({
            f"lines-{i}-description": desc, f"lines-{i}-quantity": qty,
            f"lines-{i}-unit_price": price, f"lines-{i}-vat_rate": vat,
        })
    # The extra blank row, as a browser submits it (defaults pre-filled, untouched).
    blank = len(lines)
    data.update({
        f"lines-{blank}-description": "", f"lines-{blank}-quantity": "1",
        f"lines-{blank}-unit_price": "", f"lines-{blank}-vat_rate": "15",
    })
    data.update(overrides)
    return data


def test_requires_permission(viewer_client):
    assert viewer_client.get(LIST_URL).status_code == 403


def test_create_draft_with_lines(clerk):
    customer = CustomerFactory()
    response = clerk.post(CREATE_URL, form_data(customer, [("AC service", "2", "300", "15"), ("Gas", "1", "100", "0")]))

    inv = Invoice.objects.get()
    assert response.status_code == 302
    assert response.url == url("detail", inv)
    assert inv.status == Invoice.Status.DRAFT
    assert inv.lines.count() == 2
    assert (inv.subtotal, inv.vat_amount, inv.total) == (D("700.00"), D("90.00"), D("790.00"))
    assert inv.created_by.username == "custom_user"


def test_create_requires_at_least_one_line(clerk):
    response = clerk.post(CREATE_URL, form_data(CustomerFactory(), []))
    assert response.status_code == 200
    assert not Invoice.objects.exists()


def test_create_shows_line_errors(clerk):
    response = clerk.post(CREATE_URL, form_data(CustomerFactory(), [("Bad", "0", "100", "15")]))
    assert response.context["lines"].errors
    assert not Invoice.objects.exists()


def test_create_form_renders_with_customer_preselected(clerk):
    c = CustomerFactory()
    response = clerk.get(CREATE_URL, {"customer": c.pk})
    assert response.status_code == 200
    assert response.context["form"].initial["customer"] == str(c.pk)


def test_edit_draft_replaces_lines(clerk):
    inv = invoice_with_lines("1000")
    line = inv.lines.get()
    data = form_data(inv.customer, [], **{
        "lines-TOTAL_FORMS": "1", "lines-INITIAL_FORMS": "1",
        "lines-0-id": str(line.pk), "lines-0-invoice": str(inv.pk),
        "lines-0-description": "Changed", "lines-0-quantity": "1",
        "lines-0-unit_price": "500", "lines-0-vat_rate": "15",
    })
    response = clerk.post(url("update", inv), data)
    inv.refresh_from_db()
    assert response.status_code == 302
    assert inv.total == D("575.00")


def test_edit_form_renders(clerk):
    assert clerk.get(url("update", invoice_with_lines())).status_code == 200


def test_issued_invoice_cannot_be_edited(clerk, admin_user):
    inv = invoice_with_lines()
    issue(inv, admin_user)
    assert clerk.get(url("update", inv)).status_code == 409


def test_clerk_cannot_issue(clerk):
    inv = invoice_with_lines()
    assert clerk.post(url("issue", inv)).status_code == 403


def test_issuer_issues(issuer):
    inv = invoice_with_lines()
    response = issuer.post(url("issue", inv))
    inv.refresh_from_db()
    assert response.status_code == 302
    assert inv.status == Invoice.Status.ISSUED and inv.number


def test_issue_requires_post(issuer):
    assert issuer.get(url("issue", invoice_with_lines())).status_code == 405


def test_issue_error_shown(issuer, admin_user):
    from invoicing.tests.factories import InvoiceFactory

    inv = InvoiceFactory()   # no lines
    response = issuer.post(url("issue", inv), follow=True)
    assert any(m.level_tag == "error" for m in response.context["messages"])


def test_issued_standard_invoice_print_view(issuer, admin_user, settings):
    settings.COMPANY_NAME = "Afaq Test Co"
    settings.COMPANY_VAT_NUMBER = "310122393500003"
    inv = invoice_with_lines("1000", customer=BusinessCustomerFactory(name="Riyadh Towers"))
    issue(inv, admin_user)
    html = issuer.get(url("detail", inv)).content.decode()

    assert inv.number in html
    assert "فاتورة ضريبية" in html and "Tax Invoice" in html
    assert "مبسطة" not in html
    assert "Riyadh Towers" in html and "310122393500003" in html
    assert 'class="zatca-qr"' in html         # ZATCA QR (sidebar icons are SVG too)
    assert "1150.00" in html


def test_simplified_invoice_print_view(issuer, admin_user):
    inv = invoice_with_lines(customer=CustomerFactory())
    issue(inv, admin_user)
    html = issuer.get(url("detail", inv)).content.decode()
    assert "فاتورة ضريبية مبسطة" in html and "Simplified Tax Invoice" in html


def test_draft_has_no_qr_and_is_marked_draft(clerk):
    html = clerk.get(url("detail", invoice_with_lines())).content.decode()
    assert "DRAFT" in html
    assert 'class="zatca-qr"' not in html


def test_list_filters(clerk, admin_user):
    a = invoice_with_lines(customer=CustomerFactory(name="Alpha"))
    b = invoice_with_lines(customer=CustomerFactory(name="Beta"))
    issue(b, admin_user)

    def pks(**params):
        return [i.pk for i in clerk.get(LIST_URL, params).context["invoices"]]

    assert pks(status="draft") == [a.pk]
    assert pks(status="issued") == [b.pk]
    assert pks(q="alph") == [a.pk]


# --- from job -------------------------------------------------------------------

def test_invoice_button_on_completed_job(clerk):
    job = completed_job(quoted_amount=D("650"))
    html = clerk.get(reverse("jobs:detail", args=[job.pk])).content.decode()
    assert reverse("invoicing:from_job", args=[job.pk]) in html


def test_create_from_job_via_post(clerk):
    job = completed_job(quoted_amount=D("650"))
    response = clerk.post(reverse("invoicing:from_job", args=[job.pk]))
    inv = Invoice.objects.get()
    assert response.status_code == 302
    assert response.url == url("update", inv)
    assert inv.job == job


def test_create_from_job_error_shown(clerk):
    from jobs.tests.factories import JobFactory

    job = JobFactory(quoted_amount=D("1"))   # not completed
    response = clerk.post(reverse("invoicing:from_job", args=[job.pk]), follow=True)
    assert not Invoice.objects.exists()
    assert any(m.level_tag == "error" for m in response.context["messages"])


def test_job_page_links_existing_invoice(clerk):
    job = completed_job(quoted_amount=D("650"))
    clerk.post(reverse("invoicing:from_job", args=[job.pk]))
    inv = Invoice.objects.get()
    html = clerk.get(reverse("jobs:detail", args=[job.pk])).content.decode()
    assert url("detail", inv) in html
    assert reverse("invoicing:from_job", args=[job.pk]) not in html


# --- sidebar & admin -------------------------------------------------------------

def test_sidebar_link_with_permission(clerk):
    assert LIST_URL in clerk.get(reverse("home")).content.decode()


def test_sidebar_hides_invoices_without_permission(viewer_client):
    assert LIST_URL not in viewer_client.get(reverse("home")).content.decode()


def test_admin_loads_and_cannot_delete_issued(admin_client, admin_user, rf):
    from django.contrib.admin.sites import site

    inv = invoice_with_lines()
    issue(inv, admin_user)
    inv.refresh_from_db()
    assert admin_client.get(reverse("admin:invoicing_invoice_changelist")).status_code == 200
    request = rf.get("/")
    request.user = admin_user
    model_admin = site._registry[Invoice]
    assert model_admin.has_delete_permission(request, inv) is False
    assert "delete_selected" not in model_admin.get_actions(request)


def test_job_of_another_customer_is_rejected(clerk):
    from jobs.tests.factories import JobFactory

    other_customers_job = JobFactory()
    data = form_data(CustomerFactory(), [("Work", "1", "100", "15")], job=str(other_customers_job.pk))
    response = clerk.post(CREATE_URL, data)
    assert "job" in response.context["form"].errors
    assert not Invoice.objects.exists()


def test_admin_change_page_for_draft_and_readonly_for_issued(admin_client, admin_user, rf):
    from django.contrib.admin.sites import site

    draft = invoice_with_lines()
    assert admin_client.get(reverse("admin:invoicing_invoice_change", args=[draft.pk])).status_code == 200
    issue(draft, admin_user)
    draft.refresh_from_db()
    request = rf.get("/")
    request.user = admin_user
    assert site._registry[Invoice].has_change_permission(request, draft) is False


def test_issued_invoice_page_keeps_the_frozen_buyer_name(issuer, admin_user):
    customer = BusinessCustomerFactory(name="Old Name LLC")
    inv = invoice_with_lines(customer=customer)
    issue(inv, admin_user)
    customer.name = "New Name LLC"
    customer.save()

    html = issuer.get(url("detail", inv)).content.decode()

    assert "Old Name LLC" in html
    assert "New Name LLC" not in html


def test_no_invoice_button_on_unfinished_job(clerk):
    from jobs.tests.factories import JobFactory

    job = JobFactory(quoted_amount=D("650"))          # still "new"
    html = clerk.get(reverse("jobs:detail", args=[job.pk])).content.decode()
    assert reverse("invoicing:from_job", args=[job.pk]) not in html
