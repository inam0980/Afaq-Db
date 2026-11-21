from django.contrib import admin
from simple_history.admin import SimpleHistoryAdmin

from jobs.models import Job


@admin.register(Job)
class JobAdmin(SimpleHistoryAdmin):
    list_display = ["number", "title", "customer", "service_type", "priority", "status", "scheduled_date"]
    list_filter = ["status", "service_type", "priority"]
    search_fields = ["number", "title", "customer__name"]
    list_select_related = ["customer"]
    autocomplete_fields = ["customer"]
    filter_horizontal = ["technicians"]
    readonly_fields = ["number", "status", "created_by", "created_at", "started_at", "completed_at", "cancel_reason"]
