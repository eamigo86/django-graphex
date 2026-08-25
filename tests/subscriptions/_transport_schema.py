# -*- coding: utf-8 -*-
"""The native subscription schema the transport test modules share.

Both halves of this module exist for the same reason: the output registry is
keyed by MODEL and is last-one-wins, so a second class minted for a model under
the SAME GraphQL type name leaves one holder with its own compiled node while
the registry hands the other's out through the relation graph. A schema that
reaches both then dies with "Schema must contain uniquely named types", and it
only happens under some test orders.

* The four node types below were copied into six transport modules, so six
  classes competed for each of "Tag" / "Category" / "Author" / "Post".
* "build_native_schema" was copied into those same modules and rebuilt its
  "PostModelType" on EVERY call — 85 of them in one suite run — and every
  "DjangoModelType" mints a "<Model>ListGenericType" container whose name the
  library derives from the model, so each call forked "PostListGenericType"
  again, at test-run time, long after other schemas had compiled.

One class per process is the honest answer for both: the transports need Post's
relation targets registered and one assembled schema to serve, not a private
copy per module and per call.
"""

from __future__ import annotations

from functools import lru_cache

from graphql import GraphQLSchema

from django_graphex.types import DjangoObjectType
from tests.models import Author, Category, Post, Tag


class _TagT(DjangoObjectType):
    class Meta:
        model = Tag


class _CategoryT(DjangoObjectType):
    class Meta:
        model = Category


class _AuthorT(DjangoObjectType):
    class Meta:
        model = Author


class _PostT(DjangoObjectType):
    class Meta:
        model = Post


@lru_cache(maxsize=1)
def build_native_schema() -> GraphQLSchema:
    """Assemble the native subscription schema mounting a Post SubscriptionField.

    Memoized: see the module docstring. Every caller only reads the schema, so
    one instance serves them all.

    Returns:
        The assembled GraphQLSchema with a "post" subscription field.
    """
    from graphql import GraphQLBoolean

    from django_graphex.core import ObjectType, field
    from django_graphex.core.registry_compiler import compile_all_outputs
    from django_graphex.schema import DjangoGraphQLSchema
    from django_graphex.types import DjangoModelType

    class PostModelType(DjangoModelType):
        class Meta:
            model = Post
            stream = "posts"
            payload_mode = "full"

    class Query(ObjectType):
        ok = field(GraphQLBoolean)

    class SubscriptionRoot(ObjectType):
        post = PostModelType.SubscriptionField()

    compile_all_outputs()
    schema = DjangoGraphQLSchema(query=Query, subscription=SubscriptionRoot)
    return schema.graphql_schema
