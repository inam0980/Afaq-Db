from django.contrib import admin
from django.urls import include, path

from core.views import dashboard

urlpatterns = [
    path("", dashboard, name="home"),
    path("admin/", admin.site.urls),
    path("accounts/", include("django.contrib.auth.urls")),
    path("i18n/", include("django.conf.urls.i18n")),
    path("hr/", include("hr.urls")),
    path("payroll/", include("payroll.urls")),
    path("", include("core.urls")),
]
