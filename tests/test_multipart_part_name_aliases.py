# -*- coding: utf-8 -*-
"""Multipart part names: the published alias merges as well as the attribute.

The merge that folds "info.context.FILES" into a mutation payload built its
allow-list from each input field's "out_name" -- the model's snake_case
attribute -- so the only spelling the SDL ever shows a client, the camelCase
alias, matched nothing. The part was dropped and the mutation still answered
"ok: true" with no file written. These tests pin the part-name surface:

* the camelCase alias a client reads off the SDL lands on the column,
* the snake_case attribute still lands on it too,
* the projection guard survives BOTH spellings: a part named after a column
  the input does not publish is ignored under either name, so an alias cannot
  be used to walk around "Meta.exclude_fields".
"""

from __future__ import annotations

import tempfile
from types import SimpleNamespace
from typing import Any

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from django.db import models
from django.test import override_settings
from graphql import get_named_type

from django_graphex.mutation import DjangoModelMutation
from django_graphex.types import DjangoModelType
from tests.models import DummyModel


class AliasUploadDoc(DummyModel):
    """Row whose file column has a MULTI-WORD name.

    Every existing upload fixture is named "attachment", where the camelCase
    alias and the snake attribute happen to be the same string, so neither
    spelling can be told from the other. Two words are the minimum needed to
    make "profilePhoto" and "profile_photo" differ.
    """

    label = models.CharField(max_length=50)
    profile_photo = models.FileField(upload_to="uploads/", max_length=60, blank=True)


class ProjectedAliasUploadDoc(DummyModel):
    """Row for the host that projects its multi-word file column away.

    Dedicated rather than shared with "AliasUploadDoc": the output-type reuse
    guard refuses a projection on a model another host already registered.
    """

    label = models.CharField(max_length=50)
    profile_photo = models.FileField(upload_to="uploads/", max_length=60, blank=True)


class AliasUploadDocMutation(DjangoModelMutation):
    """The mutation host over the multi-word upload model.

    No projection is declared, so "profile_photo" stays on the input surface
    and both of its spellings have a field to land on.
    """

    class Meta:
        """Bind the mutation to "AliasUploadDoc".

        No projection: the whole point is a field that IS published.
        """

        model = AliasUploadDoc


class ProjectedAliasDocType(DjangoModelType):
    """A host that deliberately keeps its multi-word file column off the input.

    The counterweight to the merge tests: widening the allow-list to a second
    spelling must not widen it to a field the input withholds.
    """

    class Meta:
        """Bind to "ProjectedAliasUploadDoc", projecting the photo away.

        The exclusion is what makes both spellings unmatched here.
        """

        model = ProjectedAliasUploadDoc
        exclude_fields = ("profile_photo",)


def _multipart_info(files: dict[str, Any]) -> SimpleNamespace:
    """Build a resolver-info stand-in carrying a multipart request context.

    Args:
        files: The mapping to expose as "context.FILES".

    Returns:
        info: A namespace shaped like the subset of resolve info the merge reads.
    """
    return SimpleNamespace(
        context=SimpleNamespace(
            META={"CONTENT_TYPE": "multipart/form-data; boundary=x"}, FILES=files
        )
    )


def _upload() -> SimpleUploadedFile:
    """Build a small in-memory upload.

    Returns:
        upload: A text upload named "hello.txt" carrying "hello-bytes".
    """
    return SimpleUploadedFile("hello.txt", b"hello-bytes", content_type="text/plain")


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


def _create(part_name: str) -> Any:
    """Run a create through the mutation host with ONE multipart part.

    Args:
        part_name: The form-field name the upload is sent under.

    Returns:
        result: The mutation result, with "MEDIA_ROOT" already torn down.
    """
    info = _multipart_info({part_name: _upload()})
    payload = {AliasUploadDocMutation._meta.input_field_name: {"label": "L"}}
    with tempfile.TemporaryDirectory() as media, override_settings(MEDIA_ROOT=media):
        result = AliasUploadDocMutation.create(None, info, **payload)
        if getattr(result, "ok", False):
            # Read the bytes back INSIDE the temporary MEDIA_ROOT: the file is
            # gone once the directory is removed, so the assertion cannot run
            # in the caller.
            row = AliasUploadDoc.objects.get()
            if row.profile_photo:
                with row.profile_photo.open("rb") as stored:
                    assert stored.read() == b"hello-bytes"
        return result


def test_the_sdl_spelling_of_a_part_name_lands_on_the_column() -> None:
    """Assert the input publishes the file column under its camelCase alias.

    Fixture precondition for the merge tests below: it is the alias, not the
    attribute, that a client can discover from the schema.
    """
    argument = AliasUploadDocMutation._meta.arguments["create"][
        AliasUploadDocMutation._meta.input_field_name
    ]
    fields = get_named_type(argument.type).fields
    assert "profilePhoto" in fields
    assert fields["profilePhoto"].out_name == "profile_photo"


@pytest.mark.django_db
def test_a_part_named_with_the_published_alias_is_merged() -> None:
    """Assert a part named "profilePhoto" reaches the column.

    This test breaks if the merge goes back to matching "out_name" only: the
    single spelling a client can read off the SDL then matches nothing, the
    part is dropped, and the mutation answers "ok: true" with no file written.
    """
    result = _create("profilePhoto")
    assert result.ok, _error_pairs(result)
    assert AliasUploadDoc.objects.get().profile_photo, (
        "The part named with the published alias was dropped"
    )


@pytest.mark.django_db
def test_a_part_named_with_the_model_attribute_is_still_merged() -> None:
    """Assert a part named "profile_photo" still reaches the column.

    The spelling that always worked. This test breaks if accepting the alias
    replaces the attribute instead of joining it, which silently retires the
    part names every existing client already sends.
    """
    result = _create("profile_photo")
    assert result.ok, _error_pairs(result)
    assert AliasUploadDoc.objects.get().profile_photo, (
        "The part named with the model attribute was dropped"
    )


@pytest.mark.django_db
def test_a_part_naming_no_field_at_all_is_still_ignored() -> None:
    """Assert an unrecognised part neither writes nor fails the mutation.

    This test breaks if widening the allow-list widens it to everything: any
    stray form field would then be merged into the payload and fail validation.
    """
    result = _create("notAField")
    assert result.ok, "An unrecognised part must not fail the mutation"
    assert not AliasUploadDoc.objects.get().profile_photo


class TestTheProjectionGuardHoldsForBothSpellings:
    """A projected-away column stays unreachable under EITHER part name.

    Accepting the alias must widen the allow-list to a second spelling of the
    fields the input publishes, never to a field it withholds.
    """

    @pytest.mark.django_db
    @pytest.mark.parametrize("part_name", ["profilePhoto", "profile_photo"])
    def test_an_excluded_column_is_not_written_by_a_multipart_part(
        self, part_name: str
    ) -> None:
        """Assert a part named after an excluded column leaves the row untouched.

        Args:
            part_name: The spelling the upload is sent under.
        """
        argument = ProjectedAliasDocType._meta.arguments["create"][
            ProjectedAliasDocType._meta.input_field_name
        ]
        fields = get_named_type(argument.type).fields
        assert "profilePhoto" not in fields and "profile_photo" not in fields, (
            "Fixture precondition failed: the input still exposes the photo"
        )

        info = _multipart_info({part_name: _upload()})
        with (
            tempfile.TemporaryDirectory() as media,
            override_settings(MEDIA_ROOT=media),
        ):
            result = ProjectedAliasDocType.create(
                None,
                info,
                **{ProjectedAliasDocType._meta.input_field_name: {"label": "L"}},
            )
            assert result.ok, "The mutation should still succeed, ignoring the part"
            row = ProjectedAliasUploadDoc.objects.get()
            assert not row.profile_photo, (
                "A multipart part wrote a column the input projects away: "
                f"{row.profile_photo.name}"
            )
