from django import template

from zatca.models import EgsUnit, ZatcaDocument
from zatca.services import local_check

register = template.Library()


@register.inclusion_tag("zatca/panel.html", takes_context=True)
def zatca_panel(context, invoice):
    doc = ZatcaDocument.objects.filter(invoice=invoice).select_related("egs").first()
    return {
        "invoice": invoice,
        "doc": doc,
        "problems": local_check(doc) if doc else None,
        "egs_ready": EgsUnit.objects.exists(),
        "can_generate": context["perms"]["invoicing"]["issue_invoice"],
        "csrf_token": context.get("csrf_token"),
    }
