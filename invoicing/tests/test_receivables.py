"""Unit tests: customer balance, statement with running balance, aging buckets."""

import datetime as dt
from decimal import Decimal as D

import pytest
from django.utils import timezone

from customers.tests.factories import CustomerFactory
from expenses.tests.factories import UserFactory
from invoicing.balances import aging, customer_balance, statement
from invoicing.services import create_credit_note, issue, recalculate, record_payment
from invoicing.tests.factories import invoice_with_lines, issued_invoice

pytestmark = pytest.mark.django_db

TODAY = dt.date(2026, 6, 30)


@pytest.fixture
def user():
    return UserFactory()


@pytest.fixture
def customer():
    return CustomerFactory()


def inv_on(customer, day, price="1000", due_days=30):
    return issued_invoice(price, customer=customer, issue_date=day, due_date=day + dt.timedelta(days=due_days))


def test_customer_balance(customer, user):
    a = inv_on(customer, timezone.localdate())                     # 1150
    inv_on(customer, timezone.localdate(), price="100")            # 115
    invoice_with_lines("5000", customer=customer)                  # draft: ignored
    issued_invoice(customer=CustomerFactory())                     # other customer: ignored
    record_payment(a, user, amount=D("150"), date=timezone.localdate(), method="cash", reference="")
    assert customer_balance(customer) == D("1115.00")


def test_statement_running_balance(customer, user):
    d = dt.date
    jan = inv_on(customer, d(2026, 1, 10))                         # 1150 (before the period)
    record_payment(jan, user, amount=D("150"), date=d(2026, 1, 20), method="cash", reference="")
    feb = inv_on(customer, d(2026, 2, 5), price="200")             # 230
    record_payment(jan, user, amount=D("1000"), date=d(2026, 2, 10), method="bank", reference="T1")
    cn = create_credit_note(feb, user, reason="Discount")
    line = cn.lines.first(); line.unit_price = D("20"); line.save(); recalculate(cn)
    from invoicing.models import Invoice
    Invoice.objects.filter(pk=cn.pk).update(issue_date=d(2026, 2, 12), due_date=d(2026, 2, 12))
    issue(cn, user)                                                # 23.00 credit

    s = statement(customer, d(2026, 2, 1), d(2026, 2, 28))

    assert s.opening_balance == D("1000.00")                       # 1150 - 150
    assert [(e.kind, e.debit, e.credit, e.balance) for e in s.entries] == [
        ("invoice", D("230.00"), None, D("1230.00")),
        ("payment", None, D("1000.00"), D("230.00")),
        ("credit_note", None, D("23.00"), D("207.00")),
    ]
    assert s.closing_balance == D("207.00")
    assert s.total_debits == D("230.00") and s.total_credits == D("1023.00")


def test_statement_with_no_activity(customer):
    s = statement(customer, dt.date(2026, 1, 1), dt.date(2026, 1, 31))
    assert (s.opening_balance, s.entries, s.closing_balance) == (D("0.00"), [], D("0.00"))


def test_aging_buckets(customer, user):
    d = TODAY
    inv_on(customer, d - dt.timedelta(days=10))                    # due in 20 days -> current
    inv_on(customer, d - dt.timedelta(days=45))                    # 15 days late   -> 1-30
    inv_on(customer, d - dt.timedelta(days=80))                    # 50 days late   -> 31-60
    inv_on(customer, d - dt.timedelta(days=110))                   # 80 days late   -> 61-90
    old = inv_on(customer, d - dt.timedelta(days=200))             # 170 days late  -> 90+
    record_payment(old, user, amount=D("1000"), date=d - dt.timedelta(days=100), method="cash", reference="")
    paid = inv_on(customer, d - dt.timedelta(days=300))            # fully paid -> not listed
    record_payment(paid, user, amount=D("1150"), date=d - dt.timedelta(days=250), method="cash", reference="")

    report = aging(as_of=d)
    row = report.rows[0]

    assert len(report.rows) == 1 and row.customer == customer
    assert row.buckets == {
        "current": D("1150.00"), "1_30": D("1150.00"), "31_60": D("1150.00"),
        "61_90": D("1150.00"), "90_plus": D("150.00"),
    }
    assert row.total == D("4750.00") and row.overdue == D("3600.00")
    assert report.totals["total"] == D("4750.00")
    assert report.totals["overdue"] == D("3600.00")


@pytest.mark.parametrize("days_late, bucket", [(0, "current"), (1, "1_30"), (30, "1_30"), (31, "31_60"),
                                               (60, "31_60"), (61, "61_90"), (90, "61_90"), (91, "90_plus")])
def test_aging_bucket_boundaries(customer, days_late, bucket):
    due = TODAY - dt.timedelta(days=days_late)
    inv_on(customer, due - dt.timedelta(days=30))
    row = aging(as_of=TODAY).rows[0]
    assert row.buckets[bucket] == D("1150.00")


def test_aging_sorted_by_largest_overdue_first(user):
    small, big = CustomerFactory(name="Alpha Small"), CustomerFactory(name="Zulu Big")
    inv_on(small, TODAY - dt.timedelta(days=60), price="100")
    inv_on(big, TODAY - dt.timedelta(days=60), price="5000")
    # biggest overdue first, even though "Alpha" sorts before "Zulu"
    assert [r.customer.name for r in aging(as_of=TODAY).rows] == ["Zulu Big", "Alpha Small"]


def test_statement_opening_balance_subtracts_earlier_credit_notes(customer, user):
    from invoicing.models import Invoice

    d = dt.date
    jan = inv_on(customer, d(2026, 1, 10))                         # 1150
    cn = create_credit_note(jan, user, reason="Discount")
    line = cn.lines.first(); line.unit_price = D("100"); line.save(); recalculate(cn)
    Invoice.objects.filter(pk=cn.pk).update(issue_date=d(2026, 1, 15), due_date=d(2026, 1, 15))
    issue(cn, user)                                                # 115 credit in January

    s = statement(customer, d(2026, 2, 1), d(2026, 2, 28))

    assert s.opening_balance == D("1035.00")
