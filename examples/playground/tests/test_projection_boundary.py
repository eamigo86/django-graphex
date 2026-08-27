"""The projection boundary, demonstrated end to end on three columns.

"blog/schema.py" projects three columns away with "Meta.exclude_fields", and
the library treats that as a SECURITY boundary rather than an output shape:

- "Author.bio" — the teaching example, seeded with real content.
- "User.password" — the same rule on the one column whose leak is an incident.
- "Comment.internal_note" — the same rule on BOTH sides, read and write, so the
  projection is pinned on the write inputs too, including the nested child
  input a "Meta.nested_fields" parent exposes.

Most of this module works "AuthorType", where all three axes the boundary
closes are visible on the very schema "make run" serves:

1. Output — "bio" is absent from "AuthorType" in the SDL, so no client can
   select it.
2. "ordering" — "results(ordering: \\"bio\\")" is refused at query time, because
   ranking rows by a hidden column recovers it one comparison at a time.
3. "filter" — "bio" is absent from "AuthorFilterInput", so there is no lookup
   to send. Naming it in "Meta.filter_fields" would fail the schema build
   instead of being dropped in silence.

The README quotes an ANSWER for each of those rows, so the answers are pinned
here too rather than only the refusal. Two of them carry graphql-core's
"Did you mean ...?" suggestion, which the library strips whenever introspection
is actually disabled -- and the README's own Views section tells the reader to
disable it. Both sides of that toggle are therefore pinned, because a reader who
follows one section must not be contradicted by another.

Run them from this directory:

    cd examples/playground
    DJANGO_SETTINGS_MODULE=config.settings python -m pytest -q
"""

from __future__ import annotations

import json
from typing import Any

from django.conf import settings
from django.test import Client, override_settings


def _author_type() -> object:
    """Return the compiled "AuthorType" from the playground schema.

    Returns:
        type: The compiled "GraphQLObjectType" the playground serves authors as.
    """
    from blog.schema import schema

    return schema.graphql_schema.type_map["AuthorType"]


def _post(query: str) -> dict[str, Any]:
    """POST a document to the playground's public endpoint and decode the body.

    The "X-Requested-With" header rides along because "REQUIRE_CSRF_HEADER"
    ships on; "application/json" would not need it, but sending it keeps this
    helper usable for the CORS-simple content types too.

    Args:
        query: The GraphQL document to execute.

    Returns:
        body: The decoded JSON response body.
    """
    response = Client().post(
        "/graphql/",
        data=json.dumps({"query": query}),
        content_type="application/json",
        headers={"x-requested-with": "XMLHttpRequest"},
    )
    return json.loads(response.content)


def _messages(query: str) -> str:
    """Return every error message the endpoint answers a document with, joined.

    Args:
        query: The GraphQL document to execute.

    Returns:
        messages: The error messages joined by a newline, empty when the
            document resolved cleanly.
    """
    return "\n".join(
        error.get("message", "") for error in _post(query).get("errors") or []
    )


def _introspection_off() -> Any:
    """Build the settings override the README's Views section recommends.

    The namespace is copied rather than rebuilt so every other playground
    setting -- the middleware list above all, since the strip only fires when
    "DisableIntrospectionMiddleware" is installed -- stays exactly as shipped.

    Returns:
        override: A context manager disabling introspection for its block.
    """
    namespace = dict(settings.DJANGO_GRAPHEX)
    namespace["ALLOW_INTROSPECTION"] = False
    return override_settings(DJANGO_GRAPHEX=namespace)


def test_the_projected_column_is_not_readable() -> None:
    """Assert the SDL publishes no "bio" field on "AuthorType".

    The control matters as much as the assertion: "name" is still there, so a
    passing test means the projection removed one column rather than the type.
    """
    fields = _author_type().fields

    assert "bio" not in fields
    assert "name" in fields


def test_the_projected_column_is_not_selectable_over_the_wire(db: object) -> None:
    """Assert selecting the hidden column answers the README's own message.

    The README's projection table quotes this answer verbatim, suggestion and
    all. The suggestion half is what the introspection toggle deletes, so it is
    asserted here rather than only the prefix.

    Args:
        db: The pytest-django database fixture that enables DB access.
    """
    messages = _messages("{ authors { results(page: 1) { bio } } }")

    assert (
        messages == "Cannot query field 'bio' on type 'AuthorType'. Did you mean 'id'?"
    )


def test_the_projected_column_is_not_orderable(db: object) -> None:
    """Assert ordering the author list by the hidden column is refused.

    Args:
        db: The pytest-django database fixture that enables DB access.
    """
    messages = _messages('{ authors { results(ordering: "bio") { id name } } }')

    assert "Invalid ordering field: 'bio'" in messages


def test_the_projected_column_is_not_filterable_over_the_wire(db: object) -> None:
    """Assert sending a lookup for the hidden column answers the README's message.

    The static check below proves the input type carries no "bio" field; this
    one proves a client that sends it anyway is refused, which is the row the
    README tells the reader to paste into GraphiQL.

    Args:
        db: The pytest-django database fixture that enables DB access.
    """
    messages = _messages(
        '{ authors(filter: { bio: { icontains: "x" } }) { totalCount } }'
    )

    assert messages == (
        "Field 'bio' is not defined by type 'AuthorFilterInput'. Did you mean 'id'?"
    )


def test_a_published_column_is_still_orderable(db: object) -> None:
    """Assert the boundary costs nothing on a column the type does publish.

    Args:
        db: The pytest-django database fixture that enables DB access.
    """
    payload = _post('{ authors { results(ordering: "name") { id name } } }')

    assert "errors" not in payload, payload


def test_disabling_introspection_strips_the_suggestion_the_readme_quotes(
    db: object,
) -> None:
    """Assert the two suggestion-carrying answers lose their tail under the toggle.

    The README's Views section tells the reader to set
    "ALLOW_INTROSPECTION = False" to watch "DisableIntrospectionMiddleware"
    work. Doing so also strips every "Did you mean ...?" built from schema
    members, because guessing at invented names rebuilds the schema the
    operator believes is hidden. The rest of each message survives, so the
    refusal a reader is looking for is still there.

    Args:
        db: The pytest-django database fixture that enables DB access.
    """
    with _introspection_off():
        selected = _messages("{ authors { results(page: 1) { bio } } }")
        filtered = _messages(
            '{ authors(filter: { bio: { icontains: "x" } }) { totalCount } }'
        )

    assert selected == "Cannot query field 'bio' on type 'AuthorType'."
    assert filtered == "Field 'bio' is not defined by type 'AuthorFilterInput'."


def test_disabling_introspection_leaves_the_ordering_refusal_whole(db: object) -> None:
    """Assert the ordering answer is byte-identical under either toggle state.

    "Invalid ordering field" is raised by this library, not by a graphql-core
    validation rule, and it names the term the CLIENT sent rather than a schema
    member -- so it is not an oracle and nothing is stripped from it. The
    control matters: a strip keyed on the shape of a trailing sentence rather
    than on the emitting rule would have eaten messages like this one.

    Args:
        db: The pytest-django database fixture that enables DB access.
    """
    query = '{ authors { results(ordering: "bio") { id name } } }'

    with _introspection_off():
        stripped = _messages(query)

    assert "Invalid ordering field: 'bio'" in stripped
    assert stripped == _messages(query)


def test_the_projected_column_is_not_filterable() -> None:
    """Assert the generated filter input carries no lookup for the hidden column.

    "AuthorType.Meta.filter_fields" names "id" and "name" only. Adding "bio"
    would raise "ImproperlyConfigured" while the schema builds rather than
    quietly dropping the entry, so absence here is the whole client-visible
    surface.
    """
    from blog.schema import schema

    fields = schema.graphql_schema.type_map["AuthorFilterInput"].fields

    assert "bio" not in fields
    assert "name" in fields


# --------------------------------------------------------------------------- #
# The same rule on the password hash, and on a column hidden from writes too   #
# --------------------------------------------------------------------------- #


def test_the_password_hash_is_not_reachable_through_the_author_relation(
    db: object,
) -> None:
    """Assert "UserType" hides the hash even from the relation that reaches it.

    "Author.user" reaches "UserType", so without the projection
    "authors { results { user { password } } }" answers the hash to every
    AUTHENTICATED caller — an ordinary logged-in user reading every author's
    hash. Anonymous callers are stopped one layer earlier by "resolve_user"
    (the to-ONE scope hatch), which is a second wall, not this one: the day
    that resolver changes, only the projection is left. This is the one row
    where a regression is not a documentation problem.

    Args:
        db: The pytest-django database fixture that enables DB access.
    """
    messages = _messages("{ authors { results { user { password } } } }")

    assert "Cannot query field 'password' on type 'UserType'" in messages
    # The control: the relation itself is still there, so the assertion above
    # is the projection talking rather than a missing field.
    assert _messages("{ authors { results { user { username } } } }") == ""


def _unwrap(graphql_type: Any) -> Any:
    """Strip every NonNull and List wrapper off a type and return the named one.

    Args:
        graphql_type: The possibly wrapped type to unwrap.

    Returns:
        named: The innermost named type.
    """
    while hasattr(graphql_type, "of_type"):
        graphql_type = graphql_type.of_type
    return graphql_type


def test_the_moderation_note_is_hidden_on_the_read_axes_it_can_reach(
    db: object,
) -> None:
    """Assert the "internal_note" projection closes reads and filters alike.

    Only two of the three axes are reachable on this type: "CommentListType"
    paginates by cursor, and "CursorGraphqlPagination" takes its ordering as
    the operator's own configuration rather than as a client argument, so
    "results" publishes no "ordering" to refuse. The ordering axis is pinned on
    "AuthorType" above, where the client can send one.

    Args:
        db: The pytest-django database fixture that enables DB access.
    """
    from blog.schema import schema

    type_map = schema.graphql_schema.type_map

    assert "internalNote" not in type_map["CommentType"].fields
    assert "internalNote" not in type_map["CommentFilterInput"].fields
    assert "Cannot query field 'internalNote' on type 'CommentType'" in _messages(
        "{ comments { results { internalNote } } }"
    )
    # The control: the type still serves what it publishes.
    assert _messages("{ comments { results { text } } }") == ""


def test_the_moderation_note_is_hidden_on_both_write_inputs() -> None:
    """Assert the write host's projection reaches its nested child input too.

    Before 2.2.0 the child's declared input projection was DROPPED when a
    parent listed the relation in "Meta.nested_fields", so a column the child's
    own host refused was still writable through the parent. Both inputs are
    read off the mutation fields rather than looked up by name, because the
    generated names carry a registry-scoped suffix that is not a contract.
    """
    from blog.schema import schema

    mutation_type = schema.graphql_schema.mutation_type
    standalone = _unwrap(mutation_type.fields["commentCreate"].args["newComment"].type)
    parent = _unwrap(
        mutation_type.fields["postWithCommentsCreate"].args["newPost"].type
    )
    nested_child = _unwrap(parent.fields["comments"].type)

    assert "internalNote" not in standalone.fields
    assert "internalNote" not in nested_child.fields
    # The control: both inputs still carry the columns the host does publish,
    # so neither assertion above is passing on an empty input type.
    assert "text" in standalone.fields
    assert "text" in nested_child.fields


def test_the_subscription_surface_hides_the_column_the_query_surface_hides() -> None:
    """Assert the shipped subscription refuses the column every other axis does.

    A hand-written "Subscription" bound to "Meta.model" builds its event type
    and its filter input from the MODEL, so it does NOT inherit "CommentType"'s
    projection — the library measures a subscription against its OWN "Meta"
    only. "CommentSubscription" therefore has to restate the exclusion, and
    this pins that it did: a moderation column reaching an anonymous
    subscriber, selectable AND filterable, is a real leak and not a
    documentation problem.

    The library-level gap this compensates for is pinned separately, in
    isolation, by
    "test_a_model_bound_subscription_does_not_inherit_the_types_projection".
    """
    from blog.schema import schema
    from graphql import parse, validate

    type_map = schema.graphql_schema.type_map
    document = (
        "subscription { commentSubscription(action: ALL_ACTIONS, "
        'filter: { internalNote: { exact: "x" } }) { internalNote text } }'
    )

    assert "internalNote" not in type_map["CommentSubscriptionEvent"].fields
    assert "internalNote" not in type_map["CommentSubscriptionFilterInput"].fields
    assert validate(schema.graphql_schema, parse(document)) != []
    # The controls: the surface is otherwise intact on both halves, so neither
    # assertion above is passing on an empty type.
    assert "text" in type_map["CommentSubscriptionEvent"].fields
    assert "text" in type_map["CommentSubscriptionFilterInput"].fields
    # And the query surface refuses the same column, which is the whole point.
    assert "internalNote" not in type_map["CommentType"].fields


def test_a_model_bound_subscription_does_not_inherit_the_types_projection() -> None:
    """Pin the library boundary the shipped subscription has to compensate for.

    A "Subscription" bound to "Meta.model" is measured against its OWN "Meta",
    never against the type registered for that model. So a subscription that
    declares no projection publishes every model column — including ones the
    registered type projects away.

    This asserts the gap rather than the fix, on purpose: the README states it
    as a known boundary, and a README claim nothing pins is a README claim that
    rots. The day the library measures a model-bound subscription against the
    registered type's projection, this test fails and the README paragraph goes
    with it.
    """
    from blog.models import Comment

    from django_graphex.subscriptions import Subscription

    class _UnprojectedCommentSubscription(Subscription):
        """A throwaway subscription that declares no projection of its own."""

        class Meta:
            """Bind to Comment with no "only_fields" / "exclude_fields"."""

            model = Comment
            stream = "comments_probe"
            payload_mode = "full"

    published = _UnprojectedCommentSubscription._output_field_names()
    assert "internal_note" in published, published
    # The control: the registered query type hides exactly that column, so the
    # two surfaces genuinely disagree.
    from blog.schema import schema

    assert "internalNote" not in schema.graphql_schema.type_map["CommentType"].fields
