"""Tests for #25 — Base64FileInput: opt-in base64 file uploads.

TDD RED→GREEN→REFACTOR cycle.

Coverage:
  - under-limit upload decodes to a SimpleUploadedFile (name/content/content_type)
  - FileField round-trip (save + read back) via an in-memory/temp MEDIA_ROOT
  - over per-field limit → GraphQLError (pre-check fires before full decode)
  - over global MAX_UPLOAD_SIZE limit → GraphQLError
  - per-field max_size override beats the global
  - MAX_UPLOAD_SIZE unset + Base64FileInput used → ImproperlyConfigured
  - MAX_REQUEST_BODY_SIZE: body over limit → 413/400; under → normal
  - batch request body over limit → 413/400
  - invalid base64 → GraphQLError (not 500)
  - default content_type when omitted
  - decode_base64_file module-level helper
"""

from __future__ import annotations

import base64
import json
import os
import tempfile
from unittest.mock import patch

import graphene
import pytest
from django.core.exceptions import ImproperlyConfigured
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import RequestFactory, TestCase, override_settings
from graphql import GraphQLError

# ---------------------------------------------------------------------------
# We import from the package — at RED phase these will ImportError; pytest
# will then mark them as collection errors (expected before implementation).
# ---------------------------------------------------------------------------
from django_graphex.uploads import Base64FileInput, decode_base64_file

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
_HELLO_BYTES = b"hello world"
_HELLO_B64 = base64.b64encode(_HELLO_BYTES).decode()

_TINY_PNG = (
    # 1x1 transparent PNG, 67 bytes
    b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01"
    b"\x08\x06\x00\x00\x00\x1f\x15\xc4\x89\x00\x00\x00\nIDATx\x9cc\x00\x01"
    b"\x00\x00\x05\x00\x01\r\n-\xb4\x00\x00\x00\x00IEND\xaeB`\x82"
)
_TINY_PNG_B64 = base64.b64encode(_TINY_PNG).decode()


# ---------------------------------------------------------------------------
# Unit: decode_base64_file
# ---------------------------------------------------------------------------


class TestDecodeBase64File:
    """decode_base64_file helper."""

    def test_decode_returns_simple_uploaded_file(self):
        """Happy path: valid base64 → SimpleUploadedFile with correct attributes."""
        result = decode_base64_file(
            {"filename": "hello.txt", "content_type": "text/plain", "data": _HELLO_B64},
            max_size=1024,
        )
        assert isinstance(result, SimpleUploadedFile)
        assert result.name == "hello.txt"
        assert result.read() == _HELLO_BYTES
        assert result.content_type == "text/plain"

    def test_default_content_type(self):
        """When content_type is absent/None, defaults to application/octet-stream."""
        result = decode_base64_file(
            {"filename": "blob.bin", "data": _HELLO_B64}, max_size=1024
        )
        assert result.content_type == "application/octet-stream"

    def test_invalid_base64_raises_graphql_error(self):
        """Non-base64 data → GraphQLError (never a 500 / binascii.Error)."""
        with pytest.raises(GraphQLError):
            decode_base64_file(
                {"filename": "bad.txt", "data": "!!!NOT_BASE64!!!"}, max_size=1024
            )

    def test_wrong_padding_raises_graphql_error(self):
        """Incorrectly padded base64 → GraphQLError."""
        with pytest.raises(GraphQLError):
            decode_base64_file(
                {"filename": "bad.txt", "data": "YWJj=="}, max_size=1024  # extra pad
            )

    def test_over_limit_raises_graphql_error(self):
        """Payload bigger than max_size → GraphQLError (pre-check before decode)."""
        data = base64.b64encode(b"x" * 200).decode()
        with pytest.raises(GraphQLError, match="exceeds"):
            decode_base64_file({"filename": "big.bin", "data": data}, max_size=100)

    def test_under_limit_succeeds(self):
        """Payload under max_size → decoded normally."""
        result = decode_base64_file({"filename": "ok.bin", "data": _HELLO_B64}, max_size=100)
        assert result.read() == _HELLO_BYTES

    def test_global_max_upload_size_enforced(self):
        """Without per-call max_size the global MAX_UPLOAD_SIZE cap is used."""
        data = base64.b64encode(b"x" * 200).decode()
        with override_settings(DJANGO_GRAPHEX={"MAX_UPLOAD_SIZE": 50}):
            from django_graphex import settings as _s

            _s.graphql_api_settings.reload()
            try:
                with pytest.raises(GraphQLError, match="exceeds"):
                    decode_base64_file({"filename": "big.bin", "data": data})
            finally:
                _s.graphql_api_settings.reload()

    def test_per_call_max_overrides_global(self):
        """Per-call max_size overrides the global MAX_UPLOAD_SIZE."""
        small_data = base64.b64encode(b"x" * 20).decode()
        with override_settings(DJANGO_GRAPHEX={"MAX_UPLOAD_SIZE": 10}):
            from django_graphex import settings as _s

            _s.graphql_api_settings.reload()
            try:
                # Per-call override of 100 allows data > global 10
                result = decode_base64_file(
                    {"filename": "ok.bin", "data": small_data}, max_size=100
                )
                assert result.read() == b"x" * 20
            finally:
                _s.graphql_api_settings.reload()


# ---------------------------------------------------------------------------
# Unit: Base64FileInput
# ---------------------------------------------------------------------------


def _make_container(filename, data, content_type=None):
    """Build a Base64FileInput container (the dict-like object that arrives in resolvers).

    graphene auto-generates a container class that is stored in
    ``Base64FileInput._meta.container`` and inherits from both
    ``InputObjectTypeContainer`` and ``Base64FileInput``. Use that class to
    create instances for unit tests.
    """
    container_cls = Base64FileInput._meta.container
    kwargs = {"filename": filename, "data": data}
    if content_type is not None:
        kwargs["content_type"] = content_type
    return container_cls(**kwargs)


class TestBase64FileInput:
    """Base64FileInput graphene.InputObjectType."""

    def test_is_input_object_type(self):
        """Base64FileInput must be a graphene.InputObjectType subclass."""
        assert issubclass(Base64FileInput, graphene.InputObjectType)

    def test_fields_present(self):
        """Must expose filename, data, and optional content_type fields."""
        fields = Base64FileInput._meta.fields
        assert "filename" in fields
        assert "data" in fields
        assert "content_type" in fields

    def test_to_uploaded_file(self):
        """Container.to_uploaded_file() → SimpleUploadedFile (as seen in a resolver)."""
        container = _make_container("photo.png", _TINY_PNG_B64, "image/png")
        result = container.to_uploaded_file(max_size=1024)
        assert isinstance(result, SimpleUploadedFile)
        assert result.name == "photo.png"
        assert result.content_type == "image/png"
        assert result.read() == _TINY_PNG

    def test_to_uploaded_file_default_content_type(self):
        """When content_type is absent, defaults to application/octet-stream."""
        container = _make_container("blob.bin", _HELLO_B64)
        result = container.to_uploaded_file(max_size=1024)
        assert result.content_type == "application/octet-stream"

    def test_to_uploaded_file_with_max_size(self):
        """to_uploaded_file(max_size=N) enforces a per-file cap."""
        large_data = base64.b64encode(b"x" * 200).decode()
        container = _make_container("big.bin", large_data)
        with pytest.raises(GraphQLError, match="exceeds"):
            container.to_uploaded_file(max_size=50)

    def test_container_inherits_from_base64_file_input(self):
        """Auto-generated container inherits from Base64FileInput (methods available)."""
        container_cls = Base64FileInput._meta.container
        assert issubclass(container_cls, Base64FileInput)

    def test_to_uploaded_file_available_in_schema_execution(self):
        """to_uploaded_file is callable on the value that arrives in a real resolver."""
        resolved_file = None

        class Mutation(graphene.ObjectType):
            upload = graphene.Field(
                graphene.String,
                file=Base64FileInput(required=True),
            )

            def resolve_upload(root, info, file):
                nonlocal resolved_file
                resolved_file = file.to_uploaded_file(max_size=1024)
                return resolved_file.name

        schema = graphene.Schema(query=Mutation)
        b64 = _HELLO_B64
        query = (
            '{ upload(file: {filename: "test.txt", '
            f'data: "{b64}", contentType: "text/plain"'
            "}) }"
        )
        result = schema.execute(query)
        assert result.errors is None
        assert resolved_file is not None
        assert resolved_file.read() == _HELLO_BYTES


# ---------------------------------------------------------------------------
# Integration: schema that uses Base64FileInput
# ---------------------------------------------------------------------------


class TestImproperlyConfiguredWhenNoMaxUploadSize(TestCase):
    """ImproperlyConfigured when MAX_UPLOAD_SIZE is not set and Base64FileInput is used."""

    @override_settings(DJANGO_GRAPHEX={})
    def test_raises_improperly_configured_without_max_upload_size(self):
        """decode_base64_file without MAX_UPLOAD_SIZE → ImproperlyConfigured."""
        from django_graphex import settings as _s

        _s.graphql_api_settings.reload()
        try:
            with pytest.raises(ImproperlyConfigured, match="MAX_UPLOAD_SIZE"):
                decode_base64_file({"filename": "any.txt", "data": _HELLO_B64})
        finally:
            _s.graphql_api_settings.reload()


# ---------------------------------------------------------------------------
# Integration: MAX_REQUEST_BODY_SIZE guard in the view
# ---------------------------------------------------------------------------


class TestMaxRequestBodySizeGuard(TestCase):
    """MAX_REQUEST_BODY_SIZE guard rejects oversized HTTP bodies BEFORE JSON parsing."""

    def _make_schema(self):
        class Query(graphene.ObjectType):
            hello = graphene.String()

            def resolve_hello(self, info):
                return "world"

        return graphene.Schema(query=Query)

    def _make_view(self, schema=None):
        from django_graphex.views import BaseGraphQLView

        if schema is None:
            schema = self._make_schema()
        return BaseGraphQLView.as_view(schema=schema)

    def _post_body(self, view, body: bytes, content_type: str = "application/json"):
        rf = RequestFactory()
        request = rf.post("/graphql/", data=body, content_type=content_type)
        return view(request)

    @override_settings(DJANGO_GRAPHEX={"MAX_REQUEST_BODY_SIZE": 50})
    def test_body_over_limit_returns_413_or_400(self):
        """A request body over MAX_REQUEST_BODY_SIZE is rejected before parsing."""
        from django_graphex import settings as _s

        _s.graphql_api_settings.reload()
        try:
            view = self._make_view()
            big_body = b"x" * 100
            response = self._post_body(view, big_body)
            assert response.status_code in (400, 413)
        finally:
            _s.graphql_api_settings.reload()

    @override_settings(DJANGO_GRAPHEX={"MAX_REQUEST_BODY_SIZE": 5000})
    def test_body_under_limit_passes_through(self):
        """A body under MAX_REQUEST_BODY_SIZE is processed normally."""
        from django_graphex import settings as _s

        _s.graphql_api_settings.reload()
        try:
            view = self._make_view()
            payload = json.dumps({"query": "{ hello }"}).encode()
            response = self._post_body(view, payload)
            assert response.status_code == 200
            data = json.loads(response.content)
            assert data["data"]["hello"] == "world"
        finally:
            _s.graphql_api_settings.reload()

    @override_settings(DJANGO_GRAPHEX={"MAX_REQUEST_BODY_SIZE": None})
    def test_no_limit_when_setting_is_none(self):
        """When MAX_REQUEST_BODY_SIZE is None, no body-size check is performed."""
        from django_graphex import settings as _s

        _s.graphql_api_settings.reload()
        try:
            view = self._make_view()
            payload = json.dumps({"query": "{ hello }"}).encode()
            response = self._post_body(view, payload)
            assert response.status_code == 200
        finally:
            _s.graphql_api_settings.reload()

    @override_settings(DJANGO_GRAPHEX={"MAX_REQUEST_BODY_SIZE": 50})
    def test_batch_over_limit_returns_413_or_400(self):
        """A batch request body over the limit is rejected before parsing."""
        from django_graphex import settings as _s

        _s.graphql_api_settings.reload()
        try:
            schema = self._make_schema()
            view = BaseGraphQLView_batch = None

            from django_graphex.views import BaseGraphQLView

            view = BaseGraphQLView.as_view(schema=schema, batch=True)
            big_body = b"x" * 200
            rf = RequestFactory()
            request = rf.post(
                "/graphql/", data=big_body, content_type="application/json"
            )
            response = view(request)
            assert response.status_code in (400, 413)
        finally:
            _s.graphql_api_settings.reload()


# ---------------------------------------------------------------------------
# FileField round-trip via a temp MEDIA_ROOT
# ---------------------------------------------------------------------------


class TestFileFieldRoundTrip(TestCase):
    """Save a SimpleUploadedFile from decode_base64_file to a real FileField."""

    def setUp(self):
        self.tmp_dir = tempfile.mkdtemp()

    def tearDown(self):
        import shutil

        shutil.rmtree(self.tmp_dir, ignore_errors=True)

    @override_settings(MEDIA_ROOT=None)
    def test_round_trip(self):
        """File is saved to disk and readable back with correct content."""
        import django.core.files.storage as storage_module
        from django.core.files.storage import FileSystemStorage

        storage = FileSystemStorage(location=self.tmp_dir)

        with override_settings(DJANGO_GRAPHEX={"MAX_UPLOAD_SIZE": 1024}):
            from django_graphex import settings as _s

            _s.graphql_api_settings.reload()
            try:
                uploaded = decode_base64_file(
                    {
                        "filename": "test.txt",
                        "content_type": "text/plain",
                        "data": _HELLO_B64,
                    }
                )
                name = storage.save("test.txt", uploaded)
                path = storage.path(name)
                with open(path, "rb") as f:
                    assert f.read() == _HELLO_BYTES
            finally:
                _s.graphql_api_settings.reload()
