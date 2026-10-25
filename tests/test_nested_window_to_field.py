"""Nested paginated lists join on the FK target field, not the parent pk."""

from __future__ import annotations

from typing import Any

import pytest
from graphql import graphql_sync

from django_graphex.core import ObjectType
from django_graphex.fields import DjangoListObjectField, DjangoNestedListObjectField
from django_graphex.paginations import LimitOffsetGraphqlPagination
from django_graphex.registry import Registry
from django_graphex.schema import DjangoGraphQLSchema
from django_graphex.types import DjangoListObjectType, DjangoObjectType

from ._schema_isolation import isolated_pair
from .test_filter_reverse_fk_to_field import ToFieldChild, ToFieldParent


def _schema() -> DjangoGraphQLSchema:
    """Build a schema whose parent lists its children through a window page.

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

    class ChildList(DjangoListObjectType):
        """Paginated child list.

        Attributes:
            Meta: Type options.
        """

        class Meta:
            """Type options.

            Attributes:
                model: The backing model.
                registry: The isolated registry.
                pagination: Two rows per page.
            """

            model = ToFieldChild
            registry = reg
            pagination = LimitOffsetGraphqlPagination(default_limit=2)

    class ParentType(DjangoObjectType):
        """Parent output type with the nested list.

        Attributes:
            children: Windowed child list.
            Meta: Type options.
        """

        children = DjangoNestedListObjectField(ChildList, accessor="children")

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
        """Parent list.

        Attributes:
            Meta: Type options.
        """

        class Meta:
            """Type options.

            Attributes:
                model: The backing model.
                registry: The isolated registry.
            """

            model = ToFieldParent
            registry = reg

    class Query(ObjectType):
        """Query root.

        Attributes:
            parents: Parent list.
        """

        parents = DjangoListObjectField(ParentList)

    return DjangoGraphQLSchema(query=Query, registries=isolated_pair(reg))


_SCHEMA = _schema()


def _seed() -> None:
    """Create parents whose pk and code cross each other.

    Parent A has pk 1 and code 101, B has pk 2 and code 1 (5 children), C has
    pk 101 and code 5 (3 children), so no pk-based join can match by luck.
    """
    ToFieldParent.objects.create(pk=1, code=101, name="A")
    b = ToFieldParent.objects.create(pk=2, code=1, name="B")
    c = ToFieldParent.objects.create(pk=101, code=5, name="C")
    for i in range(5):
        ToFieldChild.objects.create(parent=b, label=f"b{i}")
    for i in range(3):
        ToFieldChild.objects.create(parent=c, label=f"c{i}")


def _run(arguments: str) -> dict[str, Any]:
    """Query every parent with a windowed child list.

    Args:
        arguments: Arguments of the nested results field.

    Returns:
        Parent name to its nested list payload.
    """
    result = graphql_sync(
        _SCHEMA.graphql_schema,
        "{ parents { results { name children { results"
        f"{arguments} {{ label }} totalCount }} }} }} }}",
    )
    assert result.errors is None, [str(e) for e in result.errors or ()]
    return {row["name"]: row["children"] for row in result.data["parents"]["results"]}


@pytest.mark.django_db
@pytest.mark.parametrize("offset", [0, 1, 100])
def test_nested_total_and_page_match_django(offset: int) -> None:
    """The window page and totalCount equal the ORM for crossed pk and code.

    Args:
        offset: Window offset, including one past the end.
    """
    _seed()
    got = _run(f"(limit: 2, offset: {offset})")
    for parent in ToFieldParent.objects.all():
        children = parent.children.order_by("pk")
        expected = [c.label for c in children[offset : offset + 2]]
        assert [r["label"] for r in got[parent.name]["results"]] == expected
        assert got[parent.name]["totalCount"] == children.count()


@pytest.mark.django_db
@pytest.mark.parametrize("window", [True, False], ids=["window", "plain"])
def test_parent_rows_carry_the_fk_target_column(window: bool) -> None:
    """The narrowed parent query keeps the column the prefetch joins on.

    Without it every parent row lazily loads its code, one query each.

    Args:
        window: Whether nested pagination uses the window prefetch.
    """
    from django.db import connection
    from django.test import override_settings
    from django.test.utils import CaptureQueriesContext

    _seed()
    with override_settings(DJANGO_GRAPHEX={"OPTIMIZE_NESTED_PAGINATION": window}):
        with CaptureQueriesContext(connection) as queries:
            got = _run("(limit: 2, offset: 0)")
    parent_reads = [
        q["sql"]
        for q in queries.captured_queries
        if 'FROM "tests_tofieldparent"' in q["sql"]
    ]
    assert len(parent_reads) == 1, parent_reads
    for parent in ToFieldParent.objects.all():
        expected = [c.label for c in parent.children.order_by("pk")[:2]]
        assert [r["label"] for r in got[parent.name]["results"]] == expected
        assert got[parent.name]["totalCount"] == parent.children.count()
