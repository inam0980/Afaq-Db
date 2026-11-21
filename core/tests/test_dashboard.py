"""Integration tests: home dashboard (KPIs respect permissions)."""

import datetime as dt
from decimal import Decimal as D

import pytest
from django.urls import reverse
from django.utils import timezone

from hr.models import Employee
from hr.tests.factories import EmployeeFactory
from payroll.services import generate_payslips
from payroll.tests.factories import PayrollRunFactory, SalaryStructureFactory

pytestmark = pytest.mark.django_db

HOME = reverse("home")


def this_month_run():
    today = timezone.localdate()
    return PayrollRunFactory(year=today.year, month=today.month)


def test_anonymous_redirected_to_login(client):
    response = client.get(HOME)
    assert response.status_code == 302
    assert response.url.startswith(reverse("login"))


def test_login_lands_on_dashboard(settings):
    assert settings.LOGIN_REDIRECT_URL == "home"


def test_employee_kpis(viewer_client):
    today = timezone.localdate()
    EmployeeFactory.create_batch(3)
    EmployeeFactory(id_expiry=today + dt.timedelta(days=10))
    EmployeeFactory(status=Employee.Status.TERMINATED, termination_date=dt.date(2025, 1, 1))

    ctx = viewer_client.get(HOME).context

    assert ctx["active_employees"] == 4
    assert ctx["expiring_count"] == 1
    assert len(ctx["expiring"]) == 1


def test_expired_document_is_flagged_without_payroll_permission(viewer_client):
    EmployeeFactory(id_expiry=timezone.localdate() - dt.timedelta(days=3))
    html = viewer_client.get(HOME).content.decode()
    assert "badge-expired" in html


def test_expiring_list_is_capped_at_five(viewer_client):
    today = timezone.localdate()
    for i in range(7):
        EmployeeFactory(id_expiry=today + dt.timedelta(days=i))

    ctx = viewer_client.get(HOME).context

    assert ctx["expiring_count"] == 7
    assert len(ctx["expiring"]) == 5


def test_payroll_card_hidden_without_permission(viewer_client):
    this_month_run()
    response = viewer_client.get(HOME)
    assert response.context["show_payroll"] is False
    assert reverse("payroll:run_list") not in response.content.decode()


def test_payroll_card_shows_current_month_run(client_with_perms):
    client = client_with_perms("view_employee", "view_payrollrun")
    SalaryStructureFactory()
    run = this_month_run()
    generate_payslips(run)

    ctx = client.get(HOME).context

    assert ctx["show_payroll"] is True
    assert ctx["current_run"] == run
    assert ctx["current_totals"]["net"] == D("7200.00")


def test_payroll_card_when_month_not_created_yet(client_with_perms):
    client = client_with_perms("view_payrollrun")
    response = client.get(HOME)
    assert response.context["current_run"] is None
    assert "not been created" in response.content.decode()


def test_user_without_any_permission_sees_no_numbers(no_perm_client):
    EmployeeFactory()
    response = no_perm_client.get(HOME)

    assert response.status_code == 200
    assert response.context["show_employees"] is False
    assert "active_employees" not in response.context


def test_quick_actions_follow_permissions(client_with_perms):
    client = client_with_perms("view_employee", "add_employee")
    html = client.get(HOME).content.decode()
    assert reverse("hr:employee_create") in html
    assert reverse("payroll:run_list") not in html


def test_payroll_card_ignores_other_months(client_with_perms):
    client = client_with_perms("view_payrollrun")
    today = timezone.localdate()
    PayrollRunFactory(year=today.year - 1, month=today.month)

    assert client.get(HOME).context["current_run"] is None


def test_no_add_employee_action_without_permission(viewer_client):
    html = viewer_client.get(HOME).content.decode()
    assert reverse("hr:employee_create") not in html
