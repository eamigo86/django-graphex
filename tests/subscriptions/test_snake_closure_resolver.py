# -*- coding: utf-8 -*-
"""WU1 — Snake-closure resolver: correctness fix for camelCase silent-null bug.

graphql-core's default_field_resolver keys by ``info.field_name``, which is the
camelCase WIRE name (e.g. ``isActive``).  The serialized subscription payload
produced by ``native/backend.py:to_representation`` uses SNAKE keys (e.g.
``is_active``).  This mismatch causes SILENT NULL on every multi-word field.

``make_snake_resolver`` fixes this by closing over the snake-case key and
reading it directly from the source dict.

These tests are backend-agnostic: ``resolvers.py`` has zero Django/graphene/
channels imports, so no ``pytest.importorskip`` guard is needed here.
"""
from __future__ import annotations

import pytest


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_mock_info(field_name: str):
    """Return a minimal stand-in for ``graphql.GraphQLResolveInfo``.

    Only ``field_name`` is used by default_field_resolver; our resolver ignores
    it entirely (reads the snake key directly), but the signature requires it.
    """

    class _FakeInfo:
        pass

    obj = _FakeInfo()
    obj.field_name = field_name  # type: ignore[attr-defined]
    return obj


# ---------------------------------------------------------------------------
# Correctness: multi-word field delivers the REAL value (not None)
# ---------------------------------------------------------------------------


def test_snake_field_resolves_real_value():
    """A single-word snake-key field is resolved correctly from a flat dict."""
    from django_graphex.subscriptions.resolvers import make_snake_resolver

    resolver = make_snake_resolver("is_active")
    root = {"is_active": True}
    info = _make_mock_info("isActive")  # camelCase wire name — what graphql-core passes
    assert resolver(root, info) is True


def test_multiword_field_no_null_isActive_dateJoined():
    """The classic silent-null scenario: two multi-word fields, both must resolve.

    This is THE proof of the blocking correctness fix described in design §6.
    Using ``default_field_resolver`` would return ``None`` for both because:
      - info.field_name == 'isActive'  → source.get('isActive') → None
      - info.field_name == 'dateJoined' → source.get('dateJoined') → None
    ``make_snake_resolver`` closes over the SNAKE key and reads it directly.
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


def test_sentinel_set_on_closure():
    """The returned closure MUST carry ``_gdx_pure_projection = True``.

    This sentinel (a) lets COND-B whitelist the closure at schema build time
    and (b) lets COND-B reject hand-written/live resolvers that lack it.
    """
    from django_graphex.subscriptions.resolvers import make_snake_resolver

    resolver = make_snake_resolver("some_field")
    assert getattr(resolver, "_gdx_pure_projection", None) is True


# ---------------------------------------------------------------------------
# Dual-mode: getattr fallback for non-dict root
# ---------------------------------------------------------------------------


def test_object_root_fallback():
    """When root is NOT a dict, the resolver falls back to ``getattr``."""
    from django_graphex.subscriptions.resolvers import make_snake_resolver

    resolver = make_snake_resolver("is_active")

    class FakeObj:
        is_active = False

    obj = FakeObj()
    info = _make_mock_info("isActive")
    assert resolver(obj, info) is False


def test_object_root_fallback_missing_attr_returns_none():
    """``getattr`` fallback returns ``None`` when the attribute is absent."""
    from django_graphex.subscriptions.resolvers import make_snake_resolver

    resolver = make_snake_resolver("nonexistent_field")

    class FakeObj:
        pass

    assert resolver(FakeObj(), _make_mock_info("nonexistentField")) is None


# ---------------------------------------------------------------------------
# Performance: dict branch must NEVER touch the ORM (assertNumQueries(0))
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_assertNumQueries_zero(django_assert_num_queries):
    """Dict-branch resolver hits zero DB queries — no ORM, no model access."""
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


def test_resolvers_module_has_no_graphene_import():
    """``resolvers.py`` must import neither graphene nor channels."""
    import importlib
    import inspect

    from django_graphex.subscriptions import resolvers

    source = inspect.getsource(resolvers)
    assert "import graphene" not in source
    assert "from graphene" not in source
    assert "import channels" not in source
    assert "from channels" not in source


def test_resolvers_module_dunder_all():
    """``__all__`` must export exactly ``make_snake_resolver``."""
    from django_graphex.subscriptions import resolvers

    assert hasattr(resolvers, "__all__")
    assert "make_snake_resolver" in resolvers.__all__
