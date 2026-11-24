"""Unit tests: invoice a completed job; job revenue comes from issued invoices."""

from decimal import Decimal as D

import pytest
from django.core.exceptions import ValidationError

from expenses.tests.factories import UserFactory
from hr.tests.factories import EmployeeFactory
from invoicing.models import Invoice
from invoicing.services import create_from_job, issue
from jobs.costing import job_costing
from jobs.models import Job
from jobs.services import change_status
from jobs.tests.factories import JobFactory

pytestmark = pytest.mark.django_db


@pytest.fixture
def user():
    return UserFactory()


def completed_job(**kwargs):
    job = JobFactory(**kwargs)
    job.technicians.add(EmployeeFactory())
    change_status(job, Job.Status.IN_PROGRESS)
    change_status(job, Job.Status.COMPLETED)
    job.refresh_from_db()
    return job


def test_creates_draft_with_one_line_for_the_quote(user):
    job = completed_job(title="Leaking pipe", service_type="plumbing", quoted_amount=D("650"))

    inv = create_from_job(job, user)

    line = inv.lines.get()
    assert inv.status == Invoice.Status.DRAFT
    assert (inv.customer, inv.job) == (job.customer, job)
    assert line.unit_price == D("650.00") and line.vat_rate == D("15")
    assert job.number in line.description and "Leaking pipe" in line.description
    assert inv.total == D("747.50")
    assert (inv.due_date - inv.issue_date).days == 30


def test_only_completed_jobs_can_be_invoiced(user):
    with pytest.raises(ValidationError):
        create_from_job(JobFactory(quoted_amount=D("100")), user)


def test_job_needs_a_quoted_amount(user):
    with pytest.raises(ValidationError):
        create_from_job(completed_job(quoted_amount=None), user)


def test_job_cannot_be_invoiced_twice(user):
    job = completed_job(quoted_amount=D("100"))
    create_from_job(job, user)
    with pytest.raises(ValidationError):
        create_from_job(job, user)


def test_revenue_uses_quote_until_invoiced_then_invoice(user):
    job = completed_job(quoted_amount=D("1000"))
    assert job_costing(job).revenue == D("1000.00")

    inv = create_from_job(job, user)
    assert job_costing(job).revenue == D("1000.00")         # draft does not count

    line = inv.lines.get()
    line.unit_price = D("1200")                              # final price differs from quote
    line.save()
    from invoicing.services import recalculate

    recalculate(inv)
    issue(inv, user)
    assert job_costing(job).revenue == D("1200.00")          # excl. VAT


def test_draft_invoice_with_a_different_price_does_not_change_revenue(user):
    from invoicing.services import recalculate

    job = completed_job(quoted_amount=D("1000"))
    inv = create_from_job(job, user)
    line = inv.lines.get()
    line.unit_price = D("1500")
    line.save()
    recalculate(inv)
    assert job_costing(job).revenue == D("1000.00")         # still the quote while draft
