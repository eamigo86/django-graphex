# -*- coding: utf-8 -*-
"""Remaining branch coverage for "mutation.py".

Covers: the deprecated "Input" class (vs "Arguments"), the multipart
file-merge in "create" / "update", the update-save failure path, and the
"MutationFields" triple builder.
"""

from __future__ import annotations

import warnings
from types import SimpleNamespace
from typing import Any

from django.test import TestCase

from django_graphex.mutation import DjangoModelMutation

from .models import Author


class AuthorMutation(DjangoModelMutation):
    """Minimal model mutation used to exercise mutation.py branch coverage.

    Shared by the multipart file-merge and mutation-fields tests below.
    """

    class Meta:
        """Bind the mutation to the "Author" model.

        No extra options are needed for these branch-coverage tests.
        """

        model = Author


def _multipart_info(files: dict[str, Any]) -> SimpleNamespace:
    """Build a fake GraphQL "info" simulating a multipart file upload request.

    Args:
        files: The uploaded-file mapping to expose as "context.FILES".

    Returns:
        SimpleNamespace: An object shaped like a GraphQL resolve info, with a
        "context" carrying a multipart "CONTENT_TYPE" header and "FILES".
    """
    return SimpleNamespace(
        context=SimpleNamespace(
            META={"CONTENT_TYPE": "multipart/form-data; boundary=x"},
            FILES=files,
        )
    )


class MutationFieldsTest(TestCase):
    """Coverage for "DjangoModelMutation.MutationFields".

    Confirms the three returned fields expose the native graphql-core
    resolver binding rather than the graphene-era attribute.
    """

    def test_mutation_fields_returns_three_fields(self) -> None:
        """ "MutationFields()" returns create/delete/update fields bound to their methods.

        This test breaks if the native graphql-core "GraphQLField" resolver
        binding regresses to the graphene-era ".resolver" attribute, or if
        the operations stop matching their method names.
        """
        create, delete, update = AuthorMutation.MutationFields()
        # Each is a native graphql-core ``GraphQLField`` bound to the matching
        # operation method. The native field exposes its resolver via ``.resolve``
        # (graphql-core), not the graphene-era ``.resolver`` attribute.
        assert create.resolve.__name__ == "create"
        assert delete.resolve.__name__ == "delete"
        assert update.resolve.__name__ == "update"


class MultipartTest(TestCase):
    """Coverage for the multipart FILES-merge branch in create/update.

    Also covers the update-save failure path, which returns errors instead
    of raising.
    """

    def test_create_merges_uploaded_files(self) -> None:
        """ "create" merges "context.FILES" values into the input data before saving.

        This test breaks if the multipart file-merge stops happening, which
        would silently drop uploaded file fields from the created object.
        """
        info = _multipart_info({"name": "FromFile"})
        data = {}
        result = AuthorMutation.create(None, info, **{"new_author": data})
        # The FILES value was merged into data before saving.
        assert result.ok, getattr(result, "errors", None)
        assert Author.objects.get().name == "FromFile"

    def test_update_merges_uploaded_files(self) -> None:
        """ "update" merges "context.FILES" values into the input data before saving.

        This test breaks if the multipart file-merge stops happening on the
        update path, which would silently drop uploaded file fields.
        """
        author = Author.objects.create(name="orig")
        info = _multipart_info({"name": "Patched"})
        data = {"id": author.pk}
        result = AuthorMutation.update(None, info, **{"new_author": data})
        assert result.ok, getattr(result, "errors", None)
        author.refresh_from_db()
        assert author.name == "Patched"

    def test_update_save_failure_returns_errors(self) -> None:
        """A model-validation failure on save is surfaced as "ok=False" with errors.

        This test breaks if the update path stops catching save failures and
        instead lets the validation exception propagate uncaught.
        """
        author = Author.objects.create(name="orig")
        info = SimpleNamespace(context=SimpleNamespace(META={}, FILES={}))
        # An over-long name fails model validation -> not ok -> errors.
        data = {"id": author.pk, "name": "x" * 500}
        result = AuthorMutation.update(None, info, **{"new_author": data})
        assert not result.ok
        assert result.errors


class InputDeprecationTest(TestCase):
    """Coverage for the deprecated "class Input" naming warning.

    Pins both the warning message and the continued collection of the
    legacy arguments onto the mutation's operations.
    """

    def test_input_class_emits_deprecation_warning(self) -> None:
        """Declaring "class Input" (instead of "Arguments") emits a deprecation warning.

        This test breaks if the "Input"-vs-"Arguments" deprecation warning
        stops firing, or if the legacy args stop being collected onto the
        mutation's operations.
        """
        # S-del-backend-11: the legacy ``class Input`` deprecation contract is about
        # the ``Input``-vs-``Arguments`` naming, not graphene. The arg is declared
        # with the native ``GraphQLArgument`` form (the graphene arg form was removed
        # in the v2.0 CLEAN BREAK, decision #1603).
        from graphql import GraphQLArgument, GraphQLString

        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")

            class _LegacyMutation(DjangoModelMutation):
                class Input:
                    """Legacy arguments container (deprecated alias for "Arguments")."""

                    extra = GraphQLArgument(GraphQLString)

                class Meta:
                    """Bind the legacy mutation to the "Author" model."""

                    model = Author

        messages = " ".join(str(w.message) for w in caught)
        assert "Arguments instead of" in messages
        # The legacy Input args were still collected onto every operation.
        assert "extra" in _LegacyMutation._meta.arguments["create"]
