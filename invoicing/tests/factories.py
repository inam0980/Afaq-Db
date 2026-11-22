import datetime as dt
from decimal import Decimal

import factory
from django.utils import timezone

from customers.tests.factories import CustomerFactory
from expenses.tests.factories import UserFactory
from invoicing.models import Invoice, InvoiceLine


class InvoiceFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = Invoice

    customer = factory.SubFactory(CustomerFactory)
    issue_date = factory.LazyFunction(timezone.localdate)
    due_date = factory.LazyFunction(lambda: timezone.localdate() + dt.timedelta(days=30))
    created_by = factory.SubFactory(UserFactory)


class InvoiceLineFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = InvoiceLine

    invoice = factory.SubFactory(InvoiceFactory)
    description = "AC maintenance"
    quantity = Decimal("1")
    unit_price = Decimal("1000.00")
    vat_rate = Decimal("15")


def invoice_with_lines(*prices, **kwargs):
    inv = InvoiceFactory(**kwargs)
    for price in prices or (Decimal("1000.00"),):
        InvoiceLineFactory(invoice=inv, unit_price=Decimal(price))
    from invoicing.services import recalculate

    recalculate(inv)
    return inv
