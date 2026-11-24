from django.conf import settings
from django.contrib import messages
from django.contrib.auth.decorators import login_required, permission_required
from django.core.exceptions import ValidationError
from django.shortcuts import get_object_or_404, redirect, render
from django.utils.translation import gettext as _
from django.views.decorators.http import require_POST

from hr.models import Employee
from loans import services
from loans.forms import LoanForm
from loans.models import Loan


@login_required
@permission_required("loans.view_loan", raise_exception=True)
def loan_list(request):
    qs = Loan.objects.select_related("employee")
    f = {k: request.GET.get(k, "") for k in ("status", "employee")}
    if f["status"] in Loan.Status.values:
        qs = qs.filter(status=f["status"])
    if f["employee"].isdigit():
        qs = qs.filter(employee_id=int(f["employee"]))
    return render(request, "loans/loan_list.html", {
        "loans": qs, "f": f, "statuses": Loan.Status.choices,
        "employees": Employee.objects.filter(loans__isnull=False).distinct().order_by("first_name"),
        "nav_section": "loans",
    })


@login_required
@permission_required("loans.add_loan", raise_exception=True)
def loan_create(request):
    form = LoanForm(request.POST or None, initial={"employee": request.GET.get("employee")})
    if request.method == "POST" and form.is_valid():
        d = form.cleaned_data
        try:
            loan = services.request_loan(d["employee"], d["kind"], d["amount"], d["installment"],
                                         d["first_month"], request.user, reason=d["reason"])
        except ValidationError as exc:
            form.add_error(None, exc)
        else:
            messages.success(request, _("Request saved and waiting for approval."))
            return redirect(loan)
    return render(request, "loans/loan_form.html", {
        "form": form, "limit": settings.LOAN_MAX_DEDUCTION_PERCENT, "nav_section": "loans"})


@login_required
@permission_required("loans.view_loan", raise_exception=True)
def loan_detail(request, pk):
    loan = get_object_or_404(Loan.objects.select_related("employee", "requested_by", "decided_by"), pk=pk)
    return render(request, "loans/loan_detail.html", {
        "loan": loan,
        "repayments": loan.repayments.select_related("payslip__run"),
        "can_decide": request.user.has_perm("loans.approve_loan") and loan.status == Loan.Status.PENDING,
        "nav_section": "loans",
    })


def _decide(request, pk, action):
    loan = get_object_or_404(Loan, pk=pk)
    try:
        action(loan, request.user, request.POST.get("note", ""))
    except ValidationError as exc:
        messages.error(request, " ".join(exc.messages))
    else:
        messages.success(request, _("Decision saved."))
    return redirect(loan)


@login_required
@require_POST
@permission_required("loans.approve_loan", raise_exception=True)
def loan_approve(request, pk):
    return _decide(request, pk, services.approve)


@login_required
@require_POST
@permission_required("loans.approve_loan", raise_exception=True)
def loan_reject(request, pk):
    return _decide(request, pk, services.reject)
