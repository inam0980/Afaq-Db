from django.urls import path

from payroll import views

app_name = "payroll"

urlpatterns = [
    path("employees/<int:pk>/salary/", views.employee_salary, name="employee_salary"),
    path("runs/", views.run_list, name="run_list"),
    path("runs/<int:pk>/", views.run_detail, name="run_detail"),
    path("runs/<int:pk>/approve/", views.run_approve, name="run_approve"),
    path("runs/<int:pk>/paid/", views.run_mark_paid, name="run_mark_paid"),
    path("runs/<int:pk>/regenerate/", views.run_regenerate, name="run_regenerate"),
    path("payslips/<int:pk>/", views.payslip_detail, name="payslip_detail"),
    path("payslips/<int:pk>/edit/", views.payslip_edit, name="payslip_edit"),
]
