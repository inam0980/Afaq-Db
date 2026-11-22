from django.contrib import admin
from django.contrib.admin.options import ActionLocation
from simple_history.admin import SimpleHistoryAdmin

from invoicing.models import Invoice, InvoiceLine


class InvoiceLineInline(admin.TabularInline):
    model = InvoiceLine
    extra = 0
    readonly_fields = ["subtotal", "vat", "total"]

    def has_change_permission(self, request, obj=None):
        return obj is None or obj.is_draft

    has_add_permission = has_delete_permission = has_change_permission


@admin.register(Invoice)
class InvoiceAdmin(SimpleHistoryAdmin):
    list_display = ["__str__", "customer", "issue_date", "due_date", "total", "status", "invoice_type"]
    list_filter = ["status", "invoice_type"]
    search_fields = ["number", "customer__name", "buyer_name"]
    list_select_related = ["customer"]
    inlines = [InvoiceLineInline]
    readonly_fields = [
        "number", "status", "invoice_type", "subtotal", "vat_amount", "total",
        "buyer_name", "buyer_vat_number", "buyer_address", "created_by", "issued_by", "issued_at",
    ]

    def get_actions(self, request, action_location=ActionLocation.CHANGE_LIST):
        # Bulk delete bypasses the issued-invoice lock.
        actions = super().get_actions(request, action_location=action_location)
        actions.pop("delete_selected", None)
        return actions

    def has_change_permission(self, request, obj=None):
        if obj is not None and not obj.is_draft:
            return False
        return super().has_change_permission(request, obj)

    def has_delete_permission(self, request, obj=None):
        if obj is not None and not obj.is_draft:
            return False
        return super().has_delete_permission(request, obj)
