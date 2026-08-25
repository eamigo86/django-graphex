# -*- coding: utf-8 -*-
"""Multipart "FileField" / "ImageField" uploads on both mutation hosts.

The merge that folds "info.context.FILES" into the input payload has always
existed, but the derived Pydantic schema typed a file field as "str", so the
"UploadedFile" it merged was rejected with "Input should be a valid string" and
no upload could ever be saved. These tests pin the whole top-level path:

* an "UploadedFile" reaches storage on create and on update, on
  "DjangoModelMutation" (the "DjangoModelType" host is pinned in
  "test_serializer_crud_edges"),
* a plain storage-path STRING still validates and still saves (the only shape
  that worked before the fix),
* the column's "max_length" still constrains that string branch,
* a value that is neither a file nor a string is a structured "errors[]" entry,
  not a raw Django exception escaping as a 500,
* the wire stays "String" on BOTH ends: the output field reads the storage name
  and the input field accepts a path, exactly as before the fix.
"""

from __future__ import annotations

import tempfile
import warnings
from types import SimpleNamespace
from typing import Any

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import override_settings
from graphql import GraphQLString, get_named_type, print_schema

from django_graphex.core import ObjectType
from django_graphex.core.fields import FileScalar, _file_scalar
from django_graphex.core.input_compiler import _python_type_to_gql
from django_graphex.core.registry_compiler import compile_all_outputs
from django_graphex.mutation import DjangoModelMutation
from django_graphex.schema import DjangoGraphQLSchema
from django_graphex.types import DjangoModelType
from tests.models import ProjectedUploadDoc, UploadDoc


class UploadDocMutation(DjangoModelMutation):
    """The "DjangoModelMutation" host over the upload model.

    Every top-level upload case runs against this host; the "DjangoModelType" twin is
    pinned in "test_serializer_crud_edges", so nothing here repeats it.
    """

    class Meta:
        """Bind the mutation to "UploadDoc".

        No projection is declared, so "attachment" stays on the input surface and the
        multipart merge has a field to land on.
        """

        model = UploadDoc


class UploadDocSchemaType(DjangoModelType):
    """The "DjangoModelType" host, mounted only to render an SDL.

    The wire-type assertions need real query and mutation roots to print; this host
    writes nothing itself.
    """

    class Meta:
        """Bind the type to "UploadDoc".

        Deliberately the same model as the mutation host: the SDL check has to prove
        both ends of ONE file column stay "String".
        """

        model = UploadDoc


class _Query(ObjectType):
    """Root exposing the retrieve field, so the OUTPUT type reaches the SDL."""

    upload_doc_retrieve = UploadDocSchemaType.RetrieveField()


class _Mutation(ObjectType):
    """Root exposing the create field, so the INPUT type reaches the SDL."""

    upload_doc_create = UploadDocSchemaType.CreateField()


def _multipart_info(files: dict[str, Any]) -> SimpleNamespace:
    """Build a resolver-info stand-in carrying a multipart request context.

    Args:
        files: The mapping to expose as "context.FILES".

    Returns:
        info: A namespace shaped like the subset of resolve info the multipart
            merge reads.
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


def _payload(data: dict[str, Any]) -> dict[str, Any]:
    """Wrap input data under the mutation's configured input field name.

    Args:
        data: The input payload to nest.

    Returns:
        kwargs: A single-key mapping suitable for "create" / "update".
    """
    return {UploadDocMutation._meta.input_field_name: data}


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


@pytest.mark.django_db
def test_model_mutation_create_saves_a_real_uploaded_file() -> None:
    """Assert "DjangoModelMutation.create" stores an upload's bytes.

    This test breaks if the derived schema stops accepting a file object on the
    "DjangoModelMutation" host, which sends every multipart create back as
    "Input should be a valid string".
    """
    info = _multipart_info({"attachment": _upload()})
    with tempfile.TemporaryDirectory() as media, override_settings(MEDIA_ROOT=media):
        result = UploadDocMutation.create(None, info, **_payload({"label": "L"}))
        assert result.ok, _error_pairs(result)
        doc = UploadDoc.objects.get()
        assert doc.attachment, "The uploaded file was not attached to the row"
        with doc.attachment.open("rb") as stored:
            assert stored.read() == b"hello-bytes"


@pytest.mark.django_db
def test_model_mutation_update_saves_a_real_uploaded_file() -> None:
    """Assert "DjangoModelMutation.update" stores an upload's bytes.

    This test breaks if the derived partial schema stops accepting a file
    object, which sends every multipart update back as a validation error.
    """
    doc = UploadDoc.objects.create(label="orig")
    info = _multipart_info({"attachment": _upload()})
    with tempfile.TemporaryDirectory() as media, override_settings(MEDIA_ROOT=media):
        result = UploadDocMutation.update(None, info, **_payload({"id": doc.pk}))
        assert result.ok, _error_pairs(result)
        doc.refresh_from_db()
        assert doc.attachment, "The uploaded file was not attached to the row"
        with doc.attachment.open("rb") as stored:
            assert stored.read() == b"hello-bytes"


@pytest.mark.django_db
def test_a_plain_storage_path_string_is_still_accepted() -> None:
    """Assert assigning a storage-path STRING still validates and saves.

    This is the ONLY file-field write that worked before the fix, and the input
    wire type is still "String"; this test breaks if the file scalar stops
    accepting the string branch.
    """
    result = UploadDocMutation.create(
        None,
        _multipart_info({}),
        **_payload({"label": "L", "attachment": "uploads/existing.txt"}),
    )
    assert result.ok, _error_pairs(result)
    assert UploadDoc.objects.get().attachment.name == "uploads/existing.txt"


@pytest.mark.django_db
def test_an_over_long_storage_path_string_is_rejected() -> None:
    """Assert the column's "max_length" still constrains the string branch.

    This test breaks if the file scalar drops the "max_length" constraint the
    "str" mapping used to carry: an over-long path would then validate clean and
    reach the database (silently truncated-or-stored on SQLite, a "DataError"
    and a 500 on PostgreSQL).
    """
    result = UploadDocMutation.create(
        None,
        _multipart_info({}),
        **_payload({"label": "L", "attachment": "u/" + "x" * 300}),
    )
    assert not result.ok
    assert "attachment" in dict(_error_pairs(result))
    assert not UploadDoc.objects.exists()


@pytest.mark.django_db
def test_a_value_that_is_neither_file_nor_string_is_a_structured_error() -> None:
    """Assert a non-file, non-string value returns "errors[]" instead of raising.

    This test breaks if the file scalar degrades to a permissive "any" schema:
    an int would then sail through validation and blow up at "save()" as an
    uncaught Django exception -- a 500 rather than a structured result.
    """
    result = UploadDocMutation.create(
        None,
        _multipart_info({}),
        **_payload({"label": "L", "attachment": 123}),
    )
    assert not result.ok
    assert "attachment" in dict(_error_pairs(result))
    assert not UploadDoc.objects.exists()


def test_the_file_field_wire_type_is_string_on_both_ends() -> None:
    """Assert the SDL still renders the file field as "String" on input and output.

    This test breaks if the file scalar leaks into the schema: introducing an
    "Upload" scalar (or any other named type) here is a breaking wire change for
    every existing client.
    """
    compile_all_outputs()
    schema = DjangoGraphQLSchema(query=_Query, mutation=_Mutation).graphql_schema
    printed = print_schema(schema)

    output_type = get_named_type(schema.query_type.fields["uploadDocRetrieve"].type)
    assert str(output_type.fields["attachment"].type) == "String"

    (argument,) = schema.mutation_type.fields["uploadDocCreate"].args.values()
    input_type = get_named_type(argument.type)
    assert str(input_type.fields["attachment"].type) == "String"

    assert "scalar Upload" not in printed


def test_the_file_scalar_is_mapped_explicitly_not_by_the_unknown_fallback() -> None:
    """Assert the input compiler maps the file marker without degrading loudly.

    The unknown-class fallback also returns "String", so the SDL alone cannot
    tell the two apart. This test breaks if the explicit mapping is dropped: the
    marker would then trip the "unsupported input field type" warning on every
    schema build that carries a file field.
    """
    with warnings.catch_warnings():
        warnings.simplefilter("error")
        assert _python_type_to_gql(FileScalar) is GraphQLString
        assert _python_type_to_gql(_file_scalar(40)) is GraphQLString


class TestTheMergeHonoursTheInputProjection:
    """A multipart part must not reach a column the input projects away.

    Before file objects validated, an excluded file column was written to the
    row and then rejected by validation, so nothing landed. Making the value
    valid turned the same merge into a live write path that never passed the
    wire surface meant to bound it: a type declaring
    "exclude_fields = ('attachment',)" published no such input field and saved
    the file anyway.
    """

    @pytest.mark.django_db
    def test_an_excluded_file_column_is_not_written_by_a_multipart_part(self) -> None:
        """Assert a part named after an excluded column leaves the row untouched.

        This test breaks if the merge trusts the part name instead of the compiled input
        surface: the file lands on a column no client could have named, which is a write
        straight past the projection boundary.
        """

        class _ProjectedDocType(DjangoModelType):
            """A host that deliberately keeps its file column off the input."""

            class Meta:
                """Bind to "ProjectedUploadDoc", projecting the attachment away."""

                model = ProjectedUploadDoc
                exclude_fields = ("attachment",)

        argument = _ProjectedDocType._meta.arguments["create"][
            _ProjectedDocType._meta.input_field_name
        ]
        assert "attachment" not in get_named_type(argument.type).fields, (
            "Fixture precondition failed: the input still exposes 'attachment'"
        )

        info = _multipart_info({"attachment": _upload()})
        with (
            tempfile.TemporaryDirectory() as media,
            override_settings(MEDIA_ROOT=media),
        ):
            result = _ProjectedDocType.create(
                None,
                info,
                **{_ProjectedDocType._meta.input_field_name: {"label": "L"}},
            )
            assert result.ok, "The mutation should still succeed, ignoring the part"
            row = ProjectedUploadDoc.objects.get()
            assert not row.attachment, (
                "A multipart part wrote a column the input projects away: "
                f"{row.attachment.name}"
            )

    @pytest.mark.django_db
    def test_a_part_naming_no_field_at_all_is_ignored(self) -> None:
        """Assert an unrecognised part neither writes nor fails the mutation.

        The other half of the projection guard: an unknown part must be dropped quietly,
        or any stray form field would turn a valid multipart mutation into an error.
        """
        info = _multipart_info({"not_a_field": _upload()})
        with (
            tempfile.TemporaryDirectory() as media,
            override_settings(MEDIA_ROOT=media),
        ):
            result = UploadDocMutation.create(None, info, **_payload({"label": "L"}))
            assert result.ok, "An unrecognised part must not fail the mutation"
            assert not UploadDoc.objects.get().attachment
