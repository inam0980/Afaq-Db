from django.contrib import admin
from simple_history.admin import SimpleHistoryAdmin

from loans.models import Loan, LoanRepayment


class RepaymentInline(admin.TabularInline):
    model = LoanRepayment
    extra = 0
    can_delete = False
    readonly_fields = ("payslip", "amount")

    def has_add_permission(self, request, obj=None):
        return False


@admin.register(Loan)
class LoanAdmin(SimpleHistoryAdmin):
    list_display = ("employee", "kind", "amount", "installment", "first_month", "status")
    list_filter = ("status", "kind")
    search_fields = ("employee__first_name", "employee__last_name", "employee__employee_no")
    inlines = [RepaymentInline]
    readonly_fields = ("requested_by", "decided_by", "decided_at", "created_at")
