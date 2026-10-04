"""Direct contracts for the private annotation-promotion AST walker."""

from __future__ import annotations

import pytest
from graphql import (
    GraphQLField,
    GraphQLInterfaceType,
    GraphQLObjectType,
    GraphQLSchema,
    GraphQLString,
    parse,
)

from django_graphex.utils import _iter_promotion_fields
from tests.test_optimizer_phase_d import _AuthorTypePromo, _PostTypePromo, _promo_schema


def _selection_and_fragments(source: str) -> tuple[object, dict[str, object]]:
    """Read one parseable selection and its named definitions.

    Args:
        source: An AST document; validation is not implied.

    Returns:
        The first field's selection and named fragment definitions.
    """
    source = source.replace(
        " on Author", f" on {_AuthorTypePromo._meta.graphql_output_type.name}"
    ).replace(" on Post", f" on {_PostTypePromo._meta.graphql_output_type.name}")
    document = parse(source)
    selection = document.definitions[0].selection_set.selections[0].selection_set
    fragments = {fragment.name.value: fragment for fragment in document.definitions[1:]}
    return selection, fragments


def _author_schema_type() -> GraphQLObjectType:
    """Return the object instance registered in the executable schema.

    Returns:
        The schema-owned author object type used for subtype checks.
    """
    name = _AuthorTypePromo._meta.graphql_output_type.name
    current_type = _promo_schema.graphql_schema.get_type(name)
    assert isinstance(current_type, GraphQLObjectType)
    return current_type


@pytest.mark.parametrize(
    ("source", "expected"),
    [
        ("{ author { name } }", ["name"]),
        ("{ author { ... { name } } }", ["name"]),
        ("{ author { ...Named } } fragment Named on Author { name }", ["name"]),
        (
            "{ author { ... on Author { nickname: name } } }",
            ["name"],
        ),
        (
            "{ author { ...Named ...Named } } fragment Named on Author { name }",
            ["name", "name"],
        ),
    ],
)
def test_walker_returns_schema_field_names_from_applicable_fragments(
    source: str, expected: list[str]
) -> None:
    """Keep aliases out of schema lookup and repeat independent spreads.

    Args:
        source: Parseable selection shape.
        expected: Schema field names in traversal order.
    """
    selection, fragments = _selection_and_fragments(source)
    schema = _promo_schema.graphql_schema
    current_type = _author_schema_type()

    fields = list(
        _iter_promotion_fields(selection, current_type, schema, fragments, {})
    )

    assert [field.name.value for field in fields] == expected


def test_walker_returns_empty_for_absent_selection() -> None:
    """Treat a missing selection as an empty defensive optimizer input.

    The helper must yield no fields without dereferencing absent AST content.
    """
    assert (
        list(
            _iter_promotion_fields(
                None,
                _author_schema_type(),
                _promo_schema.graphql_schema,
                {},
                {},
            )
        )
        == []
    )


@pytest.mark.parametrize(
    "source",
    [
        "{ author { ...Named } } fragment Named on Author { name }",
        "{ author { ... on Author { name } } }",
    ],
)
def test_walker_rejects_typed_fragments_without_current_type(source: str) -> None:
    """Fail closed when the parent GraphQL object type is unavailable.

    Args:
        source: A parseable typed fragment selection.
    """
    selection, fragments = _selection_and_fragments(source)
    assert (
        list(
            _iter_promotion_fields(
                selection, None, _promo_schema.graphql_schema, fragments, {}
            )
        )
        == []
    )


def test_walker_keeps_untyped_inline_without_current_type() -> None:
    """Preserve the permissive untyped-inline contract with unknown parent.

    An untyped inline fragment imposes no schema condition of its own.
    """
    selection, fragments = _selection_and_fragments("{ author { ... { name } } }")
    fields = list(
        _iter_promotion_fields(
            selection, None, _promo_schema.graphql_schema, fragments, {}
        )
    )
    assert [field.name.value for field in fields] == ["name"]


@pytest.mark.parametrize(
    "source",
    [
        "{ author { ...Missing } }",
        "{ author { ...Named } } fragment Named on Unknown { name }",
        "{ author { ... on Post { title } } }",
    ],
)
def test_walker_ignores_missing_unknown_and_foreign_fragments(source: str) -> None:
    """Keep untrusted fragment targets out of this object's field plan.

    Args:
        source: Parseable AST with a missing or inapplicable target.
    """
    selection, fragments = _selection_and_fragments(source)
    schema = _promo_schema.graphql_schema
    current_type = _author_schema_type()
    assert _PostTypePromo._meta.graphql_output_type is not current_type
    assert (
        list(_iter_promotion_fields(selection, current_type, schema, fragments, {}))
        == []
    )


def test_walker_terminates_recursive_unvalidated_fragment_path() -> None:
    """Retain ordinary fields while stopping one cyclic AST spread path.

    This is an AST-walker negative contract, not a valid GraphQL request.
    """
    selection, fragments = _selection_and_fragments(
        "{ author { ...Cycle } } fragment Cycle on Author { name ...Cycle }"
    )
    fields = list(
        _iter_promotion_fields(
            selection,
            _author_schema_type(),
            _promo_schema.graphql_schema,
            fragments,
            {},
        )
    )
    assert [field.name.value for field in fields] == ["name"]


@pytest.mark.parametrize(
    ("include", "skip", "expected"),
    [
        (False, False, ["name"]),
        (True, False, ["name", "postCount"]),
        (False, True, ["name"]),
        (True, True, ["name"]),
    ],
)
def test_walker_applies_bound_spread_and_inline_directives(
    include: bool, skip: bool, expected: list[str]
) -> None:
    """Exclude directive-guarded annotation fields before planning.

    Args:
        include: Bound include value on the spread.
        skip: Bound skip value on its inline child.
        expected: Selected schema field names.
    """
    selection, fragments = _selection_and_fragments(
        "{ author { name ...Stats @include(if: $take) } } "
        "fragment Stats on Author { ... @skip(if: $hide) { postCount } }"
    )
    fields = list(
        _iter_promotion_fields(
            selection,
            _author_schema_type(),
            _promo_schema.graphql_schema,
            fragments,
            {"take": include, "hide": skip},
        )
    )
    assert [field.name.value for field in fields] == expected


def test_walker_accepts_implemented_interface_condition() -> None:
    """Use schema subtype rules rather than comparing type-name strings.

    An object implementing an interface can select fields conditioned on it.
    """
    named = GraphQLInterfaceType("Named", {"name": GraphQLField(GraphQLString)})
    person = GraphQLObjectType(
        "Person",
        {"name": GraphQLField(GraphQLString)},
        interfaces=[named],
    )
    query = GraphQLObjectType("Query", {"person": GraphQLField(person)})
    schema = GraphQLSchema(query=query, types=[named])
    selection, fragments = _selection_and_fragments(
        "{ person { ... on Named { name } } }"
    )
    fields = list(_iter_promotion_fields(selection, person, schema, fragments, {}))
    assert [field.name.value for field in fields] == ["name"]
