"""A nested child payload naming an id never reveals whether the row exists.

An id-bearing payload that does not resolve to a child the request can see is
refused with one fixed error, whether the row is hidden or absent, and writes
nothing. A payload without an id still creates a new child.
"""

from __future__ import annotations

from typing import Any

import pytest
from django.test import RequestFactory
from graphql import graphql_sync

from django_graphex.core import BooleanField, ObjectType
from django_graphex.mutation import DjangoModelMutation
from django_graphex.registry import get_global_registry
from django_graphex.schema import DjangoGraphQLSchema
from django_graphex.types import DjangoObjectType
from tests._schema_isolation import isolated_default_pair, isolated_pair
from tests.models import Author, Post, Tag
from tests.test_nested_reverse_one_orphan import O2OChild, O2OParent
from tests.test_nested_reverse_one_orphan import _adopt as _o2o_adopt
from tests.test_nested_reverse_one_orphan import _schema as _o2o_schema
from tests.test_nested_sd4_orphan_scope import (  # noqa: F401
    SD4Child,
    SD4ChildWriteType,
    SD4Parent,
    SD4ParentMutation,
    SD4ParentType,
    _execute,
    child_hosts,
)

MISSING = 987654


def _errors(result: Any) -> Any:
    """Return the comparable outcome of a generated update.

    Args:
        result: Native GraphQL execution result.

    Returns:
        The payload with ok and the error list.
    """
    assert result.errors is None, result.errors
    return next(iter(result.data.values())) if result.data else None


@pytest.mark.django_db(transaction=True)
@pytest.mark.parametrize("frontend", [SD4ParentType, SD4ParentMutation])
def test_reverse_fk_hidden_and_missing_ids_answer_identically(
    frontend: type[Any],
    child_hosts: Any,  # noqa: F811
) -> None:
    """Hidden and nonexistent reverse FK child ids give the same error.

    Args:
        frontend: Generated mutation frontend.
        child_hosts: Fixture selecting the visible child hosts.
    """
    child_hosts(SD4ChildWriteType)
    parent = SD4Parent.objects.create(tenant="A", name="p")
    other = SD4Parent.objects.create(tenant="B", name="q")
    hidden_orphan = SD4Child.objects.create(tenant="B", label="h1", parent=None)
    hidden_owned = SD4Child.objects.create(tenant="B", label="h2", parent=other)
    before = list(SD4Child.objects.values_list("id", "tenant", "label", "parent_id"))

    outcomes = []
    for child_id in (hidden_orphan.pk, hidden_owned.pk, MISSING):
        result = _execute(
            frontend,
            {
                "id": str(parent.pk),
                "children": [{"id": str(child_id), "label": "x", "tenant": "A"}],
            },
        )
        outcomes.append(result.data)

    assert outcomes[0]["updateParent"]["ok"] is False
    assert outcomes[0]["updateParent"]["errors"][0]["field"] == "children.id"
    errors = [o["updateParent"]["errors"] for o in outcomes]
    # Only the id in the message differs; the shape and wording are the same.
    for child_id, err in zip((hidden_orphan.pk, hidden_owned.pk, MISSING), errors):
        assert err == [
            {
                "field": errors[0][0]["field"],
                "messages": [f"SD4Child with id {child_id} does not exist."],
            }
        ]
    assert (
        list(SD4Child.objects.values_list("id", "tenant", "label", "parent_id"))
        == before
    )


@pytest.mark.django_db(transaction=True)
def test_reverse_fk_without_id_still_creates_and_own_child_still_updates(
    child_hosts: Any,  # noqa: F811
) -> None:
    """An id-less child is created and a child the parent owns is updated.

    Args:
        child_hosts: Fixture selecting the visible child hosts.
    """
    child_hosts(SD4ChildWriteType)
    parent = SD4Parent.objects.create(tenant="A", name="p")
    own = SD4Child.objects.create(tenant="A", label="own", parent=parent)

    created = _execute(
        SD4ParentType,
        {"id": str(parent.pk), "children": [{"label": "new", "tenant": "A"}]},
    )
    updated = _execute(
        SD4ParentType,
        {"id": str(parent.pk), "children": [{"id": str(own.pk), "label": "own2"}]},
    )

    assert created.data["updateParent"]["ok"] is True, created
    assert updated.data["updateParent"]["ok"] is True, updated
    assert sorted(parent.children.values_list("label", flat=True)) == ["new", "own2"]


@pytest.mark.django_db
def test_reverse_one_to_one_hidden_and_missing_ids_answer_identically() -> None:
    """Hidden and nonexistent reverse OneToOne child ids give the same error.

    Nothing is written for either id.
    """
    parent = O2OParent.objects.create(name="p")
    hidden = O2OChild.objects.create(tenant="B", label="hidden")
    with isolated_default_pair():
        schema = _o2o_schema(with_host=True)
        denied = _o2o_adopt(schema, parent, hidden.pk)
        missing = _o2o_adopt(schema, parent, MISSING)

    assert denied["ok"] is False and missing["ok"] is False
    assert denied["errors"] == [
        {
            "field": "child.id",
            "messages": [f"O2OChild with id {hidden.pk} does not exist."],
        }
    ]
    assert missing["errors"] == [
        {
            "field": "child.id",
            "messages": [f"O2OChild with id {MISSING} does not exist."],
        }
    ]
    parent.refresh_from_db()
    assert parent.name == "p"
    assert O2OChild.objects.count() == 1


def _tag_schema(scoped: bool) -> DjangoGraphQLSchema:
    """Build a Post update with nested tags, optionally scoping the tag output.

    Args:
        scoped: Whether the registered tag output type hides the tag labelled
            "hidden".

    Returns:
        The executable schema.
    """
    if scoped:

        class ScopedTag(DjangoObjectType):
            """Hide one tag from this request."""

            class Meta:
                """Bind the tag model."""

                model = Tag

            @classmethod
            def get_queryset(cls, queryset: Any, info: Any) -> Any:
                """Exclude the hidden tag.

                Args:
                    queryset: The tag queryset.
                    info: The request resolve info.

                Returns:
                    Queryset without the hidden tag.
                """
                return queryset.exclude(label="hidden")

    class PostMutation(DjangoModelMutation):
        """Expose the generated post update with nested tags."""

        class Meta:
            """Bind the post and its nested tags."""

            model = Post
            nested_fields = {"tags": Tag}

    _create, _delete, update = PostMutation.MutationFields()

    class Query(ObjectType):
        """Provide the required query root."""

        ready = BooleanField()

    class Mutation(ObjectType):
        """Expose the generated root."""

        post_update = update

    return DjangoGraphQLSchema(
        query=Query,
        mutation=Mutation,
        registries=isolated_pair(get_global_registry()),
    )


def _update_tags(schema: DjangoGraphQLSchema, post: Post, tag_id: int) -> Any:
    """Update a post naming a tag id together with child data.

    Args:
        schema: Schema under test.
        post: Post being updated.
        tag_id: Tag pk named in the nested payload.

    Returns:
        The mutation payload.
    """
    result = graphql_sync(
        schema.graphql_schema,
        'mutation { postUpdate(newPost: {id: "%s", title: "after", '
        'tags: [{id: "%s", label: "x"}]}) { ok errors { field messages } } }'
        % (post.pk, tag_id),
        context_value=RequestFactory().post("/graphql/"),
    )
    return _errors(result)


@pytest.mark.django_db
def test_m2m_hidden_and_missing_ids_answer_identically_and_write_nothing() -> None:
    """Hidden and nonexistent M2M child ids give the same error, no creation.

    The Tag table keeps only the hidden row.
    """
    author = Author.objects.create(name="a")
    post = Post.objects.create(title="before", author=author)
    hidden = Tag.objects.create(label="hidden")
    with isolated_default_pair():
        schema = _tag_schema(scoped=True)
        outcomes = [_update_tags(schema, post, t) for t in (hidden.pk, MISSING)]

    for tag_id, outcome in zip((hidden.pk, MISSING), outcomes):
        assert outcome["ok"] is False
        assert outcome["errors"] == [
            {
                "field": "tags",
                "messages": [f'Invalid pk "{tag_id}" - object does not exist.'],
            }
        ]
    post.refresh_from_db()
    assert post.title == "before"
    assert list(Tag.objects.values_list("label", flat=True)) == ["hidden"]


@pytest.mark.django_db
def test_m2m_missing_id_is_refused_without_an_output_scope() -> None:
    """An unknown M2M id with child data no longer creates a tag.

    The error matches the one a hidden id gets.
    """
    author = Author.objects.create(name="a")
    post = Post.objects.create(title="before", author=author)
    with isolated_default_pair():
        outcome = _update_tags(_tag_schema(scoped=False), post, MISSING)

    assert outcome["ok"] is False
    assert outcome["errors"][0]["field"] == "tags.id"
    assert outcome["errors"][0]["messages"] == [
        f"Tag with id {MISSING} does not exist."
    ]
    assert Tag.objects.count() == 0


@pytest.mark.django_db
def test_m2m_without_id_still_creates() -> None:
    """A tag payload without an id creates and links a new tag.

    Only an id-bearing payload is refused.
    """
    author = Author.objects.create(name="a")
    post = Post.objects.create(title="before", author=author)
    with isolated_default_pair():
        schema = _tag_schema(scoped=True)
        result = graphql_sync(
            schema.graphql_schema,
            'mutation { postUpdate(newPost: {id: "%s", tags: [{label: "fresh"}]})'
            " { ok errors { field messages } } }" % post.pk,
            context_value=RequestFactory().post("/graphql/"),
        )
    assert _errors(result)["ok"] is True
    assert list(post.tags.values_list("label", flat=True)) == ["fresh"]
