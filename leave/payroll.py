"""How approved leave reduces salary in a payroll month.

* Leave types with `deducts_salary` (unpaid leave): every calendar day inside
  the month is a full day's deduction.
* Sick leave (Labour Law Art. 117), counted over the 365 days ending on each
  sick day: days 1-30 full pay, days 31-90 three quarters pay (a quarter of
  the day deducted), from day 91 unpaid (the whole day deducted).
Paid leave types never reduce salary.
"""

import datetime as dt
from decimal import Decimal

from core.money import money
from leave.models import LeaveRequest

SICK_FULL_PAY_DAYS = 30
SICK_REDUCED_PAY_UNTIL = 90
SICK_REDUCED_DEDUCTION = Decimal("0.25")
YEAR = dt.timedelta(days=364)          # window of 365 days including the day itself


def _days_within(r, start: dt.date, end: dt.date):
    first, last = max(r.start_date, start), min(r.end_date, end)
    return [first + dt.timedelta(days=i) for i in range((last - first).days + 1)]


def leave_deduction_days(employee, start: dt.date, end: dt.date) -> Decimal:
    """Salary days to deduct for approved leave between start and end (inclusive)."""
    approved = LeaveRequest.objects.filter(employee=employee, status=LeaveRequest.Status.APPROVED)
    total = Decimal(0)

    for r in approved.filter(leave_type__deducts_salary=True).overlapping(start, end):
        total += len(_days_within(r, start, end))

    sick_days = set()
    for r in approved.filter(leave_type__code="SICK").overlapping(start - YEAR, end):
        sick_days.update(_days_within(r, start - YEAR, end))
    for day in sorted(d for d in sick_days if start <= d <= end):
        rank = sum(1 for d in sick_days if day - YEAR <= d <= day)
        if rank > SICK_REDUCED_PAY_UNTIL:
            total += 1
        elif rank > SICK_FULL_PAY_DAYS:
            total += SICK_REDUCED_DEDUCTION

    return money(total)
