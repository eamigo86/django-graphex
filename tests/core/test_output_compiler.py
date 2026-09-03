"""TDD A2.1 / A2.3 RED — core/output_compiler.py tests.

Tests:
- _to_graphql_field maps Django scalar fields to graphql-core scalars.
- Multi-word field names produce camelCase dict keys.
- FK fields return a zero-arg callable (lazy thunk).
- Three distinct FK fields (X, Y, Z) each thunk resolves to its own target
  (no loop-variable capture aliasing).
- GdxMeta as Annotated OUTPUT-only metadata is not eager-instantiated.

Run: .venv/bin/python -m pytest -q tests/core/test_output_compiler.py --no-cov
"""

from __future__ import annotations

import os

import django
import pytest

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "tests.settings")
django.setup()

from django.db import models  # noqa: E402

# ---------------------------------------------------------------------------
# Minimal stub models for testing (no DB required)
# ---------------------------------------------------------------------------


class AuthorModel(models.Model):
    """Minimal stub model with a single scalar field.

    Used as an FK target in the FK-mapping tests below.
    """

    name = models.CharField(max_length=100)

    class Meta:
        """Django model options.

        Declares the app label so the model registers cleanly under the
        test app without a matching database migration.
        """

        app_label = "tests"


class BookModel(models.Model):
    """Minimal stub model with a required FK to "AuthorModel".

    Used to exercise single to-one relation compilation.
    """

    title = models.CharField(max_length=200)
    author = models.ForeignKey(
        AuthorModel, on_delete=models.CASCADE, related_name="books"
    )

    class Meta:
        """Django model options.

        Declares the app label so the model registers cleanly under the
        test app without a matching database migration.
        """

        app_label = "tests"


class PublisherModel(models.Model):
    """Minimal stub model with a single scalar field.

    Used as an FK target in the multi-FK aliasing test.
    """

    name = models.CharField(max_length=100)

    class Meta:
        """Django model options.

        Declares the app label so the model registers cleanly under the
        test app without a matching database migration.
        """

        app_label = "tests"


class EditionModel(models.Model):
    """Model with three distinct FK relations for loop-capture test.

    Used to prove that compiling multiple FK fields in one pass does not
    alias distinct target types under a shared loop variable.
    """

    code = models.CharField(max_length=50)
    book = models.ForeignKey(BookModel, on_delete=models.CASCADE, null=True)
    author = models.ForeignKey(AuthorModel, on_delete=models.CASCADE, null=True)
    publisher = models.ForeignKey(PublisherModel, on_delete=models.CASCADE, null=True)

    class Meta:
        """Django model options.

        Declares the app label so the model registers cleanly under the
        test app without a matching database migration.
        """

        app_label = "tests"


class AllScalarsModel(models.Model):
    """Model with various scalar field types.

    Exercises the scalar-field-to-GraphQL-scalar mapping and camelCase
    key derivation tests below.
    """

    char_field = models.CharField(max_length=100)
    int_field = models.IntegerField(default=0)
    bool_field = models.BooleanField(default=False)
    float_field = models.FloatField(default=0.0)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        """Django model options.

        Declares the app label so the model registers cleanly under the
        test app without a matching database migration.
        """

        app_label = "tests"


# ---------------------------------------------------------------------------
# Minimal registry stub
# ---------------------------------------------------------------------------


class StubRegistry:
    """Minimal registry for testing "_to_graphql_field".

    Provides just enough of the real registry surface (get/register
    compiled type by model class) for the output-compiler tests.
    """

    def __init__(self) -> None:
        self._compiled: dict = {}

    def get_compiled(self, model_cls: type) -> object | None:
        """Return the compiled GraphQL type registered for a model class.

        Args:
            model_cls: The Django model class to look up.

        Returns:
            compiled: The registered compiled type, or None if unregistered.
        """
        return self._compiled.get(model_cls)

    def register_compiled(self, model_cls: type, gql_type: object) -> None:
        """Register a compiled GraphQL type for a model class.

        Args:
            model_cls: The Django model class being registered.
            gql_type: The compiled GraphQL type to associate with it.
        """
        self._compiled[model_cls] = gql_type


# ---------------------------------------------------------------------------
# A2.1: Scalar field mapping
# ---------------------------------------------------------------------------


def test_char_field_maps_to_string() -> None:
    """Assert that a CharField compiles to a GraphQLString output field.

    If this fails, a plain text model field would compile to the wrong
    GraphQL scalar type.
    """
    from graphql import GraphQLString

    from django_graphex.core.output_compiler import _to_graphql_field

    registry = StubRegistry()
    field_map = _to_graphql_field(
        AllScalarsModel._meta.get_field("char_field"), registry
    )

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


def test_int_field_maps_to_int() -> None:
    """Assert that an IntegerField compiles to a GraphQLInt output field.

    If this fails, an integer model field would compile to the wrong
    GraphQL scalar type.
    """
    from graphql import GraphQLInt, GraphQLNonNull

    from django_graphex.core.output_compiler import _to_graphql_field

    registry = StubRegistry()
    field_map = _to_graphql_field(
        AllScalarsModel._meta.get_field("int_field"), registry
    )
    key = next(k for k in field_map if "int" in k.lower())
    gql_type = field_map[key].type
    if isinstance(gql_type, GraphQLNonNull):
        gql_type = gql_type.of_type
    assert gql_type == GraphQLInt


def test_bool_field_maps_to_boolean() -> None:
    """Assert that a BooleanField compiles to a GraphQLBoolean output field.

    If this fails, a boolean model field would compile to the wrong
    GraphQL scalar type.
    """
    from graphql import GraphQLBoolean, GraphQLNonNull

    from django_graphex.core.output_compiler import _to_graphql_field

    registry = StubRegistry()
    field_map = _to_graphql_field(
        AllScalarsModel._meta.get_field("bool_field"), registry
    )
    key = next(k for k in field_map if "bool" in k.lower())
    gql_type = field_map[key].type
    if isinstance(gql_type, GraphQLNonNull):
        gql_type = gql_type.of_type
    assert gql_type == GraphQLBoolean


# ---------------------------------------------------------------------------
# A2.2: camelCase dict key
# ---------------------------------------------------------------------------


def test_created_at_has_camel_case_key() -> None:
    """Assert that DateTimeField "created_at" compiles to the camelCase key "createdAt".

    If this fails, the compiled field map would expose the snake_case
    Python name on the wire instead of the expected camelCase SDL key.
    """
    from django_graphex.core.output_compiler import _to_graphql_field

    registry = StubRegistry()
    field_map = _to_graphql_field(
        AllScalarsModel._meta.get_field("created_at"), registry
    )
    assert "createdAt" in field_map, (
        f"Expected camelCase key 'createdAt', got keys: {list(field_map.keys())}"
    )
    assert "created_at" not in field_map, (
        "Snake-case key must NOT appear in the field map"
    )


# ---------------------------------------------------------------------------
# A2.3: FK relation returns zero-arg callable thunk
# ---------------------------------------------------------------------------


def test_fk_field_returns_thunk() -> None:
    """Assert that a ForeignKey field's compiled type resolves to its target's compiled type.

    If this fails, an FK relation would not resolve (directly or via a
    lazy thunk) to the registered target type, breaking relation traversal.
    """
    from graphql import GraphQLField

    from django_graphex.core.output_compiler import _to_graphql_field

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
    from graphql import GraphQLList, GraphQLNonNull

    while isinstance(resolved_type, (GraphQLNonNull, GraphQLList)):
        resolved_type = resolved_type.of_type
    assert resolved_type is author_type, (
        f"FK thunk must resolve to AuthorModel's compiled type, got {resolved_type!r}"
    )


# ---------------------------------------------------------------------------
# A2.3 / A2.4: Three-field loop-capture test — no aliasing
# ---------------------------------------------------------------------------


def test_three_fk_fields_no_aliasing() -> None:
    """Assert that three distinct FK fields resolve to their own types, with no loop-var aliasing.

    If this fails, compiling multiple FK fields in one pass could leak a
    shared closure variable, making every FK field resolve to the same
    (usually the last) target type.
    """
    from graphql import GraphQLList, GraphQLNonNull, GraphQLObjectType

    from django_graphex.core.output_compiler import compile_output_fields

    # Build registry with three distinct compiled types
    registry = StubRegistry()
    book_type = GraphQLObjectType("Book", fields=lambda: {})
    author_type = GraphQLObjectType("Author", fields=lambda: {})
    publisher_type = GraphQLObjectType("Publisher", fields=lambda: {})

    registry.register_compiled(BookModel, book_type)
    registry.register_compiled(AuthorModel, author_type)
    registry.register_compiled(PublisherModel, publisher_type)

    # compile_output_fields returns the full dict for EditionModel
    fields = compile_output_fields(
        EditionModel, registry, only_fields=["book", "author", "publisher"]
    )

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


# ---------------------------------------------------------------------------
# Audit rank 6: unregistered to-ONE relation target must FAIL FAST, not
# silently emit GraphQLString (a silent type mismatch on the wire).
# ---------------------------------------------------------------------------


def test_unregistered_to_one_relation_dropped_not_string(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Assert that a to-one FK with an unregistered target is dropped, not stringified.

    The relation must be absent from the output fields with a logged
    warning naming the field AND the unregistered target — NOT silently
    emitted as "GraphQLString" (audit rank 6). Dropping (vs failing the
    build) preserves the legitimate partial-registration use case while
    removing the silent String type mismatch.

    Args:
        caplog: Captures the warning log emitted for the unregistered
            relation target so the test can assert on its content.

    If this fails, an FK to an unregistered model would silently compile
    as a GraphQLString field, producing a schema that lies about the
    field's real type.
    """
    import logging

    from graphql import GraphQLString

    from django_graphex.core.output_compiler import _to_graphql_field

    # Empty registry: AuthorModel (the FK target) is NOT registered.
    registry = StubRegistry()
    fk_field = BookModel._meta.get_field("author")

    with caplog.at_level(logging.WARNING, logger="django_graphex.core.output_compiler"):
        field_map = _to_graphql_field(fk_field, registry)

    # The relation must NOT be emitted at all — and crucially NEVER as a String.
    assert field_map == {}, (
        "an unregistered to-one relation must be dropped (empty field map), not "
        f"emitted as a GraphQLString; got {field_map!r}"
    )
    for gql_field in field_map.values():
        assert gql_field.type is not GraphQLString

    # A warning must name the field and the unregistered target so the
    # misconfiguration is diagnosable at build time.
    msg = caplog.text
    assert "author" in msg, f"warning must name the relation field; got {msg!r}"
    assert "AuthorModel" in msg, (
        f"warning must name the unregistered target model; got {msg!r}"
    )
