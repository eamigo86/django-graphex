"""The multipart upload demo, driven the way a client actually drives it.

"blog/schema.py" mounts "DocumentMutation" ("documentCreate" /
"documentUpdate") over "Document.attached_file". There is nothing to configure:
a part named after a "FileField" the mutation input EXPOSES is merged into the
payload and saved. What that sentence hides is four separate contracts, and
each one is a way for the demo to rot silently:

1. The part name may be spelled EITHER way — "attachedFile", the only spelling
   the SDL publishes, or "attached_file", the model attribute. Both resolve off
   the same compiled input field. A one-word column would spell the two
   identically, which is why the demo column carries two words.
2. A part matching no exposed input field is IGNORED. The mutation still
   answers "ok: true" and saves nothing, so a misspelled part looks exactly
   like success — the failure mode a reader has to be shown, not told about.
3. The POST needs "X-Requested-With". "multipart/form-data" is a CORS-simple
   content type, so "REQUIRE_CSRF_HEADER" (on by default) refuses it with HTTP
   403 before the body is read.
4. The document travels in a "query" part, not in a graphql-multipart-request
   "operations" / "map" envelope, which this library does not implement.

Every test here writes into a tmp "MEDIA_ROOT" so the run leaves no files in
the checkout.

Run them from this directory:

    cd examples/playground
    DJANGO_SETTINGS_MODULE=config.settings python -m pytest -q --no-migrations
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile

if TYPE_CHECKING:
    from pathlib import Path

    from django.test import Client

#: The README's own create document, selecting the stored name back so a saved
#: file can be told apart from a dropped one without touching the filesystem.
_CREATE = """
    mutation {
      documentCreate(newDocument: { name: "Notes" }) {
        ok
        errors { field messages }
        document { id name attachedFile }
      }
    }
"""


@pytest.fixture(autouse=True)
def _media_in_tmp(settings: Any, tmp_path: Path) -> None:
    """Point "MEDIA_ROOT" at a temporary directory for every test here.

    Uploading through the real settings would write into the checkout's own
    "media/documents/", which a test has no business doing.

    Args:
        settings: The pytest-django settings fixture, reverted after the test.
        tmp_path: The per-test temporary directory to store uploads in.
    """
    settings.MEDIA_ROOT = tmp_path


def _upload(client: Client, part_name: str, **extra: Any) -> dict[str, Any]:
    """POST the create document as multipart with one file part.

    Args:
        client: The Django test client issuing the multipart POST.
        part_name: The name to give the file part.
        **extra: Extra keyword arguments forwarded to "client.post".

    Returns:
        payload: The "documentCreate" payload from the decoded response.
    """
    response = client.post(
        "/graphql/",
        data={
            "query": _CREATE,
            part_name: SimpleUploadedFile(
                "notes.txt", b"hello", content_type="text/plain"
            ),
        },
        headers={"x-requested-with": "XMLHttpRequest"},
        **extra,
    )
    assert response.status_code == 200, response.content
    body = response.json()
    assert not body.get("errors"), body
    return body["data"]["documentCreate"]


@pytest.mark.django_db
def test_a_part_named_the_way_the_sdl_spells_it_is_saved(client: Client) -> None:
    """Assert the camelCase alias lands on the column.

    "attachedFile" is the only spelling a client can discover from the schema,
    so it is the one that has to work; it was silently dropped before 2.2.0.

    Args:
        client: The Django test client issuing the multipart POST.
    """
    from blog.models import Document

    payload = _upload(client, "attachedFile")

    assert payload["ok"] is True
    assert payload["document"]["attachedFile"].endswith(".txt")
    assert Document.objects.get().attached_file.read() == b"hello"


@pytest.mark.django_db
def test_a_part_named_after_the_model_attribute_is_saved_too(client: Client) -> None:
    """Assert the snake_case model attribute lands on the same column.

    Both spellings are derived from one compiled input field, so neither can
    name a target the other does not.

    Args:
        client: The Django test client issuing the multipart POST.
    """
    from blog.models import Document

    payload = _upload(client, "attached_file")

    assert payload["ok"] is True
    assert Document.objects.get().attached_file.read() == b"hello"


@pytest.mark.django_db
def test_a_misspelled_part_is_ignored_and_still_answers_ok(client: Client) -> None:
    """Assert an unmatched part saves nothing while the mutation succeeds.

    This is the demo's sharpest lesson and its least visible one: the row is
    created, "ok" is true, and the column is empty. A reader who does not know
    that reads a typo as a working upload.

    Args:
        client: The Django test client issuing the multipart POST.
    """
    from blog.models import Document

    payload = _upload(client, "attachedFyle")

    assert payload["ok"] is True
    assert payload["document"]["attachedFile"] == ""
    assert not Document.objects.get().attached_file


@pytest.mark.django_db
def test_the_multipart_post_is_refused_without_the_csrf_header(client: Client) -> None:
    """Assert the shipped-on header guard covers the upload endpoint.

    "multipart/form-data" is CORS-simple, so exempting it would leave the
    mutations that WRITE FILES as the only unprotected surface. The refusal
    lands before the body is read, so the upload never streams.

    Args:
        client: The Django test client issuing the multipart POST.
    """
    from blog.models import Document

    response = client.post(
        "/graphql/",
        data={
            "query": _CREATE,
            "attachedFile": SimpleUploadedFile(
                "notes.txt", b"hello", content_type="text/plain"
            ),
        },
    )

    assert response.status_code == 403
    assert "X-Requested-With" in response.content.decode()
    assert Document.objects.count() == 0
