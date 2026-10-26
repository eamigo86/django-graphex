"""Reverse-FK filters correlate on the FK target field, not the parent pk."""

from __future__ import annotations

from typing import Any

import pytest
from django.db import models
from django.db.models import Q
from graphql import graphql_sync

from django_graphex.core import ObjectType
from django_graphex.fields import DjangoListObjectField
from django_graphex.registry import Registry
from django_graphex.schema import DjangoGraphQLSchema
from django_graphex.types import DjangoListObjectType, DjangoObjectType

from ._schema_isolation import isolated_pair


class ToFieldParent(models.Model):
    """Parent addressed by a unique code rather than its primary key.

    Attributes:
        code: Unique column the child FK points at.
        name: Display name used in assertions.
    """

    code = models.IntegerField(unique=True)
    name = models.CharField(max_length=10)

    class Meta:
        """Test-local model options.

        Attributes:
            app_label: The label of the test app.
        """

        app_label = "tests"


class ToFieldChild(models.Model):
    """Child whose FK targets the parent's code column.

    Attributes:
        parent: FK to the parent code.
        label: Child label.
    """

    parent = models.ForeignKey(
        ToFieldParent,
        to_field="code",
        on_delete=models.CASCADE,
        related_name="children",
    )
    label = models.CharField(max_length=10)

    class Meta:
        """Test-local model options.

        Attributes:
            app_label: The label of the test app.
        """

        app_label = "tests"


def _schema(scoped: bool) -> DjangoGraphQLSchema:
    """Build a public schema, optionally with a child destination hook.

    Args:
        scoped: Whether the child type overrides get_queryset.

    Returns:
        The compiled schema.
    """
    reg = Registry()

    class ChildType(DjangoObjectType):
        """Child output type.

        Attributes:
            Meta: Type options.
        """

        class Meta:
            """Type options.

            Attributes:
                model: The backing model.
                registry: The isolated registry.
                only_fields: Published columns.
            """

            model = ToFieldChild
            registry = reg
            only_fields = ("id", "label")

        if scoped:

            @classmethod
            def get_queryset(cls, queryset: Any, info: Any) -> Any:
                """Hide rows labelled hidden.

                Args:
                    queryset: Candidate children.
                    info: Current GraphQL request.

                Returns:
                    Visible children.
                """
                return queryset.exclude(label="hidden")

    class ParentType(DjangoObjectType):
        """Parent output type.

        Attributes:
            Meta: Type options.
        """

        class Meta:
            """Type options.

            Attributes:
                model: The backing model.
                registry: The isolated registry.
                only_fields: Published columns.
            """

            model = ToFieldParent
            registry = reg
            only_fields = ("id", "name", "children")

    class ParentList(DjangoListObjectType):
        """Parent list with a child label filter.

        Attributes:
            Meta: Type options.
        """

        class Meta:
            """Type options.

            Attributes:
                model: The backing model.
                registry: The isolated registry.
                filter_fields: Child lookups.
            """

            model = ToFieldParent
            registry = reg
            filter_fields = {"children__label": ("exact",)}

    class Query(ObjectType):
        """Query root.

        Attributes:
            parents: Filterable parent list.
        """

        parents = DjangoListObjectField(ParentList)

    return DjangoGraphQLSchema(query=Query, registries=isolated_pair(reg))


_SCHEMAS = {"plain": _schema(False), "scoped": _schema(True)}
_X = '{ label: { exact: "x" } }'
_Y = '{ label: { exact: "y" } }'
_XY = Q(children__label="x") | Q(children__label="y")
_CASES = {
    "not": (
        f"{{ children: {{ not: {_X} }} }}",
        lambda: ToFieldParent.objects.exclude(Q(children__label="x")),
    ),
    "not-or": (
        f"{{ children: {{ not: {{ or: [{_X}, {_Y}] }} }} }}",
        lambda: ToFieldParent.objects.exclude(_XY),
    ),
    "or": (
        f"{{ children: {{ or: [{_X}, {_Y}] }} }}",
        lambda: ToFieldParent.objects.filter(_XY),
    ),
    "or-of-relations": (
        f"{{ or: [{{ children: {_X} }}, {{ children: {_Y} }}] }}",
        lambda: ToFieldParent.objects.filter(_XY),
    ),
    "positive": (
        f"{{ children: {_X} }}",
        lambda: ToFieldParent.objects.filter(children__label="x"),
    ),
}


@pytest.mark.django_db
@pytest.mark.parametrize("schema", sorted(_SCHEMAS))
@pytest.mark.parametrize("case", sorted(_CASES))
def test_to_field_reverse_fk_filters_match_django(schema: str, case: str) -> None:
    """Crossed pk and code values must not confuse the correlation.

    Args:
        schema: Which schema variant runs.
        case: Which filter shape runs.
    """
    ToFieldParent.objects.create(pk=1, code=101, name="A")
    b = ToFieldParent.objects.create(pk=2, code=1, name="B")
    ToFieldParent.objects.create(pk=3, code=3, name="C")
    ToFieldChild.objects.create(parent=b, label="x")
    ToFieldChild.objects.create(parent_id=101, label="y")
    node, expected = _CASES[case]
    result = graphql_sync(
        _SCHEMAS[schema].graphql_schema,
        "{ parents(filter: " + node + ") { results { name } } }",
    )
    assert result.errors is None, [str(e) for e in result.errors or ()]
    got = sorted(r["name"] for r in result.data["parents"]["results"])
    assert got == sorted(set(expected().values_list("name", flat=True)))
