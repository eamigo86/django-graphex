"""Django AppConfig for django-graphex.

Calls ``compile_all_inputs()`` in ``ready()`` so all registered ``InputType``
subclasses are compiled into ``GraphQLInputObjectType`` instances before the
first request is served.

This is NET-NEW in Phase 2 — no AppConfig existed before.
"""

from __future__ import annotations

from django.apps import AppConfig


class DjangoGraphexConfig(AppConfig):
    """AppConfig for django_graphex.

    Triggers ``compile_all_inputs()`` after all Django apps are loaded so
    that forward references in ``InputType`` annotations resolve correctly.
    """

    name = "django_graphex"
    verbose_name = "Django GraphEx"

    def ready(self) -> None:
        """Compile all registered InputType subclasses into GraphQL input types."""
        from django_graphex.native.base import compile_all_inputs

        compile_all_inputs()
