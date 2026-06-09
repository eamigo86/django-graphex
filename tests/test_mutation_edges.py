# -*- coding: utf-8 -*-
"""Remaining branch coverage for ``mutation.py``.

Covers: the deprecated ``Input`` class (vs ``Arguments``), the multipart
file-merge in ``create`` / ``update``, the update-save failure path, and the
``MutationFields`` triple builder.
"""

import warnings
from types import SimpleNamespace

import pytest
from django.test import TestCase

from django_graphex import DjangoModelMutation

from .models import Author


class AuthorMutation(DjangoModelMutation):
    class Meta:
        model = Author


def _multipart_info(files):
    return SimpleNamespace(
        context=SimpleNamespace(
            META={"CONTENT_TYPE": "multipart/form-data; boundary=x"},
            FILES=files,
        )
    )


class MutationFieldsTest(TestCase):
    def test_mutation_fields_returns_three_fields(self):
        create, delete, update = AuthorMutation.MutationFields()
        # Each is a graphene Field bound to the matching resolver.
        assert create.resolver.__name__ == "create"
        assert delete.resolver.__name__ == "delete"
        assert update.resolver.__name__ == "update"


class MultipartTest(TestCase):
    def test_create_merges_uploaded_files(self):
        info = _multipart_info({"name": "FromFile"})
        data = {}
        result = AuthorMutation.create(None, info, **{"new_author": data})
        # The FILES value was merged into data before saving.
        assert result.ok, getattr(result, "errors", None)
        assert Author.objects.get().name == "FromFile"

    def test_update_merges_uploaded_files(self):
        author = Author.objects.create(name="orig")
        info = _multipart_info({"name": "Patched"})
        data = {"id": author.pk}
        result = AuthorMutation.update(None, info, **{"new_author": data})
        assert result.ok, getattr(result, "errors", None)
        author.refresh_from_db()
        assert author.name == "Patched"

    def test_update_save_failure_returns_errors(self):
        author = Author.objects.create(name="orig")
        info = SimpleNamespace(context=SimpleNamespace(META={}, FILES={}))
        # An over-long name fails model validation -> not ok -> errors.
        data = {"id": author.pk, "name": "x" * 500}
        result = AuthorMutation.update(None, info, **{"new_author": data})
        assert not result.ok
        assert result.errors


class InputDeprecationTest(TestCase):
    def test_input_class_emits_deprecation_warning(self):
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")

            class _LegacyMutation(DjangoModelMutation):
                class Input:
                    extra = pytest.importorskip("graphene").String()

                class Meta:
                    model = Author

        messages = " ".join(str(w.message) for w in caught)
        assert "Arguments instead of" in messages
        # The legacy Input args were still collected onto every operation.
        assert "extra" in _LegacyMutation._meta.arguments["create"]
