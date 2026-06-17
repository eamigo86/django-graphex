"""S-ROOTS-c RED — migrate ``ok`` / ``errors`` to native ``field()`` descriptors.

S-ROOTS-c converts the two HAND-DECLARED payload descriptors on
``DjangoModelType`` (types.py) and ``DjangoModelMutation`` (mutation.py) off
graphene and onto the native ``field()`` currency:

    ok     = Boolean(...)        ->  field(GraphQLBoolean, ...)
    errors = List(ErrorType)     ->  field(NativeList(ErrorType), ...)

``ErrorType`` is a NATIVE plain ``ObjectType`` (S-ROOTS-b), so its compiled
graphql-core type does not exist until ``_compile_plain_object_type`` runs. A
graphql-core ``GraphQLList(ErrorType)`` CANNOT be built eagerly (graphql-core
rejects a non-``GraphQLType`` ``of_type`` at construction time), so the list is
expressed via the native ``NativeList`` wrapper (descriptors.py) which the
compiler resolves LAZILY through ``_compile_wrapped_field_type``.

PARAMOUNT GUARD — the S6c silent-null mutation-payload regression class:
the native container ``__init__`` (base.py) stashes payload kwargs whose key is
in ``cls._meta.fields``. If ``ok`` / ``errors`` are NOT in ``_meta.fields`` the
wire output silently becomes ``null`` (no crash, data loss). These tests prove,
at the WIRE level, that a real mutation returns a non-null ``ok`` AND a queryable
``errors`` (both the success path and the populated-error path), and that the
SDL is byte-identical to the graphene original (``ok: Boolean``,
``errors: [ErrorType]``).

Run: GDX_BACKEND=native .venv/bin/python -m pytest \
    tests/native/test_s_roots_c_ok_errors_native.py -q -o addopts=""
"""
from __future__ import annotations

import pytest

pytestmark = pytest.mark.native_only


# ---------------------------------------------------------------------------
# descriptors.py — NativeList currency for a lazily-resolved native object list
# ---------------------------------------------------------------------------


def test_native_list_exposes_of_type() -> None:
    """``NativeList(inner)`` exposes ``.of_type`` (the graphql-core wrapper read-contract).

    ``_compile_wrapped_field_type`` recurses through ``.of_type`` exactly as it
    does for graphene ``List`` / graphql-core ``GraphQLList`` — so the native
    wrapper must mirror that single read attribute.
    """
    from django_graphex.errors import ErrorType
    from django_graphex.native.descriptors import NativeList

    wrapper = NativeList(ErrorType)
    assert wrapper.of_type is ErrorType


def test_native_list_does_not_eagerly_build_graphql_list() -> None:
    """``NativeList(ErrorType)`` must NOT eagerly construct a ``GraphQLList``.

    graphql-core's ``GraphQLList.__init__`` raises ``TypeError`` for a
    non-``GraphQLType`` ``of_type``; ``ErrorType`` is a Python class that compiles
    later, so building the wrapper must be inert (lazy) — this is the whole reason
    ``NativeList`` exists instead of ``field(GraphQLList(ErrorType))``.
    """
    from graphql import GraphQLList

    from django_graphex.errors import ErrorType
    from django_graphex.native.descriptors import NativeList

    # Constructing the native wrapper is inert and never raises.
    wrapper = NativeList(ErrorType)
    # graphql-core would have rejected the same eager construction.
    with pytest.raises(TypeError):
        GraphQLList(ErrorType)
    assert wrapper.of_type is ErrorType


def test_field_with_native_list_errortype_compiles_to_list_of_errortype() -> None:
    """``field(NativeList(ErrorType))`` compiles to ``[ErrorType]`` (object arm, lazy).

    Routes through ``compile_declared_field`` -> ``_compile_wrapped_field_type``,
    which recurses the ``NativeList`` and compiles the inner ``ErrorType`` via
    ``_compile_plain_object_type`` (object arm). The element must be the
    ``GraphQLObjectType`` named ``ErrorType`` carrying ``field`` + ``messages`` —
    it must NOT fall into the scalar arm (KeyError) or vanish.
    """
    from graphql import GraphQLList, GraphQLObjectType

    from django_graphex.errors import ErrorType
    from django_graphex.native.descriptors import NativeList, field
    from django_graphex.native.schema_compiler import compile_declared_field

    errors_field = field(NativeList(ErrorType), description="Errors list for the field")

    class _RootsCHolder:
        pass

    compiled = compile_declared_field(_RootsCHolder, "errors", errors_field)
    assert isinstance(compiled.type, GraphQLList), "errors lost its List wrapper"
    element = compiled.type.of_type
    assert isinstance(element, GraphQLObjectType), (
        "errors element mis-routed: not a GraphQLObjectType (scalar arm / dropped)."
    )
    assert element.name == "ErrorType"
    assert "field" in element.fields
    assert "messages" in element.fields


# ---------------------------------------------------------------------------
# DjangoModelType / DjangoModelMutation — ok/errors are native, NOT graphene
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "import_path",
    ["django_graphex.types", "django_graphex.mutation"],
)
def test_ok_errors_descriptors_are_native_fields(import_path: str) -> None:
    """``ok`` / ``errors`` class-body descriptors are native ``NativeField`` instances.

    Before S-ROOTS-c they were graphene ``Boolean()`` / ``List(ErrorType)``. The
    migration replaces them with ``field(...)`` so the descriptor currency is the
    native one (graphene-free declaration site).
    """
    import importlib

    from django_graphex.native.descriptors import NativeField

    module = importlib.import_module(import_path)
    cls_name = "DjangoModelType" if "types" in import_path else "DjangoModelMutation"
    cls = getattr(module, cls_name)

    ok_desc = vars(cls)["ok"]
    errors_desc = vars(cls)["errors"]
    assert isinstance(ok_desc, NativeField), f"{cls_name}.ok is not a NativeField"
    assert isinstance(errors_desc, NativeField), f"{cls_name}.errors is not a NativeField"


@pytest.mark.django_db
def test_modeltype_ok_errors_in_meta_fields() -> None:
    """``ok`` / ``errors`` land in ``_meta.fields`` — the S6c stash mechanism.

    The native container ``__init__`` stashes a payload kwarg only when its key is
    in ``cls._meta.fields``. If ``ok`` / ``errors`` are not in ``_meta.fields`` the
    wire payload silently nulls them (the S6c bug). This asserts the EXACT
    mechanism that protects against the silent-null regression.
    """
    from django_graphex.types import DjangoModelType
    from tests.models import Category

    class _RootsCCatModelType(DjangoModelType):
        class Meta:
            model = Category

    field_names = set(_RootsCCatModelType._meta.fields)
    assert "ok" in field_names, sorted(field_names)
    assert "errors" in field_names, sorted(field_names)


@pytest.mark.django_db
def test_mutation_ok_errors_in_meta_fields() -> None:
    """``ok`` / ``errors`` land in ``DjangoModelMutation._meta.fields`` (S6c stash)."""
    from django_graphex.mutation import DjangoModelMutation
    from tests.models import Category

    class _RootsCCatMutation(DjangoModelMutation):
        class Meta:
            model = Category

    field_names = set(_RootsCCatMutation._meta.fields)
    assert "ok" in field_names, sorted(field_names)
    assert "errors" in field_names, sorted(field_names)


# ---------------------------------------------------------------------------
# SDL byte-parity — ok: Boolean, errors: [ErrorType]
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_modeltype_payload_sdl_byte_identical_to_graphene() -> None:
    """The migrated payload SDL is byte-identical to the graphene original.

    The graphene descriptors produced ``ok: Boolean`` and ``errors: [ErrorType]``
    (both nullable, list-of-nullable). The native ``field()`` migration MUST match
    those exact nullability / wrapper bytes.
    """
    from graphql import GraphQLObjectType, print_type

    from django_graphex.native.schema_compiler import compile_declared_field
    from django_graphex.types import DjangoModelType
    from tests.models import Category

    class _RootsCSdlModelType(DjangoModelType):
        class Meta:
            model = Category

    ok_field = compile_declared_field(
        _RootsCSdlModelType, "ok", _RootsCSdlModelType._meta.fields["ok"]
    )
    errors_field = compile_declared_field(
        _RootsCSdlModelType, "errors", _RootsCSdlModelType._meta.fields["errors"]
    )
    holder = GraphQLObjectType(
        name="Holder",
        fields={"ok": ok_field, "errors": errors_field},
    )
    sdl = print_type(holder)
    # Byte-identical wire shape (nullability + list wrapper).
    assert "ok: Boolean" in sdl, sdl
    assert "errors: [ErrorType]" in sdl, sdl
    # NOT non-null, NOT list-of-non-null (would be a wire-contract change).
    assert "ok: Boolean!" not in sdl, sdl
    assert "errors: [ErrorType!]" not in sdl, sdl
    assert "errors: [ErrorType]!" not in sdl, sdl


# ---------------------------------------------------------------------------
# WIRE-LEVEL silent-null guard — the S6c regression class (PARAMOUNT)
# ---------------------------------------------------------------------------


def _build_post_modeltype_schema():
    """Build a native DjangoGraphQLSchema with a DjangoModelType Post mutation."""
    from graphql import GraphQLString

    from django_graphex import DjangoObjectType, ObjectType, field
    from django_graphex.native.registry_compiler import compile_all_outputs
    from django_graphex.schema import DjangoGraphQLSchema
    from django_graphex.types import DjangoModelType
    from tests.models import Author, Post, Tag

    class _RootsCAuthor(DjangoObjectType):
        class Meta:
            model = Author

    class _RootsCTag(DjangoObjectType):
        class Meta:
            model = Tag

    class _RootsCPost(DjangoObjectType):
        class Meta:
            model = Post

    class _RootsCPostType(DjangoModelType):
        class Meta:
            model = Post

    compile_all_outputs()

    class _RootsCQuery(ObjectType):
        hello = field(GraphQLString)

    class _RootsCMutation(ObjectType):
        post_create, post_delete, post_update = _RootsCPostType.MutationFields()

    schema = DjangoGraphQLSchema(query=_RootsCQuery, mutation=_RootsCMutation)
    return schema, _RootsCPostType


@pytest.mark.django_db
def test_wire_mutation_returns_non_null_ok_and_queryable_errors() -> None:
    """SUCCESS PATH: a real mutation returns ``ok == True`` (non-null) over the wire.

    This is the S6c silent-null guard: it asserts the WIRE PAYLOAD object has a
    non-null ``ok`` — NOT merely that construction succeeded. If ``ok`` / ``errors``
    were dropped from ``_meta.fields`` (the S6c mechanism) the resolved payload
    would silently null ``ok``, and ``data["ok"] is True`` would FAIL.
    """
    from django.test import RequestFactory
    from graphql import graphql_sync

    from tests.models import Author, Post

    schema, _ = _build_post_modeltype_schema()
    author = Author.objects.create(name="Ada")
    assert Post.objects.count() == 0

    document = (
        'mutation { postCreate(newPost: {title: "X", body: "y", author: %d}) '
        "{ post { title } ok errors { field messages } } }" % author.id
    )
    request = RequestFactory().post("/graphql/", content_type="application/json")
    result = graphql_sync(schema.graphql_schema, document, context_value=request)

    assert result.errors is None, f"native create raised: {result.errors!r}"
    data = result.data["postCreate"]
    # The payload object itself is non-null on the wire (silent-null would null it).
    assert data is not None, "mutation payload silently nulled (S6c regression)"
    # ok is non-null and True (NOT silently nulled).
    assert data["ok"] is True, data
    # errors is queryable (success path -> null/empty, but the FIELD resolved).
    assert "errors" in data
    assert Post.objects.filter(title="X").exists()


@pytest.mark.django_db
def test_wire_mutation_populates_errors_on_lookup_failure() -> None:
    """ERROR PATH: a failing mutation returns ``ok == False`` AND a POPULATED errors list.

    Proves the ``errors`` field is not just present but carries the structured
    ``{field, messages}`` payload over the wire (the populated-error case the S6c
    bug would silently null). Updating a NON-EXISTENT pk passes schema-level input
    coercion but fails the object lookup -> ``get_errors(not_found_error(...))``,
    the canonical populated-``errors`` payload path.
    """
    from django.test import RequestFactory
    from graphql import graphql_sync

    from tests.models import Author, Post

    schema, _ = _build_post_modeltype_schema()
    author = Author.objects.create(name="Ada")
    assert Post.objects.count() == 0

    # A fully-shaped, schema-valid update input for a pk that does NOT exist.
    # Coercion succeeds; the lookup fails -> populated {field, messages} errors.
    document = (
        'mutation { postUpdate(newPost: {id: 999999, title: "X", body: "y", '
        "author: %d}) { post { title } ok errors { field messages } } }" % author.id
    )
    request = RequestFactory().post("/graphql/", content_type="application/json")
    result = graphql_sync(schema.graphql_schema, document, context_value=request)

    assert result.errors is None, f"native update raised: {result.errors!r}"
    data = result.data["postUpdate"]
    assert data is not None, "mutation payload silently nulled (S6c regression)"
    # ok is non-null and False (NOT silently nulled).
    assert data["ok"] is False, data
    # errors is a NON-NULL, NON-EMPTY list carrying {field, messages}.
    assert data["errors"], f"errors silently nulled/empty on failure path: {data}"
    first = data["errors"][0]
    assert "field" in first and "messages" in first, first
    assert isinstance(first["messages"], list) and first["messages"], first
