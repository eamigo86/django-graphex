# -*- coding: utf-8 -*-
"""Prune-transform tests (P1): "core.schema_pruner.prune_schema(full, granted)".

Rebuilds the reachable-from-roots closure of a labeled schema, omitting any
field whose extensions["gdx_required_perms"] are not all held by "granted".

Coverage:
- field removal by required-perms vs granted-perms; untagged fields survive
- distinct type identity (the transform is PURE — never mutates the source)
- transitive type removal (a type reachable only via an omitted field is gone)
- empty-type cascade to a fixpoint (a 0-field type is dropped, and so are the
  fields / union members / that referenced it)
- subscription action ENUM-VALUE pruning (partial perms drop ALL_ACTIONS; no
  permitted action removes the whole subscription field)
- every pruned variant passes graphql-core "validate_schema" (hard gate)
- a pruned field yields a "Cannot query field" not-found (not an authz error,
  no existence leak)
"""

from __future__ import annotations

from typing import Any

import pytest
from graphql import (
    GraphQLArgument,
    GraphQLEnumType,
    GraphQLEnumValue,
    GraphQLField,
    GraphQLInputField,
    GraphQLInputObjectType,
    GraphQLInterfaceType,
    GraphQLNonNull,
    GraphQLObjectType,
    GraphQLSchema,
    GraphQLString,
    GraphQLUnionType,
    parse,
    validate,
    validate_schema,
)

from django_graphex.core.schema_pruner import prune_schema

# --------------------------------------------------------------------------- #
# Hand-built labeled schemas (full control over labels + cascade shapes).
# Perms are opaque codename strings; ``prune_schema`` only does set arithmetic.
# --------------------------------------------------------------------------- #
_VIEW_PUB = "app.view_pub"
_VIEW_SECRET = "app.view_secret"
_ADD = "app.add_thing"
_CHANGE = "app.change_thing"
_DELETE = "app.delete_thing"
_VIEW = "app.view_thing"


def _labeled(gql_field: GraphQLField, perms: Any) -> GraphQLField:
    """Stamp "gdx_required_perms" on "gql_field" (mirrors the P0 stamp idiom).

    Args:
        gql_field: The field to annotate, in place.
        perms: The permission requirement to stamp — a frozenset for a
            simple field, or a per-action dict for a subscription field.

    Returns:
        gql_field: The same field instance, for chaining at the call site.
    """
    gql_field.extensions = {
        **(gql_field.extensions or {}),
        "gdx_required_perms": perms,
    }
    return gql_field


def _simple_schema() -> GraphQLSchema:
    """Build a query with a public, an untagged, and a perm-gated secret field.

    The "secret" field's type "Secret" is reachable ONLY via that field.

    Returns:
        schema: The assembled labeled schema.
    """
    secret_type = GraphQLObjectType("Secret", {"code": GraphQLField(GraphQLString)})
    query = GraphQLObjectType(
        "Query",
        {
            "public": _labeled(GraphQLField(GraphQLString), frozenset({_VIEW_PUB})),
            "untagged": GraphQLField(GraphQLString),  # no extension -> public
            "secret": _labeled(GraphQLField(secret_type), frozenset({_VIEW_SECRET})),
        },
    )
    return GraphQLSchema(
        query=query, extensions={"gdx_label_set": frozenset({_VIEW_PUB, _VIEW_SECRET})}
    )


def _sub_action_enum() -> GraphQLEnumType:
    """Build the CREATE/UPDATE/DELETE/ALL_ACTIONS subscription action enum.

    Returns:
        enum: The "ThingSubscriptionAction" enum type.
    """
    return GraphQLEnumType(
        "ThingSubscriptionAction",
        {
            "CREATE": GraphQLEnumValue("create"),
            "UPDATE": GraphQLEnumValue("update"),
            "DELETE": GraphQLEnumValue("delete"),
            "ALL_ACTIONS": GraphQLEnumValue("all_actions"),
        },
    )


def _subscription_schema() -> GraphQLSchema:
    """Build a schema whose Subscription carries per-action perms and an enum arg.

    The Subscription root has one "thing" field carrying the per-action
    perms dict and an "action" enum argument
    (CREATE/UPDATE/DELETE/ALL_ACTIONS).

    Returns:
        schema: The assembled labeled schema.
    """
    event_type = GraphQLObjectType("ThingEvent", {"id": GraphQLField(GraphQLString)})
    query = GraphQLObjectType(
        "Query",
        {"ping": _labeled(GraphQLField(GraphQLString), frozenset({_VIEW}))},
    )
    thing_field = GraphQLField(
        event_type,
        args={
            "action": GraphQLArgument(GraphQLNonNull(_sub_action_enum())),
        },
    )
    thing_field = _labeled(
        thing_field,
        {
            "create": frozenset({_VIEW, _ADD}),
            "update": frozenset({_VIEW, _CHANGE}),
            "delete": frozenset({_VIEW, _DELETE}),
            "all_actions": frozenset({_VIEW, _ADD, _CHANGE, _DELETE}),
        },
    )
    subscription = GraphQLObjectType("Subscription", {"thing": thing_field})
    return GraphQLSchema(
        query=query,
        subscription=subscription,
        extensions={"gdx_label_set": frozenset({_VIEW, _ADD, _CHANGE, _DELETE})},
    )


# --------------------------------------------------------------------------- #
# 1.1 — field removal / retention / purity
# --------------------------------------------------------------------------- #
def test_forbidden_field_removed() -> None:
    """Assert a field whose required perms are not granted is removed.

    If this fails, a caller lacking the required permission would still
    see the gated field in the pruned schema.
    """
    full = _simple_schema()
    granted = frozenset({_VIEW_PUB})  # lacks view_secret
    pruned = prune_schema(full, granted)
    assert "secret" not in pruned.query_type.fields
    assert "public" in pruned.query_type.fields


def test_untagged_field_retained_for_every_grant_set() -> None:
    """Assert an untagged field survives pruning regardless of granted perms.

    If this fails, a field with no "gdx_required_perms" extension would
    be treated as gated instead of public.
    """
    full = _simple_schema()
    for granted in (frozenset(), frozenset({_VIEW_PUB}), frozenset({_VIEW_SECRET})):
        pruned = prune_schema(full, granted)
        assert "untagged" in pruned.query_type.fields


def test_field_kept_when_all_perms_held() -> None:
    """Assert a gated field is kept when every required perm is granted.

    If this fails, a fully permissioned caller would still lose access
    to a field it is entitled to see.
    """
    full = _simple_schema()
    pruned = prune_schema(full, frozenset({_VIEW_PUB, _VIEW_SECRET}))
    assert "secret" in pruned.query_type.fields


def test_transform_is_pure_distinct_type_identity() -> None:
    """Assert pruning never mutates the source schema and returns distinct clones.

    If this fails, "prune_schema" would mutate the caller's original
    schema in place, corrupting it for any other consumer sharing the
    same full schema instance.
    """
    full = _simple_schema()
    full_secret = full.type_map.get("Secret")
    pruned = prune_schema(full, frozenset({_VIEW_PUB, _VIEW_SECRET}))
    # Source schema is untouched: still has all fields.
    assert set(full.query_type.fields) == {"public", "untagged", "secret"}
    # Pruned Query is a DISTINCT object (no shared identity / mutation).
    assert pruned.query_type is not full.query_type
    # A type present in both is a distinct clone, never the same instance.
    if full_secret is not None and "Secret" in pruned.type_map:
        assert pruned.type_map["Secret"] is not full_secret


def test_empty_grant_set_keeps_only_public_untagged() -> None:
    """Assert an empty grant set prunes down to only the untagged field.

    If this fails, a caller with no permissions at all would either see
    gated fields it should not, or lose the untagged public field too.
    """
    full = _simple_schema()
    pruned = prune_schema(full, frozenset())
    assert set(pruned.query_type.fields) == {"untagged"}


# --------------------------------------------------------------------------- #
# 1.2 — transitive removal + empty-type cascade (fixpoint)
# --------------------------------------------------------------------------- #
def test_transitive_type_removal() -> None:
    """Assert a type reachable only via a removed field is also removed.

    "Secret" was reachable ONLY via the removed "secret" field.

    If this fails, a type that is no longer reachable from any surviving
    field would still linger in the pruned type map.
    """
    full = _simple_schema()
    pruned = prune_schema(full, frozenset({_VIEW_PUB}))  # secret dropped
    # ``Secret`` was reachable ONLY via the removed ``secret`` field.
    assert "Secret" not in pruned.type_map


def test_transitive_type_retained_when_field_kept() -> None:
    """Assert a type stays in the pruned map when its referencing field survives.

    If this fails, a type would be dropped even though the field that
    references it is still present in the pruned schema.
    """
    full = _simple_schema()
    pruned = prune_schema(full, frozenset({_VIEW_PUB, _VIEW_SECRET}))
    assert "Secret" in pruned.type_map


def test_empty_type_cascade_drops_zero_field_type() -> None:
    """Assert a type reduced to zero fields cascades away along with its referrer.

    "Wrapper" exposes only a perm-gated "inner" field; when pruned it has
    0 fields and MUST be removed, and the "wrap" field that referenced it
    too.

    If this fails, a type left with zero fields after pruning would
    remain in the schema (producing an invalid, empty GraphQL type)
    instead of cascading away along with the field that pointed to it.
    """
    inner_type = GraphQLObjectType("Inner", {"x": GraphQLField(GraphQLString)})
    wrapper = GraphQLObjectType(
        "Wrapper",
        {
            "inner": _labeled(GraphQLField(inner_type), frozenset({_VIEW_SECRET})),
        },
    )
    query = GraphQLObjectType(
        "Query",
        {
            "ok": _labeled(GraphQLField(GraphQLString), frozenset({_VIEW_PUB})),
            "wrap": GraphQLField(wrapper),  # untagged, but points at Wrapper
        },
    )
    full = GraphQLSchema(
        query=query,
        extensions={"gdx_label_set": frozenset({_VIEW_PUB, _VIEW_SECRET})},
    )
    pruned = prune_schema(full, frozenset({_VIEW_PUB}))  # inner dropped
    assert "Inner" not in pruned.type_map
    assert "Wrapper" not in pruned.type_map  # empty -> cascade removed
    assert "wrap" not in pruned.query_type.fields  # referencing field gone
    assert "ok" in pruned.query_type.fields
    assert not validate_schema(pruned)


def test_empty_union_member_cascade_drops_member_and_empty_union() -> None:
    """Assert an emptied-out union cascades: members, then the union, then its field.

    A union of two members; each member's only field is perm-gated. With
    no perms both members become empty -> dropped -> the union is empty
    -> the union field is removed. validate_schema MUST stay clean.

    If this fails, an emptied union (every member dropped) would either
    linger as an invalid zero-member union or leave a dangling field
    reference.
    """
    member_a = GraphQLObjectType(
        "MemA",
        {"a": _labeled(GraphQLField(GraphQLString), frozenset({_VIEW_SECRET}))},
    )
    member_b = GraphQLObjectType(
        "MemB",
        {"b": _labeled(GraphQLField(GraphQLString), frozenset({_VIEW_SECRET}))},
    )
    union = GraphQLUnionType("Poly", [member_a, member_b])
    query = GraphQLObjectType(
        "Query",
        {
            "ok": _labeled(GraphQLField(GraphQLString), frozenset({_VIEW_PUB})),
            "poly": GraphQLField(union),
        },
    )
    full = GraphQLSchema(
        query=query,
        extensions={"gdx_label_set": frozenset({_VIEW_PUB, _VIEW_SECRET})},
    )
    pruned = prune_schema(full, frozenset({_VIEW_PUB}))
    assert "MemA" not in pruned.type_map
    assert "MemB" not in pruned.type_map
    assert "Poly" not in pruned.type_map
    assert "poly" not in pruned.query_type.fields
    assert not validate_schema(pruned)


def test_union_keeps_surviving_members() -> None:
    """Assert a union keeps only its surviving members, dropping emptied ones.

    Member A survives (public), member B is perm-gated to empty. The
    union keeps only A; validate_schema must stay clean (no dangling B
    reference).

    If this fails, a union with a mix of surviving and emptied members
    would either drop the surviving member too, or leave a dangling
    reference to the dropped one.
    """
    member_a = GraphQLObjectType("MemA", {"a": GraphQLField(GraphQLString)})
    member_b = GraphQLObjectType(
        "MemB",
        {"b": _labeled(GraphQLField(GraphQLString), frozenset({_VIEW_SECRET}))},
    )
    union = GraphQLUnionType("Poly", [member_a, member_b])
    query = GraphQLObjectType(
        "Query",
        {"poly": GraphQLField(union)},
    )
    full = GraphQLSchema(
        query=query,
        extensions={"gdx_label_set": frozenset({_VIEW_SECRET})},
    )
    pruned = prune_schema(full, frozenset())
    assert "poly" in pruned.query_type.fields
    poly = pruned.type_map["Poly"]
    member_names = {t.name for t in poly.types}
    assert member_names == {"MemA"}
    assert "MemB" not in pruned.type_map
    assert not validate_schema(pruned)


def test_interface_field_pruned_but_interface_survives() -> None:
    """Assert pruning an implementer's gated field keeps the shared interface intact.

    An object implements an interface; a perm-gated field on the object
    is pruned but the shared interface field survives -> schema stays
    valid.

    If this fails, pruning a gated field on an interface implementer
    could either fail to remove it or would break the interface contract
    it shares with the object.
    """
    node = GraphQLInterfaceType("Node", {"id": GraphQLField(GraphQLString)})
    thing = GraphQLObjectType(
        "Thing",
        {
            "id": GraphQLField(GraphQLString),
            "secret": _labeled(GraphQLField(GraphQLString), frozenset({_VIEW_SECRET})),
        },
        interfaces=[node],
    )
    query = GraphQLObjectType("Query", {"thing": GraphQLField(thing)})
    full = GraphQLSchema(
        query=query,
        types=[thing],
        extensions={"gdx_label_set": frozenset({_VIEW_SECRET})},
    )
    pruned = prune_schema(full, frozenset())
    pruned_thing = pruned.type_map["Thing"]
    assert "secret" not in pruned_thing.fields
    assert "id" in pruned_thing.fields
    assert not validate_schema(pruned)


def test_named_enum_output_type_is_cloned_and_survives() -> None:
    """Assert a field's named enum output type is cloned through and kept reachable.

    A field whose OUTPUT type is a named enum (for example, a Django
    choices enum) must clone the enum through and keep it reachable in
    the pruned universe.

    If this fails, a surviving field returning an enum type would either
    lose its enum type from the pruned type map, or would share the same
    (mutated) instance as the source schema.
    """
    status_enum = GraphQLEnumType(
        "Status",
        {"OK": GraphQLEnumValue("ok"), "BAD": GraphQLEnumValue("bad")},
    )
    query = GraphQLObjectType(
        "Query",
        {
            "status": _labeled(GraphQLField(status_enum), frozenset({_VIEW_PUB})),
        },
    )
    full = GraphQLSchema(
        query=query, extensions={"gdx_label_set": frozenset({_VIEW_PUB})}
    )
    pruned = prune_schema(full, frozenset({_VIEW_PUB}))
    assert "status" in pruned.query_type.fields
    pruned_enum = pruned.type_map["Status"]
    assert pruned_enum is not status_enum  # distinct clone (purity)
    assert set(pruned_enum.values) == {"OK", "BAD"}
    assert not validate_schema(pruned)


def test_named_input_type_survives_for_kept_field_arg() -> None:
    """Assert a surviving field's named input-object argument type is preserved.

    A surviving field with a named input-object argument keeps the input
    type in the pruned universe (mutation payload precedent), cloned
    distinctly.

    If this fails, a surviving field's input-object argument type would
    either be dropped from the pruned type map or would share the same
    (mutated) instance as the source schema.
    """
    filter_input = GraphQLInputObjectType(
        "ThingFilter", {"text": GraphQLInputField(GraphQLString)}
    )
    query = GraphQLObjectType(
        "Query",
        {
            "things": _labeled(
                GraphQLField(
                    GraphQLString,
                    args={"where": GraphQLArgument(filter_input)},
                ),
                frozenset({_VIEW_PUB}),
            ),
        },
    )
    full = GraphQLSchema(
        query=query, extensions={"gdx_label_set": frozenset({_VIEW_PUB})}
    )
    pruned = prune_schema(full, frozenset({_VIEW_PUB}))
    assert "things" in pruned.query_type.fields
    pruned_input = pruned.type_map["ThingFilter"]
    assert pruned_input is not filter_input  # distinct clone (purity)
    assert "text" in pruned_input.fields
    assert not validate_schema(pruned)


# --------------------------------------------------------------------------- #
# 1.2b — interface implementers reachable ONLY through the interface
# --------------------------------------------------------------------------- #
def _interface_only_schema() -> GraphQLSchema:
    """A ``Node`` interface with two implementers (``Pub`` / ``Sec``) reachable
    ONLY via ``Query.node: Node`` — never returned directly by any field.

    graphql-core keeps only root-reachable types plus whatever is listed in
    ``types=``; without a ``types=`` forward the implementers vanish from the
    (pruned) type map even though the interface itself survives.
    """
    node = GraphQLInterfaceType("Node", {"id": GraphQLField(GraphQLString)})
    pub = GraphQLObjectType(
        "Pub",
        {
            "id": GraphQLField(GraphQLString),
            "pubName": GraphQLField(GraphQLString),
        },
        interfaces=[node],
    )
    sec = GraphQLObjectType(
        "Sec",
        {
            "id": GraphQLField(GraphQLString),
            "secName": GraphQLField(GraphQLString),
        },
        interfaces=[node],
    )
    query = GraphQLObjectType("Query", {"node": GraphQLField(node)})
    return GraphQLSchema(
        query=query,
        types=[pub, sec],  # implementers are ONLY reachable via the interface
        extensions={"gdx_label_set": frozenset()},
    )


def test_interface_only_implementers_survive_empty_grant_set() -> None:
    """Assert interface-only implementers survive pruning with an empty grant set.

    The exact confirmed regression: an interface whose implementers are
    reachable ONLY through it must keep those implementers after a
    prune with NO grants at all (no gated fields anywhere). The pruner
    must forward the surviving implementer clones via "types=" so
    possible_types is non-empty.

    If this fails, implementers reachable only via an interface (never
    returned directly by any field) would vanish from the pruned
    schema's type map, breaking fragment queries against the interface.
    """
    full = _interface_only_schema()
    pruned = prune_schema(full, frozenset())
    assert "Pub" in pruned.type_map
    assert "Sec" in pruned.type_map
    node = pruned.type_map["Node"]
    possible = {t.name for t in pruned.get_possible_types(node)}
    assert possible == {"Pub", "Sec"}


def test_interface_only_implementers_fragment_query_executes() -> None:
    """Assert a fragment spread on an interface-only implementer validates.

    A fragment spread on the interface-only implementer must not error
    with "Unknown type 'Pub'": the type must exist in the pruned schema.

    If this fails, querying via an inline fragment on an interface-only
    implementer would fail validation because the type is missing from
    the pruned schema.
    """
    full = _interface_only_schema()
    pruned = prune_schema(full, frozenset())
    doc = parse("{ node { ... on Pub { pubName } ... on Sec { secName } } }")
    assert validate(pruned, doc) == []


def test_interface_only_implementers_validate_clean() -> None:
    """Assert the interface-only-implementers schema validates cleanly.

    If this fails, forwarding interface-only implementers via "types="
    would introduce a schema-validation error instead of a clean pruned
    schema.
    """
    full = _interface_only_schema()
    pruned = prune_schema(full, frozenset())
    assert validate_schema(pruned) == []


def _interface_gated_implementer_schema() -> GraphQLSchema:
    """A ``Node`` interface with two implementers reachable only via it. ``Sec``
    carries an extra perm-gated field ``secName`` on top of a public ``label``;
    ``Pub`` is fully public.
    """
    node = GraphQLInterfaceType("Node", {"id": GraphQLField(GraphQLString)})
    pub = GraphQLObjectType(
        "Pub",
        {
            "id": GraphQLField(GraphQLString),
            "pubName": GraphQLField(GraphQLString),
        },
        interfaces=[node],
    )
    sec = GraphQLObjectType(
        "Sec",
        {
            "id": GraphQLField(GraphQLString),
            "label": GraphQLField(GraphQLString),  # public
            "secName": _labeled(  # gated
                GraphQLField(GraphQLString), frozenset({_VIEW_SECRET})
            ),
        },
        interfaces=[node],
    )
    query = GraphQLObjectType("Query", {"node": GraphQLField(node)})
    return GraphQLSchema(
        query=query,
        types=[pub, sec],
        extensions={"gdx_label_set": frozenset({_VIEW_SECRET})},
    )


def test_interface_only_gated_field_pruned_type_still_survives() -> None:
    """Assert an implementer with a gated field still survives via its public fields.

    Gating one implementer's field the user lacks removes THAT field,
    but the implementer (which still has public fields) stays a
    possible type; the types= forward must carry only SURVIVORS'
    clones, not force-keep empties.

    If this fails, an implementer with a mix of gated and public fields
    would either be dropped entirely or would keep the gated field it
    should lose.
    """
    full = _interface_gated_implementer_schema()
    pruned = prune_schema(full, frozenset())  # lacks view_secret
    assert "Pub" in pruned.type_map
    assert "Sec" in pruned.type_map
    pruned_sec = pruned.type_map["Sec"]
    assert "secName" not in pruned_sec.fields  # gated field gone
    assert "label" in pruned_sec.fields  # public field kept
    node = pruned.type_map["Node"]
    possible = {t.name for t in pruned.get_possible_types(node)}
    assert possible == {"Pub", "Sec"}
    assert validate_schema(pruned) == []


def test_interface_only_fully_gated_implementer_dropped_not_forced_kept() -> None:
    """Assert a fully emptied implementer is dropped, not resurrected via types=.

    An implementer whose EVERY non-interface field is gated away
    becomes empty under the survivor fixpoint. "types=" must forward
    ONLY survivors, so a dropped implementer must NOT be resurrected
    into the type map.

    If this fails, forwarding interface implementers via "types=" would
    force-keep a fully emptied implementer instead of letting it cascade
    away.
    """
    node = GraphQLInterfaceType("Node", {"id": GraphQLField(GraphQLString)})
    pub = GraphQLObjectType(
        "Pub",
        {"id": GraphQLField(GraphQLString), "pubName": GraphQLField(GraphQLString)},
        interfaces=[node],
    )
    # ``Sec`` has ONLY the interface ``id`` field left after the interface is
    # implemented, plus a gated ``secName``. A type surviving needs a field that
    # survives; ``id`` here is public so ``Sec`` still survives. To force EMPTY
    # we gate its only non-interface field AND drop ``id`` from the object side.
    sec = GraphQLObjectType(
        "Sec",
        {"secName": _labeled(GraphQLField(GraphQLString), frozenset({_VIEW_SECRET}))},
        interfaces=[node],
    )
    query = GraphQLObjectType("Query", {"node": GraphQLField(node)})
    full = GraphQLSchema(
        query=query,
        types=[pub, sec],
        extensions={"gdx_label_set": frozenset({_VIEW_SECRET})},
    )
    pruned = prune_schema(full, frozenset())  # Sec becomes 0-field -> dropped
    assert "Pub" in pruned.type_map
    assert "Sec" not in pruned.type_map  # survivors-only: NOT force-kept
    node_t = pruned.type_map["Node"]
    possible = {t.name for t in pruned.get_possible_types(node_t)}
    assert possible == {"Pub"}
    assert validate_schema(pruned) == []


# --------------------------------------------------------------------------- #
# 1.3 — subscription enum-value pruning
# --------------------------------------------------------------------------- #
def _action_enum_values(pruned: GraphQLSchema) -> set[str]:
    sub = pruned.subscription_type
    action_arg = sub.fields["thing"].args["action"]
    enum = action_arg.type
    # unwrap NonNull
    enum = getattr(enum, "of_type", enum)
    return set(enum.values)


def test_partial_perms_drop_all_actions() -> None:
    """Assert holding only some write perms drops ALL_ACTIONS and the missing verbs.

    If this fails, a caller entitled to only a subset of subscription
    actions would still see ALL_ACTIONS or actions it cannot perform in
    the pruned enum.
    """
    full = _subscription_schema()
    # Permitted only subscribe CREATE (view + add).
    granted = frozenset({_VIEW, _ADD})
    pruned = prune_schema(full, granted)
    assert "thing" in pruned.subscription_type.fields
    values = _action_enum_values(pruned)
    assert "CREATE" in values
    assert "ALL_ACTIONS" not in values
    assert "UPDATE" not in values
    assert "DELETE" not in values


def test_all_actions_kept_when_all_permitted() -> None:
    """Assert every action enum value survives when all write perms are granted.

    If this fails, a fully permissioned caller would still lose access
    to one or more subscription action enum values.
    """
    full = _subscription_schema()
    granted = frozenset({_VIEW, _ADD, _CHANGE, _DELETE})
    pruned = prune_schema(full, granted)
    values = _action_enum_values(pruned)
    assert values == {"CREATE", "UPDATE", "DELETE", "ALL_ACTIONS"}


def test_no_permitted_action_removes_subscription_field() -> None:
    """Assert holding no write perm removes the whole subscription field and cascades.

    The whole subscription field is gone; with no surviving subscription
    field the (now empty) Subscription root cascades away entirely, and
    the now-unreachable event type too.

    If this fails, a caller with view-only access would still see a
    (now action-less) subscription field, or the cascade would fail to
    remove the emptied Subscription root and its event type.
    """
    full = _subscription_schema()
    granted = frozenset({_VIEW})  # no write verb -> no permitted action
    pruned = prune_schema(full, granted)
    # The whole subscription field is gone; with no surviving subscription field
    # the (now empty) Subscription root cascades away entirely, and the
    # now-unreachable event type too.
    assert pruned.subscription_type is None
    assert "ThingEvent" not in pruned.type_map
    # The rest of the schema stays valid and the public query field survives.
    assert "ping" in pruned.query_type.fields
    assert not validate_schema(pruned)


def test_subscription_variants_validate_clean() -> None:
    """Assert every combination of granted write perms yields a valid schema.

    If this fails, some combination of granted subscription-related
    permissions would produce a pruned schema that fails graphql-core's
    schema validation.
    """
    full = _subscription_schema()
    for granted in (
        frozenset({_VIEW}),
        frozenset({_VIEW, _ADD}),
        frozenset({_VIEW, _CHANGE}),
        frozenset({_VIEW, _DELETE}),
        frozenset({_VIEW, _ADD, _CHANGE}),
        frozenset({_VIEW, _ADD, _CHANGE, _DELETE}),
    ):
        pruned = prune_schema(full, granted)
        assert not validate_schema(pruned), f"granted={granted}"


# --------------------------------------------------------------------------- #
# 1.4 — validate_schema hard gate + not-found (no existence leak)
# --------------------------------------------------------------------------- #
def test_validate_schema_clean_across_grant_sets() -> None:
    """Assert every grant-set combination for the simple schema validates cleanly.

    If this fails, some combination of granted permissions would
    produce a pruned schema that fails graphql-core's schema validation.
    """
    full = _simple_schema()
    for granted in (
        frozenset(),
        frozenset({_VIEW_PUB}),
        frozenset({_VIEW_SECRET}),
        frozenset({_VIEW_PUB, _VIEW_SECRET}),
    ):
        pruned = prune_schema(full, granted)
        errors = validate_schema(pruned)
        assert errors == [], f"granted={granted} -> {errors}"


def test_pruned_field_query_is_cannot_query_field_not_authz() -> None:
    """Assert querying a pruned field fails as not-found, never as an authz denial.

    If this fails, a pruned field would leak its existence through an
    authorization-flavored error message instead of a plain
    field-not-found validation error.
    """
    full = _simple_schema()
    pruned = prune_schema(full, frozenset({_VIEW_PUB}))  # secret removed
    doc = parse("{ secret { code } }")
    errors = validate(pruned, doc)
    assert errors, "expected a validation error for the pruned field"
    messages = " ".join(e.message for e in errors)
    assert "Cannot query field" in messages
    # No existence leak: the error is a not-found, never an authz denial.
    assert "permission" not in messages.lower()
    assert "denied" not in messages.lower()
    assert "forbidden" not in messages.lower()


def test_public_field_still_queryable_after_prune() -> None:
    """Assert public and untagged fields remain queryable after pruning.

    If this fails, pruning would incorrectly remove or break validation
    for fields that were never gated in the first place.
    """
    full = _simple_schema()
    pruned = prune_schema(full, frozenset({_VIEW_PUB}))
    doc = parse("{ public untagged }")
    assert validate(pruned, doc) == []


# --------------------------------------------------------------------------- #
# 1.4 — integration against a REAL compiled labeled schema (many grant sets)
# --------------------------------------------------------------------------- #
def test_real_compiled_schema_prunes_and_validates() -> None:
    """Assert a real compiled schema prunes and validates across grant sets.

    If this fails, "prune_schema" would break down against a real
    compiled "DjangoGraphQLSchema" (as opposed to the hand-built test
    fixtures above), producing an invalid schema for some combination of
    granted permissions.
    """
    # Requires the "subscriptions" extra: the exercised runtime mounts
    # channels; skip in the channels-free base-install CI env.
    pytest.importorskip("channels")
    from django_graphex.core import ObjectType, field
    from django_graphex.core.registry_compiler import compile_all_outputs
    from django_graphex.mutation import DjangoModelMutation
    from django_graphex.schema import DjangoGraphQLSchema
    from django_graphex.types import DjangoModelType

    from .models import HookModel

    class _HookType(DjangoModelType):
        class Meta:
            model = HookModel
            stream = "hookpruned"
            filter_fields = {"id": ("exact",), "text": ("exact", "icontains")}

    class _HookMut(DjangoModelMutation):
        class Meta:
            model = HookModel

    class _Query(ObjectType):
        hook = _HookType.RetrieveField()
        hooks = _HookType.ListField()
        server_time = field(GraphQLString)  # untagged -> public

    class _Mutation(ObjectType):
        create_hook = _HookMut.CreateField()

    class _Subscription(ObjectType):
        hook = _HookType.SubscriptionField()

    compile_all_outputs()
    full = DjangoGraphQLSchema(
        query=_Query, mutation=_Mutation, subscription=_Subscription
    ).graphql_schema

    view = "tests.view_hookmodel"
    add = "tests.add_hookmodel"
    change = "tests.change_hookmodel"
    delete = "tests.delete_hookmodel"
    for granted in (
        frozenset(),
        frozenset({view}),
        frozenset({view, add}),
        frozenset({view, add, change, delete}),
        frozenset({add}),  # missing view -> nothing readable
    ):
        pruned = prune_schema(full, granted)
        assert validate_schema(pruned) == [], f"granted={granted}"

    # With only ``view`` the untagged public field survives and read fields show.
    pruned_view = prune_schema(full, frozenset({view}))
    assert "serverTime" in pruned_view.query_type.fields
    assert "hook" in pruned_view.query_type.fields
    # Source schema untouched.
    assert "createHook" in full.mutation_type.fields
