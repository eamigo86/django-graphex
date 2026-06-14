"""TDD WU-2 RED — native/_args.py: graphene Argument → GraphQLArgument converter.

Tests:
- Argument(String, required=True) → GraphQLArgument(GraphQLNonNull(GraphQLString))
- Argument(String) → GraphQLArgument(GraphQLString)
- Argument(List(NonNull(String))) → GraphQLArgument(GraphQLList(GraphQLNonNull(GraphQLString)))
- Argument(ID, required=True) → GraphQLArgument(GraphQLNonNull(GraphQLID))
- Result is an instance of GraphQLArgument, NOT a graphene.Argument
- default_value is preserved
- description is preserved
- out_name is snake_case derived from camelCase arg name

Run:
    GDX_BACKEND=native .venv/bin/python -m pytest -q tests/native/test_args.py
"""
from __future__ import annotations

import pytest

pytestmark = pytest.mark.native_only


# ---------------------------------------------------------------------------
# Helper import
# ---------------------------------------------------------------------------


def _converter():
    from django_graphex.native._args import graphene_arg_to_graphql_argument
    return graphene_arg_to_graphql_argument


# ---------------------------------------------------------------------------
# 2.1.1  Argument(String, required=True) → GraphQLArgument(NonNull(String))
# ---------------------------------------------------------------------------


def test_string_required_maps_to_nonnull_graphql_string():
    """Argument(String, required=True) → GraphQLArgument(GraphQLNonNull(GraphQLString))."""
    import graphene
    from graphql import GraphQLArgument, GraphQLNonNull, GraphQLString

    fn = _converter()
    arg = graphene.Argument(graphene.String, required=True)
    result = fn(arg)

    assert isinstance(result, GraphQLArgument), (
        "Converter must return a GraphQLArgument instance"
    )
    assert isinstance(result.type, GraphQLNonNull), (
        "required=True must produce GraphQLNonNull wrapper"
    )
    assert result.type.of_type is GraphQLString, (
        "Inner type must be GraphQLString"
    )


# ---------------------------------------------------------------------------
# 2.1.2  Argument(String) (optional) → GraphQLArgument(GraphQLString)
# ---------------------------------------------------------------------------


def test_string_optional_maps_to_graphql_string():
    """Argument(String) (optional) → GraphQLArgument(GraphQLString)."""
    import graphene
    from graphql import GraphQLArgument, GraphQLString

    fn = _converter()
    arg = graphene.Argument(graphene.String)
    result = fn(arg)

    assert isinstance(result, GraphQLArgument)
    assert result.type is GraphQLString, (
        "Optional String arg must map to bare GraphQLString"
    )


# ---------------------------------------------------------------------------
# 2.1.3  Argument(List(NonNull(String))) → GraphQLArgument(List(NonNull(String)))
# ---------------------------------------------------------------------------


def test_list_of_nonnull_string_maps_correctly():
    """Argument(List(NonNull(String))) → GraphQLArgument(GraphQLList(GraphQLNonNull(GraphQLString)))."""
    import graphene
    from graphql import GraphQLArgument, GraphQLList, GraphQLNonNull, GraphQLString

    fn = _converter()
    arg = graphene.Argument(graphene.List(graphene.NonNull(graphene.String)))
    result = fn(arg)

    assert isinstance(result, GraphQLArgument)
    assert isinstance(result.type, GraphQLList), (
        "Outer type must be GraphQLList"
    )
    assert isinstance(result.type.of_type, GraphQLNonNull), (
        "Inner type must be GraphQLNonNull"
    )
    assert result.type.of_type.of_type is GraphQLString, (
        "Innermost type must be GraphQLString"
    )


# ---------------------------------------------------------------------------
# 2.1.4  ID(required=True) → GraphQLArgument(GraphQLNonNull(GraphQLID))
# ---------------------------------------------------------------------------


def test_id_required_maps_to_nonnull_graphql_id():
    """Argument(ID, required=True) → GraphQLArgument(GraphQLNonNull(GraphQLID))."""
    import graphene
    from graphql import GraphQLArgument, GraphQLID, GraphQLNonNull

    fn = _converter()
    arg = graphene.Argument(graphene.ID, required=True)
    result = fn(arg)

    assert isinstance(result, GraphQLArgument)
    assert isinstance(result.type, GraphQLNonNull), (
        "required=True must produce GraphQLNonNull"
    )
    assert result.type.of_type is GraphQLID, (
        "Inner type must be GraphQLID"
    )


# ---------------------------------------------------------------------------
# 2.1.5  Result is NOT a graphene.Argument
# ---------------------------------------------------------------------------


def test_result_is_not_graphene_argument():
    """The converter output must not be a graphene.Argument."""
    import graphene
    from graphql import GraphQLArgument

    fn = _converter()
    arg = graphene.Argument(graphene.String)
    result = fn(arg)

    assert not isinstance(result, graphene.Argument), (
        "Converter must return graphql-core GraphQLArgument, not graphene.Argument"
    )
    assert isinstance(result, GraphQLArgument)


# ---------------------------------------------------------------------------
# 2.1.6  default_value is preserved
# ---------------------------------------------------------------------------


def test_default_value_is_preserved():
    """default_value on the graphene Argument is propagated to GraphQLArgument."""
    import graphene
    from graphql import GraphQLArgument, GraphQLString

    fn = _converter()
    arg = graphene.Argument(graphene.String, default_value="hello")
    result = fn(arg)

    assert isinstance(result, GraphQLArgument)
    assert result.default_value == "hello", (
        "default_value must be passed through to GraphQLArgument"
    )


# ---------------------------------------------------------------------------
# 2.1.7  description is preserved
# ---------------------------------------------------------------------------


def test_description_is_preserved():
    """description on the graphene Argument is propagated to GraphQLArgument."""
    import graphene

    fn = _converter()
    arg = graphene.Argument(graphene.String, description="A test arg")
    result = fn(arg)

    assert result.description == "A test arg", (
        "description must be passed through to GraphQLArgument"
    )


# ---------------------------------------------------------------------------
# 2.1.8  out_name uses snake_case from the camelCase key
# ---------------------------------------------------------------------------


def test_out_name_snake_case_from_camel_key():
    """out_name kwarg is converted to snake_case when a camelCase name is provided."""
    import graphene
    from django_graphex.native._args import graphene_arg_to_graphql_argument

    arg = graphene.Argument(graphene.String)
    # Pass a camelCase name as the key (simulating dict key from class args)
    result = graphene_arg_to_graphql_argument(arg, name="firstName")

    assert result.out_name == "first_name", (
        "out_name must be the snake_case form of the camelCase key"
    )


def test_out_name_snake_key_unchanged():
    """out_name stays the same when the name is already snake_case."""
    import graphene
    from django_graphex.native._args import graphene_arg_to_graphql_argument

    arg = graphene.Argument(graphene.String)
    result = graphene_arg_to_graphql_argument(arg, name="first_name")

    assert result.out_name == "first_name"


# ---------------------------------------------------------------------------
# 2.1.9  Boolean and Int scalars map correctly
# ---------------------------------------------------------------------------


def test_boolean_maps_to_graphql_boolean():
    """Argument(Boolean) → GraphQLArgument(GraphQLBoolean)."""
    import graphene
    from graphql import GraphQLBoolean

    fn = _converter()
    result = fn(graphene.Argument(graphene.Boolean))
    assert result.type is GraphQLBoolean


def test_int_required_maps_to_nonnull_graphql_int():
    """Argument(Int, required=True) → GraphQLArgument(GraphQLNonNull(GraphQLInt))."""
    import graphene
    from graphql import GraphQLInt, GraphQLNonNull

    fn = _converter()
    result = fn(graphene.Argument(graphene.Int, required=True))
    assert isinstance(result.type, GraphQLNonNull)
    assert result.type.of_type is GraphQLInt


# ---------------------------------------------------------------------------
# 2.1.10  Error branches — TypeError for non-graphene type, KeyError for unknown
# ---------------------------------------------------------------------------


def test_unwrap_raises_type_error_for_unrecognised_type():
    """_unwrap_graphene_type raises TypeError for a type with no _meta.name."""
    from django_graphex.native._args import _unwrap_graphene_type

    class NotAGrapheneType:
        """Has no _meta attribute."""

    with pytest.raises(TypeError, match="Cannot convert graphene type"):
        _unwrap_graphene_type(NotAGrapheneType())


def test_unwrap_raises_key_error_for_unknown_scalar():
    """_unwrap_graphene_type raises KeyError for a scalar name not in GDX_SCALAR_MAP."""
    from django_graphex.native._args import _unwrap_graphene_type

    class FakeMeta:
        name = "UnknownCustomScalar"

    class FakeScalar:
        _meta = FakeMeta()

    with pytest.raises(KeyError, match="UnknownCustomScalar"):
        _unwrap_graphene_type(FakeScalar())
