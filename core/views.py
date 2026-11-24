from decimal import Decimal

from django.contrib.auth.decorators import login_required
from django.db.models import Sum
from django.http import JsonResponse
from django.shortcuts import render
from django.utils import timezone
from django.views.decorators.http import require_GET

from core.health import check_database
from expenses.models import Expense
from invoicing.balances import aging
from invoicing.models import Payment
from invoicing.vat_return import parse_period, vat_return
from hr.models import Employee
from jobs.costing import profitability
from jobs.models import Job
from leave.models import LeaveRequest
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

    context["show_expenses"] = user.has_perm("expenses.view_expense")
    if context["show_expenses"]:
        context.update(
            month_expenses=Expense.objects.approved().for_month(today.year, today.month).totals()["total"],
            pending_expenses=Expense.objects.filter(status=Expense.Status.SUBMITTED).count(),
            current_period=today,
        )

    context["show_jobs"] = user.has_perm("jobs.view_job")
    if context["show_jobs"]:
        open_jobs = Job.objects.open()
        context.update(
            open_jobs=open_jobs.count(),
            urgent_jobs=open_jobs.filter(priority=Job.Priority.URGENT).count(),
            completed_this_month=Job.objects.filter(
                status=Job.Status.COMPLETED,
                completed_at__year=today.year,
                completed_at__month=today.month,
            ).count(),
        )

    context["show_leave"] = user.has_perm("leave.view_leaverequest")
    if context["show_leave"]:
        context.update(
            on_leave_today=LeaveRequest.objects.on_leave(today).count(),
            pending_leave=LeaveRequest.objects.filter(status=LeaveRequest.Status.PENDING).count(),
        )

    context["show_receivables"] = user.has_perm("invoicing.view_invoice")
    if context["show_receivables"]:
        receivable = aging(today)
        context.update(
            receivable_total=receivable.totals["total"],
            receivable_overdue=receivable.totals["overdue"],
            collected_this_month=Payment.objects.filter(
                date__year=today.year, date__month=today.month
            ).aggregate(s=Sum("amount"))["s"] or Decimal("0"),
        )

    context["show_vat"] = user.has_perm("invoicing.view_vat_return")
    if context["show_vat"]:
        start, end, label = parse_period(None, today)
        context.update(vat_due_this_quarter=vat_return(start, end).net_vat, vat_quarter=label)

    context["show_job_profit"] = user.has_perm("jobs.view_job_costing")
    if context["show_job_profit"]:
        report = profitability(today.year, today.month)
        context.update(month_job_profit=report.profit, month_jobs_done=len(report.rows))

    return render(request, "core/dashboard.html", context)
