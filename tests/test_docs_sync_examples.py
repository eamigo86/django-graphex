"""Execute the literal 4.1 numeric and foreign-key migration examples."""

from __future__ import annotations

import ast
import json
from decimal import Decimal
from pathlib import Path

import pytest
from graphql import graphql_sync, parse
from graphql.execution import MiddlewareManager

from django_graphex.directives import all_directives
from django_graphex.middleware import GraphQLDirectiveMiddleware
from django_graphex.schema import DjangoGraphQLSchema

from ._schema_isolation import isolated_pair
from .test_directives_exact_numbers import _REGISTRY, ExactNum, Query
from .test_filter_reverse_fk_to_field import _SCHEMAS, ToFieldChild, ToFieldParent
from .test_nested_window_to_field import _SCHEMA as WINDOW_SCHEMA

ROOT = Path(__file__).parents[1]
UPGRADE = ROOT / "docs/UPGRADE-4.1.md"
TO_FIELD_HEADING = "### Foreign keys targeting a non-primary-key column"


def _fence_under_heading(
    path: Path, heading: str, language: str, occurrence: int = 0
) -> str:
    """Return an unchanged fenced block under a published section heading.

    Args:
        path: Markdown source containing the published example.
        heading: Exact heading identifying the example's section.
        language: Fence language to extract.
        occurrence: Zero-based occurrence of that language in the section.

    Returns:
        The literal body of the selected fence.
    """
    lines = path.read_text(encoding="utf-8").splitlines()
    level = len(heading) - len(heading.lstrip("#"))
    section = []
    for line in lines[lines.index(heading) + 1 :]:
        if line.startswith("#") and len(line) - len(line.lstrip("#")) <= level:
            break
        section.append(line)
    blocks = []
    block = None
    for line in section:
        stripped = line.strip()
        if block is None and stripped == f"```{language}":
            block = []
        elif block is not None and stripped == "```":
            blocks.append("\n".join(block))
            block = None
        elif block is not None:
            block.append(line)
    return blocks[occurrence]


def test_numeric_api_example_preserves_exact_wire_values() -> None:
    """Execute the numeric reference's literal operation and expected JSON.

    The nullable fields must also stay null through every numeric directive.
    """
    path = ROOT / "docs/api/directives.md"
    heading = "#### Exact Decimal and BigInt example"
    document = _fence_under_heading(path, heading, "graphql")
    documented = json.loads(_fence_under_heading(path, heading, "json"))
    schema = DjangoGraphQLSchema(
        query=Query, directives=all_directives, registries=isolated_pair(_REGISTRY)
    ).graphql_schema

    result = graphql_sync(
        schema,
        document,
        context_value={
            "item": ExactNum(amt=Decimal("-2.665"), big=-(2**53 + 1), flt=4.27)
        },
        middleware=MiddlewareManager(GraphQLDirectiveMiddleware()),
    )
    assert result.errors is None, result.errors
    assert result.data == documented
    assert result.data == {
        "item": {
            "roundedHalf": "-2.66",
            "floored": "-3",
            "ceiled": "-2",
            "absolute": "2.665",
            "roundedBig": "-9007199254740990",
            "absoluteBig": "9007199254740993",
            "floatRounded": 4.3,
        }
    }

    null_result = graphql_sync(
        schema,
        document,
        context_value={"item": ExactNum(amt=None, big=None, flt=None)},
        middleware=MiddlewareManager(GraphQLDirectiveMiddleware()),
    )
    assert null_result.errors is None, null_result.errors
    assert null_result.data == {"item": dict.fromkeys(result.data["item"])}


def test_upgrade_model_declares_fields_selected_by_copied_operations() -> None:
    """Ensure both published operations can select fields on the shown model.

    The Python and GraphQL fences must describe one coherent example, not
    merely parse separately against the richer test fixture.
    """
    model_tree = ast.parse(_fence_under_heading(UPGRADE, TO_FIELD_HEADING, "python"))
    parent = next(
        node
        for node in model_tree.body
        if isinstance(node, ast.ClassDef) and node.name == "Parent"
    )
    declared = {
        target.id
        for member in parent.body
        if isinstance(member, ast.Assign)
        for target in member.targets
        if isinstance(target, ast.Name)
    }
    assert declared <= {field.name for field in ToFieldParent._meta.local_fields}
    for occurrence in (0, 1):
        document = parse(
            _fence_under_heading(UPGRADE, TO_FIELD_HEADING, "graphql", occurrence)
        )
        parents_field = document.definitions[0].selection_set.selections[0]
        results_field = next(
            field
            for field in parents_field.selection_set.selections
            if field.name.value == "results"
        )
        selected = {
            field.name.value
            for field in results_field.selection_set.selections
            if field.name.value != "children"
        }
        assert selected <= declared


@pytest.fixture
def crossed_parents(db: object) -> dict[str, ToFieldParent]:
    """Create parents whose primary keys cross their FK target codes.

    Args:
        db: Enable the test database.

    Returns:
        Parent rows keyed by display name.
    """
    parents = {
        "A": ToFieldParent.objects.create(pk=1, code=101, name="A"),
        "B": ToFieldParent.objects.create(pk=2, code=1, name="B"),
        "C": ToFieldParent.objects.create(pk=101, code=5, name="C"),
    }
    for name, labels in {
        "A": ("y",),
        "B": ("x", "b1", "b2"),
        "C": ("c0", "c1", "c2"),
    }.items():
        for label in labels:
            ToFieldChild.objects.create(parent=parents[name], label=label)
    return parents


def test_upgrade_literal_reverse_fk_filter_matches_orm(
    crossed_parents: dict[str, ToFieldParent],
) -> None:
    """Execute the guide's reverse-FK filter over crossed target columns.

    Args:
        crossed_parents: Persisted parents whose codes differ from primary keys.
    """
    document = _fence_under_heading(
        ROOT / "docs/UPGRADE-4.1.md",
        "### Foreign keys targeting a non-primary-key column",
        "graphql",
    )
    result = graphql_sync(_SCHEMAS["plain"].graphql_schema, document)
    assert result.errors is None, result.errors
    got = sorted(row["name"] for row in result.data["parents"]["results"])
    expected = sorted(
        set(
            ToFieldParent.objects.exclude(children__label="x").values_list(
                "name", flat=True
            )
        )
    )
    assert got == expected == ["A", "C"]


def test_upgrade_literal_nested_counts_match_target_relation(
    crossed_parents: dict[str, ToFieldParent],
) -> None:
    """Execute the guide's windowed nested list and compare ORM counts.

    Args:
        crossed_parents: Persisted parents whose codes differ from primary keys.
    """
    document = _fence_under_heading(
        ROOT / "docs/UPGRADE-4.1.md",
        "### Foreign keys targeting a non-primary-key column",
        "graphql",
        occurrence=1,
    )
    result = graphql_sync(WINDOW_SCHEMA.graphql_schema, document)
    assert result.errors is None, result.errors
    got = {row["name"]: row["children"] for row in result.data["parents"]["results"]}
    assert set(got) == set(crossed_parents)
    for name, parent in crossed_parents.items():
        children = parent.children.order_by("pk")
        assert got[name]["totalCount"] == children.count()
        assert [row["label"] for row in got[name]["results"]] == list(
            children.values_list("label", flat=True)[:2]
        )
