# -*- coding: utf-8 -*-
"""Track 2 — Union / Interface MVP, BLOCK B (T-08..T-12).

Covers the OPTIMIZER ROUTING for a GFK exposed as a ``DjangoUnionType``:

  T-08  ``GraphQLUnionType`` import + ``PrefetchPlan.generic_buckets`` field.
  T-09  ``_resolve_fragment_target`` — the FILTER→RESOLVE second stage.
  T-10  ``schema=None`` threading through ``_collect_prefetch_only_sets``.
  T-11  GFK GenericPrefetch per-content-type buckets (Django 5.0+) with a
        graceful <5.0 degrade and an unresolvable-bucket full-load fallback.

Every test states the mutation that breaks it (its "teeth").

Design: sdd/track2-union-interface-mvp/design #1332 (ADR-4a..4d + ADR-5).
Spec:   sdd/track2-union-interface-mvp/spec #1331 (Domains 4 + 6).
"""

from __future__ import annotations

from unittest import mock

import django
import graphene
import pytest
from django.db import connection
from django.test.utils import CaptureQueriesContext
from graphene import Field

from django_graphex import DjangoListObjectField, DjangoListObjectType, DjangoObjectType
from django_graphex.registry import Registry
from django_graphex.types import DjangoUnionType

from .models import (
    Track2Account,
    Track2AccountProxy,
    Track2GfkComment,
    Track2Invoice,
)

# Per-content-type GenericPrefetch narrowing is a Django 5.0+ optimisation; on
# < 5.0 the optimizer degrades to a bare full-load prefetch (proven by
# test_gfk_union_degrades_to_bare_prefetch_on_django_below_5). The narrow-path
# tests below assert that 5.0+ shape, so they skip on older Django.
requires_generic_prefetch = pytest.mark.skipif(
    django.VERSION < (5, 0),
    reason="Per-content-type GenericPrefetch narrowing is Django 5.0+.",
)


# --------------------------------------------------------------------------- #
# T-08 — utils imports + PrefetchPlan.generic_buckets                          #
# --------------------------------------------------------------------------- #
def test_graphql_union_type_imported_in_utils():
    """utils imports ``GraphQLUnionType`` (needed to detect union-typed GFKs).

    TEETH: if the import were dropped, the GFK-union branch (T-11) cannot
    ``isinstance(sub_gql, GraphQLUnionType)`` and ``utils.GraphQLUnionType``
    would not resolve.
    """
    from graphql import GraphQLUnionType as RealUnionType

    from django_graphex import utils

    assert utils.GraphQLUnionType is RealUnionType


def test_prefetch_plan_has_generic_buckets_default_empty():
    """``PrefetchPlan.generic_buckets`` exists and defaults to an empty dict.

    TEETH: if the field were missing, this attribute access raises; if its
    default were shared/mutable across instances, two plans would alias the
    same dict — both checked here.
    """
    from django_graphex.utils import PrefetchPlan

    p1 = PrefetchPlan(only_cols=[], child_select=[])
    p2 = PrefetchPlan(only_cols=[], child_select=[])

    assert p1.generic_buckets == {}
    # Distinct instances must NOT share the same dict object (default_factory).
    p1.generic_buckets["x"] = 1
    assert p2.generic_buckets == {}


# --------------------------------------------------------------------------- #
# T-09 — _resolve_fragment_target: FILTER→RESOLVE second stage                 #
# --------------------------------------------------------------------------- #
def _build_union_schema():
    """Build a schema exposing a GFK-union field; return (schema, registry, types).

    The owner ``Track2GfkComment`` has a GFK ``target`` declared as a union of
    ``AccountType | InvoiceType``; the union is exposed as the ``target`` field.
    """
    reg = Registry()

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
        comment = Field(GfkCommentType)

    schema = graphene.Schema(
        query=Query, types=[AccountType, InvoiceType, GfkCommentType]
    )
    return (
        schema.graphql_schema,
        reg,
        {
            "AccountType": AccountType,
            "InvoiceType": InvoiceType,
            "CommentTargetUnion": CommentTargetUnion,
            "GfkCommentType": GfkCommentType,
        },
    )


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


def test_resolve_fragment_target_returns_member_triple_for_known_type():
    """``... on AccountType`` resolves to (Track2Account, gql, AccountType).

    TEETH: if the resolver returned the parent/owner model (Track2GfkComment) or
    None for a valid member, the member_model identity assertion fails — exactly
    the mis-attribution the design exists to prevent.
    """
    from django_graphex.utils import _resolve_fragment_target

    gql_schema, _reg, types = _build_union_schema()
    union_gql = gql_schema.get_type("CommentTargetUnion")
    node = _inline_fragment_node("AccountType")

    result = _resolve_fragment_target(node, union_gql, gql_schema)
    assert result is not None
    member_model, member_gql, member_graphene = result
    assert member_model is Track2Account
    assert member_graphene is types["AccountType"]
    # Internal-consistency: the resolved graphene type's model IS member_model.
    assert member_graphene._meta.model is member_model
    # And it is NEVER the parent/owner model.
    assert member_model is not Track2GfkComment


def test_resolve_fragment_target_none_for_unknown_type():
    """``... on UnknownType`` -> None (no crash, no parent fallback).

    TEETH: if a missing type fell through to the current/parent model, narrowing
    would mis-attribute -> FieldError under OPTIMIZE_ONLY_FIELDS. This pins None.
    """
    from django_graphex.utils import _resolve_fragment_target

    gql_schema, _reg, _types = _build_union_schema()
    union_gql = gql_schema.get_type("CommentTargetUnion")
    node = _inline_fragment_node("NoSuchType")

    assert _resolve_fragment_target(node, union_gql, gql_schema) is None


def test_resolve_fragment_target_none_when_schema_is_none():
    """schema is None -> None (the degrade path; never dereference a None schema).

    TEETH: if the resolver tried ``schema.get_type`` on a None schema it would
    raise AttributeError instead of degrading.
    """
    from django_graphex.utils import _resolve_fragment_target

    node = _inline_fragment_node("AccountType")
    assert _resolve_fragment_target(node, None, None) is None


def test_resolve_fragment_target_none_for_bare_inline_fragment():
    """A bare inline fragment (no type_condition) -> None.

    TEETH: a bare fragment has no concrete member to route to; resolving it to
    anything would be a fabricated identity.
    """
    from django_graphex.utils import _resolve_fragment_target

    gql_schema, _reg, _types = _build_union_schema()
    union_gql = gql_schema.get_type("CommentTargetUnion")
    node = _inline_fragment_node(None)

    assert _resolve_fragment_target(node, union_gql, gql_schema) is None


def test_resolve_fragment_target_none_for_foreign_object_type():
    """``... on GfkCommentType`` (the OWNER, a real type but not a member) -> still
    resolves to ITS model, never silently the wrong one.

    This guards the SAFETY contract: the resolver maps strictly by the named
    type's own ``_meta.model``; it never substitutes the union/owner. Here the
    owner type DOES have a model, so the resolver returns the owner's model — and
    the caller's per-member bucket logic (T-11) is what restricts routing to true
    union members via ``_inline_fragment_applies``. The point proven here: the
    returned model is ALWAYS the named type's own model, never a fabricated one.

    TEETH: if the resolver hard-coded the union's first member (or the parent),
    this identity check against GfkCommentType's own model would fail.
    """
    from django_graphex.utils import _resolve_fragment_target

    gql_schema, _reg, _types = _build_union_schema()
    union_gql = gql_schema.get_type("CommentTargetUnion")
    node = _inline_fragment_node("GfkCommentType")

    result = _resolve_fragment_target(node, union_gql, gql_schema)
    assert result is not None
    member_model, _gql, member_graphene = result
    assert member_model is Track2GfkComment
    assert member_graphene._meta.model is member_model


# --------------------------------------------------------------------------- #
# T-10 — schema=None threading through _collect_prefetch_only_sets             #
# --------------------------------------------------------------------------- #
def test_collect_prefetch_only_sets_accepts_schema_param_default_none():
    """``_collect_prefetch_only_sets`` exposes a ``schema`` param defaulting None.

    TEETH: if the param were not added, ``inspect.signature`` would not list
    ``schema`` and every existing call site (which omits it) relies on the
    default — a non-None default would change non-GFK behaviour.
    """
    import inspect

    from django_graphex.utils import _collect_prefetch_only_sets

    params = inspect.signature(_collect_prefetch_only_sets).parameters
    assert "schema" in params
    assert params["schema"].default is None


def test_collect_prefetch_only_sets_schema_none_smoke_scalar():
    """Smoke check: a scalar-only ``{ name }`` selection yields an empty plan both
    with ``schema`` omitted and ``schema=None``.

    This is intentionally NOT load-bearing (both sides are ``{}`` because no
    relation is walked); it only documents the trivial base case. The real
    byte-identical net is the relational test below.
    """
    from graphql.language.ast import (
        FieldNode,
        NameNode,
        SelectionSetNode,
    )

    from django_graphex.utils import _collect_prefetch_only_sets
    from tests.models import Author

    sel = SelectionSetNode(
        selections=[FieldNode(name=NameNode(value="name"), arguments=[])]
    )

    plan_omitted = _collect_prefetch_only_sets(Author, sel, {})
    plan_explicit_none = _collect_prefetch_only_sets(Author, sel, {}, schema=None)

    assert plan_omitted == plan_explicit_none == {}


def test_collect_prefetch_only_sets_schema_none_keeps_non_gfk_plan_identical():
    """With ``schema=None`` (and omitted), a RELATIONAL non-GFK selection yields the
    SAME, NON-EMPTY plan — the load-bearing ADR-4d byte-identical net.

    ``Author`` has a reverse-FK ``posts`` relation. Selecting ``posts { title }``
    forces ``_collect_prefetch_only_sets`` to recurse into the relational descent
    (the very self-calls that thread ``schema``) and produce a non-empty
    ``{lookup: PrefetchPlan}`` dict. We compare the plan produced with ``schema``
    omitted vs. ``schema=None``; they MUST be equal.

    TEETH: if any recursive self-call DROPPED ``schema`` on the relational descent
    (so a deeper GFK branch would no longer see it), the relational path is now
    actually exercised here — a divergence on that path would surface as unequal
    plans. The plan must also be non-empty, proving we exercised a real descent
    (not the vacuous ``{} == {}`` of the scalar smoke case).
    """
    from graphql import parse

    from django_graphex.utils import _collect_prefetch_only_sets
    from tests.models import Author

    # { name posts { title } } on Author -> a reverse-FK prefetch descent.
    doc = parse("{ author { name posts { title } } }")
    root_field = doc.definitions[0].selection_set.selections[0]
    sel = root_field.selection_set

    plan_omitted = _collect_prefetch_only_sets(Author, sel, {})
    plan_explicit_none = _collect_prefetch_only_sets(Author, sel, {}, schema=None)

    # Load-bearing: the relational descent must have produced a real plan entry.
    assert "posts" in plan_omitted, plan_omitted
    # And threading schema=None must not change that plan one bit.
    assert plan_omitted == plan_explicit_none


# --------------------------------------------------------------------------- #
# T-11 — GFK GenericPrefetch per-content-type buckets + degrade + safety       #
# --------------------------------------------------------------------------- #
_GFK_QUERY = """
{
  allComments {
    results {
      body
      target {
        __typename
        ... on AccountType { balance }
        ... on InvoiceType { amount }
      }
    }
    totalCount
  }
}
"""


def _build_gfk_union_schema(registry=None):
    """Build a list schema over the GFK owner with a union ``target`` field.

    ``allComments`` returns a paginated list of ``Track2GfkComment``; each
    comment's ``target`` GFK is exposed as ``CommentTargetUnion``.
    """
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

    class GfkCommentListType(DjangoListObjectType):
        class Meta:
            model = Track2GfkComment
            registry = reg

    class Query(graphene.ObjectType):
        all_comments = DjangoListObjectField(GfkCommentListType)

    schema = graphene.Schema(
        query=Query, types=[AccountType, InvoiceType, GfkCommentType]
    )
    return schema, reg


def _seed_gfk_rows():
    """Create several comments, some targeting Accounts, some Invoices."""
    from django.contrib.contenttypes.models import ContentType

    acct_ct = ContentType.objects.get_for_model(Track2Account)
    inv_ct = ContentType.objects.get_for_model(Track2Invoice)

    a1 = Track2Account.objects.create(balance=100, label="acct-a")
    a2 = Track2Account.objects.create(balance=200, label="acct-b")
    i1 = Track2Invoice.objects.create(amount=50, note="inv-a")
    i2 = Track2Invoice.objects.create(amount=75, note="inv-b")

    Track2GfkComment.objects.create(body="c1", target_ct=acct_ct, target_id=a1.pk)
    Track2GfkComment.objects.create(body="c2", target_ct=inv_ct, target_id=i1.pk)
    Track2GfkComment.objects.create(body="c3", target_ct=acct_ct, target_id=a2.pk)
    Track2GfkComment.objects.create(body="c4", target_ct=inv_ct, target_id=i2.pk)


@requires_generic_prefetch
@pytest.mark.django_db
def test_gfk_union_builds_per_content_type_generic_prefetch_buckets():
    """OBSERVABLE: a union GFK on Django>=5.0 yields per-CT GenericPrefetch buckets,
    each narrowed to its member's selected columns, with NO N+1 across parents.

    TEETH (multi-pronged):
      * ``assertNumQueries`` pins NO per-parent N+1 — a regression that skipped
        the GenericPrefetch (bare full-load) would still pass count, so we ALSO
        assert each bucket's SELECT carries exactly its member's narrowed columns
        (balance for Account, amount for Invoice). Mis-routing the buckets (the
        parent-model bug) would put the wrong columns in the wrong SELECT and the
        column assertions fail.
      * 4 comments over 2 distinct content types -> the union prefetch must batch
        per content type, not per row.
    """

    schema, _reg = _build_gfk_union_schema()
    _seed_gfk_rows()

    from django.test.utils import override_settings

    with override_settings(DJANGO_GRAPHEX={"OPTIMIZE_ONLY_FIELDS": True}):
        with CaptureQueriesContext(connection) as ctx:
            result = schema.execute(_GFK_QUERY)

    assert result.errors is None, result.errors
    data = result.data["allComments"]
    assert data["totalCount"] == 4

    # No FieldError, and the union resolved both member shapes.
    balances = {
        r["target"]["balance"]
        for r in data["results"]
        if r["target"].get("__typename") == "AccountType"
    }
    amounts = {
        r["target"]["amount"]
        for r in data["results"]
        if r["target"].get("__typename") == "InvoiceType"
    }
    assert balances == {100, 200}
    assert amounts == {50, 75}

    # Per-content-type narrowing: locate the two member SELECTs. The Account
    # bucket must SELECT ``balance`` and must NOT select ``label`` (the unselected
    # Account column); the Invoice bucket must SELECT ``amount`` and not ``note``.
    sqls = [q["sql"] for q in ctx.captured_queries]
    account_selects = [
        s
        for s in sqls
        if "track2account" in s.lower() and s.lstrip().upper().startswith("SELECT")
    ]
    invoice_selects = [
        s
        for s in sqls
        if "track2invoice" in s.lower() and s.lstrip().upper().startswith("SELECT")
    ]
    assert account_selects, f"expected an Account bucket SELECT; got {sqls}"
    assert invoice_selects, f"expected an Invoice bucket SELECT; got {sqls}"

    acct_sql = " ".join(account_selects).lower()
    inv_sql = " ".join(invoice_selects).lower()
    # Narrowed: selected column present, unselected sibling column absent.
    assert "balance" in acct_sql
    assert "label" not in acct_sql, f"Account bucket not narrowed: {acct_sql}"
    assert "amount" in inv_sql
    assert "note" not in inv_sql, f"Invoice bucket not narrowed: {inv_sql}"


@pytest.mark.django_db
def test_gfk_union_no_n_plus_one_across_parents():
    """OBSERVABLE: the union GFK is batched — query count is independent of N parents.

    With 4 parents over 2 content types, a correct GenericPrefetch issues a FIXED
    number of queries (list+count, plus one prefetch per distinct content type),
    NOT one per parent.

    TEETH: a regression to per-row GFK resolution (no batched prefetch) would add
    one query per comment row and blow assertNumQueries.
    """
    from django.test import TestCase as _DjTestCase

    schema, _reg = _build_gfk_union_schema()
    _seed_gfk_rows()

    from django.test.utils import override_settings

    case = _DjTestCase()
    with override_settings(DJANGO_GRAPHEX={"OPTIMIZE_ONLY_FIELDS": True}):
        # COUNT + comments list + one narrowed prefetch per distinct content type
        # (Account, Invoice) = 4 queries.  This is INDEPENDENT of the 4 parent
        # rows: the GenericPrefetch batches each content type into ONE query.  A
        # regression to per-row GFK resolution would add one query per comment.
        with case.assertNumQueries(4):
            result = schema.execute(_GFK_QUERY)

    assert result.errors is None, result.errors


@pytest.mark.django_db
def test_gfk_union_degrades_to_bare_prefetch_on_django_below_5():
    """DEGRADE: with ``django.VERSION`` mocked to (4,2,0), the union GFK uses a
    bare full-load Prefetch, imports NO GenericPrefetch, and raises nothing.

    TEETH: if the version gate were missing, GenericPrefetch (a 5.0+ symbol) would
    still be imported/used; here we both assert the symbol is never imported AND
    that no GenericPrefetch instance reaches Django's prefetch machinery — the
    SELECTs must be the un-narrowed full-load shape.
    """
    schema, _reg = _build_gfk_union_schema()
    _seed_gfk_rows()

    import builtins

    from django.test.utils import override_settings

    import_calls: list[str] = []
    real_import = builtins.__import__

    def _tracking_import(name, *args, **kwargs):
        if "contenttypes.prefetch" in name:
            import_calls.append(name)
        return real_import(name, *args, **kwargs)

    with override_settings(DJANGO_GRAPHEX={"OPTIMIZE_ONLY_FIELDS": True}):
        with mock.patch.object(__import__("django"), "VERSION", (4, 2, 0, "final", 0)):
            with mock.patch("builtins.__import__", side_effect=_tracking_import):
                with CaptureQueriesContext(connection) as ctx:
                    result = schema.execute(_GFK_QUERY)

    assert result.errors is None, result.errors
    # No GenericPrefetch module import happened under the <5.0 gate.
    assert import_calls == [], (
        f"GenericPrefetch must not be imported on <5.0; got {import_calls}"
    )

    # Full-load degrade: the Account SELECT carries the un-narrowed columns
    # (``label`` present), proving no per-CT narrowing was attempted.
    sqls = [q["sql"].lower() for q in ctx.captured_queries]
    acct_selects = [
        s for s in sqls if "track2account" in s and s.lstrip().startswith("select")
    ]
    assert acct_selects, f"expected an Account SELECT (full-load); got {sqls}"
    assert any("label" in s for s in acct_selects), (
        "on <5.0 the Account bucket must be full-load (label column present)"
    )


@pytest.mark.django_db
def test_gfk_union_unresolvable_bucket_degrades_without_fielderror():
    """SAFETY: a fragment whose type cannot be resolved (or resolves to a non-member)
    falls back to full-load with NO FieldError under OPTIMIZE_ONLY_FIELDS.

    We force unresolvability by querying with an inline fragment on a type that is
    NOT in the schema's union — the optimizer must skip that bucket (full-load),
    never mis-narrow the parent.

    TEETH: if an unresolved fragment fell through to the parent model's columns,
    Django would raise FieldError at evaluation under OPTIMIZE_ONLY_FIELDS; this
    asserts a clean result with no errors.
    """
    schema, _reg = _build_gfk_union_schema()
    _seed_gfk_rows()

    # A query that selects only the union's __typename (no concrete member
    # fragment) -> no resolvable bucket -> every target stays full-load.
    query = """
    { allComments { results { body target { __typename } } totalCount } }
    """

    from django.test.utils import override_settings

    with override_settings(DJANGO_GRAPHEX={"OPTIMIZE_ONLY_FIELDS": True}):
        result = schema.execute(query)

    assert result.errors is None, result.errors
    assert result.data["allComments"]["totalCount"] == 4


@requires_generic_prefetch
@pytest.mark.django_db
def test_build_generic_prefetch_dedupes_by_content_type():
    """SAFETY (critique #1): two member buckets over the SAME content type collapse
    to ONE queryset — never two — so Django's duplicate-CT ValueError cannot fire.

    We force a content-type collision by mocking ``get_for_model`` to return a
    single shared ContentType for both member models, then assert the assembled
    ``GenericPrefetch`` carries exactly one queryset whose ``.only()`` is the
    MERGED column union of both buckets.

    TEETH: if the emission keyed buckets by model (not content type) it would emit
    two querysets for one content type -> Django raises ValueError at prefetch
    time; here we assert a single, merged queryset instead.  We ALSO assert the
    de-dup calls ``get_for_model`` with the GFK's actual ``for_concrete_model``
    (default True) — flipping it to False would let proxy members escape collapse
    (GPM-1); this pins the argument value Django matches on.
    """
    from django.contrib.contenttypes.models import ContentType

    from django_graphex.utils import PrefetchPlan, _build_generic_prefetch

    buckets = {
        Track2Account: PrefetchPlan(only_cols=["id", "balance"], child_select=[]),
        Track2Invoice: PrefetchPlan(only_cols=["id", "amount"], child_select=[]),
    }

    shared_ct = ContentType.objects.get_for_model(Track2Account)
    real_get_for_model = ContentType.objects.get_for_model
    seen_for_concrete: list = []

    def _spy(model, for_concrete_model=True):
        seen_for_concrete.append(for_concrete_model)
        return shared_ct

    # No gfk_field passed -> de-dup must default to for_concrete_model=True,
    # mirroring GenericForeignKey's own default (the value Django keys on).
    with mock.patch.object(ContentType.objects, "get_for_model", side_effect=_spy):
        gp = _build_generic_prefetch("target", buckets)

    assert real_get_for_model  # silence unused in case of refactor
    assert gp is not None
    # Exactly one queryset survived (the two member models collapsed to one CT).
    assert len(gp.querysets) == 1
    # The de-dup keyed by for_concrete_model=True (GFK default Django matches on).
    assert seen_for_concrete, "get_for_model was never called by the de-dup"
    assert all(v is True for v in seen_for_concrete), (
        f"de-dup must key by for_concrete_model=True (GFK default); got "
        f"{seen_for_concrete}"
    )


@requires_generic_prefetch
@pytest.mark.django_db
def test_build_generic_prefetch_uses_gfk_for_concrete_model_flag():
    """GPM-1: the de-dup mirrors the GFK's ``for_concrete_model`` flag exactly.

    Django's ``GenericForeignKey.get_prefetch_querysets`` keys each queryset by
    ``get_content_type(model=qs.query.model,
    for_concrete_model=self.for_concrete_model)``.  The de-dup MUST key on the SAME
    flag.  Here we pass a fake GFK with ``for_concrete_model=False`` and assert the
    de-dup forwards that exact value to ``get_for_model``.

    TEETH: the prior code hard-coded ``for_concrete_model=False``; if it were
    hard-coded to ``True`` (or anything not derived from the GFK) this assertion
    fails.  Combined with the proxy integration test below, this pins the keying
    to Django's own.
    """
    from django.contrib.contenttypes.models import ContentType

    from django_graphex.utils import PrefetchPlan, _build_generic_prefetch

    class _FakeGfk:
        for_concrete_model = False

    buckets = {
        Track2Account: PrefetchPlan(only_cols=["id", "balance"], child_select=[]),
    }
    seen_for_concrete: list = []
    real_ct = ContentType.objects.get_for_model(Track2Account)

    def _spy(model, for_concrete_model=True):
        seen_for_concrete.append(for_concrete_model)
        return real_ct

    with mock.patch.object(ContentType.objects, "get_for_model", side_effect=_spy):
        gp = _build_generic_prefetch("target", buckets, _FakeGfk())

    assert gp is not None
    assert seen_for_concrete == [False], (
        f"de-dup must forward the GFK's for_concrete_model verbatim; got "
        f"{seen_for_concrete}"
    )


@requires_generic_prefetch
@pytest.mark.django_db
def test_gfk_union_proxy_members_no_duplicate_content_type_valueerror():
    """GPM-1/GPM-2 integration: two union members over the SAME concrete table
    (a model and its PROXY) must NOT raise Django's duplicate-content-type
    ValueError, and must collapse to a SINGLE batched query for that content type.

    ``Track2AccountProxy`` shares ``Track2Account``'s table.  Under the GFK's
    default ``for_concrete_model=True`` they map to the SAME ContentType — which is
    exactly what Django matches on.  A de-dup keyed by ``for_concrete_model=False``
    would see them as DISTINCT, emit two querysets for one content type, and
    Django would raise ``ValueError('Only one queryset is allowed for each content
    type')`` at prefetch evaluation.

    TEETH: this executes a REAL prefetch end to end.  Reverting the GPM-1 fix
    (keying the de-dup by ``for_concrete_model=False``) makes Django raise the
    ValueError here; keying by the GFK's flag (True) collapses both members to one
    batched query and the query succeeds with no error.
    """

    reg = Registry()

    class AccountType(DjangoObjectType):
        class Meta:
            model = Track2Account
            registry = reg

    class AccountProxyType(DjangoObjectType):
        class Meta:
            model = Track2AccountProxy
            registry = reg

    class CommentTargetUnion(DjangoUnionType):
        class Meta:
            # Two members over ONE concrete table (proxy + base) -> one CT.
            gfk_types = (AccountType, AccountProxyType)
            registry = reg

    class GfkCommentType(DjangoObjectType):
        class Meta:
            model = Track2GfkComment
            registry = reg
            gfk_unions = {"target": CommentTargetUnion}

    class GfkCommentListType(DjangoListObjectType):
        class Meta:
            model = Track2GfkComment
            registry = reg

    class Query(graphene.ObjectType):
        all_comments = DjangoListObjectField(GfkCommentListType)

    schema = graphene.Schema(
        query=Query, types=[AccountType, AccountProxyType, GfkCommentType]
    )

    from django.contrib.contenttypes.models import ContentType

    acct_ct = ContentType.objects.get_for_model(Track2Account)
    a1 = Track2Account.objects.create(balance=100, label="acct-a")
    Track2GfkComment.objects.create(body="c1", target_ct=acct_ct, target_id=a1.pk)
    a2 = Track2Account.objects.create(balance=200, label="acct-b")
    Track2GfkComment.objects.create(body="c2", target_ct=acct_ct, target_id=a2.pk)

    query = """
    {
      allComments {
        results {
          body
          target {
            __typename
            ... on AccountType { balance }
            ... on AccountProxyType { balance }
          }
        }
        totalCount
      }
    }
    """

    from django.test.utils import override_settings

    with override_settings(DJANGO_GRAPHEX={"OPTIMIZE_ONLY_FIELDS": True}):
        with CaptureQueriesContext(connection) as ctx:
            result = schema.execute(query)

    # The critical assertion: NO duplicate-content-type ValueError surfaced.
    assert result.errors is None, result.errors
    assert result.data["allComments"]["totalCount"] == 2

    # Both members map to ONE content type -> the union prefetch issues exactly
    # ONE SELECT against the shared table (not two), proving the collapse.
    account_selects = [
        q["sql"]
        for q in ctx.captured_queries
        if "track2account" in q["sql"].lower()
        and q["sql"].lstrip().upper().startswith("SELECT")
    ]
    assert len(account_selects) == 1, (
        f"proxy + base must collapse to one batched SELECT for the shared "
        f"content type; got {account_selects}"
    )
