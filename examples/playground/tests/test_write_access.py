"""Which writes the playground leaves open and which it gates.

The README lists the open writes exactly: "postCreate", "postWithCommentsCreate"
(without a "comments" list), "createCategory", "documentCreate" and
"uploadDocument" accept an anonymous caller so a reader can compare them with
the gated ones. The destructive or modifying siblings, "postUpdate",
"postDelete" and "documentUpdate", live in the private mutation root and need a
logged-in user. These tests pin both lists so the README cannot drift.

Run from this directory:

    cd examples/playground
    DJANGO_SETTINGS_MODULE=config.settings python -m pytest -q --no-migrations
"""

from __future__ import annotations

import base64
import json
from typing import TYPE_CHECKING, Any

import pytest

if TYPE_CHECKING:
    from blog.models import Author
    from django.contrib.auth.models import AbstractBaseUser
    from django.test import Client

pytestmark = pytest.mark.django_db


def _graphql(client: Client, query: str) -> dict[str, Any]:
    """POST a document to the public endpoint and return the decoded body.

    Args:
        client: The Django test client issuing the request.
        query: The GraphQL document to execute.

    Returns:
        body: The decoded JSON response body.
    """
    response = client.post(
        "/graphql/", data=json.dumps({"query": query}), content_type="application/json"
    )
    return response.json()


def _denied(body: dict[str, Any]) -> bool:
    """Tell whether a response body carries the authentication refusal.

    Args:
        body: The decoded GraphQL response.

    Returns:
        denied: True when the first error says authentication is required.
    """
    return "Authentication required" in body["errors"][0]["message"]


@pytest.fixture
def post(author: Author) -> Any:
    """Create a published post for the gated writes to target.

    Args:
        author: The persisted author that owns the post.

    Returns:
        post: The saved "Post".
    """
    from blog.models import Post

    return Post.objects.create(
        title="Target", author=author, status=Post.Status.PUBLISHED
    )


def test_anonymous_post_update_is_refused(client: Client, post: Any) -> None:
    """Assert an anonymous "postUpdate" is refused and changes nothing.

    Args:
        client: The Django test client issuing the unauthenticated POST.
        post: The post the mutation targets.
    """
    body = _graphql(
        client,
        f'mutation {{ postUpdate(newPost: {{ id: {post.pk}, title: "Hacked" }}) '
        "{ ok } }",
    )
    assert _denied(body), body
    post.refresh_from_db()
    assert post.title == "Target"


def test_anonymous_post_delete_is_refused(client: Client, post: Any) -> None:
    """Assert an anonymous "postDelete" is refused and deletes nothing.

    Args:
        client: The Django test client issuing the unauthenticated POST.
        post: The post the mutation targets.
    """
    from blog.models import Post

    body = _graphql(client, f"mutation {{ postDelete(id: {post.pk}) {{ ok }} }}")
    assert _denied(body), body
    assert Post.objects.filter(pk=post.pk).exists()


def test_anonymous_document_update_is_refused(client: Client) -> None:
    """Assert an anonymous "documentUpdate" is refused and changes nothing.

    Args:
        client: The Django test client issuing the unauthenticated POST.
    """
    from blog.models import Document

    document = Document.objects.create(name="Original")
    body = _graphql(
        client,
        f"mutation {{ documentUpdate(newDocument: {{ id: {document.pk}, "
        'name: "Hacked" }) { ok } }',
    )
    assert _denied(body), body
    document.refresh_from_db()
    assert document.name == "Original"


def test_authenticated_caller_may_update_and_delete(
    client: Client, django_user_model: type[AbstractBaseUser], post: Any
) -> None:
    """Assert a logged-in caller still reaches the gated writes.

    Args:
        client: The Django test client used to log in and issue the requests.
        django_user_model: The active user model, used to create the caller.
        post: The post the mutations target.
    """
    from blog.models import Document, Post

    client.force_login(django_user_model.objects.create_user("editor", password="pw"))

    updated = _graphql(
        client,
        f'mutation {{ postUpdate(newPost: {{ id: {post.pk}, title: "Edited" }}) '
        "{ ok } }",
    )
    assert updated["data"]["postUpdate"]["ok"] is True, updated
    post.refresh_from_db()
    assert post.title == "Edited"

    document = Document.objects.create(name="Original")
    renamed = _graphql(
        client,
        f"mutation {{ documentUpdate(newDocument: {{ id: {document.pk}, "
        'name: "Renamed" }) { ok } }',
    )
    assert renamed["data"]["documentUpdate"]["ok"] is True, renamed

    deleted = _graphql(client, f"mutation {{ postDelete(id: {post.pk}) {{ ok }} }}")
    assert deleted["data"]["postDelete"]["ok"] is True, deleted
    assert not Post.objects.filter(pk=post.pk).exists()


def test_the_documented_open_writes_accept_an_anonymous_caller(
    client: Client, author: Author
) -> None:
    """Assert every write the README lists as open really is open.

    Args:
        client: The Django test client issuing the unauthenticated POSTs.
        author: The persisted author the created posts hang off.
    """
    created = _graphql(
        client,
        f'mutation {{ postCreate(newPost: {{ title: "Open", author: {author.pk} }}) '
        "{ ok } }",
    )
    assert created["data"]["postCreate"]["ok"] is True, created

    nested = _graphql(
        client,
        "mutation { postWithCommentsCreate(newPost: "
        f'{{ title: "Open nested", author: {author.pk} }}) {{ ok }} }}',
    )
    assert nested["data"]["postWithCommentsCreate"]["ok"] is True, nested

    category = _graphql(
        client,
        'mutation { createCategory(data: { name: "Open" }) { ok error } }',
    )
    assert category["data"]["createCategory"]["ok"] is True, category

    document = _graphql(
        client,
        'mutation { documentCreate(newDocument: { name: "Open" }) { ok } }',
    )
    assert document["data"]["documentCreate"]["ok"] is True, document

    data = base64.b64encode(b"hello").decode()
    upload = _graphql(
        client,
        'mutation { uploadDocument(name: "Open", file: { filename: "a.txt", '
        f'data: "{data}", contentType: "text/plain" }}) {{ ok error }} }}',
    )
    assert upload["data"]["uploadDocument"]["ok"] is True, upload
