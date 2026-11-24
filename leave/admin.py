from django.contrib import admin
from simple_history.admin import SimpleHistoryAdmin

from leave.models import LeaveRequest, LeaveType


@admin.register(LeaveType)
class LeaveTypeAdmin(admin.ModelAdmin):
    list_display = ["code", "name_en", "name_ar", "is_paid", "deducts_salary", "uses_annual_balance",
                    "counts_calendar_days", "max_days", "is_active"]
    list_filter = ["is_active", "is_paid"]


@admin.register(LeaveRequest)
class LeaveRequestAdmin(SimpleHistoryAdmin):
    list_display = ["employee", "leave_type", "start_date", "end_date", "days", "status"]
    list_filter = ["status", "leave_type"]
    search_fields = ["employee__first_name", "employee__last_name", "employee__employee_no"]
    list_select_related = ["employee", "leave_type"]
    readonly_fields = ["days", "status", "created_by", "decided_by", "decided_at", "decision_note"]
