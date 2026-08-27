# -*- coding: utf-8 -*-
"""The body-size guard must bound a multipart POST on ASGI as well as WSGI.

"BaseGraphQLView.dispatch" checks "MAX_REQUEST_BODY_SIZE" in two stages: a fast
reject on a declared "Content-Length" above the cap, then an authoritative
measurement of the body itself. Stage 1 compares the cap against a number the
CLIENT chose, so on its own it bounds nothing.

Stage 2 cannot measure multipart by reading it — that breaks the streamed upload
and collides with the CSRF check — so it measures "request._stream" by seeking to
the end and back. The two servers give two different streams, and the difference
is exactly the one that matters:

- ASGI hands over a "SpooledTemporaryFile". "ASGIHandler.read_body" already
  spooled every chunk with no "CONTENT_LENGTH" cap and "ASGIRequest.__init__"
  assigns that spool straight to "self._stream", so nothing downstream re-imposes
  the declared length: "MultiPartParser" builds its "ChunkIter" from
  "_chunk_size" and consults "_content_length" only to shortcut a ZERO-length
  body. A non-zero lie skips the shortcut and the parser drains the whole spool.
  The spool is seekable, so its true size is one seek away.
- WSGI hands over a "LimitedStream" capped at "CONTENT_LENGTH", which is not
  seekable and does not need to be: an under-declared length truncates the body
  it is lying about. Only an ABSENT length is left unbounded, and "WSGIRequest"
  turns that into a limit of zero.

Reception itself is never bounded here: under ASGI the bytes are on disk before
the view exists. This is a refusal to PROCESS.

Invariants asserted here:

- A multipart POST that UNDER-DECLARES its "Content-Length" is refused (HTTP 413)
  on ASGI, and truncated before it reaches the view on WSGI.
- A multipart POST whose length is neither declared nor measurable is refused
  (HTTP 411), which is the WSGI chunked case.
- An honestly declared multipart body under the cap is untouched, including over
  a real "ASGIRequest".
- With the guard disabled ("MAX_REQUEST_BODY_SIZE" is None) no refusal fires: the
  guard exists to keep a CONFIGURED cap honest, not as a new requirement for
  projects that never opted in.
"""

from __future__ import annotations

import json
import tempfile
from io import BytesIO
from typing import Any

from django.contrib.auth.models import AnonymousUser
from django.core.handlers.asgi import ASGIRequest
from django.core.handlers.wsgi import LimitedStream
from django.test import RequestFactory, TestCase, override_settings

from django_graphex.views import GraphQLView
from tests.cache_helpers import minimal_cache_schema as _schema

#: Small enough that the oversized bodies below stay cheap to build.
_CAP = 1024

_GUARD_ON = {"DJANGO_GRAPHEX": {"MAX_REQUEST_BODY_SIZE": _CAP}}
_GUARD_OFF = {"DJANGO_GRAPHEX": {"MAX_REQUEST_BODY_SIZE": None}}

_BOUNDARY = "gdxBoUnDaRy"
_CONTENT_TYPE = f"multipart/form-data; boundary={_BOUNDARY}"


def _multipart_body(filler: int) -> bytes:
    """Return a valid multipart body carrying a query plus *filler* padding.

    Args:
        filler: How many padding bytes to append as a second part, used to push
            the body over the configured cap.

    Returns:
        The encoded multipart body.
    """
    return (
        f"--{_BOUNDARY}\r\n"
        'Content-Disposition: form-data; name="query"\r\n\r\n'
        "{ hello }\r\n"
        f"--{_BOUNDARY}\r\n"
        'Content-Disposition: form-data; name="padding"\r\n\r\n'
        f"{'x' * filler}\r\n"
        f"--{_BOUNDARY}--\r\n"
    ).encode()


def _asgi_request(
    body: bytes, declare_length: bool, declared: int | None = None
) -> ASGIRequest:
    """Build a real "ASGIRequest" over a spooled body, as the ASGI handler does.

    Mirrors "ASGIHandler.read_body" + "ASGIHandler.create_request": the body is
    a spooled temporary file assigned straight to "request._stream", with no
    "LimitedStream" and no "CONTENT_LENGTH" unless the client declared one.

    Args:
        body: The raw request body the ASGI server received.
        declare_length: Whether the client sent a "content-length" header. A
            chunked request sends none, which is the case with no cap at all.
        declared: The length to declare instead of the real one, used to build
            the spoofed-low case. Ignored when declare_length is False.

    Returns:
        The request, with an anonymous user already attached.
    """
    headers = [
        (b"content-type", _CONTENT_TYPE.encode()),
        # The cross-site POST guard demands this header on a multipart POST.
        (b"x-requested-with", b"XMLHttpRequest"),
    ]
    if declare_length:
        length = len(body) if declared is None else declared
        headers.append((b"content-length", str(length).encode()))
    body_file = tempfile.SpooledTemporaryFile(max_size=1024 * 1024, mode="w+b")
    body_file.write(body)
    body_file.seek(0)
    scope = {
        "type": "http",
        "http_version": "1.1",
        "method": "POST",
        "path": "/graphql/",
        "raw_path": b"/graphql/",
        "root_path": "",
        "scheme": "http",
        "query_string": b"",
        "headers": headers,
        "client": ("127.0.0.1", 12345),
        "server": ("testserver", 80),
    }
    request = ASGIRequest(scope, body_file)
    request.user = AnonymousUser()
    return request


def _wsgi_request(
    body: bytes, declare_length: bool, declared: int | None = None
) -> Any:
    """Build a multipart WSGI request, optionally without a "CONTENT_LENGTH".

    Args:
        body: The raw request body.
        declare_length: Whether to keep the "CONTENT_LENGTH" environ entry.
        declared: The length to declare instead of the real one, used to build
            the spoofed-low case. Ignored when declare_length is False.

    Returns:
        The request, with an anonymous user already attached.
    """
    request = RequestFactory().post(
        "/graphql/",
        data=body,
        content_type=_CONTENT_TYPE,
        HTTP_X_REQUESTED_WITH="XMLHttpRequest",
    )
    if not declare_length:
        # A chunked WSGI request arrives with no CONTENT_LENGTH at all.
        request.META.pop("CONTENT_LENGTH", None)
    elif declared is not None:
        # "WSGIRequest.__init__" already built the LimitedStream from the honest
        # length, so the spoof has to replace both it and the environ entry —
        # exactly what a real server does when it frames the request by the
        # header the client sent.
        request.META["CONTENT_LENGTH"] = str(declared)
        request._stream = LimitedStream(BytesIO(body), declared)
    request.user = AnonymousUser()
    return request


class UndeclaredMultipartLengthTest(TestCase):
    """A multipart body must not slip past the cap on the strength of its own
    declaration.

    Stage 1 only ever compares the cap against a number the client chose, so
    every case here is one where that number is absent or a lie.
    """

    def setUp(self) -> None:
        """Bind the view under test.

        The view is built per test so a settings override applies to the
        instance the test actually dispatches through.
        """
        self.view = GraphQLView.as_view(schema=_schema)

    @override_settings(**_GUARD_ON)
    def test_asgi_chunked_multipart_over_the_cap_is_refused(self) -> None:
        """Ships broken if an ASGI multipart POST that declares no length is
        admitted past the body-size guard.

        The ASGI handler already spooled the whole body with no
        "CONTENT_LENGTH" cap, so stage 1 has nothing to reject. Only Django's
        parser quirk keeps it from being processed, and the cap must not depend
        on that. The answer is 413 rather than 411 because the spool is
        seekable: the size is not unknowable here, it is known and too big.
        """
        body = _multipart_body(_CAP * 4)
        self.assertGreater(len(body), _CAP)
        response = self.view(_asgi_request(body, declare_length=False))

        self.assertEqual(
            response.status_code,
            413,
            f"An undeclared-length multipart body of {len(body)} bytes was "
            f"answered with HTTP {response.status_code} under a "
            f"MAX_REQUEST_BODY_SIZE of {_CAP} bytes; the guard never bounded it.",
        )

    @override_settings(**_GUARD_ON)
    def test_wsgi_undeclared_multipart_is_refused(self) -> None:
        """Ships broken if the WSGI arm answers an undeclared-length multipart
        POST with anything other than the same explicit refusal.

        Django truncates the body to nothing there, so the request was already
        doomed — but it failed as an opaque "must provide query string" 400
        instead of telling the client its length was the problem.
        """
        response = self.view(_wsgi_request(_multipart_body(0), declare_length=False))

        self.assertEqual(
            response.status_code,
            411,
            "The WSGI arm must refuse an undeclared-length multipart body the "
            f"same way the ASGI arm does; got HTTP {response.status_code}.",
        )

    @override_settings(**_GUARD_ON)
    def test_declared_multipart_under_the_cap_still_runs(self) -> None:
        """Ships broken if the refusal catches an honest multipart client.

        A declared length is not what bounds the body — only WSGI frames the
        request by it, and under ASGI the guard measures the spool itself. What
        it does buy an honest client is the fast-reject path in stage 1 and,
        under WSGI, an answer at all instead of the 411 an absent length earns.
        """
        response = self.view(_asgi_request(_multipart_body(0), declare_length=True))

        self.assertEqual(response.status_code, 200)
        self.assertEqual(json.loads(response.content)["data"]["hello"], "world")

    @override_settings(**_GUARD_ON)
    def test_asgi_spoofed_low_content_length_is_refused(self) -> None:
        """Ships broken if an ASGI multipart POST that UNDER-declares its
        "Content-Length" is answered with anything but a body-size refusal.

        This is the case a declared length was assumed to cover and does not.
        Stage 1 compares the cap against the client's own claim, so a claim
        below the cap sails through it; under ASGI nothing downstream re-imposes
        that claim, because "MultiPartParser" builds its "ChunkIter" from
        "_chunk_size" and consults "_content_length" only to shortcut a
        zero-length body. A non-zero lie therefore skips the shortcut and the
        parser drains the entire spool.
        """
        body = _multipart_body(_CAP * 4)
        self.assertGreater(len(body), _CAP)
        response = self.view(_asgi_request(body, declare_length=True, declared=100))

        self.assertEqual(
            response.status_code,
            413,
            f"A multipart body of {len(body)} bytes declaring only 100 was "
            f"answered with HTTP {response.status_code} under a "
            f"MAX_REQUEST_BODY_SIZE of {_CAP} bytes; the declared length was "
            "taken at face value and the real body was never measured.",
        )

    @override_settings(**_GUARD_ON)
    def test_wsgi_spoofed_low_content_length_never_reaches_the_view(self) -> None:
        """Ships broken if the WSGI arm lets an under-declared body through
        whole.

        WSGI is bounded without any help from this guard — "WSGIRequest" wraps
        the input in a "LimitedStream" capped at "CONTENT_LENGTH" — so the lie
        truncates the body it is lying about. Pinned because the ASGI fix must
        not be paid for by loosening the arm that was already correct.
        """
        padding = _CAP * 4
        request = _wsgi_request(
            _multipart_body(padding), declare_length=True, declared=100
        )
        self.view(request)

        self.assertLess(
            len(request.POST.get("padding", "")),
            padding,
            "The WSGI arm handed the view the full under-declared body; the "
            "LimitedStream that bounds it at CONTENT_LENGTH was bypassed.",
        )

    @override_settings(**_GUARD_ON)
    def test_asgi_undeclared_multipart_under_the_cap_is_not_a_length_refusal(
        self,
    ) -> None:
        """Ships broken if a chunked multipart body small enough to pass the cap
        is still refused for having no declared length.

        Once the body is measured directly, an absent "Content-Length" is no
        longer unknowable under ASGI, so the 411 has nothing left to say about
        it. What the request then meets is Django's own parser, which reports an
        empty payload with no "CONTENT_LENGTH" — a 400, not a size refusal.
        """
        response = self.view(_asgi_request(_multipart_body(0), declare_length=False))

        self.assertEqual(
            response.status_code,
            400,
            "A measurable under-cap chunked multipart body must fall through to "
            f"Django's own handling; got HTTP {response.status_code}.",
        )

    @override_settings(**_GUARD_OFF)
    def test_undeclared_multipart_is_untouched_when_the_guard_is_off(self) -> None:
        """Ships broken if the refusal fires with no cap configured.

        "MAX_REQUEST_BODY_SIZE" defaults to None; a project that never opted
        into the guard must keep whatever Django itself does with an undeclared
        length — which is the empty-payload 400, not a body-size refusal.
        """
        response = self.view(_asgi_request(_multipart_body(0), declare_length=False))

        self.assertNotEqual(
            response.status_code,
            411,
            "The undeclared-length refusal fired with MAX_REQUEST_BODY_SIZE "
            "unset; it must only enforce a cap the project actually configured.",
        )
