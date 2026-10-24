"""Tampered cursors answer the same client error on the DB and in-memory paths."""

from __future__ import annotations

import datetime
import logging
import uuid
from decimal import Decimal
from typing import Any

import pytest
from graphql import GraphQLError

from django_graphex.paginations.pagination import CursorGraphqlPagination
from tests.models import Author, ScalarKindsModel

ENCODE = CursorGraphqlPagination.encode_cursor

# (ordering field, tampered ordering value, pk component)
TAMPERED = [
    ("decimal", "NaN", "1"),
    ("decimal", "nan", "1"),
    ("decimal", "sNaN", "1"),
    ("decimal", "Infinity", "1"),
    ("decimal", "-Infinity", "1"),
    ("decimal", "abc", "1"),
    ("decimal", "1.00", "zzz"),
    ("floating", "nan", "1"),
    ("floating", "inf", "1"),
    ("floating", "abc", "1"),
    ("integer", "1.5", "1"),
    ("integer", "abc", "1"),
    ("date", "not-a-date", "1"),
    ("date", "9" * 3000, "1"),
    ("datetime", "not-a-date", "1"),
    ("datetime", "2024-01-01T00:00:00+00:00", "x"),
    ("uuid_field", "not-a-uuid", "1"),
    ("decimal", "abc", None),
    ("date", "1.00", None),
]


@pytest.fixture
def rows() -> list[ScalarKindsModel]:
    """Create five rows with a value of every ordering type.

    Returns:
        The created rows.
    """
    author = Author.objects.create(name="a")
    return [
        ScalarKindsModel.objects.create(
            author=author,
            char="c",
            integer=i,
            floating=float(i),
            decimal=Decimal(i),
            uuid_field=uuid.UUID(int=i + 1),
            date=datetime.date(2024, 1, 1 + i),
            datetime=datetime.datetime(2024, 1, 1 + i, tzinfo=datetime.timezone.utc),
        )
        for i in range(5)
    ]


def _sources() -> list[Any]:
    """Return the DB and in-memory sources over the same rows.

    Returns:
        A queryset and an equivalent list.
    """
    return [ScalarKindsModel.objects.all(), list(ScalarKindsModel.objects.all())]


@pytest.mark.django_db
@pytest.mark.parametrize("field,value,pk", TAMPERED)
def test_tampered_cursor_is_invalid_cursor_on_both_paths(
    rows: list[ScalarKindsModel],
    caplog: pytest.LogCaptureFixture,
    field: str,
    value: str,
    pk: str | None,
) -> None:
    """Answer "Invalid cursor" and log no error for a tampered boundary.

    Args:
        rows: The created rows.
        caplog: Log capture fixture.
        field: Ordering field under test.
        value: Tampered ordering value.
        pk: Tampered pk component, or None for a legacy value-only cursor.
    """
    paginator = CursorGraphqlPagination(ordering=field, page_size=2)
    token = ENCODE(value, pk)
    with caplog.at_level(logging.DEBUG):
        for source in _sources():
            with pytest.raises(GraphQLError, match="^Invalid cursor$"):
                list(paginator.paginate_queryset(source, first=2, cursor=token))
            with pytest.raises(GraphQLError, match="^Invalid cursor$"):
                paginator.get_page_info(source, first=2, cursor=token)
    assert not [r for r in caplog.records if r.levelno >= logging.ERROR]


@pytest.mark.django_db
@pytest.mark.parametrize("token", ["!!!", "bm90LWEtY3Vyc29y"])
def test_malformed_cursor_is_invalid_cursor_on_both_paths(
    rows: list[ScalarKindsModel], token: str
) -> None:
    """Reject non-cursor tokens identically on both paths.

    Args:
        rows: The created rows.
        token: A token that is not a cursor.
    """
    paginator = CursorGraphqlPagination(ordering="decimal", page_size=2)
    for source in _sources():
        with pytest.raises(GraphQLError, match="^Invalid cursor$"):
            list(paginator.paginate_queryset(source, first=2, cursor=token))


@pytest.mark.django_db
@pytest.mark.parametrize(
    "field", ["decimal", "floating", "integer", "date", "datetime", "uuid_field"]
)
def test_valid_cursor_round_trips_identically(
    rows: list[ScalarKindsModel], field: str
) -> None:
    """Page through every row with a real cursor on both paths.

    Args:
        rows: The created rows.
        field: Ordering field under test.
    """
    paginator = CursorGraphqlPagination(ordering=field, page_size=2)
    seen = []
    for source in _sources():
        cursor = None
        ids = []
        while True:
            page = list(paginator.paginate_queryset(source, first=2, cursor=cursor))
            if not page:
                break
            ids += [r.pk for r in page]
            cursor = paginator.get_page_info(source, first=2, cursor=cursor)[
                "end_cursor"
            ]
        seen.append(ids)
    assert seen[0] == seen[1] == [r.pk for r in rows]
