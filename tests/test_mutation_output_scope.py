"""Generated update and delete honor the registered output type row scope."""

from __future__ import annotations

from typing import Any

import pytest
from django.db import connection
from django.db.models import QuerySet
from django.test import RequestFactory
from django.test.utils import CaptureQueriesContext
from graphql import graphql_sync

from django_graphex.core import BooleanField, ObjectType
from django_graphex.mutation import DjangoModelMutation
from django_graphex.registry import get_global_registry
from django_graphex.schema import DjangoGraphQLSchema
from django_graphex.types import DjangoModelType, DjangoObjectType
from tests._schema_isolation import isolated_default_pair, isolated_pair
from tests.models import Author, AuthorProfile, Post, Tag
from tests.test_nested_sd4_orphan_scope import (  # noqa: F401
    SD4Child,
    SD4Parent,
    SD4ParentType,
    _execute,
    child_hosts,
)


def _schema(
    host: str, *, scoped: bool, host_scope: bool = False
) -> DjangoGraphQLSchema:
    """Build post update and delete roots, optionally scoping the output type.

    Args:
        host: Either "model_type" or "mutation", the generated frontend.
        scoped: Whether the public post type hides titles starting with hidden.
        host_scope: Whether the host additionally hides titles ending with host.

    Returns:
        The executable schema.
    """
    if scoped:

        class ScopedPost(DjangoObjectType):
            """Publish only posts whose title does not start with hidden."""

            class Meta:
                """Bind the public post node."""

                model = Post

            @classmethod
            def get_queryset(cls, queryset: QuerySet, info: Any) -> QuerySet:
                """Hide the posts whose title starts with hidden.

                Args:
                    queryset: The unscoped post queryset.
                    info: The request resolve info.

                Returns:
                    Posts allowed for this request.
                """
                return queryset.exclude(title__startswith="hidden")

    base = DjangoModelType if host == "model_type" else DjangoModelMutation

    class PostCRUD(base):
        """Expose generated post mutations."""

        class Meta:
            """Bind the post model."""

            model = Post

        if host_scope:

            @classmethod
            def filter_queryset(
                cls, qs: QuerySet, info: Any, **kwargs: Any
            ) -> QuerySet:
                """Hide the posts whose title ends with host.

                Args:
                    qs: The unscoped post queryset.
                    info: The request resolve info.
                    **kwargs: Unused filtering options.

                Returns:
                    Posts allowed by the host.
                """
                return qs.exclude(title__endswith="host")

    _create, delete_post, update_post = PostCRUD.MutationFields()

    class Query(ObjectType):
        """Provide the schema's required query root."""

        ready = BooleanField()

    class Mutation(ObjectType):
        """Expose the generated roots."""

        post_update = update_post
        post_delete = delete_post

    return DjangoGraphQLSchema(
        query=Query,
        mutation=Mutation,
        registries=isolated_pair(get_global_registry()),
    )


def _run(schema: DjangoGraphQLSchema, query: str) -> Any:
    """Execute one mutation and return its payload.

    Args:
        schema: Schema under test.
        query: Mutation document.

    Returns:
        The payload of the only root field.
    """
    result = graphql_sync(
        schema.graphql_schema,
        query,
        context_value=RequestFactory().post("/graphql/"),
    )
    assert result.errors is None, result.errors
    return next(iter(result.data.values()))


def _update(schema: DjangoGraphQLSchema, pk: int) -> Any:
    """Rename a post through the generated update.

    Args:
        schema: Schema under test.
        pk: Post primary key.

    Returns:
        The mutation payload.
    """
    return _run(
        schema,
        f'mutation {{ postUpdate(newPost: {{id: "{pk}", title: "changed"}}) '
        "{ ok errors { field messages } } }",
    )


def _delete(schema: DjangoGraphQLSchema, pk: int) -> Any:
    """Delete a post through the generated delete.

    Args:
        schema: Schema under test.
        pk: Post primary key.

    Returns:
        The mutation payload.
    """
    return _run(
        schema,
        f'mutation {{ postDelete(id: "{pk}") {{ ok errors {{ field messages }} }} }}',
    )


@pytest.mark.django_db
@pytest.mark.parametrize("host", ("model_type", "mutation"))
def test_hidden_post_update_and_delete_answer_like_a_missing_id(host: str) -> None:
    """A row the output type hides cannot be edited or deleted by id.

    Args:
        host: The generated mutation frontend.
    """
    author = Author.objects.create(name="a")
    hidden = Post.objects.create(title="hidden-post", body="", author=author)
    with isolated_default_pair():
        schema = _schema(host, scoped=True)
        missing_id = hidden.pk + 1000000
        hidden_update = _update(schema, hidden.pk)
        missing_update = _update(schema, missing_id)
        hidden_delete = _delete(schema, hidden.pk)
        missing_delete = _delete(schema, missing_id)

    for payload, pk in (
        (hidden_update, hidden.pk),
        (missing_update, missing_id),
        (hidden_delete, hidden.pk),
        (missing_delete, missing_id),
    ):
        assert payload["ok"] is False
        assert payload["errors"] == [
            {"field": "id", "messages": [f"Post with id {pk} does not exist."]}
        ]
    hidden.refresh_from_db()
    assert hidden.title == "hidden-post"


@pytest.mark.django_db
@pytest.mark.parametrize("host", ("model_type", "mutation"))
def test_visible_post_still_updates_and_deletes(host: str) -> None:
    """A row the output type exposes is still written normally.

    Args:
        host: The generated mutation frontend.
    """
    author = Author.objects.create(name="a")
    first = Post.objects.create(title="visible-1", body="", author=author)
    second = Post.objects.create(title="visible-2", body="", author=author)
    with isolated_default_pair():
        schema = _schema(host, scoped=True)
        updated = _update(schema, first.pk)
        deleted = _delete(schema, second.pk)

    assert updated["ok"] is True, updated
    assert deleted["ok"] is True, deleted
    first.refresh_from_db()
    assert first.title == "changed"
    assert not Post.objects.filter(pk=second.pk).exists()


@pytest.mark.django_db
@pytest.mark.parametrize("host", ("model_type", "mutation"))
def test_host_scope_still_applies_with_the_output_scope(host: str) -> None:
    """The output scope intersects with, and does not replace, the host scope.

    Args:
        host: The generated mutation frontend.
    """
    author = Author.objects.create(name="a")
    host_hidden = Post.objects.create(title="a-host", body="", author=author)
    with isolated_default_pair():
        schema = _schema(host, scoped=True, host_scope=True)
        update = _update(schema, host_hidden.pk)
        delete = _delete(schema, host_hidden.pk)

    assert update["ok"] is False and delete["ok"] is False
    assert Post.objects.filter(pk=host_hidden.pk, title="a-host").exists()


@pytest.mark.django_db
@pytest.mark.parametrize("host", ("model_type", "mutation"))
def test_default_output_type_hook_adds_no_query(host: str) -> None:
    """An output type keeping the default hook costs the same queries as none.

    Args:
        host: The generated mutation frontend.
    """
    author = Author.objects.create(name="a")
    post = Post.objects.create(title="visible", body="", author=author)
    with isolated_default_pair():
        plain = _schema(host, scoped=False)
        with CaptureQueriesContext(connection) as plain_queries:
            assert _update(plain, post.pk)["ok"] is True
    with isolated_default_pair():
        scoped = _schema(host, scoped=True)
        with CaptureQueriesContext(connection) as scoped_queries:
            assert _update(scoped, post.pk)["ok"] is True

    assert len(scoped_queries) == len(plain_queries)


@pytest.mark.django_db(transaction=True)
@pytest.mark.parametrize("hidden_by_output", (True, False))
def test_nested_reverse_child_update_honors_the_child_output_scope(
    hidden_by_output: bool,
    child_hosts: Any,  # noqa: F811
) -> None:
    """A child hidden by its output type cannot be rewritten through a parent.

    Args:
        hidden_by_output: Whether the child output type hides the child.
        child_hosts: Fixture selecting the visible child hosts.
    """
    child_hosts()
    parent = SD4Parent.objects.create(tenant="A", name="p")
    own = SD4Child.objects.create(tenant="A", label="secret-own", parent=parent)
    with isolated_default_pair():

        class ScopedChild(DjangoObjectType):
            """Publish the child unless its label starts with secret."""

            class Meta:
                """Bind the public child node."""

                model = SD4Child

            @classmethod
            def get_queryset(cls, queryset: QuerySet, info: Any) -> QuerySet:
                """Hide secret children when asked to.

                Args:
                    queryset: The unscoped child queryset.
                    info: The request resolve info.

                Returns:
                    Children allowed for this request.
                """
                if hidden_by_output:
                    return queryset.exclude(label__startswith="secret")
                return queryset

        result = _execute(
            SD4ParentType,
            {"id": str(parent.pk), "children": [{"id": str(own.pk), "label": "x"}]},
        )

    payload = result.data["updateParent"]
    own.refresh_from_db()
    if hidden_by_output:
        assert payload["ok"] is False
        assert payload["errors"] == [
            {
                "field": "children.id",
                "messages": [f"SD4Child with id {own.pk} does not exist."],
            }
        ]
        assert own.label == "secret-own"
    else:
        assert payload["ok"] is True, payload
        assert own.label == "x"


@pytest.mark.django_db
def test_nested_m2m_linked_child_update_honors_the_child_output_scope() -> None:
    """A linked tag hidden by its output type cannot be rewritten by data.

    The tag keeps its label.
    """
    author = Author.objects.create(name="a")
    post = Post.objects.create(title="p", body="", author=author)
    tag = Tag.objects.create(label="hidden-tag")
    post.tags.add(tag)
    with isolated_default_pair():

        class ScopedTag(DjangoObjectType):
            """Hide tags whose label starts with hidden."""

            class Meta:
                """Bind the public tag node."""

                model = Tag

            @classmethod
            def get_queryset(cls, queryset: QuerySet, info: Any) -> QuerySet:
                """Hide hidden tags.

                Args:
                    queryset: The unscoped tag queryset.
                    info: The request resolve info.

                Returns:
                    Visible tags.
                """
                return queryset.exclude(label__startswith="hidden")

        class PostCRUD(DjangoModelMutation):
            """Expose a post update with nested tags."""

            class Meta:
                """Bind the post and its tags."""

                model = Post
                nested_fields = {"tags": Tag}

        _c, _d, update = PostCRUD.MutationFields()

        class Query(ObjectType):
            """Provide the required query root."""

            ready = BooleanField()

        class Mutation(ObjectType):
            """Expose the update root."""

            post_update = update

        schema = DjangoGraphQLSchema(
            query=Query,
            mutation=Mutation,
            registries=isolated_pair(get_global_registry()),
        )
        payload = _run(
            schema,
            f'mutation {{ postUpdate(newPost: {{id: "{post.pk}", '
            f'tags: [{{id: "{tag.pk}", label: "pwned"}}]}}) '
            "{ ok errors { field messages } } }",
        )

    assert payload["ok"] is False
    assert payload["errors"] == [
        {"field": "tags.id", "messages": [f"Tag with id {tag.pk} does not exist."]}
    ]
    tag.refresh_from_db()
    assert tag.label == "hidden-tag"


@pytest.mark.django_db
def test_nested_forward_update_with_data_is_scoped_but_id_only_is_not() -> None:
    """Writing fields of a hidden current target fails; an id-only re-send is a no-op.

    The hidden author keeps its name.
    """
    from tests.test_destination_link_one_to_one import _profile_schema

    author = Author.objects.create(name="hidden-current")
    profile = AuthorProfile.objects.create(author=author, bio="original")
    with isolated_default_pair():
        schema = _profile_schema(nested=True)
        with_data = _run(
            schema,
            f'mutation {{ profileUpdate(newAuthorprofile: {{id: "{profile.pk}", '
            f'author: {{id: "{author.pk}", name: "pwned"}}}}) '
            "{ ok errors { field messages } } }",
        )
        id_only = _run(
            schema,
            f'mutation {{ profileUpdate(newAuthorprofile: {{id: "{profile.pk}", '
            f'bio: "edited", author: {{id: "{author.pk}"}}}}) '
            "{ ok errors { field messages } } }",
        )

    assert with_data["ok"] is False
    assert with_data["errors"] == [
        {
            "field": "author.id",
            "messages": [f"Author with id {author.pk} does not exist."],
        }
    ]
    assert id_only["ok"] is True, id_only
    author.refresh_from_db()
    assert author.name == "hidden-current"
