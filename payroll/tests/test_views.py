"""Integration tests: salary page (permissions, DB, EOSB estimate, template)."""

import datetime as dt
from decimal import Decimal as D

import pytest
from django.urls import reverse
from django.utils import timezone

from hr.models import Employee
from hr.tests.factories import EmployeeFactory
from payroll.tests.factories import SalaryStructureFactory

pytestmark = pytest.mark.django_db


def salary_url(emp):
    return reverse("payroll:employee_salary", args=[emp.pk])


@pytest.fixture
def payroll_client(client_with_perms):
    return client_with_perms("view_employee", "view_salarystructure")


def test_hr_viewer_without_salary_permission_gets_403(viewer_client):
    emp = EmployeeFactory()
    assert viewer_client.get(salary_url(emp)).status_code == 403


def test_anonymous_redirected_to_login(client):
    emp = EmployeeFactory()
    response = client.get(salary_url(emp))
    assert response.status_code == 302
    assert response.url.startswith(reverse("login"))


def test_salary_page_shows_structures_newest_first(payroll_client):
    emp = EmployeeFactory()
    SalaryStructureFactory(employee=emp, effective_from=dt.date(2020, 1, 1), basic=D("4000"))
    SalaryStructureFactory(employee=emp, effective_from=dt.date(2024, 1, 1), basic=D("5000"))

    response = payroll_client.get(salary_url(emp))

    assert response.status_code == 200
    dates = [s.effective_from for s in response.context["structures"]]
    assert dates == [dt.date(2024, 1, 1), dt.date(2020, 1, 1)]
    assert response.context["current"].basic == D("5000")


def test_eosb_estimate_for_termination_by_default(payroll_client):
    hire = timezone.localdate() - dt.timedelta(days=365 * 3)
    emp = EmployeeFactory(hire_date=hire)
    SalaryStructureFactory(employee=emp, effective_from=hire)   # gross 7,200

    response = payroll_client.get(salary_url(emp))

    assert response.context["reason"] == "termination"
    assert response.context["eosb"] == D("10800.00")   # 3 x 0.5 x 7,200


def test_eosb_estimate_for_resignation(payroll_client):
    hire = timezone.localdate() - dt.timedelta(days=365 * 3)
    emp = EmployeeFactory(hire_date=hire)
    SalaryStructureFactory(employee=emp, effective_from=hire)

    response = payroll_client.get(salary_url(emp), {"reason": "resignation"})

    assert response.context["eosb"] == D("3600.00")    # 1/3 of 10,800


def test_eosb_unknown_reason_falls_back_to_termination(payroll_client):
    emp = EmployeeFactory()
    SalaryStructureFactory(employee=emp)
    response = payroll_client.get(salary_url(emp), {"reason": "hack"})
    assert response.context["reason"] == "termination"


def test_eosb_for_terminated_employee_uses_termination_date(payroll_client):
    emp = EmployeeFactory(
        hire_date=dt.date(2015, 1, 1),
        termination_date=dt.date(2015, 1, 1) + dt.timedelta(days=365 * 3),
        status=Employee.Status.TERMINATED,
    )
    SalaryStructureFactory(employee=emp, effective_from=dt.date(2015, 1, 1))

    response = payroll_client.get(salary_url(emp))

    assert response.context["eosb_end_date"] == emp.termination_date
    assert response.context["eosb"] == D("10800.00")


def test_employee_without_salary_shows_message(payroll_client):
    emp = EmployeeFactory()
    response = payroll_client.get(salary_url(emp))

    assert response.status_code == 200
    assert response.context["current"] is None
    assert response.context["eosb"] is None
    assert "No salary structure" in response.content.decode()


def test_hr_detail_hides_salary_link_without_permission(viewer_client):
    emp = EmployeeFactory()
    detail = reverse("hr:employee_detail", args=[emp.pk])
    assert salary_url(emp) not in viewer_client.get(detail).content.decode()


def test_hr_detail_shows_salary_link_with_permission(payroll_client):
    emp = EmployeeFactory()
    detail = reverse("hr:employee_detail", args=[emp.pk])
    assert salary_url(emp) in payroll_client.get(detail).content.decode()


def test_admin_pages_load(admin_client):
    SalaryStructureFactory()
    assert admin_client.get(reverse("admin:payroll_salarystructure_changelist")).status_code == 200
    assert admin_client.get(reverse("admin:payroll_gosirate_changelist")).status_code == 200
