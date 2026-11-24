from django.contrib import messages
from django.contrib.auth.decorators import login_required, permission_required
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.utils.translation import gettext as _

from hr.forms import EmployeeForm
from hr.models import Employee
from leave.services import annual_balance

DEFAULT_EXPIRY_WINDOW = 30
MAX_EXPIRY_WINDOW = 365


def _is_htmx(request) -> bool:
    return request.headers.get("HX-Request") == "true"


@login_required
@permission_required("hr.view_employee", raise_exception=True)
def employee_list(request):
    query = request.GET.get("q", "").strip()
    employees = Employee.objects.select_related("department").search(query)
    context = {"employees": employees, "q": query}
    if _is_htmx(request):
        return render(request, "hr/partials/employee_table.html", context)
    return render(request, "hr/employee_list.html", context)


@login_required
@permission_required("hr.view_employee", raise_exception=True)
def employee_detail(request, pk):
    employee = get_object_or_404(Employee.objects.select_related("department"), pk=pk)
    history = employee.history.select_related("history_user").all()[:20]
    leave_balance, leaves = None, []
    if request.user.has_perm("leave.view_leaverequest"):
        leave_balance = annual_balance(employee, timezone.localdate())
        leaves = employee.leave_requests.select_related("leave_type")[:10]
    return render(
        request,
        "hr/employee_detail.html",
        {"employee": employee, "history": list(history), "leave_balance": leave_balance, "leaves": leaves},
    )


@login_required
@permission_required("hr.add_employee", raise_exception=True)
def employee_create(request):
    form = EmployeeForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        employee = form.save()
        messages.success(request, _("Employee %(no)s created.") % {"no": employee.employee_no})
        return redirect(employee)
    return render(request, "hr/employee_form.html", {"form": form, "employee": None})


@login_required
@permission_required("hr.change_employee", raise_exception=True)
def employee_update(request, pk):
    employee = get_object_or_404(Employee, pk=pk)
    form = EmployeeForm(request.POST or None, instance=employee)
    if request.method == "POST" and form.is_valid():
        form.save()
        messages.success(request, _("Employee %(no)s updated.") % {"no": employee.employee_no})
        return redirect(employee)
    return render(request, "hr/employee_form.html", {"form": form, "employee": employee})


def _parse_days(raw) -> int:
    try:
        days = int(raw)
    except (TypeError, ValueError):
        return DEFAULT_EXPIRY_WINDOW
    if not 1 <= days <= MAX_EXPIRY_WINDOW:
        return DEFAULT_EXPIRY_WINDOW
    return days


@login_required
@permission_required("hr.view_employee", raise_exception=True)
def expiring_documents(request):
    days = _parse_days(request.GET.get("days"))
    employees = Employee.objects.select_related("department").with_expiring_documents(
        within_days=days
    )
    day_options = sorted({30, 60, 90, 180, MAX_EXPIRY_WINDOW, days})
    return render(
        request,
        "hr/expiring_documents.html",
        {"employees": employees, "days": days, "day_options": day_options},
    )
