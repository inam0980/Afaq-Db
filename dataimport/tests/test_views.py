"""Integration tests: upload -> preview -> confirm, templates, permissions."""

import io

import pytest
from django.urls import reverse
from openpyxl import load_workbook

from dataimport.tests.helpers import EMPLOYEE_HEADERS, csv_file, employee_row, xlsx_file
from hr.models import Employee
from hr.tests.factories import DepartmentFactory

pytestmark = pytest.mark.django_db

INDEX = reverse("dataimport:index")


def upload_url(kind):
    return reverse("dataimport:upload", args=[kind])


@pytest.fixture(autouse=True)
def ops():
    return DepartmentFactory(code="OPS")


@pytest.fixture
def hr(client_with_perms):
    return client_with_perms("view_employee", "add_employee")


def test_index_lists_only_permitted_imports(hr):
    html = hr.get(INDEX).content.decode()
    assert upload_url("employees") in html
    assert upload_url("customers") not in html


def test_index_requires_some_import_permission(viewer_client):
    assert viewer_client.get(INDEX).status_code == 403


def test_upload_requires_permission_for_that_kind(hr):
    assert hr.get(upload_url("customers")).status_code == 403


def test_unknown_kind_404(hr):
    assert hr.get(upload_url("spaceships")).status_code == 404


def test_upload_shows_preview(hr):
    response = hr.post(upload_url("employees"), {"file": xlsx_file([EMPLOYEE_HEADERS, employee_row()])})
    assert response.status_code == 200
    assert response.context["report"].ok
    assert "Ahmed" in response.content.decode()
    assert not Employee.objects.exists()               # nothing saved yet


def test_upload_with_errors_shows_them_and_no_confirm(hr):
    response = hr.post(upload_url("employees"),
                       {"file": csv_file([EMPLOYEE_HEADERS, employee_row(iban="SA00")])})
    html = response.content.decode()
    assert not response.context["report"].ok
    assert "Row 2: iban" in html
    assert reverse("dataimport:confirm", args=["employees"]) not in html


def test_bad_file_shows_message(hr):
    from django.core.files.uploadedfile import SimpleUploadedFile

    response = hr.post(upload_url("employees"), {"file": SimpleUploadedFile("x.pdf", b"%PDF")})
    assert response.status_code == 200 and response.context["form"].errors


def test_confirm_imports_the_previewed_rows(hr):
    hr.post(upload_url("employees"), {"file": xlsx_file([EMPLOYEE_HEADERS, employee_row()])})
    response = hr.post(reverse("dataimport:confirm", args=["employees"]))
    assert response.status_code == 302
    assert Employee.objects.count() == 1


def test_confirm_without_preview_does_nothing(hr):
    response = hr.post(reverse("dataimport:confirm", args=["employees"]), follow=True)
    assert not Employee.objects.exists()
    assert any(m.level_tag == "error" for m in response.context["messages"])


def test_confirm_revalidates(hr):
    from hr.tests.factories import EmployeeFactory

    hr.post(upload_url("employees"), {"file": xlsx_file([EMPLOYEE_HEADERS, employee_row()])})
    EmployeeFactory(id_number="2123456789")              # created by someone else meanwhile
    response = hr.post(reverse("dataimport:confirm", args=["employees"]), follow=True)
    assert Employee.objects.count() == 1
    assert any(m.level_tag == "error" for m in response.context["messages"])


def test_confirm_requires_post(hr):
    assert hr.get(reverse("dataimport:confirm", args=["employees"])).status_code == 405


def test_template_download_is_an_xlsx_with_headers(hr):
    response = hr.get(reverse("dataimport:template", args=["employees"]))
    assert "attachment" in response["Content-Disposition"]
    wb = load_workbook(io.BytesIO(response.content))
    headers = [c.value for c in wb.active[1]]
    assert headers == EMPLOYEE_HEADERS
    assert wb.active.max_row == 2                       # one example row
    example = [c.value for c in wb.active[2]]
    assert example[:2] == ["Ahmed", "Khan"]


def test_sidebar_link(hr):
    assert INDEX in hr.get(reverse("home")).content.decode()


def test_sidebar_hides_link_without_permission(viewer_client):
    assert INDEX not in viewer_client.get(reverse("home")).content.decode()


def test_file_over_size_limit(hr, settings):
    from django.core.files.uploadedfile import SimpleUploadedFile

    from dataimport.reading import MAX_BYTES

    big = SimpleUploadedFile("big.csv", b"a" * (MAX_BYTES + 1))
    response = hr.post(upload_url("employees"), {"file": big})
    assert "file" in response.context["form"].errors
    assert response.context["report"] is None


def test_customers_flow_redirects_to_customer_list(client_with_perms):
    c = client_with_perms("view_customer", "add_customer")
    rows = [["name", "mobile"], ["Khalid", "0551000002"]]
    preview = c.post(upload_url("customers"), {"file": csv_file(rows)})
    assert preview.context["report"].ok
    response = c.post(reverse("dataimport:confirm", args=["customers"]), follow=True)
    assert response.redirect_chain[-1][0] == reverse("customers:list")
    assert "Imported 1 record." in response.content.decode()


def test_failed_preview_clears_an_older_good_one(hr):
    hr.post(upload_url("employees"), {"file": xlsx_file([EMPLOYEE_HEADERS, employee_row()])})
    hr.post(upload_url("employees"), {"file": xlsx_file([EMPLOYEE_HEADERS, employee_row(iban="SA00")])})
    hr.post(reverse("dataimport:confirm", args=["employees"]))
    assert not Employee.objects.exists()


@pytest.mark.parametrize("kind", ["employees", "customers", "salaries"])
def test_template_example_row_imports_cleanly(kind):
    """The example row in each template must itself pass validation."""
    from dataimport.importers import IMPORTERS
    from hr.tests.factories import EmployeeFactory

    if kind == "salaries":
        EmployeeFactory(id_number="2123456789")      # the salary example refers to this employee
    importer = IMPORTERS[kind]
    report = importer.validate([dict(importer.example)])
    assert report.ok, report.errors
