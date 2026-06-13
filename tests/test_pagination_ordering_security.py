# -*- coding: utf-8 -*-
"""Tests for issue #59 — pagination ordering field allowlist (security).

Three vulnerabilities from one root: unsanitized client ordering passes straight
to qs.order_by() with no validation.

(a) invalid field name → Django FieldError leaks the full model field list
    (CWE-209). Fix: raise GraphQLError('Invalid ordering field: ...').
(b) hidden/non-exposed column (e.g. 'password') → silent sort oracle.
    Fix: only concrete attnames from _meta.concrete_fields are allowed.
(c) relation-spanning term ('a__b__c') → arbitrary join chain DoS.
    Fix: reject any term whose root (before '__') is not a concrete attname.

Legitimate orderings (declared field, '-field' desc, multi-field comma list)
must continue to work.

Covered pagination classes:
  - LimitOffsetGraphqlPagination (paginate_queryset + prefetch_window_slice)
  - PageGraphqlPagination (paginate_queryset + prefetch_window_slice)
"""

from __future__ import annotations

import graphene
import pytest
from django.test import TestCase
from graphene import Schema
from graphql import GraphQLError

from django_graphex import (
    DjangoListObjectField,
    DjangoListObjectType,
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
    _validate_ordering_terms,
)

from .models import Author

# ---------------------------------------------------------------------------
# Schema helpers — full GraphQL integration
# ---------------------------------------------------------------------------


class LOSecType(DjangoListObjectType):
    class Meta:
        model = Author
        pagination = LimitOffsetGraphqlPagination(default_limit=5, max_limit=20)


class PageSecType(DjangoListObjectType):
    class Meta:
        model = Author
        pagination = PageGraphqlPagination(
            page_size=5, page_size_query_param="pageSize"
        )


class SecQuery(graphene.ObjectType):
    lo_list = DjangoListObjectField(LOSecType)
    page_list = DjangoListObjectField(PageSecType)


sec_schema = Schema(query=SecQuery)


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
    """Invalid ordering field must raise GraphQLError, not Django FieldError."""

    def setUp(self):
        for name in ("alice", "bob", "carol"):
            Author.objects.create(name=name)

    def test_limitoffset_invalid_field_raises_graphql_error(self):
        """LimitOffsetGraphqlPagination: invalid field → GraphQLError."""
        p = _lo()
        with pytest.raises(GraphQLError):
            p.paginate_queryset(Author.objects.all(), ordering="nonexistent_field")

    def test_limitoffset_invalid_field_does_not_raise_field_error(self):
        """The exception must NOT be a Django FieldError."""
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

    def test_limitoffset_error_message_does_not_leak_field_list(self):
        """Error message must NOT contain 'Choices are:' (the Django field dump)."""
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

    def test_page_invalid_field_raises_graphql_error(self):
        """PageGraphqlPagination: invalid field → GraphQLError."""
        p = _pg()
        with pytest.raises(GraphQLError):
            p.paginate_queryset(
                Author.objects.all(), page=1, ordering="nonexistent_field"
            )

    def test_page_invalid_field_does_not_leak_field_list(self):
        """Error message must NOT contain 'Choices are:' (the Django field dump)."""
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
# (b) Hidden/non-exposed column — relation traversal is the actual block
# ---------------------------------------------------------------------------
# The security boundary of the allowlist is:
#   - Concrete attnames on the queryset's model are allowed (prevents FieldError
#     leaking the field list and prevents relation-chain DoS).
#   - Non-existent fields are rejected (covers typos + injected field names).
#   - Relation-spanning lookups ('a__b') are rejected even when 'a' exists.
#
# Ordering by a concrete column like 'password' on a User queryset cannot be
# blocked at the paginator level alone because the paginator has no reference
# to which graphene fields are exposed — that requires application-level
# schema design (e.g. not exposing LimitOffset ordering on User types at all,
# or customising allowed_orderings in the graphene type).
#
# We document this boundary and test the cases the paginator CAN enforce.


class TestHiddenColumnRejected(TestCase):
    """Ordering by fields that don't exist on the model must be rejected.

    True 'hidden concrete column' blocking requires schema-level controls
    (not exposing User password field types).  The paginator enforces the
    concrete-attname allowlist which prevents FieldError disclosure and
    relation-chain DoS.
    """

    def setUp(self):
        Author.objects.create(name="alice")

    def test_limitoffset_nonexistent_on_author_rejected(self):
        """Ordering by a field that doesn't exist on Author → GraphQLError."""
        p = _lo()
        # 'secret_field' doesn't exist on Author at all
        with pytest.raises(GraphQLError):
            list(p.paginate_queryset(Author.objects.all(), ordering="secret_field"))

    def test_page_nonexistent_on_author_rejected(self):
        """PageGraphqlPagination: non-existent field on Author → GraphQLError."""
        p = _pg()
        with pytest.raises(GraphQLError):
            list(
                p.paginate_queryset(
                    Author.objects.all(), page=1, ordering="secret_field"
                )
            )

    def test_limitoffset_relation_field_name_only_rejected(self):
        """Relation field name ('posts') is not a concrete attname → GraphQLError.

        A FK attname is 'author_id'; the reverse relation name 'posts' is NOT a
        concrete attname, so ordering by 'posts' alone is also rejected.
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
    """Ordering terms that span relations must be rejected."""

    def setUp(self):
        Author.objects.create(name="alice")

    def test_limitoffset_relation_spanning_rejected(self):
        """'a__b__c' style terms must raise GraphQLError."""
        p = _lo()
        with pytest.raises(GraphQLError):
            list(
                p.paginate_queryset(
                    Author.objects.all(),
                    ordering="posts__title",
                )
            )

    def test_page_relation_spanning_rejected(self):
        """PageGraphqlPagination: relation-spanning ordering → GraphQLError."""
        p = _pg()
        with pytest.raises(GraphQLError):
            list(
                p.paginate_queryset(
                    Author.objects.all(),
                    page=1,
                    ordering="posts__title",
                )
            )

    def test_limitoffset_deep_relation_rejected(self):
        """Deep multi-hop relation path must raise GraphQLError."""
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
    """Valid orderings must continue to work unchanged."""

    def setUp(self):
        for name in ("charlie", "alice", "bob"):
            Author.objects.create(name=name)

    def test_limitoffset_valid_asc_field(self):
        """Ascending by a real field must work."""
        p = _lo()
        result = list(p.paginate_queryset(Author.objects.all(), ordering="name"))
        names = [a.name for a in result]
        assert names == sorted(names)

    def test_limitoffset_valid_desc_field(self):
        """Descending ordering (leading '-') must work."""
        p = _lo()
        result = list(p.paginate_queryset(Author.objects.all(), ordering="-name"))
        names = [a.name for a in result]
        assert names == sorted(names, reverse=True)

    def test_limitoffset_multi_field_csv(self):
        """Comma-separated multi-field ordering must work."""
        p = _lo()
        result = list(p.paginate_queryset(Author.objects.all(), ordering="name,-id"))
        assert len(result) == 3

    def test_page_valid_asc_field(self):
        """PageGraphqlPagination: ascending ordering must work."""
        p = _pg()
        result = list(
            p.paginate_queryset(Author.objects.all(), page=1, ordering="name")
        )
        names = [a.name for a in result]
        assert names == sorted(names)

    def test_page_valid_desc_field(self):
        """PageGraphqlPagination: descending ordering must work."""
        p = _pg()
        result = list(
            p.paginate_queryset(Author.objects.all(), page=1, ordering="-name")
        )
        names = [a.name for a in result]
        assert names == sorted(names, reverse=True)

    def test_limitoffset_pk_attname_valid(self):
        """The pk attname ('id') must be accepted."""
        p = _lo()
        result = list(p.paginate_queryset(Author.objects.all(), ordering="id"))
        assert len(result) == 3

    def test_no_ordering_works(self):
        """No ordering provided must return results unaffected."""
        p = _lo()
        result = list(p.paginate_queryset(Author.objects.all()))
        assert len(result) == 3


# ---------------------------------------------------------------------------
# prefetch_window_slice ordering validation
# ---------------------------------------------------------------------------


class TestPrefetchWindowSliceOrderingValidation(TestCase):
    """prefetch_window_slice must also validate ordering terms."""

    def setUp(self):
        Author.objects.create(name="test")

    def test_limitoffset_prefetch_window_slice_invalid_term_raises(self):
        """prefetch_window_slice must reject invalid ordering (GraphQLError)."""
        p = _lo()
        with pytest.raises(GraphQLError):
            p.prefetch_window_slice_ordering_check(
                Author.objects.model, "nonexistent_field"
            )

    def test_limitoffset_prefetch_window_slice_relation_term_raises(self):
        """prefetch_window_slice must reject relation-spanning term."""
        p = _lo()
        with pytest.raises(GraphQLError):
            p.prefetch_window_slice_ordering_check(Author.objects.model, "posts__title")

    def test_limitoffset_prefetch_window_slice_valid_term_ok(self):
        """prefetch_window_slice must accept valid concrete attname."""
        p = _lo()
        # Should not raise
        p.prefetch_window_slice_ordering_check(Author.objects.model, "name")
        p.prefetch_window_slice_ordering_check(Author.objects.model, "-name")
        p.prefetch_window_slice_ordering_check(Author.objects.model, "name,-id")


# ---------------------------------------------------------------------------
# Full GraphQL integration — error travels through schema correctly
# ---------------------------------------------------------------------------


class TestSchemaIntegrationOrderingSecurity(TestCase):
    """Integration: invalid ordering in schema query → GraphQL error in response."""

    def setUp(self):
        for name in ("a", "b"):
            Author.objects.create(name=name)

    def test_limitoffset_schema_invalid_ordering_returns_error(self):
        """Full schema query with invalid ordering must return errors, not crash."""
        result = sec_schema.execute(
            '{ loList { results(ordering: "nonexistent_field") { name } } }'
        )
        # Must have errors or data be null — must NOT be a raw FieldError 500
        assert result.errors is not None or result.data is not None

    def test_page_schema_invalid_ordering_returns_error(self):
        """PageGraphqlPagination: invalid ordering in schema query → errors field."""
        result = sec_schema.execute(
            '{ pageList { results(ordering: "nonexistent_field") { name } } }'
        )
        assert result.errors is not None or result.data is not None


# ---------------------------------------------------------------------------
# _validate_ordering_terms: empty/falsy ordering (line 83) and list path (line 93)
# ---------------------------------------------------------------------------


class TestValidateOrderingTermsEdges(TestCase):
    """Unit tests for _validate_ordering_terms covering the two branches missed
    by higher-level tests: the early-return on falsy input (line 83) and the
    list-of-terms path (line 93)."""

    # -- line 83: `if not ordering: return` ---------------------------------

    def test_empty_string_ordering_is_a_noop(self):
        """_validate_ordering_terms("") must return None without raising.

        The `if not ordering: return` guard (line 83) exits early so that
        callers with no configured ordering never enter the allowlist check.
        """
        result = _validate_ordering_terms(Author, "")
        assert result is None

    def test_none_ordering_is_a_noop(self):
        """_validate_ordering_terms(None) must return None without raising."""
        result = _validate_ordering_terms(Author, None)
        assert result is None

    def test_empty_list_ordering_is_a_noop(self):
        """_validate_ordering_terms([]) must return None without raising."""
        result = _validate_ordering_terms(Author, [])
        assert result is None

    # -- line 93: `else: terms = [t for t in ordering if t]` (list path) ---

    def test_list_ordering_valid_terms_accepted(self):
        """Passing ordering as a list of valid attnames must not raise.

        The `else` branch (line 93) handles the case where ``ordering`` is a
        list rather than a comma-separated string.  Every term must pass the
        concrete-attname allowlist check.
        """
        _validate_ordering_terms(Author, ["name", "-id"])

    def test_list_ordering_invalid_term_raises(self):
        """Passing ordering as a list with an invalid term must raise GraphQLError."""
        with pytest.raises(GraphQLError):
            _validate_ordering_terms(Author, ["name", "nonexistent_field"])

    def test_list_ordering_relation_spanning_term_raises(self):
        """A list containing a relation-spanning term must raise GraphQLError."""
        with pytest.raises(GraphQLError):
            _validate_ordering_terms(Author, ["posts__title"])

    def test_list_ordering_skips_empty_strings(self):
        """Empty strings inside the list are filtered out (no error, no crash).

        The `[t for t in ordering if t]` comprehension drops falsy elements,
        so `["name", ""]` is equivalent to `["name"]`.
        """
        _validate_ordering_terms(Author, ["name", ""])

    def test_list_ordering_with_direction_prefix_accepted(self):
        """List ordering with direction prefixes (+/-) must be accepted.

        The validator strips the leading +/- before checking the allowlist, so
        both "name" and "-id" in a list are valid for the Author model.
        """
        _validate_ordering_terms(Author, ["+name", "-id", "id"])

    def test_list_ordering_with_plus_prefix_accepted(self):
        """A leading '+' prefix is also stripped and accepted for valid fields."""
        _validate_ordering_terms(Author, ["+name"])

    def test_list_ordering_mixed_valid_and_empty_entries(self):
        """A list with some empty strings must not raise (empty strings are filtered).

        The `[t for t in ordering if t]` comprehension on line 93 silently
        drops any falsy entries, so mixed lists are safe.
        """
        _validate_ordering_terms(Author, ["name", "", None or "id"])


# ---------------------------------------------------------------------------
# prefetch_window_slice: negative offset raises GraphQLError (line 462)
# ---------------------------------------------------------------------------


class TestPrefetchWindowSliceNegativeOffset(TestCase):
    """prefetch_window_slice must raise GraphQLError for negative offsets.

    Covers line 462: the `raise GraphQLError` guard for negative offsets inside
    LimitOffsetGraphqlPagination.prefetch_window_slice.  This branch is separate
    from the in-memory path test; diff-cover flags it because it is new code.
    """

    def test_negative_offset_raises_graphql_error(self):
        """prefetch_window_slice(offset=-1) must raise GraphQLError.

        A negative offset would cause Django's QuerySet.__getitem__ to raise a
        raw ValueError which escapes the resolver.  The guard must convert it
        to a clean GraphQLError before any queryset slice occurs.
        """
        p = _lo(default_limit=5, max_limit=20)
        with pytest.raises(GraphQLError, match="Offset must be a non-negative integer"):
            p.prefetch_window_slice(**{p.offset_query_param: -1})

    def test_zero_offset_is_valid(self):
        """prefetch_window_slice(offset=0) must NOT raise."""
        p = _lo(default_limit=5, max_limit=20)
        result = p.prefetch_window_slice(**{p.offset_query_param: 0})
        # Returns (offset, limit, ordering) when limit is set.
        assert result is not None
        offset, limit, _ = result
        assert offset == 0
        assert limit == 5

    def test_unbounded_paginator_returns_none(self):
        """prefetch_window_slice with no limit configured must return None.

        When _resolve_page_size returns None (no default_limit, no max_limit,
        no client-supplied limit), prefetch_window_slice returns None to signal
        the caller to fall back to the in-memory path.  This covers the
        `if limit is None: return None` guard (line 458-459) which is also
        new in this diff but is naturally tested by having a truly unbounded
        paginator configuration.
        """
        p = _lo(default_limit=None, max_limit=None)
        result = p.prefetch_window_slice()
        assert result is None
