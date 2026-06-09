# -*- coding: utf-8 -*-
"""CRUD edge branches of ``DjangoModelType`` (types.py).

Covers the multipart file-merge in create/update, the delete / update
not-found paths, and the update save-failure path.
"""

from types import SimpleNamespace

from django.test import TestCase

from django_graphex import DjangoModelType
from tests.models import Author


class AuthorModelType(DjangoModelType):
    class Meta:
        model = Author


def _info(content_type="", files=None):
    return SimpleNamespace(
        context=SimpleNamespace(META={"CONTENT_TYPE": content_type}, FILES=files or {})
    )


def _kwargs(data):
    return {AuthorModelType._meta.input_field_name: data}


class CreateUpdateMultipartTest(TestCase):
    def test_create_merges_uploaded_files(self):
        info = _info("multipart/form-data; boundary=x", {"name": "FromFile"})
        result = AuthorModelType.create(None, info, **_kwargs({}))
        assert result.ok, getattr(result, "errors", None)
        assert Author.objects.get().name == "FromFile"

    def test_update_merges_uploaded_files(self):
        author = Author.objects.create(name="orig")
        info = _info("multipart/form-data; boundary=x", {"name": "Patched"})
        result = AuthorModelType.update(None, info, **_kwargs({"id": author.pk}))
        assert result.ok, getattr(result, "errors", None)
        author.refresh_from_db()
        assert author.name == "Patched"


class NotFoundTest(TestCase):
    def test_delete_missing_returns_errors(self):
        result = AuthorModelType.delete(None, _info(), id=99999)
        assert not result.ok
        assert result.errors

    def test_update_missing_returns_errors(self):
        result = AuthorModelType.update(
            None, _info(), **_kwargs({"id": 99999, "name": "x"})
        )
        assert not result.ok
        assert result.errors


class SaveFailureTest(TestCase):
    def test_update_save_failure_returns_errors(self):
        author = Author.objects.create(name="orig")
        # An over-long name fails validation -> not ok -> errors.
        result = AuthorModelType.update(
            None, _info(), **_kwargs({"id": author.pk, "name": "x" * 500})
        )
        assert not result.ok
        assert result.errors

    def test_create_save_failure_returns_errors(self):
        result = AuthorModelType.create(None, _info(), **_kwargs({"name": "x" * 500}))
        assert not result.ok
        assert result.errors
