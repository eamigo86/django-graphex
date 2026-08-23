"""Regression tests for aliased nested lists and nested window pagination.

Covers four optimizer defects that all produced WRONG ROWS through the public
schema:

* two aliases of the same nested-list accessor carrying different filters,
* a filtered alias sitting next to an unfiltered one,
* a windowed alias sitting next to an unfiltered one,
* a window nested under a windowed parent (double pagination),
* an "optimize_<field>" hook on a reverse FK declared without a
  "related_name".
"""

from __future__ import annotations

from django.test import TestCase
from graphql import graphql_sync

from django_graphex.core import ObjectType
from django_graphex.fields import DjangoNestedListObjectField
from django_graphex.paginations.pagination import LimitOffsetGraphqlPagination
from django_graphex.registry import Registry
from django_graphex.schema import DjangoGraphQLSchema
from django_graphex.types import (
    DjangoListObjectField,
    DjangoListObjectType,
    DjangoObjectType,
)

from ._schema_isolation import isolated_pair
from .models import AliasWinAuthor, AliasWinComment, AliasWinNote, AliasWinPost


def _gtype(name: str, bases: tuple, ns: dict) -> type:
    """Build a native output type dynamically with a pydantic-safe namespace.

    Args:
        name: The class name to create.
        bases: The base classes for the new type.
        ns: The class namespace, whose nested "Meta" is re-qualified.

    Returns:
        The newly created type.
    """
    ns = dict(ns)
    ns.setdefault("__module__", __name__)
    ns["__qualname__"] = name
    for attr_name, attr_val in list(ns.items()):
        if isinstance(attr_val, type):
            attr_val.__qualname__ = f"{name}.{attr_name}"
    return type(name, bases, ns)


def _build_schema(prefix: str, page_size: int = 5) -> DjangoGraphQLSchema:
    """Build an author -> posts -> comments schema with filterable nested posts.

    Args:
        prefix: A unique per-test prefix for every generated type name.
        page_size: The default page size for both nested paginators.

    Returns:
        The compiled schema exposing a root "authors" list.
    """
    reg = Registry()
    pag = LimitOffsetGraphqlPagination(default_limit=page_size)

    _gtype(
        prefix + "CommentType",
        (DjangoObjectType,),
        {"Meta": _gtype("Meta", (), {"model": AliasWinComment, "registry": reg})},
    )
    comment_list = _gtype(
        prefix + "CommentListType",
        (DjangoListObjectType,),
        {
            "Meta": _gtype(
                "Meta",
                (),
                {"model": AliasWinComment, "pagination": pag, "registry": reg},
            )
        },
    )
    _gtype(
        prefix + "PostType",
        (DjangoObjectType,),
        {
            "comments": DjangoNestedListObjectField(comment_list, accessor="comments"),
            "Meta": _gtype("Meta", (), {"model": AliasWinPost, "registry": reg}),
        },
    )
    post_list = _gtype(
        prefix + "PostListType",
        (DjangoListObjectType,),
        {
            "Meta": _gtype(
                "Meta",
                (),
                {
                    "model": AliasWinPost,
                    "pagination": pag,
                    "filter_fields": {"title": ["exact", "icontains"]},
                    "registry": reg,
                },
            )
        },
    )
    _gtype(
        prefix + "AuthorType",
        (DjangoObjectType,),
        {
            "posts": DjangoNestedListObjectField(post_list, accessor="posts"),
            "Meta": _gtype("Meta", (), {"model": AliasWinAuthor, "registry": reg}),
        },
    )
    author_list = _gtype(
        prefix + "AuthorListType",
        (DjangoListObjectType,),
        {"Meta": _gtype("Meta", (), {"model": AliasWinAuthor, "registry": reg})},
    )
    return DjangoGraphQLSchema(
        query=_gtype(
            prefix + "Query",
            (ObjectType,),
            {"authors": DjangoListObjectField(author_list)},
        ),
        registries=isolated_pair(reg),
    )


def _execute(schema: DjangoGraphQLSchema, query: str) -> dict:
    """Run "query" against "schema" and return its data, asserting no errors.

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


def _titles(block: dict) -> list[str]:
    """Extract the post titles from a nested list block.

    Args:
        block: A nested list payload with a "results" key.

    Returns:
        The list of "title" values in result order.
    """
    return [row["title"] for row in block["results"]]


class TestAliasedNestedListFilters(TestCase):
    """Two aliases of one nested-list accessor must not share a wrong cache.

    See the tests below for the exact contract covered.
    """

    @classmethod
    def setUpTestData(cls) -> None:
        """Create one author with two KEEP posts and two DROP posts.

        This test breaks if this contract regresses.
        """
        cls.author = AliasWinAuthor.objects.create(name="AliasAuthor")
        for title in ("KEEP 0", "KEEP 1", "DROP 2", "DROP 3"):
            AliasWinPost.objects.create(title=title, author=cls.author)

    def test_two_different_filters_on_the_same_accessor(self) -> None:
        """Each aliased filter must return only its own matching rows.

        This test breaks if the ambiguous-lookup dedup leaves an unfiltered
        prefetch cache behind, which made both aliases return all four posts.
        """
        schema = _build_schema("_AW1")
        data = _execute(
            schema,
            """
            { authors { results {
                keep: posts(filter: {title: {icontains: "KEEP"}}) {
                    totalCount results { title } }
                drop: posts(filter: {title: {icontains: "DROP"}}) {
                    totalCount results { title } }
            } } }
            """,
        )
        row = data["authors"]["results"][0]
        self.assertEqual(_titles(row["keep"]), ["KEEP 0", "KEEP 1"])
        self.assertEqual(row["keep"]["totalCount"], 2)
        self.assertEqual(_titles(row["drop"]), ["DROP 2", "DROP 3"])
        self.assertEqual(row["drop"]["totalCount"], 2)

    def test_filtered_alias_next_to_unfiltered_alias(self) -> None:
        """A filtered alias must not leak its rows into an unfiltered sibling.

        This test breaks if the filtered prefetch cache is reused by the
        unfiltered alias, which reported two posts instead of four.
        """
        schema = _build_schema("_AW2")
        data = _execute(
            schema,
            """
            { authors { results {
                filtered: posts(filter: {title: {icontains: "KEEP"}}) {
                    totalCount results { title } }
                every: posts { totalCount results { title } }
            } } }
            """,
        )
        row = data["authors"]["results"][0]
        self.assertEqual(_titles(row["filtered"]), ["KEEP 0", "KEEP 1"])
        self.assertEqual(row["filtered"]["totalCount"], 2)
        self.assertEqual(
            _titles(row["every"]), ["KEEP 0", "KEEP 1", "DROP 2", "DROP 3"]
        )
        self.assertEqual(row["every"]["totalCount"], 4)

    def test_windowed_alias_next_to_unfiltered_alias(self) -> None:
        """A windowed alias must not truncate its unfiltered sibling.

        This test breaks if the window-sliced page is reused as the unfiltered
        alias's cache, which returned two rows while reporting totalCount 4 in
        the very same object.
        """
        schema = _build_schema("_AW3")
        data = _execute(
            schema,
            """
            { authors { results {
                win: posts { totalCount results(limit: 2) { title } }
                every: posts { totalCount results { title } }
            } } }
            """,
        )
        row = data["authors"]["results"][0]
        self.assertEqual(_titles(row["win"]), ["KEEP 0", "KEEP 1"])
        self.assertEqual(row["win"]["totalCount"], 4)
        self.assertEqual(
            _titles(row["every"]), ["KEEP 0", "KEEP 1", "DROP 2", "DROP 3"]
        )
        self.assertEqual(row["every"]["totalCount"], 4)

    def test_identical_filters_on_two_aliases_share_one_prefetch(self) -> None:
        """Two aliases carrying the SAME filter must both return the filtered rows.

        This test breaks if an unambiguous repeated lookup stops sharing its
        filtered prefetch and falls back to an unfiltered cache.
        """
        schema = _build_schema("_AW4")
        data = _execute(
            schema,
            """
            { authors { results {
                a: posts(filter: {title: {icontains: "KEEP"}}) {
                    totalCount results { title } }
                b: posts(filter: {title: {icontains: "KEEP"}}) {
                    totalCount results { title } }
            } } }
            """,
        )
        row = data["authors"]["results"][0]
        self.assertEqual(_titles(row["a"]), ["KEEP 0", "KEEP 1"])
        self.assertEqual(_titles(row["b"]), ["KEEP 0", "KEEP 1"])
        self.assertEqual(row["a"]["totalCount"], 2)
        self.assertEqual(row["b"]["totalCount"], 2)


class TestNestedWindowUnderWindowedParent(TestCase):
    """A window nested under a windowed parent must be paginated exactly once.

    See the tests below for the exact contract covered.
    """

    @classmethod
    def setUpTestData(cls) -> None:
        """Create one author with one post carrying five comments.

        This test breaks if this contract regresses.
        """
        cls.author = AliasWinAuthor.objects.create(name="NestedWinAuthor")
        cls.post = AliasWinPost.objects.create(title="p1", author=cls.author)
        for i in range(1, 6):
            AliasWinComment.objects.create(text=f"c{i}", post=cls.post)

    QUERY = """
    { authors { results {
        posts { results(limit: 5) {
            title
            comments { totalCount results(limit: 2, offset: 1) { text } }
        } }
    } } }
    """

    def test_nested_window_is_not_paginated_twice(self) -> None:
        """The inner page must be the second and third comment, with totalCount 5.

        This test breaks if the re-rooted child Prefetch loses its "to_attr",
        which let the already-sliced page land in the ordinary prefetch cache
        and be sliced a second time in memory.
        """
        schema = _build_schema("_AW5")
        data = _execute(schema, self.QUERY)
        comments = data["authors"]["results"][0]["posts"]["results"][0]["comments"]
        self.assertEqual([row["text"] for row in comments["results"]], ["c2", "c3"])
        self.assertEqual(comments["totalCount"], 5)

    def test_nested_window_offset_beyond_end_reports_the_full_count(self) -> None:
        """An empty inner page must still report the true partition size.

        This test breaks if the re-rooted child Prefetch stops being detected
        as window-sliced, since the empty page would then be indistinguishable
        from a parent with no comments at all.
        """
        schema = _build_schema("_AW6")
        data = _execute(
            schema,
            """
            { authors { results {
                posts { results(limit: 5) {
                    comments { totalCount results(limit: 2, offset: 99) { text } }
                } }
            } } }
            """,
        )
        comments = data["authors"]["results"][0]["posts"]["results"][0]["comments"]
        self.assertEqual(comments["results"], [])
        self.assertEqual(comments["totalCount"], 5)


class TestOptimizeHookOnRelatedNameLessReverseFk(TestCase):
    """An "optimize_<field>" hook must not mis-resolve a "<model>_set" accessor.

    See the tests below for the exact contract covered.
    """

    @classmethod
    def setUpTestData(cls) -> None:
        """Create one post carrying two notes through a related_name-less FK.

        This test breaks if this contract regresses.
        """
        cls.author = AliasWinAuthor.objects.create(name="NoteAuthor")
        cls.post = AliasWinPost.objects.create(title="p1", author=cls.author)
        AliasWinNote.objects.create(body="n1", post=cls.post)
        AliasWinNote.objects.create(body="n2", post=cls.post)

    def _build(self, prefix: str) -> DjangoGraphQLSchema:
        """Build a posts schema whose nested notes list declares an optimize hook.

        Args:
            prefix: A unique per-test prefix for every generated type name.

        Returns:
            The compiled schema exposing a root "posts" list.
        """
        reg = Registry()
        pag = LimitOffsetGraphqlPagination(default_limit=5)

        _gtype(
            prefix + "NoteType",
            (DjangoObjectType,),
            {"Meta": _gtype("Meta", (), {"model": AliasWinNote, "registry": reg})},
        )
        note_list = _gtype(
            prefix + "NoteListType",
            (DjangoListObjectType,),
            {
                "Meta": _gtype(
                    "Meta",
                    (),
                    {"model": AliasWinNote, "pagination": pag, "registry": reg},
                )
            },
        )

        def optimize_aliaswinnote_set(qs, info, **kwargs):
            """Return the notes queryset untouched.

            Args:
                qs: The child queryset the optimizer is about to prefetch.
                info: The GraphQL resolve info.
                **kwargs: The filter value and window flag forwarded by the
                    optimizer.

            Returns:
                The unmodified queryset.
            """
            return qs

        _gtype(
            prefix + "PostType",
            (DjangoObjectType,),
            {
                "aliaswinnote_set": DjangoNestedListObjectField(
                    note_list, accessor="aliaswinnote_set"
                ),
                "optimize_aliaswinnote_set": staticmethod(optimize_aliaswinnote_set),
                "Meta": _gtype("Meta", (), {"model": AliasWinPost, "registry": reg}),
            },
        )
        post_list = _gtype(
            prefix + "PostListType",
            (DjangoListObjectType,),
            {
                "Meta": _gtype(
                    "Meta",
                    (),
                    {"model": AliasWinPost, "pagination": pag, "registry": reg},
                )
            },
        )
        return DjangoGraphQLSchema(
            query=_gtype(
                prefix + "Query",
                (ObjectType,),
                {"posts": DjangoListObjectField(post_list)},
            ),
            registries=isolated_pair(reg),
        )

    QUERY = """
    { posts { results { title
        aliaswinnoteSet { totalCount results { body } } } } }
    """

    def test_hook_on_related_name_less_reverse_fk_resolves(self) -> None:
        """The nested notes list must resolve instead of raising a field error.

        This test breaks if the plain-prefetch hook resolves the "<model>_set"
        accessor with "_meta.get_field" and silently substitutes the OWNER
        model, which produced a "Cannot resolve keyword" FieldError.
        """
        from django.test import override_settings

        schema = self._build("_AW7")
        # OPTIMIZE_ONLY_FIELDS off keeps the lookup a bare string, which is the
        # branch that wrapped it into a Prefetch with the wrong model.
        with override_settings(
            DJANGO_GRAPHEX={
                "OPTIMIZE_NESTED_PAGINATION": False,
                "OPTIMIZE_ONLY_FIELDS": False,
            }
        ):
            data = _execute(schema, self.QUERY)
        notes = data["posts"]["results"][0]["aliaswinnoteSet"]
        self.assertEqual([row["body"] for row in notes["results"]], ["n1", "n2"])
        self.assertEqual(notes["totalCount"], 2)


class TestUnresolvableHookLookup(TestCase):
    """An optimize hook on a lookup no relation map can resolve is skipped.

    See the tests below for the exact contract covered.
    """

    @staticmethod
    def _hook(qs, info, **kwargs):
        """Return the queryset untouched.

        Args:
            qs: The child queryset the optimizer is about to prefetch.
            info: The GraphQL resolve info.
            **kwargs: The filter value and window flag forwarded by the
                optimizer.

        Returns:
            The unmodified queryset.
        """
        return qs

    def test_plain_hook_leaves_an_unresolvable_lookup_untouched(self) -> None:
        """A lookup with no matching relation stays the bare string it was.

        This test breaks if the resolver starts substituting the OWNER model,
        which built a Prefetch whose queryset had the wrong model.
        """
        from django_graphex.utils import _apply_plain_hook

        hook_map = {"nope": (None, self._hook)}
        item = _apply_plain_hook(AliasWinPost, "nope", hook_map, None)
        self.assertEqual(item, "nope")

    def test_rerooted_child_with_an_unresolvable_lookup_stays_a_string(self) -> None:
        """A re-rooted child whose relation cannot be resolved keeps its lookup.

        This test breaks if the re-root path substitutes the ancestor model
        instead of leaving the plain child lookup alone.
        """
        from django.db.models import Prefetch

        from django_graphex.utils import _merge_filtered_prefetches

        parent = Prefetch("posts", queryset=AliasWinPost.objects.all())
        hook_map = {"posts__nope": (None, self._hook)}
        top_plain, top_filtered = _merge_filtered_prefetches(
            ["posts__nope"], [parent], hook_map=hook_map
        )
        self.assertEqual(top_plain, [])
        self.assertEqual(top_filtered, [parent])
