# -*- coding: utf-8 -*-
"""Two measured query-count regressions: eager totalCount and re-resolved children.

Both defects cost SQL, not correctness, so nothing in the suite caught them --
every existing assertion is about the answer, and the answer was already right.
These cases assert the COUNT of queries instead, which is the only shape that
fails when the work is merely repeated.

Invariants asserted here:

* "DjangoModelType.list" issues no COUNT query when the client does not select
  "totalCount", and exactly one -- with the correct total -- when it does,
* a nested reverse-FK child named by primary key is resolved ONCE and has its
  scope checked ONCE, instead of twice each,
* the many-to-many branch resolves its row ONCE for the same reason,
* the authorization outcome of that path is unchanged: the hidden row is still
  refused, and the check still runs.
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

from django.db import connection
from django.test import TestCase
from django.test.utils import CaptureQueriesContext
from graphql import graphql_sync

from django_graphex.core import ObjectType
from django_graphex.schema import DjangoGraphQLSchema
from django_graphex.types import DjangoModelType
from tests.models import (
    AliasWinAuthor,
    AliasWinComment,
    AliasWinPost,
    NestedObjAuthor,
    NestedObjPost,
    NestedObjTag,
    OptimizerPerfCategory,
)

# Borrowed rather than redeclared: "PostM2MType" is the only many-to-many nesting
# host in the suite whose child model has no host of its own, and a second
# "DjangoModelType" over "NestedObjPost" would collide on the companion output
# type it derives globally. Importing it also pins the fixture -- the counts below
# would otherwise depend on which other modules pytest happened to collect.
from tests.test_nested_objects import PostM2MType


class QueryCountCategoryType(DjangoModelType):
    """A bare list host over a model no other module hosts globally.

    "DjangoModelType" always self-registers on the global registry, so the fixture
    model is chosen for being unclaimed rather than for anything it declares.
    """

    class Meta:
        """Bind the type to "OptimizerPerfCategory" with no other option.

        A plain binding is the point: the eager COUNT was in the default list path,
        not in anything a project opts into.
        """

        model = OptimizerPerfCategory


class QueryCountCommentType(DjangoModelType):
    """The nested child's own host, declaring nothing.

    It exists so "hosts_serving" returns exactly one host for the child model,
    which fixes the per-child scope-check cost at one SELECT and makes the
    before/after arithmetic readable.
    """

    class Meta:
        """Bind the type to "AliasWinComment".

        No scope and no permissions: the repeated work under test is the lookup
        itself, which a permissive host pays for just as a restrictive one does.
        """

        model = AliasWinComment


class QueryCountPostType(DjangoModelType):
    """The nesting parent, reaching its children through the reverse FK.

    "comments" is a reverse foreign key, which is the branch that resolved the
    child's primary key once for the ownership guard and again inside the writer.
    """

    class Meta:
        """Bind the type to "AliasWinPost" with "comments" nested.

        Nesting the reverse accessor is what routes a payload through
        "_attach_children", the branch carrying the duplicate lookup.
        """

        model = AliasWinPost
        nested_fields = {"comments": AliasWinComment}


class _Query(ObjectType):
    """Query root mounting the list field under measurement.

    A dedicated schema keeps the count free of fields other modules mount.
    """

    categories = QueryCountCategoryType.ListField()


_SCHEMA = DjangoGraphQLSchema(query=_Query)


def _info() -> SimpleNamespace:
    """Build a bare GraphQL resolve-info stand-in for direct resolver calls.

    Returns:
        An object shaped like a GraphQL resolve info, with a "context" carrying
        empty "META" and "FILES".
    """
    return SimpleNamespace(context=SimpleNamespace(META={}, FILES={}))


def _selects_on(captured: CaptureQueriesContext, model: Any) -> list[str]:
    """Pick the SELECT statements a capture issued against one model's table.

    Counting every statement instead would fold in the savepoints Django's
    "TestCase" wraps each case in, plus the parent's own reads and writes --
    none of which this regression touches.

    Args:
        captured: The finished capture whose statements are inspected.
        model: The Django model whose table the statements must name.

    Returns:
        The SQL of every captured SELECT naming that model's table.
    """
    table = model._meta.db_table
    return [
        query["sql"]
        for query in captured.captured_queries
        if query["sql"].lstrip().upper().startswith("SELECT") and table in query["sql"]
    ]


class ListTotalCountLazinessTest(TestCase):
    """The list path must not pay for a total the client never asked for.

    "DjangoModelType.list" called "qs.count()" unconditionally while the
    "DjangoListObjectField" path passed a supplier, so the two surfaces
    documented as equivalent cost a different number of queries.
    """

    def setUp(self) -> None:
        """Create the rows the two shapes below list.

        Three rows make a wrong total visible; one would survive most mistakes.
        """
        for title in ("a", "b", "c"):
            OptimizerPerfCategory.objects.create(title=title)

    def test_list_without_total_count_issues_no_count_query(self) -> None:
        """Selecting only "results" must cost a single SELECT.

        This test breaks if "list" computes the total eagerly: the COUNT is
        issued for every request, including the majority that never read it.
        """
        with self.assertNumQueries(1):
            result = graphql_sync(
                _SCHEMA.graphql_schema, "{ categories { results { title } } }"
            )

        assert result.errors is None, result.errors
        assert len(result.data["categories"]["results"]) == 3

    def test_list_with_total_count_issues_it_once_and_correctly(self) -> None:
        """Selecting "totalCount" must cost exactly one extra SELECT, with the total.

        The page is deliberately narrower than the table, so the total cannot be
        read off the fetched rows and a real COUNT has to run. This test breaks
        if deferring the COUNT loses it -- a supplier never invoked, invoked
        twice, or invoked on the sliced queryset instead of the whole one.
        """
        with self.assertNumQueries(2):
            result = graphql_sync(
                _SCHEMA.graphql_schema,
                '{ categories { results(limit: 2, ordering: "id") { title } '
                "totalCount } }",
            )

        assert result.errors is None, result.errors
        assert len(result.data["categories"]["results"]) == 2
        assert result.data["categories"]["totalCount"] == 3


class NestedChildResolvedOnceTest(TestCase):
    """A nested child named by primary key must be looked up once, not twice.

    The reverse-FK branch resolved the row for its ownership guard and checked
    its scope, then handed the payload to the writer, which resolved the same
    primary key and re-checked the same scope. The cost is 2x(1 + H) SELECTs per
    child, where H is the number of hosts serving the child's update.
    """

    def setUp(self) -> None:
        """Create a parent and one existing child to update by primary key.

        The child must already exist: the duplicate lookup only happens on the
        upsert branch, where the payload names a row.
        """
        self.author = AliasWinAuthor.objects.create(name="a")
        self.post = AliasWinPost.objects.create(title="p", author=self.author)
        self.comment = AliasWinComment.objects.create(text="original", post=self.post)

    def _update_child(self) -> Any:
        """Run a nested update naming the existing child by primary key.

        Returns:
            The mutation result object (exposes "ok" and, on failure, "errors").
        """
        return QueryCountPostType.update(
            None,
            _info(),
            **{
                QueryCountPostType._meta.input_field_name: {
                    "id": self.post.pk,
                    "comments": [{"id": self.comment.pk, "text": "edited"}],
                }
            },
        )

    def test_reverse_child_is_selected_twice_not_four_times(self) -> None:
        """One nested child must cost two SELECTs on its table, not four.

        One resolves the primary key the payload names, one applies the single
        host's scope. This test breaks if the writer resolves and re-checks the
        row the caller already resolved and checked.
        """
        with CaptureQueriesContext(connection) as captured:
            result = self._update_child()

        assert result.ok, getattr(result, "errors", None)
        selects = _selects_on(captured, AliasWinComment)
        assert len(selects) == 2, "\n".join(selects)

        self.comment.refresh_from_db()
        assert self.comment.text == "edited"

    def test_scope_check_runs_exactly_once_per_child(self) -> None:
        """The authorization check must run once per child, not twice.

        Avoiding a REPEATED check is the whole change; avoiding the check is the
        defect it must not introduce. This test breaks in both directions.
        """
        calls: list[Any] = []
        real = QueryCountPostType._reject_hidden_row

        def spy(field: str, model: Any, pk: Any, info: Any) -> None:
            """Record one scope check and delegate to the real one.

            Args:
                field: The nested field name.
                model: The child's Django model class.
                pk: The primary key named by the nested payload.
                info: GraphQL resolve info for the current request.
            """
            calls.append(pk)
            real(field, model, pk, info)

        # The check lives on the nested mixin, and the writer reaches it through
        # "cls", so the patch has to land on the class that actually defines it.
        holder = next(
            klass
            for klass in QueryCountPostType.__mro__
            if "_reject_hidden_row" in klass.__dict__
        )
        original = holder.__dict__["_reject_hidden_row"]
        holder._reject_hidden_row = staticmethod(spy)
        try:
            result = self._update_child()
        finally:
            holder._reject_hidden_row = original

        assert result.ok, getattr(result, "errors", None)
        assert calls == [self.comment.pk]

    def test_m2m_child_already_linked_is_selected_once(self) -> None:
        """A many-to-many row the parent already carries must be resolved once.

        The branch resolves the row to decide LINK versus WRITE, then hands the
        payload to the writer, which resolved the same primary key again. Its
        child model has no host, so the two remaining SELECTs are the lookup and
        the linkage probe. This test breaks if the lookup is paid for twice.
        """
        author = NestedObjAuthor.objects.create(name="a")
        post = NestedObjPost.objects.create(title="p", author=author)
        tag = NestedObjTag.objects.create(label="original")
        post.tags.add(tag)

        with CaptureQueriesContext(connection) as captured:
            result = PostM2MType.update(
                None,
                _info(),
                **{
                    PostM2MType._meta.input_field_name: {
                        "id": post.pk,
                        "tags": [{"id": tag.pk, "label": "edited"}],
                    }
                },
            )

        assert result.ok, getattr(result, "errors", None)
        selects = _selects_on(captured, NestedObjTag)
        assert len(selects) == 2, "\n".join(selects)

        tag.refresh_from_db()
        assert tag.label == "edited"

    def test_a_child_outside_the_hosts_scope_is_still_refused(self) -> None:
        """Deduplicating the lookup must not weaken the scope check.

        The host below hides every row, so the nested update must fail exactly as
        it did before the lookup was shared. This test breaks if the writer trusts
        the instance it was handed instead of the scope that governs it.
        """
        hidden = QueryCountCommentType.get_queryset

        @classmethod  # type: ignore[misc]
        def nothing_visible(cls: Any, qs: Any, info: Any, **kwargs: Any) -> Any:
            """Hide every row of the child model.

            Args:
                cls: The host class.
                qs: Queryset to scope.
                info: GraphQL resolve info for the current request.
                **kwargs: Extra arguments, unused here.

            Returns:
                An empty queryset.
            """
            return AliasWinComment.objects.none()

        QueryCountCommentType.get_queryset = nothing_visible
        try:
            result = self._update_child()
        finally:
            QueryCountCommentType.get_queryset = hidden

        assert not result.ok
        self.comment.refresh_from_db()
        assert self.comment.text == "original"
