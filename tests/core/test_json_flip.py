"""RAW-JSON-default flip (Wave 3).

Covers three source-level changes:

* C1 — the raw-passthrough scalar is renamed "GdxGenericScalar" ->
  "GdxJSON" and its GraphQL ".name" flips "GenericScalar" -> "JSON".
  "GDX_SCALAR_MAP" KEEPS the legacy "GenericScalar" key (graphene-class
  forwarding still resolves) and ADDS a "JSON" key; both alias the single
  "GdxJSON" singleton.
* C2 — "GdxJSON.parse_literal" recurses "ObjectValueNode" /
  "ListValueNode" (mirroring graphene's "GenericScalar.parse_literal"),
  including nested "VariableNode" resolution via the "variables" param.
  Inline object / list literals are ACCEPTED (they were rejected before).
* C3 — the "JSONField" descriptor shortcut gains an "as_str: bool"
  flag: "as_str=False" (default) binds "GdxJSON" (SDL "JSON");
  "as_str=True" binds "GdxJSONString" (SDL "JSONString"). The old
  "GenericJSONField" shortcut is DELETED (12 -> 11 scalar shortcuts).

No Django settings required for the scalar/descriptor tier.
"""

from __future__ import annotations

import pytest
from graphql import (
    GraphQLError,
    GraphQLScalarType,
    print_schema,
)
from graphql.language.ast import (
    BooleanValueNode,
    FloatValueNode,
    IntValueNode,
    ListValueNode,
    NullValueNode,
    ObjectFieldNode,
    ObjectValueNode,
    StringValueNode,
    ValueNode,
    VariableNode,
)
from graphql.language.ast import (
    NameNode as _NameNode,
)


# ===========================================================================
# C1 — scalar rename GdxGenericScalar -> GdxJSON, SDL name JSON
# ===========================================================================
class TestScalarRename:
    """Tests for the "GdxGenericScalar" -> "GdxJSON" rename (C1).

    Covers the renamed symbol, its SDL name, and both scalar-map keys.
    """

    def test_gdxjson_symbol_exported_from_scalars(self) -> None:
        """Assert that "GdxJSON" is a real "GraphQLScalarType" instance.

        If this fails, the renamed scalar symbol would be missing or of the
        wrong type, breaking every consumer that binds to it.
        """
        from django_graphex.core.scalars import GdxJSON

        assert isinstance(GdxJSON, GraphQLScalarType)

    def test_gdxjson_sdl_name_is_json(self) -> None:
        """Assert that "GdxJSON.name" prints as "JSON" in the SDL.

        If this fails, generated schemas would still emit the old
        "GenericScalar" SDL name instead of the renamed "JSON".
        """
        from django_graphex.core.scalars import GdxJSON

        assert GdxJSON.name == "JSON"

    def test_old_symbol_is_gone(self) -> None:
        """Assert that the clean rename leaves no "GdxGenericScalar" alias behind.

        If this fails, the old symbol would linger and mask the rename,
        letting stale imports keep working when they should break loudly.
        """
        import django_graphex.core.scalars as scalars

        assert not hasattr(scalars, "GdxGenericScalar")

    def test_gdxjson_exported_from_core(self) -> None:
        """Assert that "django_graphex.core" re-exports the same "GdxJSON" singleton.

        If this fails, importing "GdxJSON" from the core package would
        yield a different object than the one bound in "scalars.py".
        """
        from django_graphex.core import GdxJSON as exported
        from django_graphex.core.scalars import GdxJSON

        assert exported is GdxJSON

    def test_map_keeps_generic_scalar_key(self) -> None:
        """Assert that "GDX_SCALAR_MAP" still resolves the legacy "GenericScalar" key.

        If this fails, legacy graphene-class forwarding that looks up
        "GenericScalar" would stop resolving to the renamed scalar.
        """
        from django_graphex.core.scalars import GDX_SCALAR_MAP, GdxJSON

        assert GDX_SCALAR_MAP["GenericScalar"] is GdxJSON

    def test_map_adds_json_key(self) -> None:
        """Assert that "GDX_SCALAR_MAP" also resolves the new "JSON" key.

        If this fails, new-style lookups by the renamed "JSON" key would
        fail even though the legacy key still works.
        """
        from django_graphex.core.scalars import GDX_SCALAR_MAP, GdxJSON

        assert GDX_SCALAR_MAP["JSON"] is GdxJSON

    def test_json_scalar_appears_in_built_schema_no_collision(self) -> None:
        """Assert that a schema referencing the JSON scalar prints "scalar JSON" once.

        Guards against a pre-existing type already named "JSON" colliding
        with the renamed scalar during a real "compile_schema" build.
        """
        from django_graphex.core.compiler import compile_schema
        from django_graphex.core.ir import FieldSpec, TypeRef, TypeSpec

        spec = TypeSpec(
            name="Query",
            fields=(FieldSpec(name="json_val", type=TypeRef(name="JSON")),),
        )
        schema = compile_schema(types=[spec], enums=[], query=spec)
        sdl = print_schema(schema)
        # The renamed scalar is declared exactly once (no pre-existing ``JSON``
        # type collides with it) and the field references it.
        assert "scalar JSON" in sdl
        assert sdl.count("scalar JSON") == 1
        assert "jsonVal: JSON" in sdl


# ===========================================================================
# C2 — parse_literal recurses Object / List / Variable
# ===========================================================================
def _obj_node(fields: dict[str, ValueNode]) -> ObjectValueNode:
    """Build an "ObjectValueNode" from a name-to-value-node mapping.

    Args:
        fields: Maps each field name to the AST value node it holds.

    Returns:
        node: The assembled object literal AST node.
    """
    return ObjectValueNode(
        fields=[
            ObjectFieldNode(name=_NameNode(value=k), value=v) for k, v in fields.items()
        ]
    )


class TestGdxJSONParseLiteral:
    """Tests for "GdxJSON.parse_literal" recursion over AST literal nodes (C2).

    Covers object/list recursion, nested variables, null handling, and the
    error path for unsupported node types.
    """

    def test_inline_object_literal_parses_to_dict(self) -> None:
        """Assert that an inline object literal parses recursively into a dict.

        If this fails, nested int/list values inside an object literal
        would not be converted to their plain Python equivalents.
        """
        from django_graphex.core.scalars import GdxJSON

        node = _obj_node(
            {
                "a": IntValueNode(value="1"),
                "nested": ListValueNode(
                    values=[IntValueNode(value="1"), IntValueNode(value="2")]
                ),
            }
        )
        result = GdxJSON.parse_literal(node)
        assert result == {"a": 1, "nested": [1, 2]}

    def test_inline_list_literal_parses_to_list(self) -> None:
        """Assert that a mixed-type inline list literal parses element-by-element.

        If this fails, a list literal mixing int/string/boolean values would
        not be converted to a plain Python list with matching types.
        """
        from django_graphex.core.scalars import GdxJSON

        node = ListValueNode(
            values=[
                IntValueNode(value="1"),
                StringValueNode(value="two"),
                BooleanValueNode(value=True),
            ]
        )
        assert GdxJSON.parse_literal(node) == [1, "two", True]

    def test_float_literal_parses_to_float(self) -> None:
        """Assert that a bare "FloatValueNode" becomes a real Python float.

        If this fails, float literals would parse as strings or ints,
        losing precision or type fidelity.
        """
        from django_graphex.core.scalars import GdxJSON

        result = GdxJSON.parse_literal(FloatValueNode(value="1.5"))
        assert result == 1.5
        assert isinstance(result, float)

    def test_float_nested_in_object_literal(self) -> None:
        """Assert that a "FloatValueNode" inside an object literal round-trips as float.

        If this fails, floats nested inside an object literal would lose
        their type during the recursive parse.
        """
        from django_graphex.core.scalars import GdxJSON

        node = _obj_node({"pi": FloatValueNode(value="3.14")})
        assert GdxJSON.parse_literal(node) == {"pi": 3.14}

    def test_deeply_nested_object_and_list(self) -> None:
        """Assert that deeply nested object/list literals parse at every level.

        If this fails, recursion into a list within an object within an
        object would stop early or corrupt the innermost values.
        """
        from django_graphex.core.scalars import GdxJSON

        node = _obj_node(
            {
                "outer": _obj_node(
                    {
                        "list": ListValueNode(
                            values=[_obj_node({"deep": StringValueNode(value="x")})]
                        )
                    }
                )
            }
        )
        assert GdxJSON.parse_literal(node) == {"outer": {"list": [{"deep": "x"}]}}

    def test_nested_variable_resolution(self) -> None:
        """Assert that a "VariableNode" inside an object literal resolves via variables.

        If this fails, a GraphQL variable referenced inside an inline object
        literal would not be substituted with its runtime value.
        """
        from django_graphex.core.scalars import GdxJSON

        node = _obj_node({"a": VariableNode(name=_NameNode(value="v"))})
        result = GdxJSON.parse_literal(node, {"v": 99})
        assert result == {"a": 99}

    def test_nested_variable_in_list(self) -> None:
        """Assert that a "VariableNode" inside a list literal resolves via variables.

        If this fails, a GraphQL variable referenced inside an inline list
        literal would not be substituted with its runtime value.
        """
        from django_graphex.core.scalars import GdxJSON

        node = ListValueNode(values=[VariableNode(name=_NameNode(value="v"))])
        assert GdxJSON.parse_literal(node, {"v": "hi"}) == ["hi"]

    def test_null_literal_is_none(self) -> None:
        """Assert that a "NullValueNode" parses to Python None.

        If this fails, a GraphQL null literal would parse to something
        other than None, breaking null-handling in resolvers.
        """
        from django_graphex.core.scalars import GdxJSON

        assert GdxJSON.parse_literal(NullValueNode()) is None

    def test_object_with_null_field(self) -> None:
        """Assert that a null-valued field inside an object literal parses to None.

        If this fails, an object literal field explicitly set to null would
        be dropped or parsed as something other than None.
        """
        from django_graphex.core.scalars import GdxJSON

        node = _obj_node({"a": NullValueNode()})
        assert GdxJSON.parse_literal(node) == {"a": None}

    def test_garbage_node_still_raises_cleanly(self) -> None:
        """Assert that an unsupported node type raises a clean GraphQLError.

        If this fails, an unrecognized AST literal node (never a
        JSON-representable value) could crash with an unhandled exception
        instead of a well-formed GraphQL error.
        """
        from graphql.language.ast import (
            EnumValueNode,  # not a JSON-representable literal
        )

        from django_graphex.core.scalars import GdxJSON

        with pytest.raises(GraphQLError):
            GdxJSON.parse_literal(EnumValueNode(value="FOO"))

    def test_missing_variable_yields_undefined(self) -> None:
        """Assert that a variable literal with no matching value yields Undefined.

        graphql-core's "ValuesOfCorrectTypeRule" calls "parse_literal" at
        VALIDATION time with NO variables, so a nested "$var" inside an
        inline object/list literal must not raise for the then-undefined
        variable — it yields "Undefined" (graphene "GenericScalar" parity,
        matching graphql-core's own "value_from_ast"). At execution time
        real variables are supplied and substitution happens.
        """
        from graphql import Undefined

        from django_graphex.core.scalars import GdxJSON

        node = VariableNode(name=_NameNode(value="absent"))
        # variable_values is an empty dict (name absent) -> Undefined.
        assert GdxJSON.parse_literal(node, {}) is Undefined
        # variable_values is None (validation-time) -> Undefined.
        assert GdxJSON.parse_literal(node, None) is Undefined


# ===========================================================================
# C3 — JSONField(as_str=...) descriptor + GenericJSONField deleted
# ===========================================================================
class TestJSONFieldAsStr:
    """Tests for "JSONField(as_str=...)" and the removed "GenericJSONField" (C3).

    Covers scalar binding in both output and argument position, and the
    removal of the legacy shortcut from both its modules.
    """

    def test_default_binds_gdxjson(self) -> None:
        """Assert that a bare "JSONField()" is a "Field" descriptor bound to GdxJSON.

        If this fails, the default (raw) JSON field would not bind the
        expected descriptor type or scalar.
        """
        from django_graphex.core import JSONField
        from django_graphex.core.descriptors import Field
        from django_graphex.core.scalars import GdxJSON

        desc = JSONField()
        assert isinstance(desc, Field)
        assert desc.type is GdxJSON

    def test_as_str_false_binds_gdxjson(self) -> None:
        """Assert that "as_str=False" explicitly binds the raw "GdxJSON" scalar.

        If this fails, explicitly requesting the raw JSON representation
        would silently fall back to the string-encoded variant or vice versa.
        """
        from django_graphex.core import JSONField
        from django_graphex.core.scalars import GdxJSON

        assert JSONField(as_str=False).type is GdxJSON

    def test_as_str_true_binds_gdxjsonstring(self) -> None:
        """Assert that "as_str=True" binds the string-encoded "GdxJSONString" scalar.

        If this fails, requesting the string-encoded JSON representation
        would still bind the raw "GdxJSON" scalar instead.
        """
        from django_graphex.core import JSONField
        from django_graphex.core.scalars import GdxJSONString

        assert JSONField(as_str=True).type is GdxJSONString

    def test_as_str_true_in_argument_position(self) -> None:
        """Assert that "as_str" also governs the INPUT (argument) position.

        If this fails, the unified Field descriptor would bind a different
        scalar in argument position than in output position, breaking
        symmetry between reads and writes.
        """
        from django_graphex.core import JSONField
        from django_graphex.core.scalars import GdxJSON, GdxJSONString

        raw_arg = JSONField(as_str=False).to_graphql_argument()
        str_arg = JSONField(as_str=True).to_graphql_argument()
        assert raw_arg.type is GdxJSON
        assert str_arg.type is GdxJSONString

    def test_genericjsonfield_removed_from_core(self) -> None:
        """Assert that "GenericJSONField" is gone from the core package and "__all__".

        If this fails, the deleted legacy shortcut would still be reachable
        or advertised as public API from "django_graphex.core".
        """
        import django_graphex.core as core

        assert not hasattr(core, "GenericJSONField")
        assert "GenericJSONField" not in core.__all__

    def test_genericjsonfield_removed_from_descriptors(self) -> None:
        """Assert that "GenericJSONField" is gone from the descriptors module.

        If this fails, the deleted legacy shortcut would still be reachable
        directly from "django_graphex.core.descriptors".
        """
        import django_graphex.core.descriptors as descriptors

        assert not hasattr(descriptors, "GenericJSONField")

    def test_json_field_output_position_binds_json_scalar(self) -> None:
        """Assert that a default "JSONField()" in OUTPUT position binds the JSON scalar.

        The output SDL is driven by the bound scalar's ".name" ("JSON").
        """
        from django_graphex.core import JSONField
        from django_graphex.core.scalars import GdxJSON

        desc = JSONField()
        assert desc.type is GdxJSON
        assert desc.type.name == "JSON"
