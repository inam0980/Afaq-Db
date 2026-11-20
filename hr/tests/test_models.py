"""Unit tests: Employee / Department model rules, querysets and history."""

import datetime as dt
import re

import pytest
from django.core.exceptions import ValidationError
from django.db.models import ProtectedError

from hr.models import Employee
from hr.tests.factories import DepartmentFactory, EmployeeFactory, make_saudi_iban


def clean_errors(employee):
    with pytest.raises(ValidationError) as exc:
        employee.clean()
    return exc.value.message_dict


# --- Simple properties (no DB) -----------------------------------------------

def test_full_name():
    emp = EmployeeFactory.build(first_name="Ahmed", last_name="Khan")
    assert emp.full_name == "Ahmed Khan"


def test_str_shows_employee_no_and_name():
    emp = EmployeeFactory.build(employee_no="EMP-00007", first_name="Ahmed", last_name="Khan")
    assert str(emp) == "EMP-00007 - Ahmed Khan"


def test_is_saudi_depends_on_nationality():
    assert EmployeeFactory.build(nationality="SA").is_saudi is True
    assert EmployeeFactory.build(nationality="IN").is_saudi is False


# --- clean() business rules (no DB) ------------------------------------------

def test_saudi_must_have_national_id_starting_with_1():
    emp = EmployeeFactory.build(nationality="SA", id_number="2123456789")
    assert "id_number" in clean_errors(emp)


def test_expat_must_have_iqama_starting_with_2():
    emp = EmployeeFactory.build(nationality="IN", id_number="1123456789")
    assert "id_number" in clean_errors(emp)


def test_saudi_with_national_id_is_valid():
    EmployeeFactory.build(nationality="SA", id_number="1123456789").clean()


def test_birth_date_must_be_before_hire_date():
    emp = EmployeeFactory.build(date_of_birth=dt.date(2021, 1, 1), hire_date=dt.date(2020, 1, 1))
    assert "date_of_birth" in clean_errors(emp)


def test_termination_cannot_be_before_hire():
    emp = EmployeeFactory.build(
        hire_date=dt.date(2020, 1, 1),
        termination_date=dt.date(2019, 12, 31),
        status=Employee.Status.TERMINATED,
    )
    assert "termination_date" in clean_errors(emp)


def test_terminated_status_requires_termination_date():
    emp = EmployeeFactory.build(status=Employee.Status.TERMINATED, termination_date=None)
    assert "termination_date" in clean_errors(emp)


def test_termination_date_requires_terminated_status():
    emp = EmployeeFactory.build(
        status=Employee.Status.ACTIVE, termination_date=dt.date(2024, 1, 1)
    )
    assert "status" in clean_errors(emp)


def test_valid_terminated_employee_passes_clean():
    EmployeeFactory.build(
        status=Employee.Status.TERMINATED, termination_date=dt.date(2024, 1, 1)
    ).clean()


# --- Persistence (DB) --------------------------------------------------------

@pytest.mark.django_db
def test_employee_no_is_generated_sequentially():
    first = EmployeeFactory()
    second = EmployeeFactory()

    assert re.fullmatch(r"EMP-\d{5}", first.employee_no)
    assert int(second.employee_no[4:]) == int(first.employee_no[4:]) + 1


@pytest.mark.django_db
def test_employee_no_does_not_change_on_resave():
    emp = EmployeeFactory()
    original = emp.employee_no
    emp.job_title = "Supervisor"
    emp.save()
    emp.refresh_from_db()
    assert emp.employee_no == original


@pytest.mark.django_db
def test_save_normalizes_iban():
    iban = make_saudi_iban()
    spaced = " ".join(iban[i:i + 4] for i in range(0, len(iban), 4)).lower()
    emp = EmployeeFactory(iban=spaced)
    emp.refresh_from_db()
    assert emp.iban == iban


@pytest.mark.django_db
def test_department_with_employees_cannot_be_deleted():
    dept = DepartmentFactory()
    EmployeeFactory(department=dept)
    with pytest.raises(ProtectedError):
        dept.delete()


@pytest.mark.django_db
def test_history_is_recorded_on_every_change():
    emp = EmployeeFactory(job_title="Technician")
    emp.job_title = "Supervisor"
    emp.save()

    assert emp.history.count() == 2
    assert emp.history.first().job_title == "Supervisor"


# --- QuerySet methods (DB) ---------------------------------------------------

@pytest.mark.django_db
def test_active_excludes_terminated():
    active = EmployeeFactory()
    EmployeeFactory(status=Employee.Status.TERMINATED, termination_date=dt.date(2024, 1, 1))
    assert list(Employee.objects.active()) == [active]


@pytest.mark.django_db
def test_search_matches_name_employee_no_and_id():
    ahmed = EmployeeFactory(first_name="Ahmed", last_name="Khan", id_number="2000000001")
    sara = EmployeeFactory(first_name="Sara", last_name="Ali", id_number="2000000002")

    assert list(Employee.objects.search("ahm")) == [ahmed]
    assert list(Employee.objects.search("ahmed khan")) == [ahmed]
    assert list(Employee.objects.search(sara.employee_no)) == [sara]
    assert list(Employee.objects.search("2000000002")) == [sara]
    assert set(Employee.objects.search("")) == {ahmed, sara}
    assert list(Employee.objects.search("nobody")) == []


@pytest.mark.django_db
def test_with_expiring_documents():
    today = dt.date(2026, 1, 1)
    far = dt.date(2027, 1, 1)
    iqama_soon = EmployeeFactory(id_expiry=dt.date(2026, 1, 20), passport_expiry=far)
    already_expired = EmployeeFactory(id_expiry=dt.date(2025, 12, 1), passport_expiry=far)
    passport_soon = EmployeeFactory(id_expiry=far, passport_expiry=dt.date(2026, 1, 10))
    EmployeeFactory(id_expiry=far, passport_expiry=far)                     # not expiring
    EmployeeFactory(id_expiry=far, passport_expiry=None)                    # no passport
    EmployeeFactory(                                                        # terminated
        id_expiry=dt.date(2026, 1, 5),
        status=Employee.Status.TERMINATED,
        termination_date=dt.date(2025, 6, 1),
    )

    result = list(Employee.objects.with_expiring_documents(within_days=30, today=today))

    # Sorted by whichever document (iqama or passport) expires first.
    assert result == [already_expired, passport_soon, iqama_soon]
