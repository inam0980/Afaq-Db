"""Integration tests: costing on the job page, entry forms, report, expense link."""

import datetime as dt
from decimal import Decimal as D

import pytest
from django.urls import reverse
from django.utils import timezone

from expenses.models import Expense
from expenses.tests.factories import ExpenseCategoryFactory, receipt_file
from hr.tests.factories import EmployeeFactory
from jobs.costing import add_labour, add_material
from jobs.models import Job, JobMaterial, LabourEntry
from jobs.services import change_status
from jobs.tests.factories import JobFactory
from payroll.tests.factories import SalaryStructureFactory

pytestmark = pytest.mark.django_db

REPORT_URL = reverse("jobs:profitability")


@pytest.fixture
def tech():
    emp = EmployeeFactory(first_name="Rahul", last_name="Sharma")
    SalaryStructureFactory(employee=emp)   # 30/h
    return emp


@pytest.fixture
def job(tech):
    j = JobFactory(quoted_amount=D("1000"))
    j.technicians.add(tech)
    return j


@pytest.fixture
def coordinator(client_with_perms):
    """Runs jobs and logs hours, but must not see money."""
    return client_with_perms("view_job", "change_job", "view_employee")


@pytest.fixture
def owner(client_with_perms):
    return client_with_perms("view_job", "change_job", "view_job_costing", "view_employee")


def url(name, obj):
    return reverse(f"jobs:{name}", args=[obj.pk])


def test_costing_visible_with_permission(owner, job, admin_user):
    add_material(job, admin_user, description="Gas", quantity=D("2"), unit_cost=D("75"))
    response = owner.get(url("detail", job))
    assert response.context["costing"].total_cost == D("150.00")
    assert "150.00" in response.content.decode()


def test_coordinator_logs_hours_but_sees_no_money(coordinator, job, tech):
    today = timezone.localdate().isoformat()
    coordinator.post(url("add_labour", job), {"employee": tech.pk, "date": today, "hours": "8", "note": ""})

    entry = LabourEntry.objects.get()
    html = coordinator.get(url("detail", job)).content.decode()

    assert entry.cost == D("240.00")
    assert "Rahul Sharma" in html and "8" in html
    assert "240.00" not in html and "30.00" not in html
    assert coordinator.get(url("detail", job)).context["costing"] is None


def test_add_material_via_post(owner, job):
    response = owner.post(url("add_material", job), {"description": "Copper", "quantity": "3", "unit_cost": "20"})
    assert response.status_code == 302
    assert JobMaterial.objects.get().total == D("60.00")


def test_add_material_invalid_shows_error(owner, job):
    response = owner.post(url("add_material", job), {"description": "", "quantity": "0", "unit_cost": "1"}, follow=True)
    assert not JobMaterial.objects.exists()
    assert any(m.level_tag == "error" for m in response.context["messages"])


def test_add_labour_for_unassigned_employee_shows_error(owner, job):
    stranger = EmployeeFactory()
    data = {"employee": stranger.pk, "date": timezone.localdate().isoformat(), "hours": "2", "note": ""}
    response = owner.post(url("add_labour", job), data, follow=True)
    assert not LabourEntry.objects.exists()
    assert any(m.level_tag == "error" for m in response.context["messages"])


def test_delete_entries(owner, job, tech, admin_user):
    m = add_material(job, admin_user, description="Gas", quantity=D("1"), unit_cost=D("5"))
    lab = add_labour(job, admin_user, employee=tech, date=timezone.localdate(), hours=D("1"))
    owner.post(reverse("jobs:delete_material", args=[m.pk]))
    owner.post(reverse("jobs:delete_labour", args=[lab.pk]))
    assert not JobMaterial.objects.exists() and not LabourEntry.objects.exists()


def test_delete_on_cancelled_job_shows_error(owner, job, admin_user):
    m = add_material(job, admin_user, description="Gas", quantity=D("1"), unit_cost=D("5"))
    change_status(job, Job.Status.CANCELLED, reason="x")
    response = owner.post(reverse("jobs:delete_material", args=[m.pk]), follow=True)
    assert JobMaterial.objects.filter(pk=m.pk).exists()
    assert any(m.level_tag == "error" for m in response.context["messages"])


def test_cost_entries_need_change_permission(client_with_perms, job):
    viewer = client_with_perms("view_job")
    data = {"description": "Copper", "quantity": "1", "unit_cost": "1"}
    assert viewer.post(url("add_material", job), data).status_code == 403
    assert viewer.get(url("add_material", job)).status_code == 405


# --- profitability report ------------------------------------------------------

def test_report_requires_costing_permission(coordinator):
    assert coordinator.get(REPORT_URL).status_code == 403


def test_report_lists_completed_jobs_of_the_month(owner, job, admin_user):
    add_material(job, admin_user, description="Gas", quantity=D("1"), unit_cost=D("400"))
    change_status(job, Job.Status.IN_PROGRESS)
    change_status(job, Job.Status.COMPLETED)

    response = owner.get(REPORT_URL)

    assert response.context["report"].profit == D("600.00")
    assert job.number in response.content.decode()


@pytest.mark.parametrize("bad", ["2026-13", "x"])
def test_report_bad_month_falls_back_to_current(owner, bad):
    today = timezone.localdate()
    assert owner.get(REPORT_URL, {"month": bad}).context["period"] == (today.year, today.month)


def test_report_specific_month(owner):
    assert owner.get(REPORT_URL, {"month": "2025-03"}).context["period"] == (2025, 3)


# --- expense <-> job link --------------------------------------------------------

def test_expense_can_be_linked_to_a_job(client_with_perms, job):
    client = client_with_perms("view_expense", "add_expense", "change_expense")
    data = {
        "date": "2026-01-15", "category": ExpenseCategoryFactory().pk, "description": "Ladder rental",
        "vendor_name": "", "vendor_vat_number": "", "invoice_number": "", "total": "50",
        "vat_rate": "0", "payment_method": "cash", "receipt": receipt_file(), "job": job.pk,
    }
    client.post(reverse("expenses:create"), data)
    assert Expense.objects.get().job == job


def test_cancelled_jobs_not_offered_for_new_expenses(client_with_perms, job):
    client = client_with_perms("view_expense", "add_expense")
    cancelled = JobFactory()
    change_status(cancelled, Job.Status.CANCELLED, reason="x")
    qs = client.get(reverse("expenses:create")).context["form"].fields["job"].queryset
    assert job in qs and cancelled not in qs


def test_job_page_lists_linked_expenses(owner, job):
    from expenses.tests.factories import ExpenseFactory

    e = ExpenseFactory(job=job, description="Ladder rental")
    assert "Ladder rental" in owner.get(url("detail", job)).content.decode()
    assert e.number in owner.get(url("detail", job)).content.decode()


# --- dashboard & sidebar -----------------------------------------------------------

def test_dashboard_profit_kpi_with_costing_permission(owner, job):
    assert "month_job_profit" in owner.get(reverse("home")).context


def test_sidebar_report_link_with_permission(owner):
    assert REPORT_URL in owner.get(reverse("home")).content.decode()


def test_dashboard_hides_profit_from_coordinator(coordinator):
    assert "month_job_profit" not in coordinator.get(reverse("home")).context


def test_sidebar_report_link_only_with_permission(coordinator):
    assert REPORT_URL not in coordinator.get(reverse("home")).content.decode()


def test_editing_expense_keeps_its_cancelled_job_selectable(client_with_perms, job):
    from expenses.tests.factories import ExpenseFactory

    client = client_with_perms("view_expense", "change_expense")
    e = ExpenseFactory(job=job)
    change_status(job, Job.Status.CANCELLED, reason="x")
    qs = client.get(reverse("expenses:update", args=[e.pk])).context["form"].fields["job"].queryset
    assert job in qs
