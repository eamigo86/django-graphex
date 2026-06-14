"""Sub-spike 5: Recursive PostFilterInput SDL — gate G7.

Proves that a self-referential GraphQLInputObjectType built with fields=lambda
thunks produces correct SDL with and/or/not recursive fields.

Run: pytest tests/spike/test_recursive_filter_input.py -v
"""

from __future__ import annotations

from graphql import (
    GraphQLArgument,
    GraphQLBoolean,
    GraphQLField,
    GraphQLInputField,
    GraphQLInputObjectType,
    GraphQLList,
    GraphQLNonNull,
    GraphQLObjectType,
    GraphQLSchema,
    GraphQLString,
    print_schema,
)


# ---------------------------------------------------------------------------
# Build recursive filter input using Post model fields
# ---------------------------------------------------------------------------

def _build_recursive_filter_schema() -> tuple[GraphQLSchema, GraphQLInputObjectType]:
    """Build a schema with a recursive PostFilterInput using thunk-based fields.

    Based on the real Post model: title, body, author_id, views
    """
    # We need a mutable container for the recursive reference
    filter_cache: dict[str, GraphQLInputObjectType] = {}

    # Build PostFilterInput with lambda thunks for recursive and/or/not fields
    post_filter_input = GraphQLInputObjectType(
        "PostFilterInput",
        fields=lambda: {
            # Scalar filter fields from Post model
            "title": GraphQLInputField(GraphQLString),
            "body": GraphQLInputField(GraphQLString),
            "views": GraphQLInputField(GraphQLString),
            # Recursive combinators using list thunks
            "and": GraphQLInputField(GraphQLList(filter_cache["PostFilterInput"])),
            "or": GraphQLInputField(GraphQLList(filter_cache["PostFilterInput"])),
            "not": GraphQLInputField(filter_cache["PostFilterInput"]),
        },
    )
    filter_cache["PostFilterInput"] = post_filter_input

    # Build a minimal Post type and Query to create a complete schema
    post_type = GraphQLObjectType(
        "Post",
        fields={
            "title": GraphQLField(GraphQLString),
            "body": GraphQLField(GraphQLString),
        },
    )

    query_type = GraphQLObjectType(
        "Query",
        fields={
            "posts": GraphQLField(
                GraphQLList(post_type),
                args={"filter": GraphQLArgument(post_filter_input)},
            )
        },
    )

    schema = GraphQLSchema(query=query_type, types=[post_filter_input])
    return schema, post_filter_input


# ---------------------------------------------------------------------------
# G7: Tests
# ---------------------------------------------------------------------------

class TestG7RecursiveFilterInput:
    """G7: Self-referential FilterInput SDL contains correct recursive fields."""

    def test_post_filter_input_in_sdl(self):
        """SDL output contains PostFilterInput type definition."""
        schema, _ = _build_recursive_filter_schema()
        sdl = print_schema(schema)
        assert "PostFilterInput" in sdl, (
            f"PostFilterInput not found in SDL:\n{sdl}"
        )

    def test_and_field_is_list_of_post_filter_input(self):
        """SDL contains 'and: [PostFilterInput]' field."""
        schema, _ = _build_recursive_filter_schema()
        sdl = print_schema(schema)
        assert "and: [PostFilterInput]" in sdl, (
            f"'and: [PostFilterInput]' not found in SDL. Full SDL:\n{sdl}"
        )

    def test_or_field_is_list_of_post_filter_input(self):
        """SDL contains 'or: [PostFilterInput]' field."""
        schema, _ = _build_recursive_filter_schema()
        sdl = print_schema(schema)
        assert "or: [PostFilterInput]" in sdl, (
            f"'or: [PostFilterInput]' not found in SDL. Full SDL:\n{sdl}"
        )

    def test_not_field_is_post_filter_input(self):
        """SDL contains 'not: PostFilterInput' field."""
        schema, _ = _build_recursive_filter_schema()
        sdl = print_schema(schema)
        assert "not: PostFilterInput" in sdl, (
            f"'not: PostFilterInput' not found in SDL. Full SDL:\n{sdl}"
        )

    def test_full_sdl_structure(self):
        """Combined assertion: all required recursive SDL pieces are present."""
        schema, _ = _build_recursive_filter_schema()
        sdl = print_schema(schema)

        missing = []
        for expected in ["PostFilterInput", "and: [PostFilterInput]", "or: [PostFilterInput]"]:
            if expected not in sdl:
                missing.append(expected)

        assert not missing, (
            f"Missing from SDL: {missing}\n\nFull SDL:\n{sdl}"
        )
