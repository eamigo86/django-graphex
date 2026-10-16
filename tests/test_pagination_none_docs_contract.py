"""Executable documentation contract for explicit-None pagination fallbacks."""

from pathlib import Path

from django_graphex.paginations.pagination import (
    CursorGraphqlPagination,
    LimitOffsetGraphqlPagination,
    PageGraphqlPagination,
)


def test_all_none_table_names_each_paginator_outcome() -> None:
    """Keep the all-None documentation specific to each paginator.

    A generic all-results row hides Page's null result and Cursor's final
    20-row fallback even though both are intentional legacy behavior.
    """
    guide = (
        Path(__file__).resolve().parents[1] / "docs/api/paginations.md"
    ).read_text()
    heading = "#### When every size source is None"
    assert heading in guide
    section = guide.split(heading, 1)[1].split("Clamping is **silent**", 1)[0]
    rows = [line for line in section.splitlines() if line.startswith("|")]
    cells = [
        tuple(part.strip() for part in line.strip("|").split("|")) for line in rows
    ]
    outcomes = {row[0]: row[-1] for row in cells if len(row) == 5}
    assert "all" in outcomes["LimitOffset"].lower()
    assert "null" in outcomes["Page"].lower()
    assert "20" in outcomes["Cursor"]
    for label in ("LimitOffset", "Page", "Cursor"):
        row = next(row for row in cells if row[0] == label)
        assert row[1:4] == ("`None`", "`None`", "omitted")
    assert "| – | – | – | **all**" not in guide


def test_all_none_and_bounded_controls_match_existing_paginators() -> None:
    """Keep null, default, requested-size, and maximum behavior unchanged.

    Client-controlled Page sizing is enabled explicitly; without that option,
    a page-size argument is not available to a GraphQL query.
    """
    rows = list(range(105))
    assert (
        LimitOffsetGraphqlPagination(
            default_limit=None, max_limit=None
        ).paginate_queryset(rows)
        == rows
    )
    assert (
        PageGraphqlPagination(page_size=None, max_page_size=None).paginate_queryset(
            rows, page=1
        )
        is None
    )
    assert (
        CursorGraphqlPagination(page_size=None, max_page_size=None)._page_size() == 20
    )

    assert len(LimitOffsetGraphqlPagination().paginate_queryset(rows)) == 100
    assert len(PageGraphqlPagination().paginate_queryset(rows, page=1)) == 100
    assert CursorGraphqlPagination()._page_size() == 100
    assert (
        len(
            LimitOffsetGraphqlPagination(
                default_limit=None, max_limit=5
            ).paginate_queryset(rows)
        )
        == 5
    )
    assert (
        len(
            LimitOffsetGraphqlPagination(
                default_limit=25, max_limit=100
            ).paginate_queryset(rows, limit=500)
        )
        == 100
    )
    page = PageGraphqlPagination(
        page_size=None, page_size_query_param="pageSize", max_page_size=5
    )
    assert "pageSize" in page.to_graphql_fields()
    assert len(page.paginate_queryset(rows, page=1, pageSize=100)) == 5
