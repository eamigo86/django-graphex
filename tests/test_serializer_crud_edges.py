# -*- coding: utf-8 -*-
"""CRUD edge branches of "DjangoModelType" (types.py).

Covers the multipart file-merge in create/update, the delete / update
not-found paths, and the update save-failure path.
"""

from __future__ import annotations

import tempfile
from types import SimpleNamespace
from typing import Any

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings

from django_graphex.types import DjangoModelType
from tests.models import Author, BinaryDoc


class AuthorModelType(DjangoModelType):
    """Model type under test.

    Backed by the "Author" model with no filtering or pagination options.
    """

    class Meta:
        """Configuration for "AuthorModelType".

        Declares the backing model with no further options.
        """

        model = Author


def _info(
    content_type: str = "", files: dict[str, Any] | None = None
) -> SimpleNamespace:
    """Build a minimal resolver-info stand-in with a multipart-style context.

    Args:
        content_type: The value to expose as "context.META['CONTENT_TYPE']".
        files: The mapping to expose as "context.FILES"; defaults to empty.

    Returns:
        info: A namespace shaped like the subset of GraphQL resolver info
            that the multipart file-merge code reads.
    """
    return SimpleNamespace(
        context=SimpleNamespace(META={"CONTENT_TYPE": content_type}, FILES=files or {})
    )


def _kwargs(data: dict[str, Any]) -> dict[str, Any]:
    """Wrap input data under the model type's configured input field name.

    Args:
        data: The input payload to nest under the input field name.

    Returns:
        kwargs: A single-key mapping suitable for passing to "create"/"update"
            as keyword arguments.
    """
    return {AuthorModelType._meta.input_field_name: data}


def _error_pairs(result: Any) -> list[tuple[Any, Any]]:
    """Flatten a mutation result's errors into readable (field, messages) pairs.

    Args:
        result: The mutation result whose "errors" list is unpacked.

    Returns:
        pairs: One "(field, messages)" tuple per reported error.
    """
    return [
        (getattr(err, "field", None), getattr(err, "messages", None))
        for err in (getattr(result, "errors", None) or [])
    ]


class CreateUpdateMultipartTest(TestCase):
    """Tests for the multipart file-merge branch of create/update.

    Covers the MERGE ONLY: that "info.context.FILES" entries are folded into
    the input payload keyed by field name.  The values used here are plain
    strings landing on a "CharField", so nothing about actual file storage is
    exercised — that is covered by the upload tests at the bottom of this
    module.
    """

    def test_create_merges_uploaded_files(self) -> None:
        """Assert "create" merges "context.FILES" entries into a multipart payload.

        If this fails, a value supplied via multipart/form-data would not
        reach the saved object's fields on create.
        """
        info = _info("multipart/form-data; boundary=x", {"name": "FromFile"})
        result = AuthorModelType.create(None, info, **_kwargs({}))
        assert result.ok, getattr(result, "errors", None)
        assert Author.objects.get().name == "FromFile"

    def test_update_merges_uploaded_files(self) -> None:
        """Assert "update" merges "context.FILES" entries into a multipart payload.

        If this fails, a value supplied via multipart/form-data would not
        reach the saved object's fields on update.
        """
        author = Author.objects.create(name="orig")
        info = _info("multipart/form-data; boundary=x", {"name": "Patched"})
        result = AuthorModelType.update(None, info, **_kwargs({"id": author.pk}))
        assert result.ok, getattr(result, "errors", None)
        author.refresh_from_db()
        assert author.name == "Patched"


class NotFoundTest(TestCase):
    """Tests for delete/update against a primary key that does not exist.

    Verifies both mutations return a structured not-ok result with errors
    instead of raising when the target row is missing.
    """

    def test_delete_missing_returns_errors(self) -> None:
        """Assert deleting a nonexistent id returns a not-ok result with errors.

        If this fails, deleting a missing row would either raise instead of
        returning a structured error, or silently report success.
        """
        result = AuthorModelType.delete(None, _info(), id=99999)
        assert not result.ok
        assert result.errors

    def test_update_missing_returns_errors(self) -> None:
        """Assert updating a nonexistent id returns a not-ok result with errors.

        If this fails, updating a missing row would either raise instead of
        returning a structured error, or silently report success.
        """
        result = AuthorModelType.update(
            None, _info(), **_kwargs({"id": 99999, "name": "x"})
        )
        assert not result.ok
        assert result.errors


class SaveFailureTest(TestCase):
    """Tests for the save-failure path when model validation rejects data.

    Verifies both create and update surface validation failures as
    structured errors rather than raising.
    """

    def test_update_save_failure_returns_errors(self) -> None:
        """Assert a validation failure on update returns errors, not an exception.

        If this fails, an invalid update payload (for example, an over-long
        field) would raise instead of surfacing as a structured error result.
        """
        author = Author.objects.create(name="orig")
        # An over-long name fails validation -> not ok -> errors.
        result = AuthorModelType.update(
            None, _info(), **_kwargs({"id": author.pk, "name": "x" * 500})
        )
        assert not result.ok
        assert result.errors

    def test_create_save_failure_returns_errors(self) -> None:
        """Assert a validation failure on create returns errors, not an exception.

        If this fails, an invalid create payload (for example, an over-long
        field) would raise instead of surfacing as a structured error result.
        """
        result = AuthorModelType.create(None, _info(), **_kwargs({"name": "x" * 500}))
        assert not result.ok
        assert result.errors


# ---------------------------------------------------------------------------
# Real multipart upload: an uploaded FILE against a real FileField
#
# The two merge tests above hand a plain "str" to a "CharField", so they only
# pin the "dict.update" that folds "info.context.FILES" into the payload — they
# stay green while the upload path itself is broken end to end.  The tests below
# post a real "UploadedFile" at a real "FileField" and assert the bytes land in
# storage.
# ---------------------------------------------------------------------------


class BinaryDocModelType(DjangoModelType):
    """Model type over the file-carrying model.

    Backed by "BinaryDoc", whose "attachment" column is a real "FileField", so
    the multipart branch can be exercised with a real upload.
    """

    class Meta:
        """Configuration for "BinaryDocModelType".

        Declares the backing model with no further options.
        """

        model = BinaryDoc


def _upload() -> SimpleUploadedFile:
    """Build a small in-memory upload.

    Returns:
        upload: A text upload named "hello.txt" carrying "hello-bytes".
    """
    return SimpleUploadedFile("hello.txt", b"hello-bytes", content_type="text/plain")


@pytest.mark.xfail(
    strict=True,
    reason=(
        "KNOWN DEFECT: the pydantic schema types a FileField as str "
        "(core/fields.py _STR), so the UploadedFile merged from "
        "info.context.FILES is rejected with 'Input should be a valid string' "
        "and no multipart upload can ever be saved."
    ),
)
@pytest.mark.django_db
def test_create_saves_a_real_uploaded_file_to_a_file_field() -> None:
    """Assert "create" stores an uploaded file's bytes on the model's FileField.

    Marked strict-xfail while the defect stands: the day the write path accepts
    an "UploadedFile" this test starts passing and strict mode turns that
    unexpected pass into a failure, so the guard cannot rot.
    """
    info = _info("multipart/form-data; boundary=x", {"attachment": _upload()})
    with tempfile.TemporaryDirectory() as media, override_settings(MEDIA_ROOT=media):
        result = BinaryDocModelType.create(
            None,
            info,
            **{BinaryDocModelType._meta.input_field_name: {"label": "L"}},
        )
        assert result.ok, _error_pairs(result)
        doc = BinaryDoc.objects.get()
        assert doc.attachment, "The uploaded file was not attached to the row"
        with doc.attachment.open("rb") as stored:
            assert stored.read() == b"hello-bytes", (
                "The stored file does not carry the uploaded bytes"
            )


@pytest.mark.xfail(
    strict=True,
    reason=(
        "KNOWN DEFECT: the pydantic schema types a FileField as str "
        "(core/fields.py _STR), so the UploadedFile merged from "
        "info.context.FILES is rejected with 'Input should be a valid string' "
        "and no multipart upload can ever be saved."
    ),
)
@pytest.mark.django_db
def test_update_saves_a_real_uploaded_file_to_a_file_field() -> None:
    """Assert "update" stores an uploaded file's bytes on the model's FileField.

    Marked strict-xfail while the defect stands: the day the write path accepts
    an "UploadedFile" this test starts passing and strict mode turns that
    unexpected pass into a failure, so the guard cannot rot.
    """
    doc = BinaryDoc.objects.create(label="orig")
    info = _info("multipart/form-data; boundary=x", {"attachment": _upload()})
    with tempfile.TemporaryDirectory() as media, override_settings(MEDIA_ROOT=media):
        result = BinaryDocModelType.update(
            None,
            info,
            **{BinaryDocModelType._meta.input_field_name: {"id": doc.pk}},
        )
        assert result.ok, _error_pairs(result)
        doc.refresh_from_db()
        assert doc.attachment, "The uploaded file was not attached to the row"
        with doc.attachment.open("rb") as stored:
            assert stored.read() == b"hello-bytes", (
                "The stored file does not carry the uploaded bytes"
            )
