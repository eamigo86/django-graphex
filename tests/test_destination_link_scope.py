"""Generated relation-ID links honor the destination public row scope."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest
from django.db import connection
from django.db.models import QuerySet
from django.test import RequestFactory
from django.test.utils import CaptureQueriesContext
from graphql import graphql_sync

from django_graphex.core import BooleanField, ObjectType
from django_graphex.mutation import DjangoModelMutation
from django_graphex.registry import Registry, get_global_registry
from django_graphex.schema import DjangoGraphQLSchema
from django_graphex.types import DjangoModelType, DjangoObjectType
from tests._schema_isolation import isolated_default_pair, isolated_pair
from tests.models import Author, Post, Tag


@pytest.mark.django_db
@pytest.mark.parametrize("relation", ("author", "tags"))
@pytest.mark.parametrize("operation", ("create", "update"))
@pytest.mark.parametrize("host", ("model_type", "mutation"))
def test_hidden_relation_id_has_the_same_error_as_missing(
    relation: str, operation: str, host: str
) -> None:
    """A scoped-out FK or M2M ID is indistinguishable from an absent row.

    Args:
        relation: The generated relation input being checked.
        operation: The generated mutation action.
        host: The generated mutation frontend.
    """
    visible_author = Author.objects.create(name="VisibleAuthor")
    hidden_author = Author.objects.create(name="HiddenAuthor")
    hidden_tag = Tag.objects.create(label="HiddenTag")
    with isolated_default_pair():

        class ScopedAuthor(DjangoObjectType):
            """Publish only one author through the destination hook."""

            class Meta:
                """Bind the public author node."""

                model = Author

            @classmethod
            def get_queryset(cls, queryset: QuerySet, info: Any) -> QuerySet:
                """Hide the second author.

                Args:
                    queryset: The unscoped author queryset.
                    info: The request resolve info.

                Returns:
                    Authors allowed for this request.
                """
                return queryset.filter(pk=visible_author.pk)

        class ScopedTag(DjangoObjectType):
            """Hide every tag through the destination hook."""

            class Meta:
                """Bind the public tag node."""

                model = Tag

            @classmethod
            def get_queryset(cls, queryset: QuerySet, info: Any) -> QuerySet:
                """Hide every tag.

                Args:
                    queryset: The unscoped tag queryset.
                    info: The request resolve info.

                Returns:
                    An empty tag queryset.
                """
                return queryset.none()

        base = DjangoModelType if host == "model_type" else DjangoModelMutation

        class PostCRUD(base):
            """Expose generated post mutations."""

            class Meta:
                """Bind the post model."""

                model = Post

        create_post, _delete_post, update_post = PostCRUD.MutationFields()

        class Query(ObjectType):
            """Provide the schema's required query root."""

            ready = BooleanField()

        class Mutation(ObjectType):
            """Expose the generated create root."""

            post_create = create_post
            post_update = update_post

        schema = DjangoGraphQLSchema(
            query=Query,
            mutation=Mutation,
            registries=isolated_pair(get_global_registry()),
        )
        request = RequestFactory().post("/graphql/", content_type="application/json")

        existing = (
            Post.objects.create(title="original", body="", author=visible_author)
            if operation == "update"
            else None
        )

        def write(link_id: int, title: str) -> Any:
            """Execute a generated mutation with one destination link.

            Args:
                link_id: The requested related-row identifier.
                title: The title distinguishing attempted writes.

            Returns:
                The GraphQL execution result.
            """
            links = (
                f'author: "{link_id}"'
                if relation == "author"
                else f'author: "{visible_author.pk}", tags: ["{link_id}"]'
            )
            identifier = f'id: "{existing.pk}", ' if existing is not None else ""
            action = "postCreate" if operation == "create" else "postUpdate"
            return graphql_sync(
                schema.graphql_schema,
                f"mutation {{ {action}(newPost: {{"
                f'{identifier}title: "{title}", body: "", {links}'
                "}) { ok errors { field messages } } }",
                context_value=request,
            )

        hidden_id = hidden_author.pk if relation == "author" else hidden_tag.pk
        missing_id = hidden_id + 1000000
        hidden = write(hidden_id, "hidden-link")
        missing = write(missing_id, "missing-link")

    assert hidden.errors is None, hidden.errors
    assert missing.errors is None, missing.errors
    action = "postCreate" if operation == "create" else "postUpdate"
    hidden_errors = hidden.data[action]["errors"]
    missing_errors = missing.data[action]["errors"]
    assert hidden.data[action]["ok"] is False
    assert missing.data[action]["ok"] is False
    assert hidden_errors == [
        {
            "field": relation,
            "messages": [f'Invalid pk "{hidden_id}" - object does not exist.'],
        }
    ]
    assert missing_errors == [
        {
            "field": relation,
            "messages": [f'Invalid pk "{missing_id}" - object does not exist.'],
        }
    ]
    assert not Post.objects.filter(title__in=("hidden-link", "missing-link")).exists()
    if existing is not None:
        existing.refresh_from_db()
        assert existing.title == "original"
        assert existing.author_id == visible_author.pk
        assert not existing.tags.exists()


@pytest.mark.django_db
@pytest.mark.parametrize("relation", ("author", "tags"))
@pytest.mark.parametrize("payload_kind", ("id_only", "ignored_attributes"))
def test_nested_link_is_scoped_before_parent_save(
    relation: str, payload_kind: str
) -> None:
    """A nested link cannot reach hidden rows even if extras are ignored.

    Args:
        relation: The declared nested relation being linked.
        payload_kind: Whether the link carries ignored child attributes.
    """
    author = Author.objects.create(name="visible")
    tag = Tag.objects.create(label="hidden")
    with isolated_default_pair():

        class ScopedAuthor(DjangoObjectType):
            """Deny direct author links for this request."""

            class Meta:
                """Bind the author model."""

                model = Author

            @classmethod
            def get_queryset(cls, queryset: QuerySet, info: Any) -> QuerySet:
                """Exclude every author.

                Args:
                    queryset: The author queryset.
                    info: The request resolve info.

                Returns:
                    No visible authors.
                """
                return queryset.none()

        class ScopedTag(DjangoObjectType):
            """Deny direct tag links for this request."""

            class Meta:
                """Bind the tag model."""

                model = Tag

            @classmethod
            def get_queryset(cls, queryset: QuerySet, info: Any) -> QuerySet:
                """Exclude every tag.

                Args:
                    queryset: The tag queryset.
                    info: The request resolve info.

                Returns:
                    No visible tags.
                """
                return queryset.none()

        class NestedPost(DjangoModelType):
            """Expose both forms of nested ID-only reference."""

            class Meta:
                """Bind nested author and tags inputs."""

                model = Post
                nested_fields = {"author": Author, "tags": Tag}

        info = SimpleNamespace(
            context=RequestFactory().post("/graphql/"),
            schema=SimpleNamespace(
                extensions={"gdx_registry": isolated_pair(get_global_registry())}
            ),
        )
        identifier = author.pk if relation == "author" else tag.pk
        link_ids = (
            (identifier,)
            if relation == "tags" and payload_kind == "ignored_attributes"
            else (identifier, identifier + 1000000)
        )
        for link_id in link_ids:
            link = {"id": link_id}
            if payload_kind == "ignored_attributes":
                link["name" if relation == "author" else "label"] = "IGNORED"
            payload = {
                "title": f"attempt-{link_id}",
                "body": "",
                "author": {"id": author.pk},
            }
            if relation == "tags":
                payload["tags"] = [link]
                # The required author is ordinary nested creation in this arm.
                payload["author"] = {"name": "new-author"}
            else:
                payload["author"] = link
            result = NestedPost.create(
                None, info, **{NestedPost._meta.input_field_name: payload}
            )
            assert result.ok is False
            assert [(error.field, error.messages) for error in result.errors] == [
                (
                    relation,
                    [f'Invalid pk "{link_id}" - object does not exist.'],
                )
            ]

        if relation == "tags" and payload_kind == "ignored_attributes":
            # A missing id with child data is refused exactly like a hidden id:
            # an id-bearing payload never creates, so ids cannot be probed.
            missing = identifier + 1000000
            refused = NestedPost.create(
                None,
                info,
                **{
                    NestedPost._meta.input_field_name: {
                        "title": "child-create",
                        "body": "",
                        "author": {"name": "new-author"},
                        "tags": [{"id": missing, "label": "created"}],
                    }
                },
            )
            assert refused.ok is False
            assert [(error.field, error.messages) for error in refused.errors] == [
                ("tags", [f'Invalid pk "{missing}" - object does not exist.'])
            ]

    assert not Post.objects.exists()
    assert not Tag.objects.filter(label="created").exists()
    assert Author.objects.filter(pk=author.pk).count() == 1
    author.refresh_from_db()
    tag.refresh_from_db()
    assert author.name == "visible"
    assert tag.label == "hidden"


@pytest.mark.django_db
@pytest.mark.parametrize("relation", ("author", "tags"))
def test_existing_nested_child_update_is_not_reclassified_as_a_link(
    relation: str,
) -> None:
    """A child already linked to its parent keeps the existing write path.

    Args:
        relation: The forward FK or M2M child to update.
    """
    author = Author.objects.create(name="original-author")
    tag = Tag.objects.create(label="original-tag")
    post = Post.objects.create(title="original", body="", author=author)
    post.tags.add(tag)
    with isolated_default_pair():

        class AuthorOutput(DjangoObjectType):
            """Expose authors with an active but allowing row-scope hook."""

            class Meta:
                """Bind the author model."""

                model = Author

            @classmethod
            def get_queryset(cls, queryset: QuerySet, info: Any) -> QuerySet:
                """Allow the existing author.

                Args:
                    queryset: Candidate author rows.
                    info: The request resolve info.

                Returns:
                    All candidate author rows.
                """
                return queryset

        class TagOutput(DjangoObjectType):
            """Expose tags with an active but allowing row-scope hook."""

            class Meta:
                """Bind the tag model."""

                model = Tag

            @classmethod
            def get_queryset(cls, queryset: QuerySet, info: Any) -> QuerySet:
                """Allow the existing tag.

                Args:
                    queryset: Candidate tag rows.
                    info: The request resolve info.

                Returns:
                    All candidate tag rows.
                """
                return queryset

        class NestedPost(DjangoModelType):
            """Expose nested child writes on the post update path."""

            class Meta:
                """Bind the related models to nested update inputs."""

                model = Post
                nested_fields = {"author": Author, "tags": Tag}

        info = SimpleNamespace(
            context=RequestFactory().post("/graphql/"),
            schema=SimpleNamespace(
                extensions={"gdx_registry": isolated_pair(get_global_registry())}
            ),
        )
        child = (
            {"id": author.pk, "name": "updated-author"}
            if relation == "author"
            else [{"id": tag.pk, "label": "updated-tag"}]
        )
        result = NestedPost.update(
            None,
            info,
            **{
                NestedPost._meta.input_field_name: {
                    "id": post.pk,
                    relation: child,
                }
            },
        )

    assert result.ok is True
    author.refresh_from_db()
    tag.refresh_from_db()
    assert author.name == (
        "updated-author" if relation == "author" else "original-author"
    )
    assert tag.label == ("updated-tag" if relation == "tags" else "original-tag")


@pytest.mark.django_db
def test_request_registry_not_global_registry_selects_destination_scope() -> None:
    """A request-specific Registry must not borrow the global target hook.

    The allowing and denying schemas share a model but not a Registry.
    """
    author = Author.objects.create(name="target")
    allowed = Registry()
    denied = Registry()

    class AllowedAuthor(DjangoObjectType):
        """Allow the author in the first public schema."""

        class Meta:
            """Bind a public type to the allowing Registry."""

            model = Author
            registry = allowed

        @classmethod
        def get_queryset(cls, queryset: QuerySet, info: Any) -> QuerySet:
            """Return the unchanged queryset.

            Args:
                queryset: The candidate author rows.
                info: The request resolve info.

            Returns:
                All candidate author rows.
            """
            return queryset

    class DeniedAuthor(DjangoObjectType):
        """Hide the author in the second public schema."""

        class Meta:
            """Bind a public type to the denying Registry."""

            model = Author
            registry = denied

        @classmethod
        def get_queryset(cls, queryset: QuerySet, info: Any) -> QuerySet:
            """Return an empty queryset.

            Args:
                queryset: The candidate author rows.
                info: The request resolve info.

            Returns:
                No author rows.
            """
            return queryset.none()

    with isolated_default_pair():

        class PostCRUD(DjangoModelType):
            """Create posts under either public request schema."""

            class Meta:
                """Bind the post model."""

                model = Post

        def create(registry: Registry, title: str) -> Any:
            """Create using one request Registry.

            Args:
                registry: The request's public type registry.
                title: The post title for distinguishing writes.

            Returns:
                The generated mutation payload.
            """
            info = SimpleNamespace(
                context=RequestFactory().post("/graphql/"),
                schema=SimpleNamespace(
                    extensions={"gdx_registry": isolated_pair(registry)}
                ),
            )
            return PostCRUD.create(
                None,
                info,
                **{
                    PostCRUD._meta.input_field_name: {
                        "title": title,
                        "body": "",
                        "author": author.pk,
                    }
                },
            )

        rejected = create(denied, "denied")
        accepted = create(allowed, "allowed")

    assert rejected.ok is False
    assert [(error.field, error.messages) for error in rejected.errors] == [
        ("author", [f'Invalid pk "{author.pk}" - object does not exist.'])
    ]
    assert accepted.ok is True
    assert list(Post.objects.values_list("title", flat=True)) == ["allowed"]


@pytest.mark.django_db
def test_unregistered_destination_adds_no_fk_lookup() -> None:
    """The default output hook adds no destination existence lookup.

    Baseline backend validation may query the author, so compare the same
    mutation before and after registering its default destination output.
    """
    author = Author.objects.create(name="unscoped")
    with isolated_default_pair():

        class PostCRUD(DjangoModelType):
            """Expose an ordinary generated create path."""

            class Meta:
                """Bind the post model without a destination output node."""

                model = Post

        info = SimpleNamespace(context=RequestFactory().post("/graphql/"))
        with CaptureQueriesContext(connection) as baseline_queries:
            result = PostCRUD.create(
                None,
                info,
                **{
                    PostCRUD._meta.input_field_name: {
                        "title": "before-output",
                        "body": "",
                        "author": author.pk,
                    }
                },
            )

        class AuthorOutput(DjangoObjectType):
            """Register a target without an overridden row-scope hook."""

            class Meta:
                """Bind the author model for the default-hook fast path."""

                model = Author

        assert AuthorOutput._meta.model is Author
        with CaptureQueriesContext(connection) as registered_queries:
            registered = PostCRUD.create(
                None,
                info,
                **{
                    PostCRUD._meta.input_field_name: {
                        "title": "after-output",
                        "body": "",
                        "author": author.pk,
                    }
                },
            )

    assert result.ok is True
    assert registered.ok is True
    author_select = f'SELECT "{Author._meta.db_table}".'
    assert sum(
        query["sql"].startswith(author_select) for query in registered_queries
    ) == sum(query["sql"].startswith(author_select) for query in baseline_queries)
    assert set(Post.objects.values_list("author_id", flat=True)) == {author.pk}


@pytest.mark.django_db
def test_destination_hook_for_wrong_model_fails_before_write() -> None:
    """A foreign model queryset cannot authorize a matching numeric ID.

    Even equal numeric keys on unrelated models do not make a valid scope.
    """
    author = Author.objects.create(name="target")
    Tag.objects.create(label="same-numeric-id")
    with isolated_default_pair():

        class WrongAuthor(DjangoObjectType):
            """Expose an invalid hook result for the author model."""

            class Meta:
                """Bind the author model."""

                model = Author

            @classmethod
            def get_queryset(cls, queryset: QuerySet, info: Any) -> QuerySet:
                """Return rows of the wrong model.

                Args:
                    queryset: The intended author queryset.
                    info: The request resolve info.

                Returns:
                    The unrelated tag queryset.
                """
                return Tag.objects.all()

        class PostCRUD(DjangoModelType):
            """Provide a generated create using the invalid target hook."""

            class Meta:
                """Bind the post model."""

                model = Post

        assert WrongAuthor._meta.model is Author
        info = SimpleNamespace(context=RequestFactory().post("/graphql/"))
        with pytest.raises(TypeError, match="expected Author"):
            PostCRUD.create(
                None,
                info,
                **{
                    PostCRUD._meta.input_field_name: {
                        "title": "not-written",
                        "body": "",
                        "author": author.pk,
                    }
                },
            )

    assert not Post.objects.exists()
