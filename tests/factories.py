import factory
from django.contrib.auth.models import User


class UserFactory(factory.django.DjangoModelFactory):
    username = factory.Sequence(lambda n: f"user_{n}")
    first_name = factory.Faker("first_name")
    last_name = factory.Faker("last_name")
    email = factory.LazyAttribute(lambda o: f"{o.username}@example.com")

    class Meta:
        model = User
        django_get_or_create = ("username",)
