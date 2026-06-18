"""``graphql_schema`` management command: export the GraphQL schema.

Mirrors graphene-django's ``graphql_schema`` command (same name, so it is a
drop-in for projects migrating off graphene-django) but is built entirely on
graphql-core — there is NO graphene import here.

Behavior
--------
* ``python manage.py graphql_schema`` writes the **introspection JSON** of the
  schema to ``DJANGO_GRAPHEX["SCHEMA_OUTPUT"]`` (default ``"schema.json"``),
  indented with ``DJANGO_GRAPHEX["SCHEMA_INDENT"]`` (default ``2``).
* An output path ending in ``.graphql`` / ``.gql`` writes **SDL** instead
  (graphql-core ``print_schema``).
* ``--out`` / ``-o <path>`` overrides ``SCHEMA_OUTPUT``; ``--out -`` writes to
  **stdout**.
* ``--indent`` / ``-i <int>`` overrides ``SCHEMA_INDENT``.
* ``--schema <dotted.path>`` resolves that schema (a ``DjangoGraphQLSchema`` or
  the dotted path to one) instead of ``DJANGO_GRAPHEX["SCHEMA"]``. When neither
  is set, the command raises ``CommandError`` with an actionable message.

The introspection JSON is wrapped as ``{"data": <introspection>}`` to match
graphene-django's output shape, so existing client codegen tooling keeps
working after migrating.
"""

from __future__ import annotations

import json
from typing import Any

from django.core.management.base import BaseCommand, CommandError
from django.utils.module_loading import import_string

from django_graphex.settings import graphql_api_settings

# Output extensions that select SDL (graphql-core ``print_schema``) over the
# default introspection JSON.
SDL_EXTENSIONS = (".graphql", ".gql")


class Command(BaseCommand):
    """Export the django-graphex schema as introspection JSON or SDL."""

    help = (
        "Export the GraphQL schema as introspection JSON (default) or as SDL "
        "when the output path ends in .graphql / .gql. Drop-in replacement for "
        "graphene-django's graphql_schema command."
    )

    def add_arguments(self, parser: Any) -> None:
        """Register the command-line options.

        Args:
            parser: The argparse parser supplied by Django.
        """
        parser.add_argument(
            "--out",
            "-o",
            dest="out",
            default=None,
            help=(
                "Output file path; overrides DJANGO_GRAPHEX['SCHEMA_OUTPUT']. "
                "Use '-' to write to stdout. A .graphql / .gql extension writes "
                "SDL instead of introspection JSON."
            ),
        )
        parser.add_argument(
            "--indent",
            "-i",
            dest="indent",
            type=int,
            default=None,
            help=(
                "JSON indentation; overrides DJANGO_GRAPHEX['SCHEMA_INDENT'] "
                "(default 2). Ignored for SDL output."
            ),
        )
        parser.add_argument(
            "--schema",
            dest="schema",
            default=None,
            help=(
                "Dotted path to the schema (a DjangoGraphQLSchema) to export; "
                "overrides DJANGO_GRAPHEX['SCHEMA']."
            ),
        )

    def handle(self, *args: Any, **options: Any) -> None:
        """Resolve the schema and write its introspection JSON or SDL.

        Args:
            *args: Unused positional arguments.
            **options: Parsed command options (``out``, ``indent``, ``schema``).

        Raises:
            CommandError: When no schema can be resolved from ``--schema`` or
                ``DJANGO_GRAPHEX['SCHEMA']``.
        """
        schema = self._resolve_schema(options.get("schema"))
        graphql_schema = self._underlying_schema(schema)

        out = options.get("out")
        if out is None:
            out = graphql_api_settings.SCHEMA_OUTPUT
        indent = options.get("indent")
        if indent is None:
            indent = graphql_api_settings.SCHEMA_INDENT

        as_sdl = out != "-" and str(out).lower().endswith(SDL_EXTENSIONS)
        if as_sdl:
            content = self._render_sdl(graphql_schema)
        else:
            content = self._render_json(graphql_schema, indent)

        if out == "-":
            self.stdout.write(content)
        else:
            with open(out, "w", encoding="utf-8") as handle:
                handle.write(content)
            self.stdout.write(
                self.style.SUCCESS(f"Successfully dumped GraphQL schema to {out}")
            )

    def _resolve_schema(self, schema_path: str | None) -> Any:
        """Resolve the schema from ``--schema`` or the settings namespace.

        Args:
            schema_path: The dotted path passed via ``--schema`` (or ``None``).

        Returns:
            The resolved schema object (a ``DjangoGraphQLSchema``).

        Raises:
            CommandError: When neither ``--schema`` nor
                ``DJANGO_GRAPHEX['SCHEMA']`` provides a schema.
        """
        if schema_path:
            try:
                return import_string(schema_path)
            except ImportError as exc:
                raise CommandError(
                    f"Could not import schema from --schema '{schema_path}': {exc}"
                ) from exc

        # graphql_api_settings.SCHEMA import-resolves a dotted string for us.
        schema = graphql_api_settings.SCHEMA
        if schema is None:
            raise CommandError(
                "No schema configured. Set DJANGO_GRAPHEX['SCHEMA'] to a dotted "
                "path (or schema object), or pass --schema <dotted.path>."
            )
        return schema

    @staticmethod
    def _underlying_schema(schema: Any) -> Any:
        """Return the underlying graphql-core ``GraphQLSchema``.

        A ``DjangoGraphQLSchema`` exposes the graphql-core schema on its
        ``graphql_schema`` attribute; a raw graphql-core schema is used as-is.

        Args:
            schema: The resolved schema object.

        Returns:
            The graphql-core ``GraphQLSchema`` instance.
        """
        return getattr(schema, "graphql_schema", schema)

    @staticmethod
    def _render_json(graphql_schema: Any, indent: int) -> str:
        """Render the schema introspection as graphene-django-shaped JSON.

        Args:
            graphql_schema: The graphql-core ``GraphQLSchema``.
            indent: The JSON indentation level.

        Returns:
            A JSON string wrapped as ``{"data": <introspection>}``.
        """
        from graphql.utilities import introspection_from_schema

        introspection = introspection_from_schema(graphql_schema)
        # Match graphene-django's output shape so existing codegen keeps working.
        return json.dumps({"data": introspection}, indent=indent, sort_keys=True)

    @staticmethod
    def _render_sdl(graphql_schema: Any) -> str:
        """Render the schema as SDL via graphql-core ``print_schema``.

        Args:
            graphql_schema: The graphql-core ``GraphQLSchema``.

        Returns:
            The schema definition language (SDL) string.
        """
        from graphql.utilities import print_schema

        return print_schema(graphql_schema)
