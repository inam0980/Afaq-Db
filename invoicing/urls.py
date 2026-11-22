from django.urls import path

from invoicing import views

app_name = "invoicing"

urlpatterns = [
    path("", views.invoice_list, name="list"),
    path("new/", views.invoice_create, name="create"),
    path("<int:pk>/", views.invoice_detail, name="detail"),
    path("<int:pk>/edit/", views.invoice_update, name="update"),
    path("<int:pk>/issue/", views.invoice_issue, name="issue"),
    path("from-job/<int:job_pk>/", views.invoice_from_job, name="from_job"),
    path("<int:pk>/payments/", views.add_payment, name="add_payment"),
    path("payments/<int:pk>/delete/", views.delete_payment, name="delete_payment"),
    path("<int:pk>/credit-note/", views.credit_note, name="credit_note"),
    path("statement/<int:customer_pk>/", views.customer_statement, name="statement"),
    path("receivables/", views.receivables, name="receivables"),
]
