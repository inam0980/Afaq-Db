from django.conf import settings
from django.contrib import messages
from django.contrib.auth.decorators import login_required, permission_required
from django.core.exceptions import PermissionDenied, ValidationError
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.utils.translation import gettext as _
from django.views.decorators.http import require_POST

from hr.models import Employee
from payroll import services
from payroll.calculations import EosbReason, calculate_eosb
from payroll.forms import PayrollRunForm, PayslipInputForm
from payroll.models import PayrollLocked, PayrollRun, Payslip, SalaryStructure


@login_required
@permission_required("payroll.view_salarystructure", raise_exception=True)
def employee_salary(request, pk):
    employee = get_object_or_404(Employee, pk=pk)
    structures = list(employee.salary_structures.order_by("-effective_from"))

    eosb_end_date = employee.termination_date or timezone.localdate()
    current = SalaryStructure.objects.current_for(employee, eosb_end_date)

    reason = request.GET.get("reason")
    if reason not in EosbReason.values:
        reason = EosbReason.TERMINATION

    eosb = None
    if current is not None:
        eosb = calculate_eosb(current.gross_fixed, employee.hire_date, eosb_end_date, reason)

    return render(
        request,
        "payroll/employee_salary.html",
        {
            "employee": employee,
            "structures": structures,
            "current": current,
            "reason": reason,
            "reasons": EosbReason.choices,
            "eosb": eosb,
            "eosb_end_date": eosb_end_date,
        },
    )


# --- Payroll runs ---------------------------------------------------------------

@login_required
@permission_required("payroll.view_payrollrun", raise_exception=True)
def run_list(request):
    form = PayrollRunForm(request.POST or None)
    if request.method == "POST":
        if not request.user.has_perm("payroll.add_payrollrun"):
            raise PermissionDenied
        if form.is_valid():
            run = form.save(commit=False)
            run.created_by = request.user
            run.save()
            result = services.generate_payslips(run)
            messages.success(
                request, _("Payroll %(run)s created with %(n)d payslips.") % {"run": run, "n": result.created}
            )
            return redirect("payroll:run_detail", pk=run.pk)
    return render(request, "payroll/run_list.html", {"runs": PayrollRun.objects.all(), "form": form})


@login_required
@permission_required("payroll.view_payrollrun", raise_exception=True)
def run_detail(request, pk):
    run = get_object_or_404(PayrollRun, pk=pk)
    payslips = run.payslips.select_related("employee", "run")
    return render(
        request,
        "payroll/run_detail.html",
        {
            "run": run,
            "payslips": payslips,
            "totals": run.totals(),
            "missing": services.missing_structures(run) if not run.is_locked else [],
        },
    )


def _run_action(request, pk, action, success_message):
    run = get_object_or_404(PayrollRun, pk=pk)
    try:
        action(run)
    except (ValidationError, PayrollLocked) as exc:
        messages.error(request, " ".join(getattr(exc, "messages", [str(exc)])))
    else:
        messages.success(request, success_message % {"run": run})
    return redirect("payroll:run_detail", pk=run.pk)


@require_POST
@login_required
@permission_required("payroll.approve_payrollrun", raise_exception=True)
def run_approve(request, pk):
    return _run_action(
        request, pk, lambda run: services.approve_run(run, request.user),
        _("Payroll %(run)s approved and locked."),
    )


@require_POST
@login_required
@permission_required("payroll.approve_payrollrun", raise_exception=True)
def run_mark_paid(request, pk):
    return _run_action(
        request, pk, lambda run: services.mark_paid(run, request.user),
        _("Payroll %(run)s marked as paid."),
    )


@require_POST
@login_required
@permission_required("payroll.change_payrollrun", raise_exception=True)
def run_regenerate(request, pk):
    return _run_action(request, pk, services.regenerate, _("Payroll %(run)s recalculated."))


# --- Payslips -------------------------------------------------------------------

@login_required
@permission_required("payroll.change_payslip", raise_exception=True)
def payslip_edit(request, pk):
    slip = get_object_or_404(Payslip.objects.select_related("employee", "run"), pk=pk)
    if slip.run.is_locked:
        return render(request, "payroll/partials/payslip_row.html", {"slip": slip}, status=409)

    if request.GET.get("cancel"):
        return render(request, "payroll/partials/payslip_row.html", {"slip": slip})

    form = PayslipInputForm(request.POST or None, instance=slip)
    if request.method == "POST" and form.is_valid():
        try:
            services.update_payslip_inputs(
                slip, **{name: form.cleaned_data[name] for name in services.INPUT_FIELDS}
            )
        except ValidationError as exc:
            form.add_error(None, exc)
        else:
            return render(request, "payroll/partials/payslip_row.html", {"slip": slip})
    if form.errors:
        slip.refresh_from_db()
    return render(request, "payroll/partials/payslip_form_row.html", {"slip": slip, "form": form})


@login_required
@permission_required("payroll.view_payslip", raise_exception=True)
def payslip_detail(request, pk):
    slip = get_object_or_404(Payslip.objects.select_related("employee__department", "run"), pk=pk)
    return render(
        request,
        "payroll/payslip_detail.html",
        {"slip": slip, "company_name": settings.COMPANY_NAME},
    )
