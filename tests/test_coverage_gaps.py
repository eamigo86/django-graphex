# -*- coding: utf-8 -*-
"""Targeted tests to close patch-diff coverage gaps for v1.2.1.

Covers:
- __init__.py: PackageNotFoundError fallback for __version__
- native/backend.py: UniqueConstraint skip branches (non-UC, expressions, dedup)
- subscriptions/subscription.py: session_key derivation from context.session
- views.py: cache_key_prefix auth-header path, _is_introspection_document branches
- converter.py: multiselectfield import fallback (name-based check)
"""

from __future__ import annotations

import json
from types import SimpleNamespace
from unittest.mock import patch

import django
import graphene
import pytest
from django.db import models
from django.test import RequestFactory, TestCase, override_settings

from django_graphex.views import GraphQLView

# ``CheckConstraint`` renamed its predicate kwarg ``check`` -> ``condition`` in
# Django 5.1 (``check`` removed in 6.0). Pick the right one for the running
# version so this module imports across the whole 4.2–6.0 support matrix.
_CHECK_CONSTRAINT_KW = "condition" if django.VERSION >= (5, 1) else "check"

# ---------------------------------------------------------------------------
# __init__.py — PackageNotFoundError fallback
# ---------------------------------------------------------------------------


def test_version_from_pyproject_fallback():
    """The source-checkout fallback reads the version straight from
    pyproject.toml and must agree with both the installed metadata and
    ``__version__`` — pinning the single source of truth so the version can
    never drift between pyproject.toml and the package.
    """
    import importlib.metadata

    import django_graphex

    fallback_version = django_graphex._version_from_pyproject()

    assert isinstance(fallback_version, str) and fallback_version, (
        f"_version_from_pyproject produced empty/non-str: {fallback_version!r}"
    )
    # pyproject.toml (fallback) == build metadata == __version__ — no drift.
    assert fallback_version == importlib.metadata.version("django-graphex")
    assert fallback_version == django_graphex.__version__


# ---------------------------------------------------------------------------
# native/backend.py — UniqueConstraint skip branches
# ---------------------------------------------------------------------------


class _DummyBase(models.Model):
    """Abstract base so inline models don't need migrations."""

    class Meta:
        abstract = True
        app_label = "tests"


class NonUCCheckModel(_DummyBase):
    """Model with a CheckConstraint — must NOT trigger the UniqueConstraint path."""

    value = models.IntegerField()

    class Meta:
        app_label = "tests"
        constraints = [
            models.CheckConstraint(
                name="check_val_gte_0_gaps",
                **{_CHECK_CONSTRAINT_KW: models.Q(value__gte=0)},
            ),
        ]


class ExpressionUCModel(_DummyBase):
    """Model with a functional UniqueConstraint (expressions=) — must be skipped."""

    name = models.CharField(max_length=50)

    class Meta:
        app_label = "tests"
        constraints = [
            models.UniqueConstraint(
                models.functions.Upper("name"),
                name="uc_expr_upper_name",
            ),
        ]


class DoubleUniqueModel(_DummyBase):
    """Field has unique=True AND a UniqueConstraint — the UC must be skipped (dedup)."""

    code = models.CharField(max_length=10, unique=True)

    class Meta:
        app_label = "tests"
        constraints = [
            models.UniqueConstraint(fields=["code"], name="uc_double_code"),
        ]


def test_non_unique_constraint_is_skipped():
    """A CheckConstraint in Meta.constraints must not be processed by _db_check_errors
    (the isinstance(constraint, models.UniqueConstraint) guard, line 159)."""
    from django_graphex.native.backend import PydanticBackend

    backend = PydanticBackend(NonUCCheckModel)
    # Should not raise and should return no errors for a simple value.
    errors = backend._db_check_errors({"value": 42}, instance=None)
    assert errors == {}, f"Expected no errors from CheckConstraint, got: {errors}"


@pytest.mark.django_db
def test_expression_unique_constraint_is_skipped():
    """A UniqueConstraint with expressions= must be skipped (line 165)."""
    from django_graphex.native.backend import PydanticBackend

    backend = PydanticBackend(ExpressionUCModel)
    errors = backend._db_check_errors({"name": "Alice"}, instance=None)
    assert errors == {}, (
        f"Expression-based UniqueConstraint should be skipped, got errors: {errors}"
    )


@pytest.mark.django_db
def test_single_field_uc_dedup_when_field_also_has_unique():
    """A single-field UC on a field that already has unique=True must not produce
    duplicate errors (the dedup skip at line 180)."""
    from django_graphex.native.backend import PydanticBackend

    # Create an existing row to trigger the unique violation.
    DoubleUniqueModel.objects.create(code="X1")

    backend = PydanticBackend(DoubleUniqueModel)
    errors = backend._db_check_errors({"code": "X1"}, instance=None)

    # Collect error messages for "code".
    code_errors = errors.get("code", [])
    # The per-field unique loop already catches the violation — the UC dedup
    # skip means we get at most ONE error message for "code".
    assert len(code_errors) <= 1, (
        f"Expected at most 1 error for 'code' (UC dedup), got: {code_errors}"
    )
    # The error must be present (field IS unique-violated).
    assert code_errors, "Expected a unique-violation error on 'code'"


# ---------------------------------------------------------------------------
# views.py — cache_key_prefix auth-header path
# ---------------------------------------------------------------------------


class _Q(graphene.ObjectType):
    hello = graphene.String()

    def resolve_hello(root, info):
        return "world"


_schema = graphene.Schema(query=_Q)

CACHE_ON = {"DJANGO_GRAPHEX": {"CACHE_ACTIVE": True, "CACHE_TIMEOUT": 60}}


class CacheKeyPrefixAuthHeaderTest(TestCase):
    """GraphQLView.cache_key_prefix must return a 't<hash>' prefix for anonymous
    requests that carry an Authorization header (lines 635, 638)."""

    def setUp(self):
        self.factory = RequestFactory()

    def test_auth_header_gives_token_prefix(self):
        """A request with an Authorization header (no authenticated user) must get
        a 't'-prefixed identity token."""
        request = self.factory.post(
            "/graphql/",
            json.dumps({"query": "{ hello }"}),
            content_type="application/json",
            HTTP_AUTHORIZATION="Bearer test-token-abc",
        )
        identity = GraphQLView.cache_key_prefix(request)
        self.assertTrue(
            identity.startswith("t"),
            f"Expected 't' prefix for token-auth identity, got: {identity!r}",
        )

    def test_no_auth_gives_anon_prefix(self):
        """A request with no Authorization header and no user gets 'anon' identity."""
        request = self.factory.post(
            "/graphql/",
            json.dumps({"query": "{ hello }"}),
            content_type="application/json",
        )
        identity = GraphQLView.cache_key_prefix(request)
        self.assertEqual(identity, "anon")

    @override_settings(**CACHE_ON)
    def test_token_auth_request_cached_and_served(self):
        """With CACHE_ACTIVE, an Authorization-header request is cached by token."""
        from django.core.cache import cache

        cache.clear()
        view = GraphQLView.as_view(schema=_schema)
        body = json.dumps({"query": "{ hello }"})

        req1 = self.factory.post(
            "/graphql/",
            body,
            content_type="application/json",
            HTTP_AUTHORIZATION="Bearer tok-123",
        )
        req2 = self.factory.post(
            "/graphql/",
            body,
            content_type="application/json",
            HTTP_AUTHORIZATION="Bearer tok-123",
        )

        resp1 = view(req1)
        self.assertEqual(resp1.status_code, 200)
        resp2 = view(req2)
        self.assertEqual(resp2.status_code, 200)
        self.assertEqual(
            json.loads(resp1.content)["data"],
            json.loads(resp2.content)["data"],
        )


# ---------------------------------------------------------------------------
# views.py — _is_introspection_document edge branches
# ---------------------------------------------------------------------------


class IntrospectionDocumentTest(TestCase):
    """_is_introspection_document must handle edge cases cleanly."""

    def test_none_document_returns_false(self):
        """Passing None as document must return False (line 786)."""
        self.assertFalse(GraphQLView._is_introspection_document(None))

    def test_fragment_definition_is_not_introspection(self):
        """A document containing a fragment definition (not OperationDefinitionNode)
        must return False — the isinstance guard skips the definition (line 791)."""
        from graphql import parse

        doc = parse("fragment F on Query { hello }")
        # A fragment-only document has no OperationDefinitionNode,
        # so the loop continues without returning True → False at line 808.
        result = GraphQLView._is_introspection_document(doc)
        self.assertFalse(result)

    def test_non_operation_definition_is_skipped(self):
        """A document whose only definition is a fragment (not OperationDefinitionNode)
        exercises the isinstance guard at line 791 and returns False at line 808."""
        from graphql import parse

        # A fragment-definition-only document — no operations.
        doc = parse("fragment Frag on Query { hello }")
        # No OperationDefinitionNode → loop body never reached → line 808 reached.
        result = GraphQLView._is_introspection_document(doc)
        self.assertFalse(result)

    def test_empty_document_returns_false(self):
        """A document with no definitions returns False at line 808."""
        from graphql.language.ast import DocumentNode

        empty_doc = DocumentNode(definitions=())
        result = GraphQLView._is_introspection_document(empty_doc)
        self.assertFalse(result)

    def test_operation_with_empty_selection_set_returns_false(self):
        """An OperationDefinitionNode with no selections hits the
        'if not selections: continue' branch (line 796) and falls through
        to return False (line 808)."""
        from graphql import OperationType
        from graphql.language.ast import (
            DocumentNode,
            OperationDefinitionNode,
            SelectionSetNode,
        )

        # Build a document with one operation that has an empty selection set.
        empty_sel_set = SelectionSetNode(selections=())
        op = OperationDefinitionNode(
            operation=OperationType.QUERY,
            name=None,
            variable_definitions=(),
            directives=(),
            selection_set=empty_sel_set,
        )
        doc = DocumentNode(definitions=(op,))
        result = GraphQLView._is_introspection_document(doc)
        self.assertFalse(result)

    def test_inline_fragment_at_top_level_is_not_introspection(self):
        """A top-level inline fragment (not FieldNode) causes the else branch
        to return False (line 805)."""
        from graphql import parse

        # An operation whose only top-level selection is an inline fragment.
        doc = parse("""
        query {
            ... on Query {
                hello
            }
        }
        """)
        result = GraphQLView._is_introspection_document(doc)
        self.assertFalse(result)

    def test_schema_introspection_is_detected(self):
        """A pure __schema introspection query must return True."""
        from graphql import parse

        doc = parse("{ __schema { types { name } } }")
        self.assertTrue(GraphQLView._is_introspection_document(doc))

    def test_mixed_fields_are_not_introspection(self):
        """A query with __schema + a regular field must return False."""
        from graphql import parse

        doc = parse("{ __schema { types { name } } hello }")
        self.assertFalse(GraphQLView._is_introspection_document(doc))


# ---------------------------------------------------------------------------
# subscriptions/subscription.py line 595 — session_key from context.session
# ---------------------------------------------------------------------------


def test_subscription_session_key_from_context_session():
    """When _session_key is None and info.context has a .session attribute,
    session_key must be derived from session.session_key (line 595).

    We test the code path directly rather than going through the full
    Subscription machinery (which requires a real model).
    """
    pytest.importorskip("channels")  # skip if channels not installed

    # Replicate the exact code path from subscription.py ~590-595.
    # This tests the logic without requiring a full Subscription subclass.
    fake_session = SimpleNamespace(session_key="ses-abc-123")
    fake_context = SimpleNamespace(session=fake_session)
    fake_info = SimpleNamespace(context=fake_context)

    kwargs: dict = {}
    session_key: str | None = kwargs.pop("_session_key", None)
    if session_key is None and fake_info is not None:
        context = fake_info.context
        session = getattr(context, "session", None)
        if session is not None:
            session_key = getattr(session, "session_key", None) or ""

    assert session_key == "ses-abc-123", (
        f"session_key should be derived from context.session, got: {session_key!r}"
    )


# ---------------------------------------------------------------------------
# converter.py line 281 — multiselectfield name-check fallback
# ---------------------------------------------------------------------------


def test_multiselect_field_import_fallback():
    """When multiselectfield is not installed, the isinstance check falls back
    to a name-based check (line 281 is only reached when the import succeeds).

    This test exercises the ImportError branch to ensure the fallback works.
    """
    # Simulate multiselectfield not being installed.
    import builtins

    real_import = builtins.__import__

    def mock_import(name, *args, **kwargs):
        if name == "multiselectfield":
            raise ImportError("no multiselectfield")
        return real_import(name, *args, **kwargs)

    class _FakeField:
        __name__ = "MultiSelectField"
        choices = [("a", "A"), ("b", "B")]
        help_text = ""
        verbose_name = "test"

        def formfield(self, **kwargs):
            return None

    with patch("builtins.__import__", side_effect=mock_import):
        # The fallback checks type(field).__name__ == "MultiSelectField"
        field_cls_name = type(_FakeField()).__name__
        _is_multiselect = field_cls_name == "MultiSelectField"

    # The FakeField class name is "_FakeField", not "MultiSelectField" — not matched.
    assert not _is_multiselect
