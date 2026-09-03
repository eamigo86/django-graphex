"""Benchmark response-shape contract tests."""

from __future__ import annotations

import base64

import pytest

from benchmarks.contract import validate_response


def _relay_id(type_name: str, pk: int) -> str:
    raw = f"{type_name}:{pk}".encode()
    return base64.b64encode(raw).decode()


def _items(lib: str, values: list[dict]) -> object:
    if lib == "graphene":
        return {"edges": [{"node": value} for value in values]}
    if lib == "graphex":
        return {"results": values}
    return values


def _id(lib: str, type_name: str, pk: int) -> str:
    return _relay_id(f"{type_name}Type", pk) if lib == "graphene" else str(pk)


def _valid_nested(lib: str) -> dict:
    authors = []
    for author_index in range(20):
        posts = []
        for post_offset in range(10):
            post_index = author_index * 10 + post_offset
            comments = [
                {
                    "id": _id(lib, "Comment", post_index * 5 + offset + 1),
                    "text": f"Comment {offset} on post {post_index + 1}. ",
                }
                for offset in range(5)
            ]
            posts.append(
                {
                    "id": _id(lib, "Post", post_index + 1),
                    "title": f"Post {post_index}",
                    "comments": _items(lib, comments),
                }
            )
        authors.append(
            {
                "id": _id(lib, "Author", author_index + 1),
                "name": f"Author {author_index}",
                "posts": _items(lib, posts),
            }
        )
    return {"data": {"authors": _items(lib, authors)}}


@pytest.mark.parametrize("lib", ["graphex", "graphene", "strawberry", "ariadne"])
def test_nested_contract_checks_every_branch_and_exact_cardinality(lib: str) -> None:
    """Verify nested contract checks every branch and exact cardinality.

    Args:
        lib: The benchmark library adapter name under test.
    """
    response = _valid_nested(lib)
    validate_response(lib, "nested", response)

    authors = response["data"]["authors"]
    if lib == "graphene":
        authors["edges"][19]["node"]["posts"]["edges"][9]["node"]["comments"][
            "edges"
        ].pop()
    elif lib == "graphex":
        authors["results"][19]["posts"]["results"][9]["comments"]["results"].pop()
    else:
        authors[19]["posts"][9]["comments"].pop()

    with pytest.raises(AssertionError, match="expected 5 comments"):
        validate_response(lib, "nested", response)


def test_nested_contract_rejects_wrong_ids_and_content() -> None:
    """Verify nested contract rejects wrong ids and content.

    This protects the benchmark payload contract from false-positive fixtures.
    """
    response = _valid_nested("ariadne")
    response["data"]["authors"][7]["posts"][3]["id"] = "9999"
    with pytest.raises(AssertionError, match="post id"):
        validate_response("ariadne", "nested", response)

    response = _valid_nested("ariadne")
    response["data"]["authors"][7]["posts"][3]["comments"][2]["text"] = "wrong"
    with pytest.raises(AssertionError, match="comment content"):
        validate_response("ariadne", "nested", response)


def test_filtered_contract_rejects_non_matching_rows() -> None:
    """Verify filtered contract rejects non matching rows.

    This protects the benchmark payload contract from false-positive fixtures.
    """
    response = {
        "data": {
            "posts": [
                {"id": str(index + 1), "title": f"Post {index}"} for index in range(50)
            ]
        }
    }
    with pytest.raises(AssertionError, match="filtered post ids"):
        validate_response("ariadne", "filtered", response)


def test_flat_contract_rejects_partial_fixture() -> None:
    """Verify flat contract rejects partial fixtures.

    This protects the benchmark payload contract from false-positive fixtures.
    """
    response = {
        "data": {
            "posts": [
                {
                    "id": str(index + 1),
                    "title": f"Post {index}",
                    "status": "published",
                    "viewsCount": 1,
                }
                for index in range(49)
            ]
        }
    }
    with pytest.raises(AssertionError, match="expected 50 posts"):
        validate_response("strawberry", "flat_list", response)


def test_create_contract_uses_the_active_doubled_seed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Derive the expected mutation ID from the selected seed size.

    Args:
        monkeypatch: Pytest fixture used to isolate process state.
    """
    monkeypatch.setenv("BENCH_AUTHORS", "2000")
    response = {"data": {"createComment": {"id": "100001"}}}
    validate_response("strawberry", "create_comment", response)
