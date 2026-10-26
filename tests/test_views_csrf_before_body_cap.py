# -*- coding: utf-8 -*-
"""The body cap must refuse an oversized multipart POST before CSRF reads it.

Django's CSRF check reads "request.POST" whenever the client holds a "csrftoken"
cookie, and for multipart that parses the body and spools its files to disk. The
cap used to run inside "dispatch", behind that check, so a cookie-bearing client
paid for a parse the 413 was meant to prevent. The cap now runs in "as_view",
ahead of every dispatch.
"""

from __future__ import annotations

from unittest.mock import patch

from django.contrib.auth.models import AnonymousUser
from django.core.files.uploadedfile import SimpleUploadedFile
from django.http.multipartparser import MultiPartParser
from django.test import RequestFactory, TestCase, override_settings

from django_graphex.views import BaseGraphQLView, GraphQLView
from tests.cache_helpers import minimal_cache_schema as _schema

_CAP = 1000


def _post(payload_size: int, cookie: bool, csrf_header: bool = True) -> object:
    """Build a multipart POST carrying a file of the given size.

    Args:
        payload_size: Size in bytes of the attached file.
        cookie: Whether to attach a csrftoken cookie.
        csrf_header: Whether to send the cross-site guard header.

    Returns:
        The request.
    """
    extra = {"HTTP_X_REQUESTED_WITH": "XMLHttpRequest"} if csrf_header else {}
    request = RequestFactory().post(
        "/g/",
        data={
            "query": "{ hello }",
            "f": SimpleUploadedFile("a.bin", b"x" * payload_size),
        },
        **extra,
    )
    request.user = AnonymousUser()
    request._dont_enforce_csrf_checks = False
    if cookie:
        request.COOKIES["csrftoken"] = "a" * 32
    return request


@override_settings(DJANGO_GRAPHEX={"MAX_REQUEST_BODY_SIZE": _CAP})
class CsrfBeforeBodyCapTests(TestCase):
    """Oversized multipart is refused before any parse, cookie or not.

    The cap must come first, and CSRF semantics must not change under it.
    """

    def _call(self, view_class: type, request: object) -> tuple[int, int]:
        """Run the view and return its status and the multipart parse count.

        Args:
            view_class: The view class to build.
            request: The request to dispatch.

        Returns:
            The response status and the number of multipart parser calls.
        """
        with patch.object(
            MultiPartParser, "parse", autospec=True, side_effect=MultiPartParser.parse
        ) as spy:
            response = view_class.as_view(schema=_schema)(request)
        return response.status_code, spy.call_count

    def test_oversized_never_parsed(self) -> None:
        """Over the cap: 413 and the multipart parser is never called.

        Asserts the behavior named above.
        """
        for view_class in (BaseGraphQLView, GraphQLView):
            for cookie in (False, True):
                with self.subTest(view=view_class.__name__, cookie=cookie):
                    status, parses = self._call(view_class, _post(5000, cookie))
                    self.assertEqual(status, 413)
                    self.assertEqual(parses, 0)

    def test_under_cap_still_served(self) -> None:
        """Under the cap the request is served, cookie or not.

        Asserts the behavior named above.
        """
        for view_class in (BaseGraphQLView, GraphQLView):
            for cookie in (False, True):
                with self.subTest(view=view_class.__name__, cookie=cookie):
                    status, _ = self._call(view_class, _post(10, cookie))
                    self.assertIn(status, (200, 403))

    def test_csrf_403_unchanged_under_cap(self) -> None:
        """A header-less cross-site multipart POST still gets 403 under the cap.

        Asserts the behavior named above.
        """
        for view_class in (BaseGraphQLView, GraphQLView):
            with self.subTest(view=view_class.__name__):
                status, _ = self._call(view_class, _post(10, True, csrf_header=False))
                self.assertEqual(status, 403)
