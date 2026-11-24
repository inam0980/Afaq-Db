from django.contrib import admin

from security.models import LoginEvent


@admin.register(LoginEvent)
class LoginEventAdmin(admin.ModelAdmin):
    """Audit log: viewable, never editable."""

    list_display = ["created_at", "username", "successful", "ip", "user_agent"]
    list_filter = ["successful", "created_at"]
    search_fields = ["username", "ip"]
    date_hierarchy = "created_at"

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False
