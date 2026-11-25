from django.contrib import messages
from django.contrib.auth.decorators import login_required, permission_required
from django.core.exceptions import ValidationError
from django.http import HttpResponse
from django.shortcuts import get_object_or_404, redirect
from django.utils.translation import gettext as _
from django.views.decorators.http import require_POST

from invoicing.models import Invoice
from zatca import services
from zatca.models import ZatcaDocument


@login_required
@require_POST
@permission_required("invoicing.issue_invoice", raise_exception=True)
def generate(request, invoice_pk):
    invoice = get_object_or_404(Invoice, pk=invoice_pk)
    try:
        services.generate(invoice)
    except ValidationError as exc:
        messages.error(request, " ".join(exc.messages))
    else:
        messages.success(request, _("ZATCA XML generated and signed."))
    return redirect(invoice)


@login_required
@permission_required("invoicing.view_invoice", raise_exception=True)
def download(request, pk):
    doc = get_object_or_404(ZatcaDocument.objects.select_related("invoice"), pk=pk)
    response = HttpResponse(doc.xml, content_type="application/xml")
    response["Content-Disposition"] = f'attachment; filename="{doc.file_name}"'
    return response
