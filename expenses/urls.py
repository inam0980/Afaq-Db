from django.urls import path

from expenses import views

app_name = "expenses"

urlpatterns = [
    path("", views.expense_list, name="list"),
    path("new/", views.expense_create, name="create"),
    path("<int:pk>/", views.expense_detail, name="detail"),
    path("<int:pk>/edit/", views.expense_update, name="update"),
    path("<int:pk>/submit/", views.expense_submit, name="submit"),
    path("<int:pk>/approve/", views.expense_approve, name="approve"),
    path("<int:pk>/reject/", views.expense_reject, name="reject"),
    path("<int:pk>/receipt/", views.expense_receipt, name="receipt"),
]
