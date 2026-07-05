"""Factory Boy factories for building test-database fixtures."""

import factory
from django.contrib.auth.models import User


class UserFactory(factory.django.DjangoModelFactory):
    """Build "User" instances with unique usernames and a derived email.

    Reuses an existing row instead of duplicating one whenever a "User" with
    the same "username" already exists in the test database.
    """

    username = factory.Sequence(lambda n: f"user_{n}")
    first_name = factory.Faker("first_name")
    last_name = factory.Faker("last_name")
    email = factory.LazyAttribute(lambda o: f"{o.username}@example.com")

    class Meta:
        """Meta configuration for UserFactory.

        Declares the target model and the field used to detect and reuse an
        already-existing row instead of creating a duplicate.
        """

        model = User
        django_get_or_create = ("username",)
