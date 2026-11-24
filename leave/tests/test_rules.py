"""Unit tests: day counting, annual entitlement, balances, request/approval rules."""

import datetime as dt
from decimal import Decimal as D

import pytest
from django.core.exceptions import ValidationError
from django.core.files.uploadedfile import SimpleUploadedFile

from expenses.tests.factories import UserFactory
from hr.models import Employee
from hr.tests.factories import EmployeeFactory
from leave.models import LeaveRequest, LeaveType
from leave.services import (
    annual_accrued,
    annual_balance,
    approve,
    cancel,
    count_days,
    reject,
    request_leave,
)
from leave.tests.factories import leave_type, make_request

pytestmark = pytest.mark.django_db

S = LeaveRequest.Status
SUN = dt.date(2026, 3, 1)        # Sunday


@pytest.fixture
def hr():
    return UserFactory()


@pytest.fixture
def emp():
    return EmployeeFactory(hire_date=dt.date(2015, 1, 1))


def ask(emp, code, start, end, user, **kw):
    return request_leave(emp, leave_type(code), start, end, user, **kw)


# --- leave types -------------------------------------------------------------------

def test_default_leave_types_are_seeded():
    codes = set(LeaveType.objects.values_list("code", flat=True))
    assert {"ANNUAL", "SICK", "UNPAID", "MARRIAGE", "BEREAVEMENT", "PATERNITY", "MATERNITY", "HAJJ"} <= codes
    annual, sick, unpaid = leave_type("ANNUAL"), leave_type("SICK"), leave_type("UNPAID")
    assert annual.uses_annual_balance and not annual.counts_calendar_days
    assert sick.counts_calendar_days and sick.requires_attachment
    assert unpaid.deducts_salary and not unpaid.is_paid
    assert leave_type("MARRIAGE").max_days == 5


# --- counting days -----------------------------------------------------------------

def test_working_days_skip_friday_and_saturday():
    # Sun 1 Mar .. Sat 7 Mar 2026 = 5 working days
    assert count_days(leave_type("ANNUAL"), SUN, SUN + dt.timedelta(days=6)) == 5


def test_calendar_day_types_count_every_day():
    assert count_days(leave_type("SICK"), SUN, SUN + dt.timedelta(days=6)) == 7


def test_single_day():
    assert count_days(leave_type("ANNUAL"), SUN, SUN) == 1


# --- annual entitlement (Art. 109) ------------------------------------------------------

def test_annual_accrual_is_21_days_a_year_in_the_first_five_years():
    e = EmployeeFactory(hire_date=dt.date(2025, 1, 1))
    assert annual_accrued(e, dt.date(2025, 1, 1) + dt.timedelta(days=365)) == D("21.00")
    assert annual_accrued(e, dt.date(2025, 1, 1) + dt.timedelta(days=73)) == D("4.20")   # 73/365 * 21


def test_annual_accrual_is_30_days_a_year_after_five_years():
    e = EmployeeFactory(hire_date=dt.date(2015, 1, 1))
    as_of = dt.date(2015, 1, 1) + dt.timedelta(days=365 * 6)
    assert annual_accrued(e, as_of) == D("135.00")        # 5 x 21 + 1 x 30


def test_no_accrual_before_hire():
    e = EmployeeFactory(hire_date=dt.date(2026, 6, 1))
    assert annual_accrued(e, dt.date(2026, 5, 1)) == D("0.00")


def test_accrual_stops_at_termination():
    e = EmployeeFactory(hire_date=dt.date(2025, 1, 1), termination_date=dt.date(2026, 1, 1),
                        status=Employee.Status.TERMINATED)
    assert annual_accrued(e, dt.date(2027, 1, 1)) == D("21.00")


def test_balance_subtracts_approved_and_reserves_pending(emp, hr):
    as_of = dt.date(2026, 3, 1)
    make_request(emp, "ANNUAL", SUN, SUN + dt.timedelta(days=4), status=S.APPROVED)             # 5 days
    make_request(emp, "ANNUAL", dt.date(2026, 4, 5), dt.date(2026, 4, 6), status=S.PENDING)     # 2 days
    make_request(emp, "ANNUAL", dt.date(2026, 5, 3), dt.date(2026, 5, 3), status=S.REJECTED)
    make_request(emp, "SICK", dt.date(2026, 6, 1), dt.date(2026, 6, 3), status=S.APPROVED)      # other type

    b = annual_balance(emp, as_of)

    assert b.accrued == annual_accrued(emp, as_of)
    assert (b.taken, b.pending) == (5, 2)
    assert b.available == b.accrued - 7


# --- requesting ------------------------------------------------------------------------

def test_request_is_pending_with_counted_days(emp, hr):
    r = ask(emp, "ANNUAL", SUN, SUN + dt.timedelta(days=6), hr, reason="Family visit")
    assert (r.status, r.days, r.created_by, r.reason) == (S.PENDING, 5, hr, "Family visit")


def test_end_before_start_rejected(emp, hr):
    with pytest.raises(ValidationError, match="cannot end before it starts"):
        ask(emp, "ANNUAL", SUN, SUN - dt.timedelta(days=1), hr)


def test_leave_before_hire_rejected(hr):
    e = EmployeeFactory(hire_date=dt.date(2026, 3, 10))
    with pytest.raises(ValidationError):
        ask(e, "SICK", dt.date(2026, 3, 9), dt.date(2026, 3, 10), hr)


def test_leave_after_termination_rejected(hr):
    e = EmployeeFactory(hire_date=dt.date(2020, 1, 1), termination_date=dt.date(2026, 3, 3),
                        status=Employee.Status.TERMINATED)
    with pytest.raises(ValidationError):
        ask(e, "SICK", dt.date(2026, 3, 2), dt.date(2026, 3, 5), hr)


def test_weekend_only_working_day_request_rejected(emp, hr):
    friday = dt.date(2026, 3, 6)
    with pytest.raises(ValidationError):
        ask(emp, "ANNUAL", friday, friday + dt.timedelta(days=1), hr)


def test_max_days_per_type(emp, hr):
    with pytest.raises(ValidationError):
        ask(emp, "PATERNITY", SUN, SUN + dt.timedelta(days=3), hr)        # 4 working days > 3
    ask(emp, "PATERNITY", SUN, SUN + dt.timedelta(days=2), hr)


def test_overlapping_requests_rejected(emp, hr):
    ask(emp, "ANNUAL", SUN, SUN + dt.timedelta(days=4), hr)
    with pytest.raises(ValidationError):
        ask(emp, "SICK", SUN + dt.timedelta(days=4), SUN + dt.timedelta(days=8), hr)


def test_rejected_or_cancelled_requests_do_not_block(emp, hr):
    make_request(emp, "ANNUAL", SUN, SUN + dt.timedelta(days=4), status=S.REJECTED)
    make_request(emp, "ANNUAL", SUN, SUN + dt.timedelta(days=4), status=S.CANCELLED)
    ask(emp, "ANNUAL", SUN, SUN + dt.timedelta(days=4), hr)


def test_annual_request_cannot_exceed_available_balance(hr):
    e = EmployeeFactory(hire_date=dt.date(2026, 1, 1))     # ~4 days accrued by early March
    with pytest.raises(ValidationError) as exc:
        ask(e, "ANNUAL", dt.date(2026, 3, 8), dt.date(2026, 3, 19), hr)     # 10 working days
    assert "balance" in str(exc.value).lower()


def test_inactive_leave_type_cannot_be_requested(emp, hr):
    LeaveType.objects.filter(code="HAJJ").update(is_active=False)
    with pytest.raises(ValidationError):
        ask(emp, "HAJJ", SUN, SUN, hr)


def test_sick_leave_limited_to_120_days_a_year(emp, hr):
    make_request(emp, "SICK", dt.date(2025, 6, 1), dt.date(2025, 9, 28), status=S.APPROVED)   # 120 days
    with pytest.raises(ValidationError):
        ask(emp, "SICK", dt.date(2026, 3, 1), dt.date(2026, 3, 1), hr)                        # within 365 days
    ask(emp, "SICK", dt.date(2026, 10, 1), dt.date(2026, 10, 1), hr)                          # a year later: fine


# --- approval workflow -------------------------------------------------------------------

def test_approve(emp, hr):
    r = ask(emp, "ANNUAL", SUN, SUN + dt.timedelta(days=4), hr)
    boss = UserFactory()
    approve(r, boss)
    r.refresh_from_db()
    assert (r.status, r.decided_by) == (S.APPROVED, boss) and r.decided_at


def test_sick_leave_needs_a_certificate_before_approval(emp, hr):
    r = ask(emp, "SICK", SUN, SUN + dt.timedelta(days=1), hr)
    with pytest.raises(ValidationError):
        approve(r, UserFactory())
    r.attachment = SimpleUploadedFile("cert.pdf", b"%PDF")
    r.save()
    approve(r, UserFactory())


def test_only_pending_can_be_decided(emp, hr):
    r = make_request(emp, "ANNUAL", status=S.APPROVED)
    with pytest.raises(ValidationError):
        approve(r, UserFactory())
    with pytest.raises(ValidationError):
        reject(r, UserFactory(), note="x")


def test_approval_rechecks_the_balance(hr):
    e = EmployeeFactory(hire_date=dt.date(2025, 1, 1))
    r = ask(e, "ANNUAL", dt.date(2026, 3, 1), dt.date(2026, 3, 5), hr)       # fits now
    make_request(e, "ANNUAL", dt.date(2026, 4, 1), dt.date(2026, 6, 30), status=S.APPROVED)   # uses it all
    with pytest.raises(ValidationError):
        approve(r, UserFactory())


def test_reject_needs_a_note(emp, hr):
    r = ask(emp, "ANNUAL", SUN, SUN, hr)
    with pytest.raises(ValidationError):
        reject(r, UserFactory(), note=" ")
    reject(r, UserFactory(), note="Peak season")
    r.refresh_from_db()
    assert (r.status, r.decision_note) == (S.REJECTED, "Peak season")


def test_cancel_pending_and_future_approved(emp, hr):
    r = ask(emp, "ANNUAL", SUN, SUN, hr)
    cancel(r, hr, today=dt.date(2026, 2, 1))
    r.refresh_from_db()
    assert r.status == S.CANCELLED

    future = make_request(emp, "ANNUAL", dt.date(2026, 5, 3), dt.date(2026, 5, 4), status=S.APPROVED)
    cancel(future, hr, today=dt.date(2026, 4, 1))
    future.refresh_from_db()
    assert future.status == S.CANCELLED


def test_leave_already_started_cannot_be_cancelled(emp, hr):
    r = make_request(emp, "ANNUAL", SUN, SUN + dt.timedelta(days=4), status=S.APPROVED)
    with pytest.raises(ValidationError):
        cancel(r, hr, today=SUN)


def test_str_and_history(emp, hr):
    r = ask(emp, "ANNUAL", SUN, SUN, hr)
    approve(r, UserFactory())
    assert str(r) == f"{emp.full_name}: Annual leave 2026-03-01 → 2026-03-01"
    assert r.history.count() == 2


def test_on_leave_queryset(emp):
    make_request(emp, "ANNUAL", SUN, SUN + dt.timedelta(days=4), status=S.APPROVED)
    make_request(EmployeeFactory(), "ANNUAL", SUN, SUN + dt.timedelta(days=4), status=S.PENDING)  # same days
    assert list(LeaveRequest.objects.on_leave(SUN + dt.timedelta(days=2))) == [
        LeaveRequest.objects.get(employee=emp)
    ]
