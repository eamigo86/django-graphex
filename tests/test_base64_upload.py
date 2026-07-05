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
import tempfile
from typing import Any

import pytest
from django.core.exceptions import ImproperlyConfigured
from django.core.files.uploadedfile import SimpleUploadedFile
from django.http import HttpResponse
from django.test import RequestFactory, TestCase, override_settings
from graphql import GraphQLError, GraphQLString

from django_graphex.core import ObjectType, field
from django_graphex.schema import DjangoGraphQLSchema

# ---------------------------------------------------------------------------
# We import from the package. ``Base64FileInput`` itself is now a native
# ``InputType`` (Pydantic) — its native behavior is covered in
# ``tests/core/test_s_roots_g_base64_native.py``; this legacy file keeps the
# ``decode_base64_file`` helper + view-guard coverage (the retired graphene
# container assertions are skipped above).
# ---------------------------------------------------------------------------
from django_graphex.uploads import decode_base64_file

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
    """Tests for the "decode_base64_file" module-level helper.

    Covers happy-path decoding, content-type defaulting, malformed-input
    rejection, and the per-call/global size-limit interaction.
    """

    def test_decode_returns_simple_uploaded_file(self) -> None:
        """Valid base64 input must decode to a correctly populated SimpleUploadedFile.

        Checks the filename, decoded content, and content_type attributes
        all round-trip through the helper unchanged.
        """
        result = decode_base64_file(
            {"filename": "hello.txt", "content_type": "text/plain", "data": _HELLO_B64},
            max_size=1024,
        )
        assert isinstance(result, SimpleUploadedFile)
        assert result.name == "hello.txt"
        assert result.read() == _HELLO_BYTES
        assert result.content_type == "text/plain"

    def test_default_content_type(self) -> None:
        """An omitted content_type must default to application/octet-stream.

        Guards against the helper leaving content_type as None or empty
        when the caller does not supply one.
        """
        result = decode_base64_file(
            {"filename": "blob.bin", "data": _HELLO_B64}, max_size=1024
        )
        assert result.content_type == "application/octet-stream"

    def test_invalid_base64_raises_graphql_error(self) -> None:
        """Non-base64 data must raise GraphQLError, never a raw 500.

        If this breaks, a malformed upload would surface as an unhandled
        binascii.Error instead of a clean GraphQL error.
        """
        with pytest.raises(GraphQLError):
            decode_base64_file(
                {"filename": "bad.txt", "data": "!!!NOT_BASE64!!!"}, max_size=1024
            )

    def test_wrong_padding_raises_graphql_error(self) -> None:
        """Incorrectly padded base64 must raise GraphQLError.

        Guards against a padding-only malformation slipping past validation.
        """
        with pytest.raises(GraphQLError):
            decode_base64_file(
                {"filename": "bad.txt", "data": "YWJj=="},
                max_size=1024,  # extra pad
            )

    def test_over_limit_raises_graphql_error(self) -> None:
        """A payload bigger than max_size must raise GraphQLError before decoding.

        The pre-check must fire on the encoded size, avoiding a full decode
        of an oversized payload.
        """
        data = base64.b64encode(b"x" * 200).decode()
        with pytest.raises(GraphQLError, match="exceeds"):
            decode_base64_file({"filename": "big.bin", "data": data}, max_size=100)

    def test_under_limit_succeeds(self) -> None:
        """A payload under max_size must decode normally.

        Regression guard for the over-limit pre-check rejecting valid
        uploads.
        """
        result = decode_base64_file(
            {"filename": "ok.bin", "data": _HELLO_B64}, max_size=100
        )
        assert result.read() == _HELLO_BYTES

    def test_global_max_upload_size_enforced(self) -> None:
        """Without a per-call max_size, the global MAX_UPLOAD_SIZE cap must apply.

        If this breaks, callers that omit "max_size" could upload files of
        unbounded size.
        """
        data = base64.b64encode(b"x" * 200).decode()
        with override_settings(DJANGO_GRAPHEX={"MAX_UPLOAD_SIZE": 50}):
            from django_graphex import settings as _s

            _s.graphql_api_settings.reload()
            try:
                with pytest.raises(GraphQLError, match="exceeds"):
                    decode_base64_file({"filename": "big.bin", "data": data})
            finally:
                _s.graphql_api_settings.reload()

    def test_per_call_max_overrides_global(self) -> None:
        """A per-call max_size must override the global MAX_UPLOAD_SIZE.

        A caller passing a larger explicit "max_size" must be able to
        upload beyond the global cap.
        """
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


# ---------------------------------------------------------------------------
# RETIRED (S-ROOTS-g / S7): graphene-only Base64FileInput container assertions.
#
# Base64FileInput was ported to a native ``InputType`` (a Pydantic model) in
# S-ROOTS-g. The graphene container surface it relied on
# (``_meta.container`` / ``issubclass(graphene.InputObjectType)`` /
# ``graphene.Schema`` execution of the input) no longer exists. The graphene-free
# behavior — a VALIDATED Base64FileInput instance decoding to a
# ``SimpleUploadedFile`` end-to-end — is asserted in the native replacement
# suite ``tests/core/test_s_roots_g_base64_native.py``. This whole class is
# pruned in S7 alongside the rest of the graphene-suite retirement.
# ---------------------------------------------------------------------------
@pytest.mark.skip(
    reason="S-ROOTS-g: Base64FileInput is now a native InputType (Pydantic). "
    "Graphene container assertions retired; native behavior covered by "
    "tests/core/test_s_roots_g_base64_native.py. Pruned in S7."
)
class TestBase64FileInput:
    """RETIRED graphene-container assertions.

    See the module note above: the graphene container surface these tests
    exercised no longer exists after the S-ROOTS-g native port.
    """

    def test_retired_graphene_container_surface(self) -> None:
        """Placeholder marking the retired graphene container contract.

        The graphene container contract this test used to assert is gone
        in 2.0; native behavior is covered by
        "tests/core/test_s_roots_g_base64_native.py".
        """


# ---------------------------------------------------------------------------
# Integration: schema that uses Base64FileInput
# ---------------------------------------------------------------------------


class TestImproperlyConfiguredWhenNoMaxUploadSize(TestCase):
    """ImproperlyConfigured must be raised when MAX_UPLOAD_SIZE is unset.

    Covers the case where Base64FileInput decoding is attempted without a
    configured upload-size cap.
    """

    @override_settings(DJANGO_GRAPHEX={})
    def test_raises_improperly_configured_without_max_upload_size(self) -> None:
        """decode_base64_file without MAX_UPLOAD_SIZE must raise ImproperlyConfigured.

        Prevents silently allowing unbounded uploads when the required
        setting was never configured.
        """
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
    """MAX_REQUEST_BODY_SIZE guard rejects oversized HTTP bodies before JSON parsing.

    Covers Content-Length spoofing, missing/garbage headers, and the batch
    view path, all of which must fall back to the authoritative
    len(request.body) check.
    """

    def _make_schema(self) -> DjangoGraphQLSchema:
        """Build a minimal schema with a single "hello" query field.

        Returns:
            schema: A schema exposing "{ hello }" resolving to "world".
        """

        class Query(ObjectType):
            hello = field(GraphQLString)

            def resolve_hello(self, info):
                return "world"

        return DjangoGraphQLSchema(query=Query)

    def _make_view(self, schema: DjangoGraphQLSchema | None = None) -> Any:
        """Build a "BaseGraphQLView" bound to a schema.

        Args:
            schema: The schema to bind; when None, a fresh minimal schema is
                built via "_make_schema".

        Returns:
            view: The view callable returned by Django's "as_view".
        """
        from django_graphex.views import BaseGraphQLView

        if schema is None:
            schema = self._make_schema()
        return BaseGraphQLView.as_view(schema=schema)

    def _post_body(
        self, view: Any, body: bytes, content_type: str = "application/json"
    ) -> HttpResponse:
        """POST a raw body to a view and return its response.

        Args:
            view: The view callable to invoke.
            body: The raw request body bytes.
            content_type: The Content-Type header value for the request.

        Returns:
            response: The HttpResponse produced by the view.
        """
        rf = RequestFactory()
        request = rf.post("/graphql/", data=body, content_type=content_type)
        return view(request)

    @override_settings(DJANGO_GRAPHEX={"MAX_REQUEST_BODY_SIZE": 50})
    def test_body_over_limit_returns_413_or_400(self) -> None:
        """A request body over MAX_REQUEST_BODY_SIZE must be rejected before parsing.

        If this breaks, an oversized body could reach JSON parsing and
        resolver execution instead of being fast-rejected.
        """
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
    def test_body_under_limit_passes_through(self) -> None:
        """A body under MAX_REQUEST_BODY_SIZE must be processed normally.

        Regression guard for the size guard rejecting valid requests.
        """
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
    def test_no_limit_when_setting_is_none(self) -> None:
        """With MAX_REQUEST_BODY_SIZE set to None, no body-size check must run.

        Confirms the guard is opt-in and does not fire when explicitly
        disabled.
        """
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
    def test_spoofed_low_content_length_still_rejected(self) -> None:
        """A spoofed-low Content-Length must NOT bypass the size guard.

        A client that sends CONTENT_LENGTH: 10 but a real body larger than
        MAX_REQUEST_BODY_SIZE must receive 413. The old code trusted the
        header and skipped the body-length check, letting the request through.
        """
        from django_graphex import settings as _s

        _s.graphql_api_settings.reload()
        try:
            view = self._make_view()
            # Real body is 200 bytes — well over the 50-byte cap.
            big_body = b"x" * 200
            rf = RequestFactory()
            request = rf.post(
                "/graphql/", data=big_body, content_type="application/json"
            )
            # Spoof a low Content-Length that would pass the old check.
            request.META["CONTENT_LENGTH"] = "10"
            # Pre-populate _body cache so Django serves it without re-parsing headers.
            _ = request.body
            response = view(request)
            assert response.status_code == 413, (
                f"Expected 413 for spoofed-low CL but got {response.status_code}. "
                "The guard must check len(request.body), not trust Content-Length."
            )
        finally:
            _s.graphql_api_settings.reload()

    @override_settings(DJANGO_GRAPHEX={"MAX_REQUEST_BODY_SIZE": 50})
    def test_honest_large_body_fast_reject_413(self) -> None:
        """An honest large body with an accurate Content-Length must fast-reject.

        When Content-Length is accurate and over the cap, the guard should
        reject via the cheap header check (413) without reading the body.
        """
        from django_graphex import settings as _s

        _s.graphql_api_settings.reload()
        try:
            view = self._make_view()
            big_body = b"x" * 200
            rf = RequestFactory()
            request = rf.post(
                "/graphql/", data=big_body, content_type="application/json"
            )
            # Accurate CL — triggers fast-reject path.
            request.META["CONTENT_LENGTH"] = str(len(big_body))
            response = view(request)
            assert response.status_code == 413
        finally:
            _s.graphql_api_settings.reload()

    @override_settings(DJANGO_GRAPHEX={"MAX_REQUEST_BODY_SIZE": 50})
    def test_absent_content_length_over_cap_rejected(self) -> None:
        """A body over the cap with no Content-Length header must still be rejected.

        The authoritative len(request.body) check must catch the oversized
        request even without a header to fast-reject on.
        """
        from django_graphex import settings as _s

        _s.graphql_api_settings.reload()
        try:
            view = self._make_view()
            big_body = b"x" * 200
            rf = RequestFactory()
            request = rf.post(
                "/graphql/", data=big_body, content_type="application/json"
            )
            request.META.pop("CONTENT_LENGTH", None)
            _ = request.body  # pre-populate cache
            response = view(request)
            assert response.status_code == 413
        finally:
            _s.graphql_api_settings.reload()

    @override_settings(DJANGO_GRAPHEX={"MAX_REQUEST_BODY_SIZE": 50})
    def test_garbage_content_length_over_cap_rejected(self) -> None:
        """A body over the cap with an unparsable Content-Length must still be rejected.

        The authoritative len(request.body) check must catch the oversized
        request even when the header value cannot be parsed as an integer.
        """
        from django_graphex import settings as _s

        _s.graphql_api_settings.reload()
        try:
            view = self._make_view()
            big_body = b"x" * 200
            rf = RequestFactory()
            request = rf.post(
                "/graphql/", data=big_body, content_type="application/json"
            )
            _ = request.body  # pre-populate cache
            request.META["CONTENT_LENGTH"] = "garbage"
            response = view(request)
            assert response.status_code == 413
        finally:
            _s.graphql_api_settings.reload()

    @override_settings(DJANGO_GRAPHEX={"MAX_REQUEST_BODY_SIZE": 50})
    def test_batch_over_limit_returns_413_or_400(self) -> None:
        """A batch request body over the limit must be rejected before parsing.

        Confirms the same body-size guard applies to the batch view path,
        not just the single-operation path.
        """
        from django_graphex import settings as _s

        _s.graphql_api_settings.reload()
        try:
            from django_graphex.views import BaseGraphQLView

            schema = self._make_schema()
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
    """Save a SimpleUploadedFile from decode_base64_file to a real FileField.

    Uses a temporary directory as MEDIA_ROOT so the round-trip exercises
    real filesystem storage instead of an in-memory stand-in.
    """

    def setUp(self) -> None:
        """Create a temporary directory.

        Acts as this test's MEDIA_ROOT so saved files do not touch the
        real project media directory.
        """
        self.tmp_dir = tempfile.mkdtemp()

    def tearDown(self) -> None:
        """Remove the temporary MEDIA_ROOT directory.

        Cleans up the directory created in "setUp" regardless of test
        outcome.
        """
        import shutil

        shutil.rmtree(self.tmp_dir, ignore_errors=True)

    @override_settings(MEDIA_ROOT=None)
    def test_round_trip(self) -> None:
        """A decoded file must be saved to disk and readable back unchanged.

        Exercises the full path from base64 decoding through FileSystemStorage
        save and re-read, confirming content survives the round-trip.
        """
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
