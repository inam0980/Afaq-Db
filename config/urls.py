from django.conf import settings
from django.contrib import admin
from django.urls import include, path

from core.views import dashboard
from security.views import SecureLoginView

urlpatterns = [
    path("", dashboard, name="home"),
    path(settings.ADMIN_URL, admin.site.urls),
    path("accounts/login/", SecureLoginView.as_view(), name="login"),
    path("accounts/", include("django.contrib.auth.urls")),
    path("i18n/", include("django.conf.urls.i18n")),
    path("hr/", include("hr.urls")),
    path("payroll/", include("payroll.urls")),
    path("expenses/", include("expenses.urls")),
    path("customers/", include("customers.urls")),
    path("jobs/", include("jobs.urls")),
    path("invoices/", include("invoicing.urls")),
    path("", include("core.urls")),
]
