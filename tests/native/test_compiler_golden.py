"""Tests for native/compiler.py + native/bridge.py — golden SDL and functional gates.

No Django settings required. No django_db markers.
Run with: pytest tests/native/test_compiler_golden.py -x

normalize_sdl() definition (pinned before golden-SDL gate):
    - strip leading/trailing whitespace per line
    - sort type blocks alphabetically by type name
    - within each type block, sort field lines alphabetically
    - strip/normalize blank lines between blocks to single blank line
    - descriptions are EXCLUDED (we test structure, not docs)
    - this function is used only for structural assertion, NOT char-for-char golden
"""
import re
from types import SimpleNamespace

import pytest
from graphql import GraphQLObjectType, GraphQLSchema, GraphQLField, GraphQLString
from graphql import build_schema, graphql_sync
from graphql.utilities import print_schema


# ---------------------------------------------------------------------------
# normalize_sdl helper (pinned definition)
# ---------------------------------------------------------------------------

def normalize_sdl(sdl: str) -> str:
    """Normalize a GraphQL SDL string for structural comparison.

    Strips descriptions, sorts type blocks and fields within blocks.
    """
    # Remove description strings (triple-quoted or single-quoted)
    sdl = re.sub(r'""".*?"""', "", sdl, flags=re.DOTALL)
    sdl = re.sub(r'"[^"]*"', "", sdl)

    # Split into type blocks (split on top-level 'type/enum/scalar/input' keywords)
    lines = sdl.splitlines()

    blocks: list[list[str]] = []
    current_block: list[str] = []

    for line in lines:
        stripped = line.strip()
        if not stripped:
            continue
        # New top-level block starts
        if re.match(r"^(type|enum|scalar|input|interface|union)\s+\w+", stripped):
            if current_block:
                blocks.append(current_block)
            current_block = [stripped]
        else:
            current_block.append(stripped)

    if current_block:
        blocks.append(current_block)

    # Sort fields within each block (lines between the opening { and closing })
    sorted_blocks = []
    for block in blocks:
        if len(block) <= 1:
            sorted_blocks.append(block)
            continue
        header = block[0]
        body_lines = []
        for line in block[1:]:
            stripped = line.strip()
            if stripped not in ("{", "}"):
                body_lines.append(stripped)
        body_lines.sort()
        sorted_blocks.append([header, "{"] + body_lines + ["}"])

    # Sort blocks by their header line
    sorted_blocks.sort(key=lambda b: b[0])

    # Render
    result_lines = []
    for i, block in enumerate(sorted_blocks):
        if i > 0:
            result_lines.append("")
        result_lines.extend(block)

    return "\n".join(result_lines).strip()


# ---------------------------------------------------------------------------
# Imports (collected once, will fail RED until compiler exists)
# ---------------------------------------------------------------------------

from django_graphex.native.ir import TypeRef, FieldSpec, TypeSpec, EnumSpec, GdxMeta
from django_graphex.native.compiler import (
    compile_type,
    compile_enum,
    compile_schema,
    _reset_cache,
)
from django_graphex.native.bridge import (
    GdxPayload,
    assert_gdx_bridge,
)


# ---------------------------------------------------------------------------
# No-import gate for compiler.py
# ---------------------------------------------------------------------------

def test_compiler_has_no_django_graphene_imports():
    import re
    import pathlib
    path = pathlib.Path(__file__).parent.parent.parent / "django_graphex" / "native" / "compiler.py"
    src = path.read_text()
    # Match 'from django ' or 'from django.' (but NOT 'from django_graphex')
    # Match 'from graphene ' or 'from graphene.' (external graphene package)
    forbidden = re.compile(
        r"^(from django[.\s]|import django[.\s]|from graphene[.\s]|import graphene[.\s])",
        re.MULTILINE,
    )
    assert forbidden.findall(src) == [], "Forbidden imports in compiler.py"


def test_bridge_has_no_django_graphene_imports():
    import re
    import pathlib
    path = pathlib.Path(__file__).parent.parent.parent / "django_graphex" / "native" / "bridge.py"
    src = path.read_text()
    forbidden = re.compile(
        r"^(from django[.\s]|import django[.\s]|from graphene[.\s]|import graphene[.\s])",
        re.MULTILINE,
    )
    assert forbidden.findall(src) == [], "Forbidden imports in bridge.py"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def make_simple_schema(extra_fields=None):
    """Build a minimal schema: Query { hello: String }."""
    fields = {"hello": FieldSpec(name="hello", type=TypeRef(name="String"))}
    if extra_fields:
        fields.update(extra_fields)
    query = TypeSpec(name="Query", fields=tuple(fields.values()))
    return compile_schema(types=[query], enums=[], query=query)


# ---------------------------------------------------------------------------
# T1.3 — compile_type: camelCase via dict KEY
# ---------------------------------------------------------------------------

class TestCamelCaseKey:
    def test_created_at_becomes_camel_case(self):
        """FieldSpec(name='created_at') → fields key is 'createdAt'."""
        spec = TypeSpec(
            name="Post",
            fields=(FieldSpec(name="created_at", type=TypeRef(name="String")),),
        )
        # Use compile_schema so scalars are seeded into _TYPE_CACHE
        schema = compile_schema(types=[spec], enums=[], query=spec)
        obj_type = schema.type_map["Post"]
        assert "createdAt" in obj_type.fields, f"Expected 'createdAt', got: {list(obj_type.fields.keys())}"
        assert "created_at" not in obj_type.fields

    def test_snake_single_word_unchanged(self):
        """Single-word field 'title' stays 'title'."""
        spec = TypeSpec(
            name="Post",
            fields=(FieldSpec(name="title", type=TypeRef(name="String")),),
        )
        schema = compile_schema(types=[spec], enums=[], query=spec)
        obj_type = schema.type_map["Post"]
        assert "title" in obj_type.fields

    def test_multiple_underscore_words(self):
        """'first_name_value' → 'firstNameValue'."""
        spec = TypeSpec(
            name="Person",
            fields=(FieldSpec(name="first_name_value", type=TypeRef(name="String")),),
        )
        schema = compile_schema(types=[spec], enums=[], query=spec)
        obj_type = schema.type_map["Person"]
        assert "firstNameValue" in obj_type.fields

    def test_multiple_fields_no_aliasing(self):
        """Two fields must not alias to the same key (loop-capture fix)."""
        spec = TypeSpec(
            name="Query",
            fields=(
                FieldSpec(name="created_at", type=TypeRef(name="String")),
                FieldSpec(name="updated_at", type=TypeRef(name="String")),
            ),
        )
        schema = compile_schema(types=[spec], enums=[], query=spec)
        obj_type = schema.type_map["Query"]
        assert "createdAt" in obj_type.fields
        assert "updatedAt" in obj_type.fields
        # Verify resolvers are distinct (loop-capture fix verification)
        resolver_created = obj_type.fields["createdAt"].resolve
        resolver_updated = obj_type.fields["updatedAt"].resolve
        # Each resolver should read the correct snake-key
        root = {"created_at": "A", "updated_at": "B"}
        assert resolver_created(root, None) == "A"
        assert resolver_updated(root, None) == "B"


# ---------------------------------------------------------------------------
# T1.3 — Default resolver: dict and object sources
# ---------------------------------------------------------------------------

class TestDefaultResolver:
    def setup_method(self):
        _reset_cache()

    def test_dict_source(self):
        """Resolver reads snake key from a dict."""
        spec = TypeSpec(
            name="Query",
            fields=(FieldSpec(name="created_at", type=TypeRef(name="String")),),
        )
        schema = compile_schema(types=[spec], enums=[], query=spec)
        result = graphql_sync(
            schema,
            "{ createdAt }",
            root_value={"created_at": "2024-01-01"},
        )
        assert result.errors is None
        assert result.data == {"createdAt": "2024-01-01"}

    def test_object_source(self):
        """Resolver reads snake attribute from an object (SimpleNamespace)."""
        spec = TypeSpec(
            name="Query",
            fields=(FieldSpec(name="created_at", type=TypeRef(name="String")),),
        )
        schema = compile_schema(types=[spec], enums=[], query=spec)
        result = graphql_sync(
            schema,
            "{ createdAt }",
            root_value=SimpleNamespace(created_at="2024-01-01"),
        )
        assert result.errors is None
        assert result.data == {"createdAt": "2024-01-01"}

    def test_custom_resolver_overrides_default(self):
        """FieldSpec.resolver overrides the snake-closure default."""
        custom_resolver = lambda root, info: "custom-value"
        spec = TypeSpec(
            name="Query",
            fields=(FieldSpec(
                name="hello",
                type=TypeRef(name="String"),
                resolver=custom_resolver,
            ),),
        )
        schema = compile_schema(types=[spec], enums=[], query=spec)
        result = graphql_sync(schema, "{ hello }", root_value={})
        assert result.errors is None
        assert result.data == {"hello": "custom-value"}


# ---------------------------------------------------------------------------
# T1.3 — Mutual recursion (A→B→A) terminates
# ---------------------------------------------------------------------------

class TestMutualRecursion:
    def test_cycle_compile_does_not_raise(self):
        """Author.books → [Book] and Book.author → Author must compile."""
        author_spec = TypeSpec(
            name="Author",
            fields=(
                FieldSpec(name="name", type=TypeRef(name="String")),
                FieldSpec(name="books", type=TypeRef(name="Book", list=True)),
            ),
        )
        book_spec = TypeSpec(
            name="Book",
            fields=(
                FieldSpec(name="title", type=TypeRef(name="String")),
                FieldSpec(name="author", type=TypeRef(name="Author")),
            ),
        )
        query_spec = TypeSpec(
            name="Query",
            fields=(FieldSpec(name="author", type=TypeRef(name="Author")),),
        )
        schema = compile_schema(
            types=[author_spec, book_spec, query_spec],
            enums=[],
            query=query_spec,
        )
        assert "Author" in schema.type_map
        assert "Book" in schema.type_map

    def test_cycle_resolves_at_execute_time(self):
        """Fields in the cyclic schema resolve correctly."""
        author_spec = TypeSpec(
            name="Author",
            fields=(FieldSpec(name="name", type=TypeRef(name="String")),),
        )
        query_spec = TypeSpec(
            name="Query",
            fields=(FieldSpec(name="author", type=TypeRef(name="Author")),),
        )
        schema = compile_schema(
            types=[author_spec, query_spec],
            enums=[],
            query=query_spec,
        )
        result = graphql_sync(
            schema,
            "{ author { name } }",
            root_value={"author": {"name": "Alice"}},
        )
        assert result.errors is None
        assert result.data == {"author": {"name": "Alice"}}


# ---------------------------------------------------------------------------
# T1.3 — _reset_cache prevents cross-case leakage
# ---------------------------------------------------------------------------

class TestCacheReset:
    def test_second_schema_does_not_include_first_types(self):
        """compile_schema resets the cache, so types from call 1 don't appear in call 2."""
        spec1 = TypeSpec(
            name="QueryOne",
            fields=(FieldSpec(name="a", type=TypeRef(name="String")),),
        )
        schema1 = compile_schema(types=[spec1], enums=[], query=spec1)

        spec2 = TypeSpec(
            name="QueryTwo",
            fields=(FieldSpec(name="b", type=TypeRef(name="String")),),
        )
        schema2 = compile_schema(types=[spec2], enums=[], query=spec2)

        assert "QueryOne" not in schema2.type_map
        assert "QueryTwo" in schema2.type_map


# ---------------------------------------------------------------------------
# T1.3 — NonNull and List wrapping
# ---------------------------------------------------------------------------

class TestNonNullListWrapping:
    def test_non_null_string(self):
        from graphql import GraphQLNonNull, GraphQLScalarType
        spec = TypeSpec(
            name="Query",
            fields=(FieldSpec(name="title", type=TypeRef(name="String", non_null=True)),),
        )
        schema = compile_schema(types=[spec], enums=[], query=spec)
        field = schema.type_map["Query"].fields["title"]
        assert hasattr(field.type, "of_type"), "Expected NonNull wrapper"

    def test_list_of_strings(self):
        from graphql import GraphQLList
        spec = TypeSpec(
            name="Query",
            fields=(FieldSpec(name="tags", type=TypeRef(name="String", list=True)),),
        )
        schema = compile_schema(types=[spec], enums=[], query=spec)
        field = schema.type_map["Query"].fields["tags"]
        # Should be a List wrapper
        from graphql import GraphQLList
        assert isinstance(field.type, GraphQLList), f"Expected List, got {type(field.type)}"

    def test_non_null_list_of_non_null(self):
        """TypeRef(name, list=True, non_null=True, inner=TypeRef(non_null=True)) → [String!]!"""
        inner = TypeRef(name="String", non_null=True)
        ref = TypeRef(name="String", list=True, non_null=True, inner=inner)
        spec = TypeSpec(
            name="Query",
            fields=(FieldSpec(name="tags", type=ref),),
        )
        schema = compile_schema(types=[spec], enums=[], query=spec)
        field = schema.type_map["Query"].fields["tags"]
        from graphql import GraphQLNonNull, GraphQLList
        assert isinstance(field.type, GraphQLNonNull)
        assert isinstance(field.type.of_type, GraphQLList)


# ---------------------------------------------------------------------------
# T1.3 — compile_enum: raw value at execute time
# ---------------------------------------------------------------------------

class TestEnumRawValue:
    def test_enum_delivers_raw_int_value(self):
        """compile_enum uses GraphQLEnumValue(value=raw).

        graphql-core's enum serializer maps raw_value → wire_name.
        So root returning raw int 1 → wire "ACTIVE".
        The raw int is what a Django model field would return.
        """
        status_enum = EnumSpec(
            name="Status",
            values=(("ACTIVE", 1), ("INACTIVE", 0)),
        )
        query_spec = TypeSpec(
            name="Query",
            fields=(FieldSpec(name="status", type=TypeRef(name="Status")),),
        )
        schema = compile_schema(types=[query_spec], enums=[status_enum], query=query_spec)
        # root returns raw Python int 1 → enum serializer maps to "ACTIVE"
        result = graphql_sync(
            schema,
            "{ status }",
            root_value={"status": 1},  # raw int value
        )
        assert result.errors is None
        assert result.data["status"] == "ACTIVE"  # GraphQL wire name

    def test_enum_delivers_raw_string_value(self):
        """String raw values are delivered correctly.

        EnumSpec values=(('RED', 'red'), ...) means raw value is 'red'.
        Root returns 'red' → serializer maps to 'RED'.
        """
        color_enum = EnumSpec(
            name="Color",
            values=(("RED", "red"), ("BLUE", "blue")),
        )
        query_spec = TypeSpec(
            name="Query",
            fields=(FieldSpec(name="color", type=TypeRef(name="Color")),),
        )
        schema = compile_schema(types=[query_spec], enums=[color_enum], query=query_spec)
        result = graphql_sync(
            schema,
            "{ color }",
            root_value={"color": "red"},  # raw string value (not wire name "RED")
        )
        assert result.errors is None
        assert result.data["color"] == "RED"  # GraphQL wire name


# ---------------------------------------------------------------------------
# T1.3 — Golden SDL (structural)
# ---------------------------------------------------------------------------

class TestGoldenSDL:
    def test_simple_query_sdl(self):
        """A simple schema with 'hello: String' should produce expected SDL."""
        spec = TypeSpec(
            name="Query",
            fields=(FieldSpec(name="hello", type=TypeRef(name="String")),),
        )
        schema = compile_schema(types=[spec], enums=[], query=spec)
        sdl = print_schema(schema)
        normalized = normalize_sdl(sdl)
        # Query type with hello field should be present
        assert "type Query" in normalized
        assert "hello: String" in normalized

    def test_camel_case_in_sdl(self):
        """created_at field should appear as createdAt in SDL."""
        spec = TypeSpec(
            name="Query",
            fields=(FieldSpec(name="created_at", type=TypeRef(name="String")),),
        )
        schema = compile_schema(types=[spec], enums=[], query=spec)
        sdl = print_schema(schema)
        assert "createdAt" in sdl
        assert "created_at" not in sdl

    def test_all_7_custom_scalars_in_map_sdl(self):
        """When all 7 custom scalars are referenced, they appear in SDL.

        TypeRef names are GDX_SCALAR_MAP keys = graphene scalar names (#1508).
        """
        spec = TypeSpec(
            name="Query",
            fields=(
                FieldSpec(name="date_val", type=TypeRef(name="CustomDate")),
                FieldSpec(name="datetime_val", type=TypeRef(name="CustomDateTime")),
                FieldSpec(name="time_val", type=TypeRef(name="CustomTime")),
                FieldSpec(name="decimal_val", type=TypeRef(name="Decimal")),
                FieldSpec(name="uuid_val", type=TypeRef(name="UUID")),
                FieldSpec(name="json_val", type=TypeRef(name="JSONString")),
                FieldSpec(name="generic_val", type=TypeRef(name="GenericScalar")),
            ),
        )
        schema = compile_schema(types=[spec], enums=[], query=spec)
        sdl = print_schema(schema)
        for scalar_name in ("CustomDate", "CustomDateTime", "CustomTime", "Decimal", "UUID", "JSONString", "GenericScalar"):
            assert scalar_name in sdl, f"Missing scalar {scalar_name} in SDL"

    def test_nonnull_list_in_sdl(self):
        """[String!]! wrapping should appear in SDL."""
        inner = TypeRef(name="String", non_null=True)
        ref = TypeRef(name="String", list=True, non_null=True, inner=inner)
        spec = TypeSpec(
            name="Query",
            fields=(FieldSpec(name="tags", type=ref),),
        )
        schema = compile_schema(types=[spec], enums=[], query=spec)
        sdl = print_schema(schema)
        assert "[String!]!" in sdl

    def test_enum_in_sdl(self):
        """Compiled enum should appear in SDL."""
        status_enum = EnumSpec(
            name="Status",
            values=(("ACTIVE", 1), ("INACTIVE", 0)),
        )
        query_spec = TypeSpec(
            name="Query",
            fields=(FieldSpec(name="status", type=TypeRef(name="Status")),),
        )
        schema = compile_schema(types=[query_spec], enums=[status_enum], query=query_spec)
        sdl = print_schema(schema)
        assert "enum Status" in sdl
        assert "ACTIVE" in sdl
        assert "INACTIVE" in sdl


# ---------------------------------------------------------------------------
# T1.4 — Bridge: GdxPayload + _MetaView + assert_gdx_bridge
# ---------------------------------------------------------------------------

class TestBridge:
    def test_compiled_schema_has_gdx_extensions(self):
        """Every type in a compile_schema output carries extensions['gdx']."""
        spec = TypeSpec(
            name="Query",
            fields=(FieldSpec(name="hello", type=TypeRef(name="String")),),
        )
        schema = compile_schema(types=[spec], enums=[], query=spec)
        query_type = schema.type_map["Query"]
        assert "gdx" in query_type.extensions, "extensions['gdx'] missing from compiled type"

    def test_assert_gdx_bridge_passes_for_compiled_schema(self):
        """assert_gdx_bridge(schema) must not raise for a compile_schema output."""
        spec = TypeSpec(
            name="Query",
            fields=(FieldSpec(name="hello", type=TypeRef(name="String")),),
        )
        schema = compile_schema(types=[spec], enums=[], query=spec)
        # Should not raise
        assert_gdx_bridge(schema)

    def test_assert_gdx_bridge_raises_for_bare_type(self):
        """assert_gdx_bridge must raise for a schema with a bare type (no extensions['gdx'])."""
        bare_type = GraphQLObjectType(
            "Bare",
            {"hello": GraphQLField(GraphQLString)},
            # No extensions={'gdx': ...}
        )
        query_type = GraphQLObjectType(
            "Query",
            {"bare": GraphQLField(bare_type)},
        )
        # Note: Query also lacks gdx extension, so it should fail too
        schema = GraphQLSchema(query=query_type)
        with pytest.raises((AssertionError, ValueError, TypeError, Exception)):
            assert_gdx_bridge(schema)

    def test_gdx_payload_reachable_from_type_extensions(self):
        """GdxPayload should be accessible via type.extensions['gdx']."""
        spec = TypeSpec(
            name="Query",
            fields=(FieldSpec(name="hello", type=TypeRef(name="String")),),
            gdx=GdxMeta(max_deep=5),
        )
        schema = compile_schema(types=[spec], enums=[], query=spec)
        query_type = schema.type_map["Query"]
        payload = query_type.extensions["gdx"]
        assert isinstance(payload, GdxPayload)

    def test_meta_view_known_attribute(self):
        """_MetaView exposes known attrs from the GdxMeta."""
        from django_graphex.native.bridge import _MetaView
        meta = GdxMeta(max_deep=3, complexity=2)
        view = _MetaView(meta)
        assert view.max_deep == 3
        assert view.complexity == 2

    def test_meta_view_unknown_attribute_raises_attribute_error(self):
        """_MetaView raises AttributeError (never returns None) on unknown attr."""
        from django_graphex.native.bridge import _MetaView
        meta = GdxMeta()
        view = _MetaView(meta)
        with pytest.raises(AttributeError):
            _ = view.bogus_attr_that_does_not_exist

    def test_gdx_payload_meta_property(self):
        """GdxPayload._meta returns a _MetaView for graphene_type._meta compat."""
        payload = GdxPayload(GdxMeta(max_deep=7))
        meta = payload._meta
        assert meta.max_deep == 7

    def test_assert_gdx_bridge_skips_introspection_types(self):
        """Introspection types (starting with __) should not trigger the bridge check."""
        spec = TypeSpec(
            name="Query",
            fields=(FieldSpec(name="hello", type=TypeRef(name="String")),),
        )
        schema = compile_schema(types=[spec], enums=[], query=spec)
        # Introspection types like __Schema, __Type etc should not cause failures
        # (they are handled by graphql-core, not our compiler)
        assert_gdx_bridge(schema)  # must not raise


# ---------------------------------------------------------------------------
# T1.5 — GDX_SCALAR_MAP seeded in compile_schema
# ---------------------------------------------------------------------------

class TestScalarCacheSeeding:
    def test_gdx_date_in_schema_type_map(self):
        """The date scalar is reachable in the type_map after compile_schema.

        Keyed by the graphene scalar name ``CustomDate`` (#1508).
        """
        spec = TypeSpec(
            name="Query",
            fields=(FieldSpec(name="birthday", type=TypeRef(name="CustomDate")),),
        )
        schema = compile_schema(types=[spec], enums=[], query=spec)
        assert "CustomDate" in schema.type_map

    def test_standard_string_scalar_resolves(self):
        """Standard String scalar works without explicit TypeSpec."""
        spec = TypeSpec(
            name="Query",
            fields=(FieldSpec(name="hello", type=TypeRef(name="String")),),
        )
        schema = compile_schema(types=[spec], enums=[], query=spec)
        result = graphql_sync(schema, "{ hello }", root_value={"hello": "world"})
        assert result.errors is None
        assert result.data == {"hello": "world"}


# ---------------------------------------------------------------------------
# Coverage gap fillers — branch coverage for compiler.py / bridge.py
# ---------------------------------------------------------------------------

class TestCompilerCoverageBranches:
    def test_memoized_type_returns_cached(self):
        """compile_type called twice on same name returns the cached object."""
        spec = TypeSpec(
            name="CachedType",
            fields=(FieldSpec(name="x", type=TypeRef(name="String")),),
        )
        schema = compile_schema(types=[spec], enums=[], query=spec)
        # Re-compile same spec — should hit the cache branch
        from django_graphex.native.compiler import compile_type, _TYPE_CACHE
        cached = _TYPE_CACHE.get("CachedType")
        result = compile_type(spec)
        assert result is cached

    def test_memoized_enum_returns_cached(self):
        """compile_enum called twice on same name returns the cached object."""
        status_enum = EnumSpec(name="CachedEnum", values=(("A", 1),))
        query_spec = TypeSpec(
            name="Query",
            fields=(FieldSpec(name="s", type=TypeRef(name="CachedEnum")),),
        )
        schema = compile_schema(types=[query_spec], enums=[status_enum], query=query_spec)
        from django_graphex.native.compiler import compile_enum, _TYPE_CACHE
        cached = _TYPE_CACHE.get("CachedEnum")
        result = compile_enum(status_enum)
        assert result is cached

    def test_enum_with_descriptions(self):
        """compile_enum with descriptions sets GraphQLEnumValue description."""
        status_enum = EnumSpec(
            name="DescStatus",
            values=(("ACTIVE", 1), ("INACTIVE", 0)),
            descriptions={"ACTIVE": "Is active", "INACTIVE": "Is inactive"},
        )
        query_spec = TypeSpec(
            name="Query",
            fields=(FieldSpec(name="s", type=TypeRef(name="DescStatus")),),
        )
        schema = compile_schema(types=[query_spec], enums=[status_enum], query=query_spec)
        enum_type = schema.type_map["DescStatus"]
        assert enum_type.values["ACTIVE"].description == "Is active"

    def test_inner_ref_non_null_list(self):
        """TypeRef with inner ref and both list=True, non_null=True on inner branch."""
        # This exercises the branch where ref.inner is set but ref.non_null=False
        # (inner ref only has list without the outer non_null)
        inner = TypeRef(name="String", non_null=False)
        ref = TypeRef(name="String", list=True, non_null=False, inner=inner)
        spec = TypeSpec(
            name="Query",
            fields=(FieldSpec(name="tags", type=ref),),
        )
        schema = compile_schema(types=[spec], enums=[], query=spec)
        from graphql import GraphQLList
        field = schema.type_map["Query"].fields["tags"]
        assert isinstance(field.type, GraphQLList)

    def test_compile_schema_with_mutation(self):
        """compile_schema with mutation= builds a schema with both query and mutation."""
        query_spec = TypeSpec(
            name="Query",
            fields=(FieldSpec(name="hello", type=TypeRef(name="String")),),
        )
        mutation_spec = TypeSpec(
            name="Mutation",
            fields=(FieldSpec(name="do_something", type=TypeRef(name="String")),),
        )
        schema = compile_schema(
            types=[query_spec, mutation_spec],
            enums=[],
            query=query_spec,
            mutation=mutation_spec,
        )
        assert schema.mutation_type is not None
        assert schema.mutation_type.name == "Mutation"

    def test_compile_schema_unknown_query_type_raises(self):
        """compile_schema raises ValueError when query type is missing from types."""
        query_spec = TypeSpec(
            name="MissingQuery",
            fields=(FieldSpec(name="hello", type=TypeRef(name="String")),),
        )
        other_spec = TypeSpec(
            name="OtherType",
            fields=(FieldSpec(name="x", type=TypeRef(name="String")),),
        )
        # Pass other_spec as types but query_spec as query → MissingQuery not compiled
        with pytest.raises((ValueError, KeyError, AssertionError, Exception)):
            compile_schema(types=[other_spec], enums=[], query=query_spec)


class TestBridgeCoverageBranches:
    def test_meta_view_private_attr_raises(self):
        """_MetaView raises AttributeError for names starting with '_'."""
        from django_graphex.native.bridge import _MetaView
        view = _MetaView(GdxMeta())
        with pytest.raises(AttributeError):
            _ = view._private_attr

    def test_meta_view_known_attr_not_on_meta_raises(self):
        """_MetaView raises AttributeError when attr is in allowlist but not on GdxMeta."""
        from django_graphex.native.bridge import _MetaView, _GDX_ALLOWLIST

        class FakeMeta:
            pass  # Has none of the allowlist attrs

        # Find an allowlist attr not on GdxMeta
        view = _MetaView(FakeMeta())
        # 'model' IS on GdxMeta (returns None by default) — pick something
        # that won't be on FakeMeta and IS in the allowlist
        # 'stream' is in the allowlist but not on GdxMeta
        assert "stream" in _GDX_ALLOWLIST
        with pytest.raises(AttributeError):
            _ = view.stream

    def test_assert_gdx_bridge_skips_non_assertable_types(self):
        """assert_gdx_bridge skips union types (they don't need the bridge)."""
        # Test that a compiled schema with multiple types all pass
        spec_a = TypeSpec(
            name="TypeA",
            fields=(FieldSpec(name="x", type=TypeRef(name="String")),),
        )
        query_spec = TypeSpec(
            name="Query",
            fields=(FieldSpec(name="type_a", type=TypeRef(name="TypeA")),),
        )
        schema = compile_schema(types=[spec_a, query_spec], enums=[], query=query_spec)
        # Should pass without raising
        assert_gdx_bridge(schema)

    def test_assert_gdx_bridge_skips_enum_types(self):
        """assert_gdx_bridge skips enum types in the schema type_map."""
        status_enum = EnumSpec(
            name="BridgeStatus",
            values=(("ACTIVE", 1),),
        )
        query_spec = TypeSpec(
            name="Query",
            fields=(FieldSpec(name="s", type=TypeRef(name="BridgeStatus")),),
        )
        schema = compile_schema(types=[query_spec], enums=[status_enum], query=query_spec)
        # Enum types in type_map should be skipped, not cause assertion failure
        assert "BridgeStatus" in schema.type_map
        assert_gdx_bridge(schema)  # Must not raise


class TestCompilerRefResolutionBranches:
    """Targeted tests for uncovered branches in _resolve_ref and compile functions."""

    def test_inner_ref_list_only_no_outer_nonnull(self):
        """TypeRef with inner set, list=True, non_null=False.

        Exercises the branch where ref.inner is not None and ref.list=True,
        but ref.non_null=False (goes through 89->90 but not 91->92).
        """
        # inner ref: non_null=True (String!), outer: list=True, non_null=False → [String!]
        inner = TypeRef(name="String", non_null=True)
        ref = TypeRef(name="String", list=True, non_null=False, inner=inner)
        spec = TypeSpec(
            name="Query",
            fields=(FieldSpec(name="x", type=ref),),
        )
        schema = compile_schema(types=[spec], enums=[], query=spec)
        from graphql import GraphQLList
        field = schema.type_map["Query"].fields["x"]
        assert isinstance(field.type, GraphQLList)  # [String!] not wrapped in NonNull

    def test_compile_schema_mutation_type_not_in_types_raises(self):
        """compile_schema raises ValueError if mutation type is declared but missing."""
        query_spec = TypeSpec(
            name="Query",
            fields=(FieldSpec(name="hello", type=TypeRef(name="String")),),
        )
        mutation_spec = TypeSpec(
            name="MissingMutation",
            fields=(FieldSpec(name="do_it", type=TypeRef(name="String")),),
        )
        # Don't include mutation_spec in types
        with pytest.raises((ValueError, Exception)):
            compile_schema(
                types=[query_spec],
                enums=[],
                query=query_spec,
                mutation=mutation_spec,
            )

    def test_compile_type_cache_hit_non_object_type_falls_through(self):
        """compile_type when cache has a non-GraphQLObjectType for the same name
        falls through and creates a new type (exercises branch 169->173)."""
        from django_graphex.native.compiler import _TYPE_CACHE
        from graphql import GraphQLScalarType

        spec = TypeSpec(
            name="Query",
            fields=(FieldSpec(name="x", type=TypeRef(name="String")),),
        )
        schema = compile_schema(types=[spec], enums=[], query=spec)

        # Now manually put a non-GraphQLObjectType into the cache with the same name
        fake_scalar = GraphQLScalarType("FakeCollision", serialize=str)
        _TYPE_CACHE["FakeCollision"] = fake_scalar

        # Create a new spec with that name
        collision_spec = TypeSpec(
            name="FakeCollision",
            fields=(FieldSpec(name="y", type=TypeRef(name="String")),),
        )
        result = compile_type(collision_spec)
        from graphql import GraphQLObjectType as GQLObjType
        assert isinstance(result, GQLObjType)

    def test_compile_enum_cache_hit_non_enum_type_falls_through(self):
        """compile_enum when cache has a non-GraphQLEnumType falls through
        and creates a new enum type (exercises branch 202->205)."""
        from django_graphex.native.compiler import _TYPE_CACHE, compile_enum
        from graphql import GraphQLScalarType

        spec = TypeSpec(
            name="Query",
            fields=(FieldSpec(name="x", type=TypeRef(name="String")),),
        )
        schema = compile_schema(types=[spec], enums=[], query=spec)

        # Manually put a non-GraphQLEnumType into cache under a name
        fake_scalar = GraphQLScalarType("FakeEnumCollision", serialize=str)
        _TYPE_CACHE["FakeEnumCollision"] = fake_scalar

        fake_enum_spec = EnumSpec(
            name="FakeEnumCollision",
            values=(("A", 1),),
        )
        result = compile_enum(fake_enum_spec)
        from graphql import GraphQLEnumType as GQLEnumType
        assert isinstance(result, GQLEnumType)

    def test_resolve_ref_unknown_type_raises_at_execute(self):
        """Accessing a field whose type is unknown raises at field resolution time."""
        # Build a schema where a field refs an unknown type, then execute
        # This should surface as an error (either build-time or execute-time)
        from django_graphex.native.compiler import _TYPE_CACHE, _reset_cache, compile_type
        _reset_cache()
        from django_graphex.native.scalars import GDX_SCALAR_MAP
        for name, scalar in GDX_SCALAR_MAP.items():
            _TYPE_CACHE[name] = scalar

        spec = TypeSpec(
            name="Query",
            fields=(FieldSpec(name="x", type=TypeRef(name="NonExistentType")),),
        )
        # compile_type registers the type placeholder
        compile_type(spec)
        # When we try to access .fields, graphql-core calls the thunk
        # which calls _resolve_ref for "NonExistentType" → ValueError
        query_type = _TYPE_CACHE.get("Query")
        with pytest.raises((ValueError, TypeError, Exception)):
            _ = query_type.fields  # triggers the thunk
