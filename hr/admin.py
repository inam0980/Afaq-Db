from django.contrib import admin
from simple_history.admin import SimpleHistoryAdmin

from hr.models import Department, Employee


@admin.register(Department)
class DepartmentAdmin(admin.ModelAdmin):
    list_display = ["code", "name_en", "name_ar"]
    search_fields = ["code", "name_en", "name_ar"]


@admin.register(Employee)
class EmployeeAdmin(SimpleHistoryAdmin):
    list_display = [
        "employee_no",
        "full_name",
        "nationality",
        "department",
        "job_title",
        "status",
        "id_expiry",
    ]
    list_filter = ["status", "nationality", "department"]
    search_fields = ["employee_no", "first_name", "last_name", "name_ar", "id_number"]
    readonly_fields = ["employee_no", "created_at", "updated_at"]
    list_select_related = ["department"]

    def has_delete_permission(self, request, obj=None):
        # HR records are never deleted; set status to Terminated instead.
        return False
