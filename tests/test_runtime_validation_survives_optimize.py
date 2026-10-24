"""Configuration and input checks must not depend on assert statements."""

from __future__ import annotations

import ast
import subprocess  # nosec B404 - runs this interpreter on a fixed script
import sys
import textwrap
from pathlib import Path

import pytest
from django.core.exceptions import ImproperlyConfigured

import django_graphex
from django_graphex.core import ObjectType
from django_graphex.fields import DjangoFilterPaginateListField
from django_graphex.registry import Registry
from django_graphex.types import (
    DjangoInputObjectType,
    DjangoListObjectType,
    DjangoObjectType,
)

from .models import Author

PACKAGE = Path(django_graphex.__file__).parent


def _declare(base: type, **meta_options: object) -> type:
    """Declare a subclass of base with the given Meta options.

    Args:
        base: The host base class.
        **meta_options: Meta attributes to declare.

    Returns:
        The declared class.
    """
    meta = type(
        "Meta", (), {**meta_options, "__module__": __name__, "__qualname__": "H.Meta"}
    )
    return type(
        "H", (base,), {"Meta": meta, "__module__": __name__, "__qualname__": "H"}
    )


def test_runtime_code_has_no_assert_statements() -> None:
    """No module of the package validates anything with an assert.

    The check must hold with and without assert statements.
    """
    offenders = [
        f"{path.relative_to(PACKAGE)}:{node.lineno}"
        for path in PACKAGE.rglob("*.py")
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8")))
        if isinstance(node, ast.Assert)
    ]
    assert offenders == []


@pytest.mark.parametrize("base", (DjangoObjectType, DjangoInputObjectType))
def test_non_model_is_rejected(base: type) -> None:
    """A Meta.model that is not a Django model raises ImproperlyConfigured.

    Args:
        base: The host base class.
    """
    with pytest.raises(ImproperlyConfigured, match="valid Django Model"):
        _declare(base, model=str, registry=Registry())


@pytest.mark.parametrize("base", (DjangoObjectType, DjangoInputObjectType))
def test_non_registry_is_rejected(base: type) -> None:
    """A Meta.registry that is not a Registry raises ImproperlyConfigured.

    Args:
        base: The host base class.
    """
    with pytest.raises(ImproperlyConfigured, match="needs to be an instance of"):
        _declare(base, model=Author, registry=object())


def test_invalid_input_for_is_rejected() -> None:
    """An unknown Meta.input_for raises ImproperlyConfigured.

    The check must hold with and without assert statements.
    """
    with pytest.raises(ImproperlyConfigured, match="valid input_for"):
        _declare(
            DjangoInputObjectType, model=Author, registry=Registry(), input_for="x"
        )


def test_non_queryset_is_rejected() -> None:
    """A Meta.queryset that is not a QuerySet raises ImproperlyConfigured.

    The check must hold with and without assert statements.
    """
    with pytest.raises(ImproperlyConfigured, match="queryset"):
        _declare(
            DjangoListObjectType,
            model=Author,
            registry=Registry(),
            queryset=[Author],
        )


def test_non_paginator_is_rejected() -> None:
    """A pagination that is not a paginator raises ImproperlyConfigured.

    The check must hold with and without assert statements.
    """
    with pytest.raises(ImproperlyConfigured, match="DjangoGraphqlPagination"):
        DjangoFilterPaginateListField(
            _declare(DjangoObjectType, model=Author, registry=Registry()),
            pagination=object(),
        )


def test_abstract_type_with_other_options_is_rejected() -> None:
    """An abstract type declaring further options raises ImproperlyConfigured.

    The check must hold with and without assert statements.
    """
    meta = type(
        "Meta",
        (),
        {
            "abstract": True,
            "extra": 1,
            "__module__": __name__,
            "__qualname__": "A.Meta",
        },
    )
    with pytest.raises(ImproperlyConfigured, match="only contain the abstract"):
        type(
            "A",
            (ObjectType,),
            {"Meta": meta, "__module__": __name__, "__qualname__": "A"},
        )


def test_checks_still_reject_under_python_optimize() -> None:
    """With python -O the cited invalid configuration is still rejected.

    The check must hold with and without assert statements.
    """
    script = textwrap.dedent(
        """
        import django
        from django.conf import settings

        settings.configure(
            INSTALLED_APPS=["django.contrib.auth", "django.contrib.contenttypes"],
            DATABASES={"default": {"ENGINE": "django.db.backends.sqlite3",
                                   "NAME": ":memory:"}},
            SECRET_KEY="x",
        )
        django.setup()
        from django.core.exceptions import ImproperlyConfigured
        from django_graphex.registry import Registry
        from django_graphex.types import DjangoObjectType

        if __debug__:
            raise SystemExit("asserts are active; expected python -O")
        for meta in (
            {"model": str},
            {"model": __import__("django.contrib.auth.models",
                                 fromlist=["User"]).User, "registry": object()},
        ):
            attrs = {**meta, "__module__": "m", "__qualname__": "B.Meta"}
            try:
                type("B", (DjangoObjectType,), {
                    "Meta": type("Meta", (), attrs),
                    "__module__": "m", "__qualname__": "B"})
            except ImproperlyConfigured:
                continue
            raise SystemExit("accepted " + repr(meta))
        """
    )
    result = subprocess.run(  # noqa: S603  # nosec B603
        [sys.executable, "-O", "-c", script],
        capture_output=True,
        text=True,
        cwd=PACKAGE.parent,
        check=False,
    )
    assert result.returncode == 0, result.stderr
