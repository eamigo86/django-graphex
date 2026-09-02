"""Shared semantic contract for every benchmark library adapter."""

from __future__ import annotations

import base64

LIBRARIES = {"graphex", "graphene", "strawberry", "ariadne"}
POSTS_PER_AUTHOR = 10
COMMENTS_PER_POST = 5
NESTED_AUTHORS = 20
FLAT_POSTS = 50
TOTAL_POSTS = 10_000
SINGLE_POST_ID = 5_000


def _pk(value: object) -> int:
    """Normalize raw and Relay global IDs to their deterministic database PK."""
    text = str(value)
    if text.isdigit():
        return int(text)
    try:
        decoded = base64.b64decode(text, validate=True).decode()
        return int(decoded.rsplit(":", 1)[1])
    except (ValueError, UnicodeDecodeError, IndexError) as exc:
        raise AssertionError(f"invalid GraphQL id: {value!r}") from exc


def _items(library: str, value: object) -> list[dict]:
    if library == "graphene":
        return [edge["node"] for edge in value["edges"]]  # type: ignore[index]
    if library == "graphex":
        return value["results"]  # type: ignore[index]
    return value  # type: ignore[return-value]


def _assert_ids(label: str, items: list[dict], expected: list[int]) -> None:
    actual = [_pk(item["id"]) for item in items]
    assert actual == expected, f"unexpected {label} ids: {actual!r}"


def _validate_flat(library: str, data: dict) -> None:
    posts = _items(library, data["posts"])
    assert len(posts) == FLAT_POSTS, f"expected 50 posts, got {len(posts)}"
    _assert_ids("flat post", posts, list(range(1, FLAT_POSTS + 1)))
    for index, post in enumerate(posts):
        assert set(post) == {"id", "title", "status", "viewsCount"}, post
        assert post["title"] == f"Post {index}", f"unexpected flat post title: {post!r}"
        assert str(post["status"]).lower() in {"draft", "published"}
        assert isinstance(post["viewsCount"], int)


def _validate_nested(library: str, data: dict) -> None:
    authors = _items(library, data["authors"])
    assert len(authors) == NESTED_AUTHORS, f"expected 20 authors, got {len(authors)}"
    _assert_ids("author", authors, list(range(1, NESTED_AUTHORS + 1)))
    for author_index, author in enumerate(authors):
        assert author["name"] == f"Author {author_index}"
        posts = _items(library, author["posts"])
        assert len(posts) == POSTS_PER_AUTHOR, (
            f"expected 10 posts for author {author_index}, got {len(posts)}"
        )
        first_post = author_index * POSTS_PER_AUTHOR + 1
        _assert_ids("post", posts, list(range(first_post, first_post + 10)))
        for post_offset, post in enumerate(posts):
            post_index = author_index * POSTS_PER_AUTHOR + post_offset
            assert post["title"] == f"Post {post_index}"
            comments = _items(library, post["comments"])
            assert len(comments) == COMMENTS_PER_POST, (
                f"expected 5 comments for post {post_index + 1}, got {len(comments)}"
            )
            first_comment = post_index * COMMENTS_PER_POST + 1
            _assert_ids(
                "comment",
                comments,
                list(range(first_comment, first_comment + COMMENTS_PER_POST)),
            )
            for offset, comment in enumerate(comments):
                expected = f"Comment {offset} on post {post_index + 1}. "
                assert comment["text"] in {expected * count for count in range(1, 4)}, (
                    f"unexpected comment content: {comment!r}"
                )


def _validate_single(data: dict) -> None:
    post = data["post"]
    assert post is not None, "post not found"
    assert _pk(post["id"]) == SINGLE_POST_ID, f"unexpected single post id: {post!r}"
    assert post["title"] == "Post 4999"
    assert post["author"]["name"] == "Author 499"


def _validate_filtered(library: str, data: dict) -> None:
    posts = _items(library, data["posts"])
    matches = [index for index in range(TOTAL_POSTS) if "post 42" in f"post {index}"]
    expected = matches[:FLAT_POSTS]
    assert len(posts) == FLAT_POSTS, f"expected 50 filtered posts, got {len(posts)}"
    _assert_ids("filtered post", posts, [index + 1 for index in expected])
    assert [post["title"] for post in posts] == [f"Post {index}" for index in expected]


def _validate_create(data: dict, library: str) -> None:
    payload = data["commentCreate"] if library == "graphex" else data["createComment"]
    if library != "strawberry":
        assert payload["ok"], payload
        payload = payload["comment"]
    assert _pk(payload["id"]) == TOTAL_POSTS * COMMENTS_PER_POST + 1


def validate_response(library: str, operation: str, response: dict) -> None:
    """Validate the complete deterministic result, not merely its first branch."""
    assert library in LIBRARIES, f"unsupported benchmark library: {library}"
    assert "errors" not in response, response.get("errors")
    data = response["data"]
    validators = {
        "flat_list": lambda: _validate_flat(library, data),
        "nested": lambda: _validate_nested(library, data),
        "single": lambda: _validate_single(data),
        "filtered": lambda: _validate_filtered(library, data),
        "create_comment": lambda: _validate_create(data, library),
    }
    assert operation in validators, f"unsupported benchmark operation: {operation}"
    validators[operation]()
