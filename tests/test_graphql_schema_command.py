"""Tests for the "graphql_schema" management command.

The command mirrors graphene-django's "graphql_schema" (same name, so it is a
drop-in for migrating users) but is built on graphql-core — NO graphene import
anywhere in the suite or the command.

It exports the schema as introspection JSON (matching graphene-django's
"{"data": <introspection>}" shape so existing codegen keeps working), or as
SDL when the output path ends in ".graphql" / ".gql".
"""

from __future__ import annotations

import json
from io import StringIO
from pathlib import Path
from typing import Any

import pytest
from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import override_settings

from django_graphex.management.commands.graphql_schema import Command

# Dotted path to the shared native test schema (a DjangoGraphQLSchema). The
# conftest harness already points DJANGO_GRAPHEX["SCHEMA"] here, but the
# --schema override test names it explicitly.
TEST_SCHEMA_PATH = "tests.schema.schema"


def _run(*args: Any, **kwargs: Any) -> str:
    """Invoke the command capturing stdout, returning the captured text.

    The command is passed to "call_command" as a Command INSTANCE (a fully
    supported Django testing API) so the test does not require django_graphex
    to be listed in INSTALLED_APPS — the package is a library, not an app, and
    its heavy "__init__" cannot be imported during app-registry population.

    Args:
        *args: Positional arguments forwarded to "call_command" (e.g. "--out").
        **kwargs: Keyword arguments forwarded to "call_command".

    Returns:
        output: The captured stdout text written by the command.
    """
    out = StringIO()
    call_command(Command(), *args, stdout=out, **kwargs)
    return out.getvalue()


def test_default_json_output_is_introspection(tmp_path: Path) -> None:
    """Default run must write introspection JSON wrapped as {"data": ...}.

    Args:
        tmp_path: Pytest fixture providing a unique temporary directory.
    """
    out_file = tmp_path / "schema.json"
    _run("--out", str(out_file))

    payload = json.loads(out_file.read_text())
    # graphene-django shape: top-level "data" key wrapping the introspection.
    assert "data" in payload
    assert "__schema" in payload["data"]
    type_names = {t["name"] for t in payload["data"]["__schema"]["types"]}
    # The shared test schema declares a Query root and a UserType.
    assert "Query" in type_names
    assert "UserType" in type_names


def test_json_output_indent_is_honored(tmp_path: Path) -> None:
    """The JSON output must be indented with the configured/overridden indent.

    Args:
        tmp_path: Pytest fixture providing a unique temporary directory.
    """
    out_file = tmp_path / "schema.json"
    _run("--out", str(out_file), "--indent", "4")

    text = out_file.read_text()
    # A 4-space indent means the first nested line starts with 4 spaces.
    assert "\n    " in text
    # Still valid JSON.
    json.loads(text)


def test_graphql_extension_writes_sdl(tmp_path: Path) -> None:
    """An output path ending in .graphql must write SDL, not JSON.

    Args:
        tmp_path: Pytest fixture providing a unique temporary directory.
    """
    out_file = tmp_path / "schema.graphql"
    _run("--out", str(out_file))

    text = out_file.read_text()
    assert "type Query" in text
    # SDL is not JSON: parsing it as JSON must fail.
    with pytest.raises(json.JSONDecodeError):
        json.loads(text)


def test_gql_extension_writes_sdl(tmp_path: Path) -> None:
    """An output path ending in .gql must also write SDL.

    Args:
        tmp_path: Pytest fixture providing a unique temporary directory.
    """
    out_file = tmp_path / "schema.gql"
    _run("--out", str(out_file))

    text = out_file.read_text()
    assert "type Query" in text


def test_out_dash_writes_to_stdout() -> None:
    """ "--out -" must write the schema to stdout instead of a file.

    If this breaks, users piping the command output would get an empty
    stdout while the schema silently lands nowhere.
    """
    output = _run("--out", "-")

    payload = json.loads(output)
    assert "data" in payload
    assert "__schema" in payload["data"]


def test_schema_override_dotted_path(tmp_path: Path) -> None:
    """ "--schema <dotted.path>" must use that schema instead of the settings one.

    Args:
        tmp_path: Pytest fixture providing a unique temporary directory.
    """
    out_file = tmp_path / "schema.json"
    # Clear the settings SCHEMA so only --schema can resolve it.
    with override_settings(DJANGO_GRAPHEX={"SCHEMA": None}):
        _run("--out", str(out_file), "--schema", TEST_SCHEMA_PATH)

    payload = json.loads(out_file.read_text())
    type_names = {t["name"] for t in payload["data"]["__schema"]["types"]}
    assert "Query" in type_names


def test_schema_output_setting_default(tmp_path: Path) -> None:
    """ "SCHEMA_OUTPUT" in DJANGO_GRAPHEX must act as the default output path.

    Args:
        tmp_path: Pytest fixture providing a unique temporary directory.
    """
    out_file = tmp_path / "from_settings.json"
    with override_settings(
        DJANGO_GRAPHEX={
            "SCHEMA": TEST_SCHEMA_PATH,
            "SCHEMA_OUTPUT": str(out_file),
        }
    ):
        _run()

    assert out_file.exists()
    payload = json.loads(out_file.read_text())
    assert "__schema" in payload["data"]


def test_schema_indent_setting_default(tmp_path: Path) -> None:
    """ "SCHEMA_INDENT" in DJANGO_GRAPHEX must control the default JSON indent.

    Args:
        tmp_path: Pytest fixture providing a unique temporary directory.
    """
    out_file = tmp_path / "indented.json"
    with override_settings(
        DJANGO_GRAPHEX={
            "SCHEMA": TEST_SCHEMA_PATH,
            "SCHEMA_OUTPUT": str(out_file),
            "SCHEMA_INDENT": 4,
        }
    ):
        _run()

    text = out_file.read_text()
    assert "\n    " in text


def test_no_schema_raises_command_error(tmp_path: Path) -> None:
    """No settings SCHEMA and no "--schema" must raise a clear CommandError.

    Args:
        tmp_path: Pytest fixture providing a unique temporary directory.
    """
    out_file = tmp_path / "schema.json"
    with override_settings(DJANGO_GRAPHEX={"SCHEMA": None}):
        with pytest.raises(CommandError) as exc_info:
            _run("--out", str(out_file))
    assert "schema" in str(exc_info.value).lower()
