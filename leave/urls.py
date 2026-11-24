from django.urls import path

from leave import views

app_name = "leave"

urlpatterns = [
    path("", views.leave_list, name="list"),
    path("new/", views.leave_create, name="create"),
    path("<int:pk>/", views.leave_detail, name="detail"),
    path("<int:pk>/approve/", views.leave_approve, name="approve"),
    path("<int:pk>/reject/", views.leave_reject, name="reject"),
    path("<int:pk>/cancel/", views.leave_cancel, name="cancel"),
    path("<int:pk>/document/", views.leave_attachment, name="attachment"),
]
