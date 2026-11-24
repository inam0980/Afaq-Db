from django.urls import path

from dataimport import views

app_name = "dataimport"

urlpatterns = [
    path("", views.index, name="index"),
    path("<slug:kind>/", views.upload, name="upload"),
    path("<slug:kind>/confirm/", views.confirm, name="confirm"),
    path("<slug:kind>/template.xlsx", views.template, name="template"),
]
