# -*- coding: utf-8 -*-
"""Internals of the pagination layer: in-memory ordering, "NativePaginationField",
"to_dict" / "to_graphql_fields" and "_get_count".
"""

from types import SimpleNamespace

import pytest
from django.test import TestCase

from django_graphex.base_types import DjangoListObjectBase
from django_graphex.paginations.pagination import (
    CursorGraphqlPagination,
    LimitOffsetGraphqlPagination,
    PageGraphqlPagination,
    _inmemory_order,
    _sort_key,
)
from django_graphex.paginations.utils import (
    _get_count,
    _positive_int,
)
from tests.models import Author


# --------------------------------------------------------------------------- #
# _sort_key / _inmemory_order                                                  #
# --------------------------------------------------------------------------- #
def test_sort_key_is_comparison_safe_with_none() -> None:
    """Assert "_sort_key" makes None sortable alongside ints without raising.

    If this fails, sorting a mixed None/int column crashes with a TypeError
    instead of placing None values last.
    """
    assert _sort_key(None) == (True, 0)
    assert _sort_key(5) == (False, 5)
    # Sorting a mixed list does not raise.
    assert sorted([5, None, 1], key=_sort_key) == [1, 5, None]


def test_inmemory_order_empty_ordering_passthrough() -> None:
    """Assert an empty ordering string returns the items unchanged.

    If this fails, callers with no ordering configured get an unexpected
    reordering or a crash instead of the original sequence.
    """
    items = [SimpleNamespace(x=2), SimpleNamespace(x=1)]
    assert _inmemory_order(items, "") == items


def test_inmemory_order_ascending_and_descending() -> None:
    """Assert "_inmemory_order" honors both plain and "-"-prefixed fields.

    If this fails, ascending or descending in-memory ordering silently
    produces the wrong sequence.
    """
    items = [SimpleNamespace(x=3), SimpleNamespace(x=1), SimpleNamespace(x=2)]
    asc = [o.x for o in _inmemory_order(items, "x")]
    desc = [o.x for o in _inmemory_order(items, "-x")]
    assert asc == [1, 2, 3]
    assert desc == [3, 2, 1]


def test_inmemory_order_handles_none_values() -> None:
    """Assert "_inmemory_order" tolerates None values in the ordered field.

    If this fails, a None value in the sorted attribute raises a TypeError
    instead of sorting last.
    """
    items = [SimpleNamespace(x=2), SimpleNamespace(x=None), SimpleNamespace(x=1)]
    ordered = [o.x for o in _inmemory_order(items, "x")]
    # None sorts last in ascending order, and no TypeError is raised.
    assert ordered == [1, 2, None]


def test_inmemory_order_multikey_with_iterable_terms() -> None:
    """Assert "_inmemory_order" accepts a list of fields as a multi-key sort.

    If this fails, passing several ordering terms as an iterable does not
    apply them in sequence as tiebreakers.
    """
    items = [
        SimpleNamespace(a=1, b=2),
        SimpleNamespace(a=1, b=1),
        SimpleNamespace(a=0, b=9),
    ]
    ordered = [(o.a, o.b) for o in _inmemory_order(items, ["a", "b"])]
    assert ordered == [(0, 9), (1, 1), (1, 2)]


# --------------------------------------------------------------------------- #
# _positive_int / _get_count                                                   #
# --------------------------------------------------------------------------- #
def test_positive_int_passthrough_falsey() -> None:
    """Assert a falsy input short-circuits "_positive_int" without validation.

    If this fails, falsy values like 0 or "" get coerced or rejected instead
    of passing through untouched.
    """
    assert _positive_int(0) == 0
    assert _positive_int("") == ""


def test_positive_int_negative_raises() -> None:
    """Assert "_positive_int" rejects a negative integer.

    If this fails, negative limits or offsets are silently accepted instead
    of raising.
    """
    with pytest.raises(ValueError):
        _positive_int(-1)


def test_positive_int_strict_zero_string_raises() -> None:
    """Assert strict mode rejects the string "0" once parsed to zero.

    If this fails, a truthy zero-string bypasses strict validation instead
    of being parsed and rejected.
    """
    # "0" is truthy as a string, so it is parsed to 0 and rejected when strict.
    with pytest.raises(ValueError):
        _positive_int("0", strict=True)


def test_positive_int_cutoff_clamps() -> None:
    """Assert "_positive_int" clamps a value above cutoff down to the cutoff.

    If this fails, an oversized limit is not capped and can bypass a
    configured maximum.
    """
    assert _positive_int(100, cutoff=10) == 10


def test_get_count_queryset_and_list(db: None) -> None:
    """Assert "_get_count" counts a queryset via the database and a list via len.

    If this fails, counting falls back incorrectly between the queryset and
    plain-list code paths.

    Args:
        db: The pytest-django fixture that grants database access for the test.
    """
    Author.objects.create(name="a")
    assert _get_count(Author.objects.all()) == 1
    assert _get_count([1, 2, 3]) == 3  # falls back to len()


# --------------------------------------------------------------------------- #
# In-DB ordering through paginate_queryset (queryset branch + order_by)        #
# --------------------------------------------------------------------------- #
class PaginateQuerysetDbTest(TestCase):
    """Exercise "paginate_queryset" on real querysets for each paginator kind.

    Covers "LimitOffsetGraphqlPagination", "PageGraphqlPagination" and
    "CursorGraphqlPagination" against a real Author queryset.
    """

    def setUp(self) -> None:
        """Seed three authors so ordering and slicing behavior is observable.

        Creates authors "c", "a" and "b" in that insertion order.
        """
        for name in ("c", "a", "b"):
            Author.objects.create(name=name)

    def test_limit_offset_orders_and_slices_queryset(self) -> None:
        """Assert limit/offset pagination orders by "name" then slices to the limit.

        If this fails, the queryset branch of "paginate_queryset" stops
        applying "order_by" before slicing, returning DB-default order.
        """
        p = LimitOffsetGraphqlPagination(default_limit=2, max_limit=10, ordering="name")
        result = list(p.paginate_queryset(Author.objects.all()))
        self.assertEqual([a.name for a in result], ["a", "b"])

    def test_limit_offset_comma_ordering(self) -> None:
        """Assert a comma-separated ordering string applies multiple order_by fields.

        If this fails, "ordering=name,id" is not split and passed as
        multiple order_by terms.
        """
        p = LimitOffsetGraphqlPagination(default_limit=10, max_limit=10)
        result = list(p.paginate_queryset(Author.objects.all(), ordering="name,id"))
        self.assertEqual([a.name for a in result], ["a", "b", "c"])

    def test_page_negative_page_counts_from_end(self) -> None:
        """Assert a negative page number counts pages from the end of the set.

        If this fails, page=-1 does not resolve to the last page and instead
        errors or returns the wrong slice.
        """
        p = PageGraphqlPagination(page_size=1, max_page_size=10)
        # page=-1 -> last page.
        result = list(
            p.paginate_queryset(Author.objects.all().order_by("name"), page=-1)
        )
        self.assertEqual(len(result), 1)

    def test_page_comma_ordering_queryset(self) -> None:
        """Assert page pagination honors a comma-separated multi-field ordering.

        If this fails, "PageGraphqlPagination" ignores secondary ordering
        terms passed as a comma-separated string.
        """
        p = PageGraphqlPagination(page_size=10, max_page_size=10)
        result = list(
            p.paginate_queryset(Author.objects.all(), page=1, ordering="name,id")
        )
        self.assertEqual([a.name for a in result], ["a", "b", "c"])

    def test_cursor_queryset_with_cursor_filter(self) -> None:
        """Assert cursor pagination resumes after an encoded cursor on a queryset.

        If this fails, "CursorGraphqlPagination" either re-returns already
        seen rows or fails to decode the cursor filter correctly.
        """
        p = CursorGraphqlPagination(ordering="name", page_size=10)
        first = list(p.paginate_queryset(Author.objects.all(), first=1))
        self.assertEqual(first[0].name, "a")
        token = CursorGraphqlPagination.encode_cursor(first[-1].name)
        after = list(p.paginate_queryset(Author.objects.all(), first=10, cursor=token))
        self.assertEqual([a.name for a in after], ["b", "c"])


# --------------------------------------------------------------------------- #
# to_dict / to_graphql_fields shape                                           #
# --------------------------------------------------------------------------- #
def test_limit_offset_to_dict_and_fields() -> None:
    """Assert limit/offset "to_dict" and "to_graphql_fields" expose the right keys.

    If this fails, the schema-facing field names or the settings snapshot
    drift out of sync with what "LimitOffsetGraphqlPagination" actually uses.
    """
    p = LimitOffsetGraphqlPagination(default_limit=5, max_limit=20)
    d = p.to_dict()
    assert d["default_limit"] == 5 and d["max_limit"] == 20
    fields = p.to_graphql_fields()
    assert {"limit", "offset", "ordering"} <= set(fields)


def test_page_to_dict_and_fields_with_size_param() -> None:
    """Assert page pagination "to_dict" and "to_graphql_fields" respect the size param.

    If this fails, a custom "page_size_query_param" is not reflected in
    either the settings snapshot or the exposed GraphQL field names.
    """
    p = PageGraphqlPagination(page_size=5, page_size_query_param="page_size")
    d = p.to_dict()
    assert d["page_size"] == 5
    fields = p.to_graphql_fields()
    assert "page" in fields and "page_size" in fields


def test_cursor_to_graphql_fields() -> None:
    """Assert cursor pagination exposes "first" and "cursor" as GraphQL fields.

    If this fails, "CursorGraphqlPagination" stops advertising the fields
    clients need to page through a cursor-based connection.
    """
    p = CursorGraphqlPagination()
    fields = p.to_graphql_fields()
    assert "first" in fields and "cursor" in fields


def test_base_paginator_abstract_methods_raise() -> None:
    """Assert the base paginator raises NotImplementedError on its abstract methods.

    If this fails, a concrete paginator subclass could silently omit an
    override and still appear to work, masking the missing implementation.
    """
    from django_graphex.paginations.pagination import (
        BaseDjangoGraphqlPagination,
    )

    base = BaseDjangoGraphqlPagination()
    with pytest.raises(NotImplementedError):
        base.to_graphql_fields()
    with pytest.raises(NotImplementedError):
        base.to_dict()
    with pytest.raises(NotImplementedError):
        base.paginate_queryset([])
    # The base get_page_info_field returns None (no metadata).
    assert base.get_page_info_field(None) is None


# --------------------------------------------------------------------------- #
# NativePaginationField.list_resolver only paginates a list base              #
# (S-del-backend-11: the graphene GenericPaginationField was deleted; the      #
#  backend-neutral slicing logic lives on the native NativePaginationField.)   #
# --------------------------------------------------------------------------- #
def test_native_pagination_field_resolver_non_list_base_returns_none() -> None:
    """Assert "list_resolver" returns None when root is not a "DjangoListObjectBase".

    If this fails, the backend-neutral resolver crashes or returns a bogus
    value instead of safely short-circuiting on an unexpected root type.
    """
    from django_graphex.paginations.utils import NativePaginationField

    field = NativePaginationField(
        type=None, paginator=LimitOffsetGraphqlPagination(default_limit=5)
    )
    # root is not a DjangoListObjectBase -> None.
    assert field.list_resolver(None, "not-a-base", None) is None


def test_native_pagination_field_resolver_paginates_list_base() -> None:
    """Assert "list_resolver" paginates the results of a "DjangoListObjectBase".

    If this fails, the backend-neutral slicing logic on
    "NativePaginationField" stops applying the configured limit to the
    wrapped list of results.
    """
    from django_graphex.paginations.utils import NativePaginationField

    field = NativePaginationField(
        type=None,
        paginator=LimitOffsetGraphqlPagination(default_limit=2, max_limit=10),
    )
    base = DjangoListObjectBase(
        results=list(range(5)), count=5, results_field_name="results"
    )
    out = field.list_resolver(None, base, None)
    assert out == [0, 1]
