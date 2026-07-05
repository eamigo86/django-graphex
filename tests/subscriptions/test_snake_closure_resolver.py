# -*- coding: utf-8 -*-
"""WU1 — Snake-closure resolver: correctness fix for camelCase silent-null bug.

graphql-core's default_field_resolver keys by "info.field_name", which is the
camelCase WIRE name (e.g. "isActive"). The serialized subscription payload
produced by "native/backend.py:to_representation" uses SNAKE keys (e.g.
"is_active"). This mismatch causes SILENT NULL on every multi-word field.

"make_snake_resolver" fixes this by closing over the snake-case key and
reading it directly from the source dict.

These tests are backend-agnostic: "resolvers.py" has zero Django/graphene/
channels imports, so no "pytest.importorskip" guard is needed here.
"""

from __future__ import annotations

from typing import Any

import pytest
from pytest_django.fixtures import DjangoAssertNumQueries

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_mock_info(field_name: str) -> Any:
    """Return a minimal stand-in for "graphql.GraphQLResolveInfo".

    Only "field_name" is used by default_field_resolver; our resolver ignores
    it entirely (reads the snake key directly), but the signature requires it.

    Args:
        field_name: The camelCase wire field name to attach to the stand-in.

    Returns:
        info: An object exposing only the "field_name" attribute.
    """

    class _FakeInfo:
        pass

    obj = _FakeInfo()
    obj.field_name = field_name  # type: ignore[attr-defined]
    return obj


# ---------------------------------------------------------------------------
# Correctness: multi-word field delivers the REAL value (not None)
# ---------------------------------------------------------------------------


def test_snake_field_resolves_real_value() -> None:
    """A single-word snake-key field must resolve correctly from a flat dict.

    Contract: this test ships broken if a single-word field stops resolving
    its real value from the serialized payload dict.
    """
    from django_graphex.subscriptions.resolvers import make_snake_resolver

    resolver = make_snake_resolver("is_active")
    root = {"is_active": True}
    info = _make_mock_info("isActive")  # camelCase wire name — what graphql-core passes
    assert resolver(root, info) is True


def test_multiword_field_no_null_isActive_dateJoined() -> None:
    """Both multi-word fields in the classic silent-null scenario must resolve.

    Contract: this is the proof of the blocking correctness fix described in
    design paragraph 6. Using "default_field_resolver" would return None for
    both fields because info.field_name is the camelCase wire name
    ("isActive"/"dateJoined") while the payload is keyed by the snake name.
    "make_snake_resolver" closes over the SNAKE key and reads it directly.
    """
    from django_graphex.subscriptions.resolvers import make_snake_resolver

    payload = {"is_active": True, "date_joined": "2024-01-01"}

    resolve_is_active = make_snake_resolver("is_active")
    resolve_date_joined = make_snake_resolver("date_joined")

    assert resolve_is_active(payload, _make_mock_info("isActive")) is True
    assert resolve_date_joined(payload, _make_mock_info("dateJoined")) == "2024-01-01"


# ---------------------------------------------------------------------------
# Sentinel: COND-B whitelist marker
# ---------------------------------------------------------------------------


def test_sentinel_set_on_closure() -> None:
    """The returned closure must carry a "_gdx_pure_projection = True" sentinel.

    Contract: COND-B ships broken if it cannot tell a generated pure
    projection resolver apart from a hand-written/live resolver, since this
    sentinel is what it uses to whitelist the former and reject the latter.
    """
    from django_graphex.subscriptions.resolvers import make_snake_resolver

    resolver = make_snake_resolver("some_field")
    assert getattr(resolver, "_gdx_pure_projection", None) is True


# ---------------------------------------------------------------------------
# Dual-mode: getattr fallback for non-dict root
# ---------------------------------------------------------------------------


def test_object_root_fallback() -> None:
    """When root is not a dict, the resolver must fall back to "getattr".

    Contract: object-root sources ship broken if the resolver assumes a dict
    root and never falls back to attribute access.
    """
    from django_graphex.subscriptions.resolvers import make_snake_resolver

    resolver = make_snake_resolver("is_active")

    class FakeObj:
        is_active = False

    obj = FakeObj()
    info = _make_mock_info("isActive")
    assert resolver(obj, info) is False


def test_object_root_fallback_missing_attr_returns_none() -> None:
    """The "getattr" fallback must return None when the attribute is absent.

    Contract: this test ships broken if a missing attribute on an object root
    raises instead of degrading gracefully to None.
    """
    from django_graphex.subscriptions.resolvers import make_snake_resolver

    resolver = make_snake_resolver("nonexistent_field")

    class FakeObj:
        pass

    assert resolver(FakeObj(), _make_mock_info("nonexistentField")) is None


# ---------------------------------------------------------------------------
# Performance: dict branch must NEVER touch the ORM (assertNumQueries(0))
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_assertNumQueries_zero(
    django_assert_num_queries: DjangoAssertNumQueries,
) -> None:
    """The dict-branch resolver must hit zero DB queries.

    Contract: subscription payload resolution ships broken (N+1 risk) if the
    dict branch of the resolver ever touches the ORM instead of reading the
    already-serialized dict.

    Args:
        django_assert_num_queries: The pytest-django fixture used as a
            context manager asserting an exact DB query count.
    """
    from django_graphex.subscriptions.resolvers import make_snake_resolver

    resolver = make_snake_resolver("is_active")
    root = {"is_active": True}
    info = _make_mock_info("isActive")

    with django_assert_num_queries(0):
        result = resolver(root, info)

    assert result is True


# ---------------------------------------------------------------------------
# Module contract: no graphene / channels imports
# ---------------------------------------------------------------------------


def test_resolvers_module_has_no_graphene_import() -> None:
    """The "resolvers" module must import neither graphene nor channels.

    Contract: the backend-agnostic guarantee ships broken if resolvers.py
    gains a dependency on graphene or channels, forcing importorskip guards
    onto every consumer of the module.
    """
    import inspect

    from django_graphex.subscriptions import resolvers

    source = inspect.getsource(resolvers)
    assert "import graphene" not in source
    assert "from graphene" not in source
    assert "import channels" not in source
    assert "from channels" not in source


def test_resolvers_module_dunder_all() -> None:
    """The "resolvers" module's "__all__" must export "make_snake_resolver".

    Contract: the public surface ships broken if make_snake_resolver stops
    being re-exported through __all__.
    """
    from django_graphex.subscriptions import resolvers

    assert hasattr(resolvers, "__all__")
    assert "make_snake_resolver" in resolvers.__all__
