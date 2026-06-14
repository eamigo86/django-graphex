"""Additional coverage tests for WU-A modules to hit ≥95% branch coverage.

Covers uncovered branches in:
- native/bridge.py: assert_gdx_bridge, _MetaView AttributeError branches
- native/output_compiler.py: nullable FK, M2M, unknown field type, ForeignObjectRel
- native/registry_compiler.py: model_rebuild, already-compiled early return, in-progress stub
- native/compat.py: NativeTypeAliasMixin with no extensions
- native/factory.py: unknown op ValueError, input NotImplementedError

Run: .venv/bin/python -m pytest -q tests/native/test_wua_coverage.py
"""
from __future__ import annotations

import os
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "tests.settings")

import django
django.setup()

import pytest
from graphql import GraphQLObjectType, GraphQLSchema, GraphQLField, GraphQLString

pytestmark = pytest.mark.native_only


# ---------------------------------------------------------------------------
# bridge.py: assert_gdx_bridge
# ---------------------------------------------------------------------------


def test_assert_gdx_bridge_passes_with_gdx_types():
    """assert_gdx_bridge does not raise when all object types have extensions['gdx']."""
    from django_graphex.native.bridge import assert_gdx_bridge, GdxPayload
    from django_graphex.native.ir import GdxMeta

    payload = GdxPayload(GdxMeta())
    type_a = GraphQLObjectType(
        "TypeA",
        fields=lambda: {"field": GraphQLField(GraphQLString)},
        extensions={"gdx": payload},
    )
    schema = GraphQLSchema(query=type_a)
    # Should not raise
    assert_gdx_bridge(schema)


def test_assert_gdx_bridge_raises_on_missing_gdx():
    """assert_gdx_bridge raises AssertionError when a type lacks extensions['gdx']."""
    from django_graphex.native.bridge import assert_gdx_bridge

    type_x = GraphQLObjectType(
        "TypeX",
        fields=lambda: {"field": GraphQLField(GraphQLString)},
    )
    schema = GraphQLSchema(query=type_x)
    with pytest.raises(AssertionError) as exc_info:
        assert_gdx_bridge(schema)
    assert "TypeX" in str(exc_info.value)


def test_meta_view_attribute_error_on_private():
    """_MetaView raises AttributeError immediately for underscore-prefixed names."""
    from django_graphex.native.bridge import _MetaView
    from types import SimpleNamespace

    view = _MetaView(SimpleNamespace())
    with pytest.raises(AttributeError):
        _ = view._private_attr


def test_meta_view_attribute_error_when_gdx_meta_missing_attr():
    """_MetaView raises AttributeError when spec does not have the attr."""
    from django_graphex.native.bridge import _MetaView
    from types import SimpleNamespace

    # 'model' is in allowlist but not on spec
    spec = SimpleNamespace()  # No 'model' attr
    view = _MetaView(spec)
    with pytest.raises(AttributeError):
        _ = view.model


# ---------------------------------------------------------------------------
# output_compiler.py: uncovered branches
# ---------------------------------------------------------------------------


def _get_django_models():
    from django.db import models
    return models


def test_nullable_fk_field_no_non_null_wrapper():
    """Nullable FK field (null=True) does NOT get GraphQLNonNull wrapper."""
    from django_graphex.native.output_compiler import _to_graphql_field
    from graphql import GraphQLNonNull
    import django.db.models as models

    class RelatedModel(models.Model):
        class Meta:
            app_label = "tests"

    class OwnerModel(models.Model):
        related = models.ForeignKey(
            RelatedModel, on_delete=models.SET_NULL, null=True
        )

        class Meta:
            app_label = "tests"

    class StubReg:
        def get_compiled(self, cls):
            return GraphQLObjectType("Related", fields=lambda: {})

    field = OwnerModel._meta.get_field("related")
    field_map = _to_graphql_field(field, StubReg())
    assert len(field_map) == 1
    key, gql_field = next(iter(field_map.items()))
    # Nullable FK should NOT be wrapped in NonNull
    assert not isinstance(gql_field.type, GraphQLNonNull), (
        "Nullable FK must not be wrapped in GraphQLNonNull"
    )


def test_m2m_field_is_skipped_by_unit_compiler():
    """ManyToManyField is SKIPPED by ``_to_graphql_field`` (Slice E).

    graphene-django renders a to-many relation as the related model's auto-
    derived ``<Model>ListType`` results/totalCount CONTAINER — NOT a plain
    ``[Node]`` list. Building that container needs the graphene ``Registry``
    (``get_or_create_list_object_type``), which the unit field compiler does not
    have, so ``_to_graphql_field`` deliberately returns ``{}`` for to-many
    relations; the container field is injected separately by
    ``types._compile_relation_list_fields``. (Previously this asserted a
    divergent ``GraphQLList(Node)`` — weakened to match graphene's container.)
    """
    from django_graphex.native.output_compiler import _to_graphql_field
    import django.db.models as models

    class TagModel(models.Model):
        class Meta:
            app_label = "tests"

    class ArticleModel(models.Model):
        tags = models.ManyToManyField(TagModel, blank=True)

        class Meta:
            app_label = "tests"

    tag_type = GraphQLObjectType("Tag", fields=lambda: {})

    class StubReg:
        def get_compiled(self, cls):
            if cls is TagModel:
                return tag_type
            return None

    field = ArticleModel._meta.get_field("tags")
    field_map = _to_graphql_field(field, StubReg())
    assert field_map == {}, (
        "M2M (to-many) must be skipped by _to_graphql_field — it is rendered as "
        f"a <Model>ListType container via the relation-list injection, got {field_map!r}"
    )


def test_unknown_field_type_returns_empty_dict():
    """Unknown field types return an empty dict (skipped gracefully)."""
    from django_graphex.native.output_compiler import _to_graphql_field

    class FakeUnknownField:
        name = "unknown_field"
        null = False
        blank = False
        primary_key = False
        auto_created = False
        is_relation = False

    class StubReg:
        def get_compiled(self, cls):
            return None

    # FakeUnknownField's type is not in DJANGO_TO_GQL
    field = FakeUnknownField()
    result = _to_graphql_field(field, StubReg())
    assert result == {}, (
        "Unknown field types must return empty dict (skipped gracefully)"
    )


def test_fk_unregistered_related_model_returns_string_fallback():
    """FK field where registry returns None for related model → GraphQLString fallback."""
    from django_graphex.native.output_compiler import _to_graphql_field
    import django.db.models as models

    class UnrelatedModel(models.Model):
        class Meta:
            app_label = "tests"

    class OwnerModel2(models.Model):
        ref = models.ForeignKey(
            UnrelatedModel, on_delete=models.CASCADE, null=True
        )

        class Meta:
            app_label = "tests"

    class EmptyReg:
        def get_compiled(self, cls):
            return None  # Not in registry

    field = OwnerModel2._meta.get_field("ref")
    field_map = _to_graphql_field(field, EmptyReg())
    assert len(field_map) == 1
    key, gql_field = next(iter(field_map.items()))
    # Should fall back to GraphQLString (not crash)
    from graphql import GraphQLNonNull, GraphQLList
    t = gql_field.type
    while isinstance(t, (GraphQLNonNull, GraphQLList)):
        t = t.of_type
    assert t is GraphQLString, (
        f"Unregistered FK should fall back to GraphQLString, got {t!r}"
    )


def test_compile_output_fields_excludes_fields():
    """compile_output_fields respects exclude_fields."""
    import django.db.models as models
    from django_graphex.native.output_compiler import compile_output_fields

    class ExcludeModel(models.Model):
        name = models.CharField(max_length=100)
        secret = models.CharField(max_length=100)

        class Meta:
            app_label = "tests"

    class EmptyReg:
        def get_compiled(self, cls):
            return None

    fields = compile_output_fields(
        ExcludeModel, EmptyReg(), exclude_fields=["secret"]
    )
    assert "secret" not in fields
    assert "name" in fields or "Name" in fields  # case may vary


# ---------------------------------------------------------------------------
# registry_compiler.py: uncovered branches
# ---------------------------------------------------------------------------


def test_compile_already_compiled_returns_early():
    """_compile_one returns immediately if model_cls already compiled."""
    from django_graphex.native.registry_compiler import (
        NativeOutputRegistry,
        _compile_one,
    )

    registry = NativeOutputRegistry()

    class ModelZ:
        pass

    # Pre-populate compiled
    existing_type = GraphQLObjectType("NodeZ", fields=lambda: {})
    registry.set_compiled(ModelZ, existing_type)

    result = _compile_one("NodeZ", ModelZ, [], registry)
    assert result is existing_type


def test_compile_all_with_pydantic_model_rebuild():
    """compile_all calls model_rebuild on classes that support it (no crash)."""
    from django_graphex.native.registry_compiler import NativeOutputRegistry, compile_all

    class PydanticLikeModel:
        """Simulates a Pydantic model with model_rebuild."""
        _rebuilt = False

        @classmethod
        def model_rebuild(cls):
            cls._rebuilt = True

    registry = NativeOutputRegistry()
    registry.register("PydanticNode", PydanticLikeModel)
    compile_all(registry)

    assert PydanticLikeModel._rebuilt, "model_rebuild must be called on Pydantic-like classes"


def test_compile_all_multiple_types_all_compiled():
    """compile_all compiles all registered types."""
    from django_graphex.native.registry_compiler import NativeOutputRegistry, compile_all

    class ModelP:
        pass

    class ModelQ:
        pass

    registry = NativeOutputRegistry()
    registry.register("NodeP", ModelP)
    registry.register("NodeQ", ModelQ)

    compile_all(registry)

    assert registry.get_compiled(ModelP) is not None
    assert registry.get_compiled(ModelQ) is not None


# ---------------------------------------------------------------------------
# compat.py: NativeTypeAliasMixin with no extensions
# ---------------------------------------------------------------------------


def test_native_type_alias_mixin_no_extensions_returns_none():
    """NativeTypeAliasMixin.graphene_type returns None when no extensions."""
    from django_graphex.native.compat import NativeTypeAliasMixin

    class NoExtensionsType(NativeTypeAliasMixin):
        pass  # No extensions attribute

    t = NoExtensionsType()
    # Should return None, not raise
    result = t.graphene_type
    assert result is None, "graphene_type alias must return None when no extensions"


def test_gdx_meta_raises_when_extensions_has_no_gdx():
    """_gdx_meta raises AttributeError when extensions dict has no 'gdx' key."""
    from django_graphex.native.compat import _gdx_meta

    class TypeWithEmptyExtensions:
        extensions = {}  # No 'gdx' key

    with pytest.raises(AttributeError):
        _gdx_meta(TypeWithEmptyExtensions())


# ---------------------------------------------------------------------------
# factory.py: ValueError for unknown op
# ---------------------------------------------------------------------------


def test_native_factory_type_unknown_op_raises():
    """native_factory_type raises ValueError for unknown op."""
    from django_graphex.native.factory import native_factory_type

    with pytest.raises(ValueError, match="unknown op"):
        native_factory_type("unknown_op", object)


def test_native_factory_type_output_without_model():
    """native_factory_type('output', base) works without a model."""
    from django_graphex.native.factory import native_factory_type

    class BaseType:
        pass

    result = native_factory_type("output", BaseType)
    assert isinstance(result, type)
    assert issubclass(result, BaseType)


def test_native_factory_type_list_without_model():
    """native_factory_type('list', base) works without a model."""
    from django_graphex.native.factory import native_factory_type

    class ListBase:
        pass

    result = native_factory_type("list", ListBase)
    assert isinstance(result, type)
    # _gdx_list_fields should have all three standard fields
    assert hasattr(result, "_gdx_list_fields")
    fields = result._gdx_list_fields
    assert "results_field_name" in fields
    assert "totalCount" in fields
    assert "pageInfo" in fields


def test_native_factory_type_output_with_custom_name():
    """native_factory_type('output', ..., name='Custom') uses the given name."""
    from django_graphex.native.factory import native_factory_type

    class BaseType:
        pass

    result = native_factory_type("output", BaseType, name="CustomOutputType")
    assert result.__name__ == "CustomOutputType"
    assert result._gdx_name == "CustomOutputType"


def test_native_factory_type_list_with_custom_results_field():
    """native_factory_type('list', ..., results_field_name='items') uses custom name."""
    from django_graphex.native.factory import native_factory_type

    class ListBase:
        pass

    result = native_factory_type("list", ListBase, results_field_name="items")
    assert result._gdx_results_field_name == "items"
    assert result._gdx_list_fields["results_field_name"] == "items"
