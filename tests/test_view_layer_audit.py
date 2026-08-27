# -*- coding: utf-8 -*-
"""Regression tests for the post-2.2.0 view-layer audit.

Each class below pins one defect found in "django_graphex.views":

(1) "MAX_REQUEST_BODY_SIZE" turned every multipart POST that carried a
    "csrftoken" cookie into an unhandled "RawPostDataException": the
    "@ensure_csrf_cookie" decorator on "dispatch" runs the full CSRF token
    check, which reads "request.POST" and drains the multipart stream before
    "dispatch" ever reaches "len(request.body)".
(2) The same "len(request.body)" call subjected multipart bodies to Django's
    "DATA_UPLOAD_MAX_MEMORY_SIZE", which streaming multipart otherwise escapes.
(3) "DOCUMENT_CACHE_MAXSIZE=None" raised "TypeError" from "int(None)" on every
    request, even though "None" means "unbounded" for every sibling limit.
(4) A deeply nested JSON body raised "RecursionError" out of "json.loads",
    which the "except (TypeError, ValueError)" handler did not catch.
(5) Under "CACHE_ACTIVE" a non-string "query", or a query holding a deeply
    nested inline literal, escaped the "except GraphQLSyntaxError" handler in
    "get_operation_ast".
(6) An "application/graphql" body that is not valid UTF-8 raised
    "UnicodeDecodeError" out of "request.body.decode()".

The multipart tests deliberately drive the view through "RequestFactory" rather
than Django's test "Client": the client sets "_dont_enforce_csrf_checks", which
makes "CsrfViewMiddleware.process_view" return before it ever touches
"request.POST" — so a client-based test cannot observe defect (1) at all.
"""

import json
from typing import Any

from django.contrib.auth.models import AnonymousUser
from django.core.cache import cache
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import RequestFactory, TestCase, override_settings

from django_graphex.views import GraphQLView
from tests.cache_helpers import CACHE_ON
from tests.cache_helpers import minimal_cache_schema as _schema

#: A body-size cap large enough that nothing in this module trips it by accident.
_BODY_CAP = {"DJANGO_GRAPHEX": {"MAX_REQUEST_BODY_SIZE": 20 * 1024 * 1024}}

#: Django's own default in-memory ceiling, pinned so the tests do not silently
#: change meaning if the harness ever configures a different value.
_DATA_UPLOAD_DEFAULT = 2621440

#: Payload that is comfortably above "_DATA_UPLOAD_DEFAULT" and comfortably
#: below the 20 MB body cap, so only the defect under test can reject it.
_THREE_MB = b"x" * (3 * 1024 * 1024)


def _multipart_request(factory: RequestFactory, **extra: object) -> Any:
    """Build a multipart GraphQL POST carrying the cross-site guard header.

    Args:
        factory: The request factory used to encode the multipart body.
        **extra: Extra WSGI environ entries merged over the encoded request.

    Returns:
        The multipart request, with an anonymous user already attached.
    """
    request = factory.post(
        "/graphql/",
        data={"query": "{ hello }"},
        HTTP_X_REQUESTED_WITH="XMLHttpRequest",
        **extra,
    )
    request.user = AnonymousUser()
    return request


class MultipartBodyGuardTest(TestCase):
    """The body-size guard must never break an otherwise valid multipart POST.

    Covers audit findings (1) and (2): the guard has to keep rejecting an
    honestly oversized body while leaving the multipart stream alone.
    """

    def setUp(self) -> None:
        """Build a fresh factory and bind the view under test.

        A new factory per test keeps the cookie jar of one test out of the
        next one.
        """
        self.factory = RequestFactory()
        self.view = GraphQLView.as_view(schema=_schema)

    @override_settings(**_BODY_CAP)
    def test_multipart_post_with_csrf_cookie_is_not_a_500(self) -> None:
        """A multipart POST that carries a "csrftoken" cookie MUST still answer 200.

        The endpoint plants that cookie on every response, so the FIRST
        multipart POST from a fresh client used to work and every one after it
        raised "RawPostDataException" from "len(request.body)".
        """
        # A 32-character token is what "_sanitize_token" accepts as a raw CSRF
        # secret; anything malformed makes Django bail out before it reads
        # request.POST, which would hide the defect.
        self.factory.cookies["csrftoken"] = "a" * 32
        response = self.view(_multipart_request(self.factory))
        self.assertEqual(
            response.status_code,
            200,
            "A multipart POST with a csrftoken cookie and MAX_REQUEST_BODY_SIZE "
            f"set returned {response.status_code}; the body guard read "
            "request.body after the CSRF check already drained the stream.",
        )
        self.assertEqual(json.loads(response.content)["data"]["hello"], "world")

    @override_settings(DATA_UPLOAD_MAX_MEMORY_SIZE=_DATA_UPLOAD_DEFAULT, **_BODY_CAP)
    def test_multipart_upload_above_data_upload_max_memory_size_is_accepted(
        self,
    ) -> None:
        """A 3 MB multipart upload MUST pass with the 20 MB cap configured.

        Multipart streams to disk and so escapes "DATA_UPLOAD_MAX_MEMORY_SIZE"
        entirely; reading "request.body" in the guard dragged it back under that
        ceiling and turned the upload into an opaque Django 400.
        """
        request = self.factory.post(
            "/graphql/",
            data={
                "query": "{ hello }",
                "attachment": SimpleUploadedFile("big.bin", _THREE_MB),
            },
            HTTP_X_REQUESTED_WITH="XMLHttpRequest",
        )
        request.user = AnonymousUser()
        response = self.view(request)
        self.assertEqual(
            response.status_code,
            200,
            "A 3 MB multipart upload was rejected below the 20 MB body cap; the "
            "guard pulled the streamed body into memory.",
        )

    @override_settings(DJANGO_GRAPHEX={"MAX_REQUEST_BODY_SIZE": 1024})
    def test_honest_oversized_multipart_body_still_gets_413(self) -> None:
        """An honest oversized multipart body MUST still be refused with HTTP 413.

        This is the half of the guard that must survive the fix: stage 1 reads
        the declared "Content-Length" and rejects before anything is buffered.
        """
        request = self.factory.post(
            "/graphql/",
            data={
                "query": "{ hello }",
                "attachment": SimpleUploadedFile("big.bin", _THREE_MB),
            },
            HTTP_X_REQUESTED_WITH="XMLHttpRequest",
        )
        request.user = AnonymousUser()
        response = self.view(request)
        self.assertEqual(response.status_code, 413)

    @override_settings(**_BODY_CAP)
    def test_spoofed_low_content_length_cannot_over_allocate(self) -> None:
        """A spoofed-low "Content-Length" MUST NOT let extra bytes be read.

        This is what makes stage 1 sufficient for multipart: Django wraps the
        input in a "LimitedStream" bounded by "CONTENT_LENGTH", so a client that
        under-declares its body simply cannot get more than the declared number
        of bytes past the WSGI layer, whatever the guard does.
        """
        request = self.factory.post(
            "/graphql/",
            data={
                "query": "{ hello }",
                "attachment": SimpleUploadedFile("big.bin", _THREE_MB),
            },
            HTTP_X_REQUESTED_WITH="XMLHttpRequest",
            CONTENT_LENGTH="10",
        )
        self.assertEqual(
            len(request.read()),
            10,
            "The request stream handed out more bytes than CONTENT_LENGTH "
            "declared; the body guard can no longer rely on stage 1 alone.",
        )

    @override_settings(**_BODY_CAP)
    def test_spoofed_low_content_length_request_is_answered_not_crashed(self) -> None:
        """A truncated multipart body MUST produce an error response, not a 500.

        The truncated stream cannot be parsed into form data, so the view has no
        query to run — but it must say so through the normal error envelope.
        """
        request = self.factory.post(
            "/graphql/",
            data={
                "query": "{ hello }",
                "attachment": SimpleUploadedFile("big.bin", _THREE_MB),
            },
            HTTP_X_REQUESTED_WITH="XMLHttpRequest",
            CONTENT_LENGTH="10",
        )
        request.user = AnonymousUser()
        response = self.view(request)
        self.assertEqual(response.status_code, 400)

    @override_settings(**_BODY_CAP)
    def test_form_encoded_post_with_csrf_cookie_is_still_measured(self) -> None:
        """A form-encoded POST MUST keep its measured stage-2 check and answer 200.

        Only multipart skips stage 2. Django parses a form-encoded body through
        "request.body", which caches it, so the CSRF check does not strand the
        stream and the guard can still weigh the real bytes.
        """
        self.factory.cookies["csrftoken"] = "a" * 32
        request = self.factory.post(
            "/graphql/",
            data="query=%7B+hello+%7D",
            content_type="application/x-www-form-urlencoded",
            HTTP_X_REQUESTED_WITH="XMLHttpRequest",
        )
        request.user = AnonymousUser()
        response = self.view(request)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(json.loads(response.content)["data"]["hello"], "world")

    @override_settings(DJANGO_GRAPHEX={"MAX_REQUEST_BODY_SIZE": 8})
    def test_form_encoded_body_over_the_cap_still_gets_413(self) -> None:
        """A form-encoded body past the cap MUST still be refused with HTTP 413.

        Regression guard: the multipart exemption must not have widened into
        the other CORS-simple content type.
        """
        request = self.factory.post(
            "/graphql/",
            data="query=%7B+hello+%7D",
            content_type="application/x-www-form-urlencoded",
            HTTP_X_REQUESTED_WITH="XMLHttpRequest",
        )
        request.user = AnonymousUser()
        response = self.view(request)
        self.assertEqual(response.status_code, 413)


class DocumentCacheMaxsizeNoneTest(TestCase):
    """ "DOCUMENT_CACHE_MAXSIZE=None" must mean unbounded, not "break every request".

    Covers audit finding (3). "None" is the documented "no limit" value for
    every sibling bound in the namespace ("MAX_BATCH_SIZE",
    "MAX_REQUEST_BODY_SIZE", "MAX_QUERY_DEPTH", "MAX_PAGE_SIZE"), so it must not
    be the one value that takes the endpoint down.
    """

    def setUp(self) -> None:
        """Build a fresh factory and bind the view under test.

        Keeps each test's request construction independent of the others.
        """
        self.factory = RequestFactory()
        self.view = GraphQLView.as_view(schema=_schema)

    @override_settings(DJANGO_GRAPHEX={"DOCUMENT_CACHE_MAXSIZE": None})
    def test_none_maxsize_serves_the_query(self) -> None:
        """A plain query MUST succeed with "DOCUMENT_CACHE_MAXSIZE=None".

        The old "int(None)" raised "TypeError" inside "cached_parse", which the
        execution path turned into a 400 carrying the leaked exception text.
        """
        request = self.factory.post(
            "/graphql/",
            json.dumps({"query": "{ hello }"}),
            content_type="application/json",
        )
        request.user = AnonymousUser()
        response = self.view(request)
        self.assertEqual(
            response.status_code,
            200,
            f"DOCUMENT_CACHE_MAXSIZE=None returned {response.status_code}: "
            f"{response.content!r}",
        )
        self.assertEqual(json.loads(response.content)["data"]["hello"], "world")

    @override_settings(DJANGO_GRAPHEX={"DOCUMENT_CACHE_MAXSIZE": None})
    def test_none_maxsize_still_memoizes_the_document(self) -> None:
        """ "None" MUST leave the document cache enabled, not silently disabled.

        Unbounded is the documented meaning of "None"; mapping it to "0" would
        quietly turn the parse/validate memoization off instead.
        """
        from django_graphex.views import _PARSE_CACHE, cached_parse

        cached_parse("{ hello }")
        self.assertIn("{ hello }", _PARSE_CACHE)


class DeeplyNestedJsonBodyTest(TestCase):
    """A deeply nested JSON body must be a 400, not an unhandled "RecursionError".

    Covers audit finding (4).
    """

    def setUp(self) -> None:
        """Build a fresh factory and bind the view under test.

        Keeps each test's request construction independent of the others.
        """
        self.factory = RequestFactory()
        self.view = GraphQLView.as_view(schema=_schema)

    def test_deeply_nested_json_body_returns_400(self) -> None:
        """A 20 KB body of nested arrays MUST be refused with HTTP 400.

        "json.loads" raises "RecursionError", which is not a "ValueError", so
        the existing "except (TypeError, ValueError)" handler let it escape into
        an unhandled 500.
        """
        body = '{"query": "{ hello }", "variables": ' + "[" * 10000 + "]" * 10000 + "}"
        request = self.factory.post("/graphql/", body, content_type="application/json")
        request.user = AnonymousUser()
        response = self.view(request)
        self.assertEqual(response.status_code, 400)


@override_settings(**CACHE_ON)
class CachedOperationAstTest(TestCase):
    """ "get_operation_ast" must not 500 on a body it cannot parse.

    Covers audit finding (5). The sibling call site in
    "execute_graphql_request" already catches every exception from
    "cached_parse"; the cache pre-parse caught only "GraphQLSyntaxError".
    """

    def setUp(self) -> None:
        """Clear the cache, build a fresh factory, and bind the view.

        The response cache is process-global, so it has to be emptied before
        each test that turns "CACHE_ACTIVE" on.
        """
        cache.clear()
        self.factory = RequestFactory()
        self.view = GraphQLView.as_view(schema=_schema)

    def _post(self, body: str) -> Any:
        """Build an anonymous JSON POST carrying the given raw body.

        Args:
            body: The raw JSON text to send as the request body.

        Returns:
            The request, with an anonymous user already attached.
        """
        request = self.factory.post("/graphql/", body, content_type="application/json")
        request.user = AnonymousUser()
        return request

    def test_non_string_query_returns_400(self) -> None:
        """A JSON body whose "query" is a number MUST be refused with HTTP 400.

        "parse" raises "TypeError" for a non-string source, which escaped the
        "except GraphQLSyntaxError" handler and became a 500.
        """
        response = self.view(self._post(json.dumps({"query": 123})))
        self.assertEqual(response.status_code, 400)

    def test_deeply_nested_inline_literal_returns_400(self) -> None:
        """A query holding a deeply nested inline literal MUST answer HTTP 400.

        The GraphQL parser recurses over the literal and raises
        "RecursionError", which is not a "GraphQLSyntaxError".
        """
        nested = "[" * 5000 + "]" * 5000
        query = "{ hello(arg: " + nested + ") }"
        response = self.view(self._post(json.dumps({"query": query})))
        self.assertEqual(response.status_code, 400)


class GraphqlContentTypeDecodeTest(TestCase):
    """An "application/graphql" body must be decoded defensively.

    Covers audit finding (6): the neighbouring "application/json" branch already
    guards its "decode", this one did not.
    """

    def setUp(self) -> None:
        """Build a fresh factory and bind the view under test.

        Keeps each test's request construction independent of the others.
        """
        self.factory = RequestFactory()
        self.view = GraphQLView.as_view(schema=_schema)

    def test_non_utf8_graphql_body_returns_400(self) -> None:
        """A non-UTF-8 "application/graphql" body MUST be refused with HTTP 400.

        "request.body.decode()" raised "UnicodeDecodeError" straight out of
        "parse_body", past the "except HttpError" handler in "dispatch".
        """
        request = self.factory.post(
            "/graphql/", b"\xff\xfe{ hello }", content_type="application/graphql"
        )
        request.user = AnonymousUser()
        response = self.view(request)
        self.assertEqual(response.status_code, 400)
