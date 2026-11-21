from django.contrib import admin
from simple_history.admin import SimpleHistoryAdmin

from customers.models import Customer


@admin.register(Customer)
class CustomerAdmin(SimpleHistoryAdmin):
    list_display = ["name", "kind", "mobile", "vat_number", "city", "is_active"]
    list_filter = ["kind", "is_active", "city"]
    search_fields = ["name", "name_ar", "mobile", "vat_number"]
