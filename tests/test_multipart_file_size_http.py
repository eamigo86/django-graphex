"""Public HTTP checks for the configured multipart per-file size limit."""

from __future__ import annotations

import json
from typing import Any
from unittest.mock import patch

import pytest
from django.contrib.auth.models import AnonymousUser
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import RequestFactory, override_settings
from graphql import GraphQLString

from django_graphex.core import ObjectType, field
from django_graphex.schema import DjangoGraphQLSchema
from django_graphex.views import BaseGraphQLView, GraphQLView


@pytest.mark.parametrize("view_class", [BaseGraphQLView, GraphQLView])
@override_settings(DJANGO_GRAPHEX={"MAX_UPLOAD_SIZE": 3})
def test_oversized_multipart_file_is_rejected_before_resolver(view_class: type) -> None:
    """Reject an oversized received part even when the query never names it.

    Args:
        view_class: Public HTTP view under test.
    """
    calls: list[str] = []

    def resolve_hello(root: Any, info: Any) -> str:
        calls.append("hello")
        return "world"

    class Query(ObjectType):
        hello = field(GraphQLString, resolver=resolve_hello)

    schema = DjangoGraphQLSchema(query=Query)
    request = RequestFactory().post(
        "/graphql/",
        data={
            "query": "{ hello }",
            "unused": SimpleUploadedFile("oversized.txt", b"four"),
        },
        HTTP_X_REQUESTED_WITH="XMLHttpRequest",
    )
    request.user = AnonymousUser()
    response = view_class.as_view(schema=schema)(request)
    payload = json.loads(response.content)
    assert response.status_code == 413, payload
    assert "MAX_UPLOAD_SIZE" in payload["errors"][0]["message"]
    assert "3" in payload["errors"][0]["message"]
    assert calls == []


def _post_multipart(
    view_class: type,
    files: dict[str, SimpleUploadedFile | list[SimpleUploadedFile]],
    *,
    cap: int | None,
    batch: bool = False,
    graphiql: bool = False,
    cache_active: bool = False,
    accept_html: bool = False,
    body_cap: int | None = None,
) -> tuple[int, bytes, list[str]]:
    """Send multipart parts through a public view and close parsed uploads.

    Args:
        view_class: Public HTTP view under test.
        files: Named received file parts, including repeated-name lists.
        cap: Per-file upload limit.
        batch: Whether to use the batch endpoint.
        graphiql: Whether the view can render GraphiQL.
        cache_active: Whether the enhanced response cache is enabled.
        accept_html: Whether the client prefers HTML.
        body_cap: Independent total request-body limit.

    Returns:
        HTTP status, response body, and resolver invocation log.
    """
    calls: list[str] = []

    def resolve_hello(root: Any, info: Any) -> str:
        calls.append("hello")
        return "world"

    class Query(ObjectType):
        hello = field(GraphQLString, resolver=resolve_hello)

    schema = DjangoGraphQLSchema(query=Query)
    request = RequestFactory().post(
        "/graphql/",
        data={"query": "{ hello }", **files},
        HTTP_X_REQUESTED_WITH="XMLHttpRequest",
        HTTP_ACCEPT="text/html" if accept_html else "application/json",
    )
    request.user = AnonymousUser()
    settings = {
        "MAX_UPLOAD_SIZE": cap,
        "MAX_REQUEST_BODY_SIZE": body_cap,
        "CACHE_ACTIVE": cache_active,
    }
    try:
        with override_settings(DJANGO_GRAPHEX=settings):
            response = view_class.as_view(
                schema=schema, batch=batch, graphiql=graphiql
            )(request)
        return response.status_code, response.content, calls
    finally:
        for _, received in request.FILES.lists():
            for uploaded_file in received:
                uploaded_file.close()


def _file(name: str, content: bytes) -> SimpleUploadedFile:
    """Create one in-memory uploaded file part.

    Args:
        name: Client-supplied filename.
        content: File bytes.

    Returns:
        The upload part.
    """
    return SimpleUploadedFile(name, content)


@pytest.mark.parametrize("view_class", [BaseGraphQLView, GraphQLView])
@pytest.mark.parametrize(
    "size,cap,expected", [(2, 3, 200), (3, 3, 200), (4, 3, 413), (4, None, 200)]
)
def test_single_file_boundary_and_uncapped_mode(
    view_class: type, size: int, cap: int | None, expected: int
) -> None:
    """Apply the cap per file and keep None uncapped.

    Args:
        view_class: Public view under test.
        size: Received file size.
        cap: Configured per-file size limit.
        expected: Expected HTTP status.
    """
    status, body, calls = _post_multipart(
        view_class, {"unused": _file("one.bin", b"x" * size)}, cap=cap
    )
    assert status == expected, body
    assert calls == ([] if expected == 413 else ["hello"])


@pytest.mark.parametrize("oversize_first", [True, False])
def test_every_repeated_file_is_checked(oversize_first: bool) -> None:
    """Reject either oversized position under one multipart field name.

    Args:
        oversize_first: Whether the oversized file occurs first.
    """
    parts = [_file("small.bin", b"xx"), _file("large.bin", b"xxxx")]
    if oversize_first:
        parts.reverse()
    status, body, calls = _post_multipart(GraphQLView, {"unused": parts}, cap=3)
    assert status == 413, body
    assert calls == []
    message = json.loads(body)["errors"][0]["message"]
    assert "MAX_UPLOAD_SIZE" in message and "3" in message
    assert "small.bin" not in message and "large.bin" not in message


def test_multiple_files_are_not_summed() -> None:
    """Allow separate files whose aggregate exceeds the per-file cap."""
    status, body, calls = _post_multipart(
        GraphQLView,
        {"first": _file("a.bin", b"xx"), "second": _file("b.bin", b"xx")},
        cap=3,
    )
    assert status == 200, body
    assert calls == ["hello"]


@pytest.mark.parametrize("view_class", [BaseGraphQLView, GraphQLView])
def test_malformed_multipart_batch_keeps_400_before_file_cap(view_class: type) -> None:
    """Preserve the preexisting invalid-batch response priority.

    Args:
        view_class: Public view under test.
    """
    status, body, calls = _post_multipart(
        view_class, {"unused": _file("large.bin", b"xxxx")}, cap=3, batch=True
    )
    assert status == 400, body
    assert calls == []
    assert (
        "Batch requests should receive a list"
        in json.loads(body)["errors"][0]["message"]
    )


@pytest.mark.parametrize("view_class", [BaseGraphQLView, GraphQLView])
def test_graphiql_success_path_still_checks_files(view_class: type) -> None:
    """Do not render HTML when a received multipart file is over the cap.

    Args:
        view_class: Public view under test.
    """
    status, body, calls = _post_multipart(
        view_class,
        {"unused": _file("large.bin", b"xxxx")},
        cap=3,
        graphiql=True,
        accept_html=True,
    )
    assert status == 413, body
    assert calls == []
    assert "MAX_UPLOAD_SIZE" in json.loads(body)["errors"][0]["message"]


def test_cache_active_multipart_cannot_bypass_file_cap() -> None:
    """Reject the upload on the enhanced view's uncached multipart path."""
    status, body, calls = _post_multipart(
        GraphQLView,
        {"unused": _file("large.bin", b"xxxx")},
        cap=3,
        cache_active=True,
    )
    assert status == 413, body
    assert calls == []


def test_independent_total_body_cap_still_rejects_first() -> None:
    """Retain the earlier total-body guard when the file itself fits."""
    status, body, calls = _post_multipart(
        GraphQLView,
        {"unused": _file("small.bin", b"xx")},
        cap=3,
        body_cap=10,
    )
    assert status == 413, body
    assert calls == []
    message = json.loads(body)["errors"][0]["message"]
    assert "MAX_REQUEST_BODY_SIZE" in message


def test_temporary_uploaded_file_is_rejected_and_closed() -> None:
    """Check a disk-spooled Django upload without leaving its temp file open."""
    from django.core.files.uploadedfile import TemporaryUploadedFile

    calls: list[str] = []

    def resolve_hello(root: Any, info: Any) -> str:
        calls.append("hello")
        return "world"

    class Query(ObjectType):
        hello = field(GraphQLString, resolver=resolve_hello)

    request = RequestFactory().post(
        "/graphql/",
        data={"query": "{ hello }", "unused": _file("temp.bin", b"four")},
        HTTP_X_REQUESTED_WITH="XMLHttpRequest",
    )
    request.user = AnonymousUser()
    try:
        with override_settings(
            FILE_UPLOAD_MAX_MEMORY_SIZE=1, DJANGO_GRAPHEX={"MAX_UPLOAD_SIZE": 3}
        ):
            response = BaseGraphQLView.as_view(schema=DjangoGraphQLSchema(query=Query))(
                request
            )
        assert response.status_code == 413
        assert calls == []
        assert isinstance(request.FILES["unused"], TemporaryUploadedFile)
    finally:
        for _, received in request.FILES.lists():
            for uploaded_file in received:
                uploaded_file.close()


def test_csrf_header_refusal_precedes_file_cap() -> None:
    """Retain the existing cross-site POST refusal before parsing files."""

    class Query(ObjectType):
        hello = field(GraphQLString)

    request = RequestFactory().post(
        "/graphql/",
        data={"query": "{ hello }", "unused": _file("large.bin", b"four")},
    )
    request.user = AnonymousUser()
    with override_settings(DJANGO_GRAPHEX={"MAX_UPLOAD_SIZE": 3}):
        response = BaseGraphQLView.as_view(schema=DjangoGraphQLSchema(query=Query))(
            request
        )
    assert response.status_code == 403
    assert "MAX_UPLOAD_SIZE" not in response.content.decode()


def test_oversized_file_prevents_mutation_resolver() -> None:
    """Reject the multipart request before a mutation's write-like action."""
    from graphql import GraphQLBoolean

    from django_graphex.core import Mutation

    writes: list[str] = []

    class Query(ObjectType):
        hello = field(GraphQLString)

    class Write(Mutation):
        ok = field(GraphQLBoolean)

        @classmethod
        def mutate(cls, root: Any, info: Any) -> "Write":
            """Record a would-be write if execution reaches the resolver.

            Args:
                root: Unused parent value.
                info: GraphQL execution context.

            Returns:
                Successful mutation payload.
            """
            writes.append("write")
            return cls(ok=True)

    class MutationRoot(ObjectType):
        write = Write.Field()

    schema = DjangoGraphQLSchema(query=Query, mutation=MutationRoot)
    request = RequestFactory().post(
        "/graphql/",
        data={
            "query": "mutation { write { ok } }",
            "unused": _file("large.bin", b"four"),
        },
        HTTP_X_REQUESTED_WITH="XMLHttpRequest",
    )
    request.user = AnonymousUser()
    try:
        with (
            override_settings(
                DJANGO_GRAPHEX={"MAX_UPLOAD_SIZE": 3, "CACHE_ACTIVE": True}
            ),
            patch.object(GraphQLView, "_bump_cache_version") as bump_version,
        ):
            response = GraphQLView.as_view(schema=schema)(request)
        assert response.status_code == 413
        assert writes == []
        bump_version.assert_not_called()
    finally:
        for _, received in request.FILES.lists():
            for uploaded_file in received:
                uploaded_file.close()
