"""Integration tests: payroll run pages, HTMX payslip editing, approval flow."""

import datetime as dt
from decimal import Decimal as D

import pytest
from django.urls import reverse

from hr.tests.factories import EmployeeFactory
from payroll.models import PayrollRun
from payroll.services import approve_run, generate_payslips
from payroll.tests.factories import PayrollRunFactory, SalaryStructureFactory

pytestmark = pytest.mark.django_db

RUNS_URL = reverse("payroll:run_list")
MANAGER_PERMS = (
    "view_payrollrun", "add_payrollrun", "change_payrollrun", "view_payslip", "change_payslip",
)


@pytest.fixture
def manager_client(client_with_perms):
    """Prepares payroll but cannot approve it."""
    return client_with_perms(*MANAGER_PERMS)


@pytest.fixture
def approver_client(client_with_perms):
    return client_with_perms(*MANAGER_PERMS, "approve_payrollrun")


@pytest.fixture
def run_with_slip():
    emp = EmployeeFactory(first_name="Ahmed", last_name="Khan")
    SalaryStructureFactory(employee=emp)
    run = PayrollRunFactory()
    generate_payslips(run)
    return run


def run_url(run):
    return reverse("payroll:run_detail", args=[run.pk])


def edit_url(slip):
    return reverse("payroll:payslip_edit", args=[slip.pk])


# --- list & create ------------------------------------------------------------

def test_run_list_requires_permission(viewer_client):
    assert viewer_client.get(RUNS_URL).status_code == 403


def test_run_list_shows_runs(manager_client, run_with_slip):
    html = manager_client.get(RUNS_URL).content.decode()
    assert "2026-01" in html


def test_create_run_generates_payslips(manager_client):
    SalaryStructureFactory()
    response = manager_client.post(RUNS_URL, {"year": "2026", "month": "3"})

    run = PayrollRun.objects.get(year=2026, month=3)
    assert response.status_code == 302
    assert response.url == run_url(run)
    assert run.payslips.count() == 1
    assert run.created_by is not None


def test_create_duplicate_month_shows_error(manager_client, run_with_slip):
    response = manager_client.post(RUNS_URL, {"year": "2026", "month": "1"})
    assert response.status_code == 200
    assert response.context["form"].errors
    assert PayrollRun.objects.count() == 1


def test_create_invalid_month_shows_error(manager_client):
    response = manager_client.post(RUNS_URL, {"year": "2026", "month": "13"})
    assert "month" in response.context["form"].errors
    assert not PayrollRun.objects.exists()


def test_viewer_cannot_create_run(client_with_perms):
    client = client_with_perms("view_payrollrun")
    assert client.post(RUNS_URL, {"year": "2026", "month": "3"}).status_code == 403


# --- detail -------------------------------------------------------------------

def test_detail_shows_payslips_totals_and_missing_salaries(manager_client, run_with_slip):
    EmployeeFactory(first_name="Nosalary", last_name="Person")

    response = manager_client.get(run_url(run_with_slip))
    html = response.content.decode()

    assert response.status_code == 200
    assert "Ahmed Khan" in html
    assert response.context["totals"]["net"] == D("7200.00")
    assert [e.first_name for e in response.context["missing"]] == ["Nosalary"]
    assert "Nosalary Person" in html


# --- HTMX payslip editing ------------------------------------------------------

def test_edit_get_returns_form_row(manager_client, run_with_slip):
    slip = run_with_slip.payslips.get()
    response = manager_client.get(edit_url(slip), HTTP_HX_REQUEST="true")

    html = response.content.decode()
    assert response.status_code == 200
    assert "<html" not in html
    assert 'name="overtime_hours"' in html


def test_edit_post_updates_and_returns_row(manager_client, run_with_slip):
    slip = run_with_slip.payslips.get()
    data = {"overtime_hours": "10", "absence_days": "0", "additions": "0", "deductions": "0", "note": ""}

    response = manager_client.post(edit_url(slip), data, HTTP_HX_REQUEST="true")

    slip.refresh_from_db()
    assert response.status_code == 200
    assert slip.net == D("7600.00")
    assert "7600.00" in response.content.decode()
    assert 'name="overtime_hours"' not in response.content.decode()


def test_edit_post_invalid_keeps_values_and_shows_error(manager_client, run_with_slip):
    slip = run_with_slip.payslips.get()
    data = {"overtime_hours": "0", "absence_days": "31", "additions": "0", "deductions": "0", "note": ""}

    response = manager_client.post(edit_url(slip), data, HTTP_HX_REQUEST="true")

    slip.refresh_from_db()
    assert response.status_code == 200
    assert response.context["form"].errors
    assert slip.net == D("7200.00")


def test_edit_on_approved_run_returns_409(approver_client, run_with_slip, admin_user):
    approve_run(run_with_slip, admin_user)
    slip = run_with_slip.payslips.get()
    data = {"overtime_hours": "5", "absence_days": "0", "additions": "0", "deductions": "0", "note": ""}

    assert approver_client.post(edit_url(slip), data).status_code == 409


# --- approval flow --------------------------------------------------------------

def test_manager_without_approve_permission_gets_403(manager_client, run_with_slip):
    url = reverse("payroll:run_approve", args=[run_with_slip.pk])
    assert manager_client.post(url).status_code == 403
    run_with_slip.refresh_from_db()
    assert run_with_slip.status == PayrollRun.Status.DRAFT


def test_approver_can_approve(approver_client, run_with_slip):
    url = reverse("payroll:run_approve", args=[run_with_slip.pk])
    response = approver_client.post(url)

    run_with_slip.refresh_from_db()
    assert response.status_code == 302
    assert run_with_slip.status == PayrollRun.Status.APPROVED


def test_approve_requires_post(approver_client, run_with_slip):
    url = reverse("payroll:run_approve", args=[run_with_slip.pk])
    assert approver_client.get(url).status_code == 405


def test_approving_empty_run_shows_error_not_crash(approver_client):
    run = PayrollRunFactory()
    response = approver_client.post(reverse("payroll:run_approve", args=[run.pk]), follow=True)

    run.refresh_from_db()
    assert response.status_code == 200
    assert run.status == PayrollRun.Status.DRAFT
    assert any(m.level_tag == "error" for m in response.context["messages"])


def test_mark_paid(approver_client, run_with_slip, admin_user):
    approve_run(run_with_slip, admin_user)
    url = reverse("payroll:run_mark_paid", args=[run_with_slip.pk])

    approver_client.post(url)

    run_with_slip.refresh_from_db()
    assert run_with_slip.status == PayrollRun.Status.PAID


def test_regenerate_adds_new_employee(manager_client, run_with_slip):
    SalaryStructureFactory()   # a second eligible employee appears
    url = reverse("payroll:run_regenerate", args=[run_with_slip.pk])

    manager_client.post(url)

    assert run_with_slip.payslips.count() == 2


def test_regenerate_on_approved_run_shows_error(approver_client, run_with_slip, admin_user):
    approve_run(run_with_slip, admin_user)
    url = reverse("payroll:run_regenerate", args=[run_with_slip.pk])

    response = approver_client.post(url, follow=True)

    assert response.status_code == 200
    assert any(m.level_tag == "error" for m in response.context["messages"])


# --- payslip print page ---------------------------------------------------------

def test_payslip_page_shows_breakdown(manager_client, run_with_slip):
    slip = run_with_slip.payslips.get()
    response = manager_client.get(reverse("payroll:payslip_detail", args=[slip.pk]))
    html = response.content.decode()

    assert response.status_code == 200
    assert "Ahmed Khan" in html
    assert "7200.00" in html
    assert "2026-01" in html


def test_payslip_page_shows_company_name_from_settings(manager_client, run_with_slip, settings):
    settings.COMPANY_NAME = "Test Company LLC"
    slip = run_with_slip.payslips.get()
    html = manager_client.get(reverse("payroll:payslip_detail", args=[slip.pk])).content.decode()
    assert "Test Company LLC" in html


def test_payslip_page_requires_permission(viewer_client, run_with_slip):
    slip = run_with_slip.payslips.get()
    url = reverse("payroll:payslip_detail", args=[slip.pk])
    assert viewer_client.get(url).status_code == 403


# --- navigation & admin ---------------------------------------------------------

def test_nav_shows_payroll_link_only_with_permission(viewer_client):
    html = viewer_client.get(reverse("hr:employee_list")).content.decode()
    assert RUNS_URL not in html


def test_nav_shows_payroll_link_with_permission(client_with_perms):
    client = client_with_perms("view_employee", "view_payrollrun")
    html = client.get(reverse("hr:employee_list")).content.decode()
    assert RUNS_URL in html


def test_admin_run_pages_load(admin_client, run_with_slip):
    assert admin_client.get(reverse("admin:payroll_payrollrun_changelist")).status_code == 200
    assert admin_client.get(reverse("admin:payroll_payslip_changelist")).status_code == 200


def test_admin_cannot_delete_approved_run(rf, admin_user, run_with_slip):
    from django.contrib.admin.sites import site

    approve_run(run_with_slip, admin_user)
    run_with_slip.refresh_from_db()   # admin always loads the object fresh from the DB
    request = rf.get("/")
    request.user = admin_user
    model_admin = site._registry[PayrollRun]

    assert model_admin.has_delete_permission(request, run_with_slip) is False
    assert model_admin.has_delete_permission(request, PayrollRunFactory(month=5)) is True


def test_admin_has_no_bulk_delete_that_would_bypass_the_lock(rf, admin_user):
    from django.contrib.admin.sites import site

    from payroll.models import Payslip

    request = rf.get("/")
    request.user = admin_user
    for model in (PayrollRun, Payslip):
        assert "delete_selected" not in site._registry[model].get_actions(request)


def test_edit_cancel_returns_plain_row(manager_client, run_with_slip):
    slip = run_with_slip.payslips.get()
    response = manager_client.get(edit_url(slip), {"cancel": "1"}, HTTP_HX_REQUEST="true")

    html = response.content.decode()
    assert response.status_code == 200
    assert 'name="overtime_hours"' not in html
    assert "7200.00" in html


def test_edit_shows_service_level_error(manager_client):
    # Joined on the 16th -> 14 days not employed; 17 absent days would exceed 30.
    emp = EmployeeFactory(hire_date=dt.date(2026, 1, 16))
    SalaryStructureFactory(employee=emp)
    run = PayrollRunFactory()
    generate_payslips(run)
    slip = run.payslips.get()
    data = {"overtime_hours": "0", "absence_days": "17", "additions": "0", "deductions": "0", "note": ""}

    response = manager_client.post(edit_url(slip), data, HTTP_HX_REQUEST="true")

    slip.refresh_from_db()
    assert response.status_code == 200
    assert "absence_days" in response.context["form"].errors
    assert slip.absence_days == D("0")
