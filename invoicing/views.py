import csv
import datetime as dt

from django.conf import settings
from django.contrib import messages
from django.contrib.auth.decorators import login_required, permission_required
from django.core.exceptions import ValidationError
from django.db import transaction
from django.http import HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.utils.translation import gettext as _
from django.views.decorators.http import require_POST

from customers.models import Customer
from invoicing import services
from invoicing.balances import aging, statement, with_balances
from invoicing.forms import CreditNoteForm, InvoiceForm, LineFormSet, PaymentForm
from invoicing.models import Invoice, Payment
from invoicing.vat_return import csv_rows, parse_period, vat_return
from invoicing.zatca import qr_svg
from jobs.models import Job

PAYMENT_FILTERS = ("unpaid", "paid", "overdue")


@login_required
@permission_required("invoicing.view_invoice", raise_exception=True)
def invoice_list(request):
    qs = with_balances(Invoice.objects.select_related("customer", "job"))
    status = request.GET.get("status", "")
    if status in Invoice.Status.values:
        qs = qs.filter(status=status)
    payment = request.GET.get("payment", "")
    if payment in PAYMENT_FILTERS:
        qs = qs.filter(status=Invoice.Status.ISSUED, kind=Invoice.Kind.INVOICE)
        if payment == "paid":
            qs = qs.filter(balance__lte=0)
        else:
            qs = qs.filter(balance__gt=0)
        if payment == "overdue":
            qs = qs.filter(due_date__lt=timezone.localdate())
    q = request.GET.get("q", "").strip()
    qs = qs.search(q)
    return render(
        request,
        "invoicing/invoice_list.html",
        {
            "invoices": qs,
            "f": {"status": status, "q": q, "payment": payment},
            "today": timezone.localdate(),
            "statuses": Invoice.Status.choices,
        },
    )


def _edit(request, invoice, template_ctx):
    """Shared create/update handling for the invoice header + line formset."""
    form_class = CreditNoteForm if invoice.is_credit_note else InvoiceForm
    form = form_class(request.POST or None, instance=invoice, initial=template_ctx.pop("initial", None))
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
        messages.success(request, _("Draft saved."))
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
        with_balances(Invoice.objects.select_related("customer", "job", "original", "created_by", "issued_by")),
        pk=pk,
    )
    zatca_doc = getattr(invoice, "zatca_document", None)
    payload = zatca_doc.qr if zatca_doc else services.qr_for(invoice)
    return render(
        request,
        "invoicing/invoice_detail.html",
        {
            "invoice": invoice,
            "lines": invoice.lines.all(),
            "payments": invoice.payments.select_related("received_by"),
            "credit_notes": invoice.credit_notes.all(),
            "payment_form": PaymentForm(initial={"date": timezone.localdate(), "amount": invoice.balance}),
            "qr": qr_svg(payload) if payload else None,
            "qr_payload": payload,
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


def _flash_errors(request, exc_or_form):
    if hasattr(exc_or_form, "errors") and not isinstance(exc_or_form, ValidationError):
        text = " ".join(f"{name}: {' '.join(errs)}" for name, errs in exc_or_form.errors.items())
    else:
        text = " ".join(exc_or_form.messages)
    messages.error(request, text)


@require_POST
@login_required
@permission_required("invoicing.add_payment", raise_exception=True)
def add_payment(request, pk):
    invoice = get_object_or_404(Invoice, pk=pk)
    form = PaymentForm(request.POST)
    if not form.is_valid():
        _flash_errors(request, form)
        return redirect(invoice)
    try:
        services.record_payment(invoice, request.user, **form.cleaned_data)
    except ValidationError as exc:
        _flash_errors(request, exc)
    else:
        messages.success(request, _("Payment of %(amt)s recorded.") % {"amt": form.cleaned_data["amount"]})
    return redirect(invoice)


@require_POST
@login_required
@permission_required("invoicing.delete_payment", raise_exception=True)
def delete_payment(request, pk):
    payment = get_object_or_404(Payment.objects.select_related("invoice"), pk=pk)
    invoice = payment.invoice
    services.delete_payment(payment)
    messages.success(request, _("Payment removed."))
    return redirect(invoice)


@require_POST
@login_required
@permission_required("invoicing.add_invoice", raise_exception=True)
def credit_note(request, pk):
    original = get_object_or_404(Invoice, pk=pk)
    try:
        note = services.create_credit_note(original, request.user, reason=request.POST.get("reason", ""))
    except ValidationError as exc:
        _flash_errors(request, exc)
        return redirect(original)
    messages.success(request, _("Draft credit note created. Reduce the lines to the amount to credit, then issue."))
    return redirect("invoicing:update", pk=note.pk)


def _parse_date(raw, default):
    try:
        return dt.date.fromisoformat(raw)
    except (TypeError, ValueError):
        return default


@login_required
@permission_required("invoicing.view_invoice", raise_exception=True)
def customer_statement(request, customer_pk):
    customer = get_object_or_404(Customer, pk=customer_pk)
    today = timezone.localdate()
    start = _parse_date(request.GET.get("start"), today.replace(month=1, day=1))
    end = _parse_date(request.GET.get("end"), today)
    if end < start:
        start, end = end, start
    return render(
        request,
        "invoicing/statement.html",
        {
            "customer": customer, "start": start, "end": end,
            "statement": statement(customer, start, end),
            "company": {"name": settings.COMPANY_NAME, "vat": settings.COMPANY_VAT_NUMBER},
        },
    )


@login_required
@permission_required("invoicing.view_invoice", raise_exception=True)
def receivables(request):
    return render(request, "invoicing/receivables.html", {"report": aging()})


@login_required
@permission_required("invoicing.view_vat_return", raise_exception=True)
def vat_return_view(request):
    start, end, label = parse_period(request.GET.get("period"), timezone.localdate())
    report = vat_return(start, end)
    if request.GET.get("format") == "csv":
        response = HttpResponse(content_type="text/csv; charset=utf-8")
        response["Content-Disposition"] = f'attachment; filename="vat-return-{label}.csv"'
        response.write("\ufeff")   # BOM so Excel opens Arabic names correctly
        writer = csv.writer(response)
        for row in csv_rows(report):
            writer.writerow(row)
        return response
    today = timezone.localdate()
    quarters = [f"{y}-Q{q}" for y in (today.year, today.year - 1) for q in (4, 3, 2, 1)]
    return render(
        request,
        "invoicing/vat_return.html",
        {"report": report, "period": label, "quarters": quarters},
    )
