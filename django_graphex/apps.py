"""Django AppConfig for django-graphex.

Calls "compile_all_inputs()" in "ready()" so all registered "InputType"
subclasses are compiled into "GraphQLInputObjectType" instances before the
first request is served.

This is NET-NEW in Phase 2 — no AppConfig existed before.
"""

from __future__ import annotations

from django.apps import AppConfig


class DjangoGraphexConfig(AppConfig):
    """AppConfig for django_graphex.

    Triggers "compile_all_inputs()" after all Django apps are loaded so
    that forward references in "InputType" annotations resolve correctly.
    """

    name = "django_graphex"
    verbose_name = "Django GraphEx"

    def ready(self) -> None:
        """Compile all registered InputType and DjangoObjectType subclasses into GraphQL types.

        Also registers the contenttypes (GenericForeignKey / GenericRel /
        GenericRelation) field converters now that the app registry is ready.
        Those converters cannot be registered at module-import time without
        loading the "ContentType" model during app-population, so the
        registration is deferred to here (see "converter" module).

        Finally registers the "DJANGO_GRAPHEX" unknown-key system check so a
        misspelled setting is reported by "manage.py check" instead of being
        silently ignored.
        """
        from django.core.checks import Tags, register

        from django_graphex.converter import (
            _ensure_contenttypes_converters_registered,
        )
        from django_graphex.core.base import compile_all_inputs
        from django_graphex.core.registry_compiler import compile_all_outputs
        from django_graphex.settings import check_unknown_settings

        register(check_unknown_settings, Tags.compatibility)
        _ensure_contenttypes_converters_registered()
        compile_all_inputs()
        compile_all_outputs()
