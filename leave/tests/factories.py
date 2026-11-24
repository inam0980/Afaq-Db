import datetime as dt

from expenses.tests.factories import UserFactory
from hr.tests.factories import EmployeeFactory
from leave.models import LeaveRequest, LeaveType


def leave_type(code: str) -> LeaveType:
    return LeaveType.objects.get(code=code)


def make_request(employee=None, code="ANNUAL", start=dt.date(2026, 3, 1), end=dt.date(2026, 3, 5),
                 status=LeaveRequest.Status.PENDING, **kwargs) -> LeaveRequest:
    """Create a request directly (bypassing validation) for test setup."""
    from leave.services import count_days

    lt = leave_type(code)
    return LeaveRequest.objects.create(
        employee=employee or EmployeeFactory(hire_date=dt.date(2015, 1, 1)),
        leave_type=lt, start_date=start, end_date=end, days=count_days(lt, start, end),
        status=status, created_by=kwargs.pop("created_by", None) or UserFactory(), **kwargs,
    )
