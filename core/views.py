from django.contrib.auth.decorators import login_required
from django.http import JsonResponse
from django.shortcuts import render
from django.utils import timezone
from django.views.decorators.http import require_GET

from core.health import check_database
from hr.models import Employee
from payroll.models import PayrollRun

EXPIRY_WINDOW_DAYS = 30
EXPIRING_PREVIEW = 5


@require_GET
def health(request):
    if check_database():
        return JsonResponse({"status": "ok", "database": "ok"})
    return JsonResponse({"status": "error", "database": "error"}, status=503)


@login_required
def dashboard(request):
    user = request.user
    today = timezone.localdate()
    context = {
        "today": today,
        "show_employees": user.has_perm("hr.view_employee"),
        "show_payroll": user.has_perm("payroll.view_payrollrun"),
        "expiry_window": EXPIRY_WINDOW_DAYS,
    }

    if context["show_employees"]:
        expiring = Employee.objects.with_expiring_documents(within_days=EXPIRY_WINDOW_DAYS)
        context.update(
            active_employees=Employee.objects.active().count(),
            expiring_count=expiring.count(),
            expiring=list(expiring[:EXPIRING_PREVIEW]),
        )

    if context["show_payroll"]:
        run = PayrollRun.objects.filter(year=today.year, month=today.month).first()
        context.update(
            current_run=run,
            current_totals=run.totals() if run else None,
            current_period=today,
        )

    return render(request, "core/dashboard.html", context)
