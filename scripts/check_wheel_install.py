# -*- coding: utf-8 -*-
"""Smoke-test an installed wheel from outside the source checkout."""

from __future__ import annotations

import importlib.metadata as metadata
import importlib.util as util
import sys
import tomllib
from pathlib import Path


def expected_version(project_root: Path) -> str:
    """Return the release version declared by the source metadata."""
    pyproject = project_root / "pyproject.toml"
    data = tomllib.loads(pyproject.read_text(encoding="utf-8"))
    return str(data["project"]["version"])


def assert_outside_checkout(module_file: Path, project_root: Path) -> None:
    """Reject an import resolved from the source checkout."""
    try:
        module_file.resolve().relative_to(project_root.resolve())
    except ValueError:
        return
    raise RuntimeError(f"django_graphex imported from checkout: {module_file}")


def assert_distribution_contract(module_file: Path, version: str) -> None:
    """Validate metadata, typing marker, and the base dependency boundary."""
    installed_version = metadata.version("django-graphex")
    if installed_version != version:
        raise RuntimeError(
            f"installed metadata is {installed_version}, expected {version}"
        )
    if not (module_file.parent / "py.typed").is_file():
        raise RuntimeError("installed wheel is missing django_graphex/py.typed")
    if util.find_spec("channels") is not None:
        raise RuntimeError("base wheel unexpectedly installed Channels")


def assert_graphql_smoke() -> None:
    """Initialize Django, compile a minimal schema, and execute a query."""
    from django.conf import settings

    if not settings.configured:
        settings.configure(
            SECRET_KEY="django-graphex-wheel-smoke",
            INSTALLED_APPS=[],
            DATABASES={
                "default": {
                    "ENGINE": "django.db.backends.sqlite3",
                    "NAME": ":memory:",
                }
            },
        )

    import django
    from graphql import GraphQLString, graphql_sync

    django.setup()

    from django_graphex.core import ObjectType, field
    from django_graphex.schema import DjangoGraphQLSchema

    class Query(ObjectType):
        hello = field(GraphQLString)

        def resolve_hello(root: object, info: object) -> str:
            return "wheel-ok"

    schema = DjangoGraphQLSchema(query=Query)
    result = graphql_sync(schema.graphql_schema, "{ hello }")
    if result.errors or result.data != {"hello": "wheel-ok"}:
        raise RuntimeError(f"installed wheel query failed: {result}")


def main(argv: list[str] | None = None) -> int:
    """Run all installed-wheel contracts."""
    arguments = sys.argv[1:] if argv is None else argv
    if len(arguments) != 1:
        print("usage: check_wheel_install.py PROJECT_ROOT", file=sys.stderr)
        return 2

    project_root = Path(arguments[0]).resolve()
    import django_graphex

    module_file = Path(django_graphex.__file__).resolve()
    assert_outside_checkout(module_file, project_root)
    assert_distribution_contract(module_file, expected_version(project_root))
    assert_graphql_smoke()
    print(f"OK: installed wheel {metadata.version('django-graphex')} passed smoke test")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
