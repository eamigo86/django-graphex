"""GraphQL error payload types (native, graphene-free)."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from graphql import GraphQLList, GraphQLNonNull, GraphQLString

from .core.base import ObjectType
from .core.descriptors import field as gdx_field

__all__ = ("ErrorType",)


class ErrorType(ObjectType):
    """A field-scoped validation error: "{field, messages}".

    Mirrors "graphene_django.types.ErrorType" (the only part of it we use), so
    mutation error payloads are unchanged.

    NATIVE (S-ROOTS-b): subclasses the native "ObjectType" base (metaclass
    "pydantic.ModelMetaclass") so it compiles through the native path — NO
    "graphene.ObjectType" base, NO "import graphene" here. The two wire fields
    are declared with the native "field()" helper using graphql-core wrappers so
    the SDL is byte-identical to the graphene original:

    - "field"    -> "String!"      ("GraphQLNonNull(GraphQLString)")
    - "messages" -> "[String!]!"   ("GraphQLNonNull(GraphQLList(GraphQLNonNull(GraphQLString)))")

    The value-object constructor "ErrorType(field=..., messages=...)" still
    round-trips: the native container "__init__" stashes both field-named kwargs
    as plain instance attributes (they appear in "_meta.fields"). This is the
    contract "nested.py" / "utils.py" / "core/backend.py" rely on when
    constructing error entries and reading "error.field" / "error.messages".
    """

    field = gdx_field(GraphQLNonNull(GraphQLString))
    messages = gdx_field(GraphQLNonNull(GraphQLList(GraphQLNonNull(GraphQLString))))

    if TYPE_CHECKING:
        # Type-only constructor stub. At runtime the native ObjectType container
        # ``__init__`` accepts and stashes arbitrary field-named kwargs as instance
        # attributes; this stub tells the type checker the two wire fields are
        # valid constructor kwargs. It is NEVER present at runtime.
        def __init__(
            self,
            *,
            field: str | None = ...,
            messages: list[str] | None = ...,
            **kwargs: Any,
        ) -> None:
            """Native container accepts the field-named wire kwargs (type-only)."""
