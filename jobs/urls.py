from django.urls import path

from jobs import views

app_name = "jobs"

urlpatterns = [
    path("", views.job_list, name="list"),
    path("new/", views.job_create, name="create"),
    path("<int:pk>/", views.job_detail, name="detail"),
    path("<int:pk>/edit/", views.job_update, name="update"),
    path("<int:pk>/status/", views.job_status, name="status"),
    path("<int:pk>/materials/", views.add_material, name="add_material"),
    path("<int:pk>/labour/", views.add_labour, name="add_labour"),
    path("materials/<int:pk>/delete/", views.delete_material, name="delete_material"),
    path("labour/<int:pk>/delete/", views.delete_labour, name="delete_labour"),
    path("profitability/", views.profitability_report, name="profitability"),
]
