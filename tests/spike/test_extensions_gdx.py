"""Sub-spike 4: extensions["gdx"] reachable from a ValidationRule — gate G6.

Also empirically confirms whether GraphQLObjectType.__init__ accepts extensions=
kwarg in graphql-core 3.2.11.

Run: pytest tests/spike/test_extensions_gdx.py -v
"""

from __future__ import annotations

import inspect

import pytest
from graphql import (
    GraphQLField,
    GraphQLObjectType,
    GraphQLSchema,
    GraphQLString,
    parse,
    validate,
)
from graphql.language import FieldNode
from graphql.validation import ValidationRule

# ---------------------------------------------------------------------------
# Confirm: does GraphQLObjectType.__init__ accept extensions= in 3.2.11?
# ---------------------------------------------------------------------------


class TestGraphQLObjectTypeExtensionsKwarg:
    """Empirically confirm extensions= kwarg availability in graphql-core 3.2.11.

    Guards the WU-1 assumption that extensions can be attached directly to a
    GraphQLObjectType instead of via a side-table.
    """

    def test_extensions_kwarg_in_init_signature(self) -> None:
        """GraphQLObjectType.__init__ must accept an extensions= keyword argument.

        Contract: WU-1's direct-extensions approach ships broken if this
        graphql-core version drops the extensions= constructor parameter,
        forcing a fallback to the _GDX_EXT side-table.
        """
        sig = inspect.signature(GraphQLObjectType.__init__)
        params = list(sig.parameters.keys())
        assert "extensions" in params, (
            f"PLAN B REQUIRED: extensions= kwarg NOT found in GraphQLObjectType.__init__. "
            f"Parameters found: {params}. "
            f"_GDX_EXT side-table is required for WU-1."
        )

    def test_extensions_kwarg_works_at_construction(self) -> None:
        """Constructing GraphQLObjectType with extensions= must not raise.

        Contract: WU-1 ships broken if passing extensions={"gdx": ...} at
        construction time either raises or is not retrievable afterward.
        """
        try:
            obj_type = GraphQLObjectType(
                "TestType",
                fields={"id": GraphQLField(GraphQLString)},
                extensions={"gdx": {"max_depth": 3}},
            )
            assert obj_type.extensions.get("gdx") == {"max_depth": 3}, (
                f"extensions['gdx'] not accessible, got: {obj_type.extensions!r}"
            )
        except TypeError as e:
            pytest.fail(
                f"PLAN B REQUIRED: GraphQLObjectType(extensions=...) raised TypeError: {e}. "
                f"_GDX_EXT side-table is required for WU-1."
            )


# ---------------------------------------------------------------------------
# G6: ValidationRule reads extensions["gdx"] via get_named_type
# ---------------------------------------------------------------------------


class TestG6ExtensionsGdxFromValidationRule:
    """G6: A ValidationRule can read extensions['gdx'] from a named type.

    Confirms the gdx metadata survives schema construction and is reachable
    both from inside a running ValidationRule and via type_map lookup.
    """

    def _build_schema_with_gdx_extensions(self) -> GraphQLSchema:
        """Build a schema where types carry extensions={"gdx": {...}}.

        Returns:
            schema: A minimal Query/Author schema whose types each carry a
                gdx extensions payload.
        """
        author_type = GraphQLObjectType(
            "Author",
            fields={
                "name": GraphQLField(GraphQLString),
                "bio": GraphQLField(GraphQLString),
            },
            extensions={"gdx": {"max_depth": 3, "complexity": 2}},
        )
        query_type = GraphQLObjectType(
            "Query",
            fields={
                "author": GraphQLField(author_type),
            },
            extensions={"gdx": {"max_depth": 1, "complexity": 1}},
        )
        return GraphQLSchema(query=query_type)

    def test_validation_rule_reads_gdx_max_depth(self) -> None:
        """A ValidationRule must read extensions['gdx']['max_depth'] cleanly.

        Contract: gdx-based validation ships broken if reading the nested
        extensions dict from inside a running ValidationRule raises
        AttributeError/KeyError instead of returning the stored value.
        """
        schema = self._build_schema_with_gdx_extensions()

        # Capture the value read by the ValidationRule
        captured_values: dict[str, int] = {}
        errors_in_rule: list[Exception] = []

        class GdxMaxDeepReader(ValidationRule):
            """A test ValidationRule that reads extensions['gdx']['max_depth']."""

            def enter_field(self, node: FieldNode, *args: object) -> None:
                """Read extensions["gdx"]["max_depth"] from the Author type.

                Args:
                    node: The field node currently being visited.
                    args: The remaining visitor callback arguments (key,
                        parent, path, ancestors) supplied by graphql-core;
                        unused here.
                """
                # Try to read extensions["gdx"]["max_depth"] from the Author type
                try:
                    author_type = self.context.schema.type_map.get("Author")
                    if author_type is not None:
                        gdx = author_type.extensions.get("gdx")
                        if gdx is not None:
                            captured_values["max_depth"] = gdx["max_depth"]
                            captured_values["complexity"] = gdx["complexity"]
                except (AttributeError, KeyError) as e:
                    errors_in_rule.append(e)

        document = parse("{ author { name } }")
        errors = validate(schema, document, rules=[GdxMaxDeepReader])

        # No errors from validation
        assert not errors, f"Validation errors: {errors}"

        # No errors from within the rule
        assert not errors_in_rule, (
            f"AttributeError/KeyError raised inside ValidationRule: {errors_in_rule}"
        )

        # The max_depth value must be readable
        assert "max_depth" in captured_values, (
            "ValidationRule did not read extensions['gdx']['max_depth'] — "
            "field was not entered or type not found."
        )
        assert captured_values["max_depth"] == 3, (
            f"Expected max_depth=3, got: {captured_values['max_depth']!r}"
        )

    def test_get_named_type_path_also_works(self) -> None:
        """Looking up a type via schema.type_map must keep extensions intact.

        Contract: gdx metadata ships broken if it is lost or altered when a
        type is retrieved through type_map instead of via a ValidationRule.
        """
        schema = self._build_schema_with_gdx_extensions()

        author_type = schema.type_map.get("Author")
        assert author_type is not None, "Author type not found in schema.type_map"

        gdx = author_type.extensions.get("gdx")
        assert gdx is not None, (
            f"extensions['gdx'] not found, extensions={author_type.extensions!r}"
        )
        assert gdx["max_depth"] == 3, f"Expected 3, got {gdx['max_depth']!r}"
