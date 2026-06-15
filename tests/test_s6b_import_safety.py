"""S6b import-safety gate — core modules import cleanly under BOTH backends.

After re-parenting ``DjangoObjectType`` / ``DjangoListObjectType`` off graphene
(S6b), the package's eagerly-imported modules MUST still import under both
``GDX_BACKEND=native`` AND ``GDX_BACKEND=graphene``. A bare ``import`` of these
modules needs Django configured, so this runs inside the test harness (conftest
configures settings). The actual backend value is read from the environment at
import time; running this file under each ``GDX_BACKEND`` proves both paths.

Run BOTH:
    GDX_BACKEND=native   .venv/bin/python -m pytest tests/test_s6b_import_safety.py -q -o addopts="" -p no:cacheprovider --no-header --override-ini=addopts=""
    GDX_BACKEND=graphene .venv/bin/python -m pytest tests/test_s6b_import_safety.py -q -o addopts=""
"""
from __future__ import annotations

import importlib
import os

import pytest

_NATIVE = os.environ.get("GDX_BACKEND", "graphene") == "native"

_CORE_MODULES = (
    "django_graphex",
    "django_graphex.types",
    "django_graphex.mutation",
    "django_graphex.schema",
    "django_graphex.native.base",
    "django_graphex.subscriptions",
)


@pytest.mark.parametrize("module_name", _CORE_MODULES)
def test_core_module_imports_clean(module_name: str) -> None:
    """Each core module imports without raising under the active backend."""
    mod = importlib.import_module(module_name)
    assert mod is not None


def test_reparented_types_importable_and_native_metaclass() -> None:
    """DjangoObjectType / DjangoListObjectType import and carry the native base."""
    from django_graphex.native.base import ObjectType as NativeObjectType
    from django_graphex.types import DjangoListObjectType, DjangoObjectType

    # S6b: both re-parented onto the native graphene-free base.
    assert issubclass(DjangoObjectType, NativeObjectType)
    assert issubclass(DjangoListObjectType, NativeObjectType)


def test_s6d_polymorphic_types_reparented_onto_native_base() -> None:
    """S6d: DjangoUnionType / DjangoInterfaceType carry the native base.

    Both are REGISTRY-ONLY metadata carriers re-parented off graphene
    ``Union`` / ``Interface`` onto ``native.base.ObjectType`` (no compiled
    native Union/Interface GraphQL type today). Importability under both
    backends + the native base identity are the S6d import-safety contract.
    """
    from pydantic._internal._model_construction import ModelMetaclass

    from django_graphex.native.base import ObjectType as NativeObjectType
    from django_graphex.types import DjangoInterfaceType, DjangoUnionType

    assert issubclass(DjangoUnionType, NativeObjectType)
    assert issubclass(DjangoInterfaceType, NativeObjectType)
    # #1452 metaclass-identity invariant holds for the re-parented bases.
    assert type(DjangoUnionType) is ModelMetaclass
    assert type(DjangoInterfaceType) is ModelMetaclass


def test_s6e_subscription_reparented_onto_native_base() -> None:
    """S6e: ``Subscription`` carries the native base; subclass is ModelMetaclass.

    Re-parented off graphene ``ObjectType`` onto ``native.base.ObjectType``. The
    base must NO LONGER subclass graphene ``ObjectType`` and a concrete subclass's
    metaclass IS pydantic ``ModelMetaclass`` (#1452). Importing the subscriptions
    package pulls the ``[subscriptions]`` extra (Channels), so this lives with the
    import-safety gate (it proves the re-parent imports clean under both backends).
    """
    from pydantic._internal._model_construction import ModelMetaclass

    from django_graphex.native.base import ObjectType as NativeObjectType
    from django_graphex.subscriptions import Subscription

    assert issubclass(Subscription, NativeObjectType)
    # The base itself stays abstract; build a concrete subclass to assert the
    # metaclass-identity invariant (a class's metaclass is fixed at definition).
    from tests.models import Post

    meta_cls = type("Meta", (), {"model": Post, "stream": "posts"})
    meta_cls.__qualname__ = "_S6eSub.Meta"
    meta_cls.__module__ = __name__
    sub = type(
        "_S6eSub",
        (Subscription,),
        {"__module__": __name__, "__qualname__": "_S6eSub", "Meta": meta_cls},
    )
    assert type(sub) is ModelMetaclass


def test_s6f_django_graphql_schema_off_graphene_schema_base() -> None:
    """S6f: ``DjangoGraphQLSchema`` no longer subclasses ``graphene.Schema``.

    The S6 metaclass-swap block closes here: the schema builds its
    ``graphql_schema`` directly via the native root compiler and is a plain
    class. Importability + the base-identity invariant must hold under BOTH
    backends (under graphene the type is dead-but-importable post-S6).
    """
    import graphene

    from django_graphex.schema import DjangoGraphQLSchema

    assert not issubclass(DjangoGraphQLSchema, graphene.Schema)
    assert graphene.Schema not in DjangoGraphQLSchema.__mro__
    # The public surface attributes graphene.Schema provided are still declared.
    assert hasattr(DjangoGraphQLSchema, "__str__")
    assert hasattr(DjangoGraphQLSchema, "__init__")


@pytest.mark.skipif(
    not _NATIVE,
    reason="native root compile path (GDX_BACKEND=native); the graphene "
    "schema-build path for re-parented types is retired per slice",
)
def test_s6e_subscription_field_present_in_compiled_native_root() -> None:
    """S6e risk #4: the subscription field is PRESENT in the compiled native root.

    Re-parenting ``Subscription`` must NOT make the mount seam vanish. The native
    root compiler detects the ``SubscriptionField`` by class name and builds the
    DIRECT graphql-core field via ``field.type._build_native_field()``. This
    asserts the field survives the re-parent (it must not silently disappear).
    """
    import graphene
    from graphql import GraphQLObjectType

    from django_graphex import DjangoModelType
    from django_graphex.native.registry_compiler import compile_all_outputs
    from django_graphex.native.schema_compiler import compile_native_root
    from tests.models import Post

    class _S6ePostModelType(DjangoModelType):
        class Meta:
            model = Post
            stream = "posts"
            serialize_data = True

    class _S6eSubscriptionRoot(graphene.ObjectType):
        post = _S6ePostModelType.SubscriptionField()

    compile_all_outputs()
    native_root = compile_native_root(_S6eSubscriptionRoot, name="Subscription")

    assert isinstance(native_root, GraphQLObjectType)
    # The mount seam survived the re-parent: the subscription field IS present.
    assert "post" in native_root.fields
    # Native arg set + the field is a DIRECT graphql-core field (no graphene Field).
    assert set(native_root.fields["post"].args) == {"action", "id", "filters"}


def test_s_roots_f_public_objecttype_and_field_exported_both_backends() -> None:
    """S-ROOTS-f: ``ObjectType`` + ``field`` are importable from the top-level
    package under BOTH backends (the graphene-free public field-declaration API,
    decision #1554) and are the canonical native objects."""
    from django_graphex import ObjectType, field
    from django_graphex.native.base import ObjectType as NativeObjectType
    from django_graphex.native.descriptors import field as native_field

    assert ObjectType is NativeObjectType
    assert field is native_field
