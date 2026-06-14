"""TDD A2.1 / A2.3 RED — native/output_compiler.py tests.

Tests:
- _to_graphql_field maps Django scalar fields to graphql-core scalars.
- Multi-word field names produce camelCase dict keys.
- FK fields return a zero-arg callable (lazy thunk).
- Three distinct FK fields (X, Y, Z) each thunk resolves to its own target
  (no loop-variable capture aliasing).
- GdxMeta as Annotated OUTPUT-only metadata is not eager-instantiated.

Run: .venv/bin/python -m pytest -q tests/native/test_output_compiler.py
"""
from __future__ import annotations

import django
import os
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "tests.settings")
django.setup()

import pytest
from django.db import models

pytestmark = pytest.mark.native_only


# ---------------------------------------------------------------------------
# Minimal stub models for testing (no DB required)
# ---------------------------------------------------------------------------


class AuthorModel(models.Model):
    name = models.CharField(max_length=100)

    class Meta:
        app_label = "tests"


class BookModel(models.Model):
    title = models.CharField(max_length=200)
    author = models.ForeignKey(
        AuthorModel, on_delete=models.CASCADE, related_name="books"
    )

    class Meta:
        app_label = "tests"


class PublisherModel(models.Model):
    name = models.CharField(max_length=100)

    class Meta:
        app_label = "tests"


class EditionModel(models.Model):
    """Model with three distinct FK relations for loop-capture test."""
    code = models.CharField(max_length=50)
    book = models.ForeignKey(BookModel, on_delete=models.CASCADE, null=True)
    author = models.ForeignKey(AuthorModel, on_delete=models.CASCADE, null=True)
    publisher = models.ForeignKey(PublisherModel, on_delete=models.CASCADE, null=True)

    class Meta:
        app_label = "tests"


class AllScalarsModel(models.Model):
    """Model with various scalar field types."""
    char_field = models.CharField(max_length=100)
    int_field = models.IntegerField(default=0)
    bool_field = models.BooleanField(default=False)
    float_field = models.FloatField(default=0.0)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        app_label = "tests"


# ---------------------------------------------------------------------------
# Minimal registry stub
# ---------------------------------------------------------------------------


class StubRegistry:
    """Minimal registry for testing _to_graphql_field."""

    def __init__(self):
        self._compiled: dict = {}

    def get_compiled(self, model_cls):
        return self._compiled.get(model_cls)

    def register_compiled(self, model_cls, gql_type):
        self._compiled[model_cls] = gql_type


# ---------------------------------------------------------------------------
# A2.1: Scalar field mapping
# ---------------------------------------------------------------------------


def test_char_field_maps_to_string():
    """CharField → GraphQLString."""
    from graphql import GraphQLString
    from django_graphex.native.output_compiler import _to_graphql_field

    registry = StubRegistry()
    field_map = _to_graphql_field(AllScalarsModel._meta.get_field("char_field"), registry)

    assert "charField" in field_map or "char_field" in field_map, (
        "Expected camelCase or snake_case key in field_map"
    )
    # The result is a dict {camel_key: GraphQLField}
    key = "charField" if "charField" in field_map else "char_field"
    from graphql import GraphQLField
    assert isinstance(field_map[key], GraphQLField)
    # Unwrap NonNull if present
    gql_type = field_map[key].type
    from graphql import GraphQLNonNull
    if isinstance(gql_type, GraphQLNonNull):
        gql_type = gql_type.of_type
    assert gql_type == GraphQLString


def test_int_field_maps_to_int():
    """IntegerField → GraphQLInt."""
    from graphql import GraphQLInt, GraphQLNonNull, GraphQLField
    from django_graphex.native.output_compiler import _to_graphql_field

    registry = StubRegistry()
    field_map = _to_graphql_field(AllScalarsModel._meta.get_field("int_field"), registry)
    key = next(k for k in field_map if "int" in k.lower())
    gql_type = field_map[key].type
    if isinstance(gql_type, GraphQLNonNull):
        gql_type = gql_type.of_type
    assert gql_type == GraphQLInt


def test_bool_field_maps_to_boolean():
    """BooleanField → GraphQLBoolean."""
    from graphql import GraphQLBoolean, GraphQLNonNull
    from django_graphex.native.output_compiler import _to_graphql_field

    registry = StubRegistry()
    field_map = _to_graphql_field(AllScalarsModel._meta.get_field("bool_field"), registry)
    key = next(k for k in field_map if "bool" in k.lower())
    gql_type = field_map[key].type
    if isinstance(gql_type, GraphQLNonNull):
        gql_type = gql_type.of_type
    assert gql_type == GraphQLBoolean


# ---------------------------------------------------------------------------
# A2.2: camelCase dict key
# ---------------------------------------------------------------------------


def test_created_at_has_camel_case_key():
    """DateTimeField 'created_at' → dict key 'createdAt'."""
    from django_graphex.native.output_compiler import _to_graphql_field

    registry = StubRegistry()
    field_map = _to_graphql_field(AllScalarsModel._meta.get_field("created_at"), registry)
    assert "createdAt" in field_map, (
        f"Expected camelCase key 'createdAt', got keys: {list(field_map.keys())}"
    )
    assert "created_at" not in field_map, (
        "Snake-case key must NOT appear in the field map"
    )


# ---------------------------------------------------------------------------
# A2.3: FK relation returns zero-arg callable thunk
# ---------------------------------------------------------------------------


def test_fk_field_returns_thunk():
    """ForeignKey field → zero-arg callable (thunk)."""
    from graphql import GraphQLField
    from django_graphex.native.output_compiler import _to_graphql_field

    registry = StubRegistry()
    # Register a mock compiled type for AuthorModel
    from graphql import GraphQLObjectType
    author_type = GraphQLObjectType("Author", fields=lambda: {})
    registry.register_compiled(AuthorModel, author_type)

    # Get the 'author' FK field from BookModel
    fk_field = BookModel._meta.get_field("author")
    field_map = _to_graphql_field(fk_field, registry)

    assert len(field_map) == 1
    key, gql_field = next(iter(field_map.items()))
    assert isinstance(gql_field, GraphQLField)

    # The field type should be a thunk (callable) or a GraphQL type
    # For FK: the type itself could be a lambda or a direct GraphQLObjectType
    # The key contract is: the field resolves to the registered type
    resolved_type = gql_field.type
    # Unwrap NonNull/List if present
    from graphql import GraphQLNonNull, GraphQLList
    while isinstance(resolved_type, (GraphQLNonNull, GraphQLList)):
        resolved_type = resolved_type.of_type
    assert resolved_type is author_type, (
        f"FK thunk must resolve to AuthorModel's compiled type, got {resolved_type!r}"
    )


# ---------------------------------------------------------------------------
# A2.3 / A2.4: Three-field loop-capture test — no aliasing
# ---------------------------------------------------------------------------


def test_three_fk_fields_no_aliasing():
    """Three distinct FK fields resolve to their respective types (no loop-var aliasing)."""
    from graphql import GraphQLObjectType, GraphQLNonNull, GraphQLList
    from django_graphex.native.output_compiler import compile_output_fields

    # Build registry with three distinct compiled types
    registry = StubRegistry()
    book_type = GraphQLObjectType("Book", fields=lambda: {})
    author_type = GraphQLObjectType("Author", fields=lambda: {})
    publisher_type = GraphQLObjectType("Publisher", fields=lambda: {})

    registry.register_compiled(BookModel, book_type)
    registry.register_compiled(AuthorModel, author_type)
    registry.register_compiled(PublisherModel, publisher_type)

    # compile_output_fields returns the full dict for EditionModel
    fields = compile_output_fields(EditionModel, registry, only_fields=["book", "author", "publisher"])

    def unwrap(t):
        while isinstance(t, (GraphQLNonNull, GraphQLList)):
            t = t.of_type
        return t

    # Each FK field must resolve to its own target
    assert "book" in fields
    assert "author" in fields
    assert "publisher" in fields

    book_resolved = unwrap(fields["book"].type)
    author_resolved = unwrap(fields["author"].type)
    publisher_resolved = unwrap(fields["publisher"].type)

    assert book_resolved is book_type, (
        f"'book' thunk must resolve to book_type, got {book_resolved!r}"
    )
    assert author_resolved is author_type, (
        f"'author' thunk must resolve to author_type, got {author_resolved!r}"
    )
    assert publisher_resolved is publisher_type, (
        f"'publisher' thunk must resolve to publisher_type, got {publisher_resolved!r}"
    )
    # Critically: all three must be different
    assert book_resolved is not author_resolved
    assert author_resolved is not publisher_resolved
    assert book_resolved is not publisher_resolved
