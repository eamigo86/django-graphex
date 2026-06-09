# -*- coding: utf-8 -*-
"""Internals of the pagination layer: in-memory ordering, ``GenericPaginationField``,
``to_dict`` / ``to_graphql_fields`` and ``_get_count``.
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
    _nonzero_int,
    _positive_int,
)
from tests.models import Author


# --------------------------------------------------------------------------- #
# _sort_key / _inmemory_order                                                  #
# --------------------------------------------------------------------------- #
def test_sort_key_is_comparison_safe_with_none():
    # The key makes None comparable to ints without a TypeError.
    assert _sort_key(None) == (True, 0)
    assert _sort_key(5) == (False, 5)
    # Sorting a mixed list does not raise.
    assert sorted([5, None, 1], key=_sort_key) == [1, 5, None]


def test_inmemory_order_empty_ordering_passthrough():
    items = [SimpleNamespace(x=2), SimpleNamespace(x=1)]
    assert _inmemory_order(items, "") == items


def test_inmemory_order_ascending_and_descending():
    items = [SimpleNamespace(x=3), SimpleNamespace(x=1), SimpleNamespace(x=2)]
    asc = [o.x for o in _inmemory_order(items, "x")]
    desc = [o.x for o in _inmemory_order(items, "-x")]
    assert asc == [1, 2, 3]
    assert desc == [3, 2, 1]


def test_inmemory_order_handles_none_values():
    items = [SimpleNamespace(x=2), SimpleNamespace(x=None), SimpleNamespace(x=1)]
    ordered = [o.x for o in _inmemory_order(items, "x")]
    # None sorts last in ascending order, and no TypeError is raised.
    assert ordered == [1, 2, None]


def test_inmemory_order_multikey_with_iterable_terms():
    items = [
        SimpleNamespace(a=1, b=2),
        SimpleNamespace(a=1, b=1),
        SimpleNamespace(a=0, b=9),
    ]
    ordered = [(o.a, o.b) for o in _inmemory_order(items, ["a", "b"])]
    assert ordered == [(0, 9), (1, 1), (1, 2)]


# --------------------------------------------------------------------------- #
# _positive_int / _nonzero_int / _get_count                                    #
# --------------------------------------------------------------------------- #
def test_positive_int_passthrough_falsey():
    # A falsy value short-circuits and is returned untouched (no validation).
    assert _positive_int(0) == 0
    assert _positive_int("") == ""


def test_positive_int_negative_raises():
    with pytest.raises(ValueError):
        _positive_int(-1)


def test_positive_int_strict_zero_string_raises():
    # "0" is truthy as a string, so it is parsed to 0 and rejected when strict.
    with pytest.raises(ValueError):
        _positive_int("0", strict=True)


def test_positive_int_cutoff_clamps():
    assert _positive_int(100, cutoff=10) == 10


def test_nonzero_int_strict_zero_string_raises():
    with pytest.raises(ValueError):
        _nonzero_int("0", strict=True)


def test_nonzero_int_cutoff_clamps():
    assert _nonzero_int(100, cutoff=10) == 10
    assert _nonzero_int("") == ""


def test_get_count_queryset_and_list(db):
    Author.objects.create(name="a")
    assert _get_count(Author.objects.all()) == 1
    assert _get_count([1, 2, 3]) == 3  # falls back to len()


# --------------------------------------------------------------------------- #
# In-DB ordering through paginate_queryset (queryset branch + order_by)        #
# --------------------------------------------------------------------------- #
class PaginateQuerysetDbTest(TestCase):
    def setUp(self):
        for name in ("c", "a", "b"):
            Author.objects.create(name=name)

    def test_limit_offset_orders_and_slices_queryset(self):
        p = LimitOffsetGraphqlPagination(default_limit=2, max_limit=10, ordering="name")
        result = list(p.paginate_queryset(Author.objects.all()))
        self.assertEqual([a.name for a in result], ["a", "b"])

    def test_limit_offset_comma_ordering(self):
        p = LimitOffsetGraphqlPagination(default_limit=10, max_limit=10)
        result = list(p.paginate_queryset(Author.objects.all(), ordering="name,id"))
        self.assertEqual([a.name for a in result], ["a", "b", "c"])

    def test_page_negative_page_counts_from_end(self):
        p = PageGraphqlPagination(page_size=1, max_page_size=10)
        # page=-1 -> last page.
        result = list(
            p.paginate_queryset(Author.objects.all().order_by("name"), page=-1)
        )
        self.assertEqual(len(result), 1)

    def test_page_comma_ordering_queryset(self):
        p = PageGraphqlPagination(page_size=10, max_page_size=10)
        result = list(
            p.paginate_queryset(Author.objects.all(), page=1, ordering="name,id")
        )
        self.assertEqual([a.name for a in result], ["a", "b", "c"])

    def test_cursor_queryset_with_cursor_filter(self):
        p = CursorGraphqlPagination(ordering="name", page_size=10)
        first = list(p.paginate_queryset(Author.objects.all(), first=1))
        self.assertEqual(first[0].name, "a")
        token = CursorGraphqlPagination.encode_cursor(first[-1].name)
        after = list(p.paginate_queryset(Author.objects.all(), first=10, cursor=token))
        self.assertEqual([a.name for a in after], ["b", "c"])


# --------------------------------------------------------------------------- #
# to_dict / to_graphql_fields shape                                           #
# --------------------------------------------------------------------------- #
def test_limit_offset_to_dict_and_fields():
    p = LimitOffsetGraphqlPagination(default_limit=5, max_limit=20)
    d = p.to_dict()
    assert d["default_limit"] == 5 and d["max_limit"] == 20
    fields = p.to_graphql_fields()
    assert {"limit", "offset", "ordering"} <= set(fields)


def test_page_to_dict_and_fields_with_size_param():
    p = PageGraphqlPagination(page_size=5, page_size_query_param="page_size")
    d = p.to_dict()
    assert d["page_size"] == 5
    fields = p.to_graphql_fields()
    assert "page" in fields and "page_size" in fields


def test_cursor_to_graphql_fields():
    p = CursorGraphqlPagination()
    fields = p.to_graphql_fields()
    assert "first" in fields and "cursor" in fields


def test_base_paginator_abstract_methods_raise():
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
# GenericPaginationField.list_resolver only paginates a list base             #
# --------------------------------------------------------------------------- #
def test_generic_pagination_field_resolver_non_list_base_returns_none():
    from django_graphex.paginations.utils import GenericPaginationField

    field = GenericPaginationField.__new__(GenericPaginationField)
    field.paginator_instance = LimitOffsetGraphqlPagination(default_limit=5)
    # root is not a DjangoListObjectBase -> None.
    assert field.list_resolver(None, "not-a-base", None) is None


def test_generic_pagination_field_resolver_paginates_list_base():
    from django_graphex.paginations.utils import GenericPaginationField

    field = GenericPaginationField.__new__(GenericPaginationField)
    field.paginator_instance = LimitOffsetGraphqlPagination(
        default_limit=2, max_limit=10
    )
    base = DjangoListObjectBase(
        results=list(range(5)), count=5, results_field_name="results"
    )
    out = field.list_resolver(None, base, None)
    assert out == [0, 1]
