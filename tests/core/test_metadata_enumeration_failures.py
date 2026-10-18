"""Metadata enumeration failures must not publish partial model types."""

from __future__ import annotations

import inspect
import os
from collections.abc import Callable
from typing import NoReturn

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "tests.settings")

import django
import graphql
import pytest

django.setup()

from django.core.exceptions import ImproperlyConfigured  # noqa: E402
from graphql import (  # noqa: E402
    GraphQLObjectType,
    GraphQLSchema,
    GraphQLString,
    print_schema,
)

from django_graphex.core import ObjectType, field  # noqa: E402
from django_graphex.core.base import recompile_fields  # noqa: E402
from django_graphex.core.output_compiler import compile_output_fields  # noqa: E402
from django_graphex.registry import Registry  # noqa: E402
from django_graphex.schema import DjangoGraphQLSchema  # noqa: E402
from django_graphex.types import DjangoObjectType, _model_derived_fields  # noqa: E402
from tests.models import (  # noqa: E402
    Author,
    AuthorProfile,
    Category,
    Comment,
    Post,
    Tag,
)

_SCHEMA_REGISTRY: Registry | None = None


def _raising_get_fields(error: RuntimeError) -> Callable[..., object]:
    """Return a metadata enumerator that raises the supplied exception.

    Args:
        error: Original exception instance to preserve as the cause.

    Returns:
        An enumerator that raises the original exception instance.
    """

    def raise_original(*args: object, **kwargs: object) -> NoReturn:
        """Raise the original metadata error.

        Args:
            *args: Ignored Django metadata arguments.
            **kwargs: Ignored Django metadata options.

        Raises:
            RuntimeError: The original metadata failure.
        """
        raise error

    return raise_original


def _cause_chain(error: BaseException) -> list[BaseException]:
    """Return causes and contexts through native lazy GraphQL wrappers.

    Args:
        error: The outer error raised while building the schema.

    Returns:
        The error and all distinct linked exceptions.
    """
    chain = [error]
    for current in chain:
        for linked in (current.__cause__, current.__context__):
            if linked is not None and all(linked is not seen for seen in chain):
                chain.append(linked)
    return chain


def _public_author_schema(
    name_prefix: str, prepare: Callable[[], None] | None = None
) -> GraphQLSchema:
    """Build a public Author schema with registered relation target types.

    Args:
        name_prefix: Unique type-name prefix for this schema build.
        prepare: Optional metadata patch installed just before construction.

    Returns:
        The public GraphQL schema.
    """
    global _SCHEMA_REGISTRY
    _SCHEMA_REGISTRY = Registry()

    class AuthorNode(DjangoObjectType):
        """Author output type for this schema."""

        class Meta:
            """Bind the Author model to the isolated registry."""

            model = Author
            registry = _SCHEMA_REGISTRY
            name = f"{name_prefix}AuthorNode"

    class PostNode(DjangoObjectType):
        """Post relation target."""

        class Meta:
            """Bind Post to the schema registry."""

            model = Post
            registry = _SCHEMA_REGISTRY
            name = f"{name_prefix}PostNode"

    class CommentNode(DjangoObjectType):
        """Comment relation target."""

        class Meta:
            """Bind Comment to the schema registry."""

            model = Comment
            registry = _SCHEMA_REGISTRY
            name = f"{name_prefix}CommentNode"

    class TagNode(DjangoObjectType):
        """Tag relation target."""

        class Meta:
            """Bind Tag to the schema registry."""

            model = Tag
            registry = _SCHEMA_REGISTRY
            name = f"{name_prefix}TagNode"

    class CategoryNode(DjangoObjectType):
        """Category relation target."""

        class Meta:
            """Bind Category to the schema registry."""

            model = Category
            registry = _SCHEMA_REGISTRY
            name = f"{name_prefix}CategoryNode"

    class ProfileNode(DjangoObjectType):
        """Author profile relation target."""

        class Meta:
            """Bind AuthorProfile to the schema registry."""

            model = AuthorProfile
            registry = _SCHEMA_REGISTRY
            name = f"{name_prefix}ProfileNode"

    class Query(ObjectType):
        """Expose the Author type through public schema construction."""

        author = field(AuthorNode)

    if prepare is not None:
        prepare()
    return DjangoGraphQLSchema(query=Query).graphql_schema


def test_model_derived_fields_identifies_model_and_preserves_cause(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The shared native enumerator must abort rather than use concrete fields.

    Args:
        monkeypatch: Replaces Django's metadata enumeration for Author.
    """
    original = RuntimeError("direct model metadata failure")
    monkeypatch.setattr(Author._meta, "get_fields", _raising_get_fields(original))

    with pytest.raises(ImproperlyConfigured, match=r"tests\.Author") as caught:
        _model_derived_fields(Author)

    assert caught.value.__cause__ is original


def test_output_compiler_identifies_model_and_preserves_cause(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The native output compiler must abort on metadata failure.

    Args:
        monkeypatch: Replaces Django's metadata enumeration for Author.
    """
    original = RuntimeError("direct compiler metadata failure")
    monkeypatch.setattr(Author._meta, "get_fields", _raising_get_fields(original))

    with pytest.raises(ImproperlyConfigured, match=r"tests\.Author") as caught:
        compile_output_fields(Author, Registry())

    assert caught.value.__cause__ is original


def test_public_schema_rejects_relation_metadata_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A lazy public schema must not omit reverse relations after a fault.

    Args:
        monkeypatch: Installs one fault only in relation-list enumeration.
    """
    healthy = _public_author_schema("T14fHealthy")
    healthy_fields = healthy.get_type("T14fHealthyAuthorNode").fields
    assert {"posts", "coauthoredPosts"} <= set(healthy_fields)

    original = RuntimeError("injected Author relation metadata failure")
    get_fields = Author._meta.get_fields
    injections: list[RuntimeError] = []

    def one_shot_fault(*args: object, **kwargs: object) -> object:
        """Fail once only inside the relation-list metadata consumer.

        Args:
            *args: Positional metadata arguments.
            **kwargs: Keyword metadata arguments.

        Returns:
            The healthy metadata fields outside the fault site.

        Raises:
            RuntimeError: The original one-shot relation metadata failure.
        """
        frame = inspect.currentframe()
        caller = frame.f_back if frame is not None else None
        parent = caller.f_back if caller is not None else None
        if (
            caller is not None
            and caller.f_code.co_name == "_model_derived_fields"
            and parent is not None
            and parent.f_code.co_name == "_compile_relation_list_fields"
            and not injections
        ):
            injections.append(original)
            raise original
        return get_fields(*args, **kwargs)

    def prepare() -> None:
        """Install the one-shot fault before public schema construction."""
        monkeypatch.setattr(Author._meta, "get_fields", one_shot_fault)

    with pytest.raises((ImproperlyConfigured, TypeError)) as caught:
        print_schema(_public_author_schema("T14fFault", prepare))

    assert injections == [original]
    chain = _cause_chain(caught.value)
    assert any(
        isinstance(error, ImproperlyConfigured) and "tests.Author" in str(error)
        for error in chain
    )
    assert any(error is original for error in chain)


def test_eager_field_recompile_retains_original_cause() -> None:
    """Keep the original cause when eager field compilation fails.

    The unwrapping layer must not replace the metadata failure's cause.
    """
    original = RuntimeError("original eager metadata failure")

    def fields() -> NoReturn:
        """Raise a model-aware configuration error from its original cause.

        Raises:
            ImproperlyConfigured: The model-aware metadata failure.
        """
        raise ImproperlyConfigured("Failed to enumerate tests.Author") from original

    gql_type = GraphQLObjectType("T14fEagerCause", fields)
    with pytest.raises(ImproperlyConfigured, match="tests.Author") as caught:
        recompile_fields(gql_type)

    assert caught.value.__cause__ is original


def test_eager_field_recompile_keeps_uncaused_error_unchained() -> None:
    """Leave an existing uncaused configuration refusal unchained.

    Eager field compilation must not invent a cause for this failure.
    """

    def fields() -> NoReturn:
        """Raise an existing uncaused configuration refusal.

        Raises:
            ImproperlyConfigured: The uncaused field refusal.
        """
        raise ImproperlyConfigured("field is not published")

    gql_type = GraphQLObjectType("T14fUncaused", fields)
    with pytest.raises(ImproperlyConfigured, match="field is not published") as caught:
        recompile_fields(gql_type)

    assert caught.value.__cause__ is None


def test_lazy_schema_keeps_uncaused_configuration_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A pre-existing uncaused refusal retains its unwrapped contract.

    Args:
        monkeypatch: Replaces schema assembly with a deterministic wrapper.
    """

    def wrapped_schema(*args: object, **kwargs: object) -> NoReturn:
        """Emulate graphql-core's lazy fields wrapper for an uncaused error.

        Args:
            *args: Ignored schema arguments.
            **kwargs: Ignored schema options.

        Raises:
            TypeError: A lazy wrapper around the configuration refusal.
        """
        try:
            raise ImproperlyConfigured("field is not published")
        except ImproperlyConfigured as error:
            raise TypeError("fields cannot be resolved") from error

    monkeypatch.setattr(graphql, "GraphQLSchema", wrapped_schema)

    class Query(ObjectType):
        """Minimal public root for the schema-assembly control."""

        status = field(GraphQLString)

    with pytest.raises(ImproperlyConfigured, match="field is not published") as caught:
        DjangoGraphQLSchema(query=Query)

    assert caught.value.__cause__ is None


def test_lazy_schema_leaves_generic_type_error_untouched(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A nonconfiguration graphql-core TypeError is not transformed.

    Args:
        monkeypatch: Replaces schema assembly with a generic type failure.
    """

    def broken_schema(*args: object, **kwargs: object) -> NoReturn:
        """Raise a genuine schema type error.

        Args:
            *args: Ignored schema arguments.
            **kwargs: Ignored schema options.

        Raises:
            TypeError: The original schema shape failure.
        """
        raise TypeError("genuine GraphQL type failure")

    monkeypatch.setattr(graphql, "GraphQLSchema", broken_schema)

    class Query(ObjectType):
        """Minimal public root for the type-error control."""

        status = field(GraphQLString)

    with pytest.raises(TypeError, match="genuine GraphQL type failure") as caught:
        DjangoGraphQLSchema(query=Query)

    assert caught.value.__cause__ is None
