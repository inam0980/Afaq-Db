import datetime as dt

from django.conf import settings
from django.contrib import messages
from django.contrib.auth.decorators import login_required, permission_required
from django.core.exceptions import ValidationError
from django.db import transaction
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.utils.translation import gettext as _
from django.views.decorators.http import require_POST

from invoicing import services
from invoicing.forms import InvoiceForm, LineFormSet
from invoicing.models import Invoice
from invoicing.zatca import qr_svg
from jobs.models import Job


@login_required
@permission_required("invoicing.view_invoice", raise_exception=True)
def invoice_list(request):
    qs = Invoice.objects.select_related("customer", "job")
    status = request.GET.get("status", "")
    if status in Invoice.Status.values:
        qs = qs.filter(status=status)
    q = request.GET.get("q", "").strip()
    qs = qs.search(q)
    return render(
        request,
        "invoicing/invoice_list.html",
        {"invoices": qs, "f": {"status": status, "q": q}, "statuses": Invoice.Status.choices},
    )


def _edit(request, invoice, template_ctx):
    """Shared create/update handling for the invoice header + line formset."""
    form = InvoiceForm(request.POST or None, instance=invoice, initial=template_ctx.pop("initial", None))
    lines = LineFormSet(request.POST or None, instance=invoice, prefix="lines")
    if request.method == "POST" and form.is_valid() and lines.is_valid():
        with transaction.atomic():
            invoice = form.save(commit=False)
            if not invoice.pk:
                invoice.created_by = request.user
            invoice.save()
            lines.instance = invoice
            lines.save()
            services.recalculate(invoice)
        messages.success(request, _("Draft invoice saved."))
        return redirect(invoice)
    return render(request, "invoicing/invoice_form.html", {"form": form, "lines": lines, **template_ctx})


@login_required
@permission_required("invoicing.add_invoice", raise_exception=True)
def invoice_create(request):
    today = timezone.localdate()
    initial = {
        "customer": request.GET.get("customer"),
        "issue_date": today,
        "due_date": today + dt.timedelta(days=services.payment_terms_days()),
    }
    return _edit(request, Invoice(), {"invoice": None, "initial": initial})


@login_required
@permission_required("invoicing.change_invoice", raise_exception=True)
def invoice_update(request, pk):
    invoice = get_object_or_404(Invoice, pk=pk)
    if not invoice.is_draft:
        return render(request, "invoicing/not_editable.html", {"invoice": invoice}, status=409)
    return _edit(request, invoice, {"invoice": invoice})


@login_required
@permission_required("invoicing.view_invoice", raise_exception=True)
def invoice_detail(request, pk):
    invoice = get_object_or_404(
        Invoice.objects.select_related("customer", "job", "created_by", "issued_by"), pk=pk
    )
    payload = services.qr_for(invoice)
    return render(
        request,
        "invoicing/invoice_detail.html",
        {
            "invoice": invoice,
            "lines": invoice.lines.all(),
            "qr": qr_svg(payload) if payload else None,
            "company": {
                "name": settings.COMPANY_NAME,
                "name_ar": settings.COMPANY_NAME_AR,
                "vat": settings.COMPANY_VAT_NUMBER,
                "cr": settings.COMPANY_CR_NUMBER,
                "address": settings.COMPANY_ADDRESS,
            },
        },
    )


@require_POST
@login_required
@permission_required("invoicing.issue_invoice", raise_exception=True)
def invoice_issue(request, pk):
    invoice = get_object_or_404(Invoice, pk=pk)
    try:
        invoice = services.issue(invoice, request.user)
    except ValidationError as exc:
        messages.error(request, " ".join(exc.messages))
    else:
        messages.success(request, _("Invoice %(no)s issued.") % {"no": invoice.number})
    return redirect(invoice)


@require_POST
@login_required
@permission_required("invoicing.add_invoice", raise_exception=True)
def invoice_from_job(request, job_pk):
    job = get_object_or_404(Job, pk=job_pk)
    try:
        invoice = services.create_from_job(job, request.user)
    except ValidationError as exc:
        messages.error(request, " ".join(exc.messages))
        return redirect(job)
    messages.success(request, _("Draft invoice created from %(job)s. Review it, then issue.") % {"job": job.number})
    return redirect("invoicing:update", pk=invoice.pk)
