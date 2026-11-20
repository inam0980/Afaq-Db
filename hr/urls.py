from django.urls import path

from hr import views

app_name = "hr"

urlpatterns = [
    path("employees/", views.employee_list, name="employee_list"),
    path("employees/new/", views.employee_create, name="employee_create"),
    path("employees/expiring/", views.expiring_documents, name="expiring_documents"),
    path("employees/<int:pk>/", views.employee_detail, name="employee_detail"),
    path("employees/<int:pk>/edit/", views.employee_update, name="employee_update"),
]
