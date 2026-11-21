import datetime as dt

import factory
from django.utils import timezone

from hr.models import Department, Employee
from hr.validators import build_saudi_iban


def make_saudi_iban(bank: str = "80", account: str = "000000608010167519") -> str:
    return build_saudi_iban(bank, account)


class DepartmentFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = Department
        django_get_or_create = ("code",)

    code = factory.Sequence(lambda n: f"D{n:03d}")
    name_en = factory.Sequence(lambda n: f"Department {n}")
    name_ar = "قسم"


class EmployeeFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = Employee

    first_name = factory.Faker("first_name")
    last_name = factory.Faker("last_name")
    name_ar = ""
    nationality = "IN"
    id_number = factory.Sequence(lambda n: f"2{n:09d}")
    id_expiry = factory.LazyFunction(lambda: timezone.localdate() + dt.timedelta(days=365))
    passport_no = factory.Sequence(lambda n: f"P{n:07d}")
    passport_expiry = factory.LazyFunction(
        lambda: timezone.localdate() + dt.timedelta(days=730)
    )
    date_of_birth = dt.date(1990, 1, 1)
    gender = Employee.Gender.MALE
    department = factory.SubFactory(DepartmentFactory)
    job_title = "Technician"
    hire_date = dt.date(2020, 1, 1)
    termination_date = None
    status = Employee.Status.ACTIVE
    mobile = factory.Sequence(lambda n: f"05{n:08d}")
    email = ""
    bank_name = "Al Rajhi Bank"
    iban = factory.Sequence(lambda n: make_saudi_iban(account=f"{n:018d}"))
