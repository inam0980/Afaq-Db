import datetime as dt
from decimal import Decimal

import factory

from hr.tests.factories import EmployeeFactory
from payroll.models import PayrollRun, SalaryStructure


class PayrollRunFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = PayrollRun
        django_get_or_create = ("year", "month")

    year = 2026
    month = 1


class SalaryStructureFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = SalaryStructure

    employee = factory.SubFactory(EmployeeFactory)
    effective_from = dt.date(2020, 1, 1)
    basic = Decimal("4800.00")
    housing = Decimal("1200.00")
    transport = Decimal("600.00")
    other = Decimal("600.00")
