"""Standalone seed-schema SDL printer for the cross-process parity gate (WU2).

Run as a subprocess with ``GDX_BACKEND`` set in the environment BEFORE this
module imports ``django_graphex`` (the backend flag is read at import/class-def
time, so it can only be flipped per-process — D7). Prints the SDL of a MINIMAL
seed schema (a Query with ONE ``DjangoObjectField`` on a real Django model) to
stdout.

Usage::

    GDX_BACKEND=native  python -m tests.native._sdl_parity_seed
    GDX_BACKEND=graphene python -m tests.native._sdl_parity_seed

The two outputs, after ``normalize_sdl`` (ordering-only), MUST be byte-equal.
This is a GENUINE cross-process parity check: under native the seed assembles
via the native root compiler; under graphene via graphene.Schema.
"""
from __future__ import annotations

import os
import sys


def _configure_django() -> None:
    """Configure Django settings mirroring tests/conftest.py (minimal subset)."""
    import django
    from django.conf import settings

    if not settings.configured:
        settings.configure(
            ALLOWED_HOSTS=["*"],
            DATABASES={
                "default": {
                    "ENGINE": "django.db.backends.sqlite3",
                    "NAME": ":memory:",
                }
            },
            SITE_ID=1,
            SECRET_KEY="not very secret in tests",
            USE_I18N=True,
            STATIC_URL="/static/",
            ROOT_URLCONF="tests.urls",
            INSTALLED_APPS=(
                "django.contrib.admin",
                "django.contrib.auth",
                "django.contrib.contenttypes",
                "django.contrib.sessions",
                "django.contrib.sites",
                "django.contrib.staticfiles",
                "tests",
            ),
            GRAPHENE={"SCHEMA": "tests.schema.schema"},
        )
    django.setup()


def build_seed_sdl() -> str:
    """Build the seed schema for the current backend and return its SDL.

    The backend is determined by ``GDX_BACKEND`` (already set in os.environ
    before django_graphex is imported).
    """
    _configure_django()

    import graphene
    from graphql.utilities import print_schema

    from django_graphex.fields import DjangoObjectField
    from django_graphex.types import DjangoObjectType
    from tests.models import Category

    backend = os.environ.get("GDX_BACKEND", "graphene")

    class SeedCategoryType(DjangoObjectType):
        class Meta:
            model = Category
            # id-only node: ``id: ID!`` renders byte-identical on both backends.
            # (graphene-django renders CharField as nullable ``String`` while the
            # native compiler renders the non-null DB column as ``String!`` — a
            # WU1-level node divergence, out of scope for the WU2 ROOT-compiler
            # parity seed. WU10's full-schema parity covers node-field parity.)
            only_fields = ("id",)

    class SeedQuery(graphene.ObjectType):
        category = DjangoObjectField(SeedCategoryType)

    if backend == "native":
        # Compile outputs (app-ready normally does this; the seed app config
        # does not auto-run it here, so do it explicitly before assembly).
        from django_graphex.native.registry_compiler import compile_all_outputs
        from django_graphex.schema import DjangoGraphQLSchema

        compile_all_outputs()
        schema = DjangoGraphQLSchema(query=SeedQuery)
        # Anti-tautology sentinel: prove the native assembly path was taken and
        # the query field type IS the native canonical instance (gdx-bearing),
        # NOT a graphene-built type. Emitted to stderr to keep stdout = pure SDL.
        if os.environ.get("GDX_SEED_TRACE"):
            from django_graphex.native.base import get_shared_output_registry

            query_type = schema.graphql_schema.query_type
            field_type = query_type.fields["category"].type
            canonical = get_shared_output_registry().get_compiled(Category)
            is_native = field_type is canonical and "gdx" in (
                field_type.extensions or {}
            )
            sys.stderr.write(
                "GDX_SEED_PATH=native\n"
                if is_native
                else "GDX_SEED_PATH=graphene-fallback\n"
            )
        return print_schema(schema.graphql_schema)

    # Graphene path: build via graphene.Schema and print its graphql_schema.
    graphene_schema = graphene.Schema(query=SeedQuery)
    if os.environ.get("GDX_SEED_TRACE"):
        sys.stderr.write("GDX_SEED_PATH=graphene\n")
    return print_schema(graphene_schema.graphql_schema)


def main() -> int:
    sys.stdout.write(build_seed_sdl())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
