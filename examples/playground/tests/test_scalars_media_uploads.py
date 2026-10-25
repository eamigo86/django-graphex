"""Small example behaviours: BigInt strings, served media, safe upload errors.

- "Post.view_count" is a "BigIntegerField": the 4.1 library serializes it as a
  "BigInt" string so a value past 2**53 survives a JSON round trip.
- "MEDIA_URL" is configured, so "config/urls.py" serves uploaded files while
  "DEBUG" is on (the same development-only contract as the static files).
- "uploadDocument" is open to anonymous callers, so an unexpected failure
  answers with a generic message and logs the detail instead of echoing it.

Run from this directory:

    cd examples/playground
    DJANGO_SETTINGS_MODULE=config.settings python -m pytest -q --no-migrations
"""

from __future__ import annotations

import base64
import importlib
import json
import logging
from typing import TYPE_CHECKING, Any

import pytest
from django.test import override_settings
from django.urls import clear_url_caches

if TYPE_CHECKING:
    from blog.models import Author
    from django.test import Client

pytestmark = pytest.mark.django_db

_BIG = 2**53 + 1


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


def test_a_big_integer_is_read_and_written_as_a_string(
    client: Client, author: Author
) -> None:
    """Assert "viewCount" survives past 2**53 as a "BigInt" string both ways.

    Args:
        client: The Django test client issuing the requests.
        author: The persisted author the created post hangs off.
    """
    created = _graphql(
        client,
        f'mutation {{ postCreate(newPost: {{ title: "Big", author: {author.pk}, '
        f'status: PUBLISHED, viewCount: "{_BIG}" }}) {{ ok post {{ viewCount }} }} }}',
    )
    assert created["data"]["postCreate"]["post"]["viewCount"] == str(_BIG), created

    read = _graphql(client, "{ posts { results { viewCount } } }")
    assert read["data"]["posts"]["results"][0]["viewCount"] == str(_BIG), read


def test_uploaded_media_is_served_while_debug_is_on(tmp_path: Any) -> None:
    """Assert "MEDIA_URL" resolves to a file under "MEDIA_ROOT" in development.

    The URLconf decides at import time, so it is rebuilt under "DEBUG=True"
    (pytest forces it off) and restored afterwards.

    Args:
        tmp_path: A temporary directory standing in for "MEDIA_ROOT".
    """
    import config.urls
    from django.test import Client

    (tmp_path / "hello.txt").write_text("hello media")
    try:
        with override_settings(DEBUG=True, MEDIA_ROOT=tmp_path):
            importlib.reload(config.urls)
            clear_url_caches()
            response = Client().get("/media/hello.txt")
            assert response.status_code == 200
            assert b"".join(response.streaming_content) == b"hello media"
            # Uploads are never rendered: a download, unsniffed and sandboxed.
            assert response["Content-Disposition"] == "attachment"
            assert response["X-Content-Type-Options"] == "nosniff"
            assert response["Content-Security-Policy"] == "sandbox"
    finally:
        importlib.reload(config.urls)
        clear_url_caches()

    # With DEBUG off (the shipped test default) nothing is mounted.
    assert Client().get("/media/hello.txt").status_code == 404


def _boom(*args: Any, **kwargs: Any) -> None:
    """Fail like a storage backend whose error text carries a server path.

    Args:
        *args: Ignored positional arguments of the replaced storage method.
        **kwargs: Ignored keyword arguments of the replaced storage method.

    Raises:
        OSError: Always, with a message that must never reach the caller.
    """
    raise OSError("/srv/secret/path: permission denied")


def test_an_unexpected_upload_failure_is_generic_and_logged(
    client: Client,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Assert a storage failure does not leak its text to an anonymous caller.

    Args:
        client: The Django test client issuing the unauthenticated request.
        monkeypatch: Used to make the storage backend fail with a revealing text.
        caplog: Captures the log record that keeps the detail for the operator.
    """
    from django.core.files.storage import FileSystemStorage

    monkeypatch.setattr(FileSystemStorage, "_save", _boom)
    data = base64.b64encode(b"hello").decode()
    query = (
        'mutation { uploadDocument(name: "x", file: { filename: "a.txt", '
        f'data: "{data}", contentType: "text/plain" }}) {{ ok error }} }}'
    )

    with caplog.at_level(logging.ERROR):
        payload = _graphql(client, query)["data"]["uploadDocument"]

    assert payload == {"ok": False, "error": "Upload failed."}
    assert "/srv/secret/path" in caplog.text


def test_a_client_fault_keeps_its_actionable_message(client: Client) -> None:
    """Assert the library's own validation messages still reach the caller.

    Args:
        client: The Django test client issuing the unauthenticated request.
    """
    query = (
        'mutation { uploadDocument(name: "x", file: { filename: "a.txt", '
        'data: "***not base64***", contentType: "text/plain" }) { ok error } }'
    )

    payload = _graphql(client, query)["data"]["uploadDocument"]

    assert payload["ok"] is False
    assert payload["error"] != "Upload failed."
    assert "base64" in payload["error"].lower()


def test_an_active_content_upload_is_refused_on_the_base64_path(
    client: Client, tmp_path: Any
) -> None:
    """Assert an HTML upload answers "ok: false" and stores nothing.

    Args:
        client: The Django test client issuing the unauthenticated request.
        tmp_path: The temporary "MEDIA_ROOT" that must stay empty.
    """
    data = base64.b64encode(b"<script>alert(1)</script>").decode()
    query = (
        'mutation { uploadDocument(name: "x", file: { filename: "a.html", '
        f'data: "{data}", contentType: "text/html" }}) {{ ok error }} }}'
    )

    payload = _graphql(client, query)["data"]["uploadDocument"]

    assert payload["ok"] is False
    assert "extension" in payload["error"]
    assert not list(tmp_path.rglob("*.html"))


def test_an_active_content_upload_is_refused_on_the_multipart_path(
    client: Client, tmp_path: Any
) -> None:
    """Assert a multipart HTML part is refused by the same allow-list.

    Args:
        client: The Django test client issuing the unauthenticated request.
        tmp_path: The temporary "MEDIA_ROOT" that must stay empty.
    """
    from django.core.files.uploadedfile import SimpleUploadedFile

    response = client.post(
        "/graphql/",
        data={
            "query": 'mutation { documentCreate(newDocument: { name: "x" }) '
            "{ ok errors { field messages } } }",
            "attachedFile": SimpleUploadedFile("a.html", b"<script></script>"),
        },
        HTTP_X_REQUESTED_WITH="XMLHttpRequest",
    )

    payload = response.json()["data"]["documentCreate"]
    assert payload["ok"] is False, payload
    assert not list(tmp_path.rglob("*.html"))
