# -*- coding: utf-8 -*-
"""MAX_UPLOAD_SIZE means the same number of bytes over both upload transports.

A multipart file passes when "size <= MAX_UPLOAD_SIZE". The base64 pre-check used
"len(data) * 3 // 4", which ignores "=" padding and over-counts by up to two
bytes, so a file of exactly MAX_UPLOAD_SIZE bytes was refused when sent as
base64 but accepted as multipart.
"""

from __future__ import annotations

import base64

from django.contrib.auth.models import AnonymousUser
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import RequestFactory, SimpleTestCase, override_settings
from graphql import GraphQLError

from django_graphex.uploads import decode_base64_file
from django_graphex.views import GraphQLView
from tests.cache_helpers import minimal_cache_schema

_LIMIT = 10


def _b64(size: int) -> dict[str, str]:
    """Build a base64 payload dict for a file of the given size.

    Args:
        size: Decoded size in bytes.

    Returns:
        The payload accepted by decode_base64_file.
    """
    return {
        "filename": "a.bin",
        "data": base64.b64encode(b"x" * size).decode(),
    }


def _multipart_status(size: int) -> int:
    """POST a multipart file of the given size and return the HTTP status.

    Args:
        size: File size in bytes.

    Returns:
        The response status code.
    """
    request = RequestFactory().post(
        "/g/",
        data={"query": "{ hello }", "f": SimpleUploadedFile("a.bin", b"x" * size)},
        HTTP_X_REQUESTED_WITH="XMLHttpRequest",
    )
    request.user = AnonymousUser()
    view = GraphQLView.as_view(schema=minimal_cache_schema)
    return view(request).status_code


@override_settings(DJANGO_GRAPHEX={"MAX_UPLOAD_SIZE": _LIMIT})
class UploadSizeBoundaryTests(SimpleTestCase):
    """Limit minus one, the limit and limit plus one behave alike on both paths.

    The limit is the largest accepted size, whatever the transport.
    """

    def test_base64_boundary(self) -> None:
        """Base64 accepts up to the limit and refuses one byte beyond it.

        Every padding shape is covered by sweeping the limit across a full
        3-byte group.
        """
        for limit in range(_LIMIT, _LIMIT + 3):
            with override_settings(DJANGO_GRAPHEX={"MAX_UPLOAD_SIZE": limit}):
                for size in (limit - 1, limit):
                    with self.subTest(limit=limit, size=size):
                        file = decode_base64_file(_b64(size))
                        self.assertEqual(file.size, size)
                with self.subTest(limit=limit, size=limit + 1):
                    with self.assertRaises(GraphQLError):
                        decode_base64_file(_b64(limit + 1))

    def test_multipart_boundary(self) -> None:
        """Multipart accepts the limit and refuses one byte beyond it.

        This is the reference behavior the base64 path must match.
        """
        self.assertEqual(_multipart_status(_LIMIT - 1), 200)
        self.assertEqual(_multipart_status(_LIMIT), 200)
        self.assertEqual(_multipart_status(_LIMIT + 1), 413)
