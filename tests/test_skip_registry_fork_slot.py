# -*- coding: utf-8 -*-
"""A type that opted OUT of the registry must not claim the model's slot.

"Meta.skip_registry = True" exists for exactly one reason: the type is built
and named, but it is NOT the model's canonical output type. The graphene
"Registry" honours that ("register" skips the write) and so does the class-def
native compile (types.py skips "set_compiled").

The FORKED build -- the pair-local compile a schema gets from the public
"registries=" kwarg -- read the opt-out from "_meta", where nothing ever wrote
it. Every read therefore answered False and the opted-out type took the model's
compiled slot last-wins. Since a "DjangoListObjectType" container resolves its
"results" element through that slot, the container served the WIDE opted-out
type instead of its own declared "baseType", and every column the canonical
node projects away became readable again.

The single-registry path never had the bug (its guard reads a local variable),
so it is pinned here too: the fix must not move it.
"""

from __future__ import annotations

from graphql import GraphQLList, parse, validate

from django_graphex.core import ObjectType
from django_graphex.registry import Registry
from django_graphex.schema import DjangoGraphQLSchema
from django_graphex.types import (
    DjangoListObjectField,
    DjangoListObjectType,
    DjangoObjectType,
)

from ._schema_isolation import isolated_pair
from .models import Author

# ---------------------------------------------------------------------------
# Schema: a canonical node hiding "bio", plus an opted-out node that does not
# ---------------------------------------------------------------------------

_RSKIP = Registry()


class SkipCanonicalAuthorType(DjangoObjectType):
    """The model's canonical node type, hiding the "bio" column.

    Declared FIRST so the opted-out type below is the LAST registration -- the
    position a last-wins slot write would hand the model to.
    """

    class Meta:
        """Configuration for "SkipCanonicalAuthorType".

        Projects away "bio" so a hijacked slot is visible in the schema.
        """

        model = Author
        registry = _RSKIP
        exclude_fields = ("bio",)


class SkipOptedOutAuthorType(DjangoObjectType):
    """A WIDE Author type that explicitly declines the model's slot.

    It publishes every column, including the one the canonical node hides, so
    serving it from the container republishes a projected-away column.
    """

    class Meta:
        """Configuration for "SkipOptedOutAuthorType".

        Opts out of the registry, so nothing may treat it as canonical.
        """

        model = Author
        registry = _RSKIP
        skip_registry = True


class SkipAuthorListType(DjangoListObjectType):
    """Container whose "baseType" is the canonical node, not the opted-out one.

    Its "results" element is resolved through the model's compiled slot, so
    it is where a hijacked slot becomes a served answer.
    """

    class Meta:
        """Configuration for "SkipAuthorListType".

        Declares no projection of its own, so the node type's applies.
        """

        model = Author
        registry = _RSKIP


class SkipQuery(ObjectType):
    """Root query exposing the container over "Author".

    One wrapped list field is enough: the container is what reads the slot.
    """

    authors = DjangoListObjectField(SkipAuthorListType)


skip_schema = DjangoGraphQLSchema(query=SkipQuery, registries=isolated_pair(_RSKIP))


class TestTheOptedOutTypeDoesNotClaimTheSlot:
    """The forked pair must honour "skip_registry" as every other path does.

    The opt-out is a claim about the model's slot, and a fork fills that
    slot from scratch -- so the fork is where the claim had to be re-read.
    """

    def test_the_container_serves_its_declared_base_type(self) -> None:
        """The "results" element must be the canonical node, not the wide one.

        If this breaks, the container silently serves a type its "baseType"
        never named.
        """
        assert SkipAuthorListType._meta.baseType is SkipCanonicalAuthorType

        container = skip_schema.graphql_schema.type_map["SkipAuthorListType"]
        results = container.fields["results"].type
        assert isinstance(results, GraphQLList)
        assert results.of_type.name == "SkipCanonicalAuthorType"

    def test_the_projected_away_column_is_not_readable_through_results(self) -> None:
        """A query for the hidden column must fail VALIDATION.

        This is the leak in its served form: "bio" is hidden by the canonical
        node and published by the opted-out one. Validation, not execution, is
        the check: an executed query fails on database access before the field
        selection proves anything.
        """
        errors = validate(
            skip_schema.graphql_schema, parse("{ authors { results { bio } } }")
        )
        assert errors, "'bio' validated through a container whose node hides it"
        assert "Cannot query field 'bio'" in errors[0].message


class TestTheOrdinarySingleRegistryPathIsUntouched:
    """The non-forked path already honoured the opt-out; it must keep doing so.

    Recording the opt-out where the fork can read it must not change what
    the class-def compile writes.
    """

    def test_the_shared_slot_keeps_the_canonical_node(self) -> None:
        """The class-def compile must not stamp an opted-out type.

        Reads the class-def registry companion directly, which is the slot a
        DEFAULT (unforked) schema resolves relations and containers through.
        """
        compiled = _RSKIP.output_registry().get_compiled(Author)
        assert compiled is SkipCanonicalAuthorType._meta.graphql_output_type
