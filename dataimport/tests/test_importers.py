"""Unit tests: validating and saving employees, customers and salaries."""

import datetime as dt
from decimal import Decimal as D

import pytest

from customers.models import Customer
from customers.tests.factories import CustomerFactory
from dataimport.importers import IMPORTERS
from dataimport.tests.helpers import EMPLOYEE_HEADERS, employee_row
from hr.models import Employee
from hr.tests.factories import DepartmentFactory, EmployeeFactory
from payroll.models import SalaryStructure

pytestmark = pytest.mark.django_db


@pytest.fixture(autouse=True)
def ops():
    return DepartmentFactory(code="OPS", name_en="Operations")


def as_dicts(headers, rows):
    return [dict(zip(headers, r)) for r in rows]


def check(kind, headers, rows):
    return IMPORTERS[kind].validate(as_dicts(headers, rows))


# --- employees -------------------------------------------------------------------

def test_valid_employees_import(ops):
    report = check("employees", EMPLOYEE_HEADERS, [
        employee_row(),
        employee_row(first_name="Sara", nationality="SA", id_number="1123456789", gender="F",
                     mobile="0598765432", department=""),
    ])
    assert report.ok and report.errors == []
    created = IMPORTERS["employees"].save(report)
    assert created == 2
    a = Employee.objects.get(id_number="2123456789")
    assert (a.department, a.employee_no.startswith("EMP-")) == (ops, True)
    assert Employee.objects.get(id_number="1123456789").department is None


def test_row_errors_name_the_row_and_column():
    report = check("employees", EMPLOYEE_HEADERS, [
        employee_row(),
        employee_row(id_number="2999999999", iban="SA0000000000000000000000", mobile="0598765432"),
    ])
    assert not report.ok
    assert any(e.startswith("Row 3: iban") for e in report.errors), report.errors


def test_saudi_with_iqama_number_rejected():
    report = check("employees", EMPLOYEE_HEADERS, [employee_row(nationality="SA", id_number="2123456789")])
    assert any("id_number" in e for e in report.errors)


def test_unknown_department_and_nationality():
    report = check("employees", EMPLOYEE_HEADERS, [employee_row(department="NOPE", nationality="Atlantis")])
    joined = " ".join(report.errors)
    assert "department" in joined and "nationality" in joined


def test_nationality_and_gender_by_name():
    report = check("employees", EMPLOYEE_HEADERS, [employee_row(nationality="India", gender="Male")])
    assert report.ok, report.errors


def test_bad_date_reported():
    report = check("employees", EMPLOYEE_HEADERS, [employee_row(hire_date="someday")])
    assert any("hire_date" in e for e in report.errors)


def test_duplicate_id_inside_the_file():
    report = check("employees", EMPLOYEE_HEADERS, [employee_row(), employee_row(mobile="0598765432")])
    assert any("Row 3: id_number" in e for e in report.errors)


def test_existing_employee_is_not_overwritten():
    EmployeeFactory(id_number="2123456789")
    report = check("employees", EMPLOYEE_HEADERS, [employee_row()])
    assert any("already exists" in e for e in report.errors)


def test_missing_required_column():
    report = IMPORTERS["employees"].validate([{"first_name": "A"}])
    assert not report.ok and any("Missing column" in e for e in report.errors)


def test_nothing_saved_when_any_row_is_invalid():
    report = check("employees", EMPLOYEE_HEADERS, [employee_row(), employee_row(id_number="bad")])
    with pytest.raises(ValueError):
        IMPORTERS["employees"].save(report)
    assert not Employee.objects.exists()


def test_empty_file_is_not_ok():
    report = IMPORTERS["employees"].validate([])
    assert not report.ok


# --- customers --------------------------------------------------------------------

CUSTOMER_HEADERS = ["name", "name_ar", "kind", "mobile", "email", "vat_number",
                    "building_number", "street", "district", "city", "postal_code"]


def test_customers_import():
    report = check("customers", CUSTOMER_HEADERS, [
        ["Riyadh Towers", "", "business", "0551000001", "", "300000000000003", "1234", "King Fahd Rd",
         "Olaya", "Riyadh", "12211"],
        ["Khalid", "", "individual", 551000002, "", "", "", "", "", "Riyadh", ""],
    ])
    assert report.ok, report.errors
    assert IMPORTERS["customers"].save(report) == 2
    assert Customer.objects.get(name="Khalid").mobile == "0551000002"


def test_business_with_vat_needs_address():
    report = check("customers", CUSTOMER_HEADERS, [
        ["Riyadh Towers", "", "business", "0551000001", "", "300000000000003", "", "", "", "Riyadh", ""],
    ])
    assert not report.ok and any("street" in e for e in report.errors)


def test_customer_with_existing_mobile_rejected():
    CustomerFactory(mobile="0551000001")
    report = check("customers", CUSTOMER_HEADERS, [
        ["Dup", "", "individual", "0551000001", "", "", "", "", "", "", ""],
    ])
    assert any("already exists" in e for e in report.errors)


def test_unknown_customer_kind():
    report = check("customers", CUSTOMER_HEADERS, [["X", "", "company?", "0551000009", "", "", "", "", "", "", ""]])
    assert any("kind" in e for e in report.errors)


# --- salaries ---------------------------------------------------------------------

SALARY_HEADERS = ["id_number", "effective_from", "basic", "housing", "transport", "other"]


def test_salaries_import():
    emp = EmployeeFactory(id_number="2123456789")
    report = check("salaries", SALARY_HEADERS, [["2123456789", "2024-01-01", 4000, "1,000", 400, ""]])
    assert report.ok, report.errors
    IMPORTERS["salaries"].save(report)
    s = SalaryStructure.objects.get(employee=emp)
    assert (s.basic, s.housing, s.transport, s.other) == (D("4000"), D("1000"), D("400"), D("0"))


def test_salary_for_unknown_employee():
    report = check("salaries", SALARY_HEADERS, [["2000000000", "2024-01-01", 4000, 0, 0, 0]])
    assert report.errors == ["Row 2: id_number — No employee with this ID / iqama number."]


def test_salary_duplicate_effective_date():
    from payroll.tests.factories import SalaryStructureFactory

    emp = EmployeeFactory(id_number="2123456789")
    SalaryStructureFactory(employee=emp, effective_from=dt.date(2024, 1, 1))
    report = check("salaries", SALARY_HEADERS, [["2123456789", "2024-01-01", 4000, 0, 0, 0]])
    assert any("already exists" in e for e in report.errors)


def test_salary_bad_number():
    EmployeeFactory(id_number="2123456789")
    report = check("salaries", SALARY_HEADERS, [["2123456789", "2024-01-01", "lots", 0, 0, 0]])
    assert any("basic" in e for e in report.errors)


def test_preview_rows_are_json_friendly():
    import json

    report = check("employees", EMPLOYEE_HEADERS, [employee_row()])
    json.dumps(report.rows)      # stored in the session between preview and confirm


def test_customer_kind_defaults_to_individual_and_accepts_labels():
    report = check("customers", CUSTOMER_HEADERS, [
        ["Khalid", "", "", "0551000002", "", "", "", "", "", "", ""],
        ["Riyadh Towers", "", "Business", "0551000003", "", "", "", "", "", "", ""],
        ["Arabic", "", "فرد", "0551000004", "", "", "", "", "", "", ""],
    ])
    assert report.ok, report.errors
    assert [o.kind for o in report.objects] == ["individual", "business", "individual"]


def test_duplicate_mobile_inside_customer_file():
    report = check("customers", CUSTOMER_HEADERS, [
        ["A", "", "individual", "0551000002", "", "", "", "", "", "", ""],
        ["B", "", "individual", "551000002", "", "", "", "", "", "", ""],
    ])
    assert "Row 3: mobile — Same as row 2 in this file." in report.errors


def test_department_by_name_and_iban_spaces():
    report = check("employees", EMPLOYEE_HEADERS, [employee_row(department="operations")])
    assert report.ok, report.errors
    row = employee_row()
    iban = row[EMPLOYEE_HEADERS.index("iban")]
    spaced = check("employees", EMPLOYEE_HEADERS, [employee_row(iban=" ".join([iban[:4], iban[4:]]).lower())])
    assert spaced.ok, spaced.errors
    assert spaced.objects[0].iban == iban


def test_preview_table_marks_bad_rows():
    report = check("employees", EMPLOYEE_HEADERS, [
        employee_row(), employee_row(id_number="2999999990", hire_date="soon", mobile="0598765432"),
    ])
    (n1, v1, bad1), (n2, v2, bad2) = report.table
    assert (n1, bad1, n2, bad2) == (2, False, 3, True)
    assert v1[0] == "Ahmed" and v2[EMPLOYEE_HEADERS.index("hire_date")] == "soon"
    assert report.rows[0]["hire_date"] == "2022-02-01"


def test_salaries_revalidate_from_preview_rows():
    EmployeeFactory(id_number="2123456789")
    first = check("salaries", SALARY_HEADERS, [["2123456789", "01/01/2024", "4,000", "", "", ""]])
    again = IMPORTERS["salaries"].validate(first.rows)
    assert again.ok, again.errors
    assert again.objects[0].basic == D("4000")


def test_empty_file_message():
    assert IMPORTERS["employees"].validate([]).errors == ["The file has no data rows."]


def test_employee_mobile_leading_zero_restored():
    report = check("employees", EMPLOYEE_HEADERS, [employee_row(mobile=512345678)])
    assert report.ok, report.errors
    assert report.objects[0].mobile == "0512345678"


def test_failure_half_way_saves_nothing():
    report = check("employees", EMPLOYEE_HEADERS, [
        employee_row(), employee_row(id_number="2234567890", mobile="0598765432"),
    ])
    assert report.ok, report.errors
    EmployeeFactory(id_number="2234567890")          # appears between validate and save
    from django.db import IntegrityError

    with pytest.raises(IntegrityError):
        IMPORTERS["employees"].save(report)
    assert list(Employee.objects.values_list("id_number", flat=True)) == ["2234567890"]
