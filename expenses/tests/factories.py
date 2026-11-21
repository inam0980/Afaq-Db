import datetime as dt
from decimal import Decimal

import factory
from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile

from expenses.models import Expense, ExpenseCategory


def receipt_file(name="receipt.pdf", content=b"%PDF-1.4 test receipt"):
    return SimpleUploadedFile(name, content, content_type="application/pdf")


class UserFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = get_user_model()
        django_get_or_create = ("username",)

    username = factory.Sequence(lambda n: f"user{n}")


class ExpenseCategoryFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = ExpenseCategory
        django_get_or_create = ("code",)

    code = factory.Sequence(lambda n: f"CAT{n}")
    name_en = factory.Sequence(lambda n: f"Category {n}")


class ExpenseFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = Expense

    date = dt.date(2026, 1, 15)
    category = factory.SubFactory(ExpenseCategoryFactory)
    description = "Diesel for service van"
    vendor_name = "Aldrees"
    vendor_vat_number = "300000000000003"
    total = Decimal("115.00")
    vat_rate = Decimal("15")
    payment_method = Expense.PaymentMethod.CASH
    created_by = factory.SubFactory(UserFactory)
    receipt = factory.LazyFunction(receipt_file)
