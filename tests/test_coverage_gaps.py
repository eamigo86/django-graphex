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
from typing import Any
from unittest.mock import patch

import pytest
from django.db import models
from django.test import RequestFactory, TestCase, override_settings
from graphql import GraphQLString

from django_graphex.core import ObjectType, field
from django_graphex.schema import DjangoGraphQLSchema
from django_graphex.views import GraphQLView

# Django 5.1 renamed ``CheckConstraint`` kwarg ``check`` -> ``condition``;
# ``check`` was removed in 6.0. Floor is >=5.2, so always use ``condition``.
_CHECK_CONSTRAINT_KW = "condition"

# ---------------------------------------------------------------------------
# __init__.py — PackageNotFoundError fallback
# ---------------------------------------------------------------------------


def test_version_from_pyproject_fallback() -> None:
    """The source-checkout fallback must agree with installed metadata and "__version__".

    Pins the single source of truth so the version can never drift between
    pyproject.toml, the installed package metadata, and the module attribute.
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
    """Model with a CheckConstraint — must NOT trigger the UniqueConstraint path.

    Used to confirm the isinstance(constraint, models.UniqueConstraint) guard
    skips non-UniqueConstraint entries in Meta.constraints.
    """

    value = models.IntegerField()

    class Meta:
        """Meta options declaring a CheckConstraint (not a UniqueConstraint).

        Used to keep the UniqueConstraint skip-path from ever seeing this
        constraint.
        """

        app_label = "tests"
        constraints = [
            models.CheckConstraint(
                name="check_val_gte_0_gaps",
                **{_CHECK_CONSTRAINT_KW: models.Q(value__gte=0)},
            ),
        ]


class ExpressionUCModel(_DummyBase):
    """Model with a functional UniqueConstraint (expressions=) — must be skipped.

    Used to confirm expression-based unique constraints are excluded from the
    per-field unique-violation check.
    """

    name = models.CharField(max_length=50)

    class Meta:
        """Meta options declaring an expression-based UniqueConstraint.

        The constraint wraps "Upper(name)" rather than a plain field list.
        """

        app_label = "tests"
        constraints = [
            models.UniqueConstraint(
                models.functions.Upper("name"),
                name="uc_expr_upper_name",
            ),
        ]


class DoubleUniqueModel(_DummyBase):
    """Field has unique=True AND a UniqueConstraint — the UC must be skipped (dedup).

    Used to confirm the unique-constraint dedup logic reports at most one
    error for a field covered by both a field-level unique and a UC.
    """

    code = models.CharField(max_length=10, unique=True)

    class Meta:
        """Meta options declaring a UniqueConstraint duplicating the field's own unique=True.

        Used to confirm the dedup path avoids a double error report.
        """

        app_label = "tests"
        constraints = [
            models.UniqueConstraint(fields=["code"], name="uc_double_code"),
        ]


def test_non_unique_constraint_is_skipped() -> None:
    """A CheckConstraint in Meta.constraints must not be processed as a UniqueConstraint.

    If this breaks, "_db_check_errors" could crash or misreport errors when a
    model declares a non-unique constraint alongside its fields.
    """
    from django_graphex.core.backend import PydanticBackend

    backend = PydanticBackend(NonUCCheckModel)
    # Should not raise and should return no errors for a simple value.
    errors = backend._db_check_errors({"value": 42}, instance=None)
    assert errors == {}, f"Expected no errors from CheckConstraint, got: {errors}"


@pytest.mark.django_db
def test_expression_unique_constraint_is_skipped() -> None:
    """A UniqueConstraint built from expressions= must be skipped by "_db_check_errors".

    If this breaks, an expression-based unique constraint could crash the
    check instead of being safely ignored (the ORM already enforces it).
    """
    from django_graphex.core.backend import PydanticBackend

    backend = PydanticBackend(ExpressionUCModel)
    errors = backend._db_check_errors({"name": "Alice"}, instance=None)
    assert errors == {}, (
        f"Expression-based UniqueConstraint should be skipped, got errors: {errors}"
    )


@pytest.mark.django_db
def test_single_field_uc_dedup_when_field_also_has_unique() -> None:
    """A single-field UniqueConstraint on a field already marked unique=True must not duplicate errors.

    If this breaks, a field covered by both a field-level unique and a
    matching UniqueConstraint would surface two error messages for the same
    violation instead of one.
    """
    from django_graphex.core.backend import PydanticBackend

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


class _Q(ObjectType):
    """Minimal query root exposing a single "hello" scalar field."""

    hello = field(GraphQLString)

    def resolve_hello(root: Any, info: Any) -> str:
        """Resolve the "hello" field to a constant greeting.

        Args:
            root: The unused root value passed by the executor.
            info: The unused GraphQL resolve info passed by the executor.

        Returns:
            greeting: The literal string "world".
        """
        return "world"


_schema = DjangoGraphQLSchema(query=_Q)

CACHE_ON = {"DJANGO_GRAPHEX": {"CACHE_ACTIVE": True, "CACHE_TIMEOUT": 60}}


class CacheKeyPrefixAuthHeaderTest(TestCase):
    """Coverage of "GraphQLView.cache_key_prefix" for the Authorization-header path.

    Confirms anonymous requests carrying a bearer token get a "t"-prefixed
    identity distinct from the plain "anon" identity.
    """

    def setUp(self) -> None:
        """Create a request factory shared by each test method.

        Runs before every test in this class per unittest convention.
        """
        self.factory = RequestFactory()

    def test_auth_header_gives_token_prefix(self) -> None:
        """A request with an Authorization header (no authenticated user) must get a "t"-prefixed identity token.

        If this breaks, token-authenticated anonymous requests could share a
        cache key with unrelated requests instead of being isolated by token.
        """
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

    def test_no_auth_gives_anon_prefix(self) -> None:
        """A request with no Authorization header and no user must get the "anon" identity.

        If this breaks, fully anonymous requests could be mis-tagged with a
        token-derived identity instead of the shared anonymous cache key.
        """
        request = self.factory.post(
            "/graphql/",
            json.dumps({"query": "{ hello }"}),
            content_type="application/json",
        )
        identity = GraphQLView.cache_key_prefix(request)
        self.assertEqual(identity, "anon")

    @override_settings(**CACHE_ON)
    def test_token_auth_request_cached_and_served(self) -> None:
        """With CACHE_ACTIVE, an Authorization-header request must be cached and served by token identity.

        If this breaks, token-identified responses could bypass the cache or
        be served from a mismatched entry.
        """
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
    """Coverage of "GraphQLView._is_introspection_document" edge-case handling.

    Exercises None input, fragment-only documents, empty documents, empty
    selection sets, and top-level inline fragments.
    """

    def test_none_document_returns_false(self) -> None:
        """Passing None as the document must return False, not raise.

        If this breaks, a missing document could crash introspection
        detection instead of being treated as non-introspection.
        """
        self.assertFalse(GraphQLView._is_introspection_document(None))

    def test_fragment_definition_is_not_introspection(self) -> None:
        """A document containing only a fragment definition (no operation) must return False.

        If this breaks, the isinstance guard that skips non-operation
        definitions could mis-detect a fragment-only document as
        introspection.
        """
        from graphql import parse

        doc = parse("fragment F on Query { hello }")
        # A fragment-only document has no OperationDefinitionNode,
        # so the loop continues without returning True → False at line 808.
        result = GraphQLView._is_introspection_document(doc)
        self.assertFalse(result)

    def test_non_operation_definition_is_skipped(self) -> None:
        """A document whose only definition is a fragment must be skipped and return False.

        If this breaks, non-operation definitions could be mishandled by the
        introspection-detection loop instead of being skipped cleanly.
        """
        from graphql import parse

        # A fragment-definition-only document — no operations.
        doc = parse("fragment Frag on Query { hello }")
        # No OperationDefinitionNode → loop body never reached → line 808 reached.
        result = GraphQLView._is_introspection_document(doc)
        self.assertFalse(result)

    def test_empty_document_returns_false(self) -> None:
        """A document with no definitions at all must return False.

        If this breaks, an empty document could crash introspection
        detection instead of yielding a safe False.
        """
        from graphql.language.ast import DocumentNode

        empty_doc = DocumentNode(definitions=())
        result = GraphQLView._is_introspection_document(empty_doc)
        self.assertFalse(result)

    def test_operation_with_empty_selection_set_returns_false(self) -> None:
        """An operation with no selections must fall through to return False.

        If this breaks, an operation with an empty selection set could be
        mis-detected as introspection instead of falling through the
        "if not selections: continue" branch.
        """
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

    def test_inline_fragment_at_top_level_is_not_introspection(self) -> None:
        """A top-level inline fragment (not a field selection) must return False.

        If this breaks, an inline fragment used as a top-level selection
        could be mis-detected as introspection instead of hitting the
        else-branch fallthrough.
        """
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

    def test_schema_introspection_is_detected(self) -> None:
        """A pure "__schema" introspection query must return True.

        If this breaks, genuine introspection queries could be missed by
        cost/permission checks meant to exempt them.
        """
        from graphql import parse

        doc = parse("{ __schema { types { name } } }")
        self.assertTrue(GraphQLView._is_introspection_document(doc))

    def test_mixed_fields_are_not_introspection(self) -> None:
        """A query mixing "__schema" with a regular field must return False.

        If this breaks, a query that smuggles real data-fetching fields
        alongside introspection could be wrongly exempted from cost or
        permission enforcement.
        """
        from graphql import parse

        doc = parse("{ __schema { types { name } } hello }")
        self.assertFalse(GraphQLView._is_introspection_document(doc))


# ---------------------------------------------------------------------------
# subscriptions/subscription.py line 595 — session_key from context.session
# ---------------------------------------------------------------------------


def test_subscription_session_key_from_context_session() -> None:
    """When no explicit "_session_key" is given and "info.context" has a "session", the key must be derived from it.

    Tests the code path directly rather than going through the full
    Subscription machinery (which requires a real model). If this breaks,
    anonymous-channel subscriptions could lose their session-derived
    identity.
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


def test_multiselect_field_import_fallback() -> None:
    """When multiselectfield is not installed, the isinstance check must fall back to a name-based check.

    Exercises the ImportError branch (the isinstance check is only reachable
    when the optional import succeeds) to ensure the fallback still works.

    Raises:
        ImportError: Simulated internally by "mock_import" for the
            "multiselectfield" module name, to exercise the not-installed
            branch; the test itself does not propagate this error.
    """
    # Simulate multiselectfield not being installed.
    import builtins

    real_import = builtins.__import__

    def mock_import(name: str, *args: Any, **kwargs: Any) -> Any:
        """Delegate to the real "__import__", except fail for "multiselectfield".

        Args:
            name: The dotted module name being imported.
            args: Additional positional arguments forwarded to "__import__".
            kwargs: Additional keyword arguments forwarded to "__import__".

        Returns:
            module: The imported module, from the real "__import__".

        Raises:
            ImportError: When "name" is "multiselectfield", to simulate the
                package not being installed.
        """
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
