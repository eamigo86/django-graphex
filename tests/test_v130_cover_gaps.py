# -*- coding: utf-8 -*-
"""Close v1.3.0 patch-coverage gaps (PR #77).

Covers:
- filtering/filter_field.py:114  — ``if value is None: continue`` when a
  @filter_field arg is not supplied in the query (getattr returns None).
- types.py:896-897              — ``raise ImproperlyConfigured`` for a
  @filter_field name colliding with a reserved arg on ``DjangoModelType``.
- uploads.py:217-218            — ``except UnicodeDecodeError`` is genuinely
  unreachable: base64.b64decode(str, validate=True) can only raise
  binascii.Error or ValueError for str inputs; it never raises
  UnicodeDecodeError because it decodes B64-encoded bytes into raw bytes
  without performing any str-level decoding. Marked # pragma: no cover.
- views.py:279-280              — ``except (ValueError, TypeError): content_length
  = len(request.body)`` fallback when CONTENT_LENGTH META is absent or
  non-numeric.
"""

from __future__ import annotations

import json

import pytest
from django.core.exceptions import ImproperlyConfigured
from django.db import models
from django.test import RequestFactory, TestCase, override_settings
from graphql import GraphQLInt, GraphQLString

from django_graphex import (
    DjangoGraphQLSchema,
    DjangoObjectType,
    ObjectType,
    field,
    filter_field,
)
from django_graphex.filtering.filter_field import apply_custom_filters
from django_graphex.registry import Registry
from django_graphex.types import DjangoModelType

from .models import Author, Post

# ---------------------------------------------------------------------------
# Shared proxy model (same DB table as Post) for filter_field isolation.
# Reuses the same approach as test_filter_field.py.
# ---------------------------------------------------------------------------


class _GapFilterPost(models.Model):
    """Lightweight stand-in for Post; shares the DB table via proxy."""

    title = models.CharField(max_length=200)
    body = models.TextField(default="")
    author = models.ForeignKey(
        Author, related_name="gap_posts", on_delete=models.CASCADE
    )
    views = models.PositiveIntegerField(default=0)

    class Meta:
        app_label = "tests"
        db_table = "tests_post"
        managed = False


# ---------------------------------------------------------------------------
# 1. filter_field.py:114 — ``if value is None: continue``
#    A query that does NOT pass the @filter_field argument → the arg is
#    absent from filter_value → getattr returns None → continue is taken →
#    the queryset is returned unchanged without error.
# ---------------------------------------------------------------------------


_SKIP_ARG_REGISTRY = Registry()


class _SkipArgType(DjangoObjectType):
    """Has two @filter_field methods; query supplies only one."""

    class Meta:
        model = _GapFilterPost
        filter_fields = {"title": ("exact",)}
        registry = _SKIP_ARG_REGISTRY

    @filter_field(GraphQLString, description="Search in title")
    def search(cls, queryset, info, value):
        return queryset.filter(title__icontains=value)

    @filter_field(GraphQLInt, description="Filter by min views")
    def min_views(cls, queryset, info, value):
        return queryset.filter(views__gte=value)


class TestFilterFieldNoneSkip:
    """filter_field.py:114 — None value is skipped, queryset unchanged."""

    @pytest.mark.django_db
    def test_missing_arg_is_skipped_queryset_unchanged(self, db):
        """When only 'search' is supplied and 'min_views' is absent, the
        min_views method is never called and the queryset is unaffected by it.
        """
        author = Author.objects.create(name="Gap Author")
        p1 = Post.objects.create(
            title="Alpha Post", body="body", author=author, views=5
        )
        p2 = Post.objects.create(
            title="Beta Post", body="body", author=author, views=50
        )

        qs = _GapFilterPost.objects.all()
        custom_filters = _SkipArgType._dgx_custom_filters

        class _FakeInfo:
            context = None

        # filter_value has 'search' but NOT 'min_views' (attribute missing).
        # getattr(filter_value, 'min_views', None) → None → line 114 hit.
        filter_value = type("FV", (), {"search": "Alpha"})()

        qs_out = apply_custom_filters(qs, custom_filters, _FakeInfo(), filter_value)

        ids = set(qs_out.values_list("id", flat=True))
        # Only the 'search' filter ran; min_views was skipped.
        assert p1.id in ids, "p1 with 'Alpha' title must survive the search filter"
        assert p2.id not in ids, "p2 with 'Beta' title must be filtered out"

    def test_none_value_does_not_call_method(self):
        """A filter_value whose attribute is explicitly None hits line 114
        (value is None → continue) without invoking the corresponding method.
        """
        call_log: list[str] = []

        custom_filters_def: list = []

        def _spy_method(queryset, info, value):
            call_log.append("called")
            return queryset

        # Simulate what collect_custom_filters produces: (arg_name, method, meta).
        custom_filters_def.append(("my_arg", _spy_method, {}))

        class _FakeInfo:
            context = None

        # filter_value.my_arg is None → should hit line 114 (continue).
        filter_value = type("FV", (), {"my_arg": None})()

        qs = object()  # Sentinel; method must NOT be called.
        result = apply_custom_filters(qs, custom_filters_def, _FakeInfo(), filter_value)

        assert result is qs, "Queryset must be returned unchanged"
        assert call_log == [], "Method must NOT be called when value is None"


# ---------------------------------------------------------------------------
# 2. types.py:896-897 — ImproperlyConfigured on DjangoModelType
#    The existing test_filter_field.py::TestFilterFieldReservedNameCollision
#    exercises DjangoObjectType (line 248), NOT DjangoModelType (line 896).
#    We need a class definition using DjangoModelType that triggers line 896.
# ---------------------------------------------------------------------------


class TestDjangoModelTypeReservedNameCollision:
    """types.py:896-897 — reserved @filter_field name on DjangoModelType raises."""

    @pytest.mark.parametrize(
        "reserved_name",
        [
            "limit",
            "offset",
            "ordering",
            "page",
            "page_size",
        ],
    )
    def test_reserved_name_on_django_model_type_raises(self, reserved_name):
        """Defining a DjangoModelType with a @filter_field whose name matches a
        reserved pagination/ordering argument raises ImproperlyConfigured at class
        creation time (types.py line 896-897).

        Note: DjangoModelType does NOT accept 'registry' in Meta — use only the
        options it explicitly recognises to avoid a false positive from
        _check_unknown_options which runs before the reserved-name guard.
        """

        def _make_bad_type():
            # Build the method, decorate it, rename it to the reserved name.
            def _method(cls, queryset, info, value):
                return queryset

            _method.__name__ = reserved_name
            decorated = filter_field(GraphQLString)(_method)
            decorated.__name__ = reserved_name

            cls_name = f"BadModelType_{reserved_name}"
            # DjangoModelType accepts: model, filter_fields, pagination, etc.
            # Do NOT include 'registry' (a DjangoObjectType-only option).
            #
            # Native ``DjangoModelType`` routes class creation through Pydantic's
            # ``ModelMetaclass``. A class built with ``type(...)`` must therefore
            # carry the ``__module__`` / ``__qualname__`` keys that a ``class``
            # statement injects automatically, and the inner ``Meta`` needs a
            # qualified name so Pydantic recognises it as the nested options
            # class the metaclass strips (otherwise it raises before the
            # reserved-name guard runs). These are construction details only —
            # the reserved-name guard still fires at class-creation time.
            meta = type(
                "Meta",
                (),
                {
                    "model": Post,
                    "filter_fields": {"id": ("exact",)},
                    "__qualname__": f"{cls_name}.Meta",
                },
            )
            attrs = {
                "__module__": __name__,
                "__qualname__": cls_name,
                "Meta": meta,
                reserved_name: decorated,
            }
            type(cls_name, (DjangoModelType,), attrs)

        with pytest.raises(ImproperlyConfigured, match=reserved_name):
            _make_bad_type()


# ---------------------------------------------------------------------------
# 3. views.py body-size guard — authoritative len(request.body) check
#    Content-Length is used only for a fast-reject optimisation when it is
#    already over the cap.  The authoritative guard always reads the actual
#    body length so that spoofed-low / absent / garbage Content-Length
#    values cannot bypass the limit.
# ---------------------------------------------------------------------------


class _SimpleQuery(ObjectType):
    hello = field(GraphQLString)

    def resolve_hello(root, info):
        return "world"


_simple_schema = DjangoGraphQLSchema(query=_SimpleQuery)


class TestContentLengthFallback(TestCase):
    """Body-size guard: absent or invalid Content-Length falls back to authoritative body length."""

    def setUp(self):
        self.factory = RequestFactory()

    def _make_view(self):
        from django_graphex.views import BaseGraphQLView

        return BaseGraphQLView.as_view(schema=_simple_schema)

    @override_settings(DJANGO_GRAPHEX={"MAX_REQUEST_BODY_SIZE": 50})
    def test_missing_content_length_over_limit_returns_413_or_400(self):
        """When CONTENT_LENGTH is absent and body exceeds the limit, the fallback
        len(request.body) path (lines 279-280) is taken and the request is rejected.
        """
        from django_graphex import settings as _s

        _s.graphql_api_settings.reload()
        try:
            view = self._make_view()
            # A body larger than the 50-byte limit.
            big_body = b"x" * 200
            request = self.factory.post(
                "/graphql/", data=big_body, content_type="application/json"
            )
            # Remove CONTENT_LENGTH so the except branch runs (ValueError/TypeError).
            request.META.pop("CONTENT_LENGTH", None)

            response = view(request)
            self.assertIn(response.status_code, (400, 413))
        finally:
            _s.graphql_api_settings.reload()

    @override_settings(DJANGO_GRAPHEX={"MAX_REQUEST_BODY_SIZE": 5000})
    def test_missing_content_length_under_limit_passes(self):
        """When CONTENT_LENGTH is absent and body is under the limit, the fallback
        len(request.body) path is taken and the request proceeds normally.
        """
        from django_graphex import settings as _s

        _s.graphql_api_settings.reload()
        try:
            view = self._make_view()
            payload = json.dumps({"query": "{ hello }"}).encode()
            request = self.factory.post(
                "/graphql/", data=payload, content_type="application/json"
            )
            # Remove CONTENT_LENGTH so the except branch runs.
            request.META.pop("CONTENT_LENGTH", None)

            response = view(request)
            self.assertEqual(response.status_code, 200)
            data = json.loads(response.content)
            self.assertEqual(data["data"]["hello"], "world")
        finally:
            _s.graphql_api_settings.reload()

    @override_settings(DJANGO_GRAPHEX={"MAX_REQUEST_BODY_SIZE": 50})
    def test_invalid_content_length_over_limit_returns_413_or_400(self):
        """When CONTENT_LENGTH is a non-numeric string the fast-reject stage
        skips it and the authoritative len(request.body) check rejects the
        over-limit body.

        Note: request._body is pre-read before CONTENT_LENGTH is corrupted so
        that Django's own request.body property (which caches the stream) does
        not fail when the view reads len(request.body).
        """
        from django_graphex import settings as _s

        _s.graphql_api_settings.reload()
        try:
            view = self._make_view()
            big_body = b"x" * 200
            request = self.factory.post(
                "/graphql/", data=big_body, content_type="application/json"
            )
            # Pre-read the body so Django caches it in request._body; after
            # this request.body is served from cache.  Then set a non-numeric
            # CONTENT_LENGTH so the fast-reject stage skips it and the
            # authoritative check fires.
            _ = request.body  # populate _body cache
            request.META["CONTENT_LENGTH"] = "not-a-number"

            response = view(request)
            self.assertIn(response.status_code, (400, 413))
        finally:
            _s.graphql_api_settings.reload()

    @override_settings(DJANGO_GRAPHEX={"MAX_REQUEST_BODY_SIZE": 5000})
    def test_invalid_content_length_under_limit_passes(self):
        """When CONTENT_LENGTH is non-numeric and body is under the limit the
        authoritative check passes and the request proceeds normally.

        Note: request._body is pre-read before CONTENT_LENGTH is corrupted (same
        reason as the over-limit test above).
        """
        from django_graphex import settings as _s

        _s.graphql_api_settings.reload()
        try:
            view = self._make_view()
            payload = json.dumps({"query": "{ hello }"}).encode()
            request = self.factory.post(
                "/graphql/", data=payload, content_type="application/json"
            )
            _ = request.body  # populate _body cache
            request.META["CONTENT_LENGTH"] = "not-a-number"

            response = view(request)
            self.assertEqual(response.status_code, 200)
            data = json.loads(response.content)
            self.assertEqual(data["data"]["hello"], "world")
        finally:
            _s.graphql_api_settings.reload()
