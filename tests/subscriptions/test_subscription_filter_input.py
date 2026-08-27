# -*- coding: utf-8 -*-
"""2.1.0 — the subscription "filter" argument is a real generated input type.

Through 2.0.x a subscription took "filters" as a plain "GraphQLString" carrying
JSON, while queries took "filter" as a typed "<Model>FilterInput". Two names,
two shapes, and NO schema validation or autocompletion on the subscription side
— which is exactly why the docs shipped a broken syntax for two releases.

2.1.0 unifies them: the argument is "filter" (singular, the query term) and its
type is a GENERATED "<Model>SubscriptionFilterInput" using the same nested
"{field: {lookup: value}}" shape queries use. The type is DELIBERATELY distinct
from the query's "<Model>FilterInput":

  * it exposes only the subscription's PROJECTED output fields
    ("Meta.only_fields" / "Meta.exclude_fields"), and
  * only the four lookups the 2.0.1 security fix allows
    ("exact"/"iexact"/"in"/"isnull"),

so the TYPE SYSTEM now enforces what the runtime validator enforces. Reusing
the query's input would reopen the extraction oracle 2.0.1 closed, so these
tests pin that the two types coexist with byte-identical query SDL, in BOTH
declaration orders.
"""

from __future__ import annotations

import asyncio
import json
from typing import Any

import pytest
from graphql import GraphQLSchema, print_type

pytest.importorskip("channels")

from channels.layers import InMemoryChannelLayer  # noqa: E402

from django_graphex.subscriptions import Subscription  # noqa: E402
from django_graphex.types import DjangoObjectType as _DOT  # noqa: E402
from tests.models import (  # noqa: E402
    SubFilterComment,
    SubFilterPost,
    SubFilterTag,
)
from tests.subscriptions._sse import sse_frames  # noqa: E402


# Output types registered ONCE at module scope (a DjangoObjectType registration
# is last-one-wins on the global registry, so a per-test class would fork the
# shared slot for whatever test runs next). "SubFilterPost"/"SubFilterTag" exist
# so the "post" relation actually renders on the event type instead of being
# dropped as an unregistered target.
class _SubFilterTagT(_DOT):
    class Meta:
        model = SubFilterTag


class _SubFilterPostT(_DOT):
    class Meta:
        model = SubFilterPost


class _CommentT(_DOT):
    class Meta:
        model = SubFilterComment
        filter_fields = {"text": ("exact", "icontains"), "post": ("exact", "in")}


# The exact query-side SDL as it stands BEFORE this change. Asserted verbatim so
# a regression in the subscription builder that reached into the shared
# "<Model>FilterInput" cache (or its "<Field>Lookups" names) fails loudly here.
_QUERY_FILTER_INPUT_SDL = """input SubFilterCommentFilterInput {
  text: SubFilterCommentTextLookups
  post: SubFilterCommentPostLookups
  and: [SubFilterCommentFilterInput]
  or: [SubFilterCommentFilterInput]
  not: SubFilterCommentFilterInput
}"""

_QUERY_POST_LOOKUPS_SDL = """input SubFilterCommentPostLookups {
  exact: ID
  in: [ID]
}"""

_QUERY_TEXT_LOOKUPS_SDL = """input SubFilterCommentTextLookups {
  exact: String
  icontains: String
}"""


def _comment_subscription(**meta: Any) -> type[Subscription]:
    """Build a fresh "SubFilterComment" subscription class.

    Args:
        **meta: Extra attributes merged into the generated Meta class; model
            and stream are always set and overrides here win.

    Returns:
        The freshly created Subscription subclass.
    """
    meta_cls = type(
        "Meta",
        (),
        {"model": SubFilterComment, "stream": "sub-filter-comments", **meta},
    )
    meta_cls.__qualname__ = "SubFilterCommentSubscription.Meta"
    meta_cls.__module__ = __name__
    return type(
        "SubFilterCommentSubscription",
        (Subscription,),
        {
            "__module__": __name__,
            "__qualname__": "SubFilterCommentSubscription",
            "Meta": meta_cls,
        },
    )


#: The subscription under test, built once (a Subscription subclass registers a
#: live signal binding, so a per-test class would stack duplicate bindings).
_SUB = _comment_subscription(payload_mode="full")


def _build_schema(
    *, with_query_filter: bool, subscription_first: bool
) -> GraphQLSchema:
    """Assemble a native schema mounting a subscription and/or a query filter.

    Args:
        with_query_filter: Whether to mount a filtered list field over the SAME
            model, so the query "<Model>FilterInput" is compiled too.
        subscription_first: Whether the SUBSCRIPTION filter input is compiled
            before the query one (the build order the name collision, and the
            shared filter-input cache, must survive either way).

    Returns:
        The assembled graphql-core schema.
    """
    from graphql import GraphQLBoolean

    from django_graphex.core import ObjectType, field
    from django_graphex.core.registry_compiler import compile_all_outputs
    from django_graphex.fields import DjangoFilterPaginateListField
    from django_graphex.schema import DjangoGraphQLSchema

    if subscription_first:
        # Force the subscription input to compile BEFORE the query one.
        _SUB._build_native_field()

    query_attrs: dict[str, Any] = {"ok": field(GraphQLBoolean)}
    if with_query_filter:
        query_attrs["comments"] = DjangoFilterPaginateListField(_CommentT)
    query_cls = type("Query", (ObjectType,), query_attrs)
    sub_root = type("SubscriptionRoot", (ObjectType,), {"comment": _SUB.Field()})

    compile_all_outputs()
    return DjangoGraphQLSchema(query=query_cls, subscription=sub_root).graphql_schema


# ---------------------------------------------------------------------------
# 1) SDL — the argument is "filter", typed by the generated input
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_subscription_arg_is_filter_typed_by_generated_input() -> None:
    """The subscription field must take "filter: <Model>SubscriptionFilterInput".

    Contract: ships broken if the argument is still the 2.0.x JSON
    "filters: String", or if it is typed by the query's "<Model>FilterInput"
    (which exposes every lookup and would reopen the 2.0.1 extraction oracle).
    """
    from graphql import GraphQLInputObjectType

    schema = _build_schema(with_query_filter=False, subscription_first=True)
    args = schema.subscription_type.fields["comment"].args

    assert "filters" not in args
    assert set(args) == {"action", "id", "filter"}
    filter_type = args["filter"].type
    assert isinstance(filter_type, GraphQLInputObjectType)
    assert filter_type.name == "SubFilterCommentSubscriptionFilterInput"


@pytest.mark.django_db
def test_subscription_filter_input_projects_fields_and_allowed_lookups() -> None:
    """The generated input must expose the projected fields x the four lookups.

    Contract: ships broken if the input advertises a field the subscription
    does not project, or a lookup outside the 2.0.1 allow list — the whole point
    of the change is that the type system now IS the boundary.
    """
    schema = _build_schema(with_query_filter=False, subscription_first=True)
    filter_type = schema.subscription_type.fields["comment"].args["filter"].type

    # Exactly the projected output fields — no "and"/"or"/"not" combinators
    # (the delivery path consumes a FLAT lookup dict that cannot express them).
    assert set(filter_type.fields) == {"id", "post", "text"}
    # Every field carries the snake ORM name so camelCase wire keys map back.
    for name, field_def in filter_type.fields.items():
        assert field_def.out_name == name

    for name in filter_type.fields:
        lookups = filter_type.fields[name].type
        assert set(lookups.fields) == {"exact", "iexact", "in", "isnull"}, name
        assert lookups.name.endswith("SubscriptionLookups"), lookups.name
        for lookup, lookup_field in lookups.fields.items():
            assert lookup_field.out_name == lookup


@pytest.mark.django_db
def test_exclude_fields_keeps_a_column_out_of_the_filter_input() -> None:
    """ "Meta.exclude_fields" must remove the column from the generated input.

    Contract: ships broken if a projected-out column stays filterable — the
    2.0.1 fix made the projection real on the payload and the runtime
    validator; 2.1.0 must make it real in the SDL too.
    """
    meta_cls = type(
        "Meta",
        (),
        {
            "model": SubFilterPost,
            "stream": "sub-filter-posts",
            "exclude_fields": ("secret",),
        },
    )
    meta_cls.__qualname__ = "SubFilterPostSubscription.Meta"
    meta_cls.__module__ = __name__
    sub_cls = type(
        "SubFilterPostSubscription",
        (Subscription,),
        {
            "__module__": __name__,
            "__qualname__": "SubFilterPostSubscription",
            "Meta": meta_cls,
        },
    )

    filter_type = sub_cls._build_native_field().args["filter"].type
    assert "secret" not in filter_type.fields
    assert {"id", "title", "status", "tags"} == set(filter_type.fields)
    # The choices column reuses the shared choices enum on its lookups input.
    status_lookups = filter_type.fields["status"].type
    assert status_lookups.fields["exact"].type.name.endswith("Enum")


@pytest.mark.django_db
def test_a_fully_excluded_subscription_has_no_filter_argument() -> None:
    """A projection that leaves no column must drop the "filter" argument entirely.

    Contract: ships broken if an empty projection still advertises a "filter"
    argument — graphql-core rejects an input object with no fields, so the
    schema would fail to build instead of simply offering no filtering.
    """
    meta_cls = type(
        "Meta",
        (),
        {
            "model": SubFilterTag,
            "stream": "sub-filter-tags",
            "exclude_fields": ("id", "label", "posts"),
        },
    )
    meta_cls.__qualname__ = "SubFilterTagSubscription.Meta"
    meta_cls.__module__ = __name__
    sub_cls = type(
        "SubFilterTagSubscription",
        (Subscription,),
        {
            "__module__": __name__,
            "__qualname__": "SubFilterTagSubscription",
            "Meta": meta_cls,
        },
    )

    assert set(sub_cls._meta.arguments) == {"action", "id"}
    assert set(sub_cls._build_native_field().args) == {"action", "id"}


# ---------------------------------------------------------------------------
# 2) Coexistence — the query input is untouched, in BOTH declaration orders
# ---------------------------------------------------------------------------


@pytest.mark.django_db
@pytest.mark.parametrize("subscription_first", [True, False])
def test_query_filter_input_unchanged_and_coexists(subscription_first: bool) -> None:
    """Both input types must live in ONE schema with the query SDL byte-identical.

    Contract: ships broken if the subscription builder reuses or widens the
    query's "<Model>FilterInput" (or mints a same-named "<Field>Lookups"),
    which graphql-core rejects as a duplicate name — or silently reopens the
    extraction oracle by handing the subscription every query lookup.

    Args:
        subscription_first: Whether the subscription type is declared before
            the query output type.
    """
    schema = _build_schema(
        with_query_filter=True, subscription_first=subscription_first
    )

    assert print_type(schema.type_map["SubFilterCommentFilterInput"]).strip() == (
        _QUERY_FILTER_INPUT_SDL
    )
    assert print_type(schema.type_map["SubFilterCommentPostLookups"]).strip() == (
        _QUERY_POST_LOOKUPS_SDL
    )
    assert print_type(schema.type_map["SubFilterCommentTextLookups"]).strip() == (
        _QUERY_TEXT_LOOKUPS_SDL
    )

    sub_input = schema.type_map["SubFilterCommentSubscriptionFilterInput"]
    assert sub_input is not schema.type_map["SubFilterCommentFilterInput"]
    assert print_type(sub_input).strip() == (
        "input SubFilterCommentSubscriptionFilterInput {\n"
        "  id: SubFilterCommentIdSubscriptionLookups\n"
        "  post: SubFilterCommentPostSubscriptionLookups\n"
        "  text: SubFilterCommentTextSubscriptionLookups\n"
        "}"
    )


# ---------------------------------------------------------------------------
# 3) Coercion — the schema, not the runtime, now rejects a banned lookup
# ---------------------------------------------------------------------------


def _validate(schema: GraphQLSchema, document: str) -> list[str]:
    """Validate a document against a schema and return the error messages.

    Args:
        schema: The schema to validate against.
        document: The GraphQL document source.

    Returns:
        The validation error messages (empty when the document is valid).
    """
    from graphql import parse, validate

    return [str(err) for err in validate(schema, parse(document))]


@pytest.mark.django_db
@pytest.mark.parametrize(
    ("selection", "expect_valid", "needle"),
    [
        ("filter: { post: { exact: 7 } }", True, ""),
        ('filter: { text: { in: ["a", "b"] } }', True, ""),
        ("filter: { post: { isnull: true } }", True, ""),
        # A banned lookup is now a SCHEMA error, not a runtime one.
        ('filter: { text: { icontains: "x" } }', False, "icontains"),
        ('filter: { text: { startswith: "x" } }', False, "startswith"),
        # An undeclared field is a schema error.
        ('filter: { nope: { exact: "x" } }', False, "nope"),
        # Relation traversal is unexpressible: "post" only takes lookups.
        ('filter: { post: { text: { exact: "x" } } }', False, "text"),
        # The 2.0.x JSON-string form no longer parses against this schema.
        ('filters: "{\\"post\\": 7}"', False, "filters"),
    ],
)
def test_filter_argument_coercion(
    selection: str, expect_valid: bool, needle: str
) -> None:
    """The four allowed lookups validate; everything else is a schema error.

    Contract: ships broken if a pattern/ordered lookup, an undeclared field, a
    relation path, or the retired JSON-string argument still validates.

    Args:
        selection: The argument source spliced into the subscription field.
        expect_valid: Whether the document must pass validation.
        needle: A substring the validation error must mention.
    """
    schema = _build_schema(with_query_filter=False, subscription_first=True)
    errors = _validate(
        schema, "subscription { comment(action: CREATE, %s) { id text } }" % selection
    )
    if expect_valid:
        assert errors == []
    else:
        assert errors
        assert any(needle in err for err in errors)


# ---------------------------------------------------------------------------
# 4) End to end over SSE — real DB, real transport (proves the flattening)
# ---------------------------------------------------------------------------


def _make_request(query: str) -> Any:
    """Build an async-capable request carrying a GraphQL subscription body.

    Args:
        query: The GraphQL subscription document to send as the body.

    Returns:
        The constructed Django test request.
    """
    from django.test import RequestFactory

    request = RequestFactory().post(
        "/subscriptions/sse",
        data=json.dumps({"query": query}),
        content_type="application/json",
    )
    request.user = type("_U", (), {"is_authenticated": True, "pk": 1})()
    return request


@pytest.mark.django_db(transaction=True)
async def test_sse_delivers_only_events_matching_the_filter(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A matching event must be delivered over SSE and a non-matching one dropped.

    Contract: this is the test that proves the nested input is FLATTENED into
    real ORM lookups at the resolver boundary. It ships broken if the coerced
    "{post: {exact: N}}" dict reaches the delivery gate unflattened (nothing
    would ever match) or is flattened to a key the gate mis-reads (everything
    would match).

    Args:
        monkeypatch: The pytest fixture used to stub the channel layer.
    """
    from asgiref.sync import sync_to_async

    from django_graphex.subscriptions.transports import sse

    wanted, other = await sync_to_async(
        lambda: (
            SubFilterPost.objects.create(title="wanted"),
            SubFilterPost.objects.create(title="other"),
        )
    )()
    match, miss = await sync_to_async(
        lambda: (
            SubFilterComment.objects.create(post=wanted, text="yes"),
            SubFilterComment.objects.create(post=other, text="no"),
        )
    )()

    layer = InMemoryChannelLayer()
    monkeypatch.setattr("channels.layers.get_channel_layer", lambda *a, **k: layer)

    schema = _build_schema(with_query_filter=False, subscription_first=True)
    view = sse.subscription_sse_view(schema=schema)
    query = (
        "subscription { comment(action: CREATE, filter: { post: { exact: %d } }) "
        "{ id text post } }" % wanted.pk
    )
    response = await view(_make_request(query))
    assert response.status_code == 200

    started = sse.get_started_source(response)
    group = started.joined_groups[0]

    def _notify(comment: SubFilterComment) -> dict[str, Any]:
        return {
            "type": "subscription.notify",
            "stream": "sub-filter-comments",
            "group": group,
            "pk": comment.pk,
            "payload": {
                "action": "create",
                "model": "tests.subfiltercomment",
                "data": {
                    "id": comment.pk,
                    "post": comment.post_id,
                    "text": comment.text,
                },
            },
        }

    # The non-matching event first: if the filter leaked, IT would arrive.
    await layer.group_send(group, _notify(miss))
    await layer.group_send(group, _notify(match))

    aiter = sse_frames(response).__aiter__()
    frame = await asyncio.wait_for(aiter.__anext__(), timeout=2.0)
    frame = frame.decode() if isinstance(frame, (bytes, bytearray)) else frame
    assert frame.startswith("event: next\n")
    payload_line = [ln for ln in frame.splitlines() if ln.startswith("data: ")][0]
    delivered = json.loads(payload_line[len("data: ") :])["data"]["comment"]
    assert delivered == {
        "id": str(match.pk),
        "text": "yes",
        "post": str(wanted.pk),
    }

    await started.aclose()
    aclose = getattr(aiter, "aclose", None)
    if aclose is not None:
        await aclose()
