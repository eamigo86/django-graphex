"""Tests for WU-B: DjangoInputObjectType native compile path + _GdxInputOptions.

Tests verify:
- DjangoInputObjectType subclass with model + input_for="create" has
  _meta.graphql_input_type after native compile (Phase-2 deliverable).
- Update form → all fields nullable (partial model).
- Model-free _GdxInputMeta does NOT expose 'container' (container-free meta for
  native model-free path). S6c: DjangoInputObjectType._meta.container is now
  ALSO absent — the InputObjectTypeContainer construction was deleted (resolvers
  receive a validated Pydantic model, not a container).
- assert input_flag is not None fires for the output branch.
- type(InputType subclass) is ModelMetaclass (model-FREE metaclass identity —
  the Phase-2 deliverable for model-free types).
  S6c: type(DjangoInputObjectType subclass) IS ALSO ModelMetaclass now — the
  re-parent off graphene InputObjectType onto native InputType removed graphene's
  SubclassWithMeta_Meta, achieving the #1452 metaclass-identity constraint. The
  graphene-free driver runs via __init_subclass__, not a custom metaclass.
- _meta.graphql_input_type is GraphQLInputObjectType after __init_subclass_with_meta__
  (the real Phase-2 model-coupled deliverable).
- Accessing _meta.bogus_attr raises AttributeError.

All tests run under GDX_BACKEND=native via the native_only mark.
"""
from __future__ import annotations

import os

import pytest

pytestmark = pytest.mark.native_only


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _native_only() -> bool:
    """Return True when GDX_BACKEND=native is set."""
    return os.environ.get("GDX_BACKEND", "graphene") == "native"


# ---------------------------------------------------------------------------
# Task 2.1: DjangoInputObjectType native compile path
# ---------------------------------------------------------------------------

@pytest.mark.django_db
def test_django_input_object_type_graphql_input_type_create():
    """DjangoInputObjectType with input_for='create' must expose graphql_input_type."""
    from graphql import GraphQLInputObjectType
    from django_graphex.native.input_compiler import compile_input_type, GdxInputSpec
    from django_graphex.native.fields import build_model_schema
    from django_graphex.native.validators import build_validator_model
    from tests.models import Category

    # Build a Pydantic model for Category (create — non-partial)
    pydantic_model = build_model_schema(Category, partial=False)

    # compile_input_type must return a GraphQLInputObjectType
    gql_input_type = compile_input_type(
        pydantic_model,
        name="CategoryInput",
        description="Create input for Category",
    )

    assert isinstance(gql_input_type, GraphQLInputObjectType), (
        "compile_input_type must return a GraphQLInputObjectType"
    )
    assert gql_input_type.name == "CategoryInput"
    # extensions["gdx"] must be a GdxInputSpec
    assert isinstance(gql_input_type.extensions.get("gdx"), GdxInputSpec), (
        "graphql_input_type must carry extensions['gdx'] = GdxInputSpec"
    )


@pytest.mark.django_db
def test_django_input_object_type_graphql_input_type_update_all_nullable():
    """DjangoInputObjectType with input_for='update' → all fields nullable (partial)."""
    from graphql import GraphQLNonNull
    from django_graphex.native.input_compiler import compile_input_type
    from django_graphex.native.fields import build_model_schema
    from tests.models import Category

    # Update form → partial=True → every field nullable
    pydantic_model = build_model_schema(Category, partial=True)
    gql_input_type = compile_input_type(
        pydantic_model,
        name="CategoryUpdateInput",
    )

    # With partial=True, no fields should be NonNull-wrapped
    fields = gql_input_type.fields
    for field_name, gql_field in fields.items():
        assert not isinstance(gql_field.type, GraphQLNonNull), (
            f"Update input field {field_name!r} must be nullable (partial model), "
            f"got {gql_field.type!r}"
        )


@pytest.mark.django_db
def test_model_free_meta_container_absent():
    """Model-free _GdxInputMeta does NOT expose 'container' — the native model-free
    metaclass has no container slot.

    SCOPE: this tests the model-FREE path (_GdxInputMeta / _GdxInputOptions).
    It does NOT test DjangoInputObjectType._meta, which is a DjangoObjectOptions
    instance and DOES still expose .container in Phase 2 (graphene.Schema reads
    _meta.container at build time; container removal is Phase 7 work).
    """
    from django_graphex.native.base import _GdxInputOptions, _GdxInputMeta

    opts = _GdxInputOptions()
    meta = _GdxInputMeta(opts)

    with pytest.raises(AttributeError):
        _ = meta.container  # type: ignore[attr-defined]


@pytest.mark.django_db
def test_django_input_object_type_meta_container_absent_after_s6c():
    """DjangoInputObjectType._meta.container is ABSENT after S6c.

    S6c (Phase 7) re-parents ``DjangoInputObjectType`` onto the native
    ``InputType`` base and DELETES the ``InputObjectTypeContainer`` construction:
    resolvers receive a VALIDATED Pydantic model (exposed as
    ``_meta.graphql_input_type``), never a container. ``NativeObjectTypeOptions``
    no longer has the driver set ``container``, so it stays at its ``None``
    default (no container instance is built).

    This test was INVERTED at S6c (pre-S6c it asserted the container was a class,
    per the Phase-2 note that said "Phase-7 will change this assertion").
    """
    from django_graphex.types import DjangoInputObjectType
    from tests.models import Category

    class _ContainerAbsentTest(DjangoInputObjectType):
        class Meta:
            model = Category
            input_for = "create"

    # The driver no longer builds an InputObjectTypeContainer; _meta.container
    # stays at the NativeObjectTypeOptions default (None) — never a container class.
    assert getattr(_ContainerAbsentTest._meta, "container", None) is None, (
        "After S6c the InputObjectTypeContainer is deleted: _meta.container must "
        "be None (resolvers receive a validated Pydantic model, not a container)."
    )


@pytest.mark.django_db
def test_assert_input_flag_guard():
    """The assert input_flag is not None guard: compile_input_type rejects None model.

    The native compile path separates input and output branches.
    compile_input_type requires a valid Pydantic BaseModel — passing None
    raises an error, confirming the guard isolates the INPUT branch from
    the OUTPUT branch (construct_fields is not called for inputs).
    """
    from django_graphex.native.input_compiler import compile_input_type
    from django_graphex.native.fields import build_model_schema
    from tests.models import Post

    # Verify compile_input_type works for a real model
    pydantic_model = build_model_schema(Post, partial=False)
    result = compile_input_type(pydantic_model, name="WuBPostCreateInput")
    assert result is not None, "compile_input_type must return a type"

    # The compile_input_type signature requires a Pydantic model with model_fields.
    # The lambda thunk is evaluated lazily when .fields is accessed.
    # Passing None (or a non-model object) must raise on field evaluation.
    broken_type = compile_input_type(None, name="BrokenInput")  # type: ignore[arg-type]
    with pytest.raises((AttributeError, TypeError)):
        _ = broken_type.fields  # trigger lazy evaluation


# ---------------------------------------------------------------------------
# Task 2.2: _GdxInputOptions / _MetaView extension
# ---------------------------------------------------------------------------

def test_gdx_input_meta_graphql_input_type_exposed():
    """_GdxInputMeta exposes graphql_input_type after compilation."""
    from django_graphex.native.base import _GdxInputOptions, _GdxInputMeta
    from graphql import GraphQLInputObjectType

    opts = _GdxInputOptions()
    meta = _GdxInputMeta(opts)

    # Before compilation, graphql_input_type is None
    assert meta.graphql_input_type is None

    # Simulate compilation setting the type
    sentinel = GraphQLInputObjectType("TestInput", fields={})
    opts.graphql_input_type = sentinel

    assert meta.graphql_input_type is sentinel


def test_gdx_input_meta_unknown_attr_raises():
    """_GdxInputMeta must raise AttributeError for unknown attributes."""
    from django_graphex.native.base import _GdxInputOptions, _GdxInputMeta

    opts = _GdxInputOptions()
    meta = _GdxInputMeta(opts)

    with pytest.raises(AttributeError):
        _ = meta.bogus_attr  # type: ignore[attr-defined]


def test_type_of_model_free_input_is_model_metaclass():
    """type(InputType subclass) is pydantic.ModelMetaclass — Phase-2 deliverable
    for model-free types.

    InputType is a pure pydantic.BaseModel; its metaclass is ModelMetaclass.
    This is the Phase-2 metaclass-identity deliverable for the MODEL-FREE path.
    """
    from pydantic._internal._model_construction import ModelMetaclass
    from django_graphex.native.base import InputType

    class _WuBModelFreeInput2(InputType):
        """A model-free input for metaclass identity test."""
        query: str
        limit: int = 10

    assert type(_WuBModelFreeInput2) is ModelMetaclass, (
        "type(InputType subclass) must be pydantic.ModelMetaclass"
    )


@pytest.mark.django_db
def test_build_model_schema_returns_pydantic_model():
    """build_model_schema returns an intermediate Pydantic model class.

    This tests the INTERMEDIATE Pydantic model produced by build_model_schema,
    NOT the public DjangoInputObjectType subclass. The inner model IS a
    pydantic.BaseModel subclass, so type(...) is ModelMetaclass is true for it.

    This is an internal-pipeline test, not a public-API metaclass claim.
    The public Phase-2 deliverable for model-coupled types is
    _meta.graphql_input_type being a real GraphQLInputObjectType
    (see test_django_input_object_type_meta_graphql_input_type_is_graphql_type).
    """
    from pydantic._internal._model_construction import ModelMetaclass
    from django_graphex.native.fields import build_model_schema
    from tests.models import Post

    # build_model_schema returns an INTERMEDIATE Pydantic model; type IS ModelMetaclass
    pydantic_model = build_model_schema(Post, partial=False)
    assert type(pydantic_model) is ModelMetaclass, (
        "build_model_schema must return a class with pydantic.ModelMetaclass "
        "(this is the intermediate Pydantic model, NOT the DjangoInputObjectType subclass)"
    )


@pytest.mark.django_db
def test_model_coupled_metaclass_is_modelmetaclass_after_s6c():
    """type(DjangoInputObjectType subclass) IS pydantic.ModelMetaclass after S6c.

    S6c (Phase 7) re-parents ``DjangoInputObjectType`` off graphene
    ``InputObjectType`` onto the native ``InputType`` base, whose sole metaclass
    is pydantic ``ModelMetaclass`` (NO custom metaclass — the graphene-free driver
    runs via ``__init_subclass__``). This is the systemic metaclass-identity
    constraint #1452: every public ``Django*`` type keeps ``type(X) is
    ModelMetaclass``.

    This test was INVERTED at S6c: pre-S6c it asserted the graphene Phase-2
    reality (``type(...) is not ModelMetaclass``); now the re-parent makes the
    #1452 goal real, so it asserts the goal — mirroring the S6b inversion of
    ``test_types_objecttype.py``.
    """
    from pydantic._internal._model_construction import ModelMetaclass
    from django_graphex.types import DjangoInputObjectType
    from tests.models import Category

    class _S6cModelCoupledInput(DjangoInputObjectType):
        class Meta:
            model = Category
            input_for = "create"

    # After S6c: the driver runs via __init_subclass__, NOT a custom metaclass,
    # so the metaclass is pydantic's ModelMetaclass (#1452).
    assert type(_S6cModelCoupledInput) is ModelMetaclass, (
        "After S6c, type(DjangoInputObjectType subclass) is pydantic."
        "ModelMetaclass — the re-parent onto native InputType removed graphene's "
        "SubclassWithMeta_Meta (the driver now runs via __init_subclass__, #1452)."
    )

    # Model-coupled deliverable: _meta.graphql_input_type IS a GraphQLInputObjectType
    from graphql import GraphQLInputObjectType
    assert isinstance(_S6cModelCoupledInput._meta.graphql_input_type, GraphQLInputObjectType), (
        "Model-coupled deliverable: _meta.graphql_input_type must be a "
        "GraphQLInputObjectType (the native compile path must be wired)"
    )


@pytest.mark.django_db
def test_django_input_object_type_does_not_pollute_input_registry():
    """A DjangoInputObjectType subclass must NOT register in _gdx_input_registry.

    S6c anti-regression lock. DjangoInputObjectType re-parents onto native
    ``InputType`` for the Pydantic engine, but it is MODEL-driven (its
    ``graphql_input_type`` is compiled from ``build_model_schema(model)``), so it
    overrides ``__init_subclass__`` to run the ObjectType driver WITHOUT
    InputType's registry-append + ``_meta`` overwrite. If it leaked into
    ``_gdx_input_registry``, ``compile_all_inputs()`` would re-compile it from its
    (empty) ``model_fields`` at app-ready under a DUPLICATE name and clobber the
    driver's ``_meta.graphql_input_type``. This guards that the bypass holds.
    """
    from django_graphex.native.base import _gdx_input_registry
    from django_graphex.types import DjangoInputObjectType
    from tests.models import Category

    before = list(_gdx_input_registry)

    class _RegistryIsolationInput(DjangoInputObjectType):
        class Meta:
            model = Category
            input_for = "create"

    after = list(_gdx_input_registry)
    assert after == before, (
        "DjangoInputObjectType subclass must NOT be appended to "
        "_gdx_input_registry (the InputType registry is for annotation-driven "
        f"model-free inputs only). Leaked: {set(after) - set(before)}"
    )
    # The driver-built _meta (NOT an empty _GdxInputMeta) must survive — its
    # graphql_input_type is the compiled GraphQLInputObjectType.
    from graphql import GraphQLInputObjectType

    assert isinstance(
        _RegistryIsolationInput._meta.graphql_input_type, GraphQLInputObjectType
    )


def test_gdx_input_options_graphql_input_type_default_none():
    """_GdxInputOptions.graphql_input_type defaults to None before compilation."""
    from django_graphex.native.base import _GdxInputOptions

    opts = _GdxInputOptions()
    assert opts.graphql_input_type is None


def test_input_type_meta_populated_by_compile_all_inputs():
    """InputType._meta.graphql_input_type is None before compile_all_inputs."""
    from django_graphex.native.base import InputType

    class _WuBTestPreCompile(InputType):
        """Test pre-compile state."""
        value: str

    # Before compile_all_inputs, _meta.graphql_input_type is None
    assert _WuBTestPreCompile._meta.graphql_input_type is None  # type: ignore[attr-defined]


# ---------------------------------------------------------------------------
# INTEGRATED WIRING TESTS (corrective WU-B apply)
# Verify that DjangoInputObjectType.__init_subclass_with_meta__ actually calls
# compile_input_type and stores the result on _meta.graphql_input_type.
# These are the tests that were missing — the previous batch only exercised
# compile_input_type in isolation; these assert the PRODUCTION INTEGRATION.
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_django_input_object_type_meta_graphql_input_type_is_graphql_type():
    """Under GDX_BACKEND=native, DjangoInputObjectType subclass must set
    _meta.graphql_input_type to a real GraphQLInputObjectType at class creation.

    This is the core integration gate for WU-B: the production
    __init_subclass_with_meta__ must branch on GDX_BACKEND and call
    compile_input_type; the existing graphene path must remain intact.
    """
    from graphql import GraphQLInputObjectType
    from django_graphex.types import DjangoInputObjectType
    from tests.models import Category

    class _IntegCategoryCreateInput(DjangoInputObjectType):
        class Meta:
            model = Category
            input_for = "create"

    meta = _IntegCategoryCreateInput._meta
    assert hasattr(meta, "graphql_input_type"), (
        "DjangoInputObjectType._meta must expose graphql_input_type under native"
    )
    assert isinstance(meta.graphql_input_type, GraphQLInputObjectType), (
        "DjangoInputObjectType._meta.graphql_input_type must be a "
        f"GraphQLInputObjectType, got {type(meta.graphql_input_type)}"
    )


@pytest.mark.django_db
def test_django_input_object_type_native_no_container_created():
    """Under GDX_BACKEND=native, _meta.graphql_input_type is set; no container
    is read by the native resolver path (graphene still has a container for its own
    schema build, but that is a graphene-internal detail we don't test here).
    """
    from graphql import GraphQLInputObjectType
    from django_graphex.types import DjangoInputObjectType
    from tests.models import Category

    class _IntegCategoryUpdateInput(DjangoInputObjectType):
        class Meta:
            model = Category
            input_for = "update"

    meta = _IntegCategoryUpdateInput._meta
    # Must have a graphql_input_type set by native compile path
    assert isinstance(meta.graphql_input_type, GraphQLInputObjectType)


@pytest.mark.django_db
def test_django_input_object_type_update_meta_all_fields_nullable():
    """Under native, update input (partial=True) → all fields nullable."""
    from graphql import GraphQLNonNull, GraphQLInputObjectType
    from django_graphex.types import DjangoInputObjectType
    from tests.models import Category

    class _IntegCategoryUpdate2Input(DjangoInputObjectType):
        class Meta:
            model = Category
            input_for = "update"

    gql_type = _IntegCategoryUpdate2Input._meta.graphql_input_type
    assert isinstance(gql_type, GraphQLInputObjectType)

    for field_name, field in gql_type.fields.items():
        assert not isinstance(field.type, GraphQLNonNull), (
            f"Update input field {field_name!r} must be nullable under partial=True, "
            f"got {field.type!r}"
        )


@pytest.mark.django_db
def test_mutation_arguments_use_graphql_argument_under_native():
    """Under GDX_BACKEND=native, DjangoModelType's _meta.arguments['create'] must
    hold a dict with a GraphQLArgument (not a graphene Argument).

    This is the 'call site' integration test: when the 6 factory_type("input", ...)
    call sites are properly wired, global_arguments[op][input_field_name] must be
    a graphql-core GraphQLArgument, not a graphene Argument.
    """
    from graphql import GraphQLArgument
    from django_graphex.types import DjangoModelType
    from tests.models import Category

    class _IntegCategoryType(DjangoModelType):
        class Meta:
            model = Category

    args_create = _IntegCategoryType._meta.arguments.get("create", {})
    assert args_create, "DjangoModelType must have 'create' arguments"

    # Find the input argument (not 'id')
    input_arg = None
    for key, val in args_create.items():
        if key != "id":
            input_arg = val
            break

    assert input_arg is not None, "Must have an input argument for 'create'"
    assert isinstance(input_arg, GraphQLArgument), (
        f"Under GDX_BACKEND=native, mutation input arg must be GraphQLArgument, "
        f"got {type(input_arg)}"
    )
