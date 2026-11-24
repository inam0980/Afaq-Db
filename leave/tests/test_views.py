"""Integration tests: leave pages, approval buttons, employee page, dashboard, sidebar."""

import datetime as dt

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from django.urls import reverse
from django.utils import timezone

from hr.tests.factories import EmployeeFactory
from leave.models import LeaveRequest
from leave.tests.factories import leave_type, make_request

pytestmark = pytest.mark.django_db

S = LeaveRequest.Status
LIST_URL = reverse("leave:list")
CREATE_URL = reverse("leave:create")
HR_PERMS = ("view_leaverequest", "add_leaverequest", "change_leaverequest", "view_employee")


@pytest.fixture
def hr_clerk(client_with_perms):
    return client_with_perms(*HR_PERMS)


@pytest.fixture
def approver(django_user_model):
    from django.contrib.auth.models import Permission
    from django.test import Client

    user = django_user_model.objects.create_user("boss", password="Test-pass-123")
    user.user_permissions.add(*Permission.objects.filter(codename__in=[*HR_PERMS, "approve_leaverequest"]))
    c = Client()
    c.force_login(user)
    return c


def url(name, r):
    return reverse(f"leave:{name}", args=[r.pk])


def test_requires_permission(viewer_client):
    assert viewer_client.get(LIST_URL).status_code == 403


def test_create_request(hr_clerk):
    emp = EmployeeFactory(hire_date=dt.date(2015, 1, 1))
    data = {"employee": emp.pk, "leave_type": leave_type("ANNUAL").pk,
            "start_date": "2026-03-01", "end_date": "2026-03-05", "reason": "Umrah"}
    response = hr_clerk.post(CREATE_URL, data)
    r = LeaveRequest.objects.get()
    assert response.status_code == 302 and response.url == url("detail", r)
    assert (r.days, r.status, r.created_by.username) == (5, S.PENDING, "custom_user")


def test_create_with_certificate(hr_clerk):
    emp = EmployeeFactory(hire_date=dt.date(2015, 1, 1))
    data = {"employee": emp.pk, "leave_type": leave_type("SICK").pk, "start_date": "2026-03-01",
            "end_date": "2026-03-02", "reason": "", "attachment": SimpleUploadedFile("cert.pdf", b"%PDF")}
    hr_clerk.post(CREATE_URL, data)
    assert LeaveRequest.objects.get().attachment


def test_create_shows_rule_errors(hr_clerk):
    emp = EmployeeFactory(hire_date=dt.date(2015, 1, 1))
    data = {"employee": emp.pk, "leave_type": leave_type("PATERNITY").pk,
            "start_date": "2026-03-01", "end_date": "2026-03-10", "reason": ""}
    response = hr_clerk.post(CREATE_URL, data)
    assert response.status_code == 200 and response.context["form"].errors
    assert not LeaveRequest.objects.exists()


def test_create_preselects_employee(hr_clerk):
    emp = EmployeeFactory()
    assert hr_clerk.get(CREATE_URL, {"employee": emp.pk}).context["form"].initial["employee"] == str(emp.pk)


def test_list_filters(hr_clerk):
    a = make_request(status=S.PENDING)
    b = make_request(status=S.APPROVED, code="SICK")

    def pks(**p):
        return [r.pk for r in hr_clerk.get(LIST_URL, p).context["requests"]]

    assert pks(status="pending") == [a.pk]
    assert pks(type="SICK") == [b.pk]
    assert pks(employee=b.employee.pk) == [b.pk]
    assert set(pks()) == {a.pk, b.pk}


def test_clerk_cannot_approve(hr_clerk):
    r = make_request()
    assert hr_clerk.post(url("approve", r)).status_code == 403


def test_approver_approves(approver):
    r = make_request()
    response = approver.post(url("approve", r))
    r.refresh_from_db()
    assert response.status_code == 302 and r.status == S.APPROVED


def test_approve_error_shown(approver):
    r = make_request(code="SICK")                       # no certificate
    response = approver.post(url("approve", r), follow=True)
    r.refresh_from_db()
    assert r.status == S.PENDING
    assert any(m.level_tag == "error" for m in response.context["messages"])


def test_reject_with_note(approver):
    r = make_request()
    approver.post(url("reject", r), {"note": "Busy season"})
    r.refresh_from_db()
    assert (r.status, r.decision_note) == (S.REJECTED, "Busy season")


def test_cancel(hr_clerk):
    r = make_request(start=timezone.localdate() + dt.timedelta(days=30),
                     end=timezone.localdate() + dt.timedelta(days=31))
    hr_clerk.post(url("cancel", r))
    r.refresh_from_db()
    assert r.status == S.CANCELLED


def test_actions_require_post(approver):
    r = make_request()
    assert approver.get(url("approve", r)).status_code == 405


def test_detail_and_attachment_download(hr_clerk):
    r = make_request(code="SICK")
    r.attachment = SimpleUploadedFile("cert.pdf", b"%PDF-sick")
    r.save()
    assert r.employee.full_name in hr_clerk.get(url("detail", r)).content.decode()
    response = hr_clerk.get(url("attachment", r))
    assert b"".join(response.streaming_content) == b"%PDF-sick"


def test_attachment_404_when_missing(hr_clerk):
    assert hr_clerk.get(url("attachment", make_request())).status_code == 404


def test_employee_page_shows_balance_and_leaves(hr_clerk):
    emp = EmployeeFactory(hire_date=dt.date(2015, 1, 1))
    make_request(emp, status=S.APPROVED)
    response = hr_clerk.get(reverse("hr:employee_detail", args=[emp.pk]))
    html = response.content.decode()
    assert response.context["leave_balance"].taken == 5
    assert CREATE_URL in html


def test_employee_page_hides_leave_without_permission(viewer_client):
    emp = EmployeeFactory()
    assert viewer_client.get(reverse("hr:employee_detail", args=[emp.pk])).context["leave_balance"] is None


def test_dashboard_on_leave_and_pending(hr_clerk):
    today = timezone.localdate()
    make_request(start=today, end=today, status=S.APPROVED, code="SICK")
    make_request(status=S.PENDING)
    ctx = hr_clerk.get(reverse("home")).context
    assert (ctx["on_leave_today"], ctx["pending_leave"]) == (1, 1)


def test_dashboard_hides_leave_without_permission(viewer_client):
    assert "on_leave_today" not in viewer_client.get(reverse("home")).context


def test_sidebar_link(hr_clerk):
    assert LIST_URL in hr_clerk.get(reverse("home")).content.decode()


def test_sidebar_hides_link_without_permission(viewer_client):
    assert LIST_URL not in viewer_client.get(reverse("home")).content.decode()


def test_admin_pages(admin_client):
    make_request()
    assert admin_client.get(reverse("admin:leave_leaverequest_changelist")).status_code == 200
    assert admin_client.get(reverse("admin:leave_leavetype_changelist")).status_code == 200


def test_annual_leave_detail_shows_balance(hr_clerk):
    r = make_request(code="ANNUAL")
    assert hr_clerk.get(url("detail", r)).context["balance"].taken == 0


def test_sick_leave_detail_has_no_annual_balance(hr_clerk):
    r = make_request(code="SICK")
    assert hr_clerk.get(url("detail", r)).context["balance"] is None


def test_document_missing_on_disk_gives_404(hr_clerk):
    import os

    r = make_request(code="SICK")
    r.attachment = SimpleUploadedFile("cert.pdf", b"%PDF")
    r.save()
    os.remove(r.attachment.path)
    assert hr_clerk.get(url("attachment", r)).status_code == 404
