"""Preserve supported destination scope hooks and queryset membership."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest
from django.db import connection, models
from django.db.models import QuerySet
from django.test import RequestFactory
from django.test.utils import isolate_apps
from graphql import graphql_sync

from django_graphex.core import BooleanField, ObjectType
from django_graphex.fields import DjangoFilterListField
from django_graphex.registry import get_global_registry
from django_graphex.schema import DjangoGraphQLSchema
from django_graphex.types import DjangoModelType, DjangoObjectType
from django_graphex.utils import apply_object_type_get_queryset
from tests._schema_isolation import isolated_default_pair, isolated_pair
from tests.models import Author, Post


def _info() -> SimpleNamespace:
    """Build a request context bound to the isolated public Registry.

    Returns:
        A lightweight resolve-info object for direct generated writes.
    """
    return SimpleNamespace(
        context=RequestFactory().post("/graphql/"),
        schema=SimpleNamespace(
            extensions={"gdx_registry": isolated_pair(get_global_registry())}
        ),
    )


def _schema(host: type[DjangoModelType], output: type[DjangoObjectType]) -> Any:
    """Build public query and generated mutation roots for a scoped model.

    Args:
        host: The generated mutation frontend.
        output: The registered public destination type.

    Returns:
        The executable GraphQL schema.
    """
    create, _delete, _update = host.MutationFields()

    class Query(ObjectType):
        """Expose the destination list and required query root."""

        ready = BooleanField()
        authors = DjangoFilterListField(output)

    class Mutation(ObjectType):
        """Expose the generated create mutation."""

        post_create = create

    return DjangoGraphQLSchema(
        query=Query,
        mutation=Mutation,
        registries=isolated_pair(get_global_registry()),
    ).graphql_schema


@pytest.mark.django_db
@pytest.mark.parametrize("kind", ("staticmethod", "plain_function", "callable_object"))
def test_supported_callable_destination_hooks_allow_visible_id(kind: str) -> None:
    """A public callable hook must not be mistaken for the inherited default.

    Args:
        kind: The supported callable form registered on the public type.
    """
    visible = Author.objects.create(name="visible")
    hidden = Author.objects.create(name="hidden")
    with isolated_default_pair():

        def scope(queryset: QuerySet, info: Any) -> QuerySet:
            """Limit authors to the visible row.

            Args:
                queryset: The unscoped author queryset.
                info: The request resolve info.

            Returns:
                The visible author queryset.
            """
            return queryset.filter(pk=visible.pk)

        class CallableScope:
            """Represent a callable-object row hook."""

            def __call__(self, queryset: QuerySet, info: Any) -> QuerySet:
                """Apply the same row scope.

                Args:
                    queryset: The unscoped author queryset.
                    info: The request resolve info.

                Returns:
                    The visible author queryset.
                """
                return scope(queryset, info)

        hook: Any = {
            "staticmethod": staticmethod(scope),
            "plain_function": scope,
            "callable_object": CallableScope(),
        }[kind]

        class ScopedAuthor(DjangoObjectType):
            """Expose the destination model."""

            class Meta:
                """Bind the author model."""

                model = Author

        ScopedAuthor.get_queryset = hook

        class PostCRUD(DjangoModelType):
            """Generate a post create mutation."""

            class Meta:
                """Bind the post model."""

                model = Post

        schema = _schema(PostCRUD, ScopedAuthor)
        assert list(
            apply_object_type_get_queryset(Author.objects.all(), ScopedAuthor, _info())
        ) == [visible]

        def create(identifier: int, title: str) -> Any:
            """Attempt one generated relation-ID link.

            Args:
                identifier: The destination author identifier.
                title: The distinguishing post title.

            Returns:
                The GraphQL execution result.
            """
            return graphql_sync(
                schema,
                "mutation { postCreate(newPost: {"
                f'title: "{title}", body: "", author: "{identifier}"'
                "}) { ok errors { field messages } } }",
                context_value=_info().context,
            )

        allowed = create(visible.pk, "allowed")
        denied = create(hidden.pk, "denied")
        assert allowed.errors is None, allowed.formatted
        assert allowed.data["postCreate"]["ok"] is True
        assert denied.errors is None, denied.formatted
        assert denied.data["postCreate"]["ok"] is False
        assert list(Post.objects.values_list("title", flat=True)) == ["allowed"]


@pytest.mark.django_db(transaction=True)
@isolate_apps()
def test_mti_parent_table_cannot_authorize_child_id() -> None:
    """An annotated parent-table queryset cannot scope a child-table link.

    The child's own AutoField and concrete table must remain authoritative.
    """

    class Parent(models.Model):
        """Own the base table of an MTI hierarchy."""

        label = models.CharField(max_length=20)

        class Meta:
            """Bind the disposable test app."""

            app_label = "sd3compat"

    class Child(Parent):
        """Own a distinct concrete child table and identifier."""

        child_key = models.AutoField(primary_key=True)

        class Meta:
            """Bind the disposable test app."""

            app_label = "sd3compat"

    class Holder(models.Model):
        """Reference the child through a generated ID link."""

        target = models.ForeignKey(Child, on_delete=models.CASCADE)
        title = models.CharField(max_length=20)

        class Meta:
            """Bind the disposable test app."""

            app_label = "sd3compat"

    with connection.schema_editor() as editor:
        for model in (Parent, Child, Holder):
            editor.create_model(model)
    try:
        child = Child.objects.create(label="private")
        with isolated_default_pair():

            class ScopedChild(DjangoObjectType):
                """Register the child destination."""

                class Meta:
                    """Bind the child model."""

                    model = Child

                @classmethod
                def get_queryset(cls, queryset: QuerySet, info: Any) -> QuerySet:
                    """Return an invalid parent-table scope with matching ID data.

                    Args:
                        queryset: The child queryset being scoped.
                        info: The request resolve info.

                    Returns:
                        A parent queryset, which must be rejected.
                    """
                    return Parent.objects.annotate(child_key=models.F("pk")).filter(
                        pk=child.pk
                    )

            class HolderCRUD(DjangoModelType):
                """Generate a holder create mutation."""

                class Meta:
                    """Bind the holder model."""

                    model = Holder

            with pytest.raises(TypeError, match="expected Child"):
                HolderCRUD.create(
                    None,
                    _info(),
                    **{
                        HolderCRUD._meta.input_field_name: {
                            "title": "forbidden",
                            "target": child.pk,
                        }
                    },
                )
            assert not Holder.objects.exists()
    finally:
        with connection.schema_editor() as editor:
            for model in (Holder, Child, Parent):
                editor.delete_model(model)


@pytest.mark.django_db
@isolate_apps()
def test_same_concrete_proxy_queryset_still_allows_link() -> None:
    """A proxy scope remains valid because it uses the destination table.

    A proxy class changes model identity without changing concrete storage.
    """

    class ProxyAuthor(Author):
        """Use the author's concrete table through a proxy class."""

        class Meta:
            """Bind the disposable test app without creating a table."""

            app_label = "sd3compat"
            proxy = True

    visible = Author.objects.create(name="proxy-visible")
    with isolated_default_pair():

        class ScopedAuthor(DjangoObjectType):
            """Expose an author type scoped through a proxy queryset."""

            class Meta:
                """Bind the underlying author model."""

                model = Author

            @classmethod
            def get_queryset(cls, queryset: QuerySet, info: Any) -> QuerySet:
                """Return a valid same-table proxy scope.

                Args:
                    queryset: The candidate author queryset.
                    info: The request resolve info.

                Returns:
                    The visible proxy-author queryset.
                """
                return ProxyAuthor.objects.filter(pk=visible.pk)

        class PostCRUD(DjangoModelType):
            """Generate a post create mutation."""

            class Meta:
                """Bind the post model."""

                model = Post

        result = PostCRUD.create(
            None,
            _info(),
            **{
                PostCRUD._meta.input_field_name: {
                    "title": "proxy-link",
                    "author": visible.pk,
                }
            },
        )
        assert result.ok is True
        assert Post.objects.get().author_id == visible.pk


@pytest.mark.django_db
@pytest.mark.parametrize("shape", ("duplicate_join", "slice"))
def test_visible_id_remains_linkable_through_supported_queryset_shapes(
    shape: str,
) -> None:
    """Destination membership must tolerate JOIN duplicates and finite slices.

    Args:
        shape: The supported public queryset shape to exercise.
    """
    first = Author.objects.create(name="first")
    outside = Author.objects.create(name="outside")
    Post.objects.create(title="existing-one", author=first)
    Post.objects.create(title="existing-two", author=first)
    with isolated_default_pair():

        class ScopedAuthor(DjangoObjectType):
            """Publish a JOIN or ordered slice of the destination model."""

            class Meta:
                """Bind the author model."""

                model = Author

            @classmethod
            def get_queryset(cls, queryset: QuerySet, info: Any) -> QuerySet:
                """Build the public author queryset.

                Args:
                    queryset: The unscoped author queryset.
                    info: The request resolve info.

                Returns:
                    A duplicated JOIN or one-row ordered slice.
                """
                if shape == "duplicate_join":
                    return queryset.filter(posts__title__startswith="existing")
                return queryset.order_by("pk")[:1]

        class PostCRUD(DjangoModelType):
            """Generate a post create mutation."""

            class Meta:
                """Bind the post model."""

                model = Post

        schema = _schema(PostCRUD, ScopedAuthor)
        root = graphql_sync(
            schema, "{ authors { id name } }", context_value=_info().context
        )
        assert root.errors is None, root.formatted
        assert root.data["authors"]
        assert {row["id"] for row in root.data["authors"]} == {str(first.pk)}

        def create(identifier: int, title: str) -> Any:
            """Attempt one generated relation-ID link.

            Args:
                identifier: The requested author identifier.
                title: The attempted post title.

            Returns:
                The GraphQL execution result.
            """
            return graphql_sync(
                schema,
                "mutation { postCreate(newPost: {"
                f'title: "{title}", body: "", author: "{identifier}"'
                "}) { ok errors { field messages } } }",
                context_value=_info().context,
            )

        allowed = create(first.pk, "allowed")
        denied = create(outside.pk, "outside")
        assert allowed.errors is None, allowed.formatted
        assert allowed.data["postCreate"]["ok"] is True
        assert denied.errors is None, denied.formatted
        assert denied.data["postCreate"]["ok"] is False
        assert list(
            Post.objects.filter(title__in=("allowed", "outside")).values_list(
                "title", flat=True
            )
        ) == ["allowed"]
