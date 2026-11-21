import factory

from customers.models import Customer


class CustomerFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = Customer

    name = factory.Sequence(lambda n: f"Customer {n}")
    kind = Customer.Kind.INDIVIDUAL
    mobile = factory.Sequence(lambda n: f"055{n:07d}")
    city = "Riyadh"


class BusinessCustomerFactory(CustomerFactory):
    kind = Customer.Kind.BUSINESS
    name = factory.Sequence(lambda n: f"Company {n} LLC")
    vat_number = "300000000000003"
    district = "Al Olaya"
    street = "King Fahd Road"
    building_number = "1234"
    postal_code = "12211"
