import factory

from customers.tests.factories import CustomerFactory
from expenses.tests.factories import UserFactory
from jobs.models import Job


class JobFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = Job

    customer = factory.SubFactory(CustomerFactory)
    service_type = Job.ServiceType.AC
    title = "AC not cooling"
    created_by = factory.SubFactory(UserFactory)
