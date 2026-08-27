# -*- coding: utf-8 -*-
"""Tests for issue #59 — pagination ordering field allowlist (security).

Three vulnerabilities from one root: unsanitized client ordering passes straight
to qs.order_by() with no validation.

(a) invalid field name → Django FieldError leaks the full model field list
    (CWE-209). Fix: raise GraphQLError('Invalid ordering field: ...').
(b) hidden/non-exposed column (e.g. 'password') → silent sort oracle.
    Fix: only the attnames the GraphQL TYPE exposes are allowed. The
    projection half of that guarantee lives in
    tests/test_pagination_ordering_projection.py; this module covers the
    model-level half (a term that is not a concrete column at all).
(c) relation-spanning term ('a__b__c') → arbitrary join chain DoS.
    Fix: reject any term whose root (before '__') is not a concrete attname.

Legitimate orderings (declared field, '-field' desc, multi-field comma list)
must continue to work.

Covered pagination classes:
  - LimitOffsetGraphqlPagination (paginate_queryset + prefetch_window_slice)
  - PageGraphqlPagination (paginate_queryset + prefetch_window_slice)
"""

from __future__ import annotations

import pytest
from django.test import TestCase
from graphql import GraphQLError, graphql_sync

from django_graphex.core import ObjectType
from django_graphex.fields import DjangoListObjectField
from django_graphex.paginations import (
    LimitOffsetGraphqlPagination,
    PageGraphqlPagination,
)
from django_graphex.paginations.pagination import (
    LimitOffsetGraphqlPagination as _LOF,
)
from django_graphex.paginations.pagination import (
    PageGraphqlPagination as _PGP,
)
from django_graphex.paginations.pagination import (
    _normalize_ordering_term,
    _split_ordering,
    _validate_ordering_terms,
)
from django_graphex.registry import Registry
from django_graphex.schema import DjangoGraphQLSchema
from django_graphex.types import DjangoListObjectType

from ._schema_isolation import isolated_pair
from .models import Author

_RPOS = Registry()

# ---------------------------------------------------------------------------
# Schema helpers — full GraphQL integration
# ---------------------------------------------------------------------------


class LOSecType(DjangoListObjectType):
    """List type backed by "Author" using limit/offset pagination.

    Feeds the ordering-security integration tests below.
    """

    class Meta:
        """Configuration for "LOSecType".

        Declares the backing model, an isolated test registry, and a
        limit/offset pagination strategy.
        """

        model = Author
        registry = _RPOS
        pagination = LimitOffsetGraphqlPagination(default_limit=5, max_limit=20)


class PageSecType(DjangoListObjectType):
    """List type backed by "Author" using page/page_size pagination.

    Feeds the ordering-security integration tests below.
    """

    class Meta:
        """Configuration for "PageSecType".

        Declares the backing model, an isolated test registry, and a
        page-based pagination strategy.
        """

        model = Author
        registry = _RPOS
        pagination = PageGraphqlPagination(
            page_size=5, page_size_query_param="pageSize"
        )


class SecQuery(ObjectType):
    """Root query exposing the limit/offset and page-based list fields under test.

    Used by the full-integration ordering-security tests below.
    """

    lo_list = DjangoListObjectField(LOSecType)
    page_list = DjangoListObjectField(PageSecType)


sec_schema = DjangoGraphQLSchema(query=SecQuery, registries=isolated_pair(_RPOS))


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _lo(default_limit=5, max_limit=20, ordering=""):
    return _LOF(default_limit=default_limit, max_limit=max_limit, ordering=ordering)


def _pg(page_size=5, max_page_size=20, ordering=""):
    return _PGP(page_size=page_size, max_page_size=max_page_size, ordering=ordering)


# ---------------------------------------------------------------------------
# (a) Invalid field name → GraphQLError, NOT FieldError
# ---------------------------------------------------------------------------


class TestInvalidFieldRaisesGraphQLError(TestCase):
    """Invalid ordering field must raise GraphQLError, not Django FieldError.

    Covers the raw-error type, and both paginators' error message content.
    """

    def setUp(self) -> None:
        """Create three authors so paginated queries have rows to order.

        Three rows are enough to observe both ordering direction and
        error paths.
        """
        for name in ("alice", "bob", "carol"):
            Author.objects.create(name=name)

    def test_limitoffset_invalid_field_raises_graphql_error(self) -> None:
        """Assert LimitOffsetGraphqlPagination raises GraphQLError for an invalid field.

        If this fails, an invalid ordering field would raise some other
        exception type (or none at all) instead of the clean GraphQLError
        the security guard is supposed to produce.

        Raises:
            GraphQLError: Expected from "paginate_queryset" and asserted
                via pytest.raises.
        """
        p = _lo()
        with pytest.raises(GraphQLError):
            p.paginate_queryset(Author.objects.all(), ordering="nonexistent_field")

    def test_limitoffset_invalid_field_does_not_raise_field_error(self) -> None:
        """Assert the exception raised is never a raw Django FieldError.

        If this fails, the raw Django "FieldError" (which enumerates
        every concrete model field in its message) would leak past the
        guard, exposing the full field list to the client (CWE-209).
        """
        from django.core.exceptions import FieldError

        p = _lo()
        try:
            list(
                p.paginate_queryset(Author.objects.all(), ordering="nonexistent_field")
            )
            pytest.fail("Expected an exception")
        except GraphQLError:
            pass  # correct
        except FieldError:
            pytest.fail(
                "paginate_queryset raised raw FieldError — full model field list "
                "leaks to the client (CWE-209). Must raise GraphQLError instead."
            )

    def test_limitoffset_error_message_does_not_leak_field_list(self) -> None:
        """Assert the error message never contains the Django field-list dump.

        If this fails, the GraphQLError message would leak the phrase
        "Choices are:" (Django's enumerated field list), defeating the
        purpose of wrapping the raw FieldError.
        """
        p = _lo()
        try:
            list(
                p.paginate_queryset(Author.objects.all(), ordering="nonexistent_field")
            )
        except GraphQLError as exc:
            assert "Choices are:" not in str(exc), (
                "Error message leaks the model field list to the client."
            )
        except Exception:
            pass  # other exceptions covered by the test above

    def test_page_invalid_field_raises_graphql_error(self) -> None:
        """Assert PageGraphqlPagination raises GraphQLError for an invalid field.

        If this fails, an invalid ordering field would raise some other
        exception type (or none at all) instead of the clean GraphQLError
        the security guard is supposed to produce.

        Raises:
            GraphQLError: Expected from "paginate_queryset" and asserted
                via pytest.raises.
        """
        p = _pg()
        with pytest.raises(GraphQLError):
            p.paginate_queryset(
                Author.objects.all(), page=1, ordering="nonexistent_field"
            )

    def test_page_invalid_field_does_not_leak_field_list(self) -> None:
        """Assert the error message never contains the Django field-list dump.

        If this fails, the GraphQLError message would leak the phrase
        "Choices are:" (Django's enumerated field list) on the
        page-pagination path too.
        """
        p = _pg()
        try:
            list(
                p.paginate_queryset(
                    Author.objects.all(), page=1, ordering="nonexistent_field"
                )
            )
        except GraphQLError as exc:
            assert "Choices are:" not in str(exc), (
                "Error message leaks the model field list to the client."
            )
        except Exception:
            pass


# ---------------------------------------------------------------------------
# (b) Hidden/non-exposed column — the model-level half of the allowlist
# ---------------------------------------------------------------------------
# The security boundary of the allowlist is:
#   - Only attnames the GraphQL TYPE exposes are allowed. A column removed with
#     'only_fields' / 'exclude_fields' is rejected, so 'ordering' can no longer
#     rank rows by a column the client cannot select.
#   - Non-existent fields are rejected (covers typos + injected field names).
#   - Relation-spanning lookups ('a__b') are rejected even when 'a' exists.
#
# This block used to state the OPPOSITE: that ordering by a concrete column like
# 'password' "cannot be blocked at the paginator level alone because the
# paginator has no reference to which schema fields are exposed". That was a
# real design decision and it was wrong — it left 'ordering' a read oracle over
# every hidden column. The paginator now carries the type's projection
# ('ordering_allowed_attnames'), stamped on a COPY of the paginator once per
# SCHEMA — in the list container's fields thunk, in the flat paginated list
# field's constructor, and again in the permission pruner for each pruned clone
# — because which columns a node publishes is a per-schema fact and the
# paginator instance is shared. The projection half of the contract is pinned in
# tests/test_pagination_ordering_projection.py and
# tests/test_ordering_allowlist_scope.py.
#
# What stays here is the half that needs no type: a term naming a column the
# MODEL does not have, and a relation-spanning term. A bare paginator built in
# a test carries no projection, so it still allows every concrete column.


class TestHiddenColumnRejected(TestCase):
    """Ordering by fields that don't exist on the model must be rejected.

    A paginator constructed directly carries no type projection, so these
    cases exercise the model-level allowlist: non-existent columns and
    relation names that are not concrete attnames. Blocking a column the type
    projects away is covered in tests/test_pagination_ordering_projection.py.
    """

    def setUp(self) -> None:
        """Create one author so paginated queries have a row to order.

        A single row is enough to exercise the rejection paths under test.
        """
        Author.objects.create(name="alice")

    def test_limitoffset_nonexistent_on_author_rejected(self) -> None:
        """Assert ordering by a field that doesn't exist on Author raises.

        If this fails, an ordering term naming a nonexistent field would
        reach the queryset instead of being rejected before it can leak
        Django's field-list error.

        Raises:
            GraphQLError: Expected from "paginate_queryset" and asserted
                via pytest.raises.
        """
        p = _lo()
        # 'secret_field' doesn't exist on Author at all
        with pytest.raises(GraphQLError):
            list(p.paginate_queryset(Author.objects.all(), ordering="secret_field"))

    def test_page_nonexistent_on_author_rejected(self) -> None:
        """Assert PageGraphqlPagination rejects a non-existent field on Author.

        If this fails, an ordering term naming a nonexistent field would
        reach the queryset on the page-pagination path too.

        Raises:
            GraphQLError: Expected from "paginate_queryset" and asserted
                via pytest.raises.
        """
        p = _pg()
        with pytest.raises(GraphQLError):
            list(
                p.paginate_queryset(
                    Author.objects.all(), page=1, ordering="secret_field"
                )
            )

    def test_limitoffset_relation_field_name_only_rejected(self) -> None:
        """Assert a relation field name ("posts") is rejected as not a concrete attname.

        A FK attname is "author_id"; the reverse relation name "posts" is
        NOT a concrete attname, so ordering by "posts" alone is also
        rejected.

        If this fails, a relation's Python-level field name (rather than
        its concrete attname) could be used to order results, widening
        the allowlist beyond concrete columns.

        Raises:
            GraphQLError: Expected from "paginate_queryset" and asserted
                via pytest.raises.
        """
        from .models import Post

        # 'author' on Post is a FK; its attname is 'author_id' not 'author'
        p = _lo()
        with pytest.raises(GraphQLError):
            list(p.paginate_queryset(Post.objects.all(), ordering="author"))


# ---------------------------------------------------------------------------
# (c) Relation-spanning term → rejected (DoS prevention)
# ---------------------------------------------------------------------------


class TestRelationSpanningRejected(TestCase):
    """Ordering terms that span relations must be rejected.

    Covers a single-hop and a multi-hop relation-spanning term, on both
    the limit/offset and page paginators.
    """

    def setUp(self) -> None:
        """Create one author so paginated queries have a row to order.

        A single row is enough to exercise the rejection paths under test.
        """
        Author.objects.create(name="alice")

    def test_limitoffset_relation_spanning_rejected(self) -> None:
        """Assert an "a__b" style relation-spanning term raises GraphQLError.

        If this fails, a relation-spanning ordering term would reach the
        queryset, enabling an arbitrary join-chain denial-of-service.

        Raises:
            GraphQLError: Expected from "paginate_queryset" and asserted
                via pytest.raises.
        """
        p = _lo()
        with pytest.raises(GraphQLError):
            list(
                p.paginate_queryset(
                    Author.objects.all(),
                    ordering="posts__title",
                )
            )

    def test_page_relation_spanning_rejected(self) -> None:
        """Assert PageGraphqlPagination rejects a relation-spanning ordering term.

        If this fails, a relation-spanning ordering term would reach the
        queryset on the page-pagination path too.

        Raises:
            GraphQLError: Expected from "paginate_queryset" and asserted
                via pytest.raises.
        """
        p = _pg()
        with pytest.raises(GraphQLError):
            list(
                p.paginate_queryset(
                    Author.objects.all(),
                    page=1,
                    ordering="posts__title",
                )
            )

    def test_limitoffset_deep_relation_rejected(self) -> None:
        """Assert a deep multi-hop relation path is rejected.

        If this fails, a multi-hop relation-spanning term (more than one
        "__" join) would slip past the single-hop check.

        Raises:
            GraphQLError: Expected from "paginate_queryset" and asserted
                via pytest.raises.
        """
        p = _lo()
        with pytest.raises(GraphQLError):
            list(
                p.paginate_queryset(
                    Author.objects.all(),
                    ordering="posts__category__title",
                )
            )


# ---------------------------------------------------------------------------
# Legitimate orderings must still work
# ---------------------------------------------------------------------------


class TestLegitimateOrderingsWork(TestCase):
    """Valid orderings must continue to work unchanged.

    Covers ascending, descending, multi-field, pk, and no-ordering cases
    across both paginators.
    """

    def setUp(self) -> None:
        """Create three authors with distinct names so ordering is observable.

        Insertion order intentionally differs from name order so a sort
        failure would be caught.
        """
        for name in ("charlie", "alice", "bob"):
            Author.objects.create(name=name)

    def test_limitoffset_valid_asc_field(self) -> None:
        """Assert ascending ordering by a real field works on limit/offset paging.

        If this fails, the security allowlist would have broken the
        legitimate ascending-ordering use case.
        """
        p = _lo()
        result = list(p.paginate_queryset(Author.objects.all(), ordering="name"))
        names = [a.name for a in result]
        assert names == sorted(names)

    def test_limitoffset_valid_desc_field(self) -> None:
        """Assert descending ordering (leading "-") works on limit/offset paging.

        If this fails, the security allowlist would have broken the
        legitimate descending-ordering use case.
        """
        p = _lo()
        result = list(p.paginate_queryset(Author.objects.all(), ordering="-name"))
        names = [a.name for a in result]
        assert names == sorted(names, reverse=True)

    def test_limitoffset_multi_field_csv(self) -> None:
        """Assert comma-separated multi-field ordering works on limit/offset paging.

        If this fails, the security allowlist would have broken
        multi-field ordering expressed as a comma-separated list.
        """
        p = _lo()
        result = list(p.paginate_queryset(Author.objects.all(), ordering="name,-id"))
        assert len(result) == 3

    def test_page_valid_asc_field(self) -> None:
        """Assert ascending ordering works on page-based pagination.

        If this fails, the security allowlist would have broken the
        legitimate ascending-ordering use case on the page paginator.
        """
        p = _pg()
        result = list(
            p.paginate_queryset(Author.objects.all(), page=1, ordering="name")
        )
        names = [a.name for a in result]
        assert names == sorted(names)

    def test_page_valid_desc_field(self) -> None:
        """Assert descending ordering works on page-based pagination.

        If this fails, the security allowlist would have broken the
        legitimate descending-ordering use case on the page paginator.
        """
        p = _pg()
        result = list(
            p.paginate_queryset(Author.objects.all(), page=1, ordering="-name")
        )
        names = [a.name for a in result]
        assert names == sorted(names, reverse=True)

    def test_limitoffset_pk_attname_valid(self) -> None:
        """Assert the pk attname ("id") is accepted as an ordering term.

        If this fails, the concrete-attname allowlist would have
        rejected the model's own primary key attname.
        """
        p = _lo()
        result = list(p.paginate_queryset(Author.objects.all(), ordering="id"))
        assert len(result) == 3

    def test_no_ordering_works(self) -> None:
        """Assert omitting ordering entirely returns results unaffected.

        If this fails, the security guard would incorrectly require an
        ordering argument instead of tolerating its absence.
        """
        p = _lo()
        result = list(p.paginate_queryset(Author.objects.all()))
        assert len(result) == 3


# ---------------------------------------------------------------------------
# prefetch_window_slice ordering validation
# ---------------------------------------------------------------------------


class TestPrefetchWindowSliceOrderingValidation(TestCase):
    """prefetch_window_slice must also validate ordering terms.

    Covers the invalid-field, relation-spanning, and valid-term cases.
    """

    def setUp(self) -> None:
        """Create one author so prefetch-window checks have a real model to inspect.

        The row itself is not read; only the model class is used by the
        ordering check.
        """
        Author.objects.create(name="test")

    def test_limitoffset_prefetch_window_slice_invalid_term_raises(self) -> None:
        """Assert the prefetch-window ordering check rejects an invalid field.

        If this fails, the prefetch-window optimization path would skip
        the same security allowlist enforced by the main pagination path.

        Raises:
            GraphQLError: Expected from
                "prefetch_window_slice_ordering_check" and asserted via
                pytest.raises.
        """
        p = _lo()
        with pytest.raises(GraphQLError):
            p.prefetch_window_slice_ordering_check(
                Author.objects.model, "nonexistent_field"
            )

    def test_limitoffset_prefetch_window_slice_relation_term_raises(self) -> None:
        """Assert the prefetch-window ordering check rejects a relation-spanning term.

        If this fails, the prefetch-window optimization path would allow
        a relation-spanning ordering term the main pagination path
        rejects.

        Raises:
            GraphQLError: Expected from
                "prefetch_window_slice_ordering_check" and asserted via
                pytest.raises.
        """
        p = _lo()
        with pytest.raises(GraphQLError):
            p.prefetch_window_slice_ordering_check(Author.objects.model, "posts__title")

    def test_limitoffset_prefetch_window_slice_valid_term_ok(self) -> None:
        """Assert the prefetch-window ordering check accepts valid concrete attnames.

        If this fails, the prefetch-window optimization path would
        reject legitimate ordering terms it should accept.
        """
        p = _lo()
        # Should not raise
        p.prefetch_window_slice_ordering_check(Author.objects.model, "name")
        p.prefetch_window_slice_ordering_check(Author.objects.model, "-name")
        p.prefetch_window_slice_ordering_check(Author.objects.model, "name,-id")


# ---------------------------------------------------------------------------
# Full GraphQL integration — error travels through schema correctly
# ---------------------------------------------------------------------------


class TestSchemaIntegrationOrderingSecurity(TestCase):
    """Integration: invalid ordering in schema query, GraphQL error in response.

    Covers both paginators plus a negative control that neuters the
    validator to prove the positive tests are load-bearing.
    """

    def setUp(self) -> None:
        """Create two authors so full-schema paginated queries have rows.

        Two rows are enough to exercise the ordering-error response shape.
        """
        for name in ("a", "b"):
            Author.objects.create(name=name)

    # Markers a raw Django "FieldError" leaks (CWE-209) but the clean guard
    # must never emit: the "Cannot resolve keyword" phrasing and the enumerated
    # "Choices are: ..." model field list.
    _LEAK_MARKERS = ("Cannot resolve keyword", "Choices are")

    def test_limitoffset_schema_invalid_ordering_returns_error(self) -> None:
        """Full schema query with invalid ordering must return errors, not crash.

        The real contract (not the previous "A or B" tautology): a single
        GraphQLError whose message is the clean ""Invalid ordering field:
        'nonexistent_field'." form (no "Cannot resolve keyword" / "Choices
        are" model-field-list leak), rooted at the "results"" path, with a null
        "results" payload.
        """
        result = graphql_sync(
            sec_schema.graphql_schema,
            '{ loList { results(ordering: "nonexistent_field") { name } } }',
        )
        assert result.errors is not None
        assert len(result.errors) == 1
        message = result.errors[0].message
        assert "Invalid ordering field: 'nonexistent_field'." in message
        # The raw FieldError leak must be absent — this is the security property.
        assert not any(marker in message for marker in self._LEAK_MARKERS)
        assert result.errors[0].path == ["loList", "results"]
        # The invalid field's payload is absent/None (not partial data).
        assert result.data["loList"]["results"] is None

    def test_page_schema_invalid_ordering_returns_error(self) -> None:
        """PageGraphqlPagination: invalid ordering in schema query → the clean
        field-naming GraphQLError (no model-field-list leak), null 'results'."""
        result = graphql_sync(
            sec_schema.graphql_schema,
            '{ pageList { results(ordering: "nonexistent_field") { name } } }',
        )
        assert result.errors is not None
        assert len(result.errors) == 1
        message = result.errors[0].message
        assert "Invalid ordering field: 'nonexistent_field'." in message
        assert not any(marker in message for marker in self._LEAK_MARKERS)
        assert result.errors[0].path == ["pageList", "results"]
        assert result.data["pageList"]["results"] is None

    def test_neutered_validator_breaks_the_contract(self) -> None:
        """Negative control: with '_validate_ordering_terms' neutered to a no-op,
        the clean contract above no longer holds — the raw Django "FieldError"
        leaks the model field list instead.

        This proves the two positive tests are load-bearing: they exercise the
        real guard, not some incidental behaviour. The neuter is a temporary
        "mock.patch" context — the library source is never modified and the real
        symbol is restored on exit. With the guard removed, the invalid term
        reaches "qs.order_by('nonexistent_field')" and Django raises
        "FieldError('Cannot resolve keyword ... Choices are: ...')" — the exact
        CWE-209 leak the guard exists to prevent.
        """
        from unittest import mock

        with mock.patch(
            "django_graphex.paginations.pagination._validate_ordering_terms",
            lambda *a, **k: None,
        ):
            result = graphql_sync(
                sec_schema.graphql_schema,
                '{ loList { results(ordering: "nonexistent_field") { name } } }',
            )

        assert result.errors is not None
        message = result.errors[0].message
        # The clean guard message is GONE and the raw FieldError leak is present.
        assert "Invalid ordering field: 'nonexistent_field'." not in message
        assert any(marker in message for marker in self._LEAK_MARKERS), (
            "Neutering _validate_ordering_terms did NOT produce the raw FieldError "
            "leak — the positive tests are not actually exercising the validator."
        )


# ---------------------------------------------------------------------------
# _validate_ordering_terms: empty/falsy ordering (line 83) and list path (line 93)
# ---------------------------------------------------------------------------


class TestValidateOrderingTermsEdges(TestCase):
    """Unit tests for _validate_ordering_terms covering the two branches missed
    by higher-level tests: the early-return on falsy input (line 83) and the
    list-of-terms path (line 93)."""

    # -- line 83: "if not ordering: return" ---------------------------------

    def test_empty_string_ordering_is_a_noop(self) -> None:
        """_validate_ordering_terms("") must return None without raising.

        The "if not ordering: return" guard (line 83) exits early so that
        callers with no configured ordering never enter the allowlist check.
        """
        result = _validate_ordering_terms(Author, "")
        assert result is None

    def test_none_ordering_is_a_noop(self) -> None:
        """Assert "_validate_ordering_terms(None)" returns None without raising.

        If this fails, a None ordering value would raise instead of being
        treated as "no ordering configured".
        """
        result = _validate_ordering_terms(Author, None)
        assert result is None

    def test_empty_list_ordering_is_a_noop(self) -> None:
        """Assert "_validate_ordering_terms([])" returns None without raising.

        If this fails, an empty ordering list would raise instead of
        being treated as "no ordering configured".
        """
        result = _validate_ordering_terms(Author, [])
        assert result is None

    # -- line 93: "else: terms = [t for t in ordering if t]" (list path) ---

    def test_list_ordering_valid_terms_accepted(self) -> None:
        """Passing ordering as a list of valid attnames must not raise.

        The "else" branch (line 93) handles the case where "ordering" is a
        list rather than a comma-separated string.  Every term must pass the
        concrete-attname allowlist check.
        """
        _validate_ordering_terms(Author, ["name", "-id"])

    def test_list_ordering_invalid_term_raises(self) -> None:
        """Assert a list ordering value with an invalid term raises GraphQLError.

        If this fails, the list-form ordering path would not apply the
        same concrete-attname allowlist as the string-form path.
        """
        with pytest.raises(GraphQLError):
            _validate_ordering_terms(Author, ["name", "nonexistent_field"])

    def test_list_ordering_relation_spanning_term_raises(self) -> None:
        """Assert a list ordering value with a relation-spanning term raises.

        If this fails, the list-form ordering path would not reject
        relation-spanning terms the string-form path rejects.
        """
        with pytest.raises(GraphQLError):
            _validate_ordering_terms(Author, ["posts__title"])

    def test_list_ordering_skips_empty_strings(self) -> None:
        """Empty strings inside the list are filtered out (no error, no crash).

        The "[t for t in ordering if t]" comprehension drops falsy elements,
        so '["name", ""]' is equivalent to '["name"]'.
        """
        _validate_ordering_terms(Author, ["name", ""])

    def test_list_ordering_with_direction_prefix_accepted(self) -> None:
        """List ordering with direction prefixes (+/-) must be accepted.

        The validator strips the leading +/- before checking the allowlist, so
        both "name" and "-id" in a list are valid for the Author model.
        """
        _validate_ordering_terms(Author, ["+name", "-id", "id"])

    def test_list_ordering_with_plus_prefix_accepted(self) -> None:
        """Assert a leading "+" prefix is stripped and the field is accepted.

        If this fails, an explicit ascending-direction prefix would be
        mishandled by the allowlist check.
        """
        _validate_ordering_terms(Author, ["+name"])

    def test_list_ordering_mixed_valid_and_empty_entries(self) -> None:
        """A list with some empty strings must not raise (empty strings are filtered).

        The "[t for t in ordering if t]" comprehension on line 93 silently
        drops any falsy entries, so mixed lists are safe.
        """
        _validate_ordering_terms(Author, ["name", "", None or "id"])


# ---------------------------------------------------------------------------
# prefetch_window_slice: negative offset raises GraphQLError (line 462)
# ---------------------------------------------------------------------------


class TestPrefetchWindowSliceNegativeOffset(TestCase):
    """prefetch_window_slice must raise GraphQLError for negative offsets.

    Covers line 462: the "raise GraphQLError" guard for negative offsets inside
    LimitOffsetGraphqlPagination.prefetch_window_slice.  This branch is separate
    from the in-memory path test; diff-cover flags it because it is new code.
    """

    def test_negative_offset_raises_graphql_error(self) -> None:
        """prefetch_window_slice(offset=-1) must raise GraphQLError.

        A negative offset would cause Django's QuerySet.__getitem__ to raise a
        raw ValueError which escapes the resolver.  The guard must convert it
        to a clean GraphQLError before any queryset slice occurs.
        """
        p = _lo(default_limit=5, max_limit=20)
        with pytest.raises(GraphQLError, match="Offset must be a non-negative integer"):
            p.prefetch_window_slice(**{p.offset_query_param: -1})

    def test_zero_offset_is_valid(self) -> None:
        """Assert prefetch_window_slice(offset=0) does not raise.

        If this fails, the negative-offset guard would be over-broad and
        wrongly reject the valid zero offset.
        """
        p = _lo(default_limit=5, max_limit=20)
        result = p.prefetch_window_slice(**{p.offset_query_param: 0})
        # Returns (offset, limit, ordering) when limit is set.
        assert result is not None
        offset, limit, _ = result
        assert offset == 0
        assert limit == 5

    def test_unbounded_paginator_returns_none(self) -> None:
        """prefetch_window_slice with no limit configured must return None.

        When _resolve_page_size returns None (no default_limit, no max_limit,
        no client-supplied limit), prefetch_window_slice returns None to signal
        the caller to fall back to the in-memory path.  This covers the
        "if limit is None: return None" guard (line 458-459) which is also
        new in this diff but is naturally tested by having a truly unbounded
        paginator configuration.
        """
        p = _lo(default_limit=None, max_limit=None)
        result = p.prefetch_window_slice()
        assert result is None


# ---------------------------------------------------------------------------
# pk alias — 'pk' and '-pk' must be accepted (regression #70)
# ---------------------------------------------------------------------------


class TestPkAliasAccepted(TestCase):
    """'pk' and '-pk' are native Django ordering aliases and must be accepted.

    Regression from #59: _validate_ordering_terms built its allowlist from
    {f.attname for f in model._meta.concrete_fields}.  'pk' is NOT in that set
    (it is an alias, not a real attname) so ordering='pk' raised GraphQLError on
    every paginated request.

    These tests MUST FAIL on unpatched code.
    """

    def setUp(self) -> None:
        """Create three authors with distinct names so ordering is observable.

        Insertion order intentionally differs from name order so a sort
        failure would be caught.
        """
        for name in ("charlie", "alice", "bob"):
            Author.objects.create(name=name)

    # -- _validate_ordering_terms unit-level ---------------------------------

    def test_validate_pk_alias_accepted(self) -> None:
        """Assert "_validate_ordering_terms" does not raise for "pk".

        If this fails, the pk alias would still be rejected by the
        concrete-attname allowlist, regressing issue #70.
        """
        _validate_ordering_terms(Author, "pk")  # must not raise

    def test_validate_pk_desc_alias_accepted(self) -> None:
        """Assert "_validate_ordering_terms" does not raise for "-pk".

        If this fails, the descending pk alias would still be rejected
        by the concrete-attname allowlist.
        """
        _validate_ordering_terms(Author, "-pk")  # must not raise

    def test_validate_pk_plus_prefix_accepted(self) -> None:
        """Assert "_validate_ordering_terms" does not raise for "+pk".

        If this fails, the explicit-ascending pk alias would still be
        rejected by the concrete-attname allowlist.
        """
        _validate_ordering_terms(Author, "+pk")  # must not raise

    # -- LimitOffsetGraphqlPagination ----------------------------------------

    def test_limitoffset_pk_ordering_accepted(self) -> None:
        """LimitOffsetGraphqlPagination with ordering='pk' must not raise.

        This test MUST FAIL on unpatched code.
        """
        p = _lo()
        result = list(p.paginate_queryset(Author.objects.all(), ordering="pk"))
        assert len(result) == 3

    def test_limitoffset_pk_desc_ordering_accepted(self) -> None:
        """Assert LimitOffsetGraphqlPagination accepts ordering="-pk".

        If this fails, descending pk ordering would still be rejected on
        the limit/offset pagination path.
        """
        p = _lo()
        result = list(p.paginate_queryset(Author.objects.all(), ordering="-pk"))
        assert len(result) == 3

    def test_limitoffset_pk_configured_default_ordering_accepted(self) -> None:
        """A LimitOffset paginator configured with ordering='pk' must not raise.

        This exercises the developer-configured default ordering path — the path
        that breaks in production when ordering='pk' is set at definition time.

        This test MUST FAIL on unpatched code.
        """
        p = _LOF(default_limit=5, max_limit=20, ordering="pk")
        result = list(p.paginate_queryset(Author.objects.all()))
        assert len(result) == 3

    # -- PageGraphqlPagination -----------------------------------------------

    def test_page_pk_ordering_accepted(self) -> None:
        """PageGraphqlPagination with ordering='pk' must not raise.

        This test MUST FAIL on unpatched code.
        """
        p = _pg()
        result = list(p.paginate_queryset(Author.objects.all(), page=1, ordering="pk"))
        assert len(result) == 3

    def test_page_pk_desc_ordering_accepted(self) -> None:
        """Assert PageGraphqlPagination accepts ordering="-pk".

        If this fails, descending pk ordering would still be rejected on
        the page pagination path.
        """
        p = _pg()
        result = list(p.paginate_queryset(Author.objects.all(), page=1, ordering="-pk"))
        assert len(result) == 3

    def test_page_pk_configured_default_ordering_accepted(self) -> None:
        """A Page paginator configured with ordering='pk' must not raise.

        This test MUST FAIL on unpatched code.
        """
        p = _PGP(page_size=5, max_page_size=20, ordering="pk")
        result = list(p.paginate_queryset(Author.objects.all(), page=1))
        assert len(result) == 3

    # -- Security boundary: __-spanning and FK-name still rejected -----------

    def test_pk_does_not_loosen_relation_spanning_rejection(self) -> None:
        """Assert allowing "pk" does not loosen relation-spanning rejection.

        If this fails, adding the pk alias to the allowlist would have
        accidentally widened it to accept relation-spanning terms too.

        Raises:
            GraphQLError: Expected from "_validate_ordering_terms" and
                asserted via pytest.raises.
        """
        with pytest.raises(GraphQLError):
            _validate_ordering_terms(Author, "posts__pk")

    def test_pk_does_not_loosen_fk_name_rejection(self) -> None:
        """Allowing 'pk' must not allow the FK *name* ('author') to slip through.

        'author' on Post is a FK; its attname is 'author_id'.  Ordering by the
        field name 'author' (not 'author_id') must still be rejected.
        """
        from .models import Post

        with pytest.raises(GraphQLError):
            _validate_ordering_terms(Post, "author")


# ---------------------------------------------------------------------------
# C9: direction-prefix parity — the validated term must be the term order_by
# receives, so "+name" works and "--name" is rejected without a field dump.
# ---------------------------------------------------------------------------


class TestDirectionPrefixParity(TestCase):
    """The direction prefix must be canonicalized at the single parse point.

    "_normalize_ordering_term" is the only place the leading "-"/"+" is parsed,
    so the term reaching "order_by" is byte-identical to the validated one. A
    "+" prefix means ascending and is dropped; a repeated prefix ("--name") is
    rejected because no convention gives it a meaning and Django's own
    "FieldError" would enumerate every column of the model (CWE-209).
    """

    def setUp(self) -> None:
        """Create three authors so the ordering assertions have rows to sort.

        The names are inserted out of alphabetical order so an ascending sort
        is distinguishable from insertion order.
        """
        for name in ("carol", "alice", "bob"):
            Author.objects.create(name=name)

    def test_plus_prefix_orders_ascending_through_the_schema(self) -> None:
        """A "+name" ordering must sort ascending instead of raising.

        If this fails, the "+" survives the validator and reaches "order_by",
        where Django raises FieldError listing every column of the model.
        """
        result = graphql_sync(
            sec_schema.graphql_schema,
            '{ loList { results(ordering: "+name") { name } } }',
        )
        assert result.errors is None, result.errors
        assert result.data is not None
        names = [row["name"] for row in result.data["loList"]["results"]]
        assert names == ["alice", "bob", "carol"]

    def test_repeated_prefix_rejected_without_leaking_the_field_list(self) -> None:
        """A "--name" ordering must fail with the clean allowlist error.

        If this fails, the repeated prefix reaches "order_by" and Django's
        FieldError message enumerates every concrete column of the model.
        """
        result = graphql_sync(
            sec_schema.graphql_schema,
            '{ loList { results(ordering: "--name") { name } } }',
        )
        assert result.errors is not None
        message = result.errors[0].message
        assert "Invalid ordering field" in message
        assert "Choices are:" not in message

    def test_split_ordering_rejects_a_repeated_prefix(self) -> None:
        """The shared splitter must reject "--name" for every consumer.

        "_split_ordering" is imported by the window-prefetch pre-check in
        "django_graphex/fields.py" too, so rejecting here keeps the window path
        and the paginator path from disagreeing on the same input.

        Raises:
            GraphQLError: Expected from "_split_ordering" and asserted via
                pytest.raises.
        """
        with pytest.raises(GraphQLError, match="Invalid ordering field"):
            _split_ordering("--name")

    def test_plus_prefix_normalizes_to_the_bare_snake_case_attname(self) -> None:
        """A "+createdAt" term must normalize to the plain "created_at" attname.

        If this fails, the normalized term still carries a prefix Django does
        not understand.
        """
        assert _normalize_ordering_term("+createdAt") == "created_at"
        assert _normalize_ordering_term("-createdAt") == "-created_at"
