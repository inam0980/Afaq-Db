from pathlib import Path

from django.contrib import messages
from django.contrib.auth.decorators import login_required, permission_required
from django.core.exceptions import ValidationError
from django.http import FileResponse, Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.utils.translation import gettext as _
from django.views.decorators.http import require_POST

from hr.models import Employee
from leave import services
from leave.forms import LeaveRequestForm
from leave.models import LeaveRequest, LeaveType


@login_required
@permission_required("leave.view_leaverequest", raise_exception=True)
def leave_list(request):
    qs = LeaveRequest.objects.select_related("employee", "leave_type")
    f = {k: request.GET.get(k, "") for k in ("status", "type", "employee")}
    if f["status"] in LeaveRequest.Status.values:
        qs = qs.filter(status=f["status"])
    if f["type"]:
        qs = qs.filter(leave_type__code=f["type"])
    if f["employee"].isdigit():
        qs = qs.filter(employee_id=int(f["employee"]))
    return render(
        request,
        "leave/leave_list.html",
        {
            "requests": qs,
            "f": f,
            "statuses": LeaveRequest.Status.choices,
            "types": LeaveType.objects.all(),
            "employees": Employee.objects.active().order_by("first_name"),
        },
    )


@login_required
@permission_required("leave.add_leaverequest", raise_exception=True)
def leave_create(request):
    form = LeaveRequestForm(request.POST or None, request.FILES or None,
                            initial={"employee": request.GET.get("employee")})
    if request.method == "POST" and form.is_valid():
        data = form.cleaned_data
        try:
            req = services.request_leave(
                data["employee"], data["leave_type"], data["start_date"], data["end_date"],
                request.user, reason=data["reason"], attachment=data.get("attachment"),
            )
        except ValidationError as exc:
            form.add_error(None, exc)
        else:
            messages.success(request, _("Leave request saved and waiting for approval."))
            return redirect(req)
    return render(request, "leave/leave_form.html", {"form": form})


@login_required
@permission_required("leave.view_leaverequest", raise_exception=True)
def leave_detail(request, pk):
    req = get_object_or_404(
        LeaveRequest.objects.select_related("employee", "leave_type", "created_by", "decided_by"), pk=pk
    )
    balance = None
    if req.leave_type.uses_annual_balance:
        balance = services.annual_balance(req.employee, req.end_date)
    return render(request, "leave/leave_detail.html", {"req": req, "balance": balance})


def _decide(request, pk, action, success):
    req = get_object_or_404(LeaveRequest, pk=pk)
    try:
        action(req)
    except ValidationError as exc:
        messages.error(request, " ".join(exc.messages))
    else:
        messages.success(request, success)
    return redirect(req)


@require_POST
@login_required
@permission_required("leave.approve_leaverequest", raise_exception=True)
def leave_approve(request, pk):
    return _decide(request, pk, lambda r: services.approve(r, request.user), _("Leave approved."))


@require_POST
@login_required
@permission_required("leave.approve_leaverequest", raise_exception=True)
def leave_reject(request, pk):
    note = request.POST.get("note", "")
    return _decide(request, pk, lambda r: services.reject(r, request.user, note), _("Leave rejected."))


@require_POST
@login_required
@permission_required("leave.change_leaverequest", raise_exception=True)
def leave_cancel(request, pk):
    return _decide(request, pk, lambda r: services.cancel(r, request.user), _("Leave cancelled."))


@login_required
@permission_required("leave.view_leaverequest", raise_exception=True)
def leave_attachment(request, pk):
    req = get_object_or_404(LeaveRequest, pk=pk)
    if not req.attachment:
        raise Http404
    try:
        handle = req.attachment.open("rb")
    except FileNotFoundError as exc:
        raise Http404 from exc
    return FileResponse(handle, filename=Path(req.attachment.name).name)
