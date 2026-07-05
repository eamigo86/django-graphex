# -*- coding: utf-8 -*-
"""WU3 — COND-B build-time flat-type guard.

Design paragraph 5 (COND-B): at schema build time, for every subscription
output (event) type, assert that EVERY field's resolve is a sentinel-marked
snake-closure. Hard-fail on any field whose resolve is MISSING the sentinel,
is None, or is "default_field_resolver".

Key design decision: the check is "_gdx_pure_projection" SENTINEL PRESENCE,
NOT identity against "default_field_resolver". Identity-checking
"default_field_resolver" would re-admit the silent-null combo (a snake payload
with a camelCase-keying default resolver). A snake-closure-shaped fn that LACKS
the sentinel must ALSO be rejected.

Type-level escape hatch: if the TYPE itself carries "_gdx_pure_projection"
(e.g. "some_type._gdx_pure_projection = True"), the guard is bypassed for
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
    GraphQLFieldResolver,
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


def _make_type(name: str, fields: dict[str, GraphQLField]) -> GraphQLObjectType:
    """Build a GraphQLObjectType with the given fields dict.

    Args:
        name: The name to give the constructed GraphQL object type.
        fields: The field-name to GraphQLField mapping for the type.

    Returns:
        gql_type: The assembled GraphQLObjectType, built with a thunk so
            forward references between test types are supported.
    """
    return GraphQLObjectType(name, lambda: fields)


def _field_with_resolver(resolver: GraphQLFieldResolver | None) -> GraphQLField:
    """Return a GraphQLString field with the given resolver attached.

    Args:
        resolver: The resolver callable to attach to the field, or None to
            leave it unresolved.

    Returns:
        field: The constructed GraphQLField.
    """
    return GraphQLField(GraphQLString, resolve=resolver)


# ---------------------------------------------------------------------------
# 1. Hard-fail on a live/hand-written resolver (no sentinel)
# ---------------------------------------------------------------------------


def test_live_resolver_rejected_at_build() -> None:
    """A hand-written resolver lacking "_gdx_pure_projection" must raise at build time.

    Contract: the COND-B guard ships broken if it does not name both the
    offending type and field in the error it raises.
    """

    def live_resolver(root: dict[str, object], info: object) -> object:
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


def test_snake_closure_with_sentinel_passes() -> None:
    """A type whose every field carries a sentinel-marked snake closure must pass.

    Contract: this test ships broken if a legitimately generated
    make_snake_resolver closure is rejected by the guard.
    """
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


def test_snake_closure_missing_sentinel_rejected() -> None:
    """A closure shaped like a snake resolver but lacking the sentinel must be rejected.

    Contract: proves the guard checks sentinel presence, not closure shape —
    ships broken if a look-alike closure without "_gdx_pure_projection" is
    silently accepted.
    """

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


def test_none_resolver_rejected() -> None:
    """A field with resolve=None must be rejected by the build-time guard.

    Contract: this test ships broken if a field with no resolver set at all
    slips through the guard instead of raising.
    """
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


def test_default_field_resolver_rejected() -> None:
    """A field using graphql-core's default_field_resolver must be rejected.

    Contract: the silent-null bug ships broken if a field left on the
    camelCase-keying default_field_resolver is not caught by the guard.
    """
    gql_type = _make_type(
        "EventType",
        {"name": _field_with_resolver(default_field_resolver)},
    )
    with pytest.raises(Exception, match="EventType"):
        check_subscription_output_type(gql_type)


# ---------------------------------------------------------------------------
# 6. Type-level escape hatch bypasses guard
# ---------------------------------------------------------------------------


def test_type_level_escape_hatch_bypasses_guard() -> None:
    """A type-level "_gdx_pure_projection=True" must bypass the guard entirely.

    Contract: the advanced-user escape hatch ships broken if the guard still
    raises on a live resolver field once the type opts out.
    """

    def live_resolver(root: dict[str, object], info: object) -> object:
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


def test_check_subscription_schema_rejects_bad_type() -> None:
    """ "check_subscription_schema" must raise when any output type has an unmarked field.

    Contract: the schema-wide walk ships broken if it misses a subscription
    output type whose field lacks the sentinel, letting a silent-null field
    reach production.
    """
    from graphql import GraphQLSchema

    def live_resolver(root: dict[str, object], info: object) -> object:
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


def test_check_subscription_schema_passes_clean_schema() -> None:
    """ "check_subscription_schema" must pass when every output type is clean.

    Contract: this test ships broken if the schema-wide walk raises a false
    positive against a fully sentinel-marked subscription schema.
    """
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
