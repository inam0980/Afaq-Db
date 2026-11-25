from django.urls import path

from zatca import views

app_name = "zatca"

urlpatterns = [
    path("invoices/<int:invoice_pk>/generate/", views.generate, name="generate"),
    path("documents/<int:pk>/xml/", views.download, name="download"),
]
