"""Integration tests: expense pages, uploads, workflow, protected receipts."""

import datetime as dt
from decimal import Decimal as D

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from django.urls import reverse

from expenses.models import Expense
from expenses.services import submit
from expenses.tests.factories import ExpenseCategoryFactory, ExpenseFactory, receipt_file

pytestmark = pytest.mark.django_db

LIST_URL = reverse("expenses:list")
CREATE_URL = reverse("expenses:create")
CLERK_PERMS = ("view_expense", "add_expense", "change_expense")


@pytest.fixture
def clerk(client_with_perms):
    """Enters expenses; cannot approve."""
    return client_with_perms(*CLERK_PERMS)


@pytest.fixture
def approver_client(django_user_model):
    from django.contrib.auth.models import Permission
    from django.test import Client

    user = django_user_model.objects.create_user("boss", password="Test-pass-123")
    user.user_permissions.add(
        *Permission.objects.filter(codename__in=[*CLERK_PERMS, "approve_expense"])
    )
    c = Client()
    c.force_login(user)
    return c


def form_data(**overrides):
    data = {
        "date": "2026-01-15",
        "category": ExpenseCategoryFactory().pk,
        "description": "Copper pipes",
        "vendor_name": "Saco",
        "vendor_vat_number": "300000000000003",
        "invoice_number": "INV-77",
        "total": "230.00",
        "vat_rate": "15",
        "payment_method": "card",
        "receipt": receipt_file(),
    }
    data.update(overrides)
    return data


def url(name, e):
    return reverse(f"expenses:{name}", args=[e.pk])


# --- access ------------------------------------------------------------------

def test_list_requires_permission(viewer_client):
    assert viewer_client.get(LIST_URL).status_code == 403


def test_anonymous_redirected(client):
    assert client.get(LIST_URL).status_code == 302


# --- create ------------------------------------------------------------------

def test_create_with_receipt(clerk, settings):
    response = clerk.post(CREATE_URL, form_data())

    e = Expense.objects.get()
    assert response.status_code == 302
    assert response.url == url("detail", e)
    assert e.vat_amount == D("30.00")
    assert e.status == Expense.Status.DRAFT
    assert e.created_by.username == "custom_user"
    assert e.receipt.name.startswith("receipts/")
    assert str(settings.MEDIA_ROOT) in e.receipt.path


def test_create_rejects_bad_file_type(clerk):
    bad = SimpleUploadedFile("evil.exe", b"MZ", content_type="application/octet-stream")
    response = clerk.post(CREATE_URL, form_data(receipt=bad))
    assert "receipt" in response.context["form"].errors
    assert not Expense.objects.exists()


def test_create_rejects_vat_without_vendor_number(clerk):
    response = clerk.post(CREATE_URL, form_data(vendor_vat_number=""))
    assert "vendor_vat_number" in response.context["form"].errors


# --- list --------------------------------------------------------------------

def test_list_filters_and_totals(clerk):
    fuel = ExpenseCategoryFactory(code="FUELX", name_en="Fuel")
    ExpenseFactory(category=fuel, total=D("115"), date=dt.date(2026, 1, 5))
    ExpenseFactory(total=D("50"), vat_rate=D("0"), vendor_vat_number="", date=dt.date(2026, 1, 6))
    ExpenseFactory(category=fuel, total=D("999"), date=dt.date(2026, 2, 1))

    ctx = clerk.get(LIST_URL, {"month": "2026-01"}).context
    assert ctx["totals"]["total"] == D("165.00")
    assert ctx["totals"]["count"] == 2

    ctx = clerk.get(LIST_URL, {"month": "2026-01", "category": fuel.pk}).context
    assert ctx["totals"]["total"] == D("115.00")


def test_list_status_filter_and_search(clerk):
    a = ExpenseFactory(description="Diesel")
    b = ExpenseFactory(description="Paint")
    submit(a, a.created_by)

    assert [e.pk for e in clerk.get(LIST_URL, {"status": "submitted"}).context["expenses"]] == [a.pk]
    assert [e.pk for e in clerk.get(LIST_URL, {"q": "pain"}).context["expenses"]] == [b.pk]
    assert [e.pk for e in clerk.get(LIST_URL, {"q": b.number}).context["expenses"]] == [b.pk]


@pytest.mark.parametrize("bad", ["2026-13", "2026-00", "abc", "2026"])
def test_list_ignores_bad_month(clerk, bad):
    e = ExpenseFactory()
    response = clerk.get(LIST_URL, {"month": bad})
    assert response.status_code == 200
    # An invalid month is ignored (all expenses shown), not turned into an empty filter.
    assert [x.pk for x in response.context["expenses"]] == [e.pk]


# --- edit / submit -------------------------------------------------------------

def test_edit_draft(clerk):
    e = ExpenseFactory()
    data = form_data(description="Changed", receipt="")
    response = clerk.post(url("update", e), data)
    e.refresh_from_db()
    assert response.status_code == 302
    assert e.description == "Changed"
    assert e.receipt                       # existing receipt kept


def test_cannot_edit_submitted_expense(clerk):
    e = ExpenseFactory()
    submit(e, e.created_by)
    assert clerk.get(url("update", e)).status_code == 409


def test_submit_via_post(clerk):
    e = ExpenseFactory()
    clerk.post(url("submit", e))
    e.refresh_from_db()
    assert e.status == Expense.Status.SUBMITTED


def test_submit_without_receipt_shows_error(clerk):
    e = ExpenseFactory(receipt="")
    response = clerk.post(url("submit", e), follow=True)
    e.refresh_from_db()
    assert e.status == Expense.Status.DRAFT
    assert any(m.level_tag == "error" for m in response.context["messages"])


# --- approve / reject -----------------------------------------------------------

def test_clerk_cannot_approve(clerk):
    e = ExpenseFactory()
    submit(e, e.created_by)
    assert clerk.post(url("approve", e)).status_code == 403


def test_approver_approves(approver_client):
    e = ExpenseFactory()
    submit(e, e.created_by)
    approver_client.post(url("approve", e))
    e.refresh_from_db()
    assert e.status == Expense.Status.APPROVED


def test_approver_cannot_approve_own_expense(approver_client):
    approver_client.post(CREATE_URL, form_data())
    e = Expense.objects.get()
    approver_client.post(url("submit", e))

    response = approver_client.post(url("approve", e), follow=True)

    e.refresh_from_db()
    assert e.status == Expense.Status.SUBMITTED
    assert any(m.level_tag == "error" for m in response.context["messages"])


def test_reject_with_reason(approver_client):
    e = ExpenseFactory()
    submit(e, e.created_by)
    approver_client.post(url("reject", e), {"reason": "Duplicate"})
    e.refresh_from_db()
    assert e.status == Expense.Status.REJECTED
    assert e.rejection_reason == "Duplicate"


def test_approve_requires_post(approver_client):
    e = ExpenseFactory()
    assert approver_client.get(url("approve", e)).status_code == 405


# --- receipts are not public -----------------------------------------------------

def test_receipt_download_with_permission(clerk):
    e = ExpenseFactory(receipt=receipt_file(content=b"%PDF-secret"))
    response = clerk.get(url("receipt", e))
    assert response.status_code == 200
    assert b"".join(response.streaming_content) == b"%PDF-secret"


def test_receipt_download_requires_permission(viewer_client):
    e = ExpenseFactory()
    assert viewer_client.get(url("receipt", e)).status_code == 403


def test_receipt_404_when_missing(clerk):
    e = ExpenseFactory(receipt="")
    assert clerk.get(url("receipt", e)).status_code == 404


def test_media_files_are_not_served_publicly(client):
    e = ExpenseFactory()
    assert client.get("/media/" + e.receipt.name).status_code == 404


# --- detail, sidebar, dashboard, admin --------------------------------------------

def test_detail_page(clerk):
    e = ExpenseFactory(description="Diesel for van")
    html = clerk.get(url("detail", e)).content.decode()
    assert "Diesel for van" in html
    assert e.number in html


def test_sidebar_shows_expenses_with_permission(clerk):
    assert LIST_URL in clerk.get(reverse("home")).content.decode()


def test_sidebar_hides_expenses_without_permission(viewer_client):
    assert LIST_URL not in viewer_client.get(reverse("home")).content.decode()


def test_dashboard_expense_kpis(approver_client):
    from django.utils import timezone

    today = timezone.localdate()
    approved = ExpenseFactory(date=today, total=D("115"))
    submit(approved, approved.created_by)
    approver_client.post(url("approve", approved))
    pending = ExpenseFactory(date=today)
    submit(pending, pending.created_by)

    ctx = approver_client.get(reverse("home")).context

    assert ctx["show_expenses"] is True
    assert ctx["month_expenses"] == D("115.00")
    assert ctx["pending_expenses"] == 1


def test_admin_pages_load(admin_client):
    ExpenseFactory()
    assert admin_client.get(reverse("admin:expenses_expense_changelist")).status_code == 200
    assert admin_client.get(reverse("admin:expenses_expensecategory_changelist")).status_code == 200


def test_edit_form_renders(clerk):
    e = ExpenseFactory()
    response = clerk.get(url("update", e))
    assert response.status_code == 200
    assert 'name="total"' in response.content.decode()


def test_cannot_submit_someone_elses_expense_without_change_permission(client_with_perms):
    client = client_with_perms("view_expense", "add_expense")
    e = ExpenseFactory()   # created by another user
    assert client.post(url("submit", e)).status_code == 403


def test_receipt_missing_on_disk_gives_404_not_crash(clerk):
    import os

    e = ExpenseFactory()
    os.remove(e.receipt.path)
    assert clerk.get(url("receipt", e)).status_code == 404


def test_admin_cannot_delete_approved_expense(rf, admin_user):
    from django.contrib.admin.sites import site

    e = ExpenseFactory()
    Expense.objects.filter(pk=e.pk).update(status=Expense.Status.APPROVED)
    e.refresh_from_db()
    request = rf.get("/")
    request.user = admin_user
    model_admin = site._registry[Expense]

    assert model_admin.has_delete_permission(request, e) is False
    assert model_admin.has_delete_permission(request, ExpenseFactory()) is True
    assert "delete_selected" not in model_admin.get_actions(request)
