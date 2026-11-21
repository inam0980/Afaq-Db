from django.contrib import admin
from django.contrib.admin.options import ActionLocation
from simple_history.admin import SimpleHistoryAdmin

from expenses.models import Expense, ExpenseCategory


@admin.register(ExpenseCategory)
class ExpenseCategoryAdmin(admin.ModelAdmin):
    list_display = ["code", "name_en", "name_ar", "is_active"]
    list_filter = ["is_active"]
    search_fields = ["code", "name_en", "name_ar"]


@admin.register(Expense)
class ExpenseAdmin(SimpleHistoryAdmin):
    list_display = ["number", "date", "category", "description", "total", "vat_amount", "status"]
    list_filter = ["status", "category", "payment_method"]
    search_fields = ["number", "description", "vendor_name", "invoice_number"]
    date_hierarchy = "date"
    list_select_related = ["category"]
    readonly_fields = [
        "number", "vat_amount", "amount_excl_vat", "status", "created_by", "created_at",
        "submitted_at", "decided_by", "decided_at", "rejection_reason",
    ]

    def get_actions(self, request, action_location=ActionLocation.CHANGE_LIST):
        # Bulk delete bypasses the approved-expense lock.
        actions = super().get_actions(request, action_location=action_location)
        actions.pop("delete_selected", None)
        return actions

    def has_delete_permission(self, request, obj=None):
        if obj is not None and obj.status == Expense.Status.APPROVED:
            return False
        return super().has_delete_permission(request, obj)
