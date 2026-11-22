"""Unit tests: job cost entries, labour cost snapshot, costing summary."""

import datetime as dt
from decimal import Decimal as D

import pytest
from django.core.exceptions import ValidationError
from django.utils import timezone

from expenses.models import Expense
from expenses.tests.factories import ExpenseFactory
from hr.tests.factories import EmployeeFactory
from jobs.costing import add_labour, add_material, delete_cost_entry, job_costing, profitability
from jobs.models import Job, JobMaterial, LabourEntry
from jobs.services import change_status
from jobs.tests.factories import JobFactory
from payroll.tests.factories import SalaryStructureFactory

pytestmark = pytest.mark.django_db


@pytest.fixture
def today():
    return timezone.localdate()


@pytest.fixture
def tech():
    emp = EmployeeFactory()
    SalaryStructureFactory(employee=emp, effective_from=dt.date(2020, 1, 1))   # gross 7,200 -> 30/h
    return emp


@pytest.fixture
def job(tech):
    j = JobFactory(quoted_amount=D("1000.00"))
    j.technicians.add(tech)
    return j


# --- materials ---------------------------------------------------------------

def test_material_line_total(job, admin_user):
    m = add_material(job, admin_user, description="Copper pipe", quantity=D("2.5"), unit_cost=D("12.40"))
    assert m.total == D("31.00")


@pytest.mark.parametrize("qty, cost", [(D("0"), D("10")), (D("-1"), D("10")), (D("1"), D("-5"))])
def test_material_needs_positive_quantity_and_non_negative_cost(job, admin_user, qty, cost):
    with pytest.raises(ValidationError):
        add_material(job, admin_user, description="X", quantity=qty, unit_cost=cost)


# --- labour ------------------------------------------------------------------

def test_labour_cost_uses_hourly_rate_from_salary(job, tech, admin_user, today):
    e = add_labour(job, admin_user, employee=tech, date=today, hours=D("8"))
    assert e.hourly_cost == D("30.00")
    assert e.cost == D("240.00")


def test_labour_cost_is_frozen_when_salary_changes_later(job, tech, admin_user, today):
    e = add_labour(job, admin_user, employee=tech, date=today, hours=D("8"))
    SalaryStructureFactory(employee=tech, effective_from=today, basic=D("9600"))   # raise
    e.refresh_from_db()
    assert e.cost == D("240.00")


def test_labour_uses_salary_in_force_on_that_date(job, tech, admin_user, today):
    Job.objects.filter(pk=job.pk).update(created_at=timezone.now() - dt.timedelta(days=10))
    SalaryStructureFactory(employee=tech, effective_from=today, basic=D("12000"))  # 14,400 -> 60/h
    old = add_labour(job, admin_user, employee=tech, date=today - dt.timedelta(days=1), hours=D("1"))
    new = add_labour(job, admin_user, employee=tech, date=today, hours=D("1"))
    assert (old.hourly_cost, new.hourly_cost) == (D("30.00"), D("60.00"))


def test_labour_only_for_assigned_technicians(job, admin_user, today):
    stranger = EmployeeFactory()
    SalaryStructureFactory(employee=stranger)
    with pytest.raises(ValidationError):
        add_labour(job, admin_user, employee=stranger, date=today, hours=D("2"))


def test_labour_needs_a_salary_structure(admin_user, today):
    no_salary = EmployeeFactory()
    j = JobFactory()
    j.technicians.add(no_salary)
    with pytest.raises(ValidationError):
        add_labour(j, admin_user, employee=no_salary, date=today, hours=D("2"))


@pytest.mark.parametrize("hours", [D("0"), D("-1"), D("24.5")])
def test_labour_hours_must_be_within_a_day(job, tech, admin_user, today, hours):
    with pytest.raises(ValidationError):
        add_labour(job, admin_user, employee=tech, date=today, hours=hours)


def test_24_hours_is_allowed(job, tech, admin_user, today):
    add_labour(job, admin_user, employee=tech, date=today, hours=D("24"))


def test_labour_cannot_be_in_the_future(job, tech, admin_user, today):
    with pytest.raises(ValidationError):
        add_labour(job, admin_user, employee=tech, date=today + dt.timedelta(days=1), hours=D("1"))


def test_labour_cannot_be_before_the_job_existed(job, tech, admin_user):
    before = timezone.localtime(job.created_at).date() - dt.timedelta(days=1)
    with pytest.raises(ValidationError):
        add_labour(job, admin_user, employee=tech, date=before, hours=D("1"))


# --- cancelled jobs are frozen -------------------------------------------------

def test_no_costs_on_cancelled_job(job, tech, admin_user, today):
    m = add_material(job, admin_user, description="Tape", quantity=D("1"), unit_cost=D("5"))
    change_status(job, Job.Status.CANCELLED, reason="Duplicate")

    with pytest.raises(ValidationError):
        add_material(job, admin_user, description="X", quantity=D("1"), unit_cost=D("1"))
    with pytest.raises(ValidationError):
        add_labour(job, admin_user, employee=tech, date=today, hours=D("1"))
    with pytest.raises(ValidationError):
        delete_cost_entry(m)
    assert JobMaterial.objects.filter(pk=m.pk).exists()


def test_costs_allowed_on_completed_job(job, tech, admin_user, today):
    change_status(job, Job.Status.IN_PROGRESS)
    change_status(job, Job.Status.COMPLETED)
    add_material(job, admin_user, description="Late invoice part", quantity=D("1"), unit_cost=D("10"))


def test_delete_cost_entries(job, tech, admin_user, today):
    m = add_material(job, admin_user, description="Tape", quantity=D("1"), unit_cost=D("5"))
    lab = add_labour(job, admin_user, employee=tech, date=today, hours=D("1"))
    delete_cost_entry(m)
    delete_cost_entry(lab)
    assert not JobMaterial.objects.exists() and not LabourEntry.objects.exists()


# --- costing summary -----------------------------------------------------------

def link_expense(job, status, total=D("115.00")):
    e = ExpenseFactory(job=job, total=total)            # 100.00 excl. VAT
    Expense.objects.filter(pk=e.pk).update(status=status)
    return e


def test_costing_summary(job, tech, admin_user, today):
    add_material(job, admin_user, description="Gas", quantity=D("2"), unit_cost=D("75"))      # 150
    add_labour(job, admin_user, employee=tech, date=today, hours=D("10"))                   # 300
    link_expense(job, Expense.Status.APPROVED)                                              # 100 excl. VAT
    link_expense(job, Expense.Status.SUBMITTED)                                             # not counted
    link_expense(job, Expense.Status.DRAFT)                                                 # not counted

    c = job_costing(job)

    assert (c.materials, c.labour, c.expenses) == (D("150.00"), D("300.00"), D("100.00"))
    assert c.total_cost == D("550.00")
    assert c.revenue == D("1000.00")
    assert c.profit == D("450.00")
    assert c.margin_pct == D("45.00")
    assert c.labour_hours == D("10.00")


def test_costing_without_quote_has_no_profit(admin_user):
    j = JobFactory(quoted_amount=None)
    add_material(j, admin_user, description="Gas", quantity=D("1"), unit_cost=D("50"))
    c = job_costing(j)
    assert c.total_cost == D("50.00")
    assert (c.revenue, c.profit, c.margin_pct) == (None, None, None)


def test_costing_with_zero_quote_has_no_margin(admin_user):
    c = job_costing(JobFactory(quoted_amount=D("0")))
    assert c.profit == D("0.00")
    assert c.margin_pct is None


def test_loss_making_job_has_negative_profit(job, admin_user):
    add_material(job, admin_user, description="Compressor", quantity=D("1"), unit_cost=D("1500"))
    c = job_costing(job)
    assert c.profit == D("-500.00")
    assert c.margin_pct == D("-50.00")


# --- profitability report ------------------------------------------------------

def complete(job):
    change_status(job, Job.Status.IN_PROGRESS)
    change_status(job, Job.Status.COMPLETED)


def test_profitability_for_month(job, tech, admin_user, today):
    add_material(job, admin_user, description="Gas", quantity=D("1"), unit_cost=D("200"))
    complete(job)
    other = JobFactory(quoted_amount=D("500"))
    other.technicians.add(tech)
    complete(other)
    open_job = JobFactory(quoted_amount=D("999"))          # not completed -> excluded

    report = profitability(today.year, today.month)

    assert {row.job.pk for row in report.rows} == {job.pk, other.pk}
    assert report.revenue == D("1500.00")
    assert report.total_cost == D("200.00")
    assert report.profit == D("1300.00")
    assert open_job.pk not in {row.job.pk for row in report.rows}


def test_profitability_other_month_is_empty(job, today):
    complete(job)
    other = today.replace(day=1) - dt.timedelta(days=1)
    report = profitability(other.year, other.month)
    assert report.rows == [] and report.profit == D("0.00")


def test_entry_str(job, tech, admin_user, today):
    m = add_material(job, admin_user, description="Gas", quantity=D("1"), unit_cost=D("5"))
    lab = add_labour(job, admin_user, employee=tech, date=today, hours=D("2"))
    assert str(m) == f"{job.number}: Gas"
    assert str(lab) == f"{job.number}: {tech.full_name} 2h"


def test_profitability_only_counts_jobs_whose_status_is_completed(job, today):
    # e.g. a job re-opened after completion keeps its old completed_at
    Job.objects.filter(pk=job.pk).update(status=Job.Status.IN_PROGRESS, completed_at=timezone.now())
    assert profitability(today.year, today.month).rows == []
