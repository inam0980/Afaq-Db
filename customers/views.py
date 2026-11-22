from django.contrib import messages
from django.contrib.auth.decorators import login_required, permission_required
from django.shortcuts import get_object_or_404, redirect, render
from django.utils.translation import gettext as _

from customers.forms import CustomerForm
from customers.models import Customer
from invoicing.balances import customer_balance


@login_required
@permission_required("customers.view_customer", raise_exception=True)
def customer_list(request):
    q = request.GET.get("q", "").strip()
    show_all = request.GET.get("all") == "1"
    qs = Customer.objects.all() if show_all else Customer.objects.active()
    return render(
        request,
        "customers/customer_list.html",
        {"customers": qs.search(q), "q": q, "show_all": show_all},
    )


@login_required
@permission_required("customers.view_customer", raise_exception=True)
def customer_detail(request, pk):
    customer = get_object_or_404(Customer, pk=pk)
    jobs = customer.jobs.order_by("-created_at")[:50] if request.user.has_perm("jobs.view_job") else []
    balance = customer_balance(customer) if request.user.has_perm("invoicing.view_invoice") else None
    return render(
        request, "customers/customer_detail.html", {"customer": customer, "jobs": jobs, "balance": balance}
    )


def _save(request, form, message):
    if request.method == "POST" and form.is_valid():
        customer = form.save()
        messages.success(request, message % {"name": customer.name})
        return redirect(customer)
    return None


@login_required
@permission_required("customers.add_customer", raise_exception=True)
def customer_create(request):
    form = CustomerForm(request.POST or None)
    return _save(request, form, _("Customer %(name)s added.")) or render(
        request, "customers/customer_form.html", {"form": form, "customer": None}
    )


@login_required
@permission_required("customers.change_customer", raise_exception=True)
def customer_update(request, pk):
    customer = get_object_or_404(Customer, pk=pk)
    form = CustomerForm(request.POST or None, instance=customer)
    return _save(request, form, _("Customer %(name)s updated.")) or render(
        request, "customers/customer_form.html", {"form": form, "customer": customer}
    )
