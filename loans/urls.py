from django.urls import path

from loans import views

app_name = "loans"

urlpatterns = [
    path("", views.loan_list, name="list"),
    path("new/", views.loan_create, name="create"),
    path("<int:pk>/", views.loan_detail, name="detail"),
    path("<int:pk>/approve/", views.loan_approve, name="approve"),
    path("<int:pk>/reject/", views.loan_reject, name="reject"),
]
