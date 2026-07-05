# -*- coding: utf-8 -*-
"""End-to-end RAW-JSON wire contract for model-derived "JSONField" (Wave 3).

The v2 flip makes a model "JSONField" render as the RAW "JSON" scalar in
ALL THREE derived paths (output / mutation-input / filter-input) instead of the
string-encoded "JSONString":

* **Output** — a query returns the JSONField value as a REAL nested structure
  (a Python "dict" / "list" in "result.data"), never a JSON-encoded
  string.
* **Mutation input** — a create/update accepts the raw object BOTH as a GraphQL
  variable AND as an inline object/list literal (exercising the recursive
  "GdxJSON.parse_literal"); the parsed value lands in the column as the real
  Python object ("refresh_from_db").
* **SDL** — the field prints ": JSON" (not ": JSONString") in the OUTPUT
  type, the mutation INPUT type, and the filter INPUT type.

The escape hatch ("JSONField(as_str=True)" / the "JSONString" scalar) is
covered by "tests/test_explicit_null_and_json_input.py" and
"tests/core/test_json_flip.py".
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

from django.db import models
from django.test import RequestFactory, TestCase
from graphql import (
    ExecutionResult,
    GraphQLInputObjectType,
    GraphQLNonNull,
    GraphQLScalarType,
    GraphQLString,
    GraphQLType,
    graphql_sync,
    parse,
    print_type,
    validate,
)

from django_graphex.core import ObjectType, field
from django_graphex.core.fields import build_model_schema
from django_graphex.core.input_compiler import compile_input_type
from django_graphex.mutation import DjangoModelMutation
from django_graphex.registry import Registry
from django_graphex.schema import DjangoGraphQLSchema
from django_graphex.types import DjangoModelType

from ._schema_isolation import isolated_pair
from .models import DummyModel


# --------------------------------------------------------------------------- #
# Models (distinct sets per path — same rationale as                          #
# test_explicit_null_and_json_input.py).                                       #
# --------------------------------------------------------------------------- #
class JAuthorBase(DummyModel):
    """An abstract author base carrying a nullable "prefs" JSONField.

    Shared by both the DjangoModelType-path and DjangoModelMutation-path
    concrete authors below.
    """

    name = models.CharField(max_length=100)
    prefs = models.JSONField(null=True, blank=True)

    class Meta:
        """Mark "JAuthorBase" abstract under the "tests" app label.

        Concrete subclasses provide their own table and Django model
        identity.
        """

        app_label = "tests"
        abstract = True


class JTAuthor(JAuthorBase):
    """DjangoModelType-path author with a JSONField.

    Backs "JTAuthorType" and the read-only schema used by the output and SDL
    tests.
    """


class JMAuthor(JAuthorBase):
    """DjangoModelMutation-path author with a JSONField.

    Backs "JMAuthorMutation" and the mutation schema used by the
    mutation-input tests.
    """


class JTAuthorType(DjangoModelType):
    """A "DjangoModelType" for "JTAuthor", exercising the raw-JSON output path.

    Compiled into "_jread_schema" so the OUTPUT type is queryable end-to-end.
    """

    class Meta:
        """Bind "JTAuthorType" to the "JTAuthor" model.

        No other options are set; this is the plain single-model
        configuration.
        """

        model = JTAuthor


# A read schema so the OUTPUT type is compiled and queryable end-to-end.
class _JReadQuery(ObjectType):
    """The root query exposing the "JTAuthorType" list resolver.

    Used exclusively by the OUTPUT and SDL test classes in this module.
    """

    __test__ = False
    authors = JTAuthorType.ListField()


_jread_schema = DjangoGraphQLSchema(query=_JReadQuery)


def _compiled_output_type() -> Any:
    """Return the compiled OUTPUT "GraphQLObjectType" for "JTAuthor".

    Returns:
        gql_type: The compiled "GraphQLObjectType" registered as
            "JTAuthorGenericType".
    """
    gql_schema = _jread_schema.graphql_schema
    return gql_schema.get_type("JTAuthorGenericType")


def _info() -> SimpleNamespace:
    """Build a bare GraphQL resolve-info stand-in for direct mutation calls.

    Returns:
        info: A namespace with the "context.META"/"context.FILES" shape the
            mutation resolvers read from.
    """
    return SimpleNamespace(context=SimpleNamespace(META={}, FILES={}))


def _type_create(type_cls: type[DjangoModelType], data: dict[str, Any]) -> Any:
    """Invoke "create" on a "DjangoModelType" host with the given input payload.

    Args:
        type_cls: The DjangoModelType class to call create on.
        data: The input field's payload, keyed by the host's input field name.

    Returns:
        result: The mutation result returned by "type_cls.create".
    """
    return type_cls.create(None, _info(), **{type_cls._meta.input_field_name: data})


def _type_update(type_cls: type[DjangoModelType], data: dict[str, Any]) -> Any:
    """Invoke "update" on a "DjangoModelType" host with the given input payload.

    Args:
        type_cls: The DjangoModelType class to call update on.
        data: The input field's payload, keyed by the host's input field name.

    Returns:
        result: The mutation result returned by "type_cls.update".
    """
    return type_cls.update(None, _info(), **{type_cls._meta.input_field_name: data})


# --- DjangoModelMutation path (real GraphQL execution) --------------------- #
_RMUT = Registry()


class JMAuthorMutation(DjangoModelMutation):
    """A "DjangoModelMutation" for "JMAuthor", exercising the raw-JSON input path.

    Compiled into "_jschema" so the mutation INPUT type is exercised
    end-to-end.
    """

    class Meta:
        """Bind "JMAuthorMutation" to "JMAuthor" under an isolated registry.

        The isolated registry keeps this schema's types separate from
        "_jread_schema".
        """

        model = JMAuthor
        registry = _RMUT


class _JQuery(ObjectType):
    """The root query exposing a static "hello" field for the mutation schema."""

    __test__ = False
    hello = field(GraphQLString)

    def resolve_hello(self, info: Any) -> str:
        """Resolve "hello" to the constant string "hi".

        Args:
            info: The GraphQL resolve info for the current request.

        Returns:
            value: The literal string "hi".
        """
        return "hi"


class _JRoot(ObjectType):
    """The root mutation exposing "JMAuthorMutation" create and update fields."""

    __test__ = False
    author_create = JMAuthorMutation.CreateField()
    author_update = JMAuthorMutation.UpdateField()


_jschema = DjangoGraphQLSchema(
    query=_JQuery, mutation=_JRoot, registries=isolated_pair(_RMUT)
)


def _gql(query: str, variables: dict[str, Any] | None = None) -> ExecutionResult:
    """Execute a GraphQL document against the mutation-path schema.

    Args:
        query: The raw GraphQL document to execute.
        variables: The variable values to bind, or None when the document has
            none.

    Returns:
        result: The graphql-core execution result for the document.
    """
    request = RequestFactory().post("/graphql/", content_type="application/json")
    return graphql_sync(
        _jschema.graphql_schema,
        query,
        context_value=request,
        variable_values=variables,
    )


def _unwrap(gql_type: GraphQLType) -> GraphQLType:
    """Strip a non-null wrapper from a GraphQL type, if present.

    Args:
        gql_type: The GraphQL type to unwrap.

    Returns:
        inner: The wrapped type when "gql_type" is a "GraphQLNonNull",
            otherwise "gql_type" unchanged.
    """
    return gql_type.of_type if isinstance(gql_type, GraphQLNonNull) else gql_type


# =========================================================================== #
# SDL — the model JSONField renders ``: JSON`` in all three positions          #
# =========================================================================== #
class JSONRawSDLTest(TestCase):
    """The model JSONField must print ": JSON" in all three SDL positions.

    Covers the OUTPUT type, the mutation INPUT type, and the filter INPUT
    type.
    """

    def test_output_sdl_is_json(self) -> None:
        """The OUTPUT type's "prefs" field must print as ": JSON", not ": JSONString".

        Guards the OUTPUT position of the three SDL positions covered by this
        class.
        """
        out_type = _compiled_output_type()
        sdl = print_type(out_type)
        self.assertIn("prefs: JSON", sdl)
        self.assertNotIn("prefs: JSONString", sdl)

    def test_mutation_input_sdl_is_json(self) -> None:
        """The mutation INPUT type's "prefs" field must compile to the "JSON" scalar.

        Guards the mutation-INPUT position of the three SDL positions covered
        by this class.
        """
        schema = build_model_schema(JTAuthor, partial=True)
        gql_input = compile_input_type(schema, name="JAuthorProbeInput")
        assert isinstance(gql_input, GraphQLInputObjectType)
        gql_type = _unwrap(gql_input.fields["prefs"].type)
        self.assertIsInstance(gql_type, GraphQLScalarType)
        self.assertEqual(gql_type.name, "JSON")

    def test_filter_input_sdl_is_json(self) -> None:
        """The filter INPUT type's "exact" lookup on "prefs" must print as ": JSON".

        Guards the filter-INPUT position of the three SDL positions covered
        by this class.
        """
        from django_graphex.filtering.native_schema import build_filter_input_type

        # Build the filter-input for a JSONField-bearing model. The JSON-derived
        # filter arg lives on the per-field "<Model><Field>Lookups" sub-input.
        filter_input = build_filter_input_type(
            JTAuthor,
            filter_fields={"prefs": ["exact"]},
            registry=Registry(),
        )
        assert filter_input is not None
        lookups_type = _unwrap(filter_input.fields["prefs"].type)
        sdl = print_type(lookups_type)
        # The exact-match filter arg on a JSONField is the raw "JSON" scalar.
        self.assertIn("exact: JSON", sdl)
        self.assertNotIn("JSONString", sdl)


# =========================================================================== #
# OUTPUT — a query returns the RAW nested structure (dict / list)              #
# =========================================================================== #
class JSONRawOutputTest(TestCase):
    """A query must return the JSONField value as a real nested structure.

    Covers both the full GraphQL execution path and the compiled resolver
    called directly.
    """

    def test_query_returns_raw_dict(self) -> None:
        """A query executed end-to-end must return "prefs" as a real dict, not a string.

        Exercises the full GraphQL execution path, distinct from the direct
        resolver test below.
        """
        JTAuthor.objects.create(name="A", prefs={"theme": "dark", "n": 3})
        result = graphql_sync(
            _jread_schema.graphql_schema,
            "query { authors { results { prefs } } }",
            context_value=RequestFactory().get("/graphql/"),
        )
        self.assertIsNone(result.errors)
        rows = result.data["authors"]["results"]
        self.assertEqual(rows[0]["prefs"], {"theme": "dark", "n": 3})
        # The wire payload carries a REAL dict, not a JSON-encoded string.
        self.assertIsInstance(rows[0]["prefs"], dict)

    def test_type_output_resolver_returns_dict(self) -> None:
        """The compiled output resolver for "prefs" must return a real dict directly.

        Drives the resolver directly, bypassing full GraphQL execution.
        """
        obj = JTAuthor.objects.create(name="A", prefs={"theme": "dark", "n": 3})
        # Drive the compiled output resolver directly.
        out_type = _compiled_output_type()
        resolver = out_type.fields["prefs"].resolve
        value = resolver(obj, _info())
        self.assertEqual(value, {"theme": "dark", "n": 3})
        self.assertIsInstance(value, dict)


# =========================================================================== #
# MUTATION INPUT — raw object via VARIABLE and via INLINE LITERAL              #
# =========================================================================== #
class JSONRawMutationInputTest(TestCase):
    """A create mutation must accept the raw JSON object via variable and inline literal.

    Covers a GraphQL variable, an inline object literal, an inline list
    literal, and a nested float literal, exercising "GdxJSON.parse_literal"
    end-to-end.
    """

    def test_create_via_variable_stores_dict(self) -> None:
        """A dict passed as a "$p: JSON" variable must be stored as a real dict.

        Covers the GraphQL-variable path, distinct from the inline-literal
        paths below.
        """
        result = _gql(
            "mutation ($p: JSON) { authorCreate(newJmauthor: "
            '{ name: "V" prefs: $p }) { ok errors { field messages } } }',
            variables={"p": {"k": "v", "n": 1}},
        )
        self.assertIsNone(result.errors)
        payload = result.data["authorCreate"]
        self.assertTrue(payload["ok"], msg=payload["errors"])
        obj = JMAuthor.objects.get(name="V")
        self.assertEqual(obj.prefs, {"k": "v", "n": 1})
        self.assertIsInstance(obj.prefs, dict)

    def test_create_via_inline_object_literal_stores_dict(self) -> None:
        """An inline object literal for "prefs" must be parsed and stored as a dict.

        Exercises the recursive "GdxJSON.parse_literal" for a nested object.
        """
        # Inline object literal — exercises the recursive GdxJSON.parse_literal.
        result = _gql(
            "mutation { authorCreate(newJmauthor: "
            '{ name: "L" prefs: { k: "v", nested: [1, 2] } }) '
            "{ ok errors { field messages } } }"
        )
        self.assertIsNone(result.errors)
        payload = result.data["authorCreate"]
        self.assertTrue(payload["ok"], msg=payload["errors"])
        obj = JMAuthor.objects.get(name="L")
        self.assertEqual(obj.prefs, {"k": "v", "nested": [1, 2]})

    def test_create_via_inline_list_literal_stores_list(self) -> None:
        """An inline list literal for "prefs" must be parsed and stored as a list.

        Exercises the recursive "GdxJSON.parse_literal" for a nested list
        with a mixed-type element.
        """
        result = _gql(
            "mutation { authorCreate(newJmauthor: "
            '{ name: "Li" prefs: [1, 2, { x: true }] }) '
            "{ ok errors { field messages } } }"
        )
        self.assertIsNone(result.errors)
        payload = result.data["authorCreate"]
        self.assertTrue(payload["ok"], msg=payload["errors"])
        obj = JMAuthor.objects.get(name="Li")
        self.assertEqual(obj.prefs, [1, 2, {"x": True}])
        self.assertIsInstance(obj.prefs, list)

    def test_create_via_inline_float_literal_stores_float(self) -> None:
        """A float literal nested in an inline object must be parsed and stored correctly.

        Exercises the FloatValueNode branch of "GdxJSON.parse_literal"
        end-to-end.
        """
        # A float literal nested in the inline object exercises the FloatValueNode
        # branch of GdxJSON.parse_literal end-to-end.
        result = _gql(
            "mutation { authorCreate(newJmauthor: "
            '{ name: "F" prefs: { ratio: 1.5 } }) '
            "{ ok errors { field messages } } }"
        )
        self.assertIsNone(result.errors)
        payload = result.data["authorCreate"]
        self.assertTrue(payload["ok"], msg=payload["errors"])
        obj = JMAuthor.objects.get(name="F")
        self.assertEqual(obj.prefs, {"ratio": 1.5})


# =========================================================================== #
# NESTED-VARIABLE-INSIDE-LITERAL — the $var lives inside an inline object/list  #
# literal, so graphql-core's ValuesOfCorrectTypeRule calls parse_literal at     #
# VALIDATION time with NO variables. parse_literal MUST NOT raise for the       #
# then-undefined variable — it must yield Undefined so validation passes; at    #
# execution time real variables are supplied and substitution happens.          #
# =========================================================================== #
class JSONRawNestedVariableTest(TestCase):
    """A "$var" nested inside an inline object/list literal must substitute correctly.

    graphql-core's ValuesOfCorrectTypeRule calls parse_literal at VALIDATION
    time with NO variables. "GdxJSON.parse_literal" must not raise for the
    then-undefined variable — it must yield Undefined so validation passes;
    at execution time real variables are supplied and substitution happens.
    """

    def test_variable_nested_in_object_literal_substitutes_at_execution(self) -> None:
        """A "$p" nested inside an object literal must substitute correctly at execution.

        Covers the object-literal container, distinct from the list-literal
        case below.
        """
        # $p is nested INSIDE the inline object literal (not the top-level value).
        result = _gql(
            "mutation ($p: JSON) { authorCreate(newJmauthor: "
            '{ name: "NV" prefs: { fixed: "y", dynamic: $p } }) '
            "{ ok errors { field messages } } }",
            variables={"p": [1, 2, 3]},
        )
        self.assertIsNone(result.errors)
        payload = result.data["authorCreate"]
        self.assertTrue(payload["ok"], msg=payload["errors"])
        obj = JMAuthor.objects.get(name="NV")
        self.assertEqual(obj.prefs, {"fixed": "y", "dynamic": [1, 2, 3]})

    def test_variable_nested_in_list_literal_substitutes_at_execution(self) -> None:
        """A "$p" nested inside a list literal must substitute correctly at execution.

        Covers the list-literal container, distinct from the object-literal
        case above.
        """
        result = _gql(
            "mutation ($p: JSON) { authorCreate(newJmauthor: "
            '{ name: "NVL" prefs: [1, $p, 3] }) '
            "{ ok errors { field messages } } }",
            variables={"p": {"deep": True}},
        )
        self.assertIsNone(result.errors)
        payload = result.data["authorCreate"]
        self.assertTrue(payload["ok"], msg=payload["errors"])
        obj = JMAuthor.objects.get(name="NVL")
        self.assertEqual(obj.prefs, [1, {"deep": True}, 3])

    def test_validation_only_nested_variable_is_clean(self) -> None:
        """Validation-only "parse_literal" (no variables bound) must not raise or error.

        graphql.validate calls parse_literal with NO variables — the nested
        $var must not fail ValuesOfCorrectTypeRule.
        """
        query = (
            "mutation ($p: JSON) { authorCreate(newJmauthor: "
            '{ name: "V" prefs: { extra: $p } }) '
            "{ ok errors { field messages } } }"
        )
        document = parse(query)
        errors = validate(_jschema.graphql_schema, document)
        self.assertEqual(errors, [])


# =========================================================================== #
# OMIT-vs-NULL contract preserved on the RAW-JSON field                        #
# =========================================================================== #
class JSONRawOmitNullTest(TestCase):
    """The omit-vs-null contract must be preserved on the raw-JSON field.

    Covers an omitted "prefs" key (untouched), an explicit null (clears the
    field), and a dict/list roundtrip through create.
    """

    def test_update_prefs_omitted_untouched(self) -> None:
        """Omitting "prefs" from an update payload must leave the stored value untouched.

        Covers the omit side of the omit-vs-null contract.
        """
        obj = JTAuthor.objects.create(name="A", prefs={"keep": True})
        result = _type_update(JTAuthorType, {"id": obj.id, "name": "A2"})
        self.assertTrue(result.ok, msg=getattr(result, "errors", None))
        obj.refresh_from_db()
        self.assertEqual(obj.prefs, {"keep": True})
        self.assertEqual(obj.name, "A2")

    def test_update_prefs_null_clears(self) -> None:
        """Setting "prefs" to null in an update payload must clear the stored value.

        Covers the null side of the omit-vs-null contract.
        """
        obj = JTAuthor.objects.create(name="A", prefs={"old": 1})
        result = _type_update(JTAuthorType, {"id": obj.id, "prefs": None})
        self.assertTrue(result.ok, msg=getattr(result, "errors", None))
        obj.refresh_from_db()
        self.assertIsNone(obj.prefs)

    def test_roundtrip_dict_and_list(self) -> None:
        """A "prefs" dict and a "prefs" list must both roundtrip through create unchanged.

        Confirms create is not restricted to one JSON container shape.
        """
        d = _type_create(JTAuthorType, {"name": "d", "prefs": {"a": 1}})
        self.assertTrue(d.ok, msg=getattr(d, "errors", None))
        self.assertEqual(JTAuthor.objects.get(name="d").prefs, {"a": 1})
        li = _type_create(JTAuthorType, {"name": "li", "prefs": [1, 2, 3]})
        self.assertTrue(li.ok, msg=getattr(li, "errors", None))
        self.assertEqual(JTAuthor.objects.get(name="li").prefs, [1, 2, 3])
