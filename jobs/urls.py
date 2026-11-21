from django.urls import path

from jobs import views

app_name = "jobs"

urlpatterns = [
    path("", views.job_list, name="list"),
    path("new/", views.job_create, name="create"),
    path("<int:pk>/", views.job_detail, name="detail"),
    path("<int:pk>/edit/", views.job_update, name="update"),
    path("<int:pk>/status/", views.job_status, name="status"),
]
