# -*- coding: utf-8 -*-
"""Edge branches of "types.py": is_type_of, get_node, get_queryset, and the
"DEFAULT_PAGINATION_CLASS" global-paginator path.
"""

from unittest.mock import patch

import pytest
from django.test import TestCase
from django.utils.functional import SimpleLazyObject
from graphql import graphql_sync

from django_graphex.core import ObjectType
from django_graphex.fields import DjangoListObjectField
from django_graphex.paginations import LimitOffsetGraphqlPagination
from django_graphex.registry import Registry
from django_graphex.schema import DjangoGraphQLSchema
from django_graphex.types import DjangoListObjectType, DjangoObjectType

from .models import Author, BasicModel

R = Registry()


class _AuthorType(DjangoObjectType):
    class Meta:
        model = Author
        registry = R


class IsTypeOfTest(TestCase):
    """Cover "DjangoObjectType.is_type_of" across model, lazy, and mismatched inputs.

    Groups the accept/reject branches of the type-resolution check used when
    GraphQL needs to know which concrete type an interface/union value is.
    """

    def test_is_type_of_accepts_model_instance(self) -> None:
        """A plain instance of the mapped model must be accepted as a match.

        If this fails, "is_type_of" no longer recognizes the model instances
        it is supposed to resolve at the GraphQL interface/union boundary.
        """
        author = Author.objects.create(name="x")
        self.assertTrue(_AuthorType.is_type_of(author, None))

    def test_is_type_of_resolves_lazy_object(self) -> None:
        """A Django "SimpleLazyObject" wrapping the model must resolve transparently.

        If this fails, lazily-evaluated instances (e.g. from "request.user")
        would be wrongly rejected by the type check.
        """
        author = Author.objects.create(name="y")
        lazy = SimpleLazyObject(lambda: author)
        self.assertTrue(_AuthorType.is_type_of(lazy, None))

    def test_is_type_of_rejects_non_model(self) -> None:
        """A non-model value must raise TypeError instead of silently failing.

        If this fails, callers lose the early, explicit signal that an
        invalid object reached type resolution.
        """
        with self.assertRaises(TypeError):
            _AuthorType.is_type_of("not-a-model", None)

    def test_is_type_of_false_for_other_model(self) -> None:
        """An instance of an unrelated model must be rejected, not accepted.

        If this fails, "is_type_of" would misclassify instances across
        unrelated Django models sharing the same registry.
        """
        other = BasicModel.objects.create(text="z")
        self.assertFalse(_AuthorType.is_type_of(other, None))


class GetNodeTest(TestCase):
    """Cover "DjangoObjectType.get_node" and "get_queryset" lookup behavior.

    Groups the Relay node-lookup and queryset-passthrough hooks that
    subclasses rely on for default behavior.
    """

    def test_get_node_found(self) -> None:
        """An existing primary key must resolve to the matching instance.

        If this fails, Relay-style node lookups by ID would break for
        objects that do exist.
        """
        author = Author.objects.create(name="found")
        self.assertEqual(_AuthorType.get_node(None, author.pk), author)

    def test_get_node_missing_returns_none(self) -> None:
        """A primary key with no matching row must resolve to None, not raise.

        If this fails, node lookups for stale or invalid IDs would surface as
        an unhandled exception instead of a clean null result.
        """
        self.assertIsNone(_AuthorType.get_node(None, 999999))

    def test_get_queryset_passthrough(self) -> None:
        """The base "get_queryset" hook must return the queryset unchanged.

        If this fails, the default hook would be filtering or mutating
        querysets when it is only meant to be an identity passthrough for
        subclasses to override.
        """
        qs = Author.objects.all()
        self.assertIs(_AuthorType.get_queryset(qs, None), qs)


# --------------------------------------------------------------------------- #
# DEFAULT_PAGINATION_CLASS: a list type with no Meta.pagination uses the global #
# --------------------------------------------------------------------------- #
_PR = Registry()


class GlobalPaginationTest(TestCase):
    """Cover the DEFAULT_PAGINATION_CLASS fallback for list types without Meta.pagination.

    Verifies the global paginator is wired in automatically when a list type
    does not declare its own Meta.pagination.
    """

    def test_global_paginator_applied_to_list_type(self) -> None:
        """A list type with no Meta.pagination must still use the global paginator.

        If this fails, list types would silently lose pagination (and its
        "limit"/"totalCount" surface) whenever Meta.pagination is omitted.
        """
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
        # The global LimitOffset paginator wraps the "results" field, which now
        # exposes a "limit" argument (proving the global paginator was applied).
        result = graphql_sync(
            schema.graphql_schema,
            "{ authors { results(limit: 1) { name } totalCount } } ",
        )
        self.assertIsNone(result.errors, result.errors)
        self.assertEqual(len(result.data["authors"]["results"]), 1)
        self.assertEqual(result.data["authors"]["totalCount"], 2)


def test_invalid_global_paginator_class_asserts(db: None) -> None:
    """DEFAULT_PAGINATION_CLASS set to a non-paginator class must raise AssertionError.

    Args:
        db: The pytest-django fixture that enables database access for the test.

    If this fails, misconfiguring the global pagination setting with an
    incompatible class would fail silently instead of asserting loudly at
    type-construction time.
    """
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
