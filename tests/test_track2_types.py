# -*- coding: utf-8 -*-
"""Track 2 — Union / Interface MVP, BLOCK A (T-01..T-07).

Covers the type-system FOUNDATION only ("inert-but-correct"): the registry
parallel stores + dispatch, the ``gfk_unions`` Meta surface, the
``DjangoUnionType`` / ``DjangoInterfaceType`` bases with their MANDATORY
``resolve_type`` contract, the public exports, and the GFK→Union converter
branch (with GenericForeignKeyType fallback). The optimizer routing
(GenericPrefetch / ``_resolve_fragment_target``) is BLOCK B — out of scope here.

Every test states the mutation that breaks it (its "teeth").
"""

from __future__ import annotations

import warnings

import graphene
import pytest
from django.contrib.contenttypes.fields import GenericForeignKey
from graphene import Dynamic, Field
from graphql import GraphQLString, GraphQLUnionType

from django_graphex import (
    DjangoInterfaceType,
    DjangoObjectType,
    DjangoUnionType,
    field,
)
from django_graphex.base_types import GenericForeignKeyType
from django_graphex.converter import convert_django_field
from django_graphex.registry import Registry
from django_graphex.schema import DjangoGraphQLSchema

from .models import (
    Track2Account,
    Track2Book,
    Track2GfkComment,
    Track2Invoice,
    Track2Magazine,
)


# --------------------------------------------------------------------------- #
# Helpers — build a fresh, isolated registry with the member ObjectTypes.      #
# --------------------------------------------------------------------------- #
def _make_member_types(reg):
    """Register AccountType / InvoiceType in ``reg`` and return them."""

    class AccountType(DjangoObjectType):
        class Meta:
            model = Track2Account
            registry = reg

    class InvoiceType(DjangoObjectType):
        class Meta:
            model = Track2Invoice
            registry = reg

    return AccountType, InvoiceType


def _make_union(reg, members):
    class PaymentUnion(DjangoUnionType):
        class Meta:
            gfk_types = members
            registry = reg

    return PaymentUnion


# =========================================================================== #
# T-01 / T-02 — Registry parallel stores + register_polymorphic + dispatch     #
# =========================================================================== #
def test_register_polymorphic_stores_union_and_leaves_types_untouched():
    """register_polymorphic routes a union to ``_union_types`` only.

    TEETH: if register_polymorphic wrote to ``_types`` (or the dispatch in
    register() fell through to the (model, for_input) write), ``_types`` would
    grow and this assertion on its emptiness-of-union would fail.
    """
    reg = Registry()
    members = _make_member_types(reg)
    types_snapshot = dict(reg._types)

    union = _make_union(reg, members)

    assert reg._union_types[union._meta.name] is union
    # _types must be byte-for-byte what it was before the union appeared.
    assert reg._types == types_snapshot


def test_register_polymorphic_is_idempotent():
    """Registering the same union twice overwrites harmlessly (no raise).

    TEETH: if register_polymorphic raised on a duplicate name, the second call
    would error.
    """
    reg = Registry()
    members = _make_member_types(reg)
    union = _make_union(reg, members)

    # Second registration via the public register() path -> dispatch -> polymorphic.
    reg.register(union)
    assert reg._union_types[union._meta.name] is union


def test_register_union_then_register_objecttype_both_work():
    """register(union) is a no-op on _types; a later register(ObjectType) works.

    TEETH: if the dispatch did not early-return, register(union) would attempt
    the ``(cls._meta.model, for_input)`` write — a union has no single model, so
    it would corrupt _types or crash; and the subsequent ObjectType register
    would be the only way to prove _types still accepts normal types.
    """
    reg = Registry()
    members = _make_member_types(reg)
    union = _make_union(reg, members)

    reg.register(union)  # must not touch _types

    class LateType(DjangoObjectType):
        class Meta:
            model = Track2Book
            registry = reg

    assert reg.get_type_for_model(Track2Book) is LateType
    assert reg._union_types[union._meta.name] is union


def test_get_model_for_type_name_resolves_via_types_only():
    """get_model_for_type_name maps a GraphQL name back to its model.

    TEETH: if it scanned ``_union_types`` (or matched input entries), it could
    return the wrong model; here AccountType -> Track2Account must hold and an unknown
    name must be None.
    """
    reg = Registry()
    account_type, _ = _make_member_types(reg)

    assert reg.get_model_for_type_name(account_type._meta.name) is Track2Account
    assert reg.get_model_for_type_name("NoSuchType") is None


def test_get_member_models_union_is_ordered():
    """get_member_models(union) returns the explicit member models, in order.

    TEETH: if it derived members from ContentType rows or a set, order/identity
    would not match [Track2Account, Track2Invoice].
    """
    reg = Registry()
    members = _make_member_types(reg)
    union = _make_union(reg, members)

    assert reg.get_member_models(union) == [Track2Account, Track2Invoice]


def test_register_polymorphic_rejects_cross_registry_union():
    """A union built in registry A cannot be registered into registry B.

    REG-INV-01: ``register_polymorphic`` must mirror the object-type
    ``register()`` guard (``"Registry for a Model must match."``). Without the
    guard, ``regB.register(union_from_A)`` would write ``regB._union_types`` while
    the union's ``_dgx_registry`` still points to A, so its ``resolve_type``
    consults A's ``_types`` — a silent stale-registry resolve.

    TEETH: drop the ``_dgx_registry is not self`` guard and the cross-registry
    register() succeeds silently, so this ``pytest.raises`` fails AND
    ``reg_b._union_types`` is polluted with a foreign-bound union.
    """
    reg_a = Registry()
    members_a = _make_member_types(reg_a)
    union = _make_union(reg_a, members_a)

    reg_b = Registry()
    with pytest.raises(ValueError, match="Registry for a polymorphic type must match"):
        reg_b.register(union)

    # The foreign union must NOT have leaked into reg_b's polymorphic store.
    assert union._meta.name not in reg_b._union_types
    # And the union's own binding is untouched (still points at reg_a).
    assert union._dgx_registry is reg_a


def test_register_polymorphic_rejects_cross_registry_interface():
    """An interface built in registry A cannot be registered into registry B.

    REG-INV-01: same cross-registry guard, exercised through the interface path
    of ``register_polymorphic``.

    TEETH: without the bound-registry guard, ``reg_b.register(interface)`` writes
    ``reg_b._interface_types`` for a foreign-bound interface.
    """
    reg_a = Registry()

    class ProductInterface(DjangoInterfaceType):
        name = field(GraphQLString)

        class Meta:
            registry = reg_a

    reg_b = Registry()
    with pytest.raises(ValueError, match="Registry for a polymorphic type must match"):
        reg_b.register(ProductInterface)

    assert ProductInterface._meta.name not in reg_b._interface_types
    assert ProductInterface._dgx_registry is reg_a


def test_register_polymorphic_same_registry_still_works():
    """The cross-registry guard does NOT block a same-registry re-registration.

    REG-INV-01 regression net: the bound-registry check must be ``is not self``,
    not ``is not None`` — a union re-registered into its OWN registry must still
    pass (idempotent overwrite), otherwise the guard would break the auto-register
    + manual-register double path documented for ``register_polymorphic``.

    TEETH: if the guard mistakenly raised whenever ``_dgx_registry`` is set, this
    same-registry register() would raise and the test would fail.
    """
    reg = Registry()
    members = _make_member_types(reg)
    union = _make_union(reg, members)

    reg.register(union)  # same registry — must be a benign overwrite, no raise.
    assert reg._union_types[union._meta.name] is union


def test_register_polymorphic_rejects_non_polymorphic_class():
    """Direct misuse with a non-polymorphic class fails loud (TypeError).

    REG-INV-02: ``register_polymorphic`` branches union/interface with no ``else``
    in the original; a class that is neither would fall through, storing nothing
    and raising nothing — silently dropped from BOTH the polymorphic stores and
    ``_types``. The trailing ``else: raise TypeError`` makes direct misuse loud.

    TEETH: remove the trailing ``else`` and this call returns None silently, so
    the ``pytest.raises(TypeError)`` fails.
    """
    reg = Registry()
    account_type, _ = _make_member_types(reg)

    # A plain DjangoObjectType has a ``_meta.name`` but is neither a union nor an
    # interface — the realistic "wrong class" for direct misuse of the method.
    with pytest.raises(TypeError, match="DjangoUnionType or DjangoInterfaceType"):
        reg.register_polymorphic(account_type)


# =========================================================================== #
# T-03 — DjangoObjectOptions.gfk_unions Meta round-trip + get_gfk_union         #
# =========================================================================== #
def test_gfk_unions_meta_round_trips_and_registry_lookup():
    """Meta.gfk_unions is stored on _meta and resolvable via the registry.

    TEETH: if the kwarg were dropped (not stored on _meta) or get_gfk_union
    looked at the wrong store, the union would not round-trip for ("target").
    """
    reg = Registry()
    members = _make_member_types(reg)
    union = _make_union(reg, members)

    class GfkCommentType(DjangoObjectType):
        class Meta:
            model = Track2GfkComment
            registry = reg
            gfk_unions = {"target": union}

    assert GfkCommentType._meta.gfk_unions["target"] is union
    assert reg.get_gfk_union(Track2GfkComment, "target") is union
    # Absent FK name -> None, never a crash.
    assert reg.get_gfk_union(Track2GfkComment, "absent") is None


def test_gfk_unions_defaults_to_none_when_absent():
    """A DjangoObjectType without Meta.gfk_unions has _meta.gfk_unions falsy.

    TEETH: if the default leaked a shared mutable dict or a truthy sentinel,
    get_gfk_union would mis-report a union for a plain type.
    """
    reg = Registry()

    class PlainType(DjangoObjectType):
        class Meta:
            model = Track2Account
            registry = reg

    assert not PlainType._meta.gfk_unions
    assert reg.get_gfk_union(Track2Account, "anything") is None


# =========================================================================== #
# T-04 — DjangoUnionType base: resolve_type contract + no possible_types        #
# =========================================================================== #
def test_union_resolve_type_returns_registered_objecttype():
    """resolve_type(instance) -> the registered DjangoObjectType for its model.

    TEETH: if resolve_type returned None or fell through to graphene's default
    (which returns None for Django rows), this identity check would fail and a
    real schema would raise "Abstract type must resolve to an Object type".
    """
    reg = Registry()
    account_type, _ = _make_member_types(reg)
    union = _make_union(reg, (account_type, reg.get_type_for_model(Track2Invoice)))

    instance = Track2Account(balance=10)
    assert union.resolve_type(instance, None) is account_type


def test_union_resolve_type_raises_on_unregistered_instance():
    """resolve_type raises (descriptive) for an instance with no registered type.

    TEETH: if resolve_type silently returned None for an unknown model, this
    would not raise — exactly the silent-None bug the spec forbids.
    """
    reg = Registry()
    members = _make_member_types(reg)
    union = _make_union(reg, members)

    # Track2Magazine has NO DjangoObjectType registered in ``reg``.
    with pytest.raises(TypeError):
        union.resolve_type(Track2Magazine(name="x"), None)


def test_union_does_not_set_possible_types():
    """The union base/subclass never sets Meta.possible_types.

    TEETH: if possible_types were set, it would collide with is_type_of and
    AssertionError at schema build (objecttype.py:143). Guard at the _meta level.
    """
    reg = Registry()
    members = _make_member_types(reg)
    union = _make_union(reg, members)

    assert getattr(union._meta, "possible_types", None) in (None, ())


def test_union_self_registers_during_construction():
    """Constructing a DjangoUnionType registers it in _union_types (auto).

    TEETH: if register_polymorphic were not called from
    __init_subclass_with_meta__, the union would be absent from _union_types
    until a manual register() — breaking the converter lookup path.
    """
    reg = Registry()
    members = _make_member_types(reg)
    union = _make_union(reg, members)

    assert reg._union_types.get(union._meta.name) is union


def test_union_requires_nonempty_gfk_types():
    """A union with no members is rejected at declaration time.

    TEETH: if the assert were removed, graphene's own "Must provide types"
    assertion would still fire, but the descriptive gfk_types message is the
    contract; either way an empty union must not silently construct.
    """
    reg = Registry()
    with pytest.raises(AssertionError):

        class EmptyUnion(DjangoUnionType):
            class Meta:
                gfk_types = ()
                registry = reg


def test_union_schema_builds_without_assertionerror():
    """A schema exposing a union field builds with no possible_types collision.

    TEETH: if possible_types leaked, schema construction would raise
    AssertionError from objecttype.py is_type_of logic.
    """
    reg = Registry()
    account_type, invoice_type = _make_member_types(reg)
    union = _make_union(reg, (account_type, invoice_type))

    class Query(graphene.ObjectType):
        payment = Field(union)

    schema = DjangoGraphQLSchema(query=Query, types=[account_type, invoice_type])
    # The union is present in the built schema as a GraphQLUnionType.
    gql_union = schema.graphql_schema.get_type(union._meta.name)
    assert isinstance(gql_union, GraphQLUnionType)


# =========================================================================== #
# T-05 — DjangoInterfaceType base: shared fields + resolve_type + members       #
# =========================================================================== #
def test_interface_shared_field_resolves_on_implementors():
    """An interface's shared field is exposed on each implementor.

    TEETH: if Meta.interfaces wiring were broken, the implementor type would
    not declare the interface field and the schema field set would miss ``name``.
    """
    reg = Registry()

    class ProductInterface(DjangoInterfaceType):
        name = field(GraphQLString)

        class Meta:
            registry = reg

    class BookType(DjangoObjectType):
        class Meta:
            model = Track2Book
            registry = reg
            interfaces = (ProductInterface,)

    class MagazineType(DjangoObjectType):
        class Meta:
            model = Track2Magazine
            registry = reg
            interfaces = (ProductInterface,)

    schema = DjangoGraphQLSchema(
        query=type(
            "Q",
            (graphene.ObjectType,),
            {"book": Field(BookType), "magazine": Field(MagazineType)},
        ),
        types=[BookType, MagazineType],
    )
    book_gql = schema.graphql_schema.get_type("BookType")
    assert "name" in book_gql.fields


def test_interface_resolve_type_maps_concrete_instance():
    """interface.resolve_type(magazine) -> MagazineType, not BookType/None.

    TEETH: if resolve_type were not overridden (or returned the first
    implementor), a Track2Magazine row would resolve as BookType — the classic
    mis-attribution the contract forbids.
    """
    reg = Registry()

    class ProductInterface(DjangoInterfaceType):
        name = field(GraphQLString)

        class Meta:
            registry = reg

    class BookType(DjangoObjectType):
        class Meta:
            model = Track2Book
            registry = reg
            interfaces = (ProductInterface,)

    class MagazineType(DjangoObjectType):
        class Meta:
            model = Track2Magazine
            registry = reg
            interfaces = (ProductInterface,)

    assert ProductInterface.resolve_type(Track2Magazine(name="m"), None) is MagazineType
    assert ProductInterface.resolve_type(Track2Book(name="b"), None) is BookType


def test_interface_does_not_set_possible_types():
    """The interface base/subclass never sets Meta.possible_types.

    TEETH: possible_types on an interface would collide with is_type_of the
    same way it does for unions.
    """
    reg = Registry()

    class NodeInterface(DjangoInterfaceType):
        created_at = field(GraphQLString)

        class Meta:
            registry = reg

    assert getattr(NodeInterface._meta, "possible_types", None) in (None, ())


def test_interface_self_registers_and_get_member_models():
    """Interface self-registers; get_member_models returns its implementors.

    TEETH: get_member_models(interface) scans output _types whose
    Meta.interfaces include the interface; if the scan keyed off the wrong
    store or skipped interfaces, the implementor model list would be wrong.
    """
    reg = Registry()

    class ProductInterface(DjangoInterfaceType):
        name = field(GraphQLString)

        class Meta:
            registry = reg

    class BookType(DjangoObjectType):
        class Meta:
            model = Track2Book
            registry = reg
            interfaces = (ProductInterface,)

    class MagazineType(DjangoObjectType):
        class Meta:
            model = Track2Magazine
            registry = reg
            interfaces = (ProductInterface,)

    assert reg._interface_types.get(ProductInterface._meta.name) is ProductInterface
    members = reg.get_member_models(ProductInterface)
    assert set(members) == {Track2Book, Track2Magazine}


# =========================================================================== #
# T-06 — Public exports                                                         #
# =========================================================================== #
def test_public_exports_present():
    """Both bases are importable from the package root and in __all__.

    TEETH: if the import block / __all__ TYPES section were not updated, the
    public import would ImportError or __all__ would omit the names.
    """
    import django_graphex

    assert "DjangoUnionType" in django_graphex.__all__
    assert "DjangoInterfaceType" in django_graphex.__all__
    assert django_graphex.DjangoUnionType is DjangoUnionType
    assert django_graphex.DjangoInterfaceType is DjangoInterfaceType


# =========================================================================== #
# T-07 — Converter GFK→Union branch (+ GenericForeignKeyType fallback/warning)  #
# =========================================================================== #
def _gfk_field():
    return next(
        f
        for f in Track2GfkComment._meta.get_fields()
        if isinstance(f, GenericForeignKey)
    )


def _resolve_dynamic(converted):
    if isinstance(converted, Dynamic):
        return converted.get_type()
    return converted


def test_converter_emits_union_when_gfk_unions_declared():
    """When the owner declares Meta.gfk_unions for the FK, emit a Union field.

    TEETH: if the converter ignored gfk_unions, the field type would be the flat
    GenericForeignKeyType, not the union — this asserts the union is emitted.
    """
    reg = Registry()
    members = _make_member_types(reg)
    union = _make_union(reg, members)

    class GfkCommentType(DjangoObjectType):
        class Meta:
            model = Track2GfkComment
            registry = reg
            gfk_unions = {"target": union}

    field = _resolve_dynamic(convert_django_field(_gfk_field(), registry=reg))
    assert isinstance(field, Field)
    assert field.type is union


def test_converter_falls_back_to_generic_type_when_no_union():
    """No companion union declared -> flat GFK output (no regression).

    TEETH: if the union branch hijacked every GFK, a plain GFK owner would lose
    the flat ``GenericForeignKeyType`` output; this asserts the flat fallback is
    intact.

    S-rel-4: the FLAT GFK output path retired graphene on the native backend — a
    plain GFK (no declared union) now converts to a graphene-free
    ``NativeRelationField`` marker, and the native output compiler renders the
    flat ``GenericForeignKeyType`` from ``model._meta`` (the union path is
    UNTOUCHED — see ``test_converter_emits_union_when_gfk_unions_declared``). On
    the graphene backend the legacy ``Dynamic`` closure is UNCHANGED and still
    resolves to a graphene ``Field`` wrapping ``GenericForeignKeyType``.
    """
    from django_graphex.converter import _NATIVE_BACKEND
    from django_graphex.native.descriptors import NativeRelationField

    reg = Registry()
    _make_member_types(reg)

    class GfkCommentType(DjangoObjectType):
        class Meta:
            model = Track2GfkComment
            registry = reg
            # No gfk_unions declared.

    converted = convert_django_field(_gfk_field(), registry=reg)
    if _NATIVE_BACKEND:
        # S-rel-4: the flat GFK output is a graphene-free native marker.
        assert isinstance(converted, NativeRelationField)
    else:
        field = _resolve_dynamic(converted)
        assert isinstance(field, Field)
        assert field.type is GenericForeignKeyType


@pytest.mark.django_db
def test_converter_no_content_type_query_for_member_discovery():
    """Building the union field issues NO query against django_content_type.

    TEETH: if members were discovered from ContentType rows, resolving the
    Dynamic would hit the DB; this asserts no SQL touches django_content_type
    during conversion.
    """
    from django.db import connection
    from django.test.utils import CaptureQueriesContext

    reg = Registry()
    members = _make_member_types(reg)
    union = _make_union(reg, members)

    class GfkCommentType(DjangoObjectType):
        class Meta:
            model = Track2GfkComment
            registry = reg
            gfk_unions = {"target": union}

    with CaptureQueriesContext(connection) as ctx:
        field = _resolve_dynamic(convert_django_field(_gfk_field(), registry=reg))

    assert field.type is union
    assert not any("django_content_type" in q["sql"] for q in ctx.captured_queries)


def test_converter_warns_and_falls_back_on_misordered_declaration():
    """gfk_unions declared but union missing from registry -> WARNING + fallback.

    TEETH: if a mis-ordered declaration crashed (or silently fell back with no
    signal), this would either raise or see no warning. The contract is: warn
    AND degrade to GenericForeignKeyType.

    S-rel-4: the converter-level warning lives INSIDE the graphene flat-GFK
    closure (``dynamic_type``). On the native OUTPUT path that closure is dead —
    the converter now returns a graphene-free ``NativeRelationField`` marker when
    no union is registered for the GFK (``registry.get_gfk_union`` is None), so the
    converter-level warning is NOT emitted on native. The mis-order DEGRADE
    semantics are preserved at the SCHEMA level instead: the native union injector
    (``types._compile_gfk_union_output_fields``) skips an unregistered union,
    leaving the flat ``GenericForeignKeyType`` field (verified by the S-rel-4
    schema-level GFK-union tests). This test therefore asserts the graphene-path
    warning contract on the graphene backend and the native-marker fallback on
    native.
    """
    from django_graphex.converter import _NATIVE_BACKEND
    from django_graphex.native.descriptors import NativeRelationField

    reg = Registry()
    _make_member_types(reg)

    # Build a sentinel union object that is NOT registered in ``reg`` to simulate
    # a mis-ordered declaration where get_gfk_union cannot find a registered
    # companion union. We declare gfk_unions pointing at a name the registry has
    # never seen by stripping it from the store after construction.
    members = _make_member_types(reg)
    union = _make_union(reg, members)

    class GfkCommentType(DjangoObjectType):
        class Meta:
            model = Track2GfkComment
            registry = reg
            gfk_unions = {"target": union}

    # Simulate mis-order: the union is not yet in the registry when the field is
    # converted (owner Meta declared before the union was registered).
    reg._union_types.pop(union._meta.name, None)

    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        converted = convert_django_field(_gfk_field(), registry=reg)

    if _NATIVE_BACKEND:
        # S-rel-4: an unregistered union -> the flat path returns the native
        # marker (the schema-level injector degrades to the flat type; the
        # converter-level warning is a dead graphene-closure artifact on native).
        assert isinstance(converted, NativeRelationField)
    else:
        field = _resolve_dynamic(converted)
        assert field.type is GenericForeignKeyType
        assert any(
            "gfk_union" in str(w.message).lower()
            or "union" in str(w.message).lower()
            for w in caught
        )
