"""Reverse-FK destination scopes must resolve Django's accessor names."""

from __future__ import annotations

from typing import Any

import pytest
from django.db import models
from django.test import override_settings
from graphql import graphql_sync

from django_graphex.core import ObjectType
from django_graphex.fields import DjangoFilterListField
from django_graphex.registry import Registry
from django_graphex.schema import DjangoGraphQLSchema
from django_graphex.types import DjangoObjectType

from ._schema_isolation import isolated_pair


class SD1VerifyParent(models.Model):
    """Own reverse-FK relations with default and explicit accessor names.

    The model exists only for the public GraphQL regression witness.
    """

    name = models.CharField(max_length=20)

    class Meta:
        """Bind the witness model to the existing tests application.

        Django creates its table with the regular test database.
        """

        app_label = "tests"


class SD1VerifyChild(models.Model):
    """Child whose default reverse accessor ends in set.

    Django's reverse query name differs from its Python accessor.
    """

    owner = models.ForeignKey(SD1VerifyParent, on_delete=models.CASCADE)
    visible = models.BooleanField()
    title = models.CharField(max_length=20)

    class Meta:
        """Bind the default-accessor child to the tests application.

        This model intentionally does not declare related_name.
        """

        app_label = "tests"


class SD1VerifyNamedChild(models.Model):
    """Child with a reverse accessor distinct from its reverse query name.

    Both names must resolve to the same reverse-FK destination scope.
    """

    owner = models.ForeignKey(
        SD1VerifyParent,
        on_delete=models.CASCADE,
        related_name="named_children",
        related_query_name="named_match",
    )
    visible = models.BooleanField()
    title = models.CharField(max_length=20)

    class Meta:
        """Bind the custom-accessor child to the tests application.

        Its query name must not be mistaken for its Python accessor.
        """

        app_label = "tests"


_REGISTRY = Registry()


class ScopedDefaultChildType(DjangoObjectType):
    """Expose only visible default-accessor child rows.

    Root and reverse-FK paths must agree on this type's hook.
    """

    class Meta:
        """Bind the default-accessor child to the isolated registry.

        The visibility flag stays out of the GraphQL output shape.
        """

        model = SD1VerifyChild
        registry = _REGISTRY
        only_fields = ("id", "title")

    @classmethod
    def get_queryset(cls, queryset: Any, info: Any) -> Any:
        """Restrict rows to the visible children.

        Args:
            queryset: Candidate child rows.
            info: GraphQL resolve information for this request.

        Returns:
            The queryset containing only visible rows.
        """
        return queryset.filter(visible=True)


class ScopedNamedChildType(DjangoObjectType):
    """Expose only visible custom-accessor child rows.

    Its target relation has distinct accessor and query names.
    """

    class Meta:
        """Bind the custom-accessor child to the isolated registry.

        The visibility flag stays out of the GraphQL output shape.
        """

        model = SD1VerifyNamedChild
        registry = _REGISTRY
        only_fields = ("id", "title")

    @classmethod
    def get_queryset(cls, queryset: Any, info: Any) -> Any:
        """Restrict rows to the visible children.

        Args:
            queryset: Candidate child rows.
            info: GraphQL resolve information for this request.

        Returns:
            The queryset containing only visible rows.
        """
        return queryset.filter(visible=True)


class AccessorParentType(DjangoObjectType):
    """Automatically expose both reverse-FK child containers.

    Neither relation field is mounted by an explicit resolver.
    """

    class Meta:
        """Bind the parent to the same isolated output registry.

        Automatic reverse-FK fields are compiled from model metadata.
        """

        model = SD1VerifyParent
        registry = _REGISTRY


class AccessorQuery(ObjectType):
    """Compare root child visibility with nested automatic traversal.

    The three roots share one isolated schema registry.
    """

    parents = DjangoFilterListField(AccessorParentType)
    children = DjangoFilterListField(ScopedDefaultChildType)
    named_children = DjangoFilterListField(ScopedNamedChildType)


_SCHEMA = DjangoGraphQLSchema(query=AccessorQuery, registries=isolated_pair(_REGISTRY))


@pytest.mark.django_db
@pytest.mark.parametrize(
    "optimize,window", [(True, True), (True, False), (False, False)]
)
@pytest.mark.parametrize("kind", ["default", "related_query_name"])
def test_hidden_reverse_child_cannot_bypass_destination_scope(
    optimize: bool, window: bool, kind: str
) -> None:
    """Hide reverse-FK children for both accessor shapes and resolver paths.

    Args:
        optimize: Whether queryset optimization is enabled.
        window: Whether nested window pagination is enabled.
        kind: Django reverse accessor naming convention under test.
    """
    parent = SD1VerifyParent.objects.create(name="visible-parent")
    if kind == "default":
        model = SD1VerifyChild
        accessor = "sd1verifychildSet"
        root = "children"
    else:
        model = SD1VerifyNamedChild
        accessor = "namedChildren"
        root = "namedChildren"
    model.objects.create(owner=parent, visible=False, title="secret")
    model.objects.create(owner=parent, visible=True, title="public")
    query = (
        "{ "
        + root
        + " { title } parents { name "
        + accessor
        + " { totalCount results(limit: 1) { title } } } }"
    )

    with override_settings(
        DJANGO_GRAPHEX={
            "OPTIMIZE_QUERYSET": optimize,
            "OPTIMIZE_NESTED_PAGINATION": window,
        }
    ):
        result = graphql_sync(_SCHEMA.graphql_schema, query)

    assert result.errors is None, [str(error) for error in result.errors or ()]
    assert result.data is not None
    assert result.data[root] == [{"title": "public"}]
    nested = result.data["parents"][0][accessor]
    assert nested["totalCount"] == 1
    assert nested["results"] == [{"title": "public"}]
