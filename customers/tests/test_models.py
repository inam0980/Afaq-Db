"""Unit tests: Customer rules."""

import pytest
from django.core.exceptions import ValidationError

from customers.models import Customer
from customers.tests.factories import BusinessCustomerFactory, CustomerFactory

pytestmark = pytest.mark.django_db


def errors(customer):
    with pytest.raises(ValidationError) as exc:
        customer.full_clean()
    return exc.value.message_dict


def test_individual_needs_only_name_and_mobile():
    CustomerFactory(email="", vat_number="", street="").full_clean()


def test_vat_registered_business_needs_full_address():
    c = BusinessCustomerFactory(street="", building_number="", postal_code="")
    assert {"street", "building_number", "postal_code"} <= set(errors(c))


def test_complete_business_customer_is_valid():
    BusinessCustomerFactory().full_clean()


def test_business_without_vat_number_does_not_need_address():
    BusinessCustomerFactory(vat_number="", street="", building_number="", postal_code="").full_clean()


def test_individual_cannot_have_vat_number():
    c = CustomerFactory(vat_number="300000000000003")
    assert "vat_number" in errors(c)


@pytest.mark.parametrize(
    "field, bad",
    [("mobile", "12345"), ("vat_number", "123"), ("postal_code", "12"), ("building_number", "12a4")],
)
def test_field_formats(field, bad):
    c = BusinessCustomerFactory()
    setattr(c, field, bad)
    assert field in errors(c)


def test_vat_number_is_unique_when_present():
    BusinessCustomerFactory(vat_number="300000000000003")
    c = BusinessCustomerFactory.build(vat_number="300000000000003")
    assert "vat_number" in errors(c)


def test_many_customers_without_vat_number_allowed():
    CustomerFactory(vat_number="")
    CustomerFactory(vat_number="").full_clean()


def test_address_line():
    c = BusinessCustomerFactory.build(
        building_number="1234", street="King Fahd Rd", district="Olaya", city="Riyadh", postal_code="12211"
    )
    assert c.address_line == "1234 King Fahd Rd, Olaya, Riyadh 12211"
    assert CustomerFactory.build(street="", district="", city="", building_number="", postal_code="").address_line == ""


def test_search_and_str():
    a = CustomerFactory(name="Ahmed Trading", mobile="0551112222")
    CustomerFactory(name="Other")
    assert list(Customer.objects.search("ahmed")) == [a]
    assert list(Customer.objects.search("0551112222")) == [a]
    assert str(a) == "Ahmed Trading"


def test_changes_are_audited():
    c = CustomerFactory()
    c.name = "Renamed"
    c.save()
    assert c.history.count() == 2
