import re
from pathlib import Path

from django.contrib import messages
from django.contrib.auth.decorators import login_required, permission_required
from django.core.exceptions import PermissionDenied, ValidationError
from django.http import FileResponse, Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.utils.translation import gettext as _
from django.views.decorators.http import require_POST

from expenses import services
from expenses.forms import ExpenseForm
from expenses.models import Expense, ExpenseCategory

_MONTH_RE = re.compile(r"^(\d{4})-(\d{2})$")


def _parse_month(raw):
    match = _MONTH_RE.match(raw or "")
    if not match:
        return None
    year, month = int(match.group(1)), int(match.group(2))
    return (year, month) if 1 <= month <= 12 else None


@login_required
@permission_required("expenses.view_expense", raise_exception=True)
def expense_list(request):
    qs = Expense.objects.select_related("category", "created_by")

    status = request.GET.get("status", "")
    if status in Expense.Status.values:
        qs = qs.filter(status=status)
    category = request.GET.get("category", "")
    if category.isdigit():
        qs = qs.filter(category_id=int(category))
    month = _parse_month(request.GET.get("month"))
    if month:
        qs = qs.for_month(*month)
    q = request.GET.get("q", "").strip()
    qs = qs.search(q)

    return render(
        request,
        "expenses/expense_list.html",
        {
            "expenses": qs,
            "totals": qs.totals(),
            "by_category": list(qs.by_category()[:6]),
            "categories": ExpenseCategory.objects.all(),
            "statuses": Expense.Status.choices,
            "f": {"status": status, "category": category, "month": request.GET.get("month", ""), "q": q},
        },
    )


@login_required
@permission_required("expenses.add_expense", raise_exception=True)
def expense_create(request):
    form = ExpenseForm(request.POST or None, request.FILES or None)
    if request.method == "POST" and form.is_valid():
        expense = form.save(commit=False)
        expense.created_by = request.user
        expense.save()
        messages.success(request, _("Expense %(no)s saved as draft.") % {"no": expense.number})
        return redirect(expense)
    return render(request, "expenses/expense_form.html", {"form": form, "expense": None})


@login_required
@permission_required("expenses.view_expense", raise_exception=True)
def expense_detail(request, pk):
    expense = get_object_or_404(
        Expense.objects.select_related("category", "created_by", "decided_by"), pk=pk
    )
    return render(request, "expenses/expense_detail.html", {"expense": expense})


@login_required
@permission_required("expenses.change_expense", raise_exception=True)
def expense_update(request, pk):
    expense = get_object_or_404(Expense, pk=pk)
    if not expense.is_editable:
        return render(request, "expenses/not_editable.html", {"expense": expense}, status=409)
    form = ExpenseForm(request.POST or None, request.FILES or None, instance=expense)
    if request.method == "POST" and form.is_valid():
        form.save()
        messages.success(request, _("Expense %(no)s updated.") % {"no": expense.number})
        return redirect(expense)
    return render(request, "expenses/expense_form.html", {"form": form, "expense": expense})


def _action(request, pk, action, success):
    expense = get_object_or_404(Expense, pk=pk)
    try:
        action(expense)
    except ValidationError as exc:
        messages.error(request, " ".join(exc.messages))
    else:
        messages.success(request, success % {"no": expense.number})
    return redirect(expense)


@require_POST
@login_required
@permission_required("expenses.add_expense", raise_exception=True)
def expense_submit(request, pk):
    expense = get_object_or_404(Expense, pk=pk)
    if expense.created_by_id != request.user.pk and not request.user.has_perm("expenses.change_expense"):
        raise PermissionDenied
    return _action(
        request, pk, lambda e: services.submit(e, request.user), _("Expense %(no)s submitted for approval.")
    )


@require_POST
@login_required
@permission_required("expenses.approve_expense", raise_exception=True)
def expense_approve(request, pk):
    return _action(request, pk, lambda e: services.approve(e, request.user), _("Expense %(no)s approved."))


@require_POST
@login_required
@permission_required("expenses.approve_expense", raise_exception=True)
def expense_reject(request, pk):
    reason = request.POST.get("reason", "")
    return _action(
        request, pk, lambda e: services.reject(e, request.user, reason), _("Expense %(no)s rejected.")
    )


@login_required
@permission_required("expenses.view_expense", raise_exception=True)
def expense_receipt(request, pk):
    """Receipts are never exposed under a public /media/ URL."""
    expense = get_object_or_404(Expense, pk=pk)
    if not expense.receipt:
        raise Http404
    try:
        handle = expense.receipt.open("rb")
    except FileNotFoundError as exc:
        raise Http404 from exc
    return FileResponse(handle, filename=Path(expense.receipt.name).name)
