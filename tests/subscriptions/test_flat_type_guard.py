# -*- coding: utf-8 -*-
"""WU3 — COND-B build-time flat-type guard.

Design §5 (COND-B): at schema build time, for every subscription output (event)
type, assert that EVERY field's resolve is a sentinel-marked snake-closure.
Hard-fail on any field whose resolve is MISSING the sentinel, is ``None``, or
is ``default_field_resolver``.

Key design decision: the check is ``_gdx_pure_projection`` SENTINEL PRESENCE,
NOT identity against ``default_field_resolver``.  Identity-checking
``default_field_resolver`` would re-admit the silent-null combo (a snake payload
with a camelCase-keying default resolver).  A snake-closure-shaped fn that LACKS
the sentinel must ALSO be rejected.

Type-level escape hatch: if the TYPE itself carries ``_gdx_pure_projection``
(e.g. ``some_type._gdx_pure_projection = True``), the guard is bypassed for
that type — advanced users accept the per-subscriber live-resolver cost.

These tests are the WU3 gate:
  - HARD-FAIL on a live/hand-written resolver field (lacking sentinel)
  - PASS a flat type whose every field has a sentinel-marked snake-closure
  - REJECT an unmarked closure (proves sentinel check, NOT shape/identity check)
  - REJECT resolve=None
  - REJECT resolve=default_field_resolver
  - ESCAPE-HATCH: type-level _gdx_pure_projection bypasses guard (no raise)
"""
from __future__ import annotations

import pytest
from graphql import (
    GraphQLField,
    GraphQLObjectType,
    GraphQLString,
    default_field_resolver,
)

from django_graphex.subscriptions.guard import (
    check_subscription_output_type,
    check_subscription_schema,
)
from django_graphex.subscriptions.resolvers import make_snake_resolver

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_type(name: str, fields: dict) -> GraphQLObjectType:
    """Build a GraphQLObjectType with the given fields dict."""
    return GraphQLObjectType(name, lambda: fields)


def _field_with_resolver(resolver) -> GraphQLField:
    """Return a GraphQLString field with the given resolver attached."""
    return GraphQLField(GraphQLString, resolve=resolver)


# ---------------------------------------------------------------------------
# 1. Hard-fail on a live/hand-written resolver (no sentinel)
# ---------------------------------------------------------------------------


def test_live_resolver_rejected_at_build():
    """A field with a hand-written resolver (lacking _gdx_pure_projection) must
    raise a build-time error naming the type and field."""

    def live_resolver(root, info):
        return root.get("name")  # hand-written — no sentinel

    gql_type = _make_type(
        "EventType",
        {"name": _field_with_resolver(live_resolver)},
    )
    with pytest.raises(Exception, match="EventType") as exc_info:
        check_subscription_output_type(gql_type)

    # Error message must name the field too
    assert "name" in str(exc_info.value)


# ---------------------------------------------------------------------------
# 2. Pass a flat type with sentinel-marked resolvers
# ---------------------------------------------------------------------------


def test_snake_closure_with_sentinel_passes():
    """All fields have a make_snake_resolver closure (sentinel=True) — no raise."""
    gql_type = _make_type(
        "EventType",
        {
            "isActive": _field_with_resolver(make_snake_resolver("is_active")),
            "dateJoined": _field_with_resolver(make_snake_resolver("date_joined")),
        },
    )
    # Must not raise
    check_subscription_output_type(gql_type)


# ---------------------------------------------------------------------------
# 3. Reject an unmarked closure (sentinel check, NOT shape/identity)
# ---------------------------------------------------------------------------


def test_snake_closure_missing_sentinel_rejected():
    """A closure that LOOKS like a snake resolver but lacks the sentinel is
    rejected — proves the guard checks the sentinel, not closure shape."""

    # Same shape as make_snake_resolver, but NO sentinel attribute
    unmarked = lambda root, _info, *, _name="is_active": (  # noqa: E731
        root.get(_name) if isinstance(root, dict) else getattr(root, _name, None)
    )
    # Confirm there is NO sentinel
    assert not getattr(unmarked, "_gdx_pure_projection", False)

    gql_type = _make_type(
        "EventType",
        {"isActive": _field_with_resolver(unmarked)},
    )
    with pytest.raises(Exception, match="EventType"):
        check_subscription_output_type(gql_type)


# ---------------------------------------------------------------------------
# 4. Reject resolve=None
# ---------------------------------------------------------------------------


def test_none_resolver_rejected():
    """A field with resolve=None (no resolver set) must be rejected."""
    # When no resolver is set, field.resolve is None
    gql_type = _make_type(
        "EventType",
        {"name": GraphQLField(GraphQLString)},  # resolve defaults to None
    )
    # Confirm field.resolve is actually None
    assert gql_type.fields["name"].resolve is None

    with pytest.raises(Exception, match="EventType"):
        check_subscription_output_type(gql_type)


# ---------------------------------------------------------------------------
# 5. Reject resolve=default_field_resolver
# ---------------------------------------------------------------------------


def test_default_field_resolver_rejected():
    """A field with the graphql-core default_field_resolver must be rejected —
    it keys by camelCase wire name, not snake, causing silent NULL."""
    gql_type = _make_type(
        "EventType",
        {"name": _field_with_resolver(default_field_resolver)},
    )
    with pytest.raises(Exception, match="EventType"):
        check_subscription_output_type(gql_type)


# ---------------------------------------------------------------------------
# 6. Type-level escape hatch bypasses guard
# ---------------------------------------------------------------------------


def test_type_level_escape_hatch_bypasses_guard():
    """If the TYPE carries ``_gdx_pure_projection=True`` the guard is bypassed
    entirely — no raise, even though the field has a live resolver."""

    def live_resolver(root, info):
        return root.get("name")

    gql_type = _make_type(
        "EventType",
        {"name": _field_with_resolver(live_resolver)},
    )
    # Set type-level escape hatch
    gql_type._gdx_pure_projection = True  # type: ignore[attr-defined]

    # Must NOT raise
    check_subscription_output_type(gql_type)


# ---------------------------------------------------------------------------
# 7. check_subscription_schema: walks multiple subscription output types
# ---------------------------------------------------------------------------


def test_check_subscription_schema_rejects_bad_type():
    """check_subscription_schema raises when any subscription output type has
    a field lacking the sentinel."""
    from graphql import GraphQLSchema

    def live_resolver(root, info):
        return root.get("id")

    event_type = _make_type(
        "MyEventType",
        {"id": _field_with_resolver(live_resolver)},
    )

    # Build a minimal schema with a subscription type that exposes event_type
    subscription_type = GraphQLObjectType(
        "Subscription",
        lambda: {
            "myEvent": GraphQLField(
                event_type,
                resolve=lambda root, info: root,
            )
        },
    )
    schema = GraphQLSchema(subscription=subscription_type)

    with pytest.raises(Exception, match="MyEventType"):
        check_subscription_schema(schema)


def test_check_subscription_schema_passes_clean_schema():
    """check_subscription_schema passes when all subscription output types are clean."""
    from graphql import GraphQLSchema

    event_type = _make_type(
        "CleanEvent",
        {
            "name": _field_with_resolver(make_snake_resolver("name")),
        },
    )

    subscription_type = GraphQLObjectType(
        "Subscription",
        lambda: {
            "myEvent": GraphQLField(
                event_type,
                resolve=lambda root, info: root,
            )
        },
    )
    schema = GraphQLSchema(subscription=subscription_type)

    # Must not raise
    check_subscription_schema(schema)
