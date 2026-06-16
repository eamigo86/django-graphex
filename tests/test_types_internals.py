# -*- coding: utf-8 -*-
"""Edge branches of ``types.py``: is_type_of, get_node, get_queryset, and the
``DEFAULT_PAGINATION_CLASS`` global-paginator path.
"""

from unittest.mock import patch

import pytest
from django.test import TestCase
from django.utils.functional import SimpleLazyObject
from graphql import graphql_sync

from django_graphex import (
    DjangoGraphQLSchema,
    DjangoListObjectField,
    DjangoListObjectType,
    DjangoObjectType,
    ObjectType,
)
from django_graphex.paginations import LimitOffsetGraphqlPagination
from django_graphex.registry import Registry

from .models import Author, BasicModel

R = Registry()


class _AuthorType(DjangoObjectType):
    class Meta:
        model = Author
        registry = R


class IsTypeOfTest(TestCase):
    def test_is_type_of_accepts_model_instance(self):
        author = Author.objects.create(name="x")
        self.assertTrue(_AuthorType.is_type_of(author, None))

    def test_is_type_of_resolves_lazy_object(self):
        author = Author.objects.create(name="y")
        lazy = SimpleLazyObject(lambda: author)
        self.assertTrue(_AuthorType.is_type_of(lazy, None))

    def test_is_type_of_rejects_non_model(self):
        with self.assertRaises(TypeError):
            _AuthorType.is_type_of("not-a-model", None)

    def test_is_type_of_false_for_other_model(self):
        other = BasicModel.objects.create(text="z")
        self.assertFalse(_AuthorType.is_type_of(other, None))


class GetNodeTest(TestCase):
    def test_get_node_found(self):
        author = Author.objects.create(name="found")
        self.assertEqual(_AuthorType.get_node(None, author.pk), author)

    def test_get_node_missing_returns_none(self):
        self.assertIsNone(_AuthorType.get_node(None, 999999))

    def test_get_queryset_passthrough(self):
        qs = Author.objects.all()
        self.assertIs(_AuthorType.get_queryset(qs, None), qs)


# --------------------------------------------------------------------------- #
# DEFAULT_PAGINATION_CLASS: a list type with no Meta.pagination uses the global #
# --------------------------------------------------------------------------- #
_PR = Registry()


class GlobalPaginationTest(TestCase):
    def test_global_paginator_applied_to_list_type(self):
        # The setting is read via the (stale) binding in types.py, so patch it
        # there directly rather than through override_settings.
        with patch(
            "django_graphex.types.graphql_api_settings.DEFAULT_PAGINATION_CLASS",
            LimitOffsetGraphqlPagination,
        ):

            class _PagedAuthorList(DjangoListObjectType):
                class Meta:
                    model = Author
                    registry = _PR

            class _Query(ObjectType):
                authors = DjangoListObjectField(_PagedAuthorList)

            schema = DjangoGraphQLSchema(query=_Query)

        Author.objects.create(name="a")
        Author.objects.create(name="b")
        # The global LimitOffset paginator wraps the `results` field, which now
        # exposes a `limit` argument (proving the global paginator was applied).
        result = graphql_sync(
            schema.graphql_schema,
            "{ authors { results(limit: 1) { name } totalCount } } ",
        )
        self.assertIsNone(result.errors, result.errors)
        self.assertEqual(len(result.data["authors"]["results"]), 1)
        self.assertEqual(result.data["authors"]["totalCount"], 2)


def test_invalid_global_paginator_class_asserts(db):
    _BadR = Registry()
    with patch(
        "django_graphex.types.graphql_api_settings.DEFAULT_PAGINATION_CLASS",
        dict,  # not a BaseDjangoGraphqlPagination subclass
    ):
        with pytest.raises(AssertionError):

            class _BadList(DjangoListObjectType):
                class Meta:
                    model = Author
                    registry = _BadR
