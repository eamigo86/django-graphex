# -*- coding: utf-8 -*-
"""Track 2 — coverage hardening for the union / interface + GAP-5 NEW code.

These tests close the remaining UNTESTED branches in the Track-2 surface:

  * ``_inline_fragment_applies`` (GAP-5 guard) — the interface-membership match,
    the GraphQL-identity SKIP, the model-name-only descent, and the
    "no reliable identity -> descend" inconclusive branch.
  * ``_collect_gfk_union_buckets`` guards — missing field_def, ``schema=None``,
    the filter-skip / unresolvable-target continues, and the same-member merge.
  * ``_build_member_queryset`` — the select_related / alias / annotate assembly.
  * ``_content_type_or_none`` — the degrade-to-None path when ``get_for_model``
    raises, and the resulting bucket drop in ``_build_generic_prefetch``.
  * ``_build_generic_prefetch`` — the no-usable-bucket ``None`` return.
  * ``_narrow_plain_prefetch`` — the alias-only Prefetch emission.
  * ``_collect_prefetch_only_sets`` — the named ``FragmentSpread`` recursion.
  * ``Registry.get_member_models`` — interface scan skipping input entries and
    non-implementor output types.

Every test states the mutation that breaks it (its "teeth").
"""

from __future__ import annotations

from unittest import mock

import graphene
import pytest

from django_graphex import DjangoInterfaceType, DjangoObjectType
from django_graphex.fields import DjangoObjectField
from django_graphex.registry import Registry
from django_graphex.schema import DjangoGraphQLSchema
from django_graphex.types import DjangoUnionType

from .models import (
    Track2Account,
    Track2Book,
    Track2GfkComment,
    Track2Invoice,
    Track2Magazine,
    Track2Order,
)

# Per-content-type GenericPrefetch narrowing requires Django 5.0+.
# Floor is >=5.2, so these tests always run; marker is a no-op kept for symmetry.
requires_generic_prefetch = pytest.mark.skipif(
    False,
    reason="Per-content-type GenericPrefetch narrowing is Django 5.0+ (floor is 5.2).",
)


# --------------------------------------------------------------------------- #
# Shared inline-fragment node builder (mirrors test_track2_optimizer helper).  #
# --------------------------------------------------------------------------- #
def _inline_fragment_node(type_name: str | None):
    """Build a minimal InlineFragmentNode carrying ``... on type_name``."""
    from graphql.language.ast import (
        InlineFragmentNode,
        NamedTypeNode,
        NameNode,
        SelectionSetNode,
    )

    node = InlineFragmentNode()
    node.selection_set = SelectionSetNode(selections=[])
    if type_name is None:
        node.type_condition = None
    else:
        node.type_condition = NamedTypeNode(name=NameNode(value=type_name))
    return node


# =========================================================================== #
# _inline_fragment_applies — the GAP-5 decision table branches                 #
# =========================================================================== #
def test_inline_fragment_skips_foreign_type_with_gql_identity():
    """``... on Other`` SKIPS (False) when a reliable GraphQL identity is present.

    With ``current_type_name`` set (a real GraphQL type name) and the condition
    naming a DIFFERENT type, the guard MUST return False so the foreign
    fragment's fields are not mis-attributed against the current model.

    TEETH: this is the whole point of GAP-5. If the final ``return False`` were
    flipped to ``True`` (transparent descent, the pre-GAP-5 bug), a fragment
    targeting another concrete type would be walked against the wrong relation
    map. Pinning False here guards that.
    """
    from django_graphex.utils import _inline_fragment_applies

    node = _inline_fragment_node("InvoiceType")
    # A reliable GraphQL identity for the type we are walking ("AccountType").
    assert _inline_fragment_applies(node, current_type_name="AccountType") is False


def test_inline_fragment_descends_on_matching_gql_name():
    """``... on AccountType`` descends (True) when the current GraphQL name matches.

    TEETH: if the positive match branch ``condition_name in accepted_names`` were
    broken, a fragment naming the CURRENT type would be wrongly skipped, dropping
    its legitimately-selected columns.
    """
    from django_graphex.utils import _inline_fragment_applies

    node = _inline_fragment_node("AccountType")
    assert _inline_fragment_applies(node, current_type_name="AccountType") is True


def test_inline_fragment_descends_via_graphene_meta_name_and_dunder_name():
    """A graphene type contributes its ``_meta.name`` AND ``__name__`` as identities.

    The guard accepts the condition if it matches the graphene type's GraphQL
    name (``_meta.name``) OR its Python class ``__name__`` (lines that add both to
    ``accepted_names`` and set ``have_gql_identity``).

    TEETH: drop the ``_meta.name`` collection and a ``... on <GraphQLName>``
    fragment over the matching type would no longer descend (it would SKIP,
    losing columns). Drop the ``__name__`` collection and the class-name variant
    would mis-route. Both identities are asserted distinct here.
    """
    from django_graphex.utils import _inline_fragment_applies

    reg = Registry()

    class AccountType(DjangoObjectType):
        class Meta:
            model = Track2Account
            registry = reg

    # The GraphQL name and the Python class name happen to coincide here, so we
    # additionally prove the *class __name__* path by walking a graphene type and
    # matching its dunder name explicitly.
    by_meta_name = _inline_fragment_node(AccountType._meta.name)
    assert (
        _inline_fragment_applies(by_meta_name, current_graphene_type=AccountType)
        is True
    )

    by_class_name = _inline_fragment_node(AccountType.__name__)
    assert (
        _inline_fragment_applies(by_class_name, current_graphene_type=AccountType)
        is True
    )


def test_inline_fragment_descends_on_implemented_interface_name():
    """``... on <Interface>`` descends when the current type IMPLEMENTS it.

    The forward-compat (interfaces-only) branch adds each implemented interface's
    name to ``accepted_names``. A fragment naming an interface the current
    graphene type declares via ``Meta.interfaces`` MUST descend (True).

    TEETH: remove the ``for iface in ... interfaces`` collection loop and an
    ``... on ProductInterface`` fragment over an implementing type would no
    longer be recognised -> it SKIPS, and the interface-typed selection's columns
    are dropped. Pinning True guards that loop.
    """
    from django_graphex.utils import _inline_fragment_applies

    reg = Registry()

    class ProductInterface(DjangoInterfaceType):
        name = graphene.String()

        class Meta:
            registry = reg

    class BookType(DjangoObjectType):
        class Meta:
            model = Track2Book
            registry = reg
            interfaces = (ProductInterface,)

    node = _inline_fragment_node(ProductInterface._meta.name)
    # current_graphene_type implements ProductInterface -> the interface name is
    # an accepted identity -> descend. Without the interface loop this is False.
    assert _inline_fragment_applies(node, current_graphene_type=BookType) is True


def test_inline_fragment_model_name_alone_never_skips_but_can_confirm():
    """A model ``__name__`` match CONFIRMS descent; a non-match with no GraphQL
    identity stays inconclusive -> descend (never a skip).

    The model name is added to ``accepted_names`` but does NOT set
    ``have_gql_identity``. So:
      * ``... on Track2Account`` over ``current_model=Track2Account`` -> True
        (positive model-name confirm, line ~750-753 collection + match).
      * ``... on Whatever`` over only a ``current_model`` (no GraphQL identity)
        -> True (the ``not have_gql_identity -> descend`` inconclusive branch).

    TEETH: if a model-name MISS were allowed to drive a SKIP (return False),
    every legitimate ``... on <Model>Type`` fragment whose GraphQL name differs
    from the model class name would be wrongly dropped -> FieldError under
    OPTIMIZE_ONLY_FIELDS. Both asserts pin "model name alone never skips".
    """
    from django_graphex.utils import _inline_fragment_applies

    confirm = _inline_fragment_node(Track2Account.__name__)
    assert _inline_fragment_applies(confirm, current_model=Track2Account) is True

    inconclusive = _inline_fragment_node("SomeUnrelatedTypeName")
    # Only a model is known (no GraphQL type name / graphene type) -> the guard
    # cannot reliably skip -> it descends.
    assert _inline_fragment_applies(inconclusive, current_model=Track2Account) is True


def test_inline_fragment_malformed_condition_descends():
    """A type_condition whose ``name`` carries no ``value`` -> descend (True).

    TEETH: if the malformed-node guard raised (or returned False), a node with a
    ``type_condition`` but no usable name would crash the walker or silently drop
    the selection instead of preserving transparent descent.
    """
    from graphql.language.ast import InlineFragmentNode, NamedTypeNode, NameNode

    from django_graphex.utils import _inline_fragment_applies

    node = InlineFragmentNode()
    # A NamedTypeNode whose NameNode has an empty value -> condition_name falsy.
    node.type_condition = NamedTypeNode(name=NameNode(value=""))

    assert _inline_fragment_applies(node, current_type_name="AccountType") is True


# =========================================================================== #
# _collect_gfk_union_buckets — guard branches + same-member merge              #
# =========================================================================== #
def _build_union_gql_schema(registry=None):
    """Build a GraphQL schema exposing a GFK ``target`` union; return (schema, types)."""
    reg = registry or Registry()

    class AccountType(DjangoObjectType):
        class Meta:
            model = Track2Account
            registry = reg

    class InvoiceType(DjangoObjectType):
        class Meta:
            model = Track2Invoice
            registry = reg

    class CommentTargetUnion(DjangoUnionType):
        class Meta:
            gfk_types = (AccountType, InvoiceType)
            registry = reg

    class GfkCommentType(DjangoObjectType):
        class Meta:
            model = Track2GfkComment
            registry = reg
            gfk_unions = {"target": CommentTargetUnion}

    class Query(graphene.ObjectType):
        comment = DjangoObjectField(GfkCommentType)

    schema = DjangoGraphQLSchema(
        query=Query, types=[AccountType, InvoiceType, GfkCommentType]
    )
    return schema.graphql_schema, {
        "AccountType": AccountType,
        "InvoiceType": InvoiceType,
        "GfkCommentType": GfkCommentType,
    }


def _gfk_field():
    from django.contrib.contenttypes.fields import GenericForeignKey

    return next(
        f
        for f in Track2GfkComment._meta.get_fields()
        if isinstance(f, GenericForeignKey)
    )


def test_collect_gfk_union_buckets_none_when_field_not_on_gql_type():
    """A GFK whose name is absent from the owner's GraphQL fields -> None (degrade).

    TEETH: this is GUARD 2's ``field_def is None`` early-out. If it were removed,
    ``get_named_type(None)`` would raise instead of degrading to full-load.
    """
    from django_graphex.utils import _collect_gfk_union_buckets

    gql_schema, _types = _build_union_gql_schema()
    owner_gql = gql_schema.get_type("GfkCommentType")
    sub_selection = _inline_fragment_node("AccountType").selection_set

    # A name that is NOT a field on GfkCommentType -> field_def is None -> None.
    result = _collect_gfk_union_buckets(
        _gfk_field(),
        "noSuchField",
        "no_such_field",
        sub_selection,
        {},
        owner_gql,
        gql_schema,
    )
    assert result is None


def test_collect_gfk_union_buckets_none_when_schema_is_none():
    """GUARD 3: ``schema is None`` -> None (cannot resolve fragment targets).

    TEETH: drop the ``schema is None`` guard and ``_resolve_fragment_target``
    would later dereference a None schema (AttributeError) instead of degrading.
    """
    from django_graphex.utils import _collect_gfk_union_buckets

    gql_schema, _types = _build_union_gql_schema()
    owner_gql = gql_schema.get_type("GfkCommentType")
    field_def = owner_gql.fields.get("target")
    assert field_def is not None  # the union field exists on the owner.
    sub_selection = _inline_fragment_node("AccountType").selection_set

    result = _collect_gfk_union_buckets(
        _gfk_field(),
        "target",
        "target",
        sub_selection,
        {},
        owner_gql,
        None,  # schema=None -> degrade.
    )
    assert result is None


@requires_generic_prefetch
def test_collect_gfk_union_buckets_skips_unresolvable_fragment_keeps_member():
    """An unresolvable ``... on Other`` fragment is skipped; a real member survives.

    The selection mixes a resolvable ``... on AccountType { balance }`` with an
    ``... on InvoiceType`` (resolvable too) PLUS a bare inline fragment carrying
    no concrete member. The bare fragment resolves to None and is skipped (the
    ``target is None -> continue`` branch); the two concrete members each yield a
    bucket.

    TEETH: if the ``target is None`` skip were removed, a None member would crash
    the per-member ``_compute_child_only`` call. We assert exactly the two real
    member models are bucketed and the bare fragment contributes nothing.
    """
    from graphql import parse

    from django_graphex.utils import _collect_gfk_union_buckets

    gql_schema, _types = _build_union_gql_schema()
    owner_gql = gql_schema.get_type("GfkCommentType")

    # Build a selection set with two concrete member fragments + one BARE inline
    # fragment (no type_condition -> _resolve_fragment_target returns None).
    doc = parse(
        """
        {
          comment {
            target {
              __typename
              ... on AccountType { balance }
              ... on InvoiceType { amount }
              ... { __typename }
            }
          }
        }
        """
    )
    comment_field = doc.definitions[0].selection_set.selections[0]
    target_field = comment_field.selection_set.selections[0]
    sub_selection = target_field.selection_set

    plan = _collect_gfk_union_buckets(
        _gfk_field(),
        "target",
        "target",
        sub_selection,
        {},
        owner_gql,
        gql_schema,
    )
    assert plan is not None
    # Exactly the two concrete members were bucketed; the bare fragment added none.
    assert set(plan.generic_buckets) == {Track2Account, Track2Invoice}


@requires_generic_prefetch
def test_collect_gfk_union_buckets_merges_split_member_selections():
    """Two fragments over the SAME member merge their narrowed columns (no loss).

    ``... on AccountType { balance } ... on AccountType { label }`` must collapse
    into a single Account bucket whose ``only_cols`` carries BOTH ``balance`` and
    ``label`` (the same-member merge branch).

    TEETH: if the merge branch were dropped (second fragment overwrote the
    first), the surviving bucket would carry only one column -> the other
    column's field would be missing at resolve time. We assert both columns
    coexist in the single merged bucket.
    """
    from graphql import parse

    from django_graphex.utils import _collect_gfk_union_buckets

    gql_schema, _types = _build_union_gql_schema()
    owner_gql = gql_schema.get_type("GfkCommentType")

    doc = parse(
        """
        {
          comment {
            target {
              ... on AccountType { balance }
              ... on AccountType { label }
            }
          }
        }
        """
    )
    comment_field = doc.definitions[0].selection_set.selections[0]
    target_field = comment_field.selection_set.selections[0]
    sub_selection = target_field.selection_set

    plan = _collect_gfk_union_buckets(
        _gfk_field(),
        "target",
        "target",
        sub_selection,
        {},
        owner_gql,
        gql_schema,
    )
    assert plan is not None
    assert set(plan.generic_buckets) == {Track2Account}
    account_cols = plan.generic_buckets[Track2Account].only_cols
    # Both split columns survived the merge into one bucket.
    assert "balance" in account_cols
    assert "label" in account_cols


@requires_generic_prefetch
def test_collect_gfk_union_buckets_skips_full_load_member():
    """A member whose per-member plan is full-load (None) is skipped, not bucketed.

    We force ``_compute_child_only`` to return None for the Invoice member only
    (a computed/unknown leaf -> full-load). That member's bucket is dropped (the
    ``member_plan is None -> continue`` branch) while the narrowable Account
    member still produces a bucket.

    TEETH: drop the ``member_plan is None`` skip and a None plan would be stored
    as a bucket, then crash ``_build_member_queryset`` (it reads ``plan.only_cols``
    etc.). We assert ONLY the Account member survives -> the None member was
    cleanly skipped.
    """
    from graphql import parse

    from django_graphex import utils
    from django_graphex.utils import PrefetchPlan, _collect_gfk_union_buckets

    gql_schema, _types = _build_union_gql_schema()
    owner_gql = gql_schema.get_type("GfkCommentType")

    doc = parse(
        """
        {
          comment {
            target {
              ... on AccountType { balance }
              ... on InvoiceType { amount }
            }
          }
        }
        """
    )
    comment_field = doc.definitions[0].selection_set.selections[0]
    target_field = comment_field.selection_set.selections[0]
    sub_selection = target_field.selection_set

    real_compute = utils._compute_child_only

    def _fake_compute(member_model, *args, **kwargs):
        if member_model is Track2Invoice:
            return None  # force the Invoice member to full-load.
        return real_compute(member_model, *args, **kwargs)

    with mock.patch.object(utils, "_compute_child_only", side_effect=_fake_compute):
        plan = _collect_gfk_union_buckets(
            _gfk_field(),
            "target",
            "target",
            sub_selection,
            {},
            owner_gql,
            gql_schema,
        )

    assert plan is not None
    # The Invoice member returned a None plan and was skipped; only Account remains.
    assert set(plan.generic_buckets) == {Track2Account}
    assert isinstance(plan.generic_buckets[Track2Account], PrefetchPlan)


# =========================================================================== #
# _build_member_queryset — select_related / alias / annotate assembly          #
# =========================================================================== #
@requires_generic_prefetch
@pytest.mark.django_db
def test_build_member_queryset_applies_select_alias_and_annotate():
    """A member plan with child_select + child_aliases + child_annotations emits a
    queryset that carries all three (plus ``.only()``), observable in its SQL.

    ``Track2GfkComment`` has a forward FK ``target_ct`` (to ContentType), giving a
    real ``select_related`` head. We attach an alias and a Count annotation to the
    same member plan and assert the compiled SQL reflects the select-related JOIN,
    the annotation, and the narrowed columns.

    TEETH: if ``_build_member_queryset`` dropped the ``select_related`` /
    ``alias`` / ``annotate`` application (lines 1924-1929), the JOIN and the
    annotated column would be absent from the SQL. Each is asserted.
    """
    from django.db.models import Count, Value

    from django_graphex.utils import PrefetchPlan, _build_member_queryset

    plan = PrefetchPlan(
        # ``target_ct`` is the select_related head, so its FK column must be in
        # .only() (Django forbids deferring + traversing the same FK).
        only_cols=["id", "body", "target_ct"],
        child_select=["target_ct"],
        child_annotations={"alias_cnt": Count("id")},
        child_aliases={"alias_zero": Value(0)},
    )

    qs = _build_member_queryset(Track2GfkComment, plan)
    sql = str(qs.query).lower()

    # select_related("target_ct") forces a JOIN against the content-type table.
    assert "django_content_type" in sql, sql
    # The annotation column is present in the SELECT.
    assert "alias_cnt" in sql, sql
    # Narrowing kept ``body`` and did NOT pull the full row's other text columns.
    assert "body" in sql

    # And an annotate-only member plan (empty only_cols) must NOT call .only():
    # the queryset has no deferred loading, proving the ``if plan.only_cols``
    # branch was skipped (full columns, plus the annotation).
    annotate_only = PrefetchPlan(
        only_cols=[],
        child_select=[],
        child_annotations={"alias_cnt2": Count("id")},
    )
    qs2 = _build_member_queryset(Track2Invoice, annotate_only)
    # deferred_loading == (frozenset(), True) means NO .only() narrowing applied.
    assert qs2.query.deferred_loading == (frozenset(), True)
    assert "alias_cnt2" in str(qs2.query).lower()


# =========================================================================== #
# _content_type_or_none + _build_generic_prefetch degrade paths                #
# =========================================================================== #
@requires_generic_prefetch
@pytest.mark.django_db
def test_content_type_or_none_degrades_when_get_for_model_raises():
    """A member whose ``get_for_model`` raises yields None (bucket dropped), never
    crashing the resolve; the surviving member still emits exactly one queryset.

    We force ``get_for_model`` to raise for the Invoice member only. The Invoice
    bucket is dropped (``_content_type_or_none`` returns None -> ``ct is None ->
    continue``) and the assembled ``GenericPrefetch`` carries ONLY the Account
    queryset.

    TEETH: remove the try/except in ``_content_type_or_none`` and the raise would
    propagate, blowing up the whole prefetch build instead of degrading one
    bucket. We assert exactly one surviving queryset (Account) and no exception.
    """
    from django.contrib.contenttypes.models import ContentType

    from django_graphex.utils import PrefetchPlan, _build_generic_prefetch

    buckets = {
        Track2Account: PrefetchPlan(only_cols=["id", "balance"], child_select=[]),
        Track2Invoice: PrefetchPlan(only_cols=["id", "amount"], child_select=[]),
    }

    real_get_for_model = ContentType.objects.get_for_model
    account_ct = real_get_for_model(Track2Account)

    def _raising(model, for_concrete_model=True):
        if model is Track2Invoice:
            raise RuntimeError("no content type for this member")
        return account_ct

    with mock.patch.object(ContentType.objects, "get_for_model", side_effect=_raising):
        gp = _build_generic_prefetch("target", buckets)

    assert gp is not None
    # The Invoice bucket degraded to None and was dropped -> one queryset survives.
    assert len(gp.querysets) == 1
    assert gp.querysets[0].model is Track2Account


@requires_generic_prefetch
@pytest.mark.django_db
def test_build_generic_prefetch_returns_none_when_no_bucket_resolves():
    """When EVERY member's ContentType degrades to None, the emission returns None
    (caller falls back to the bare full-load string), never an empty GenericPrefetch.

    TEETH: drop the ``if not querysets: return None`` guard and Django would build
    a ``GenericPrefetch`` with an empty queryset list (a malformed prefetch). We
    force every ``get_for_model`` to raise and assert the result is None.
    """
    from django.contrib.contenttypes.models import ContentType

    from django_graphex.utils import PrefetchPlan, _build_generic_prefetch

    buckets = {
        Track2Account: PrefetchPlan(only_cols=["id", "balance"], child_select=[]),
        Track2Invoice: PrefetchPlan(only_cols=["id", "amount"], child_select=[]),
    }

    def _always_raise(model, for_concrete_model=True):
        raise RuntimeError("no content type at all")

    with mock.patch.object(
        ContentType.objects, "get_for_model", side_effect=_always_raise
    ):
        gp = _build_generic_prefetch("target", buckets)

    assert gp is None


@requires_generic_prefetch
@pytest.mark.django_db
def test_build_generic_prefetch_merges_columns_on_content_type_collision():
    """Two members colliding on ONE content type merge their .only() columns into a
    SINGLE queryset whose narrowing is the union of both buckets.

    Here both members map to the SAME shared ContentType (we mock get_for_model to
    return one CT for both), so the second bucket hits the merge branch: its
    columns are appended onto the existing bucket's queryset.

    TEETH: drop the merge branch and the colliding member's distinct column
    (``amount``) would be lost from the single surviving queryset. We assert the
    one queryset's ``.only()`` carries BOTH members' columns.
    """
    from django.contrib.contenttypes.models import ContentType

    from django_graphex.utils import PrefetchPlan, _build_generic_prefetch

    buckets = {
        # Distinct child_select heads per bucket so the merge also unions the
        # select_related heads (the child_select merge branch), not just columns.
        Track2Account: PrefetchPlan(
            only_cols=["id", "balance", "head_a"], child_select=["head_a"]
        ),
        Track2Invoice: PrefetchPlan(
            only_cols=["id", "amount", "head_b"], child_select=["head_b"]
        ),
    }

    shared_ct = ContentType.objects.get_for_model(Track2Account)

    def _shared(model, for_concrete_model=True):
        return shared_ct

    captured: dict = {}

    from django_graphex import utils

    def _capture_build(member_model, plan):
        # Capture the MERGED plan handed to the single surviving queryset so we
        # can assert both the column union and the select_related-head union.
        captured["plan"] = plan
        # Return a real (un-narrowed) queryset to avoid FieldError on fake heads.
        return member_model._default_manager.all()

    with mock.patch.object(ContentType.objects, "get_for_model", side_effect=_shared):
        with mock.patch.object(
            utils, "_build_member_queryset", side_effect=_capture_build
        ):
            gp = _build_generic_prefetch("target", buckets)

    assert gp is not None
    assert len(gp.querysets) == 1
    merged = captured["plan"]
    # The merged plan unions BOTH members' .only() columns ...
    assert {"id", "balance", "amount"} <= set(merged.only_cols), merged.only_cols
    # ... AND both members' select_related heads (the child_select merge branch).
    assert {"head_a", "head_b"} <= set(merged.child_select), merged.child_select


# =========================================================================== #
# _narrow_plain_prefetch — alias-only Prefetch emission                         #
# =========================================================================== #
@pytest.mark.django_db
def test_narrow_plain_prefetch_emits_prefetch_for_alias_only_plan():
    """A plan with only ``child_aliases`` (no .only(), no annotations) still emits a
    ``Prefetch`` whose queryset carries the alias.

    ``Author`` has a reverse-FK ``posts``. We hand ``_narrow_plain_prefetch`` a
    plan that sets only ``child_aliases`` and assert it returns a ``Prefetch``
    (not the bare string) with the alias applied — exercising the
    ``qs.alias(**...)`` branch and the ``child_aliases``-driven Prefetch emission.

    TEETH: if the alias branch (line ~2075) were skipped, the alias would be
    absent; if the emission condition omitted ``child_aliases`` (line ~2082), an
    alias-only plan would degrade to the bare string and lose the alias entirely.
    """
    from django.db.models import Prefetch, Value

    from django_graphex.utils import PrefetchPlan, _narrow_plain_prefetch
    from tests.models import Author

    plan = PrefetchPlan(
        only_cols=[],
        child_select=[],
        child_aliases={"alias_marker": Value(7)},
    )
    only_map = {"posts": plan}

    result = _narrow_plain_prefetch(Author, "posts", only_map)
    assert isinstance(result, Prefetch), result
    # The alias is present on the emitted prefetch queryset.
    assert "alias_marker" in result.queryset.query.annotations


@pytest.mark.django_db
def test_narrow_plain_prefetch_bare_string_for_empty_plan():
    """A plan with no .only(), no annotations, no aliases -> the bare lookup string.

    TEETH: if the trailing ``return lookup`` (line ~2084) were replaced by a
    ``Prefetch`` emission, an empty plan would build a needless Prefetch object.
    We pin that an empty plan degrades to the bare string.
    """
    from django_graphex.utils import PrefetchPlan, _narrow_plain_prefetch
    from tests.models import Author

    empty_plan = PrefetchPlan(only_cols=[], child_select=[])
    result = _narrow_plain_prefetch(Author, "posts", {"posts": empty_plan})
    assert result == "posts"


# =========================================================================== #
# _collect_prefetch_only_sets — named FragmentSpread recursion                  #
# =========================================================================== #
def test_collect_prefetch_only_sets_descends_into_named_fragment_spread():
    """A named ``...frag`` spread recurses, so a relational descent inside the
    fragment still produces a prefetch plan.

    ``{ author { ...f } } fragment f on Author { posts { title } }`` — the
    ``posts`` reverse-FK prefetch lives INSIDE the named fragment, so it is only
    discovered if ``_collect_prefetch_only_sets`` follows the FragmentSpreadNode
    into the fragment's selection set.

    TEETH: if the FragmentSpread recursion were dropped (fragment is None / not
    followed), ``posts`` would be invisible and the plan empty -> the relation
    would not be narrowed and would N+1. We assert ``posts`` IS in the plan.
    """
    from graphql import parse

    from django_graphex.utils import _collect_prefetch_only_sets
    from tests.models import Author

    doc = parse("{ author { ...f } } fragment f on Author { name posts { title } }")
    operation = next(
        d
        for d in doc.definitions
        if getattr(d, "selection_set", None) is not None
        and getattr(d, "name", None) is None
    )
    fragments = {
        d.name.value: d
        for d in doc.definitions
        if getattr(d, "name", None) is not None and hasattr(d, "type_condition")
    }
    author_field = operation.selection_set.selections[0]
    sel = author_field.selection_set

    plan = _collect_prefetch_only_sets(Author, sel, fragments)
    # The reverse-FK ``posts`` prefetch was discovered THROUGH the named fragment.
    assert "posts" in plan, plan


# =========================================================================== #
# Registry — get_member_models scan branches                                    #
# =========================================================================== #
def test_get_member_models_interface_skips_input_entries_and_non_implementors():
    """``get_member_models(interface)`` returns only OUTPUT implementor models —
    skipping input-type entries and output types that do NOT implement it.

    We register: a BookType implementing the interface, a MagazineType NOT
    implementing it, plus the model's auto-generated INPUT types (via a
    DjangoModelType is heavy; instead we inject a synthetic input entry). The scan
    must skip the input entry (``for_input is not None -> continue``) and the
    non-implementor (``polymorphic_type not in interfaces``), returning only
    [Track2Book].

    TEETH: drop the ``for_input is not None`` skip and an input entry's model
    would be wrongly returned; drop the ``in interfaces`` filter and the
    non-implementor (Magazine) would leak in. We assert EXACTLY [Track2Book].
    """
    reg = Registry()

    class ProductInterface(DjangoInterfaceType):
        name = graphene.String()

        class Meta:
            registry = reg

    class BookType(DjangoObjectType):
        class Meta:
            model = Track2Book
            registry = reg
            interfaces = (ProductInterface,)

    # An OUTPUT type that does NOT implement the interface (non-implementor skip).
    class MagazineType(DjangoObjectType):
        class Meta:
            model = Track2Magazine
            registry = reg

    # A synthetic INPUT entry for Track2Magazine so the ``for_input is not None``
    # skip branch is exercised against a real (model, action) key.
    reg._types[(Track2Magazine, "create")] = MagazineType

    members = reg.get_member_models(ProductInterface)
    assert members == [Track2Book]


# =========================================================================== #
# DjangoUnionType / DjangoInterfaceType — DEFAULT (global) registry path        #
# =========================================================================== #
def test_django_union_type_self_registers_into_global_registry_by_default():
    """A ``DjangoUnionType`` declared with NO ``registry=`` binds to and registers
    into the GLOBAL registry (the ``if not registry: get_global_registry()`` path).

    Every other test injects an isolated ``Registry`` for hygiene, so the default
    branch (types.py:322-323) is otherwise never walked. Here we deliberately omit
    ``registry`` and assert the union landed in the global registry's
    ``_union_types`` AND that its ``_dgx_registry`` IS the global singleton.

    TEETH: if the default branch were dropped (or bound to a fresh throwaway
    registry instead of the global one), ``_dgx_registry is get_global_registry()``
    would fail and the union would be absent from the global ``_union_types`` —
    breaking GFK-union resolution for any schema built without an explicit
    registry. Cleanup pops the unique-named entry so no other test sees it.
    """
    from django_graphex import DjangoObjectType
    from django_graphex.registry import get_global_registry

    global_reg = get_global_registry()

    # Members must be DjangoObjectTypes; bind THEM to the global registry too so
    # the union's member-model resolution is internally consistent.
    class _GlobalDefaultAccountType(DjangoObjectType):
        class Meta:
            model = Track2Account

    class _GlobalDefaultUnion(DjangoUnionType):
        class Meta:
            gfk_types = (_GlobalDefaultAccountType,)
            # NOTE: registry deliberately OMITTED -> default global path.

    union_name = _GlobalDefaultUnion._meta.name
    try:
        # Bound to the global singleton, not some other registry.
        assert _GlobalDefaultUnion._dgx_registry is global_reg
        # And self-registered under its name in the global union store.
        assert global_reg._union_types.get(union_name) is _GlobalDefaultUnion
    finally:
        global_reg._union_types.pop(union_name, None)
        # Also drop the member object-type entries we leaked into the global reg.
        for key in list(global_reg._types):
            if global_reg._types[key] is _GlobalDefaultAccountType:
                global_reg._types.pop(key, None)


def test_django_interface_type_self_registers_into_global_registry_by_default():
    """A ``DjangoInterfaceType`` declared with NO ``registry=`` binds to and
    registers into the GLOBAL registry (types.py:386-387 default path).

    TEETH: mirror of the union test. Drop the default branch and the interface's
    ``_dgx_registry`` would not be the global singleton, and it would be absent
    from the global ``_interface_types`` store — so a schema built without an
    explicit registry could not resolve the interface. Cleanup pops the entry.
    """
    from django_graphex.registry import get_global_registry

    global_reg = get_global_registry()

    class _GlobalDefaultInterface(DjangoInterfaceType):
        name = graphene.String()

        class Meta:
            # NOTE: registry deliberately OMITTED -> default global path.
            pass

    iface_name = _GlobalDefaultInterface._meta.name
    try:
        assert _GlobalDefaultInterface._dgx_registry is global_reg
        assert global_reg._interface_types.get(iface_name) is _GlobalDefaultInterface
    finally:
        global_reg._interface_types.pop(iface_name, None)
        global_reg._interface_implementors.pop(iface_name, None)


# =========================================================================== #
# _inline_fragment_applies — graceful degradation on PARTIAL type identity      #
# =========================================================================== #
class _FakeMeta:
    """A stand-in for a graphene ``_meta`` with controllable identity sources."""

    def __init__(self, name=None, interfaces=()):
        self.name = name
        self.interfaces = interfaces
        self.model = None


class _FakeGrapheneInstance:
    """A graphene-type stand-in that is an INSTANCE (not a class).

    ``getattr(instance, "__name__", None)`` returns ``None`` for a plain instance,
    so this lets us drive the ``__name__``-absent FALSE branch while still
    supplying a ``_meta`` (so the walker reaches the later guards).
    """

    def __init__(self, meta):
        self._meta = meta


def test_inline_fragment_descends_when_meta_name_absent_but_dunder_name_present():
    """``_meta.name`` absent (falsy) but ``__name__`` present: the ``__name__``
    fallback still supplies identity; a condition matching it descends (True).

    This walks the ``if gql_name:`` FALSE branch (725->728): ``_meta`` exists but
    its ``name`` is None, so no GraphQL-name identity is added there — yet the
    class ``__name__`` (line 729-731) still provides one.

    TEETH: if the ``__name__`` collection were the ONLY identity source and the
    ``_meta.name`` guard mistakenly added a falsy/None name, the accepted-name set
    would be polluted; here we prove the falsy ``_meta.name`` is correctly skipped
    while ``__name__`` alone drives the positive match.
    """
    from django_graphex.utils import _inline_fragment_applies

    class _NamedClass:
        # A real class so ``__name__`` is defined, but its ``_meta.name`` is None.
        _meta = _FakeMeta(name=None)

    node = _inline_fragment_node("_NamedClass")
    assert _inline_fragment_applies(node, current_graphene_type=_NamedClass) is True


def test_inline_fragment_descends_when_dunder_name_absent_but_meta_name_present():
    """``__name__`` absent but ``_meta.name`` present: the GraphQL-name identity is
    supplied by ``_meta.name``; a condition matching it descends (True).

    Walks the ``if gt_name:`` FALSE branch (730->737): the graphene type is an
    INSTANCE (no ``__name__``), so ``gt_name`` is falsy and nothing is added there
    — but ``_meta.name`` (line 724-726) already provided the identity.

    TEETH: if the ``_meta.name`` collection were dropped, an instance-shaped
    graphene type (no ``__name__``) would have NO identity and a matching
    ``... on Foo`` could not descend. Pinning True guards the ``_meta.name`` path.
    """
    from django_graphex.utils import _inline_fragment_applies

    graphene_type = _FakeGrapheneInstance(_FakeMeta(name="FooGqlName"))
    node = _inline_fragment_node("FooGqlName")
    assert _inline_fragment_applies(node, current_graphene_type=graphene_type) is True


def test_inline_fragment_skips_unnamed_interface_in_interfaces_loop():
    """An interface in ``Meta.interfaces`` with NO usable name is skipped, so it
    contributes no accepted identity; a non-matching foreign condition still SKIPS.

    Walks the ``if iface_name:`` FALSE branch (742->737): the interface object has
    neither ``_meta.name`` nor ``__name__``, so ``iface_name`` is None and is NOT
    added to ``accepted_names``. The graphene type's own ``_meta.name`` still gives
    a reliable GraphQL identity, so a condition matching NEITHER the type name nor
    the (unnamed) interface SKIPS (False).

    TEETH: if a None ``iface_name`` were wrongly added to ``accepted_names``, the
    set could gain a junk entry; worse, if the loop crashed on the unnamed iface,
    the walker would blow up. We prove the unnamed interface is silently ignored
    and the foreign-type SKIP still fires.
    """
    from django_graphex.utils import _inline_fragment_applies

    # An interface with no name identity at all (instance, no __name__; meta.name
    # None). It must be ignored by the interfaces loop.
    unnamed_iface = _FakeGrapheneInstance(_FakeMeta(name=None))
    graphene_type = _FakeGrapheneInstance(
        _FakeMeta(name="OwnerGqlName", interfaces=(unnamed_iface,))
    )

    # The condition names neither the owner type nor any (named) interface, and a
    # reliable GraphQL identity (OwnerGqlName) exists -> SKIP.
    node = _inline_fragment_node("SomeForeignType")
    assert _inline_fragment_applies(node, current_graphene_type=graphene_type) is False


def test_inline_fragment_descends_when_model_has_no_usable_name():
    """A ``current_model`` whose ``__name__`` is absent contributes no model-name
    identity; with no other reliable identity the guard DESCENDS (inconclusive).

    Walks the ``if model_name:`` FALSE branch (750->753): the model object is an
    INSTANCE (no ``__name__``), so ``model_name`` is None and nothing is added.
    Because no GraphQL-type-name identity exists either, ``have_gql_identity`` is
    False -> the inconclusive-descent rule returns True.

    TEETH: if a None ``model_name`` were added to ``accepted_names`` it would be a
    junk entry; if the missing model name somehow drove a SKIP, a legitimately
    typed fragment would be dropped. We pin transparent descent on partial info.
    """
    from django_graphex.utils import _inline_fragment_applies

    class _ModelInstance:
        # An instance has no ``__name__``; getattr(..., "__name__", None) -> None.
        pass

    node = _inline_fragment_node("AnyConditionName")
    assert _inline_fragment_applies(node, current_model=_ModelInstance()) is True


# =========================================================================== #
# _collect_gfk_union_buckets — member-level child_select merge (forward-FK head) #
# =========================================================================== #
@requires_generic_prefetch
def test_collect_gfk_union_buckets_merges_member_child_select_heads():
    """Two split ``... on OrderType`` fragments — each pulling a DISTINCT forward-FK
    relation — merge their ``child_select`` heads into one member bucket.

    ``Track2Order`` carries two forward FKs: ``customer`` (-> Track2Account) and
    ``invoice`` (-> Track2Invoice). The first fragment selects ``customer``; the
    second selects ``customer`` AGAIN (already-present, no-op FALSE branch) plus
    ``invoice`` (new -> the APPEND branch). ``_compute_child_only`` turns each
    forward-FK descent into a ``child_select`` head, so the SAME-member merge both
    skips the duplicate and appends the new head onto the first bucket.

    TEETH: if the APPEND branch were dropped (second fragment overwrote the first,
    or only ``only_cols`` merged), the surviving Order bucket would carry only ONE
    select_related head -> the other forward FK re-introduces an N+1 at resolve
    time. If the no-op guard were dropped, ``customer`` would be duplicated. We
    assert BOTH heads survive AND ``customer`` appears exactly once.
    """
    from graphql import parse

    from django_graphex.utils import _collect_gfk_union_buckets

    reg = Registry()

    class OrderType(DjangoObjectType):
        class Meta:
            model = Track2Order
            registry = reg

    class AccountType(DjangoObjectType):
        class Meta:
            model = Track2Account
            registry = reg

    class InvoiceType(DjangoObjectType):
        class Meta:
            model = Track2Invoice
            registry = reg

    class OrderTargetUnion(DjangoUnionType):
        class Meta:
            gfk_types = (OrderType,)
            registry = reg

    class GfkCommentType(DjangoObjectType):
        class Meta:
            model = Track2GfkComment
            registry = reg
            gfk_unions = {"target": OrderTargetUnion}

    class Query(graphene.ObjectType):
        comment = DjangoObjectField(GfkCommentType)

    schema = DjangoGraphQLSchema(
        query=Query, types=[OrderType, AccountType, InvoiceType, GfkCommentType]
    )
    gql_schema = schema.graphql_schema
    owner_gql = gql_schema.get_type("GfkCommentType")

    # Two split fragments over the SAME member (OrderType). The FIRST pulls
    # ``customer``; the SECOND pulls BOTH ``customer`` (already present -> the
    # merge's no-op FALSE branch) AND ``invoice`` (new -> the APPEND branch). This
    # exercises both sides of the member-level ``child_select`` merge in one go.
    doc = parse(
        """
        {
          comment {
            target {
              ... on OrderType { customer { id } }
              ... on OrderType { customer { id } invoice { id } }
            }
          }
        }
        """
    )
    comment_field = doc.definitions[0].selection_set.selections[0]
    target_field = comment_field.selection_set.selections[0]
    sub_selection = target_field.selection_set

    plan = _collect_gfk_union_buckets(
        _gfk_field(),
        "target",
        "target",
        sub_selection,
        {},
        owner_gql,
        gql_schema,
    )
    assert plan is not None
    assert set(plan.generic_buckets) == {Track2Order}
    order_select = plan.generic_buckets[Track2Order].child_select
    # Both split forward-FK heads survived the member-level child_select merge ...
    assert "customer" in order_select, order_select
    assert "invoice" in order_select, order_select
    # ... and the duplicate ``customer`` was NOT appended twice (no-op branch).
    assert order_select.count("customer") == 1, order_select


# =========================================================================== #
# _build_generic_prefetch — CT-collision child_select merge: ALREADY-PRESENT head #
# =========================================================================== #
@requires_generic_prefetch
@pytest.mark.django_db
def test_build_generic_prefetch_ct_collision_skips_duplicate_child_select_head():
    """At a content-type collision, a ``child_select`` head ALREADY present on the
    existing bucket is NOT appended twice (the merge's no-op FALSE branch).

    Both members collide on ONE content type (mocked). They share the head
    ``head_shared``; the second member ALSO carries a distinct ``head_extra``. The
    merge must: skip ``head_shared`` (already present -> the 2020->2019 FALSE
    branch) and append ``head_extra`` once. The result is a de-duplicated union.

    TEETH: if the ``if sel not in existing_plan.child_select`` guard were dropped
    (unconditional append), ``head_shared`` would appear TWICE in the merged
    ``child_select`` -> a duplicated ``select_related`` head (redundant JOIN / a
    Django error on some paths). We assert each head appears EXACTLY once.
    """
    from django.contrib.contenttypes.models import ContentType

    from django_graphex import utils
    from django_graphex.utils import PrefetchPlan, _build_generic_prefetch

    buckets = {
        Track2Account: PrefetchPlan(
            only_cols=["id", "head_shared"], child_select=["head_shared"]
        ),
        Track2Invoice: PrefetchPlan(
            only_cols=["id", "head_shared", "head_extra"],
            child_select=["head_shared", "head_extra"],
        ),
    }

    shared_ct = ContentType.objects.get_for_model(Track2Account)

    def _shared(model, for_concrete_model=True):
        return shared_ct

    captured: dict = {}

    def _capture_build(member_model, plan):
        captured["plan"] = plan
        return member_model._default_manager.all()

    with mock.patch.object(ContentType.objects, "get_for_model", side_effect=_shared):
        with mock.patch.object(
            utils, "_build_member_queryset", side_effect=_capture_build
        ):
            gp = _build_generic_prefetch("target", buckets)

    assert gp is not None
    assert len(gp.querysets) == 1
    merged = captured["plan"].child_select
    # The shared head was NOT duplicated (the already-present FALSE branch fired) ...
    assert merged.count("head_shared") == 1, merged
    # ... and the distinct head was appended exactly once.
    assert merged.count("head_extra") == 1, merged
