"""Integration tests: `manage.py seed_demo` builds a realistic, valid demo dataset."""

import datetime as dt

import pytest
from django.contrib.auth import get_user_model
from django.core.management import CommandError, call_command
from django.utils import timezone

from customers.models import Customer
from expenses.models import Expense
from hr.models import Department, Employee
from jobs.models import Job
from payroll.models import PayrollRun, SalaryStructure

pytestmark = pytest.mark.django_db


@pytest.fixture
def seeded(settings):
    settings.DEBUG = True
    call_command("seed_demo", verbosity=0)


def counts():
    return (
        Department.objects.count(),
        Employee.objects.count(),
        SalaryStructure.objects.count(),
        PayrollRun.objects.count(),
        Expense.objects.count(),
        get_user_model().objects.count(),
        Customer.objects.count(),
        Job.objects.count(),
    )


def test_refuses_to_run_in_production(settings):
    settings.DEBUG = False
    with pytest.raises(CommandError):
        call_command("seed_demo", verbosity=0)
    assert Employee.objects.count() == 0


def test_force_flag_allows_running_without_debug(settings):
    settings.DEBUG = False
    call_command("seed_demo", "--force", verbosity=0)
    assert Employee.objects.exists()


def test_creates_employees_that_pass_all_validation(seeded):
    assert Employee.objects.count() == 12
    assert Employee.objects.filter(nationality="SA").exists()
    assert Employee.objects.exclude(nationality="SA").exists()
    for emp in Employee.objects.all():
        emp.full_clean()          # IDs, IBANs, mobiles, dates all valid


def test_some_documents_need_attention(seeded):
    today = timezone.localdate()
    assert Employee.objects.with_expiring_documents(within_days=30).count() >= 3
    assert Employee.objects.filter(id_expiry__lt=today).exists()        # one already expired


def test_every_active_employee_has_a_salary(seeded):
    for emp in Employee.objects.active():
        assert SalaryStructure.objects.current_for(emp, timezone.localdate()) is not None


def test_payroll_last_month_paid_this_month_draft(seeded):
    today = timezone.localdate()
    last = (today.replace(day=1) - dt.timedelta(days=1))
    this_run = PayrollRun.objects.get(year=today.year, month=today.month)
    last_run = PayrollRun.objects.get(year=last.year, month=last.month)

    assert this_run.status == PayrollRun.Status.DRAFT
    assert last_run.status == PayrollRun.Status.PAID
    assert this_run.payslips.filter(overtime_hours__gt=0).exists()
    assert this_run.payslips.count() >= 10


def test_expenses_cover_every_status_and_are_valid(seeded):
    statuses = set(Expense.objects.values_list("status", flat=True))
    assert statuses == set(Expense.Status.values)
    for e in Expense.objects.all():
        e.full_clean()
    assert not Expense.objects.filter(date__gt=timezone.localdate()).exists()


def test_approvals_respect_segregation_of_duties(seeded):
    for e in Expense.objects.filter(decided_by__isnull=False):
        assert e.decided_by_id != e.created_by_id


def test_demo_users_have_role_permissions(seeded):
    User = get_user_model()
    hr = User.objects.get(username="hr_demo")
    accountant = User.objects.get(username="accountant_demo")
    manager = User.objects.get(username="manager_demo")

    assert hr.check_password("Demo@12345")
    assert hr.has_perm("hr.add_employee") and not hr.has_perm("expenses.view_expense")
    assert accountant.has_perm("expenses.add_expense") and not accountant.has_perm("expenses.approve_expense")
    assert manager.has_perm("expenses.approve_expense") and manager.has_perm("payroll.approve_payrollrun")


def test_running_twice_does_not_duplicate(seeded):
    before = counts()
    call_command("seed_demo", verbosity=0)
    assert counts() == before


def test_rerun_after_this_months_payroll_was_approved_still_works(seeded):
    from payroll.services import approve_run

    today = timezone.localdate()
    run = PayrollRun.objects.get(year=today.year, month=today.month)
    approve_run(run, get_user_model().objects.get(username="manager_demo"))

    call_command("seed_demo", verbosity=0)     # must not crash on the locked run


def test_prints_demo_logins(settings):
    from io import StringIO

    settings.DEBUG = True
    out = StringIO()
    call_command("seed_demo", stdout=out)
    text = out.getvalue()
    assert "Demo@12345" in text
    assert "manager_demo" in text


def test_unknown_permission_in_role_fails_loudly(settings, monkeypatch):
    from core.management.commands import seed_demo

    settings.DEBUG = True
    monkeypatch.setattr(seed_demo, "ROLES", [("x_demo", "X", "Y", "X", ["no_such_perm"])])
    with pytest.raises(CommandError):
        call_command("seed_demo", verbosity=0)


def test_customers_are_valid_and_mixed(seeded):
    assert Customer.objects.count() >= 6
    assert Customer.objects.filter(kind="business").exclude(vat_number="").exists()
    assert Customer.objects.filter(kind="individual").exists()
    for c in Customer.objects.all():
        c.full_clean()


def test_jobs_cover_every_status(seeded):
    assert set(Job.objects.values_list("status", flat=True)) == set(Job.Status.values)
    for job in Job.objects.all():
        job.full_clean()
    for job in Job.objects.filter(status__in=["in_progress", "completed"]):
        assert job.technicians.exists() and job.started_at
    assert Job.objects.filter(status="completed").exclude(completed_at=None).exists()
    assert not Job.objects.filter(status="cancelled", cancel_reason="").exists()
    assert Job.objects.filter(priority="urgent").exists()


def test_coordinator_role(seeded):
    user = get_user_model().objects.get(username="coordinator_demo")
    assert user.has_perm("jobs.change_job") and user.has_perm("customers.add_customer")
    assert not user.has_perm("expenses.view_expense")
    manager = get_user_model().objects.get(username="manager_demo")
    assert manager.has_perm("jobs.change_job")
