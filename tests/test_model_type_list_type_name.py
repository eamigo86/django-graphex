# -*- coding: utf-8 -*-
"""A "DjangoModelType" must not mint the list-container name users are taught.

The list container generated for a "DjangoModelType" was named
"<Model>ListType" -- the exact name the docs give the user's own
"DjangoListObjectType" (docs/index.md, docs/api/types.md,
docs/usage/filtering.md, the playground schema). Declaring both therefore put
two distinct classes with one name into a single schema and graphql-core
refused to assemble it:

    TypeError: Schema must contain uniquely named types but contains multiple
    types named 'AuthorListType'.

The generated container now uses the "Generic" name-space the same type
already mints its output ("<Model>GenericType") and input
("<Model>CreateGenericType") into, which no user convention claims.
"""

from __future__ import annotations

from graphql import print_schema

from django_graphex.core import ObjectType
from django_graphex.fields import DjangoListObjectField
from django_graphex.paginations.pagination import LimitOffsetGraphqlPagination
from django_graphex.schema import DjangoGraphQLSchema
from django_graphex.types import (
    DjangoListObjectType,
    DjangoModelType,
    DjangoObjectType,
)

from .models import NonEditableOwner


class OwnerType(DjangoObjectType):
    """The user's own output type, following the documented convention.

    Registered so the batteries-included type below reuses it as its node.
    """

    class Meta:
        """Bind the type to "NonEditableOwner".

        The filter fields exist only so the type takes its normal path.
        """

        model = NonEditableOwner
        filter_fields = {"name": ("exact",)}


class NonEditableOwnerListType(DjangoListObjectType):
    """The user's own list container, named the way the docs teach.

    The name is the whole point of this module: it is what the generated
    container used to be called too.
    """

    class Meta:
        """Bind the container to "NonEditableOwner".

        Deliberately left unconfigured: only its NAME matters here.
        """

        model = NonEditableOwner


_MODEL_TYPE_PAGINATION = LimitOffsetGraphqlPagination(default_limit=3)


class OwnerModelType(DjangoModelType):
    """A "DjangoModelType" over the SAME model as the declared container.

    The pairing is what used to make the schema unbuildable.
    """

    class Meta:
        """Bind the batteries-included type to "NonEditableOwner".

        The explicit paginator is what a reuse-based fix would have thrown
        away, so it doubles as the proof that the generated container is still
        shaped by THIS Meta.
        """

        model = NonEditableOwner
        pagination = _MODEL_TYPE_PAGINATION


class _Query(ObjectType):
    """Root query mounting BOTH containers over the same model.

    Both have to be reachable for graphql-core to compare their names.
    """

    mine = DjangoListObjectField(NonEditableOwnerListType)
    generated = OwnerModelType.ListField()


def test_the_generated_container_does_not_take_the_documented_name() -> None:
    """The generated container is named in the "Generic" name-space.

    This test breaks if the container goes back to claiming "<Model>ListType".
    """
    generated = OwnerModelType._meta.output_list_type

    assert generated._meta.name == "NonEditableOwnerListGenericType"
    assert generated is not NonEditableOwnerListType


def test_both_containers_coexist_in_one_schema() -> None:
    """The schema assembles instead of raising on a duplicate type name.

    This is the end-to-end symptom: the build used to abort with "Schema must
    contain uniquely named types".
    """
    sdl = print_schema(DjangoGraphQLSchema(query=_Query).graphql_schema)

    assert "type NonEditableOwnerListType {" in sdl, sdl
    assert "type NonEditableOwnerListGenericType {" in sdl, sdl


def test_the_generated_container_keeps_its_own_shape() -> None:
    """The generated container is still built from the "DjangoModelType"'s Meta.

    Reusing the registered container was the other candidate fix; it was
    rejected because a "DjangoModelType" carries its own "pagination" /
    "results_field_name" / projection, which a user-declared container built
    from its own Meta would silently discard.
    """
    generated = OwnerModelType._meta.output_list_type

    assert generated._meta.model is NonEditableOwner
    assert generated._meta.pagination is _MODEL_TYPE_PAGINATION
    assert NonEditableOwnerListType._meta.pagination is not _MODEL_TYPE_PAGINATION
