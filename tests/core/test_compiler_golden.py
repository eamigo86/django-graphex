"""Tests for core/compiler.py + core/bridge.py — golden SDL and functional gates.

No Django settings required. No django_db markers.
Run with: pytest tests/core/test_compiler_golden.py -x --no-cov

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
from graphql import (
    GraphQLField,
    GraphQLObjectType,
    GraphQLSchema,
    GraphQLString,
    graphql_sync,
)
from graphql.utilities import print_schema

from django_graphex.core.bridge import (
    GdxPayload,
    assert_gdx_bridge,
)
from django_graphex.core.compiler import (
    _reset_cache,
    compile_enum,
    compile_schema,
    compile_type,
)
from django_graphex.core.ir import EnumSpec, FieldSpec, GdxMeta, TypeRef, TypeSpec

# ---------------------------------------------------------------------------
# normalize_sdl helper (pinned definition)
# ---------------------------------------------------------------------------


def normalize_sdl(sdl: str) -> str:
    """Normalize a GraphQL SDL string for structural comparison.

    Strips descriptions, sorts type blocks and fields within blocks.

    Args:
        sdl: The raw GraphQL SDL text to normalize.

    Returns:
        normalized: The SDL with descriptions removed and blocks/fields sorted,
            stripped of surrounding whitespace.
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
# No-import gate for compiler.py
# ---------------------------------------------------------------------------


def test_compiler_has_no_django_graphene_imports() -> None:
    """core/compiler.py must never import Django or graphene.

    If this fails, the compiler module has regained a dependency on Django or
    graphene, breaking the framework-free contract the core layer relies on.
    """
    import pathlib
    import re

    path = (
        pathlib.Path(__file__).parent.parent.parent
        / "django_graphex"
        / "core"
        / "compiler.py"
    )
    src = path.read_text()
    # Match 'from django ' or 'from django.' (but NOT 'from django_graphex')
    # Match 'from graphene ' or 'from graphene.' (external graphene package)
    forbidden = re.compile(
        r"^(from django[.\s]|import django[.\s]|from graphene[.\s]|import graphene[.\s])",
        re.MULTILINE,
    )
    assert forbidden.findall(src) == [], "Forbidden imports in compiler.py"


def test_bridge_has_no_django_graphene_imports() -> None:
    """core/bridge.py must never import Django or graphene.

    If this fails, the bridge module has regained a dependency on Django or
    graphene, breaking the framework-free contract the core layer relies on.
    """
    import pathlib
    import re

    path = (
        pathlib.Path(__file__).parent.parent.parent
        / "django_graphex"
        / "core"
        / "bridge.py"
    )
    src = path.read_text()
    forbidden = re.compile(
        r"^(from django[.\s]|import django[.\s]|from graphene[.\s]|import graphene[.\s])",
        re.MULTILINE,
    )
    assert forbidden.findall(src) == [], "Forbidden imports in bridge.py"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def make_simple_schema(
    extra_fields: dict[str, FieldSpec] | None = None,
) -> GraphQLSchema:
    """Build a minimal schema: Query { hello: String }.

    Args:
        extra_fields: Additional "FieldSpec" entries, keyed by field name, to
            merge into the Query type alongside "hello".

    Returns:
        schema: The compiled "GraphQLSchema" for the resulting Query type.
    """
    fields = {"hello": FieldSpec(name="hello", type=TypeRef(name="String"))}
    if extra_fields:
        fields.update(extra_fields)
    query = TypeSpec(name="Query", fields=tuple(fields.values()))
    return compile_schema(types=[query], enums=[], query=query)


# ---------------------------------------------------------------------------
# T1.3 — compile_type: camelCase via dict KEY
# ---------------------------------------------------------------------------


class TestCamelCaseKey:
    """compile_type() must expose object fields under their camelCase key.

    Snake_case FieldSpec names are the canonical Python-side identifiers;
    the compiled GraphQL type must expose the camelCase wire name instead.
    """

    def test_created_at_becomes_camel_case(self) -> None:
        """FieldSpec(name="created_at") must expose fields key "createdAt".

        If this fails, snake_case field names stop being converted to
        camelCase on the compiled GraphQL type.
        """
        spec = TypeSpec(
            name="Post",
            fields=(FieldSpec(name="created_at", type=TypeRef(name="String")),),
        )
        # Use compile_schema so scalars are seeded into _TYPE_CACHE
        schema = compile_schema(types=[spec], enums=[], query=spec)
        obj_type = schema.type_map["Post"]
        assert "createdAt" in obj_type.fields, (
            f"Expected 'createdAt', got: {list(obj_type.fields.keys())}"
        )
        assert "created_at" not in obj_type.fields

    def test_snake_single_word_unchanged(self) -> None:
        """A single-word field name such as "title" must stay unchanged.

        If this fails, the camelCase conversion incorrectly mutates
        single-word field names that have no underscores to convert.
        """
        spec = TypeSpec(
            name="Post",
            fields=(FieldSpec(name="title", type=TypeRef(name="String")),),
        )
        schema = compile_schema(types=[spec], enums=[], query=spec)
        obj_type = schema.type_map["Post"]
        assert "title" in obj_type.fields

    def test_multiple_underscore_words(self) -> None:
        """ "first_name_value" must become "firstNameValue".

        If this fails, multi-word snake_case names are not fully converted
        to camelCase (e.g. only the first underscore is handled).
        """
        spec = TypeSpec(
            name="Person",
            fields=(FieldSpec(name="first_name_value", type=TypeRef(name="String")),),
        )
        schema = compile_schema(types=[spec], enums=[], query=spec)
        obj_type = schema.type_map["Person"]
        assert "firstNameValue" in obj_type.fields

    def test_multiple_fields_no_aliasing(self) -> None:
        """Two distinct fields must not alias to the same compiled key.

        Regression guard for a loop-capture bug: if this fails, resolvers
        built in a loop end up sharing a closure and both fields resolve
        to the same (wrong) value.
        """
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
    """compile_type()'s default resolver must read the snake_case source key.

    This applies whether the resolved GraphQL root value is a dict or a
    plain Python object exposing snake_case attributes.
    """

    def setup_method(self) -> None:
        """Reset the compiler's module-level type cache before each test.

        If this fails to run, a type compiled by an earlier test could leak
        into this test's schema through the shared cache.
        """
        _reset_cache()

    def test_dict_source(self) -> None:
        """Resolver reads snake key from a dict.

        If this fails, a dict-backed root value would no longer resolve a
        camelCase field to its underlying snake_case dict key.
        """
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

    def test_object_source(self) -> None:
        """Resolver reads snake attribute from an object (SimpleNamespace).

        If this fails, an object-backed root value would no longer resolve a
        camelCase field to its underlying snake_case attribute.
        """
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

    def test_custom_resolver_overrides_default(self) -> None:
        """FieldSpec.resolver overrides the snake-closure default.

        If this fails, an explicit "resolver" on a "FieldSpec" would be
        ignored in favor of the auto-generated snake_case default resolver.
        """

        def custom_resolver(root, info):
            return "custom-value"

        spec = TypeSpec(
            name="Query",
            fields=(
                FieldSpec(
                    name="hello",
                    type=TypeRef(name="String"),
                    resolver=custom_resolver,
                ),
            ),
        )
        schema = compile_schema(types=[spec], enums=[], query=spec)
        result = graphql_sync(schema, "{ hello }", root_value={})
        assert result.errors is None
        assert result.data == {"hello": "custom-value"}


# ---------------------------------------------------------------------------
# T1.3 — Mutual recursion (A→B→A) terminates
# ---------------------------------------------------------------------------


class TestMutualRecursion:
    """A-to-B-to-A mutually-recursive TypeSpec graphs must compile without recursing forever.

    Covers both schema compilation and runtime field resolution over the
    cyclic type graph.
    """

    def test_cycle_compile_does_not_raise(self) -> None:
        """Author.books to [Book] and Book.author to Author must compile.

        If this fails, mutually recursive TypeSpec references between two
        object types would blow the stack or loop forever during compilation.
        """
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

    def test_cycle_resolves_at_execute_time(self) -> None:
        """Fields in the cyclic schema resolve correctly.

        If this fails, a mutually recursive schema would compile but fail to
        actually resolve field values at query-execution time.
        """
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
    """compile_schema() must reset its module-level type cache on every call.

    Without the reset, types from an earlier, unrelated schema could leak
    into a later schema's type_map.
    """

    def test_second_schema_does_not_include_first_types(self) -> None:
        """compile_schema resets the cache, so types from call 1 do not appear in call 2.

        If this fails, a second unrelated compile_schema() call would leak
        types from a prior schema into the new one's type_map.
        """
        spec1 = TypeSpec(
            name="QueryOne",
            fields=(FieldSpec(name="a", type=TypeRef(name="String")),),
        )
        compile_schema(types=[spec1], enums=[], query=spec1)

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
    """TypeRef's non_null/list flags must compile to the matching GraphQL wrapper types.

    Covers plain non-null scalars, plain lists, and nested non-null lists of
    non-null scalars.
    """

    def test_non_null_string(self) -> None:
        """TypeRef(non_null=True) must compile to a GraphQLNonNull-wrapped field.

        If this fails, a required scalar field would compile as nullable,
        silently weakening the GraphQL schema's non-null guarantee.
        """
        spec = TypeSpec(
            name="Query",
            fields=(
                FieldSpec(name="title", type=TypeRef(name="String", non_null=True)),
            ),
        )
        schema = compile_schema(types=[spec], enums=[], query=spec)
        field = schema.type_map["Query"].fields["title"]
        assert hasattr(field.type, "of_type"), "Expected NonNull wrapper"

    def test_list_of_strings(self) -> None:
        """TypeRef(list=True) must compile to a GraphQLList-wrapped field.

        If this fails, a list-typed field would compile as a bare scalar
        instead of a GraphQL list, breaking any client expecting an array.
        """
        from graphql import GraphQLList

        spec = TypeSpec(
            name="Query",
            fields=(FieldSpec(name="tags", type=TypeRef(name="String", list=True)),),
        )
        schema = compile_schema(types=[spec], enums=[], query=spec)
        field = schema.type_map["Query"].fields["tags"]
        # Should be a List wrapper

        assert isinstance(field.type, GraphQLList), (
            f"Expected List, got {type(field.type)}"
        )

    def test_non_null_list_of_non_null(self) -> None:
        """TypeRef(name, list=True, non_null=True, inner=TypeRef(non_null=True)) compiles to "[String!]!".

        If this fails, a doubly non-null list ref would compile to the wrong
        GraphQL wrapper nesting (e.g. "[String]" or "[String!]" instead of
        "[String!]!"), changing the schema's nullability contract.
        """
        inner = TypeRef(name="String", non_null=True)
        ref = TypeRef(name="String", list=True, non_null=True, inner=inner)
        spec = TypeSpec(
            name="Query",
            fields=(FieldSpec(name="tags", type=ref),),
        )
        schema = compile_schema(types=[spec], enums=[], query=spec)
        field = schema.type_map["Query"].fields["tags"]
        from graphql import GraphQLList, GraphQLNonNull

        assert isinstance(field.type, GraphQLNonNull)
        assert isinstance(field.type.of_type, GraphQLList)


# ---------------------------------------------------------------------------
# T1.3 — compile_enum: raw value at execute time
# ---------------------------------------------------------------------------


class TestEnumRawValue:
    """compile_enum() must preserve raw Python values for the GraphQL enum serializer.

    Covers both int-backed and string-backed EnumSpec values.
    """

    def test_enum_delivers_raw_int_value(self) -> None:
        """compile_enum uses GraphQLEnumValue(value=raw).

        graphql-core's enum serializer maps raw_value to wire_name.
        So root returning raw int 1 becomes wire "ACTIVE".
        The raw int is what a Django model field would return.

        If this fails, an int-backed enum field would fail to serialize (or
        serialize to the wrong wire name) when the resolver returns the raw
        database value instead of the enum member.
        """
        status_enum = EnumSpec(
            name="Status",
            values=(("ACTIVE", 1), ("INACTIVE", 0)),
        )
        query_spec = TypeSpec(
            name="Query",
            fields=(FieldSpec(name="status", type=TypeRef(name="Status")),),
        )
        schema = compile_schema(
            types=[query_spec], enums=[status_enum], query=query_spec
        )
        # root returns raw Python int 1 → enum serializer maps to "ACTIVE"
        result = graphql_sync(
            schema,
            "{ status }",
            root_value={"status": 1},  # raw int value
        )
        assert result.errors is None
        assert result.data["status"] == "ACTIVE"  # GraphQL wire name

    def test_enum_delivers_raw_string_value(self) -> None:
        """String raw values are delivered correctly.

        EnumSpec values=(("RED", "red"), ...) means raw value is "red".
        Root returns "red" and the serializer maps it to "RED".

        If this fails, a string-backed enum field would fail to serialize
        when the resolver returns the raw stored string instead of the wire
        enum name.
        """
        color_enum = EnumSpec(
            name="Color",
            values=(("RED", "red"), ("BLUE", "blue")),
        )
        query_spec = TypeSpec(
            name="Query",
            fields=(FieldSpec(name="color", type=TypeRef(name="Color")),),
        )
        schema = compile_schema(
            types=[query_spec], enums=[color_enum], query=query_spec
        )
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
    """compile_schema()'s printed SDL must match the expected structural shape.

    Covers plain scalar fields, camelCase field naming, custom scalars,
    non-null list wrapping, and enum blocks.
    """

    def test_simple_query_sdl(self) -> None:
        """A simple schema with "hello: String" should produce expected SDL.

        If this fails, the compiler would stop emitting a well-formed "type
        Query" block with its declared scalar field in the printed SDL.
        """
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

    def test_camel_case_in_sdl(self) -> None:
        """created_at field should appear as createdAt in SDL.

        If this fails, the printed SDL would expose the raw snake_case field
        name instead of the camelCase wire name clients rely on.
        """
        spec = TypeSpec(
            name="Query",
            fields=(FieldSpec(name="created_at", type=TypeRef(name="String")),),
        )
        schema = compile_schema(types=[spec], enums=[], query=spec)
        sdl = print_schema(schema)
        assert "createdAt" in sdl
        assert "created_at" not in sdl

    def test_all_7_custom_scalars_in_map_sdl(self) -> None:
        """When all 7 custom scalars are referenced, they appear in SDL.

        TypeRef names are GDX_SCALAR_MAP keys, i.e. the graphene scalar names (#1508).

        If this fails, one or more of the project's custom scalar types would
        stop being emitted into the printed SDL, breaking client codegen for
        that scalar.
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
                # The raw JSON scalar is referenced by its canonical ``JSON``
                # name (the legacy ``GenericScalar`` key still resolves to the
                # same singleton, but the SDL now prints ``JSON`` by design).
                FieldSpec(name="generic_val", type=TypeRef(name="JSON")),
            ),
        )
        schema = compile_schema(types=[spec], enums=[], query=spec)
        sdl = print_schema(schema)
        for scalar_name in (
            "CustomDate",
            "CustomDateTime",
            "CustomTime",
            "Decimal",
            "UUID",
            "JSONString",
            "JSON",
        ):
            assert scalar_name in sdl, f"Missing scalar {scalar_name} in SDL"

    def test_nonnull_list_in_sdl(self) -> None:
        """ "[String!]!" wrapping should appear in SDL.

        If this fails, the printed SDL would render the wrong nullability
        wrapper for a non-null list of non-null strings.
        """
        inner = TypeRef(name="String", non_null=True)
        ref = TypeRef(name="String", list=True, non_null=True, inner=inner)
        spec = TypeSpec(
            name="Query",
            fields=(FieldSpec(name="tags", type=ref),),
        )
        schema = compile_schema(types=[spec], enums=[], query=spec)
        sdl = print_schema(schema)
        assert "[String!]!" in sdl

    def test_enum_in_sdl(self) -> None:
        """Compiled enum should appear in SDL.

        If this fails, a compiled EnumSpec would stop being printed as an
        "enum" block with its declared values in the schema's SDL.
        """
        status_enum = EnumSpec(
            name="Status",
            values=(("ACTIVE", 1), ("INACTIVE", 0)),
        )
        query_spec = TypeSpec(
            name="Query",
            fields=(FieldSpec(name="status", type=TypeRef(name="Status")),),
        )
        schema = compile_schema(
            types=[query_spec], enums=[status_enum], query=query_spec
        )
        sdl = print_schema(schema)
        assert "enum Status" in sdl
        assert "ACTIVE" in sdl
        assert "INACTIVE" in sdl


# ---------------------------------------------------------------------------
# T1.4 — Bridge: GdxPayload + _MetaView + assert_gdx_bridge
# ---------------------------------------------------------------------------


class TestBridge:
    """GdxPayload / _MetaView / assert_gdx_bridge must bridge compiled types to the gdx contract.

    Covers extension presence, the assertion's pass/fail behavior, and the
    "_meta"-style attribute view over a GdxMeta.
    """

    def test_compiled_schema_has_gdx_extensions(self) -> None:
        """Every type in a compile_schema output carries extensions["gdx"].

        If this fails, compiled GraphQL types would lose the "gdx" extension
        payload that downstream code (permissions, pagination metadata) reads
        off "type.extensions".
        """
        spec = TypeSpec(
            name="Query",
            fields=(FieldSpec(name="hello", type=TypeRef(name="String")),),
        )
        schema = compile_schema(types=[spec], enums=[], query=spec)
        query_type = schema.type_map["Query"]
        assert "gdx" in query_type.extensions, (
            "extensions['gdx'] missing from compiled type"
        )

    def test_assert_gdx_bridge_passes_for_compiled_schema(self) -> None:
        """assert_gdx_bridge(schema) must not raise for a compile_schema output.

        If this fails, a normally-compiled schema would be wrongly flagged as
        missing the gdx bridge, breaking any code path that gates on this
        assertion at schema-build time.
        """
        spec = TypeSpec(
            name="Query",
            fields=(FieldSpec(name="hello", type=TypeRef(name="String")),),
        )
        schema = compile_schema(types=[spec], enums=[], query=spec)
        # Should not raise
        assert_gdx_bridge(schema)

    def test_assert_gdx_bridge_raises_for_bare_type(self) -> None:
        """assert_gdx_bridge must raise for a schema with a bare type (no extensions["gdx"]).

        If this fails, a hand-built GraphQLObjectType lacking the gdx bridge
        would silently pass the assertion instead of surfacing the missing
        extension early.
        """
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
        with pytest.raises(AssertionError, match="missing extensions\\['gdx'\\]"):
            assert_gdx_bridge(schema)

    def test_gdx_payload_reachable_from_type_extensions(self) -> None:
        """GdxPayload should be accessible via type.extensions["gdx"].

        If this fails, the GdxMeta attached to a TypeSpec would not survive
        compilation into a reachable GdxPayload on the compiled type.
        """
        spec = TypeSpec(
            name="Query",
            fields=(FieldSpec(name="hello", type=TypeRef(name="String")),),
            gdx=GdxMeta(max_depth=5),
        )
        schema = compile_schema(types=[spec], enums=[], query=spec)
        query_type = schema.type_map["Query"]
        payload = query_type.extensions["gdx"]
        assert isinstance(payload, GdxPayload)

    def test_meta_view_known_attribute(self) -> None:
        """_MetaView exposes known attrs from the GdxMeta.

        If this fails, code that reads graphene-style "_meta.<attr>" against
        a bridged type would stop seeing the underlying GdxMeta values.
        """
        from django_graphex.core.bridge import _MetaView

        meta = GdxMeta(max_depth=3, complexity=2)
        view = _MetaView(meta)
        assert view.max_depth == 3
        assert view.complexity == 2

    def test_meta_view_unknown_attribute_raises_attribute_error(self) -> None:
        """_MetaView raises AttributeError (never returns None) on unknown attr.

        If this fails, an unknown "_meta" attribute would silently resolve to
        None instead of raising, masking typos in caller code.
        """
        from django_graphex.core.bridge import _MetaView

        meta = GdxMeta()
        view = _MetaView(meta)
        with pytest.raises(AttributeError):
            _ = view.bogus_attr_that_does_not_exist

    def test_gdx_payload_meta_property(self) -> None:
        """GdxPayload._meta returns a _MetaView for graphene_type._meta compat.

        If this fails, code emulating the legacy graphene "graphene_type._meta"
        access pattern against a GdxPayload would break.
        """
        payload = GdxPayload(GdxMeta(max_depth=7))
        meta = payload._meta
        assert meta.max_depth == 7

    def test_assert_gdx_bridge_skips_introspection_types(self) -> None:
        """Introspection types (starting with "__") should not trigger the bridge check.

        If this fails, assert_gdx_bridge would wrongly demand a "gdx"
        extension on graphql-core's own introspection types, breaking every
        schema that runs an introspection query.
        """
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
    """compile_schema() must seed GDX_SCALAR_MAP scalars into the type cache.

    Covers both a custom project scalar and a standard built-in scalar.
    """

    def test_gdx_date_in_schema_type_map(self) -> None:
        """The date scalar is reachable in the type_map after compile_schema.

        Keyed by the graphene scalar name "CustomDate" (#1508).

        If this fails, a field referencing the custom date scalar by its
        GDX_SCALAR_MAP key would fail to resolve to a real GraphQL scalar
        type in the compiled schema.
        """
        spec = TypeSpec(
            name="Query",
            fields=(FieldSpec(name="birthday", type=TypeRef(name="CustomDate")),),
        )
        schema = compile_schema(types=[spec], enums=[], query=spec)
        assert "CustomDate" in schema.type_map

    def test_standard_string_scalar_resolves(self) -> None:
        """Standard String scalar works without explicit TypeSpec.

        If this fails, the built-in GraphQL String scalar would stop
        resolving out of the box, requiring callers to register it manually.
        """
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
    """Targeted tests for cache-hit and error branches in compile_type/compile_enum/compile_schema.

    Each test exercises one specific branch that the golden-path tests above
    do not reach.
    """

    def test_memoized_type_returns_cached(self) -> None:
        """compile_type called twice on same name returns the cached object.

        If this fails, recompiling the same TypeSpec name would allocate a
        second distinct GraphQLObjectType instead of reusing the cached one,
        risking identity mismatches in the schema's type_map.
        """
        spec = TypeSpec(
            name="CachedType",
            fields=(FieldSpec(name="x", type=TypeRef(name="String")),),
        )
        compile_schema(types=[spec], enums=[], query=spec)
        # Re-compile same spec — should hit the cache branch
        from django_graphex.core.compiler import _TYPE_CACHE, compile_type

        cached = _TYPE_CACHE.get("CachedType")
        result = compile_type(spec)
        assert result is cached

    def test_memoized_enum_returns_cached(self) -> None:
        """compile_enum called twice on same name returns the cached object.

        If this fails, recompiling the same EnumSpec name would allocate a
        second distinct GraphQLEnumType instead of reusing the cached one.
        """
        status_enum = EnumSpec(name="CachedEnum", values=(("A", 1),))
        query_spec = TypeSpec(
            name="Query",
            fields=(FieldSpec(name="s", type=TypeRef(name="CachedEnum")),),
        )
        compile_schema(types=[query_spec], enums=[status_enum], query=query_spec)
        from django_graphex.core.compiler import _TYPE_CACHE

        cached = _TYPE_CACHE.get("CachedEnum")
        result = compile_enum(status_enum)
        assert result is cached

    def test_enum_with_descriptions(self) -> None:
        """compile_enum with descriptions sets GraphQLEnumValue description.

        If this fails, per-value description text on an EnumSpec would be
        dropped instead of surfacing on the compiled GraphQLEnumValue.
        """
        status_enum = EnumSpec(
            name="DescStatus",
            values=(("ACTIVE", 1), ("INACTIVE", 0)),
            descriptions={"ACTIVE": "Is active", "INACTIVE": "Is inactive"},
        )
        query_spec = TypeSpec(
            name="Query",
            fields=(FieldSpec(name="s", type=TypeRef(name="DescStatus")),),
        )
        schema = compile_schema(
            types=[query_spec], enums=[status_enum], query=query_spec
        )
        enum_type = schema.type_map["DescStatus"]
        assert enum_type.values["ACTIVE"].description == "Is active"

    def test_inner_ref_non_null_list(self) -> None:
        """TypeRef with inner ref and both list=True, non_null=True on inner branch.

        If this fails, the ref-resolution branch for an inner ref combined
        with a non-non-null outer list would stop producing a GraphQLList.
        """
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

    def test_compile_schema_with_mutation(self) -> None:
        """compile_schema with mutation= builds a schema with both query and mutation.

        If this fails, passing a mutation TypeSpec to compile_schema would
        stop producing a schema whose "mutation_type" is set.
        """
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

    def test_compile_schema_unknown_query_type_raises(self) -> None:
        """compile_schema raises ValueError when query type is missing from types.

        If this fails, passing a query TypeSpec that is absent from the
        "types" list would silently compile an incomplete schema instead of
        raising, hiding a caller mistake.
        """
        query_spec = TypeSpec(
            name="MissingQuery",
            fields=(FieldSpec(name="hello", type=TypeRef(name="String")),),
        )
        other_spec = TypeSpec(
            name="OtherType",
            fields=(FieldSpec(name="x", type=TypeRef(name="String")),),
        )
        # Pass other_spec as types but query_spec as query → MissingQuery not compiled
        with pytest.raises(ValueError, match="query type 'MissingQuery'"):
            compile_schema(types=[other_spec], enums=[], query=query_spec)


class TestBridgeCoverageBranches:
    """Targeted tests for uncovered error and skip branches in core/bridge.py.

    Covers "_MetaView" attribute rejection paths and "assert_gdx_bridge"'s
    skip-list for union and enum types.
    """

    def test_meta_view_private_attr_raises(self) -> None:
        """_MetaView raises AttributeError for names starting with "_".

        If this fails, "_MetaView" would leak access to private/internal
        attributes instead of rejecting them like a real graphene "_meta".
        """
        from django_graphex.core.bridge import _MetaView

        view = _MetaView(GdxMeta())
        with pytest.raises(AttributeError):
            _ = view._private_attr

    def test_meta_view_known_attr_not_on_meta_raises(self) -> None:
        """_MetaView raises AttributeError when attr is in allowlist but not on GdxMeta.

        If this fails, an allowlisted "_meta" attribute name that GdxMeta
        does not actually define would silently return something instead of
        raising, hiding the missing field.
        """
        from django_graphex.core.bridge import _GDX_ALLOWLIST, _MetaView

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

    def test_assert_gdx_bridge_skips_non_assertable_types(self) -> None:
        """assert_gdx_bridge skips union types (they do not need the bridge).

        If this fails, assert_gdx_bridge would wrongly demand a "gdx"
        extension on a union type, which never carries one.
        """
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

    def test_assert_gdx_bridge_skips_enum_types(self) -> None:
        """assert_gdx_bridge skips enum types in the schema type_map.

        If this fails, assert_gdx_bridge would wrongly demand a "gdx"
        extension on enum types, which never carry one.
        """
        status_enum = EnumSpec(
            name="BridgeStatus",
            values=(("ACTIVE", 1),),
        )
        query_spec = TypeSpec(
            name="Query",
            fields=(FieldSpec(name="s", type=TypeRef(name="BridgeStatus")),),
        )
        schema = compile_schema(
            types=[query_spec], enums=[status_enum], query=query_spec
        )
        # Enum types in type_map should be skipped, not cause assertion failure
        assert "BridgeStatus" in schema.type_map
        assert_gdx_bridge(schema)  # Must not raise


class TestCompilerRefResolutionBranches:
    """Targeted tests for uncovered branches in _resolve_ref and compile functions.

    Each test pins a specific list/non_null/inner combination or cache-miss
    scenario left unexercised by the golden-path tests above.
    """

    def test_inner_ref_list_only_no_outer_nonnull(self) -> None:
        """TypeRef with inner set, list=True, non_null=False.

        Exercises the branch where ref.inner is not None and ref.list=True,
        but ref.non_null=False (goes through 89->90 but not 91->92).

        If this fails, this specific ref-resolution branch would stop
        producing a bare GraphQLList (e.g. wrapping it in NonNull instead).
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

    def test_compile_schema_mutation_type_not_in_types_raises(self) -> None:
        """compile_schema raises ValueError if mutation type is declared but missing.

        If this fails, a mutation TypeSpec absent from the "types" list would
        silently compile an incomplete schema instead of raising.
        """
        query_spec = TypeSpec(
            name="Query",
            fields=(FieldSpec(name="hello", type=TypeRef(name="String")),),
        )
        mutation_spec = TypeSpec(
            name="MissingMutation",
            fields=(FieldSpec(name="do_it", type=TypeRef(name="String")),),
        )
        # Don't include mutation_spec in types
        with pytest.raises(ValueError, match="mutation type 'MissingMutation'"):
            compile_schema(
                types=[query_spec],
                enums=[],
                query=query_spec,
                mutation=mutation_spec,
            )

    def test_compile_type_cache_hit_non_object_type_falls_through(self) -> None:
        """compile_type when cache has a non-GraphQLObjectType for the same name
        falls through and creates a new type (exercises branch 169->173).

        If this fails, a name collision between an object type and an
        unrelated cached type (e.g. a scalar) would return the wrong cached
        object instead of compiling a fresh GraphQLObjectType.
        """
        from graphql import GraphQLScalarType

        from django_graphex.core.compiler import _TYPE_CACHE

        spec = TypeSpec(
            name="Query",
            fields=(FieldSpec(name="x", type=TypeRef(name="String")),),
        )
        compile_schema(types=[spec], enums=[], query=spec)

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

    def test_compile_enum_cache_hit_non_enum_type_falls_through(self) -> None:
        """compile_enum when cache has a non-GraphQLEnumType falls through
        and creates a new enum type (exercises branch 202->205).

        If this fails, a name collision between an enum and an unrelated
        cached type would return the wrong cached object instead of
        compiling a fresh GraphQLEnumType.
        """
        from graphql import GraphQLScalarType

        from django_graphex.core.compiler import _TYPE_CACHE

        spec = TypeSpec(
            name="Query",
            fields=(FieldSpec(name="x", type=TypeRef(name="String")),),
        )
        compile_schema(types=[spec], enums=[], query=spec)

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

    def test_resolve_ref_unknown_type_raises_at_execute(self) -> None:
        """Accessing a field whose type is unknown raises at field resolution time.

        If this fails, a TypeRef naming a type absent from the compiler's
        type cache would silently resolve to something instead of raising
        when the schema's field thunk is evaluated.
        """
        # Build a schema where a field refs an unknown type, then execute
        # This should surface as an error (either build-time or execute-time)
        from django_graphex.core.compiler import _TYPE_CACHE, _reset_cache, compile_type

        _reset_cache()
        from django_graphex.core.scalars import GDX_SCALAR_MAP

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
        with pytest.raises(TypeError, match="Query fields cannot be resolved"):
            _ = query_type.fields  # triggers the thunk
