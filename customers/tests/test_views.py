"""Integration tests: customer pages."""

import pytest
from django.urls import reverse

from customers.models import Customer
from customers.tests.factories import CustomerFactory

pytestmark = pytest.mark.django_db

LIST_URL = reverse("customers:list")
CREATE_URL = reverse("customers:create")


@pytest.fixture
def sales(client_with_perms):
    return client_with_perms("view_customer", "add_customer", "change_customer", "view_job")


def form_data(**overrides):
    data = {
        "name": "Riyadh Towers Co.",
        "name_ar": "شركة أبراج الرياض",
        "kind": "business",
        "mobile": "0551234567",
        "email": "ops@example.com",
        "vat_number": "300000000000003",
        "city": "Riyadh",
        "district": "Al Olaya",
        "street": "King Fahd Road",
        "building_number": "1234",
        "postal_code": "12211",
        "is_active": "on",
    }
    data.update(overrides)
    return data


def test_requires_permission(viewer_client):
    assert viewer_client.get(LIST_URL).status_code == 403


def test_create_business_customer(sales):
    response = sales.post(CREATE_URL, form_data())
    c = Customer.objects.get()
    assert response.status_code == 302
    assert response.url == reverse("customers:detail", args=[c.pk])


def test_create_shows_address_errors(sales):
    response = sales.post(CREATE_URL, form_data(street="", postal_code=""))
    assert {"street", "postal_code"} <= set(response.context["form"].errors)
    assert not Customer.objects.exists()


def test_list_search(sales):
    CustomerFactory(name="Ahmed Trading")
    CustomerFactory(name="Zeta")
    names = [c.name for c in sales.get(LIST_URL, {"q": "ahmed"}).context["customers"]]
    assert names == ["Ahmed Trading"]


def test_list_hides_inactive_unless_asked(sales):
    CustomerFactory(name="Old Client", is_active=False)
    CustomerFactory(name="Live Client")
    assert [c.name for c in sales.get(LIST_URL).context["customers"]] == ["Live Client"]
    assert len(sales.get(LIST_URL, {"all": "1"}).context["customers"]) == 2


def test_update(sales):
    c = CustomerFactory()
    data = form_data(kind="individual", vat_number="", name="New Name")
    response = sales.post(reverse("customers:update", args=[c.pk]), data)
    c.refresh_from_db()
    assert response.status_code == 302
    assert c.name == "New Name"


def test_update_form_renders(sales):
    c = CustomerFactory()
    assert sales.get(reverse("customers:update", args=[c.pk])).status_code == 200


def test_detail_lists_customer_jobs(sales):
    from jobs.tests.factories import JobFactory

    job = JobFactory(title="AC not cooling")
    html = sales.get(reverse("customers:detail", args=[job.customer.pk])).content.decode()
    assert "AC not cooling" in html
    assert job.number in html


def test_viewer_cannot_create(client_with_perms):
    client = client_with_perms("view_customer")
    assert client.get(CREATE_URL).status_code == 403
