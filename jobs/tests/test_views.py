"""Integration tests: job pages, workflow buttons, dashboard, sidebar."""

import pytest
from django.urls import reverse
from django.utils import timezone

from customers.tests.factories import CustomerFactory
from hr.tests.factories import EmployeeFactory
from jobs.models import Job
from jobs.services import change_status
from jobs.tests.factories import JobFactory

pytestmark = pytest.mark.django_db

LIST_URL = reverse("jobs:list")
CREATE_URL = reverse("jobs:create")
COORDINATOR = ("view_job", "add_job", "change_job", "view_customer", "view_employee")


@pytest.fixture
def coordinator(client_with_perms):
    return client_with_perms(*COORDINATOR)


def url(name, job):
    return reverse(f"jobs:{name}", args=[job.pk])


def form_data(**overrides):
    data = {
        "customer": CustomerFactory().pk,
        "service_type": "plumbing",
        "title": "Kitchen sink leaking",
        "description": "Water under the cabinet",
        "site_address": "Villa 12, Al Malqa",
        "priority": "urgent",
        "scheduled_date": "",
        "technicians": [EmployeeFactory().pk],
        "quoted_amount": "350.00",
    }
    data.update(overrides)
    return data


def test_requires_permission(viewer_client):
    assert viewer_client.get(LIST_URL).status_code == 403


def test_create_job(coordinator):
    response = coordinator.post(CREATE_URL, form_data())
    job = Job.objects.get()
    assert response.status_code == 302
    assert response.url == url("detail", job)
    assert job.created_by.username == "custom_user"
    assert job.technicians.count() == 1
    assert job.priority == Job.Priority.URGENT


def test_create_preselects_customer_from_query(coordinator):
    customer = CustomerFactory()
    form = coordinator.get(CREATE_URL, {"customer": customer.pk}).context["form"]
    assert form.initial["customer"] == str(customer.pk)


def test_technician_choices_exclude_terminated(coordinator):
    import datetime as dt

    from hr.models import Employee

    active = EmployeeFactory()
    gone = EmployeeFactory(status=Employee.Status.TERMINATED, termination_date=dt.date(2024, 1, 1))
    qs = coordinator.get(CREATE_URL).context["form"].fields["technicians"].queryset
    assert active in qs and gone not in qs


def test_list_filters(coordinator):
    a = JobFactory(title="AC service", service_type="ac")
    b = JobFactory(title="Paint room", service_type="painting")
    tech = EmployeeFactory()
    b.technicians.add(tech)
    Job.objects.filter(pk=b.pk).update(priority="urgent")

    def pks(**params):
        return [j.pk for j in coordinator.get(LIST_URL, params).context["jobs"]]

    assert pks(service="painting") == [b.pk]
    assert pks(technician=tech.pk) == [b.pk]
    assert pks(priority="urgent") == [b.pk]
    assert pks(q="AC serv") == [a.pk]
    assert set(pks(status="new")) == {a.pk, b.pk}


def test_list_hides_closed_jobs_by_default(coordinator):
    open_job = JobFactory()
    closed = JobFactory()
    Job.objects.filter(pk=closed.pk).update(status="completed")
    assert [j.pk for j in coordinator.get(LIST_URL).context["jobs"]] == [open_job.pk]
    assert {j.pk for j in coordinator.get(LIST_URL, {"status": "all"}).context["jobs"]} == {open_job.pk, closed.pk}


def test_detail_shows_job(coordinator):
    job = JobFactory(title="Leaking AC")
    html = coordinator.get(url("detail", job)).content.decode()
    assert "Leaking AC" in html and job.number in html


def test_update_open_job(coordinator):
    job = JobFactory()
    response = coordinator.post(url("update", job), form_data(customer=job.customer.pk, title="Updated"))
    job.refresh_from_db()
    assert response.status_code == 302
    assert job.title == "Updated"


def test_update_form_renders(coordinator):
    assert coordinator.get(url("update", JobFactory())).status_code == 200


def test_cannot_edit_completed_job(coordinator):
    job = JobFactory()
    Job.objects.filter(pk=job.pk).update(status="completed")
    assert coordinator.get(url("update", job)).status_code == 409


def test_status_change_via_post(coordinator):
    job = JobFactory()
    job.technicians.add(EmployeeFactory())
    response = coordinator.post(url("status", job), {"status": "in_progress"})
    job.refresh_from_db()
    assert response.status_code == 302
    assert job.status == Job.Status.IN_PROGRESS


def test_invalid_status_change_shows_error(coordinator):
    job = JobFactory()
    response = coordinator.post(url("status", job), {"status": "completed"}, follow=True)
    job.refresh_from_db()
    assert job.status == Job.Status.NEW
    assert any(m.level_tag == "error" for m in response.context["messages"])


def test_cancel_with_reason_via_post(coordinator):
    job = JobFactory()
    coordinator.post(url("status", job), {"status": "cancelled", "reason": "Duplicate"})
    job.refresh_from_db()
    assert job.status == Job.Status.CANCELLED


def test_status_change_requires_post_and_permission(client_with_perms):
    client = client_with_perms("view_job")
    job = JobFactory()
    assert client.get(url("status", job)).status_code == 405
    assert client.post(url("status", job), {"status": "cancelled", "reason": "x"}).status_code == 403


def test_sidebar_links(client_with_perms):
    coordinator = client_with_perms("view_job", "view_customer")
    nav = coordinator.get(reverse("home")).content.decode()
    assert LIST_URL in nav and reverse("customers:list") in nav


def test_sidebar_hides_jobs_without_permission(viewer_client):
    html = viewer_client.get(reverse("home")).content.decode()
    assert LIST_URL not in html
    assert reverse("customers:list") not in html


def test_dashboard_job_kpis(coordinator):
    JobFactory()
    urgent = JobFactory()
    Job.objects.filter(pk=urgent.pk).update(priority="urgent")
    done = JobFactory()
    done.technicians.add(EmployeeFactory())
    change_status(done, Job.Status.IN_PROGRESS)
    change_status(done, Job.Status.COMPLETED)

    ctx = coordinator.get(reverse("home")).context

    assert ctx["show_jobs"] is True
    assert ctx["open_jobs"] == 2
    assert ctx["urgent_jobs"] == 1
    assert ctx["completed_this_month"] == 1


def test_dashboard_hides_jobs_without_permission(viewer_client):
    assert viewer_client.get(reverse("home")).context["show_jobs"] is False


def test_admin_pages_load(admin_client):
    JobFactory()
    assert admin_client.get(reverse("admin:jobs_job_changelist")).status_code == 200
    assert admin_client.get(reverse("admin:customers_customer_changelist")).status_code == 200


def test_dashboard_completed_count_ignores_other_months_of_the_same_year(coordinator):
    import datetime as dt

    today = timezone.localdate()
    other_month = 2 if today.month == 1 else today.month - 1
    old = JobFactory()
    Job.objects.filter(pk=old.pk).update(
        status=Job.Status.COMPLETED,
        completed_at=timezone.make_aware(dt.datetime(today.year, other_month, 15, 12)),
    )

    assert coordinator.get(reverse("home")).context["completed_this_month"] == 0
