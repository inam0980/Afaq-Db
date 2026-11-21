"""Integration tests: URL -> permission -> view -> form -> PostgreSQL -> template."""

import datetime as dt

import pytest
from django.contrib.admin.sites import site as admin_site
from django.urls import reverse

from hr.models import Employee
from hr.tests.factories import DepartmentFactory, EmployeeFactory, make_saudi_iban

pytestmark = pytest.mark.django_db

LIST_URL = reverse("hr:employee_list")
CREATE_URL = reverse("hr:employee_create")
EXPIRING_URL = reverse("hr:expiring_documents")


def form_data(**overrides):
    data = {
        "first_name": "Ahmed",
        "last_name": "Khan",
        "name_ar": "أحمد خان",
        "nationality": "IN",
        "id_number": "2123456789",
        "id_expiry": "2027-05-01",
        "passport_no": "P1234567",
        "passport_expiry": "2028-05-01",
        "date_of_birth": "1990-03-15",
        "gender": "M",
        "department": DepartmentFactory().pk,
        "job_title": "AC Technician",
        "hire_date": "2022-02-01",
        "termination_date": "",
        "status": "active",
        "mobile": "0512345678",
        "email": "ahmed@example.com",
        "bank_name": "Al Rajhi Bank",
        "iban": make_saudi_iban(),
    }
    data.update(overrides)
    return data


# --- Access control -----------------------------------------------------------

def test_anonymous_user_is_redirected_to_login(client):
    response = client.get(LIST_URL)
    assert response.status_code == 302
    assert response.url.startswith(reverse("login"))


def test_user_without_permission_gets_403(no_perm_client):
    assert no_perm_client.get(LIST_URL).status_code == 403


def test_viewer_cannot_open_create_form(viewer_client):
    assert viewer_client.get(CREATE_URL).status_code == 403


def test_viewer_cannot_edit(viewer_client):
    emp = EmployeeFactory()
    url = reverse("hr:employee_update", args=[emp.pk])
    assert viewer_client.post(url, form_data()).status_code == 403


def test_login_page_renders(client):
    assert client.get(reverse("login")).status_code == 200


def test_root_shows_dashboard(hr_client):
    response = hr_client.get("/")
    assert response.status_code == 200
    assert "core/dashboard.html" in [t.name for t in response.templates]


# --- UI: empty state & form sections ------------------------------------------

def test_empty_list_invites_to_add_first_employee(hr_client):
    html = hr_client.get(LIST_URL).content.decode()
    assert "Add your first employee" in html
    assert CREATE_URL in html


def test_empty_list_without_add_permission_has_no_add_button(viewer_client):
    html = viewer_client.get(LIST_URL).content.decode()
    assert "Add your first employee" not in html
    assert CREATE_URL not in html


def test_employee_form_is_grouped_into_sections(hr_client):
    response = hr_client.get(CREATE_URL)
    html = response.content.decode()

    for heading in ["Personal", "Identity documents", "Employment", "Contact &amp; bank"]:
        assert heading in html, heading
    for name in response.context["form"].fields:      # every field still rendered
        assert f'name="{name}"' in html, name


def test_list_rows_show_initials_avatar(viewer_client):
    EmployeeFactory(first_name="Ahmed", last_name="Khan")
    html = viewer_client.get(LIST_URL).content.decode()
    assert 'class="avatar"' in html
    assert ">AK<" in html


# --- List + search (HTMX) ------------------------------------------------------

def test_list_shows_employees(viewer_client):
    emp = EmployeeFactory(first_name="Ahmed", last_name="Khan")
    response = viewer_client.get(LIST_URL)

    assert response.status_code == 200
    assert "Ahmed Khan" in response.content.decode()
    assert emp.employee_no in response.content.decode()


def test_search_filters_list(viewer_client):
    EmployeeFactory(first_name="Ahmed", last_name="Khan")
    EmployeeFactory(first_name="Sara", last_name="Ali")

    html = viewer_client.get(LIST_URL, {"q": "sara"}).content.decode()

    assert "Sara Ali" in html
    assert "Ahmed Khan" not in html


def test_htmx_search_returns_only_the_table_partial(viewer_client):
    EmployeeFactory(first_name="Sara", last_name="Ali")

    response = viewer_client.get(LIST_URL, {"q": "sara"}, HTTP_HX_REQUEST="true")
    html = response.content.decode()

    assert response.status_code == 200
    assert "<html" not in html
    assert "Sara Ali" in html
    assert [t.name for t in response.templates][0] == "hr/partials/employee_table.html"


def test_page_uses_local_htmx_not_cdn(viewer_client):
    html = viewer_client.get(LIST_URL).content.decode()
    assert "vendor/htmx-2.0.4.min.js" in html
    assert "unpkg.com" not in html


def test_arabic_request_renders_rtl(viewer_client):
    html = viewer_client.get(LIST_URL, HTTP_ACCEPT_LANGUAGE="ar").content.decode()
    assert 'dir="rtl"' in html


# --- Create ------------------------------------------------------------------

def test_create_valid_employee(hr_client, hr_user):
    response = hr_client.post(CREATE_URL, form_data())

    emp = Employee.objects.get()
    assert response.status_code == 302
    assert response.url == reverse("hr:employee_detail", args=[emp.pk])
    assert emp.employee_no.startswith("EMP-")
    assert emp.history.get().history_user == hr_user


def test_create_rejects_invalid_iban(hr_client):
    response = hr_client.post(CREATE_URL, form_data(iban="SA0000000000000000000000"))

    assert response.status_code == 200
    assert "iban" in response.context["form"].errors
    assert not Employee.objects.exists()


def test_create_rejects_saudi_with_iqama_number(hr_client):
    response = hr_client.post(CREATE_URL, form_data(nationality="SA", id_number="2123456789"))

    assert "id_number" in response.context["form"].errors
    assert not Employee.objects.exists()


def test_create_rejects_duplicate_id_number(hr_client):
    EmployeeFactory(id_number="2123456789")
    response = hr_client.post(CREATE_URL, form_data(id_number="2123456789"))

    assert "id_number" in response.context["form"].errors
    assert Employee.objects.count() == 1


# --- Update + detail -----------------------------------------------------------

def test_edit_form_is_prefilled_with_iso_dates(hr_client):
    emp = EmployeeFactory(hire_date=dt.date(2022, 2, 1), job_title="AC Technician")

    html = hr_client.get(reverse("hr:employee_update", args=[emp.pk])).content.decode()

    # <input type="date"> only shows values in YYYY-MM-DD format.
    assert 'type="date"' in html
    assert 'value="2022-02-01"' in html
    assert 'value="AC Technician"' in html


def test_create_accepts_iban_with_spaces_and_stores_it_compact(hr_client):
    iban = make_saudi_iban()
    spaced = " ".join(iban[i:i + 4] for i in range(0, len(iban), 4))

    hr_client.post(CREATE_URL, form_data(iban=spaced))

    assert Employee.objects.get().iban == iban


def test_update_changes_employee_and_records_history(hr_client):
    emp = EmployeeFactory(job_title="Technician")
    url = reverse("hr:employee_update", args=[emp.pk])

    data = form_data(
        id_number=emp.id_number, iban=emp.iban, job_title="Senior Technician"
    )
    response = hr_client.post(url, data)

    emp.refresh_from_db()
    assert response.status_code == 302
    assert emp.job_title == "Senior Technician"
    assert emp.history.count() == 2


def test_detail_shows_employee_and_change_history(viewer_client):
    emp = EmployeeFactory(first_name="Ahmed", last_name="Khan", job_title="Technician")
    emp.job_title = "Supervisor"
    emp.save()

    response = viewer_client.get(reverse("hr:employee_detail", args=[emp.pk]))
    html = response.content.decode()

    assert response.status_code == 200
    assert "Ahmed Khan" in html
    assert len(response.context["history"]) == 2


def test_detail_404_for_missing_employee(viewer_client):
    assert viewer_client.get(reverse("hr:employee_detail", args=[999999])).status_code == 404


# --- Expiring documents ------------------------------------------------------

def test_expiring_documents_page(viewer_client):
    soon = EmployeeFactory(id_expiry=dt.date.today() + dt.timedelta(days=10))
    later = EmployeeFactory(id_expiry=dt.date.today() + dt.timedelta(days=200))

    html = viewer_client.get(EXPIRING_URL).content.decode()

    assert soon.employee_no in html
    assert later.employee_no not in html


def test_expiring_documents_custom_window(viewer_client):
    later = EmployeeFactory(id_expiry=dt.date.today() + dt.timedelta(days=200))
    html = viewer_client.get(EXPIRING_URL, {"days": "365"}).content.decode()
    assert later.employee_no in html


@pytest.mark.parametrize("bad", ["abc", "-5", "0", "100000"])
def test_expiring_documents_bad_days_param_falls_back_safely(viewer_client, bad):
    response = viewer_client.get(EXPIRING_URL, {"days": bad})
    assert response.status_code == 200
    assert 1 <= response.context["days"] <= 365


# --- Admin -------------------------------------------------------------------

def test_admin_employee_changelist_loads(admin_client):
    EmployeeFactory()
    assert admin_client.get(reverse("admin:hr_employee_changelist")).status_code == 200


def test_admin_cannot_delete_employees(rf, admin_user):
    request = rf.get("/")
    request.user = admin_user
    assert admin_site._registry[Employee].has_delete_permission(request) is False


def test_expiring_page_shows_days_left_and_expired_badges(viewer_client):
    from django.utils import timezone

    today = timezone.localdate()
    EmployeeFactory(id_expiry=today + dt.timedelta(days=10), passport_expiry=None)
    EmployeeFactory(id_expiry=today - dt.timedelta(days=3), passport_expiry=None)

    html = viewer_client.get(EXPIRING_URL).content.decode()

    assert "10 days left" in html
    assert "Expired 3 days ago" in html
    assert "badge-expired" in html
    assert "badge-soon" in html
