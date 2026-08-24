"""Regressions for the "django_graphex.utils" defects found by the 2.1.0 audit.

Six reproduced defects, each pinned by the symptom a user would report:

* U1 — "_detect_promotions" never recursed, so an "AnnotatedField" reached
  through two chained forward foreign keys resolved to null.
* U2 — the ".only()" walkers never received the source class, so an
  "... on <Interface>" fragment inside a prefetched child was skipped and its
  columns were dropped from ".only()" (deferred-column N+1).
* U3 — "_collect_gfk_union_buckets" ignored named fragment spreads, so a
  selection mixing "... on Member" with "...NamedFrag" built the bucket from
  the inline fragment alone (deferred-column N+1).
* U4 — the two walkers that DO thread the identity read the wrong attribute
  ("gql_type.graphene_type" is never set on a natively compiled type), leaving
  the interface branch of the guard inert at both sites.
* 5  — "get_extra_filters" ANDed every relation back to the parent, so a child
  with two foreign keys to the same parent scoped to the empty set.
* 6  — the optimizer appended its prefetches without checking the ones the
  user's "get_queryset" had already registered, so the same lookup collided.

STRICT TDD: every test here was RED against the shipped tree first.
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

from django.contrib.contenttypes.models import ContentType
from django.core.exceptions import ImproperlyConfigured
from django.db import connection
from django.db.models import Count
from django.test import TestCase
from django.test.utils import CaptureQueriesContext
from graphql import GraphQLInt, GraphQLString, graphql_sync, parse

from django_graphex.core import ObjectType, field
from django_graphex.fields import (
    AnnotatedField,
    DjangoFilterListField,
    DjangoFilterPaginateListField,
    DjangoListObjectField,
)
from django_graphex.paginations import LimitOffsetGraphqlPagination
from django_graphex.registry import Registry
from django_graphex.schema import DjangoGraphQLSchema
from django_graphex.types import (
    DjangoInterfaceType,
    DjangoListObjectType,
    DjangoObjectType,
    DjangoUnionType,
)
from django_graphex.utils import (
    _collect_prefetch_only_sets,
    _walk_filtered_prefetches,
    get_extra_filters,
)

from ._schema_isolation import isolated_pair
from .models import (
    AuditArticle,
    AuditEditor,
    Author,
    Comment,
    Post,
    Track2Account,
    Track2GfkComment,
)


def _exec(schema: DjangoGraphQLSchema, query: str) -> dict:
    """Execute "query" against "schema" and return its data, asserting success.

    Args:
        schema: The compiled schema to execute against.
        query: The GraphQL document to execute.

    Returns:
        The "data" mapping of the execution result.

    Raises:
        AssertionError: If the execution produced GraphQL errors.
    """
    result = graphql_sync(schema.graphql_schema, query)
    assert result.errors is None, result.errors
    return result.data


def _sql(query_log: list[dict]) -> list[str]:
    """Extract the SQL text of each captured query.

    Args:
        query_log: The captured queries of a "CaptureQueriesContext".

    Returns:
        The list of SQL statements in execution order.
    """
    return [entry["sql"] for entry in query_log]


# --------------------------------------------------------------------------- #
# U1 — AnnotatedField through two chained forward foreign keys                 #
# --------------------------------------------------------------------------- #
class AnnotatedFieldThroughChainedForeignKeysTest(TestCase):
    """An "AnnotatedField" two forward-FK hops down must still resolve.

    "_detect_promotions" walked only the first hop, so the second hop's
    select_related path was never promoted to a prefetch and the annotation
    was never applied.
    """

    @classmethod
    def setUpTestData(cls) -> None:
        """Seed the chained-hop fixture.

        One author with two posts (so the annotated count is 2) and one comment
        on the first post, which is the row the query starts from.
        """
        author = Author.objects.create(name="chained")
        first = Post.objects.create(title="p1", author=author)
        Post.objects.create(title="p2", author=author)
        Comment.objects.create(post=first, body="c1")

    @staticmethod
    def _schema() -> DjangoGraphQLSchema:
        """Build a schema exposing Comment -> post -> author with an annotation.

        Returns:
            The compiled schema for the chained-hop query.
        """
        reg = Registry()

        class ChainAuthorType(DjangoObjectType):
            """Author output type carrying the annotated post count."""

            post_count = AnnotatedField(GraphQLInt, lambda: Count("posts"))

            class Meta:
                """Bind the type to Author under the isolated registry."""

                model = Author
                registry = reg

        class ChainPostType(DjangoObjectType):
            """Post output type: the middle hop of the chain."""

            class Meta:
                """Bind the type to Post under the isolated registry."""

                model = Post
                registry = reg

        class ChainCommentType(DjangoObjectType):
            """Comment output type: the root row of the chain."""

            class Meta:
                """Bind the type to Comment under the isolated registry."""

                model = Comment
                registry = reg

        class ChainCommentListType(DjangoListObjectType):
            """Paginated container for the comment rows."""

            class Meta:
                """Bind the container to Comment under the isolated registry."""

                model = Comment
                registry = reg
                pagination = LimitOffsetGraphqlPagination(default_limit=10)

        class Query(ObjectType):
            """Root query exposing the comment list."""

            comments = DjangoListObjectField(ChainCommentListType)

        return DjangoGraphQLSchema(query=Query, registries=isolated_pair(reg))

    def test_annotation_survives_two_forward_fk_hops(self) -> None:
        """The annotated count must resolve through "comment -> post -> author".

        This test breaks if "_detect_promotions" stops recursing into each
        select_related sub-selection: the second hop is never promoted from
        select_related to prefetch_related, the annotation is never applied,
        and "postCount" silently resolves to null.
        """
        data = _exec(
            self._schema(),
            "{ comments { results { post { author { name postCount } } } } }",
        )
        author = data["comments"]["results"][0]["post"]["author"]
        self.assertEqual(author["name"], "chained")
        self.assertEqual(author["postCount"], 2)


# --------------------------------------------------------------------------- #
# U2 — interface inline fragment inside a prefetched child                     #
# --------------------------------------------------------------------------- #
class PrefetchChildInterfaceFragmentTest(TestCase):
    """An interface fragment inside a prefetched child must keep its columns.

    The ".only()" walkers never received the child's source class, so the
    interface branch of the inline-fragment guard could not fire and the
    fragment was skipped — every selected column was deferred and reloaded
    one query per row.
    """

    @classmethod
    def setUpTestData(cls) -> None:
        """Seed the prefetched-child fixture.

        Five posts under one author, each with a body long enough that a
        deferred-column reload is visible in the query log.
        """
        author = Author.objects.create(name="iface")
        for index in range(5):
            Post.objects.create(title=f"t{index}", body="B" * 40, author=author)

    @staticmethod
    def _schema() -> DjangoGraphQLSchema:
        """Build a schema whose Post type implements a "Titled" interface.

        Returns:
            The compiled schema for the interface-fragment query.
        """
        reg = Registry()

        class IfaceTitled(DjangoInterfaceType):
            """Interface exposing the shared "title" field."""

            title = field(GraphQLString)

            class Meta:
                """Bind the interface to the isolated registry."""

                registry = reg

        class IfacePostType(DjangoObjectType):
            """Post output type implementing "IfaceTitled"."""

            class Meta:
                """Bind the type to Post and declare the interface."""

                model = Post
                registry = reg
                interfaces = (IfaceTitled,)

        class IfaceAuthorType(DjangoObjectType):
            """Author output type owning the prefetched "posts" child."""

            class Meta:
                """Bind the type to Author under the isolated registry."""

                model = Author
                registry = reg

        class IfaceAuthorListType(DjangoListObjectType):
            """Paginated container for the author rows."""

            class Meta:
                """Bind the container to Author under the isolated registry."""

                model = Author
                registry = reg
                pagination = LimitOffsetGraphqlPagination(default_limit=10)

        class Query(ObjectType):
            """Root query exposing the author list."""

            authors = DjangoListObjectField(IfaceAuthorListType)

        return DjangoGraphQLSchema(
            query=Query,
            types=[IfacePostType],
            registries=isolated_pair(reg),
        )

    def test_interface_fragment_child_is_not_deferred(self) -> None:
        """Selecting a child column through an interface fragment stays 2 queries.

        This test breaks if the ".only()" walkers stop receiving the child's
        source class: the interface name is no longer an accepted identity, the
        fragment is skipped, "title" drops out of ".only()", and each of the
        five posts costs one extra deferred-column query.
        """
        schema = self._schema()
        query = """
        { authors { results { name posts { results {
            ... on IfaceTitled { title }
        } } } } }
        """
        with CaptureQueriesContext(connection) as captured:
            data = _exec(schema, query)

        titles = [
            row["title"] for row in data["authors"]["results"][0]["posts"]["results"]
        ]
        self.assertEqual(titles, ["t0", "t1", "t2", "t3", "t4"])
        self.assertEqual(len(captured.captured_queries), 2, _sql(captured))


# --------------------------------------------------------------------------- #
# U3 — named fragment spread on a GFK union member                             #
# --------------------------------------------------------------------------- #
class GfkUnionNamedFragmentSpreadTest(TestCase):
    """A named fragment spread on a union member must join the same bucket.

    "_collect_gfk_union_buckets" only looked at inline fragments, so a mixed
    selection narrowed the member queryset to the inline fragment's columns
    and reloaded the rest one query per row.
    """

    @classmethod
    def setUpTestData(cls) -> None:
        """Seed the GFK-union fixture.

        Four accounts, each targeted by exactly one comment, so a per-row
        deferred fetch shows up as four extra queries.
        """
        content_type = ContentType.objects.get_for_model(Track2Account)
        for index in range(4):
            account = Track2Account.objects.create(balance=index, label=f"L{index}")
            Track2GfkComment.objects.create(
                body=f"c{index}", target_ct=content_type, target_id=account.pk
            )

    @staticmethod
    def _schema() -> DjangoGraphQLSchema:
        """Build a schema exposing a GFK union over "Track2Account".

        Returns:
            The compiled schema for the mixed-fragment query.
        """
        reg = Registry()

        class MixAccountType(DjangoObjectType):
            """The single concrete member of the GFK union."""

            class Meta:
                """Bind the type to Track2Account under the isolated registry."""

                model = Track2Account
                registry = reg

        class MixTargetUnion(DjangoUnionType):
            """Companion union for the GFK "target" field."""

            class Meta:
                """Declare the union members under the isolated registry."""

                types = (MixAccountType,)
                registry = reg

        class MixCommentType(DjangoObjectType):
            """GFK owner type exposing "target" as the union."""

            class Meta:
                """Bind the GFK owner and map "target" to the union."""

                model = Track2GfkComment
                registry = reg
                unions = {"target": MixTargetUnion}

        class MixCommentListType(DjangoListObjectType):
            """Paginated container for the GFK comment rows."""

            class Meta:
                """Bind the container to the GFK owner model."""

                model = Track2GfkComment
                registry = reg
                pagination = LimitOffsetGraphqlPagination(default_limit=10)

        class Query(ObjectType):
            """Root query exposing the GFK comment list."""

            comments = DjangoListObjectField(MixCommentListType)

        return DjangoGraphQLSchema(
            query=Query,
            types=[MixAccountType],
            registries=isolated_pair(reg),
        )

    def test_mixed_inline_and_named_fragment_stays_two_queries(self) -> None:
        """Mixing "... on Member" with "...NamedFrag" must not fan out per row.

        This test breaks if the union-bucket collector stops resolving
        "FragmentSpreadNode" against the document fragments: the bucket is built
        from the inline fragment alone, "label" is deferred, and each of the four
        rows costs one extra query.
        """
        schema = self._schema()
        query = """
        fragment MixLabel on MixAccountType { label }
        { comments { results { body target {
            ... on MixAccountType { balance }
            ...MixLabel
        } } } }
        """
        with CaptureQueriesContext(connection) as captured:
            data = _exec(schema, query)

        rows = data["comments"]["results"]
        self.assertEqual(
            [row["target"]["label"] for row in rows], ["L0", "L1", "L2", "L3"]
        )
        self.assertEqual([row["target"]["balance"] for row in rows], [0, 1, 2, 3])
        self.assertEqual(len(captured.captured_queries), 2, _sql(captured))


# --------------------------------------------------------------------------- #
# U4 — the two walkers that read the wrong source-class attribute              #
# --------------------------------------------------------------------------- #
_U4_REGISTRY = Registry()


class _U4Named(DjangoInterfaceType):
    """Interface the walked Author type declares via "Meta.interfaces"."""

    name = field(GraphQLString)

    class Meta:
        """Bind the interface to the module-local registry."""

        registry = _U4_REGISTRY


class _U4PostType(DjangoObjectType):
    """Post output type, registered so Author exposes its "posts" relation."""

    class Meta:
        """Bind the type to Post under the module-local registry."""

        model = Post
        registry = _U4_REGISTRY


class _U4AuthorType(DjangoObjectType):
    """Author output type implementing "_U4Named"."""

    class Meta:
        """Bind the type to Author and declare the interface."""

        model = Author
        registry = _U4_REGISTRY
        interfaces = (_U4Named,)


class _U4Query(ObjectType):
    """Root query used only to compile the types under test."""

    a = field(_U4AuthorType)
    p = field(_U4PostType)


_U4_SCHEMA = DjangoGraphQLSchema(query=_U4Query, registries=isolated_pair(_U4_REGISTRY))
_U4_AUTHOR_GQL = _U4_SCHEMA.graphql_schema.get_type(_U4AuthorType._meta.name)
_U4_IFACE_NAME = _U4Named._meta.name


def _u4_selection_set(query_str: str):
    """Return the inner selection set of the single root field "a".

    Args:
        query_str: The GraphQL document to parse.

    Returns:
        The "SelectionSetNode" nested under the root field.
    """
    return parse(query_str).definitions[0].selection_set.selections[0].selection_set


class ParentInterfaceFragmentIdentityTest(TestCase):
    """A parent-level interface fragment must not disable the optimizer.

    "_collect_prefetch_only_sets" and "_walk_filtered_prefetches" both read
    "gql_type.graphene_type", which a natively compiled type never carries, so
    the interface branch of the guard was inert: the fragment was skipped and
    every relation it selected fell back to an unoptimized full load.
    """

    @staticmethod
    def _info() -> Any:
        """Return a minimal resolve-info stand-in for the filtered walker.

        Returns:
            An object exposing the "fragments", "variable_values" and "schema"
            attributes the walker reads.
        """
        return SimpleNamespace(fragments={}, variable_values={}, schema=None)

    def test_prefetch_plan_is_built_under_an_interface_fragment(self) -> None:
        """ "_collect_prefetch_only_sets" must descend an implemented interface.

        This test breaks if the walker goes back to reading
        "gql_type.graphene_type": the source class resolves to None, the
        interface name is never an accepted identity, the fragment is skipped,
        and the "posts" prefetch loses its column plan (full-column load).
        """
        selection = _u4_selection_set(
            "{ a { name ... on " + _U4_IFACE_NAME + " { posts { id title } } } }"
        )
        out = _collect_prefetch_only_sets(
            Author, selection, {}, gql_type=_U4_AUTHOR_GQL
        )
        self.assertIn("posts", out)
        self.assertNotIn("body", out["posts"].only_cols)

    def test_filtered_prefetch_is_seen_under_an_interface_fragment(self) -> None:
        """ "_walk_filtered_prefetches" must descend an implemented interface.

        This test breaks the same way: the fragment is skipped, the nested
        "posts" selection is never visited, and no lookup is registered — so the
        filtered child is resolved one query per parent row.
        """
        selection = _u4_selection_set(
            "{ a { name ... on " + _U4_IFACE_NAME + " { posts { id } } } }"
        )
        out: list = []
        seen: dict = {}
        _walk_filtered_prefetches(
            _U4_AUTHOR_GQL, Author, selection, "", self._info(), out, seen
        )
        self.assertIn("posts", seen)


# --------------------------------------------------------------------------- #
# 5 — a child with two relations back to the same parent                       #
# --------------------------------------------------------------------------- #
class AmbiguousParentRelationTest(TestCase):
    """Scoping a nested list needs ONE relation, not every relation ANDed.

    "get_extra_filters" returned every relation pointing at the parent, so a
    child with "created_by" and "updated_by" was scoped to rows matching both
    — the empty set for every audit-column schema.
    """

    @classmethod
    def setUpTestData(cls) -> None:
        """Seed the ambiguous-relation fixture.

        Two articles created by one editor and updated by another, so the two
        relations back to the parent select disjoint sets.
        """
        cls.creator = AuditEditor.objects.create(name="creator")
        cls.updater = AuditEditor.objects.create(name="updater")
        for title in ("a1", "a2"):
            AuditArticle.objects.create(
                title=title, created_by=cls.creator, updated_by=cls.updater
            )

    def test_get_extra_filters_declines_an_ambiguous_child(self) -> None:
        """Two relations back to the parent must be refused, not ANDed.

        This test breaks if "get_extra_filters" goes back to updating one
        mapping per relation: the caller then filters on "created_by" AND
        "updated_by" at once and every nested list silently resolves empty.
        """
        with self.assertRaises(ImproperlyConfigured) as caught:
            get_extra_filters(self.creator, AuditArticle)

        message = str(caught.exception)
        self.assertIn("created_by", message)
        self.assertIn("updated_by", message)

    def test_get_extra_filters_still_maps_a_single_relation(self) -> None:
        """One relation back to the parent must still map to that relation.

        This test breaks if the ambiguity guard starts refusing the
        unambiguous single-relation case too.
        """
        author = Author.objects.create(name="single")
        post = Post.objects.create(title="only", author=author)
        self.assertEqual(get_extra_filters(post, Comment), {"post": post})
        self.assertEqual(get_extra_filters(post, AuditArticle), {})

    def test_ambiguous_nested_list_reports_instead_of_returning_nothing(self) -> None:
        """An ambiguous nested list must fail loudly, not return an empty page.

        This test breaks if the ambiguity is swallowed again: the query then
        succeeds with "paginatedArticles: []" while the editor demonstrably has
        two created articles, which is silent data loss.
        """
        reg = Registry()

        class AmbArticleType(DjangoObjectType):
            """Article output type for the ambiguous nested list."""

            class Meta:
                """Bind the type to AuditArticle under the isolated registry."""

                model = AuditArticle
                registry = reg
                filter_fields = {"title": ["exact", "icontains"]}

        class AmbEditorType(DjangoObjectType):
            """Editor output type declaring an ambiguously named nested list."""

            paginated_articles = DjangoFilterPaginateListField(
                AmbArticleType,
                pagination=LimitOffsetGraphqlPagination(default_limit=10),
            )
            listed_articles = DjangoFilterListField(AmbArticleType)

            class Meta:
                """Bind the type to AuditEditor under the isolated registry."""

                model = AuditEditor
                registry = reg

        class Query(ObjectType):
            """Root query exposing the editor list."""

            editors = DjangoFilterListField(AmbEditorType)

        schema = DjangoGraphQLSchema(query=Query, registries=isolated_pair(reg))

        self.assertEqual(
            list(self.creator.created_articles.values_list("title", flat=True)),
            ["a1", "a2"],
        )
        for selection in ("paginatedArticles", "listedArticles"):
            with self.subTest(selection=selection):
                result = graphql_sync(
                    schema.graphql_schema,
                    "{ editors { name %s { title } } }" % selection,
                )
                self.assertIsNotNone(result.errors)
                self.assertIn("created_by", str(result.errors[0]))


# --------------------------------------------------------------------------- #
# 6 — a manual prefetch that the optimizer also derives                        #
# --------------------------------------------------------------------------- #
class ManualPrefetchCollisionTest(TestCase):
    """A manual "prefetch_related" must be replaced, not collide.

    The optimizer appended its own lookups without inspecting
    "_prefetch_related_lookups", so a "get_queryset" hook that prefetched the
    same relation made Django raise mid-resolve.
    """

    @classmethod
    def setUpTestData(cls) -> None:
        """Seed the manual-prefetch fixture.

        One author with two posts, the relation the type's own hook prefetches.
        """
        author = Author.objects.create(name="manual")
        for title in ("m1", "m2"):
            Post.objects.create(title=title, author=author)

    @staticmethod
    def _schema(lookup: str) -> DjangoGraphQLSchema:
        """Build a schema whose "get_queryset" prefetches "lookup".

        Args:
            lookup: The relation the type's own hook prefetches.

        Returns:
            The compiled schema for the manual-prefetch query.
        """
        reg = Registry()

        class ManualPostType(DjangoObjectType):
            """Post output type for the nested list."""

            class Meta:
                """Bind the type to Post under the isolated registry."""

                model = Post
                registry = reg

        class ManualAuthorType(DjangoObjectType):
            """Author output type prefetching a relation in its own hook."""

            class Meta:
                """Bind the type to Author under the isolated registry."""

                model = Author
                registry = reg

            @classmethod
            def get_queryset(cls, queryset, info):
                """Return the documented manual prefetch.

                Args:
                    queryset: The base queryset built for the request.
                    info: The GraphQL resolve info for the current field.

                Returns:
                    The queryset with the manual prefetch attached.
                """
                return queryset.prefetch_related(lookup)

        class Query(ObjectType):
            """Root query exposing the author list."""

            authors = DjangoFilterListField(ManualAuthorType)

        return DjangoGraphQLSchema(query=Query, registries=isolated_pair(reg))

    def test_manual_prefetch_of_the_same_lookup_is_superseded(self) -> None:
        """The optimizer's derived prefetch must replace the manual one.

        This test breaks if the optimizer appends its lookups without dropping
        the ones already on the queryset: Django raises "'posts' lookup was
        already seen with a different queryset" and the whole field resolves
        to null.
        """
        data = _exec(
            self._schema("posts"),
            "{ authors { name posts { results { title } totalCount } } }",
        )
        row = data["authors"][0]
        self.assertEqual(row["posts"]["totalCount"], 2)
        self.assertEqual(
            [entry["title"] for entry in row["posts"]["results"]], ["m1", "m2"]
        )

    def test_manual_prefetch_of_another_lookup_survives(self) -> None:
        """A manual prefetch the optimizer does not derive must be kept.

        This test breaks if the supersede step clears the queryset's lookups
        wholesale instead of dropping only the ones it is about to re-add: the
        unrelated "coauthored_posts" prefetch disappears and its query with it.
        """
        schema = self._schema("coauthored_posts")
        with CaptureQueriesContext(connection) as captured:
            _exec(schema, "{ authors { name posts { results { title } } } }")

        self.assertEqual(len(captured.captured_queries), 3, _sql(captured))
