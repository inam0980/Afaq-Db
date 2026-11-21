"""Unit tests: Job numbering, rules, status workflow."""

import datetime as dt
import re

import pytest
from django.core.exceptions import ValidationError
from django.utils import timezone

from customers.tests.factories import BusinessCustomerFactory
from hr.models import Employee
from hr.tests.factories import EmployeeFactory
from jobs.models import Job
from jobs.services import change_status
from jobs.tests.factories import JobFactory

pytestmark = pytest.mark.django_db

S = Job.Status


def test_number_is_sequential():
    a, b = JobFactory(), JobFactory()
    assert re.fullmatch(r"JOB-\d{5}", a.number)
    assert int(b.number[4:]) == int(a.number[4:]) + 1


def test_new_job_is_new_and_normal_priority():
    job = JobFactory()
    assert (job.status, job.priority) == (S.NEW, Job.Priority.NORMAL)


def test_site_address_falls_back_to_customer_address():
    customer = BusinessCustomerFactory()
    assert JobFactory(customer=customer, site_address="").location == customer.address_line
    assert JobFactory(customer=customer, site_address="Villa 7, Hittin").location == "Villa 7, Hittin"


def test_quoted_amount_cannot_be_negative():
    job = JobFactory()
    job.quoted_amount = -1
    with pytest.raises(ValidationError):
        job.full_clean()


def test_str_and_search():
    job = JobFactory(title="Leaking pipe")
    JobFactory(title="Paint villa")
    assert str(job) == f"{job.number} - Leaking pipe"
    assert list(Job.objects.search("leak")) == [job]
    assert list(Job.objects.search(job.number)) == [job]
    assert list(Job.objects.search(job.customer.name)) == [job]


def test_open_queryset():
    open_job = JobFactory()
    done = JobFactory()
    Job.objects.filter(pk=done.pk).update(status=S.COMPLETED)
    assert list(Job.objects.open()) == [open_job]


# --- status workflow -----------------------------------------------------------

@pytest.fixture
def tech():
    return EmployeeFactory()


def schedule(job):
    job.scheduled_date = timezone.localdate()
    job.save()
    change_status(job, S.SCHEDULED)


def test_schedule_requires_date():
    job = JobFactory()
    with pytest.raises(ValidationError):
        change_status(job, S.SCHEDULED)
    schedule(job)
    job.refresh_from_db()
    assert job.status == S.SCHEDULED


def test_start_requires_a_technician(tech):
    job = JobFactory()
    with pytest.raises(ValidationError):
        change_status(job, S.IN_PROGRESS)
    job.technicians.add(tech)
    change_status(job, S.IN_PROGRESS)
    job.refresh_from_db()
    assert job.status == S.IN_PROGRESS
    assert job.started_at is not None


def test_terminated_technician_cannot_start_a_job():
    gone = EmployeeFactory(status=Employee.Status.TERMINATED, termination_date=dt.date(2024, 1, 1))
    job = JobFactory()
    job.technicians.add(gone)
    with pytest.raises(ValidationError):
        change_status(job, S.IN_PROGRESS)


def test_complete_sets_completed_at(tech):
    job = JobFactory()
    job.technicians.add(tech)
    change_status(job, S.IN_PROGRESS)
    change_status(job, S.COMPLETED)
    job.refresh_from_db()
    assert job.status == S.COMPLETED
    assert job.completed_at is not None


@pytest.mark.parametrize("target", [S.COMPLETED, S.NEW])
def test_new_job_cannot_jump(target):
    with pytest.raises(ValidationError):
        change_status(JobFactory(), target)


def test_cancel_requires_reason():
    job = JobFactory()
    with pytest.raises(ValidationError):
        change_status(job, S.CANCELLED, reason="  ")
    change_status(job, S.CANCELLED, reason="Customer postponed")
    job.refresh_from_db()
    assert (job.status, job.cancel_reason) == (S.CANCELLED, "Customer postponed")


@pytest.mark.parametrize("final", [S.COMPLETED, S.CANCELLED])
def test_final_states_cannot_change(final):
    job = JobFactory()
    Job.objects.filter(pk=job.pk).update(status=final)
    job.refresh_from_db()
    for target in S.values:
        with pytest.raises(ValidationError):
            change_status(job, target, reason="x")


def test_unknown_status_rejected():
    with pytest.raises(ValidationError):
        change_status(JobFactory(), "flying")


def test_is_editable():
    job = JobFactory()
    assert job.is_editable
    for final in (S.COMPLETED, S.CANCELLED):
        job.status = final
        assert not job.is_editable


def test_allowed_next_statuses_for_ui():
    job = JobFactory()
    assert set(job.next_statuses) == {S.SCHEDULED, S.IN_PROGRESS, S.CANCELLED}


def test_status_changes_are_audited(tech):
    job = JobFactory()
    job.technicians.add(tech)
    change_status(job, S.IN_PROGRESS)
    assert job.history.count() == 2
