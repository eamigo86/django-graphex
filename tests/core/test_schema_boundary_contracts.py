"""Public schema-construction boundaries for native GraphQL roots."""

from graphql import GraphQLField, GraphQLObjectType, GraphQLString, graphql_sync

from django_graphex.schema import DjangoGraphQLSchema


def test_native_argument_keeps_explicit_output_name_and_identity() -> None:
    """Preserve an already-mounted argument's explicit resolver keyword.

    Rebuilding it from the public field name would change resolver input keys.
    """
    from graphql import GraphQLArgument

    from django_graphex.core._args import native_arg

    argument = GraphQLArgument(GraphQLString, out_name="explicit_key")

    assert native_arg(argument, name="wireName") is argument
    assert argument.out_name == "explicit_key"


def test_positional_native_query_root_retains_its_fields() -> None:
    """Accept a positional native query root without replacing its type.

    Schema construction must preserve its declared name and executable field.
    """
    query = GraphQLObjectType(
        "NativeGreetingRoot",
        {"greeting": GraphQLField(GraphQLString, resolve=lambda _root, _info: "hello")},
    )

    schema = DjangoGraphQLSchema(query)
    result = graphql_sync(schema.graphql_schema, "{ greeting }")

    assert schema.graphql_schema.query_type is query
    assert result.errors is None
    assert result.data == {"greeting": "hello"}
