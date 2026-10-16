"""Public and unit regressions for negative-page count failures."""

from __future__ import annotations

from typing import Any
from unittest import mock

import pytest
from django.db import DatabaseError, OperationalError, connection
from django.db.models import QuerySet
from django.test.utils import CaptureQueriesContext
from graphql import GraphQLError

from django_graphex.paginations.utils import _get_count
from tests.models import Author, Post
from tests.test_pagination_page_null_http import _post, _query


@pytest.fixture
def page_rows(db: Any) -> list[Post]:
    """Create five ordered posts in the disposable test database.

    Args:
        db: Pytest database fixture.

    Returns:
        The posts in insertion order.
    """
    author = Author.objects.create(name="count-failure-parent")
    return [Post.objects.create(author=author, title=f"Page {i}") for i in range(1, 6)]


@pytest.mark.parametrize(
    "page,variable", [(-1, False), (-2, False), (-1, True), (-2, True)]
)
def test_failed_negative_page_count_is_generic_and_does_not_fetch_rows(
    page_rows: list[Post], page: int, variable: bool
) -> None:
    """Fail closed at the public resolver without materializing the queryset.

    Args:
        page_rows: Five ordered posts in the disposable test database.
        page: Negative page number requiring a count.
        variable: Whether to send the page as a GraphQL variable.
    """
    original_count = QuerySet.count
    original_fetch_all = QuerySet._fetch_all
    counted: list[type[Any]] = []
    fetched: list[type[Any]] = []

    def failing_count(qs: QuerySet[Any]) -> int:
        """Fail only the page queryset's count with sensitive backend text.

        Args:
            qs: Queryset being counted.

        Returns:
            The ordinary count for unrelated querysets.

        Raises:
            DatabaseError: For the post queryset under test.
        """
        if qs.model is Post:
            counted.append(qs.model)
            raise DatabaseError("private_table secret constraint in COUNT")
        return original_count(qs)

    def record_fetch_all(qs: QuerySet[Any]) -> None:
        """Record any post-row evaluation before delegating to Django.

        Args:
            qs: Queryset about to materialize.
        """
        if qs.model is Post:
            fetched.append(qs.model)
        original_fetch_all(qs)

    argument = "page: $page" if variable else f"page: {page}"
    query = _query("root", argument, variable=variable).replace("totalCount ", "")
    with (
        mock.patch.object(QuerySet, "count", failing_count),
        mock.patch.object(QuerySet, "_fetch_all", record_fetch_all),
        CaptureQueriesContext(connection) as queries,
    ):
        body = _post(query, {"page": page} if variable else None)

    assert counted == [Post]
    assert body["errors"][0]["message"] == "Unable to calculate pagination count"
    assert body["errors"][0]["path"] == ["posts", "results"]
    assert fetched == []
    assert not any('FROM "tests_post"' in item["sql"] for item in queries)
    assert body["data"]["posts"]["results"] is None
    assert "private_table" not in str(body)
    assert "secret constraint" not in str(body)


def test_failed_count_does_not_use_length_or_iteration() -> None:
    """Keep the failed-count path independent of collection evaluation.

    Neither length nor iteration may recover a database count failure.
    """

    class BrokenCount:
        """Count failure with instrumented materialization escape hatches."""

        def __init__(self) -> None:
            self.length_calls = 0
            self.iter_calls = 0

        def count(self) -> int:
            """Raise the backend failure.

            Raises:
                OperationalError: Always.
            """
            raise OperationalError("private backend detail")

        def __len__(self) -> int:
            """Track forbidden length evaluation.

            Returns:
                A sentinel length.
            """
            self.length_calls += 1
            return 5

        def __iter__(self) -> Any:
            """Track forbidden iteration.

            Returns:
                An empty iterator.
            """
            self.iter_calls += 1
            return iter(())

    broken = BrokenCount()
    with pytest.raises(GraphQLError, match="^Unable to calculate pagination count$"):
        _get_count(broken)
    assert broken.length_calls == 0
    assert broken.iter_calls == 0


def test_list_fallback_and_unrelated_count_errors_are_unchanged() -> None:
    """Keep list compatibility without swallowing arbitrary count failures.

    Only database errors receive the new GraphQL failure policy.
    """
    assert _get_count([1, 2, 3]) == 3

    class Countless:
        """List-like value with no count method."""

        def __len__(self) -> int:
            """Return a stable count.

            Returns:
                The synthetic collection length.
            """
            return 2

    class InvalidCount:
        """Count method with an unrelated programming error."""

        def count(self) -> int:
            """Raise an error outside the count-failure policy.

            Raises:
                ValueError: Always.
            """
            raise ValueError("invalid count")

    assert _get_count(Countless()) == 2
    with pytest.raises(ValueError, match="invalid count"):
        _get_count(InvalidCount())


def test_positive_page_does_not_attempt_count_when_not_selected(
    page_rows: list[Post],
) -> None:
    """Forward navigation remains independent of the optional count query.

    Args:
        page_rows: Five ordered posts in the disposable test database.
    """
    with mock.patch.object(
        QuerySet, "count", side_effect=AssertionError("count called")
    ):
        body = _post(
            _query("root", 'page: 1, ordering: "id"').replace("totalCount ", "")
        )
    assert "errors" not in body, body
    assert [row["id"] for row in body["data"]["posts"]["results"]] == [
        str(post.pk) for post in page_rows[:2]
    ]
