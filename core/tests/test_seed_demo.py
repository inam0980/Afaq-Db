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


def test_jobs_have_costs_and_profit_report_has_data(seeded):
    from jobs.costing import job_costing, profitability

    for job in Job.objects.filter(status__in=["in_progress", "completed"]):
        c = job_costing(job)
        assert c.materials > 0 and c.labour > 0
    today = timezone.localdate()
    report = profitability(today.year, today.month)
    assert report.rows and report.profit != 0


def test_some_approved_expenses_are_linked_to_jobs(seeded):
    assert Expense.objects.filter(job__isnull=False, status="approved").exists()


def test_only_manager_sees_job_costs(seeded):
    User = get_user_model()
    assert User.objects.get(username="manager_demo").has_perm("jobs.view_job_costing")
    assert not User.objects.get(username="coordinator_demo").has_perm("jobs.view_job_costing")


def test_rerun_backfills_costs_and_links_on_an_older_demo_database(seeded):
    from jobs.models import JobMaterial, LabourEntry

    # Simulate a database seeded before job costing existed.
    JobMaterial.objects.all().delete()
    LabourEntry.objects.all().delete()
    Expense.objects.update(job=None)

    call_command("seed_demo", verbosity=0)

    assert JobMaterial.objects.exists() and LabourEntry.objects.exists()
    assert Expense.objects.filter(job__isnull=False, status="approved").exists()
    before = (JobMaterial.objects.count(), LabourEntry.objects.count())
    call_command("seed_demo", verbosity=0)
    assert (JobMaterial.objects.count(), LabourEntry.objects.count()) == before


def test_demo_job_profits_are_realistic(seeded):
    # Demo data should show healthy jobs, not losses caused by unrelated costs.
    from jobs.costing import job_costing

    for job in Job.objects.filter(status="completed"):
        assert job_costing(job).profit > 0, job.title


def test_rerun_corrects_wrong_demo_expense_links(seeded):
    wrong = Job.objects.get(title="Repaint school corridors")
    Expense.objects.filter(invoice_number="DEMO-0004").update(job=wrong)   # govt fee, not a job cost
    call_command("seed_demo", verbosity=0)
    assert Expense.objects.get(invoice_number="DEMO-0004").job is None


def test_invoicing_roles(seeded):
    User = get_user_model()
    accountant = User.objects.get(username="accountant_demo")
    manager = User.objects.get(username="manager_demo")
    assert accountant.has_perm("invoicing.add_invoice") and not accountant.has_perm("invoicing.issue_invoice")
    assert manager.has_perm("invoicing.issue_invoice")


def test_demo_receivables_cover_every_situation(seeded):
    from invoicing.balances import aging, with_balances
    from invoicing.models import Invoice, Payment

    issued = with_balances(Invoice.objects.filter(status="issued", kind="invoice"))
    statuses = {i.payment_status for i in issued}
    assert {"paid", "partial", "unpaid"} <= statuses
    assert any(i.is_overdue for i in issued)
    assert Invoice.objects.filter(kind="credit_note", status="issued").exists()
    assert Invoice.objects.filter(job__status="completed", status="issued").count() == 2
    assert Payment.objects.exists()
    assert aging().totals["overdue"] > 0


def test_demo_invoices_are_not_duplicated(seeded):
    from invoicing.models import Invoice, Payment

    before = (Invoice.objects.count(), Payment.objects.count())
    call_command("seed_demo", verbosity=0)
    assert (Invoice.objects.count(), Payment.objects.count()) == before


def test_demo_job_invoices_are_paid_and_part_paid(seeded):
    from invoicing.balances import with_balances
    from invoicing.models import Invoice

    def status(title):
        return with_balances(Invoice.objects.filter(job__title=title, kind="invoice")).get().payment_status

    assert status("Leaking pipe in clinic washroom") == "paid"
    assert status("Classroom lighting rewiring") == "partial"


def test_vat_return_roles(seeded):
    User = get_user_model()
    assert User.objects.get(username="accountant_demo").has_perm("invoicing.view_vat_return")
    assert User.objects.get(username="manager_demo").has_perm("invoicing.view_vat_return")
    assert not User.objects.get(username="hr_demo").has_perm("invoicing.view_vat_return")


def test_demo_leave_covers_statuses_and_reaches_payroll(seeded):
    from leave.models import LeaveRequest

    statuses = set(LeaveRequest.objects.values_list("status", flat=True))
    assert {"approved", "pending", "rejected"} <= statuses
    assert LeaveRequest.objects.filter(leave_type__code="UNPAID", status="approved").exists()

    today = timezone.localdate()
    run = PayrollRun.objects.get(year=today.year, month=today.month)
    assert run.payslips.filter(leave_days__gt=0).exists()     # unpaid leave shows in this month's payroll


def test_leave_roles(seeded):
    User = get_user_model()
    hr = User.objects.get(username="hr_demo")
    manager = User.objects.get(username="manager_demo")
    assert hr.has_perm("leave.add_leaverequest") and not hr.has_perm("leave.approve_leaverequest")
    assert manager.has_perm("leave.approve_leaverequest")


def test_demo_leave_is_not_duplicated(seeded):
    from leave.models import LeaveRequest

    before = LeaveRequest.objects.count()
    call_command("seed_demo", verbosity=0)
    assert LeaveRequest.objects.count() == before


def test_demo_loans_reach_this_months_payroll(seeded):
    from loans.models import Loan

    assert set(Loan.objects.values_list("status", flat=True)) == {"approved", "pending"}
    today = timezone.localdate()
    run = PayrollRun.objects.get(year=today.year, month=today.month)
    slip = run.payslips.get(employee__id_number="2045678904")
    assert slip.loan_deduction > 0


def test_loan_roles(seeded):
    User = get_user_model()
    hr = User.objects.get(username="hr_demo")
    manager = User.objects.get(username="manager_demo")
    assert hr.has_perm("loans.add_loan") and not hr.has_perm("loans.approve_loan")
    assert manager.has_perm("loans.approve_loan")


def test_demo_loans_are_not_duplicated(seeded):
    from loans.models import Loan

    before = Loan.objects.count()
    call_command("seed_demo", verbosity=0)
    assert Loan.objects.count() == before
