# -*- coding: utf-8 -*-
"""CRUD edge branches of "DjangoModelType" (types.py).

Covers the multipart file-merge in create/update, the delete / update
not-found paths, and the update save-failure path.
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

from django.test import TestCase

from django_graphex.types import DjangoModelType
from tests.models import Author


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


class CreateUpdateMultipartTest(TestCase):
    """Tests for the multipart file-merge branch of create/update.

    Verifies that uploaded files are merged into the input data before the
    serializer validates and saves the object.
    """

    def test_create_merges_uploaded_files(self) -> None:
        """Assert "create" merges uploaded files into a multipart request's data.

        If this fails, a file uploaded via multipart/form-data would not
        reach the saved object's fields on create.
        """
        info = _info("multipart/form-data; boundary=x", {"name": "FromFile"})
        result = AuthorModelType.create(None, info, **_kwargs({}))
        assert result.ok, getattr(result, "errors", None)
        assert Author.objects.get().name == "FromFile"

    def test_update_merges_uploaded_files(self) -> None:
        """Assert "update" merges uploaded files into a multipart request's data.

        If this fails, a file uploaded via multipart/form-data would not
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
