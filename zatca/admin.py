from django.contrib import admin

from zatca.models import EgsUnit, ZatcaDocument


@admin.register(EgsUnit)
class EgsUnitAdmin(admin.ModelAdmin):
    list_display = ("name", "environment", "last_icv", "created_at")
    readonly_fields = ("last_icv", "last_hash", "created_at")
    exclude = ("private_key",)


@admin.register(ZatcaDocument)
class ZatcaDocumentAdmin(admin.ModelAdmin):
    list_display = ("invoice", "icv", "status", "created_at")
    list_filter = ("status",)
    readonly_fields = [f.name for f in ZatcaDocument._meta.fields]

    def has_add_permission(self, request):
        return False

    def has_delete_permission(self, request, obj=None):
        return False
