# -*- coding: utf-8 -*-
"""Multi-table-inheritance models must expose their INHERITED fields.

The native compilers walked "model._meta.get_fields(include_parents=False)".
That call is right for an ABSTRACT base (whose columns are copied into the
child and would otherwise be emitted twice) and wrong for MULTI-TABLE
inheritance, where the parent's columns live in the parent table and are only
reachable through the parent link. The result was a child type carrying only
its own columns -- not even "id" -- and a HARD schema-build failure whenever
the parent owned a reverse to-many relation: the relation stayed in
"_meta.fields" with no compiled counterpart, so the build died with
"<Child>Type fields cannot be resolved".

These tests pin the child type's inherited surface plus the no-op guarantee
for every model that does NOT use multi-table inheritance.
"""

from __future__ import annotations

from graphql import graphql_sync, print_type

from django_graphex.core import ObjectType
from django_graphex.fields import DjangoListObjectField
from django_graphex.registry import Registry
from django_graphex.schema import DjangoGraphQLSchema
from django_graphex.types import DjangoListObjectType, DjangoObjectType

from ._schema_isolation import isolated_pair
from .models import MtiPlace, MtiRestaurant, MtiReview

R = Registry()


class MtiReviewType(DjangoObjectType):
    """Output type for the review pointing at the MTI parent.

    Registered so the inherited reverse relation has a node type to render.
    """

    class Meta:
        """Bind the type to "MtiReview".

        The module registry keeps these types out of the global namespace.
        """

        model = MtiReview
        registry = R


class MtiPlaceType(DjangoObjectType):
    """Output type for the MTI parent model.

    Registered so the child's parent link has a target to point at.
    """

    class Meta:
        """Bind the type to "MtiPlace".

        The module registry keeps these types out of the global namespace.
        """

        model = MtiPlace
        registry = R


class MtiRestaurantType(DjangoObjectType):
    """Output type for the MTI child model.

    The child table holds only "serves_pizza"; everything else it renders has
    to come from the inherited "MtiPlace" table.
    """

    class Meta:
        """Bind the type to "MtiRestaurant".

        The module registry keeps these types out of the global namespace.
        """

        model = MtiRestaurant
        registry = R


class MtiRestaurantList(DjangoListObjectType):
    """List container over the MTI child, mounted on the root query.

    Gives the schema a root field through which the child type is reachable.
    """

    class Meta:
        """Bind the container to "MtiRestaurant".

        The module registry keeps these types out of the global namespace.
        """

        model = MtiRestaurant
        registry = R


class _Query(ObjectType):
    """Root query exposing the MTI child list.

    One field is enough: it drags the whole child subgraph into the schema.
    """

    restaurants = DjangoListObjectField(MtiRestaurantList)


_schema = DjangoGraphQLSchema(query=_Query, registries=isolated_pair(R))


def _child_sdl() -> str:
    """Return the printed SDL of the MTI child output type.

    Returns:
        The SDL block for "MtiRestaurantType".
    """
    return print_type(_schema.graphql_schema.get_type("MtiRestaurantType"))


def test_mti_schema_builds_at_all() -> None:
    """A model whose MTI parent owns a reverse to-many still compiles.

    This is the hard-failure half of the defect: "reviews" is derived on the
    child through the parent, so leaving it out of the compilers' field walk
    made the whole schema build raise "MtiRestaurantType fields cannot be
    resolved. Cannot convert None to a graphql-core type".
    """
    assert _schema.graphql_schema.get_type("MtiRestaurantType") is not None


def test_mti_child_type_exposes_the_parents_reverse_to_many() -> None:
    """The parent's reverse to-many is re-injected on the child type.

    This test breaks if the relation-list compiler stops walking parents: the
    container disappears from the child type's SDL.
    """
    assert "reviews: MtiReviewListType" in _child_sdl(), _child_sdl()


def test_mti_child_reverse_to_many_resolves(db: None) -> None:
    """The inherited reverse to-many returns the parent's related rows.

    Args:
        db: The pytest-django database fixture.
    """
    restaurant = MtiRestaurant.objects.create(name="Luigi", serves_pizza=True)
    MtiReview.objects.create(place_id=restaurant.pk, rating=5)

    result = graphql_sync(
        _schema.graphql_schema,
        "{ restaurants { results { reviews { totalCount } } } }",
    )

    assert result.errors is None, result.errors
    assert result.data["restaurants"]["results"][0]["reviews"]["totalCount"] == 1


def test_the_field_walk_is_a_no_op_for_every_non_mti_model() -> None:
    """Only multi-table children see a different derived-field list.

    "include_parents" does nothing for abstract-base or proxy inheritance --
    Django copies or shares those columns either way -- so the switch to the
    default "include_parents=True" cannot move a single field on any model
    whose "_meta.parents" is empty. Asserting it over the WHOLE registry (every
    model the suite defines, plus Django's own contrib models) is the
    byte-identical-SDL proof for the abstract-base case the old
    "include_parents=False" was protecting.
    """
    from django.apps import apps

    from django_graphex.types import _model_derived_fields

    changed = {
        model.__name__
        for model in apps.get_models()
        if not model._meta.parents
        and [f.name for f in _model_derived_fields(model)]
        != [f.name for f in model._meta.get_fields(include_parents=False)]
    }

    assert changed == set(), changed
    assert MtiRestaurant._meta.parents, "the fixture stopped being a MTI child"


def test_mti_child_type_exposes_inherited_concrete_fields() -> None:
    """The child type renders the parent's columns, "id" included.

    Only the primary key is non-null, which is this compiler's convention for
    every model: a concrete column renders nullable regardless of its Django
    "null" setting. The implicit "<parent>_ptr" link is deliberately absent —
    it is join plumbing, and every column it would reach is already here.
    """
    sdl = _child_sdl()

    assert "id: ID!" in sdl, sdl
    assert "name: String" in sdl, sdl
    assert "address: String" in sdl, sdl
    assert "mtiplacePtr" not in sdl, sdl
    assert "servesPizza: Boolean" in sdl, sdl
