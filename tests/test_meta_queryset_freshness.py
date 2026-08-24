# -*- coding: utf-8 -*-
"""A "Meta.queryset" must never serve a frozen snapshot of the first request.

"Meta.queryset" is evaluated once, at class-definition time, and bound as the
resolver base. "_get_queryset" returned that very object verbatim, so whenever
nothing downstream cloned it -- which is exactly what happens with the
documented "OPTIMIZE_QUERYSET = False" escape hatch -- the first request filled
its "_result_cache" and every later request in the same process replayed that
cache. Rows created afterwards were invisible until a restart.

The fix clones at the single choke point ("_get_queryset"), so both binding
sites ("DjangoListObjectField.wrap_resolve" and "DjangoModelType.Meta.queryset")
get a fresh queryset per request.
"""

from __future__ import annotations

from typing import Any

from django.test import TestCase, override_settings
from graphql import graphql_sync

from django_graphex.core import ObjectType
from django_graphex.fields import DjangoListObjectField
from django_graphex.registry import Registry
from django_graphex.schema import DjangoGraphQLSchema
from django_graphex.types import DjangoListObjectType, DjangoObjectType

from ._schema_isolation import isolated_pair
from .models import Author, Post

R = Registry()


class FrozenPostType(DjangoObjectType):
    """Row type for the "Meta.queryset" staleness regression.

    Only the rows it serves matter here, so it stays deliberately plain.
    """

    class Meta:
        """Bind the type to "Post" with a filterable "title".

        The lookups exist only so the list field takes its normal path.
        """

        model = Post
        registry = R
        filter_fields = {"title": ("exact",)}


class FrozenPostList(DjangoListObjectType):
    """List container declaring a class-level "Meta.queryset".

    The queryset instance is created once, at import time -- which is what made
    the cached rows survive across requests.
    """

    class Meta:
        """Bind the list type to "Post" with an explicit base queryset.

        The queryset instance is what the regression is about: it is created
        once, at import time, and shared by every request.
        """

        model = Post
        registry = R
        queryset = Post.objects.all()


class _Query(ObjectType):
    """Root query exposing the list backed by "Meta.queryset"."""

    posts = DjangoListObjectField(FrozenPostList)


_schema = DjangoGraphQLSchema(query=_Query, registries=isolated_pair(R))

_QUERY = "{ posts { results { title } totalCount } }"


def _run() -> Any:
    """Execute the list query and return its data.

    Returns:
        The "data" mapping of the execution result.

    Raises:
        AssertionError: When the execution reported errors.
    """
    result = graphql_sync(_schema.graphql_schema, _QUERY)
    assert result.errors is None, result.errors
    return result.data


@override_settings(DJANGO_GRAPHEX={"OPTIMIZE_QUERYSET": False})
class MetaQuerysetFreshnessTest(TestCase):
    """A row created between two requests must show up in the second one.

    The optimizer is off for the whole class -- that is the configuration in
    which nothing downstream clones the bound base queryset.
    """

    def test_second_request_sees_new_rows(self) -> None:
        """The list is rebuilt per request instead of replaying a result cache.

        This test breaks if the bound "Meta.queryset" is served without a clone
        again, freezing the list at whatever the first request saw.
        """
        author = Author.objects.create(name="Ada")
        Post.objects.create(title="p1", author=author)

        first = _run()
        self.assertEqual(first["posts"]["results"], [{"title": "p1"}])
        self.assertEqual(first["posts"]["totalCount"], 1)

        Post.objects.create(title="p2", author=author)

        second = _run()
        self.assertEqual(second["posts"]["results"], [{"title": "p1"}, {"title": "p2"}])
        self.assertEqual(second["posts"]["totalCount"], 2)

    def test_declared_queryset_is_never_evaluated(self) -> None:
        """The declared "Meta.queryset" keeps an empty result cache forever.

        This test breaks if a request evaluates the shared queryset instance
        itself rather than a per-request clone of it.
        """
        author = Author.objects.create(name="Ada")
        Post.objects.create(title="p1", author=author)

        _run()

        self.assertIsNone(FrozenPostList._meta.queryset._result_cache)
