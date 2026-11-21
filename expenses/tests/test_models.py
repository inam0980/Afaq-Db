"""Unit tests: Expense model rules, numbering, locking, querysets, seeds."""

import datetime as dt
import re
from decimal import Decimal as D

import pytest
from django.core.exceptions import ValidationError
from django.utils import timezone

from expenses.models import Expense, ExpenseCategory, ExpenseLocked
from expenses.tests.factories import ExpenseCategoryFactory, ExpenseFactory

pytestmark = pytest.mark.django_db


def clean_errors(expense):
    with pytest.raises(ValidationError) as exc:
        expense.full_clean()
    return exc.value.message_dict


def test_default_categories_are_seeded():
    codes = set(ExpenseCategory.objects.values_list("code", flat=True))
    assert {"RENT", "VEHICLE", "MATERIALS", "GOVT", "OTHER"} <= codes


def test_number_is_generated_sequentially():
    first, second = ExpenseFactory(), ExpenseFactory()
    assert re.fullmatch(r"EXP-\d{5}", first.number)
    assert int(second.number[4:]) == int(first.number[4:]) + 1


def test_number_does_not_change_on_resave():
    e = ExpenseFactory()
    original = e.number
    e.description = "Changed"
    e.save()
    assert e.number == original


def test_vat_is_split_on_save():
    e = ExpenseFactory(total=D("115.00"), vat_rate=D("15"))
    e.refresh_from_db()
    assert (e.amount_excl_vat, e.vat_amount) == (D("100.00"), D("15.00"))


def test_vat_recalculated_when_total_changes():
    e = ExpenseFactory(total=D("115.00"))
    e.total = D("230.00")
    e.save()
    assert e.vat_amount == D("30.00")


def test_vat_requires_vendor_vat_number():
    e = ExpenseFactory.build(vat_rate=D("15"), vendor_vat_number="")
    e.category.save()
    e.created_by.save()
    assert "vendor_vat_number" in clean_errors(e)


def test_zero_vat_does_not_need_vendor_vat_number():
    e = ExpenseFactory(vat_rate=D("0"), vendor_vat_number="")
    e.full_clean()


def test_future_date_rejected():
    e = ExpenseFactory()
    e.date = timezone.localdate() + dt.timedelta(days=1)
    assert "date" in clean_errors(e)


def test_total_must_be_positive():
    e = ExpenseFactory()
    e.total = D("0")
    assert "total" in clean_errors(e)


def test_changes_are_audited():
    e = ExpenseFactory()
    e.description = "Changed"
    e.save()
    assert e.history.count() == 2


# --- locking -----------------------------------------------------------------

@pytest.fixture
def approved():
    e = ExpenseFactory()
    Expense.objects.filter(pk=e.pk).update(status=Expense.Status.APPROVED)
    e.refresh_from_db()
    return e


def test_approved_expense_cannot_be_saved(approved):
    approved.total = D("1")
    with pytest.raises(ExpenseLocked):
        approved.save()


def test_approved_expense_cannot_be_deleted(approved):
    with pytest.raises(ExpenseLocked):
        approved.delete()
    assert Expense.objects.filter(pk=approved.pk).exists()


def test_draft_expense_can_be_deleted():
    e = ExpenseFactory()
    e.delete()
    assert not Expense.objects.exists()


# --- querysets ---------------------------------------------------------------

def test_for_month():
    jan = ExpenseFactory(date=dt.date(2026, 1, 31))
    ExpenseFactory(date=dt.date(2026, 2, 1))
    assert list(Expense.objects.for_month(2026, 1)) == [jan]


def test_totals():
    ExpenseFactory(total=D("115.00"))
    ExpenseFactory(total=D("50.00"), vat_rate=D("0"), vendor_vat_number="")
    t = Expense.objects.totals()
    assert t == {"count": 2, "total": D("165.00"), "vat": D("15.00"), "excl": D("150.00")}


def test_totals_of_empty_queryset_are_zero():
    assert Expense.objects.none().totals()["total"] == D("0")


def test_by_category_sorted_by_amount():
    fuel = ExpenseCategoryFactory(code="FUELX", name_en="Fuel")
    rent = ExpenseCategoryFactory(code="RENTX", name_en="Rent")
    ExpenseFactory(category=fuel, total=D("100"))
    ExpenseFactory(category=fuel, total=D("50"))
    ExpenseFactory(category=rent, total=D("1000"))

    rows = list(Expense.objects.by_category())

    assert [(r["category__name_en"], r["amount"]) for r in rows] == [
        ("Rent", D("1000.00")),
        ("Fuel", D("150.00")),
    ]


def test_str():
    e = ExpenseFactory(description="Diesel")
    assert str(e) == f"{e.number} - Diesel"
