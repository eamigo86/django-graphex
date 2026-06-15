"""item-b B3 + B4 — schema owns a ``SchemaRegistries`` + query-time resolve_type scoping.

B3 (schema owns the pair):
- ``DjangoGraphQLSchema`` selects a ``SchemaRegistries`` (new optional ``registries=``
  kwarg; ``None`` -> the global default pair) and exposes it on
  ``graphql_schema.extensions['gdx_registry']`` ALONGSIDE the existing
  ``gdx_protected_fields`` extension.
- The selected pair is threaded into the native build (compile uses THAT pair's
  caches/registry). With the default pair this is byte-identical to today.

B4 (query-time scoping for polymorphic resolve_type):
- ``DjangoUnionType`` / ``DjangoInterfaceType`` ``resolve_type`` reads the
  schema-scoped registry from ``info.schema.extensions['gdx_registry']`` FIRST,
  then falls back to the existing per-class ``_dgx_registry`` / global chain.
- The loud-failure contract is preserved: an unresolvable model RAISES
  ``TypeError`` (never returns ``None``).
- With the default pair the resolved registry IS the global, so resolution is
  byte-identical.

Run: GDX_BACKEND=native .venv/bin/python -m pytest -q \
    tests/native/test_schema_scoped_registry.py
"""
from __future__ import annotations

import os

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "tests.settings")

import django

django.setup()

import pytest

pytestmark = pytest.mark.native_only


# =========================================================================== #
# Helpers                                                                      #
# =========================================================================== #
class _FakeSchema:
    """Minimal stand-in for ``info.schema`` carrying only ``extensions``.

    ``resolve_type`` reads the schema-scoped registry exactly as ``security.py``
    reads protected fields: ``getattr(info, 'schema', None)`` ->
    ``getattr(schema, 'extensions', None) or {}`` -> ``.get('gdx_registry')``.
    A plain object with an ``extensions`` dict is all the contract needs.
    """

    def __init__(self, extensions: dict | None) -> None:
        self.extensions = extensions


class _FakeInfo:
    """Minimal stand-in for ``ResolveInfo`` carrying only ``schema``."""

    def __init__(self, schema: object | None) -> None:
        self.schema = schema


def _build_union_pair():
    """Return (Registry, AccountType, InvoiceType, union) wired in a fresh registry."""
    import graphene

    from django_graphex.registry import Registry
    from django_graphex.types import DjangoObjectType, DjangoUnionType
    from tests.models import Track2Account, Track2Invoice  # noqa: F401

    reg = Registry()

    class AccountType(DjangoObjectType):
        class Meta:
            model = Track2Account
            registry = reg

    class InvoiceType(DjangoObjectType):
        class Meta:
            model = Track2Invoice
            registry = reg

    class PaymentUnion(DjangoUnionType):
        class Meta:
            gfk_types = (AccountType, InvoiceType)
            registry = reg

    return reg, AccountType, InvoiceType, PaymentUnion


# =========================================================================== #
# B3 — DjangoGraphQLSchema owns a SchemaRegistries                             #
# =========================================================================== #
@pytest.mark.django_db
def test_schema_sets_gdx_registry_extension_to_default_pair():
    """A default ``DjangoGraphQLSchema`` exposes the GLOBAL pair on the extension.

    B3: ``graphql_schema.extensions['gdx_registry']`` IS the process-wide default
    pair (``default_schema_registries()``), set ALONGSIDE the existing
    ``gdx_protected_fields`` extension. With no ``registries=`` the schema must
    pick the default pair, so this read path is wired without a 2nd schema.

    TEETH: before B3 the extension does not exist, so ``.get('gdx_registry')`` is
    ``None`` and this identity assertion fails.
    """
    import graphene

    from django_graphex.fields import DjangoObjectField
    from django_graphex.native.base import default_schema_registries
    from django_graphex.native.registry_compiler import compile_all_outputs
    from django_graphex.schema import DjangoGraphQLSchema
    from django_graphex.types import DjangoObjectType
    from tests.models import Category

    class _ScopedCatType(DjangoObjectType):
        class Meta:
            model = Category

    compile_all_outputs()

    class _ScopedQuery(graphene.ObjectType):
        category = DjangoObjectField(_ScopedCatType)

    schema = DjangoGraphQLSchema(query=_ScopedQuery)
    extensions = schema.graphql_schema.extensions or {}
    assert extensions.get("gdx_registry") is default_schema_registries()


@pytest.mark.django_db
def test_schema_keeps_protected_fields_extension_alongside_registry():
    """``gdx_registry`` is added WITHOUT clobbering ``gdx_protected_fields``.

    B3 sets the registry extension alongside the existing protected-fields one;
    both must survive on the same schema.

    TEETH: if B3 replaced ``extensions`` (instead of adding a key), the protected
    set would vanish and the auth middleware read path would break.
    """
    import graphene

    from django_graphex.schema import DjangoGraphQLSchema

    class _PubQuery(graphene.ObjectType):
        hello = graphene.String()

    class _PrivQuery(graphene.ObjectType):
        secret = graphene.String()

    schema = DjangoGraphQLSchema(query=_PubQuery, private_query=_PrivQuery)
    extensions = schema.graphql_schema.extensions or {}
    # Both extensions coexist.
    assert "gdx_registry" in extensions
    assert extensions.get("gdx_protected_fields") == frozenset({"secret"})


@pytest.mark.django_db
def test_explicit_registries_kwarg_is_used_for_extension():
    """An explicit ``registries=`` pair is the one exposed on the extension.

    B3: the optional ``registries=`` kwarg selects the pair; ``None`` -> default.
    An explicitly-passed pair must be the exact object stored on the extension
    (this is the seam B5's lazy-fork rides on).

    TEETH: if ``__init__`` ignored ``registries=`` and always used the global
    default, this identity check against the custom pair fails.
    """
    import graphene

    from django_graphex.fields import DjangoObjectField
    from django_graphex.native.base import (
        SchemaRegistries,
        default_schema_registries,
    )
    from django_graphex.native.registry_compiler import compile_all_outputs
    from django_graphex.schema import DjangoGraphQLSchema
    from django_graphex.types import DjangoObjectType
    from tests.models import Category

    class _ExplicitCatType(DjangoObjectType):
        class Meta:
            model = Category

    compile_all_outputs()

    class _ExplicitQuery(graphene.ObjectType):
        category = DjangoObjectField(_ExplicitCatType)

    # A pair that REUSES the global registries (so compile stays byte-identical)
    # but is a DISTINCT container object — proves the kwarg is threaded through.
    default = default_schema_registries()
    custom = SchemaRegistries(
        graphene=default.graphene,
        output=default.output,
        plain_object_cache=default.plain_object_cache,
        union_cache=default.union_cache,
        interface_cache=default.interface_cache,
        filter_input_cache=default.filter_input_cache,
    )
    assert custom is not default

    schema = DjangoGraphQLSchema(query=_ExplicitQuery, registries=custom)
    extensions = schema.graphql_schema.extensions or {}
    assert extensions.get("gdx_registry") is custom


# =========================================================================== #
# B4 — query-time scoping for polymorphic resolve_type                         #
# =========================================================================== #
@pytest.mark.django_db
def test_resolve_type_prefers_schema_scoped_registry_over_class_binding():
    """resolve_type reads ``info.schema.extensions['gdx_registry']`` FIRST.

    Two independent registries each register a DjangoObjectType for the SAME
    model. The union is bound (``_dgx_registry``) to registry A, but the request
    carries a schema whose ``gdx_registry`` pair points its ``.graphene`` at
    registry B. resolve_type must return B's type — proving the schema-scoped
    registry wins over the per-class binding.

    TEETH: before B4, resolve_type ignores ``info`` entirely and returns A's
    type (the ``_dgx_registry`` binding), so the identity assertion against B's
    type fails.
    """
    from django_graphex.native.base import SchemaRegistries
    from django_graphex.registry import Registry
    from django_graphex.types import DjangoObjectType, DjangoUnionType
    from tests.models import Track2Account, Track2Invoice

    reg_a = Registry()

    class AccountTypeA(DjangoObjectType):
        class Meta:
            model = Track2Account
            registry = reg_a

    class InvoiceTypeA(DjangoObjectType):
        class Meta:
            model = Track2Invoice
            registry = reg_a

    class PaymentUnion(DjangoUnionType):
        class Meta:
            gfk_types = (AccountTypeA, InvoiceTypeA)
            registry = reg_a

    # Registry B registers a DISTINCT AccountType for the same model.
    reg_b = Registry()

    class AccountTypeB(DjangoObjectType):
        class Meta:
            model = Track2Account
            registry = reg_b

    assert AccountTypeA is not AccountTypeB

    pair_b = SchemaRegistries(graphene=reg_b)
    info = _FakeInfo(_FakeSchema({"gdx_registry": pair_b}))

    instance = Track2Account(balance=10)
    resolved = PaymentUnion.resolve_type(instance, info)
    assert resolved is AccountTypeB, (
        "resolve_type must consult the schema-scoped registry (B) first, not the "
        "union's _dgx_registry binding (A)."
    )


@pytest.mark.django_db
def test_resolve_type_falls_back_to_class_binding_when_schema_scope_misses():
    """When the schema-scoped registry has NO type, fall back to ``_dgx_registry``.

    The union is bound to registry A (which DOES register the model); the request
    carries a schema-scoped pair whose ``.graphene`` is an EMPTY registry. The
    scoped registry misses, so resolution falls through to A — byte-identical to
    the pre-B4 chain.

    TEETH: if B4 used ONLY the schema-scoped registry (no fallback), the empty
    scope would miss and the resolve would raise instead of returning A's type.
    """
    from django_graphex.native.base import SchemaRegistries
    from django_graphex.registry import Registry
    from django_graphex.types import DjangoObjectType, DjangoUnionType
    from tests.models import Track2Account, Track2Invoice

    reg_a = Registry()

    class AccountTypeA(DjangoObjectType):
        class Meta:
            model = Track2Account
            registry = reg_a

    class InvoiceTypeA(DjangoObjectType):
        class Meta:
            model = Track2Invoice
            registry = reg_a

    class PaymentUnion(DjangoUnionType):
        class Meta:
            gfk_types = (AccountTypeA, InvoiceTypeA)
            registry = reg_a

    empty_pair = SchemaRegistries(graphene=Registry())
    info = _FakeInfo(_FakeSchema({"gdx_registry": empty_pair}))

    instance = Track2Account(balance=10)
    resolved = PaymentUnion.resolve_type(instance, info)
    assert resolved is AccountTypeA, (
        "When the schema-scoped registry misses, resolve_type must fall back to "
        "the union's _dgx_registry (A)."
    )


@pytest.mark.django_db
def test_resolve_type_falls_back_when_info_has_no_gdx_registry():
    """resolve_type with ``info=None`` (or no extension) uses the class chain.

    The track2 unit tests call ``union.resolve_type(instance, None)`` directly.
    B4 must not crash on a ``None`` info / missing extension — it degrades to the
    existing ``_dgx_registry`` / global chain (byte-identical).

    TEETH: a naive ``info.schema.extensions`` dereference would raise
    AttributeError on ``info=None``; the defensive getattr chain must degrade.
    """
    _reg, account_type, _invoice_type, union = _build_union_pair()
    from tests.models import Track2Account

    instance = Track2Account(balance=10)

    # info=None (the unit-test call style) must still resolve via the binding.
    assert union.resolve_type(instance, None) is account_type
    # An info whose schema carries no gdx_registry extension also degrades.
    info = _FakeInfo(_FakeSchema({}))
    assert union.resolve_type(instance, info) is account_type


@pytest.mark.django_db
def test_resolve_type_raises_on_total_miss_never_returns_none():
    """An instance unresolvable in EVERY candidate registry RAISES (never None).

    Loud-failure contract: a model registered in NEITHER the schema-scoped pair
    NOR the class binding must raise ``TypeError`` (a silent ``None`` would
    surface as the opaque "Abstract type must resolve to an Object type").

    TEETH: if B4's fallback chain swallowed the miss and returned None, this
    ``pytest.raises`` fails.
    """
    from django_graphex.native.base import SchemaRegistries
    from django_graphex.registry import Registry
    from django_graphex.types import DjangoObjectType, DjangoUnionType
    from tests.models import (
        Track2Account,
        Track2Invoice,
        Track2Magazine,
    )

    reg = Registry()

    class AccountType(DjangoObjectType):
        class Meta:
            model = Track2Account
            registry = reg

    class InvoiceType(DjangoObjectType):
        class Meta:
            model = Track2Invoice
            registry = reg

    class PaymentUnion(DjangoUnionType):
        class Meta:
            gfk_types = (AccountType, InvoiceType)
            registry = reg

    # A schema-scoped pair whose registry ALSO lacks Track2Magazine.
    info = _FakeInfo(_FakeSchema({"gdx_registry": SchemaRegistries(graphene=Registry())}))

    with pytest.raises(TypeError):
        PaymentUnion.resolve_type(Track2Magazine(name="x"), info)


@pytest.mark.django_db
def test_interface_resolve_type_reads_schema_scope_too():
    """The interface resolve_type path shares the schema-scoped read.

    Both ``DjangoUnionType`` and ``DjangoInterfaceType`` delegate to the SAME
    ``_resolve_polymorphic_type`` helper, so the interface path must also consult
    ``info.schema.extensions['gdx_registry']`` first.

    TEETH: if only the union path were patched, the interface would ignore the
    schema scope and return the class-binding type (A) instead of B's.
    """
    import graphene

    from django_graphex.native.base import SchemaRegistries
    from django_graphex.registry import Registry
    from django_graphex.types import DjangoInterfaceType, DjangoObjectType
    from tests.models import Track2Book

    reg_a = Registry()

    class ProductInterface(DjangoInterfaceType):
        name = graphene.String()

        class Meta:
            registry = reg_a

    class BookTypeA(DjangoObjectType):
        class Meta:
            model = Track2Book
            registry = reg_a
            interfaces = (ProductInterface,)

    reg_b = Registry()

    class BookTypeB(DjangoObjectType):
        class Meta:
            model = Track2Book
            registry = reg_b

    assert BookTypeA is not BookTypeB

    info = _FakeInfo(_FakeSchema({"gdx_registry": SchemaRegistries(graphene=reg_b)}))
    resolved = ProductInterface.resolve_type(Track2Book(name="b"), info)
    assert resolved is BookTypeB
