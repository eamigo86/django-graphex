"""Regression tests for deterministic model-backed offset and page ordering."""

from __future__ import annotations

import json
import re
from unittest.mock import patch

import pytest
from django.db import connection
from django.db.models import F
from django.db.models.expressions import Col
from django.test import RequestFactory, TestCase
from django.test.utils import CaptureQueriesContext
from graphql import GraphQLError, graphql_sync

from django_graphex.paginations.pagination import (
    LimitOffsetGraphqlPagination,
    PageGraphqlPagination,
    _append_model_pk_ordering,
)
from django_graphex.views import GraphQLView

from .models import Author, Post, SubSlugPkItem


class PkTiebreakOrderingTest(TestCase):
    """Keep requested direction while ordering equal-key rows by PK ascending.

    The fixture separates insertion sequence from PK order.
    """

    @classmethod
    def setUpTestData(cls) -> None:
        """Create equal-key rows with non-monotonic primary-key insertion.

        This makes the expected secondary order explicit in each assertion.
        """
        cls.author = Author.objects.create(name="author")
        for pk in (30, 10, 20):
            Post.objects.create(pk=pk, title="same", author=cls.author)

    def test_limit_offset_db_appends_pk_to_client_order(self) -> None:
        """Require explicit SQL ordering so physical SQLite order cannot mask ties.

        The second slice must cover the remaining row without overlap.
        """
        paginator = LimitOffsetGraphqlPagination(default_limit=2, max_limit=2)
        page = paginator.paginate_queryset(Post.objects.all(), ordering="-title")
        assert page.query.order_by == ("-title", "id")
        assert [row.pk for row in page] == [10, 20]
        next_page = paginator.paginate_queryset(
            Post.objects.all(), ordering="-title", offset=2
        )
        assert [row.pk for row in next_page] == [30]

    def test_page_db_appends_pk_to_client_order(self) -> None:
        """Require the same SQL secondary key for page-number pagination.

        Both positive page numbers must cover the static fixture exactly once.
        """
        paginator = PageGraphqlPagination(page_size=2, max_page_size=2)
        page = paginator.paginate_queryset(Post.objects.all(), ordering="-title")
        assert page.query.order_by == ("-title", "id")
        assert [row.pk for row in page] == [10, 20]
        next_page = paginator.paginate_queryset(
            Post.objects.all(), ordering="-title", page=2
        )
        assert [row.pk for row in next_page] == [30]

    def test_materialized_model_list_uses_same_tie_break(self) -> None:
        """Sort cached model rows by PK even when their source order differs.

        The database path alone would not protect nested materialized rows.
        """
        rows = list(Post.objects.order_by("-pk"))
        paginator = LimitOffsetGraphqlPagination(default_limit=2, max_limit=2)
        first = paginator.paginate_queryset(rows, ordering="-title")
        second = paginator.paginate_queryset(rows, ordering="-title", offset=2)
        assert [row.pk for row in first] == [10, 20]
        assert [row.pk for row in second] == [30]

    def test_explicit_descending_pk_is_not_overridden(self) -> None:
        """Keep a client's descending PK term without appending another key.

        The explicit direction must win over the internal ascending default.
        """
        paginator = PageGraphqlPagination(page_size=3, max_page_size=3)
        result = paginator.paginate_queryset(Post.objects.all(), ordering="-title,-pk")
        assert result.query.order_by == ("-title", "-pk")
        assert [row.pk for row in result] == [30, 20, 10]

    def test_explicit_id_inside_multiple_terms_is_not_duplicated(self) -> None:
        """Recognize the concrete PK name even when it is not the last term.

        Duplicating it at the end would change the declared term list.
        """
        paginator = LimitOffsetGraphqlPagination(default_limit=3, max_limit=3)
        result = paginator.paginate_queryset(
            Post.objects.all(), ordering="-title,-id,views"
        )
        assert result.query.order_by == ("-title", "-id", "views")
        assert [row.pk for row in result] == [30, 20, 10]

    def test_no_order_uses_pk_and_page_materialized_rows_match(self) -> None:
        """Order otherwise unordered rows by PK on both bounded paths.

        A shuffled list must agree with the direct database page.
        """
        paginator = PageGraphqlPagination(page_size=2, max_page_size=2)
        db_page = paginator.paginate_queryset(Post.objects.all())
        cached_page = paginator.paginate_queryset(list(Post.objects.order_by("-pk")))
        assert db_page.query.order_by == ("id",)
        assert [row.pk for row in db_page] == [10, 20]
        assert [row.pk for row in cached_page] == [10, 20]

    def test_queryset_default_and_explicit_order_are_preserved(self) -> None:
        """Append PK only after queryset ordering and respect an explicit PK.

        The caller's original queryset must not be mutated.
        """
        paginator = LimitOffsetGraphqlPagination(default_limit=3, max_limit=3)
        base = Post.objects.order_by("-title")
        result = paginator.paginate_queryset(base)
        assert result.query.order_by == ("-title", "id")
        assert base.query.order_by == ("-title",)
        already_total = paginator.paginate_queryset(Post.objects.order_by("-pk"))
        assert already_total.query.order_by == ("-pk",)

    def test_queryset_expression_order_stays_ahead_of_pk(self) -> None:
        """Preserve an existing ORM expression instead of rebuilding a string.

        The internal key is only a secondary term after the expression.
        """
        paginator = LimitOffsetGraphqlPagination(default_limit=3, max_limit=3)
        expression = F("title").desc()
        original = Post.objects.order_by(expression)
        result = paginator.paginate_queryset(original)
        assert result.query.order_by == (expression, "id")
        assert original.query.order_by == (expression,)

    def test_queryset_extra_ordering_stays_ahead_of_pk(self) -> None:
        """Preserve an existing extra-ordering term before the internal key.

        Legacy querysets using extra ordering must keep their primary term.
        """
        paginator = LimitOffsetGraphqlPagination(default_limit=3, max_limit=3)
        original = Post.objects.extra(order_by=["-title"])
        assert original.query.extra_order_by == ["-title"]
        result = paginator.paginate_queryset(original)
        assert result.query.order_by == ("-title", "id")
        assert original.query.extra_order_by == ["-title"]

    def test_col_pk_expression_is_not_duplicated(self) -> None:
        """Recognize an ORM column expression that already orders by PK.

        A target-backed expression is equivalent to the concrete key name.
        """
        expression = Col(Post._meta.db_table, Post._meta.pk)
        assert _append_model_pk_ordering(Post, [expression]) == [expression]

    def test_unbounded_no_order_preserves_original_queryset_cache(self) -> None:
        """Keep the original evaluated queryset when no page boundary exists.

        Its populated result cache must still satisfy totalCount without SQL.
        """
        paginator = LimitOffsetGraphqlPagination(default_limit=None, max_limit=None)
        original = Post.objects.all()
        assert [row.pk for row in original] == [10, 20, 30]
        result = paginator.paginate_queryset(original)
        assert result is original
        with self.assertNumQueries(0):
            assert result.count() == 3

    def test_unbounded_no_order_retains_meta_ordering_without_a_clone(self) -> None:
        """Keep a Meta-ordered queryset's identity for lazy totalCount reuse.

        The pre-existing handle order is not rewritten for an unbounded list.
        """
        from tests.test_optimizer_coverage import Profile

        paginator = LimitOffsetGraphqlPagination(default_limit=None, max_limit=None)
        original = Profile.objects.all()
        assert original.query.order_by == ()
        assert original.query.default_ordering is True
        assert Profile._meta.ordering == ["handle"]
        assert paginator.paginate_queryset(original) is original

    def test_internal_pk_does_not_expand_client_ordering_allowlist(self) -> None:
        """Append a hidden internal key but still reject hidden client terms.

        Client validation precedes the server-generated secondary term.
        """
        paginator = LimitOffsetGraphqlPagination(default_limit=2, max_limit=2)
        paginator.ordering_allowed_attnames = {"title"}
        accepted = paginator.paginate_queryset(Post.objects.all(), ordering="title")
        assert accepted.query.order_by == ("title", "id")
        for hidden in ("id", "pk", "body"):
            with pytest.raises(GraphQLError, match="Invalid ordering field"):
                paginator.paginate_queryset(Post.objects.all(), ordering=hidden)

    def test_model_meta_ordering_survives_db_and_materialized_paths(self) -> None:
        """Keep the model's primary term and add PK only after it.

        Materialized and database paths must agree on both terms.
        """
        Post.objects.filter(pk=10).update(title="a")
        Post.objects.filter(pk=20).update(title="z")
        Post.objects.filter(pk=30).update(title="a")
        paginator = LimitOffsetGraphqlPagination(default_limit=2, max_limit=2)
        with patch.object(Post._meta, "ordering", ["-title"]):
            db_page = paginator.paginate_queryset(Post.objects.all())
            cached_page = paginator.paginate_queryset(
                list(Post.objects.order_by("-pk"))
            )
        assert db_page.query.order_by == ("-title", "id")
        assert [row.pk for row in db_page] == [20, 10]
        assert [row.pk for row in cached_page] == [20, 10]

    def test_unsupported_meta_list_ordering_keeps_pk_fallback(self) -> None:
        """Keep the historical list fallback for a relation-spanning Meta term.

        The in-memory sorter cannot safely evaluate ORM joins on model rows.
        """
        rows = list(Post.objects.order_by("-pk"))
        paginator = LimitOffsetGraphqlPagination(default_limit=2, max_limit=2)
        with patch.object(Post._meta, "ordering", ["author__name"]):
            result = paginator.paginate_queryset(rows)
        assert [row.pk for row in result] == [10, 20]

    def test_natural_pk_uses_field_name_not_id(self) -> None:
        """Tie-break a model whose primary key is a non-id slug.

        The ORM term must come from model metadata rather than assume id.
        """
        for slug in ("c", "a", "b"):
            SubSlugPkItem.objects.create(slug=slug, title="same")
        paginator = LimitOffsetGraphqlPagination(default_limit=2, max_limit=2)
        result = paginator.paginate_queryset(
            SubSlugPkItem.objects.all(), ordering="title"
        )
        assert result.query.order_by == ("title", "slug")
        assert [row.pk for row in result] == ["a", "b"]

    def test_natural_pk_alias_and_attname_keep_explicit_direction(self) -> None:
        """Do not add another slug term after either explicit PK spelling.

        Django's alias and the concrete field name both retain descending order.
        """
        for slug in ("c", "a", "b"):
            SubSlugPkItem.objects.create(slug=slug, title="same")
        paginator = PageGraphqlPagination(page_size=3, max_page_size=3)
        for name in ("pk", "slug"):
            result = paginator.paginate_queryset(
                SubSlugPkItem.objects.all(), ordering=f"title,-{name}"
            )
            assert result.query.order_by == ("title", f"-{name}")
            assert [row.pk for row in result] == ["c", "b", "a"]

    def test_reverse_fk_window_row_number_uses_pk_secondary(self) -> None:
        """Require ROW_NUMBER to use the same secondary key as direct pages.

        The assertion checks generated SQL rather than incidental row order.
        """
        from tests.test_optimizer_phase_c import (
            _make_test_nested_field,
            _row_gql_type,
        )

        field = _make_test_nested_field()
        pf = field.build_window_prefetch(
            lookup="posts",
            filter_value=None,
            slice_tuple=(0, 2, ["-title"]),
            related_field=Author._meta.get_field("posts"),
            sub_selection=None,
            fragments={},
            child_gql_type=_row_gql_type(field),
        )
        assert pf is not None
        sql = str(pf.queryset.query)
        assert re.search(r"ROW_NUMBER\(\) OVER .*ORDER BY .*title.*DESC.*id.*ASC", sql)

    def test_reverse_fk_window_keeps_model_meta_ordering(self) -> None:
        """Use Meta.ordering before the PK in an unconfigured window page.

        A missing client term must not discard the model's ordering policy.
        """
        from tests.test_optimizer_phase_c import (
            _make_test_nested_field,
            _row_gql_type,
        )

        field = _make_test_nested_field()
        with patch.object(Post._meta, "ordering", ["-title"]):
            pf = field.build_window_prefetch(
                lookup="posts",
                filter_value=None,
                slice_tuple=(0, 2, []),
                related_field=Author._meta.get_field("posts"),
                sub_selection=None,
                fragments={},
                child_gql_type=_row_gql_type(field),
            )
            assert pf is not None
            sql = str(pf.queryset.query)
        assert re.search(r"ROW_NUMBER\(\) OVER .*ORDER BY .*title.*DESC.*id.*ASC", sql)

    def test_reverse_fk_window_keeps_hook_queryset_ordering(self) -> None:
        """Keep a server hook's ordering when the client supplies none.

        The internal tie-break follows the hook's primary direction.
        """
        from tests.test_optimizer_phase_c import (
            _make_test_nested_field,
            _row_gql_type,
        )

        def ordered_hook(qs, info, *, filter_value, is_window):
            """Return a queryset ordered by the hook's server-owned term."""
            return qs.order_by("-title")

        field = _make_test_nested_field()
        pf = field.build_window_prefetch(
            lookup="posts",
            filter_value=None,
            slice_tuple=(0, 2, []),
            related_field=Author._meta.get_field("posts"),
            sub_selection=None,
            fragments={},
            child_gql_type=_row_gql_type(field),
            hook=ordered_hook,
        )
        assert pf is not None
        sql = str(pf.queryset.query)
        assert re.search(r"ROW_NUMBER\(\) OVER .*ORDER BY .*title.*DESC.*id.*ASC", sql)

    def test_reverse_fk_window_keeps_extra_queryset_ordering(self) -> None:
        """Keep a hook's legacy extra ordering before the window tie-break.

        Its SQL term remains primary even without a client ordering argument.
        """
        from tests.test_optimizer_phase_c import _make_test_nested_field, _row_gql_type

        field = _make_test_nested_field()

        def extra_hook(qs, info, *, filter_value, is_window):
            """Return a legacy queryset with a server-owned ordering term."""
            return qs.extra(order_by=["-title"])

        pf = field.build_window_prefetch(
            lookup="posts",
            filter_value=None,
            slice_tuple=(0, 2, []),
            related_field=Author._meta.get_field("posts"),
            sub_selection=None,
            fragments={},
            child_gql_type=_row_gql_type(field),
            hook=extra_hook,
        )
        assert pf is not None
        sql = str(pf.queryset.query)
        assert re.search(r"ROW_NUMBER\(\) OVER .*ORDER BY .*title.*DESC.*id.*ASC", sql)

    def test_reverse_fk_window_falls_back_for_unsupported_hook_terms(self) -> None:
        """Use plain prefetch for ORM expressions and relation-spanning terms.

        Neither unsupported term is silently replaced in window SQL.
        """
        from tests.test_optimizer_phase_c import _make_test_nested_field, _row_gql_type

        field = _make_test_nested_field()
        for term in (F("title").asc(), "author__name"):

            def hook(qs, info, *, filter_value, is_window):
                """Return a queryset ordered by this case's server term."""
                return qs.order_by(term)

            pf = field.build_window_prefetch(
                lookup="posts",
                filter_value=None,
                slice_tuple=(0, 2, []),
                related_field=Author._meta.get_field("posts"),
                sub_selection=None,
                fragments={},
                child_gql_type=_row_gql_type(field),
                hook=hook,
            )
            assert pf is None

    def test_nested_hidden_pk_is_internal_not_client_ordering(self) -> None:
        """Use a hidden PK internally while rejecting hidden client fields.

        The projected child exposes title, not id or body, to the client.
        """
        from tests.test_pagination_ordering_projection import win_pk_schema

        with CaptureQueriesContext(connection) as captured:
            accepted = graphql_sync(
                win_pk_schema.graphql_schema,
                '{ authors { results { posts { results(limit: 2, ordering: "title") '
                "{ title } } } } }",
            )
        assert accepted.errors is None, accepted.errors
        sql = " ".join(query["sql"] for query in captured.captured_queries)
        assert re.search(r"ROW_NUMBER\(\) OVER .*ORDER BY .*title.*ASC.*id.*ASC", sql)
        for hidden in ("id", "body"):
            denied = graphql_sync(
                win_pk_schema.graphql_schema,
                '{ authors { results { posts { results(ordering: "'
                + hidden
                + '") { title } } } } }',
            )
            assert denied.errors
            assert f"Invalid ordering field: '{hidden}'." in denied.errors[0].message

    def test_public_graphql_pages_cover_equal_name_rows_once(self) -> None:
        """Serve offset and page-number slices through the public schema.

        Equal-name rows appear once across consecutive GraphQL requests.
        """
        from tests.test_pagination_ordering_security import sec_schema

        for pk in (130, 110, 120):
            Author.objects.create(pk=pk, name="same")
        queries = (
            '{ loList { results(limit: 2, ordering: "-name") { id } } }',
            '{ loList { results(limit: 2, offset: 2, ordering: "-name") { id } } }',
            '{ pageList { results(pageSize: 2, ordering: "-name") { id } } }',
            '{ pageList { results(pageSize: 2, page: 2, ordering: "-name") { id } } }',
        )
        results = [graphql_sync(sec_schema.graphql_schema, query) for query in queries]
        for result in results:
            assert result.errors is None, result.errors
        assert [row["id"] for row in results[0].data["loList"]["results"]] == [
            "110",
            "120",
        ]
        assert [row["id"] for row in results[1].data["loList"]["results"]] == [
            "130",
            str(self.author.pk),
        ]
        assert [row["id"] for row in results[2].data["pageList"]["results"]] == [
            "110",
            "120",
        ]
        assert [row["id"] for row in results[3].data["pageList"]["results"]] == [
            "130",
            str(self.author.pk),
        ]

    def test_http_offset_pages_keep_equal_name_rows_disjoint(self) -> None:
        """Exercise actual JSON requests through the public GraphQL view.

        A static tied dataset must occupy disjoint first and second slices.
        """
        from tests.test_pagination_ordering_security import sec_schema

        for pk in (130, 110, 120):
            Author.objects.create(pk=pk, name="same")
        view = GraphQLView.as_view(schema=sec_schema)
        rows = []
        for offset in (0, 2):
            query = (
                '{ loList { results(limit: 2, offset: %d, ordering: "-name") '
                "{ id } } }" % offset
            )
            response = view(
                RequestFactory().post(
                    "/graphql/",
                    json.dumps({"query": query}),
                    content_type="application/json",
                    HTTP_X_CSRF_TOKEN="test",
                )
            )
            assert response.status_code == 200
            payload = json.loads(response.content)
            assert "errors" not in payload, payload
            rows.extend(row["id"] for row in payload["data"]["loList"]["results"])
        assert rows == ["110", "120", "130", str(self.author.pk)]
