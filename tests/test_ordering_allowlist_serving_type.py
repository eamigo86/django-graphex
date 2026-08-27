# -*- coding: utf-8 -*-
"""The flat paginated list field must rank by the type ITS schema serves.

Every other ordering-allowlist stamper reads the node type the schema being
built holds: the list container reads its pair's compiled element type
("types._list_container_fields_thunk"), and the permission-scoped pruner
re-derives the allowlist against the CLONE it just built
("core.schema_pruner._rebuild_pagination_resolver"). The flat
"DjangoFilterPaginateListField" was the one that did not: it stamped a thunk
over "_type._meta.graphql_output_type", the CLASS-DEF canonical instance, at
class-body time -- and that instance is demonstrably not the object the schema
serves. Instrumenting every flat paginated field this suite builds found twelve
whose served node type is a different object from the canonical one.

They agree today, which is why nothing failed. They agree only by construction:
a fork recompiles the same class from the same "Meta" against the same graphene
registry. Any schema that publishes LESS than the canonical type -- which is
precisely what a prune is -- puts the two out of step, and the direction of the
disagreement is the dangerous one: the allowlist would name a column the served
SDL denies.

Pinned here by taking the built schema's OWN node type and removing a relation
from it, the way a prune does, and then asking the field a query. The answer has
to follow the schema in the caller's hands, not the class body's.
"""

from __future__ import annotations

import pytest
from django.test import TestCase
from graphql import graphql_sync

from django_graphex.core import ObjectType
from django_graphex.fields import DjangoFilterPaginateListField
from django_graphex.paginations.pagination import LimitOffsetGraphqlPagination
from django_graphex.registry import Registry
from django_graphex.schema import DjangoGraphQLSchema
from django_graphex.types import DjangoObjectType

from ._schema_isolation import isolated_pair
from .models import Author, Post

_R = Registry()


class ServingAuthorType(DjangoObjectType):
    """Author node reached through the post node's forward foreign key.

    Publishes the key, so the relation is what makes "author_id" orderable.
    """

    class Meta:
        """Configuration for "ServingAuthorType".

        Publishes the key so the relation makes "author_id" orderable to begin
        with.
        """

        model = Author
        registry = _R
        only_fields = ("id", "name")


class ServingPostType(DjangoObjectType):
    """Post node whose "author" relation is what publishes "author_id".

    The relation is the only reason the ordering term is legitimate, which is
    what makes removing it from the served type a measurable change.
    """

    class Meta:
        """Configuration for "ServingPostType".

        Keeps the relation so the ordering term is legitimate before the type
        is narrowed.
        """

        model = Post
        registry = _R
        only_fields = ("id", "title", "author")


class ServingQuery(ObjectType):
    """Root query mounting the flat paginated list field under test.

    Flat rather than a container, because the container stamps its allowlist
    from a different place and was never the field in question.
    """

    posts = DjangoFilterPaginateListField(
        ServingPostType,
        pagination=LimitOffsetGraphqlPagination(default_limit=10, max_limit=20),
    )


serving_schema = DjangoGraphQLSchema(query=ServingQuery, registries=isolated_pair(_R))


@pytest.mark.django_db
class FlatPaginatedFieldRanksByTheServingTypeTests(TestCase):
    """The allowlist follows the schema in the caller's hands.

    Not the class body's, which can only name the canonical compiled type.
    """

    @classmethod
    def setUpTestData(cls) -> None:
        """Create one post so the list has a row to rank.

        Returns:
            None.
        """
        author = Author.objects.create(name="a", bio="")
        Post.objects.create(title="t", author=author)

    def test_the_relation_makes_the_key_orderable_while_it_is_published(self) -> None:
        """The contrast that makes the next assertion about provenance.

        Returns:
            None.
        """
        result = graphql_sync(
            serving_schema.graphql_schema,
            '{ posts(ordering: "authorId") { title } }',
        )
        assert result.errors is None, [str(e) for e in result.errors or ()]

    def test_narrowing_the_served_type_withdraws_the_key(self) -> None:
        """Removing the relation from the SERVED type must refuse the term.

        Built fresh rather than narrowing the module-level schema: the
        paginator resolves its allowlist thunk once and keeps the answer, so a
        narrowed schema has to be a schema of its own or the two tests would
        depend on the order they run in.

        Returns:
            None.
        """
        narrowed = DjangoGraphQLSchema(query=ServingQuery, registries=isolated_pair(_R))
        narrowed.graphql_schema.type_map["ServingPostType"].fields.pop("author")

        result = graphql_sync(
            narrowed.graphql_schema,
            '{ posts(ordering: "authorId") { title } }',
        )
        assert result.errors is not None
        assert "Invalid ordering field" in str(result.errors[0])
