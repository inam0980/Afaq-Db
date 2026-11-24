"""Leave rules (Saudi Labour Law).

Annual leave (Art. 109): 21 days a year, 30 days a year after five years of
service, accrued day by day; counted in working days (Sunday-Thursday).
Sick leave (Art. 117): at most 120 days in any 365-day period; calendar days.
Other types: per-request maximum from LeaveType.max_days.
"""

import datetime as dt
from dataclasses import dataclass
from decimal import Decimal

from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models import Sum
from django.utils import timezone
from django.utils.translation import gettext as _

from core.money import money
from hr.models import Employee
from leave.models import LeaveRequest, LeaveType

WEEKEND = {4, 5}                      # Friday, Saturday
FIRST_TIER_DAYS = 5 * 365
ANNUAL_RATE_FIRST = Decimal(21) / 365
ANNUAL_RATE_LATER = Decimal(30) / 365
SICK_DAYS_PER_YEAR = 120


def count_days(leave_type: LeaveType, start: dt.date, end: dt.date) -> int:
    total = (end - start).days + 1
    if total <= 0:
        return 0
    if leave_type.counts_calendar_days:
        return total
    return sum(1 for i in range(total) if (start + dt.timedelta(days=i)).weekday() not in WEEKEND)


def annual_accrued(employee: Employee, as_of: dt.date) -> Decimal:
    end = min(as_of, employee.termination_date) if employee.termination_date else as_of
    service = max((end - employee.hire_date).days, 0)
    first = min(service, FIRST_TIER_DAYS)
    return money(first * ANNUAL_RATE_FIRST + (service - first) * ANNUAL_RATE_LATER)


@dataclass(frozen=True)
class AnnualBalance:
    accrued: Decimal
    taken: int
    pending: int

    @property
    def available(self) -> Decimal:
        return self.accrued - self.taken - self.pending


def annual_balance(employee: Employee, as_of: dt.date, exclude=None) -> AnnualBalance:
    annual = LeaveRequest.objects.filter(employee=employee, leave_type__uses_annual_balance=True)
    if exclude is not None:
        annual = annual.exclude(pk=exclude.pk)

    def total(status):
        return annual.filter(status=status).aggregate(s=Sum("days"))["s"] or 0

    return AnnualBalance(
        annual_accrued(employee, as_of), total(LeaveRequest.Status.APPROVED), total(LeaveRequest.Status.PENDING)
    )


def _sick_days_in_year(employee, until: dt.date, exclude=None) -> int:
    window_start = until - dt.timedelta(days=364)       # the 365 days ending on `until`
    days = 0
    qs = LeaveRequest.objects.blocking().filter(employee=employee, leave_type__code="SICK")
    if exclude is not None:
        qs = qs.exclude(pk=exclude.pk)
    for r in qs.overlapping(window_start, until):
        start, end = max(r.start_date, window_start), min(r.end_date, until)
        days += (end - start).days + 1
    return days


def _check(employee, leave_type, start, end, days, exclude=None):
    if end < start:
        raise ValidationError({"end_date": _("The leave cannot end before it starts.")})
    if start < employee.hire_date:
        raise ValidationError({"start_date": _("The employee had not joined yet on that date.")})
    if employee.termination_date and end > employee.termination_date:
        raise ValidationError({"end_date": _("The employee's service ends before that date.")})
    if not leave_type.is_active:
        raise ValidationError({"leave_type": _("This leave type is no longer in use.")})
    if days == 0:
        raise ValidationError({"end_date": _("These dates contain no working days.")})
    if leave_type.max_days and days > leave_type.max_days:
        raise ValidationError(
            {"end_date": _("%(type)s allows at most %(max)s days per request.")
             % {"type": leave_type, "max": leave_type.max_days}}
        )

    clash = LeaveRequest.objects.blocking().filter(employee=employee).overlapping(start, end)
    if exclude is not None:
        clash = clash.exclude(pk=exclude.pk)
    if clash.exists():
        raise ValidationError(_("These dates overlap another leave of this employee."))

    if leave_type.uses_annual_balance:
        balance = annual_balance(employee, end, exclude=exclude)
        if days > balance.available:
            raise ValidationError(
                _("Not enough annual leave balance: %(days)s days requested, %(left)s available.")
                % {"days": days, "left": balance.available}
            )
    if leave_type.code == "SICK":
        used = _sick_days_in_year(employee, end, exclude=exclude)
        if used + days > SICK_DAYS_PER_YEAR:
            raise ValidationError(
                _("Sick leave is limited to %(max)s days a year; %(used)s already used.")
                % {"max": SICK_DAYS_PER_YEAR, "used": used}
            )


@transaction.atomic
def request_leave(employee, leave_type, start, end, user, reason="", attachment=None) -> LeaveRequest:
    Employee.objects.select_for_update().get(pk=employee.pk)       # serialise per employee
    days = count_days(leave_type, start, end)
    _check(employee, leave_type, start, end, days)
    req = LeaveRequest(
        employee=employee, leave_type=leave_type, start_date=start, end_date=end, days=days,
        reason=reason, created_by=user,
    )
    if attachment:
        req.attachment = attachment
    req.full_clean(exclude=["created_by"])
    req.save()
    return req


def _lock(req) -> LeaveRequest:
    return LeaveRequest.objects.select_for_update().select_related("employee", "leave_type").get(pk=req.pk)


@transaction.atomic
def approve(req: LeaveRequest, user) -> LeaveRequest:
    req = _lock(req)
    if req.status != LeaveRequest.Status.PENDING:
        raise ValidationError(_("Only pending requests can be approved."))
    if req.leave_type.requires_attachment and not req.attachment:
        raise ValidationError(_("Attach the supporting document (e.g. medical certificate) first."))
    _check(req.employee, req.leave_type, req.start_date, req.end_date, req.days, exclude=req)
    req.status = LeaveRequest.Status.APPROVED
    req.decided_by, req.decided_at = user, timezone.now()
    req.save()
    return req


@transaction.atomic
def reject(req: LeaveRequest, user, note: str) -> LeaveRequest:
    req = _lock(req)
    if req.status != LeaveRequest.Status.PENDING:
        raise ValidationError(_("Only pending requests can be rejected."))
    note = (note or "").strip()
    if not note:
        raise ValidationError(_("Give a reason for rejecting."))
    req.status = LeaveRequest.Status.REJECTED
    req.decided_by, req.decided_at, req.decision_note = user, timezone.now(), note
    req.save()
    return req


@transaction.atomic
def cancel(req: LeaveRequest, user, today: dt.date | None = None) -> LeaveRequest:
    req = _lock(req)
    today = today or timezone.localdate()
    cancellable = req.status == LeaveRequest.Status.PENDING or (
        req.status == LeaveRequest.Status.APPROVED and req.start_date > today
    )
    if not cancellable:
        raise ValidationError(_("Only pending leave, or approved leave that has not started, can be cancelled."))
    req.status = LeaveRequest.Status.CANCELLED
    req.save()
    return req
