"""Unit tests: SalaryStructure and GosiRate models (need the DB)."""

import datetime as dt
from decimal import Decimal as D

import pytest
from django.core.exceptions import ValidationError
from django.db import IntegrityError

from hr.tests.factories import EmployeeFactory
from payroll.models import GosiRate, SalaryStructure
from payroll.tests.factories import SalaryStructureFactory

pytestmark = pytest.mark.django_db


def test_gross_fixed_is_sum_of_components():
    s = SalaryStructureFactory.build(
        basic=D("4800"), housing=D("1200"), transport=D("600"), other=D("100")
    )
    assert s.gross_fixed == D("6700")


def test_basic_must_be_positive():
    s = SalaryStructureFactory(basic=D("1000"))
    s.basic = D("0")
    with pytest.raises(ValidationError) as exc:
        s.full_clean()
    assert "basic" in exc.value.message_dict


def test_allowances_cannot_be_negative():
    s = SalaryStructureFactory()
    s.housing = D("-1")
    with pytest.raises(ValidationError) as exc:
        s.full_clean()
    assert "housing" in exc.value.message_dict


def test_one_structure_per_employee_per_date():
    first = SalaryStructureFactory(effective_from=dt.date(2024, 1, 1))
    with pytest.raises(IntegrityError):
        SalaryStructureFactory(employee=first.employee, effective_from=dt.date(2024, 1, 1))


def test_current_for_picks_latest_effective_on_or_before_date():
    emp = EmployeeFactory()
    old = SalaryStructureFactory(employee=emp, effective_from=dt.date(2020, 1, 1), basic=D("5000"))
    new = SalaryStructureFactory(employee=emp, effective_from=dt.date(2024, 1, 1), basic=D("6000"))
    SalaryStructureFactory(effective_from=dt.date(2025, 1, 1))   # other employee

    assert SalaryStructure.objects.current_for(emp, dt.date(2023, 12, 31)) == old
    assert SalaryStructure.objects.current_for(emp, dt.date(2024, 1, 1)) == new
    assert SalaryStructure.objects.current_for(emp, dt.date(2019, 12, 31)) is None


def test_salary_changes_are_audited():
    s = SalaryStructureFactory(basic=D("5000"))
    s.basic = D("5500")
    s.save()
    assert s.history.count() == 2


# --- GOSI rates (seeded by migration) -----------------------------------------

def test_default_gosi_rates_are_seeded():
    saudi = GosiRate.for_employee(EmployeeFactory.build(nationality="SA"), dt.date(2026, 1, 1))
    expat = GosiRate.for_employee(EmployeeFactory.build(nationality="IN"), dt.date(2026, 1, 1))

    assert (saudi.employee_rate, saudi.employer_rate, saudi.salary_cap) == (
        D("9.75"), D("11.75"), D("45000.00"),
    )
    assert (expat.employee_rate, expat.employer_rate) == (D("0.00"), D("2.00"))


def test_newer_gosi_rate_applies_from_its_effective_date():
    GosiRate.objects.create(
        category=GosiRate.Category.SAUDI,
        effective_from=dt.date(2026, 7, 1),
        employee_rate=D("10.25"),
        employer_rate=D("12.25"),
        salary_cap=D("45000"),
    )
    saudi = EmployeeFactory.build(nationality="SA")

    assert GosiRate.for_employee(saudi, dt.date(2026, 6, 30)).employee_rate == D("9.75")
    assert GosiRate.for_employee(saudi, dt.date(2026, 7, 1)).employee_rate == D("10.25")


def test_missing_gosi_rate_raises_clear_error():
    GosiRate.objects.all().delete()
    with pytest.raises(GosiRate.DoesNotExist):
        GosiRate.for_employee(EmployeeFactory.build(nationality="SA"), dt.date(2026, 1, 1))
