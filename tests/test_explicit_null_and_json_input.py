# -*- coding: utf-8 -*-
"""Explicit-null update semantics + JSONField mutation-input coercion.

Two behavior changes (v2.0.0, GraphQL-spec-correct: omitted != null):

* Change 1 -- update mutations honour an explicit "null": a present "null"
  on a nullable scalar/FK sets the column NULL; an omitted key leaves the value
  untouched; "tags: null" clears an M2M (same as "tags: []"); "null" on a
  required field yields a clean validation ErrorType (never a 500); a nested
  "null" payload stays a no-op. Verified on both mutation paths
  ("DjangoModelMutation" and "DjangoModelType").

* Change 2 -- a model-derived "JSONField" mutation INPUT renders as the raw
  "JSON" scalar (v2 raw-JSON default; not plain "String" and not the
  string-encoded "JSONString") and round-trips a real Python object (dict AND
  list) to the column -- never a double-encoded JSON string.
"""

from types import SimpleNamespace

from django.db import models
from django.test import RequestFactory, TestCase
from graphql import (
    GraphQLInputObjectType,
    GraphQLNonNull,
    GraphQLScalarType,
    GraphQLString,
    graphql_sync,
    print_type,
)

from django_graphex.core import ObjectType, field
from django_graphex.core.fields import build_model_schema
from django_graphex.core.input_compiler import _python_type_to_gql, compile_input_type
from django_graphex.core.scalars import GdxJSON
from django_graphex.mutation import DjangoModelMutation
from django_graphex.registry import Registry
from django_graphex.schema import DjangoGraphQLSchema
from django_graphex.types import DjangoModelType

from ._schema_isolation import isolated_pair
from .models import DummyModel, Tag


# --------------------------------------------------------------------------- #
# Test models. Distinct model sets per mutation path so the DjangoModelType's   #
# auto-derived ``<Model>ListType`` (registered globally at class definition)    #
# never collides with the DjangoModelMutation's output list type on the SAME    #
# model name — a same-name double registration would break unrelated schema     #
# builds in the shared global output registry.                                  #
# --------------------------------------------------------------------------- #
class _AuthorBase(DummyModel):
    """An author whose ``bio`` is NULLABLE (so ``bio: null`` can clear it)."""

    name = models.CharField(max_length=100)  # required
    bio = models.TextField(null=True, blank=True)

    class Meta:
        app_label = "tests"
        abstract = True


class TAuthor(_AuthorBase):
    """DjangoModelType-path author.

    Exercised through "TAuthorType.create"/"update" directly.
    """


class MAuthor(_AuthorBase):
    """DjangoModelMutation-path author.

    Exercised through GraphQL mutations built by "MAuthorMutation".
    """


class TPost(DummyModel):
    """DjangoModelType-path post: nullable FK, required FK, M2M, JSONField.

    Exercised through "TPostType.create"/"update" directly.
    """

    title = models.CharField(max_length=200)
    author = models.ForeignKey(
        TAuthor, related_name="t_posts", on_delete=models.CASCADE
    )  # REQUIRED fk
    editor = models.ForeignKey(
        TAuthor,
        null=True,
        blank=True,
        related_name="t_edited_posts",
        on_delete=models.SET_NULL,
    )  # nullable fk
    tags = models.ManyToManyField(Tag, related_name="t_posts", blank=True)
    meta = models.JSONField(null=True, blank=True)


class MPost(DummyModel):
    """DjangoModelMutation-path post: nullable FK, required FK, M2M, JSONField.

    Exercised through GraphQL mutations built by "MPostMutation".
    """

    title = models.CharField(max_length=200)
    author = models.ForeignKey(
        MAuthor, related_name="m_posts", on_delete=models.CASCADE
    )  # REQUIRED fk
    editor = models.ForeignKey(
        MAuthor,
        null=True,
        blank=True,
        related_name="m_edited_posts",
        on_delete=models.SET_NULL,
    )  # nullable fk
    tags = models.ManyToManyField(Tag, related_name="m_posts", blank=True)
    meta = models.JSONField(null=True, blank=True)


# --------------------------------------------------------------------------- #
# DjangoModelType path (direct .create/.update with a raw coerced dict)         #
# --------------------------------------------------------------------------- #
class TAuthorType(DjangoModelType):
    """Serializer-backed GraphQL type wrapping "TAuthor" for the direct create/update path.

    Used by "_type_create"/"_type_update" to exercise Change 1 without
    going through GraphQL execution.
    """

    class Meta:
        """Meta options binding this type to the "TAuthor" model.

        No other options are set; defaults apply.
        """

        model = TAuthor


class TPostType(DjangoModelType):
    """Serializer-backed GraphQL type wrapping "TPost" for the direct create/update path.

    Used by "_type_create"/"_type_update" to exercise Change 1 without
    going through GraphQL execution.
    """

    class Meta:
        """Meta options binding this type to the "TPost" model.

        No other options are set; defaults apply.
        """

        model = TPost


def _info() -> SimpleNamespace:
    return SimpleNamespace(context=SimpleNamespace(META={}, FILES={}))


def _type_create(type_cls: type[DjangoModelType], data: dict) -> object:
    return type_cls.create(None, _info(), **{type_cls._meta.input_field_name: data})


def _type_update(type_cls: type[DjangoModelType], data: dict) -> object:
    return type_cls.update(None, _info(), **{type_cls._meta.input_field_name: data})


# --------------------------------------------------------------------------- #
# DjangoModelMutation path (GraphQL execution -- proves the coercion layer      #
# distinguishes omitted from explicit null)                                    #
# --------------------------------------------------------------------------- #
_RMUT = Registry()


class MAuthorMutation(DjangoModelMutation):
    """Create/update mutation for "MAuthor", registered on the isolated test registry.

    Used by "ExplicitNullMutationPathTest" to exercise Change 1 through
    real GraphQL execution.
    """

    class Meta:
        """Meta options binding this mutation to "MAuthor" and the isolated registry.

        Uses "_RMUT" so this test module's types never collide with the
        shared global registry.
        """

        model = MAuthor
        registry = _RMUT


class MPostMutation(DjangoModelMutation):
    """Create/update mutation for "MPost", registered on the isolated test registry.

    Used by "ExplicitNullMutationPathTest" and the JSONField round-trip
    tests to exercise Change 1 and Change 2 through real GraphQL execution.
    """

    class Meta:
        """Meta options binding this mutation to "MPost" and the isolated registry.

        Uses "_RMUT" so this test module's types never collide with the
        shared global registry.
        """

        model = MPost
        registry = _RMUT


class _MutQuery(ObjectType):
    """Minimal query root required to build a schema alongside the mutations under test."""

    __test__ = False
    hello = field(GraphQLString)

    def resolve_hello(self, info: object) -> str:
        """Resolve "hello" to a constant greeting.

        Args:
            info: The unused GraphQL resolve info passed by the executor.

        Returns:
            greeting: The literal string "hi".
        """
        return "hi"


class _MutRoot(ObjectType):
    """Mutation root exposing the author/post create and update fields under test."""

    __test__ = False
    author_create = MAuthorMutation.CreateField()
    author_update = MAuthorMutation.UpdateField()
    post_create = MPostMutation.CreateField()
    post_update = MPostMutation.UpdateField()


_mut_schema = DjangoGraphQLSchema(
    query=_MutQuery, mutation=_MutRoot, registries=isolated_pair(_RMUT)
)


def _gql(query: str) -> object:
    request = RequestFactory().post("/graphql/", content_type="application/json")
    return graphql_sync(_mut_schema.graphql_schema, query, context_value=request)


# =========================================================================== #
# Change 1 -- explicit-null update semantics                                   #
# =========================================================================== #
class ExplicitNullTypePathTest(TestCase):
    """ "DjangoModelType.update"/".create" -- raw coerced dict.

    Verifies the explicit-null-vs-omitted distinction (Change 1) on the
    direct type-method path, as opposed to the GraphQL mutation path.
    """

    def test_update_bio_null_clears_field(self) -> None:
        """An explicit "bio: None" in the update dict must clear the nullable field to NULL.

        If this breaks, an explicit null could be silently ignored instead
        of clearing the column.
        """
        author = TAuthor.objects.create(name="A", bio="original")
        result = _type_update(TAuthorType, {"id": author.id, "bio": None})
        self.assertTrue(result.ok, msg=getattr(result, "errors", None))
        author.refresh_from_db()
        self.assertIsNone(author.bio)

    def test_update_bio_omitted_keeps_field(self) -> None:
        """Omitting "bio" from the update dict must leave the existing value untouched.

        If this breaks, an update could wrongly clear fields the caller
        never mentioned, violating the omitted-vs-null distinction.
        """
        author = TAuthor.objects.create(name="A", bio="keep me")
        # ``bio`` absent from the dict = omitted.
        result = _type_update(TAuthorType, {"id": author.id, "name": "A2"})
        self.assertTrue(result.ok, msg=getattr(result, "errors", None))
        author.refresh_from_db()
        self.assertEqual(author.bio, "keep me")
        self.assertEqual(author.name, "A2")

    def test_update_nullable_fk_null_clears(self) -> None:
        """An explicit null on a nullable FK must clear it while leaving the required FK untouched.

        If this breaks, clearing an optional foreign key could
        inadvertently affect or fail to affect the correct column.
        """
        req = TAuthor.objects.create(name="req")
        ed = TAuthor.objects.create(name="ed")
        post = TPost.objects.create(title="t", author=req, editor=ed)
        result = _type_update(TPostType, {"id": post.id, "editor": None})
        self.assertTrue(result.ok, msg=getattr(result, "errors", None))
        post.refresh_from_db()
        self.assertIsNone(post.editor_id)
        self.assertEqual(post.author_id, req.id)  # required fk untouched

    def test_update_m2m_null_clears(self) -> None:
        """An explicit null on an M2M field must clear all related rows.

        If this breaks, "tags: null" could be ignored instead of behaving
        like an explicit empty-set clear.
        """
        req = TAuthor.objects.create(name="req")
        t1 = Tag.objects.create(label="t1")
        post = TPost.objects.create(title="t", author=req)
        post.tags.set([t1])
        result = _type_update(TPostType, {"id": post.id, "tags": None})
        self.assertTrue(result.ok, msg=getattr(result, "errors", None))
        self.assertEqual(post.tags.count(), 0)

    def test_update_m2m_empty_list_clears(self) -> None:
        """An explicit empty list on an M2M field must clear all related rows, matching "tags: null".

        If this breaks, the empty-list and explicit-null spellings of
        "clear the M2M" could diverge in behavior.
        """
        req = TAuthor.objects.create(name="req")
        t1 = Tag.objects.create(label="t1")
        post = TPost.objects.create(title="t", author=req)
        post.tags.set([t1])
        result = _type_update(TPostType, {"id": post.id, "tags": []})
        self.assertTrue(result.ok, msg=getattr(result, "errors", None))
        self.assertEqual(post.tags.count(), 0)

    def test_update_m2m_omitted_untouched(self) -> None:
        """Omitting the M2M field from the update dict must leave the existing relations untouched.

        If this breaks, an unrelated field update could wrongly clear
        relations the caller never mentioned.
        """
        req = TAuthor.objects.create(name="req")
        t1 = Tag.objects.create(label="t1")
        post = TPost.objects.create(title="t", author=req)
        post.tags.set([t1])
        result = _type_update(TPostType, {"id": post.id, "title": "t2"})
        self.assertTrue(result.ok, msg=getattr(result, "errors", None))
        self.assertEqual(list(post.tags.values_list("pk", flat=True)), [t1.pk])

    def test_update_required_field_null_is_validation_error(self) -> None:
        """An explicit null on a required field must fail validation cleanly, leaving the row unchanged.

        If this breaks, nulling a required field could either succeed
        silently (corrupting the row) or raise an unhandled exception
        instead of a clean validation error.
        """
        author = TAuthor.objects.create(name="A", bio="b")
        result = _type_update(TAuthorType, {"id": author.id, "name": None})
        self.assertFalse(result.ok)
        self.assertIn("name", {e.field for e in result.errors})
        author.refresh_from_db()
        self.assertEqual(author.name, "A")  # unchanged

    def test_create_explicit_null_on_nullable_field(self) -> None:
        """Creating with an explicit null on a nullable field must succeed and store NULL.

        If this breaks, create-time explicit nulls could be rejected or
        coerced to an empty string instead of a true NULL.
        """
        result = _type_create(TAuthorType, {"name": "C", "bio": None})
        self.assertTrue(result.ok, msg=getattr(result, "errors", None))
        obj = TAuthor.objects.get(name="C")
        self.assertIsNone(obj.bio)


class ExplicitNullMutationPathTest(TestCase):
    """ "DjangoModelMutation" via GraphQL -- coercion distinguishes omitted/null.

    Mirrors "ExplicitNullTypePathTest" but through the GraphQL execution
    path, proving the coercion layer itself (not just the type methods)
    honors the explicit-null-vs-omitted distinction.
    """

    def test_update_bio_null_clears_field(self) -> None:
        """A "bio: null" mutation argument must clear the nullable field to NULL.

        If this breaks, an explicit null sent over GraphQL could be
        dropped before reaching the update logic.
        """
        author = MAuthor.objects.create(name="A", bio="original")
        result = _gql(
            f"mutation {{ authorUpdate(newMauthor: {{ id: {author.id} bio: null }}) "
            "{ ok errors { field messages } } }"
        )
        self.assertIsNone(result.errors)
        payload = result.data["authorUpdate"]
        self.assertTrue(payload["ok"], msg=payload["errors"])
        author.refresh_from_db()
        self.assertIsNone(author.bio)

    def test_update_bio_omitted_keeps_field(self) -> None:
        """Omitting "bio" from the mutation input must leave the existing value untouched.

        If this breaks, the GraphQL coercion layer could treat an omitted
        argument as an implicit null instead of "leave unchanged".
        """
        author = MAuthor.objects.create(name="A", bio="keep me")
        result = _gql(
            f'mutation {{ authorUpdate(newMauthor: {{ id: {author.id} name: "A2" }}) '
            "{ ok errors { field messages } } }"
        )
        self.assertIsNone(result.errors)
        payload = result.data["authorUpdate"]
        self.assertTrue(payload["ok"], msg=payload["errors"])
        author.refresh_from_db()
        self.assertEqual(author.bio, "keep me")

    def test_update_m2m_null_clears(self) -> None:
        """A "tags: null" mutation argument must clear the M2M relation.

        If this breaks, an explicit M2M null sent over GraphQL could fail
        to clear the relation.
        """
        req = MAuthor.objects.create(name="req")
        t1 = Tag.objects.create(label="t1")
        post = MPost.objects.create(title="t", author=req)
        post.tags.set([t1])
        result = _gql(
            f"mutation {{ postUpdate(newMpost: {{ id: {post.id} tags: null }}) "
            "{ ok errors { field messages } } }"
        )
        self.assertIsNone(result.errors)
        payload = result.data["postUpdate"]
        self.assertTrue(payload["ok"], msg=payload["errors"])
        self.assertEqual(post.tags.count(), 0)

    def test_update_required_field_null_is_validation_error(self) -> None:
        """A "name: null" mutation argument on a required field must yield a clean ErrorType, never a top-level error.

        If this breaks, nulling a required field over GraphQL could crash
        the request (a 500-equivalent) instead of returning a structured
        validation error.
        """
        author = MAuthor.objects.create(name="A", bio="b")
        result = _gql(
            f"mutation {{ authorUpdate(newMauthor: {{ id: {author.id} name: null }}) "
            "{ ok errors { field messages } } }"
        )
        # A clean ErrorType response -- never a top-level 500/GraphQLError.
        self.assertIsNone(result.errors)
        payload = result.data["authorUpdate"]
        self.assertFalse(payload["ok"])
        self.assertIn("name", {e["field"] for e in payload["errors"]})


# =========================================================================== #
# Change 2 -- JSONField mutation-input coercion                                #
# =========================================================================== #
class JSONFieldInputSDLTest(TestCase):
    """A model-derived JSONField INPUT renders as the raw JSON scalar, not String.

    Verifies Change 2 at the schema-compilation level, before any mutation
    ever executes.
    """

    def test_python_type_mapping_via_build_model_schema(self) -> None:
        """A JSONField-derived input field must compile to the raw "JSON" scalar type.

        If this breaks, model-derived JSON input fields could compile to
        "String" or "JSONString" instead of the raw structured "JSON"
        scalar.
        """
        schema = build_model_schema(TPost, partial=True)
        gql_input = compile_input_type(schema, name="TPostProbeInput")
        assert isinstance(gql_input, GraphQLInputObjectType)
        meta_field = gql_input.fields["meta"]
        gql_type = meta_field.type
        if isinstance(gql_type, GraphQLNonNull):
            gql_type = gql_type.of_type
        self.assertIsInstance(gql_type, GraphQLScalarType)
        self.assertEqual(gql_type.name, "JSON")

    def test_input_sdl_renders_json(self) -> None:
        """The printed SDL for a create input must render "meta: JSON", never "String" or "JSONString".

        If this breaks, the generated schema's SDL could mislead clients
        about the actual accepted input shape for JSON fields.
        """
        # Compile the create-input directly (partial=False) and render its SDL.
        schema = build_model_schema(TPost, partial=False)
        gql_input = compile_input_type(schema, name="TPostCreateProbeInput")
        sdl = print_type(gql_input)
        # The JSONField-backed ``meta`` input field is the RAW ``JSON`` scalar.
        self.assertIn("meta: JSON", sdl)
        self.assertNotIn("meta: String", sdl)
        self.assertNotIn("meta: JSONString", sdl)


class JSONFieldRoundTripTypePathTest(TestCase):
    """The parsed Python object reaches the JSONField (never a JSON string).

    Covers the direct "DjangoModelType" create/update path with both dict
    and list JSON payloads.
    """

    def test_create_stores_dict(self) -> None:
        """Creating with a dict "meta" payload must store a real Python dict on the JSONField.

        If this breaks, the JSON payload could be stored as a
        double-encoded string instead of the structured Python object.
        """
        req = TAuthor.objects.create(name="req")
        result = _type_create(
            TPostType,
            {"title": "t", "author": req.pk, "meta": {"k": "v", "n": 1}},
        )
        self.assertTrue(result.ok, msg=getattr(result, "errors", None))
        obj = TPost.objects.get()
        self.assertEqual(obj.meta, {"k": "v", "n": 1})
        self.assertIsInstance(obj.meta, dict)

    def test_create_stores_list(self) -> None:
        """Creating with a list "meta" payload must store a real Python list on the JSONField.

        If this breaks, list-shaped JSON payloads specifically could be
        mishandled even if dict payloads work correctly.
        """
        req = TAuthor.objects.create(name="req")
        result = _type_create(
            TPostType,
            {"title": "t", "author": req.pk, "meta": [1, 2, {"x": True}]},
        )
        self.assertTrue(result.ok, msg=getattr(result, "errors", None))
        obj = TPost.objects.get()
        self.assertEqual(obj.meta, [1, 2, {"x": True}])
        self.assertIsInstance(obj.meta, list)

    def test_update_stores_dict(self) -> None:
        """Updating "meta" with a new dict payload must replace the stored value with a real Python dict.

        If this breaks, updating a JSONField could corrupt the existing
        value or store it double-encoded.
        """
        req = TAuthor.objects.create(name="req")
        post = TPost.objects.create(title="t", author=req, meta={"old": 1})
        result = _type_update(TPostType, {"id": post.id, "meta": {"new": 2}})
        self.assertTrue(result.ok, msg=getattr(result, "errors", None))
        post.refresh_from_db()
        self.assertEqual(post.meta, {"new": 2})


class JSONFieldRoundTripGraphQLTest(TestCase):
    """End-to-end through the coercion layer: an inline JSON literal becomes a dict.

    v2 raw-JSON: "meta" is the raw "JSON" scalar, so the client sends an
    inline object literal ("meta: { k: "v" }") -- not a JSON-encoded
    string -- and the recursive "GdxJSON.parse_literal" yields a real dict
    on the column.
    """

    def test_create_dict_through_graphql(self) -> None:
        """An inline "meta: { k: "v" }" mutation literal must land as a real Python dict on the column.

        If this breaks, the GraphQL execution path could store the JSON
        payload as a string instead of parsing it into a structured value.
        """
        req = MAuthor.objects.create(name="req")
        result = _gql(
            "mutation { postCreate(newMpost: { "
            f'title: "t" author: "{req.pk}" meta: {{ k: "v" }} '
            "}) { ok errors { field messages } } }"
        )
        self.assertIsNone(result.errors)
        payload = result.data["postCreate"]
        self.assertTrue(payload["ok"], msg=payload["errors"])
        obj = MPost.objects.get()
        self.assertEqual(obj.meta, {"k": "v"})
        self.assertIsInstance(obj.meta, dict)


class PythonTypeToGqlAnyTest(TestCase):
    """The JSONScalar->JSON mapping is scoped to the JSONField origin.

    Confirms the raw-JSON mapping only applies to the dedicated JSONField
    marker, not to every bare "Any"-typed field.
    """

    def test_json_marker_maps_to_raw_json(self) -> None:
        """The dedicated JSONField marker type must map to the raw "GdxJSON" scalar.

        If this breaks, model-derived JSON fields could map to the
        string-encoded "GdxJSONString" instead of the raw scalar.
        """
        from django_graphex.core.fields import JSONScalar

        # v2 RAW-JSON default: the JSONField marker maps to the raw ``JSON``
        # scalar (structured passthrough), NOT the string-encoded ``JSONString``.
        self.assertIs(_python_type_to_gql(JSONScalar), GdxJSON)

    def test_bare_any_still_falls_back_to_string(self) -> None:
        """A bare "Any"-typed field (not the JSONField marker) must still map to plain "GraphQLString".

        If this breaks, the raw-JSON mapping fix could over-match and
        hijack every "Any"-typed field instead of only the JSONField
        marker.
        """
        from typing import Any

        from graphql import GraphQLString

        # A user's bare ``Any``-typed field is NOT hijacked to JSON: the fix is
        # scoped to the dedicated JSONField marker, not all of ``Any``.
        self.assertIs(_python_type_to_gql(Any), GraphQLString)

    def test_json_scalar_importable_from_core(self) -> None:
        """ "GdxJSON" must be importable from "django_graphex.core" as a stable public re-export.

        If this breaks, callers relying on the documented import path
        would get an ImportError instead of the scalar.
        """
        from django_graphex.core import GdxJSON as exported

        self.assertIs(exported, GdxJSON)

    def test_jsonstring_escape_hatch_still_importable(self) -> None:
        """The "GdxJSONString" escape hatch must remain importable from "django_graphex.core" for "as_str=True" users.

        If this breaks, users who opted into the string-encoded JSON
        escape hatch would lose access to it.
        """
        # The ``JSONString`` escape hatch remains available for ``as_str=True``.
        from django_graphex.core import GdxJSONString as exported
        from django_graphex.core.scalars import GdxJSONString

        self.assertIs(exported, GdxJSONString)
