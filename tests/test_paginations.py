# -*- coding: utf-8 -*-
"""Validation tests for the three pagination strategies.

Pagination ships in ``django_graphex.paginations`` and is used through
``DjangoListObjectType(Meta.pagination=...)`` + ``DjangoListObjectField``; the
pagination arguments live on the ``results`` subfield.

These tests pin down each strategy:

* ``LimitOffsetGraphqlPagination`` — limit/offset slicing + ordering.
* ``PageGraphqlPagination`` — page/page_size paging + ordering.
* ``CursorGraphqlPagination`` — forward keyset cursor paging + ``pageInfo``.
"""

import graphene
from django.test import TestCase
from graphene import Schema

from django_graphex import (
    CursorGraphqlPagination,
    DjangoListObjectField,
    DjangoListObjectType,
    LimitOffsetGraphqlPagination,
    PageGraphqlPagination,
)

from .models import BasicModel


# --------------------------------------------------------------------------- #
# Schema                                                                        #
# --------------------------------------------------------------------------- #
class LimitOffsetType(DjangoListObjectType):
    class Meta:
        model = BasicModel
        pagination = LimitOffsetGraphqlPagination(default_limit=5)


class PageType(DjangoListObjectType):
    class Meta:
        model = BasicModel
        pagination = PageGraphqlPagination(
            page_size=5, page_size_query_param="pageSize"
        )


class CursorType(DjangoListObjectType):
    class Meta:
        model = BasicModel
        pagination = CursorGraphqlPagination(ordering="id")


class Query(graphene.ObjectType):
    # Canonical mechanism (documented): pagination args live on `results`.
    limit_offset = DjangoListObjectField(LimitOffsetType)
    page = DjangoListObjectField(PageType)
    cursor = DjangoListObjectField(CursorType)


schema = Schema(query=Query)

# 12 deterministic rows: ids 1..12 map to text "M00".."M11" (insertion order).
ROWS = 12


def _texts(results):
    return [row["text"] for row in results]


def _exec(query):
    result = schema.execute(query)
    assert result.errors is None, result.errors
    return result.data


class _Base(TestCase):
    def setUp(self):
        for i in range(ROWS):
            BasicModel.objects.create(text="M%02d" % i)


# --------------------------------------------------------------------------- #
# LimitOffsetGraphqlPagination — WORKS                                          #
# --------------------------------------------------------------------------- #
class LimitOffsetClassTest(_Base):
    def test_limit_and_offset(self):
        data = _exec(
            "query { limitOffset { results(limit: 3, offset: 2) { text } totalCount } }"
        )["limitOffset"]
        self.assertEqual(data["totalCount"], ROWS)
        self.assertEqual(_texts(data["results"]), ["M02", "M03", "M04"])

    def test_default_limit_applied(self):
        data = _exec("query { limitOffset { results { text } totalCount } }")[
            "limitOffset"
        ]
        # default_limit=5
        self.assertEqual(len(data["results"]), 5)
        self.assertEqual(_texts(data["results"]), ["M00", "M01", "M02", "M03", "M04"])

    def test_offset_only(self):
        data = _exec(
            "query { limitOffset { results(limit: 4, offset: 10) { text } } }"
        )["limitOffset"]
        self.assertEqual(_texts(data["results"]), ["M10", "M11"])

    def test_ordering_descending(self):
        data = _exec(
            'query { limitOffset { results(limit: 3, ordering: "-id") { text } } }'
        )["limitOffset"]
        self.assertEqual(_texts(data["results"]), ["M11", "M10", "M09"])


# --------------------------------------------------------------------------- #
# PageGraphqlPagination — WORKS                                                 #
# --------------------------------------------------------------------------- #
class PageClassTest(_Base):
    def test_first_page_default(self):
        data = _exec("query { page { results { text } totalCount } }")["page"]
        self.assertEqual(data["totalCount"], ROWS)
        # page_size=5, page 1
        self.assertEqual(_texts(data["results"]), ["M00", "M01", "M02", "M03", "M04"])

    def test_specific_page_and_size(self):
        data = _exec(
            "query { page { results(page: 2, pageSize: 4) { text } totalCount } }"
        )["page"]
        self.assertEqual(_texts(data["results"]), ["M04", "M05", "M06", "M07"])

    def test_last_partial_page(self):
        data = _exec("query { page { results(page: 3, pageSize: 5) { text } } }")[
            "page"
        ]
        self.assertEqual(_texts(data["results"]), ["M10", "M11"])

    def test_ordering(self):
        data = _exec(
            'query { page { results(page: 1, pageSize: 3, ordering: "-id") { text } } }'
        )["page"]
        self.assertEqual(_texts(data["results"]), ["M11", "M10", "M09"])


# --------------------------------------------------------------------------- #
# CursorGraphqlPagination — WORKS (forward keyset cursor)                        #
# --------------------------------------------------------------------------- #
class CursorClassTest(_Base):
    def test_first_page(self):
        data = _exec("query { cursor { results(first: 5) { text } totalCount } }")[
            "cursor"
        ]
        self.assertEqual(data["totalCount"], ROWS)
        # CursorType orders by ascending id -> M00..M04
        self.assertEqual(_texts(data["results"]), ["M00", "M01", "M02", "M03", "M04"])

    def test_forward_paging_with_cursor(self):
        first = _exec("query { cursor { results(first: 5) { id text } } }")["cursor"][
            "results"
        ]
        boundary_id = first[-1]["id"]
        token = CursorGraphqlPagination.encode_cursor(boundary_id)

        nxt = _exec(
            'query { cursor { results(first: 5, cursor: "%s") { text } } }' % token
        )["cursor"]["results"]
        # No overlap with the first page; continues in order.
        self.assertEqual(_texts(nxt), ["M05", "M06", "M07", "M08", "M09"])

    def test_last_partial_page(self):
        token = CursorGraphqlPagination.encode_cursor(9)  # after the 9th id
        data = _exec(
            'query { cursor { results(first: 5, cursor: "%s") { text } } }' % token
        )["cursor"]
        self.assertEqual(_texts(data["results"]), ["M09", "M10", "M11"])

    def test_invalid_cursor_errors(self):
        result = schema.execute(
            'query { cursor { results(cursor: "not-a-valid-cursor") { text } } }'
        )
        self.assertIsNotNone(result.errors)

    def test_encode_decode_roundtrip(self):
        self.assertEqual(
            CursorGraphqlPagination.decode_cursor(
                CursorGraphqlPagination.encode_cursor(42)
            ),
            "42",
        )


# --------------------------------------------------------------------------- #
# CursorGraphqlPagination — pageInfo                                            #
# --------------------------------------------------------------------------- #
class CursorPageInfoTest(_Base):
    def _cursor(self, value):
        return CursorGraphqlPagination.encode_cursor(value)

    def test_cursor_exposes_pageinfo(self):
        # AC1: the cursor list type has a `pageInfo` field.
        fields = schema.graphql_schema.type_map["CursorType"].fields
        self.assertIn("pageInfo", fields)

    def test_limitoffset_and_page_have_no_pageinfo(self):
        # AC1: LimitOffset / Page list types do NOT expose `pageInfo`.
        for type_name in ("LimitOffsetType", "PageType"):
            fields = schema.graphql_schema.type_map[type_name].fields
            self.assertNotIn("pageInfo", fields)

    def test_pageinfo_endcursor_drives_next_page(self):
        # AC2: endCursor of page N -> contiguous page N+1, no overlap.
        page1 = _exec(
            "query { cursor { results(first: 5) { text } pageInfo(first: 5) "
            "{ endCursor } } }"
        )["cursor"]
        self.assertEqual(_texts(page1["results"]), ["M00", "M01", "M02", "M03", "M04"])
        end = page1["pageInfo"]["endCursor"]

        page2 = _exec(
            'query { cursor { results(first: 5, cursor: "%s") { text } } }' % end
        )["cursor"]
        self.assertEqual(_texts(page2["results"]), ["M05", "M06", "M07", "M08", "M09"])

    def test_hasnextpage_true_then_false(self):
        # AC3: true on a non-final page, false on the last one.
        first = _exec("query { cursor { pageInfo(first: 5) { hasNextPage } } }")[
            "cursor"
        ]["pageInfo"]
        self.assertTrue(first["hasNextPage"])

        last = _exec(
            'query { cursor { pageInfo(first: 5, cursor: "%s") { hasNextPage } } }'
            % self._cursor(10)
        )["cursor"]["pageInfo"]
        self.assertFalse(last["hasNextPage"])

    def test_haspreviouspage(self):
        # AC4: false on the first page (even with a spurious cursor), true later.
        first = _exec("query { cursor { pageInfo(first: 5) { hasPreviousPage } } }")[
            "cursor"
        ]["pageInfo"]
        self.assertFalse(first["hasPreviousPage"])

        spurious = _exec(
            'query { cursor { pageInfo(first: 5, cursor: "%s") { hasPreviousPage } } }'
            % self._cursor(0)
        )["cursor"]["pageInfo"]
        self.assertFalse(spurious["hasPreviousPage"])

        later = _exec(
            'query { cursor { pageInfo(first: 5, cursor: "%s") { hasPreviousPage } } }'
            % self._cursor(5)
        )["cursor"]["pageInfo"]
        self.assertTrue(later["hasPreviousPage"])

    def test_pageinfo_empty_page(self):
        # AC5: an empty page yields null cursors and hasNextPage false.
        info = _exec(
            'query { cursor { pageInfo(first: 5, cursor: "%s") '
            "{ hasNextPage hasPreviousPage startCursor endCursor } } }"
            % self._cursor(9999)
        )["cursor"]["pageInfo"]
        self.assertEqual(
            info,
            {
                "hasNextPage": False,
                "hasPreviousPage": False,
                "startCursor": None,
                "endCursor": None,
            },
        )


def test_filter_paginate_list_field_without_pagination_does_not_raise():
    """No `pagination` and DEFAULT_PAGINATION_CLASS=None must not call None()."""
    from django_graphex import DjangoFilterPaginateListField

    from .schema import UserType

    field = DjangoFilterPaginateListField(UserType)
    assert getattr(field, "pagination", None) is None
