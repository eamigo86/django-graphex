# -*- coding: utf-8 -*-
"""WU7 — deliverable-pk subscription event type + DjangoModelType auto-gen.

The native subscription EVENT type carries EVERY "backend.output_field_names()"
entry with the DELIVERABLE native type the serialize-once flat-pk payload
("native/backend.py:to_representation") actually carries:

  * scalars with the Phase-5 native NAMES + nullability ("id: ID!"; model
    scalars NULLABLE; Date -> CustomDate / DateTime ->
    CustomDateTime / UUID -> UUID / JSON -> JSONString /
    Decimal -> Float — matching "native/output_compiler" /
    "native/scalars"),
  * FK / O2O -> the related model's pk SCALAR ("author: ID"), NOT the DB-backed
    nested output type — the flat payload carries the FK as the pk int under key
    "<field.name>" ("getattr(obj, '<name>_id')"),
  * M2M / reverse to-many -> a LIST of pk scalars ("coAuthors: [ID]"), NOT the
    results/totalCount container — the flat payload carries the M2M as a list of
    pks under key "<field.name>" ("list(... values_list('pk', flat=True))").

DESIGN RECONCILIATION (#1432 paragraphs 3 vs 8): paragraph 8's "event type SDL
byte-identical to the DjangoObjectType OUTPUT type" goal is a CATEGORY ERROR
vs paragraph 3's flat-pk serialize-once payload — the output type's FK/M2M are
DB-backed nested types, so a serialize-once event (one serialize feeds N
subscribers with ZERO DB per subscriber) CANNOT deliver them without a
per-subscriber DB query (the N+1 cliff serialize-once forbids). The
DELIVERABLE parity reference is what "to_representation" carries: FK -> pk
scalar, M2M -> pk-list.

Every event field still carries a WU1 "make_snake_resolver" closure (sentinel
"_gdx_pure_projection" so COND-B / "guard.py" whitelists it) keyed by the
SNAKE payload key "to_representation" writes ("field.name" for every kind);
the event type carries "extensions['gdx']"; "check_subscription_output_type"
(COND-B) is run AFTER attaching the sentinels and MUST pass (all fields
sentinel-marked).

The DjangoModelType auto-gen ("types.py" "subscription_type" /
"SubscriptionField") targets the native compile path
and the native field compiles through "compile_native_root"'s subscription-root
path ("schema.py"), so a native schema assembles the Subscription type
end-to-end and executes serialize-once.
"""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING, Any

import pytest

pytest.importorskip("channels")

from channels.layers import InMemoryChannelLayer  # noqa: E402
from graphql import (  # noqa: E402
    GraphQLID,
    GraphQLInt,
    GraphQLList,
    GraphQLNonNull,
    GraphQLObjectType,
    GraphQLString,
    parse,
)

# ---------------------------------------------------------------------------
# Helpers.
#
# Node types are registered ONCE at module scope: a DjangoObjectType is
# identity-stable (one canonical GraphQLObjectType per class in the shared output
# registry). Re-registering per-test would create multiple AuthorT/TagT instances
# polluting the shared registry — the FK nested type and the M2M container's
# results element would then resolve to DIFFERENT instances, tripping graphql-core's
# "uniquely named types" guard. Real usage defines node types once, so module-scope
# registration mirrors production.
# ---------------------------------------------------------------------------
from django_graphex.types import DjangoObjectType as _DOT
from tests.models import Author, Category, Post, Tag  # noqa: E402

if TYPE_CHECKING:
    from django_graphex.subscriptions import Subscription


class TagT(_DOT):
    """Module-scoped output node type for the Tag model.

    Registered once at import time so the shared output registry keeps a
    single canonical GraphQLObjectType instance for Tag.
    """

    class Meta:
        """Binds this node type to the Tag model.

        No other options are set; the default output field set is used.
        """

        model = Tag


class CategoryT(_DOT):
    """Module-scoped output node type for the Category model.

    Registered once at import time so the shared output registry keeps a
    single canonical GraphQLObjectType instance for Category.
    """

    class Meta:
        """Binds this node type to the Category model.

        No other options are set; the default output field set is used.
        """

        model = Category


class AuthorT(_DOT):
    """Module-scoped output node type for the Author model.

    Registered once at import time so the shared output registry keeps a
    single canonical GraphQLObjectType instance for Author.
    """

    class Meta:
        """Binds this node type to the Author model.

        No other options are set; the default output field set is used.
        """

        model = Author


class PostT(_DOT):
    """Module-scoped output node type for the Post model.

    Registered once at import time so the shared output registry keeps a
    single canonical GraphQLObjectType instance for Post, matching the FK
    and M2M nested types used by AuthorT/TagT.
    """

    class Meta:
        """Binds this node type to the Post model.

        No other options are set; the default output field set is used.
        """

        model = Post


def _register_post_node_types() -> type[_DOT]:
    """Return the module-scoped PostT node class (registered once at import).

    Returns:
        PostT: The module-level DjangoObjectType subclass for Post.
    """
    return PostT


def _make_subscription(**meta: Any) -> type["Subscription"]:
    """Build a fresh "PostSubscription" (native base, S6e re-parent).

    "Subscription" is now a pydantic ModelMetaclass type (S6e); a 3-arg
    type(name, bases, ns) build must inject __module__/__qualname__
    (and re-stamp the nested Meta qualname) or pydantic's
    inspect_namespace raises KeyError('__module__') — mirroring the
    production "DjangoModelType.subscription_type" builder.

    Args:
        meta: Extra attributes merged into the generated Meta class (model
            and stream are always set; overrides here win).

    Returns:
        PostSubscription: The freshly created Subscription subclass.
    """
    from django_graphex.subscriptions import Subscription

    meta_cls = type("Meta", (), {"model": Post, "stream": "posts", **meta})
    meta_cls.__qualname__ = "PostSubscription.Meta"
    meta_cls.__module__ = __name__
    return type(
        "PostSubscription",
        (Subscription,),
        {"__module__": __name__, "__qualname__": "PostSubscription", "Meta": meta_cls},
    )


def _notify(
    group: str, data: dict[str, Any], *, action: str = "create", pk: int = 1
) -> dict[str, Any]:
    """Build a channel-layer "subscription.notify" message envelope.

    Args:
        group: The channel-layer group name the message targets.
        data: The serialized payload data to embed in the message.
        action: The CRUD action name to embed in the payload.
        pk: The primary key to embed in the envelope.

    Returns:
        message: The assembled notify message dict.
    """
    return {
        "type": "subscription.notify",
        "stream": "posts",
        "group": group,
        "pk": pk,
        "payload": {"action": action, "model": "tests.post", "data": data},
    }


def _unwrap(t: Any) -> Any:
    """Strip GraphQLList/GraphQLNonNull wrappers down to the leaf type.

    Args:
        t: The GraphQL type to unwrap.

    Returns:
        leaf: The innermost type once every List/NonNull wrapper is removed.
    """
    while isinstance(t, (GraphQLList, GraphQLNonNull)):
        t = t.of_type
    return t


# ---------------------------------------------------------------------------
# WU7: the event type carries ALL fields with the FULL converter mapping.
# ---------------------------------------------------------------------------


def test_event_type_has_all_fields_no_omission() -> None:
    """Every "output_field_names()" entry must be mounted, with no field omitted.

    Contract: this test ships broken if any declared output field is
    silently dropped from the native subscription event type.
    """
    _register_post_node_types()
    sub = _make_subscription()
    event_type = sub._build_native_event_type()

    snake_names = sub._meta.backend.output_field_names()
    # WU6 OMITTED M2M (tags / co_authors); WU7 mounts EVERY declared output field.
    from django_graphex._strconv import to_camel_case

    for snake in snake_names:
        wire = to_camel_case(snake)
        assert wire in event_type.fields, f"{wire} ({snake}) must be present after WU7"


def test_event_type_scalar_names_and_nullability() -> None:
    """Scalars must use the Phase-5 native names and nullability.

    Contract: this test ships broken if "id" stops being the sole
    non-nullable "ID!" field, or if other scalars stop matching their
    Phase-5 native GraphQL type.
    """
    _register_post_node_types()
    sub = _make_subscription()
    event_type = sub._build_native_event_type()

    # pk -> ID! (the ONLY non-null output scalar — #1494 parity).
    id_type = event_type.fields["id"].type
    assert isinstance(id_type, GraphQLNonNull)
    assert id_type.of_type is GraphQLID
    # CharField / TextField -> String (nullable).
    assert event_type.fields["title"].type is GraphQLString
    assert event_type.fields["body"].type is GraphQLString
    # PositiveIntegerField -> Int (nullable).
    assert event_type.fields["views"].type is GraphQLInt


def test_event_type_fk_is_deliverable_pk_scalar_not_nested_object() -> None:
    """FK / O2O fields must render the deliverable pk scalar, not a nested object.

    Contract: this test ships broken if a FK/O2O field renders as the
    DB-backed nested output type (forcing a per-subscriber query the
    serialize-once design forbids) or reverts to the old Int seam.

    DESIGN RECONCILIATION (#1432 paragraph 3): the serialize-once payload
    ("backend.to_representation") carries the FK as the pk int under key
    "<field.name>" ("getattr(obj, '<name>_id')") — NOT a nested object dict.
    The event type therefore renders the FK as the pk's GraphQL scalar (ID for
    an auto/id pk), NOT the DB-backed nested AuthorT output type.
    """
    _register_post_node_types()
    sub = _make_subscription()
    event_type = sub._build_native_event_type()

    # FK author/category -> the related model's pk scalar (auto pk -> ID), NOT a
    # nested object type and NOT the WU6 Int seam.
    for wire in ("author", "category"):
        fk_type = event_type.fields[wire].type
        assert fk_type is GraphQLID, wire
        assert not isinstance(_unwrap(fk_type), GraphQLObjectType), wire
        assert fk_type is not GraphQLInt, wire


def test_event_type_m2m_is_deliverable_pk_list_not_container_not_string() -> None:
    """M2M fields must render a deliverable list of pk scalars.

    Contract: this test ships broken if an M2M field renders as the
    DB-backed results/totalCount container (whose totalCount resolver over a
    plain list raises a coercion error), is omitted, or falls back to String.

    DESIGN RECONCILIATION (#1432 paragraph 3): the serialize-once payload
    ("backend.to_representation") carries the M2M as a LIST OF PKS under key
    "<field.name>" ("list(... values_list('pk', flat=True))"). The event type
    renders it as "[<pk scalar>]" (auto pk -> "[ID]").
    """
    _register_post_node_types()
    sub = _make_subscription()
    event_type = sub._build_native_event_type()

    for wire in ("tags", "coAuthors"):
        assert wire in event_type.fields, f"{wire} M2M pk-list must be present"
        m2m_type = event_type.fields[wire].type
        # [pk scalar] — a GraphQLList whose inner type is the pk scalar (ID).
        assert isinstance(m2m_type, GraphQLList), wire
        assert m2m_type.of_type is GraphQLID, wire
        # NOT the results/totalCount container (the category error) and NOT String.
        leaf = _unwrap(m2m_type)
        assert not isinstance(leaf, GraphQLObjectType), wire
        assert m2m_type is not GraphQLString, wire


def test_every_field_is_sentinel_snake_closure_and_cond_b_passes() -> None:
    """Every event field must carry the sentinel snake-closure, and COND-B must pass.

    Contract: the COND-B guard ships broken if any event field's resolver
    lacks the "_gdx_pure_projection" sentinel after attachment.
    """
    from django_graphex.subscriptions.guard import check_subscription_output_type

    _register_post_node_types()
    sub = _make_subscription()
    event_type = sub._build_native_event_type()

    # gdx stamped on the event type.
    assert (event_type.extensions or {}).get("gdx") is not None

    # EVERY field (scalars + FK + M2M containers) carries the sentinel.
    for field_name, field in event_type.fields.items():
        assert getattr(field.resolve, "_gdx_pure_projection", False) is True, field_name

    # COND-B passes for the whole type AFTER sentinels are attached.
    check_subscription_output_type(event_type)


def test_event_type_sdl_is_the_deliverable_flat_pk_shape() -> None:
    """The event type's SDL must be the deliverable flat-pk shape, not the output type's.

    Contract: this test ships broken if the event type's SDL drifts from the
    flat-pk shape (scalars per Phase-5 naming, FK as pk scalar, M2M as pk
    list) or if it ever matches the output type's DB-backed nested shape.

    DESIGN RECONCILIATION (#1432 paragraphs 3 vs 8): paragraph 8's "event
    type SDL byte-identical to the DjangoObjectType OUTPUT type" goal is a
    CATEGORY ERROR vs paragraph 3's flat-pk payload — the output type's
    FK/M2M are DB-backed nested types, which a serialize-once event CANNOT
    deliver without a per-subscriber DB query.
    """
    post_t = _register_post_node_types()

    sub = _make_subscription()
    event_type = sub._build_native_event_type()

    # The event type carries EVERY backend output field name (no omission).
    snake_names = sub._meta.backend.output_field_names()
    from django_graphex._strconv import to_camel_case

    assert set(event_type.fields) == {to_camel_case(s) for s in snake_names}

    # The deliverable flat-pk SDL: scalars + FK pk + M2M pk-list.
    rendered = {name: str(field.type) for name, field in event_type.fields.items()}
    assert rendered["id"] == "ID!"
    assert rendered["title"] == "String"
    assert rendered["body"] == "String"
    assert rendered["views"] == "Int"
    # FK / O2O -> pk scalar.
    assert rendered["author"] == "ID"
    assert rendered["category"] == "ID"
    # M2M -> list of pk scalars.
    assert rendered["tags"] == "[ID]"
    assert rendered["coAuthors"] == "[ID]"

    # The output type, by contrast, renders FK/M2M as DB-backed nested types —
    # proving the event type does NOT (and MUST not) match the output type SDL.
    from django_graphex.core.registry_compiler import compile_all_outputs

    compile_all_outputs()
    model_output = post_t._meta.graphql_output_type
    assert str(model_output.fields["author"].type) != rendered["author"]
    assert str(model_output.fields["tags"].type) != rendered["tags"]


# ---------------------------------------------------------------------------
# WU7: DjangoModelType auto-gen wires the native field through compile_native_root.
# ---------------------------------------------------------------------------


def test_djangomodeltype_subscription_field_native_compiles_through_root() -> None:
    """A DjangoModelType SubscriptionField must mount on a native Subscription root.

    Contract: DjangoModelType auto-gen ships broken if the generated
    subscription field's return type fails to compile through
    compile_native_root into a fully-converted native event type (with the
    full converter mapping, gdx, and snake resolvers).
    """
    from django_graphex.core import ObjectType
    from django_graphex.core.registry_compiler import compile_all_outputs
    from django_graphex.core.schema_compiler import compile_native_root
    from django_graphex.types import DjangoModelType

    _register_post_node_types()

    class PostModelType(DjangoModelType):
        class Meta:
            model = Post
            stream = "posts"
            payload_mode = "full"

    class SubscriptionRoot(ObjectType):
        post = PostModelType.SubscriptionField()

    compile_all_outputs()
    native_root = compile_native_root(SubscriptionRoot, name="Subscription")

    assert isinstance(native_root, GraphQLObjectType)
    assert "post" in native_root.fields
    event_type = _unwrap(native_root.fields["post"].type)
    assert isinstance(event_type, GraphQLObjectType)
    # The event type carries the deliverable flat-pk mapping: M2M present as a
    # pk-list ([ID]), FK present as a pk scalar (ID).
    assert "coAuthors" in event_type.fields
    assert isinstance(event_type.fields["coAuthors"].type, GraphQLList)
    assert event_type.fields["coAuthors"].type.of_type is GraphQLID
    assert "author" in event_type.fields
    assert event_type.fields["author"].type is GraphQLID
    # Reduced native arg set: {action, id, filters}.
    assert set(native_root.fields["post"].args) == {"action", "id", "filters"}


# ---------------------------------------------------------------------------
# WU7: serialize-once delivery still GREEN on the scalar/FK equality path.
# ---------------------------------------------------------------------------


async def test_serialize_once_delivers_over_full_converter_event_type() -> None:
    """Driving the full-converter event type must yield a projected flat-dict result.

    Contract: this test ships broken if a scalar-only selection over the
    full-converter event type raises a coercion error instead of cleanly
    projecting the serialize-once flat snake dict.
    """
    from graphql import ExecutionResult, GraphQLBoolean, GraphQLField, GraphQLSchema

    from django_graphex.subscriptions.streaming import drive_subscription

    _register_post_node_types()
    sub = _make_subscription()
    event_type = sub._build_native_event_type()
    subscription_type = GraphQLObjectType(
        "Subscription",
        lambda: {"postEvent": GraphQLField(event_type, resolve=lambda root, _i: root)},
    )
    query_type = GraphQLObjectType(
        "Query", lambda: {"ok": GraphQLField(GraphQLBoolean)}
    )
    schema = GraphQLSchema(query=query_type, subscription=subscription_type)
    doc = parse("subscription { postEvent { id title views } }")

    layer = InMemoryChannelLayer()
    spec = sub._build_native_spec(schema, doc)
    source = await sub._native_subscribe(
        layer, schema, doc, action="create", obj_id=None, filters=None, context=None
    )
    delivery = drive_subscription(source, spec)

    group = source.joined_groups[0]
    flat = {"id": 1, "title": "hello", "views": 3, "author": 7, "co_authors": [7, 8]}
    await layer.group_send(group, _notify(group, flat))

    result = await asyncio.wait_for(delivery.__anext__(), timeout=1.0)
    await delivery.aclose()

    assert isinstance(result, ExecutionResult)
    assert result.errors is None
    assert result.data == {"postEvent": {"id": "1", "title": "hello", "views": 3}}


# ---------------------------------------------------------------------------
# WU7-FIX: nested-relation selection DELIVERS the flat-payload PKS (the defect
# fix). Selecting the FK pk field AND the M2M pk-list field over the REAL
# serialize-once ``to_representation`` flat payload must deliver the PKS (FK
# pk; M2M list of pks), errors=None, ZERO queries — proving the relations now
# render the DELIVERABLE pk scalar/list, not the DB-backed nested object /
# results-totalCount container (which returned a fully-null object / raised a
# GraphQLError). These FAIL against the old nested-object/container shapes and
# PASS after the pk-representation fix.
# ---------------------------------------------------------------------------


def _build_event_schema(sub: "type[Subscription]") -> Any:
    """Assemble a native subscription schema mounting "sub"'s event type.

    Args:
        sub: The Subscription subclass whose native event type is mounted.

    Returns:
        schema: The assembled GraphQLSchema with a "postEvent" subscription
            field returning sub's native event type.
    """
    from graphql import GraphQLBoolean, GraphQLField, GraphQLSchema

    event_type = sub._build_native_event_type()
    subscription_type = GraphQLObjectType(
        "Subscription",
        lambda: {"postEvent": GraphQLField(event_type, resolve=lambda root, _i: root)},
    )
    query_type = GraphQLObjectType(
        "Query", lambda: {"ok": GraphQLField(GraphQLBoolean)}
    )
    return GraphQLSchema(query=query_type, subscription=subscription_type)


@pytest.mark.django_db
async def test_nested_fk_and_m2m_selection_delivers_pks_zero_queries() -> None:
    """Selecting the FK pk plus M2M pk-list must deliver the pks with zero DB queries.

    Contract: this test ships broken if the FK/M2M selection either raises,
    touches the DB, or fails to deliver the exact pk values from the flat
    payload (regressing to a fully-null FK object or a totalCount coercion
    GraphQLError).

    Drives the REAL serialize-once flat payload (author=7 pk int,
    co_authors=[7, 8] pk list, tags=[3]). The deliverable event type
    renders "author: ID" and "coAuthors/tags: [ID]", so the selection
    DELIVERS the pks (FK pk -> "7"; M2M pks -> ["7", "8"]) with NO error and ZERO
    DB queries — the snake-closure projects the flat dict, never the ORM.
    """
    from asgiref.sync import sync_to_async
    from django.db import connection, reset_queries
    from graphql import ExecutionResult

    from django_graphex.subscriptions.streaming import drive_subscription

    _register_post_node_types()
    sub = _make_subscription()
    schema = _build_event_schema(sub)
    doc = parse("subscription { postEvent { id author category tags coAuthors } }")

    layer = InMemoryChannelLayer()
    spec = sub._build_native_spec(schema, doc)
    source = await sub._native_subscribe(
        layer, schema, doc, action="create", obj_id=None, filters=None, context=None
    )
    delivery = drive_subscription(source, spec)

    group = source.joined_groups[0]
    # The EXACT flat shape backend.to_representation emits: FK -> pk int under
    # key <name>; M2M -> list of pk ints under key <name>.
    flat = {
        "id": 1,
        "title": "hello",
        "body": "",
        "views": 0,
        "author": 7,
        "category": 9,
        "tags": [3],
        "co_authors": [7, 8],
    }
    await layer.group_send(group, _notify(group, flat))

    # Serialize-once query proof: enable query logging via a thread (the
    # connection bootstrap is sync-only and cannot run in the async context), then
    # drive the delivery and assert ZERO queries were logged by the projection.
    @sync_to_async
    def _enable_query_log():
        connection.ensure_connection()
        connection.force_debug_cursor = True
        reset_queries()

    @sync_to_async
    def _query_count():
        return len(connection.queries)

    await _enable_query_log()
    result = await asyncio.wait_for(delivery.__anext__(), timeout=1.0)
    n_queries = await _query_count()
    await delivery.aclose()

    assert isinstance(result, ExecutionResult)
    assert result.errors is None
    # FK pk delivered as the ID scalar (coerced to str); NOT a fully-null object.
    assert result.data == {
        "postEvent": {
            "id": "1",
            "author": "7",
            "category": "9",
            "tags": ["3"],
            "coAuthors": ["7", "8"],
        }
    }
    # Serialize-once: the snake-closure projects the flat dict, ZERO DB queries.
    assert n_queries == 0


async def test_nested_m2m_totalcount_selection_is_rejected_at_validation() -> None:
    """The old M2M container's totalCount selection must no longer validate.

    Contract: this test ships broken if a container-style sub-selection on
    the now-leaf M2M field either passes validation or crashes at execution
    time instead of failing statically at validation.

    The defect was that the M2M rendered the "<Model>ListType" results/totalCount
    CONTAINER, so "tags { totalCount results { id } }" parsed and then RAISED a
    GraphQLError (totalCount coerced the list's .count method). Now the
    M2M is "[ID]" (a leaf list), so a sub-selection on it is a STATIC schema
    error caught at validation — never an execution-time coercion crash.
    """
    from graphql import validate

    _register_post_node_types()
    sub = _make_subscription()
    schema = _build_event_schema(sub)
    # A container-style sub-selection on the (now leaf) M2M field.
    doc = parse("subscription { postEvent { tags { totalCount results { id } } } }")
    errors = validate(schema, doc)
    assert errors, "selecting into a leaf [ID] M2M must be a validation error"
    assert any("tags" in str(e) for e in errors)
