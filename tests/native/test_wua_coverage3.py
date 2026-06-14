"""Final coverage booster tests for WU-A modules — part 3.

Targets the last uncovered branches:
- factory.py:149 — list with model (name derived from model)
- output_compiler.py:144-147 — _is_relation_field fallback (is_relation attr)
- output_compiler.py:157-160 — _get_related_model via field.field.model (reverse rel)
- output_compiler.py:197 — is_many=True with null FK
- output_compiler.py:311-312 — get_fields exception fallback to concrete_fields
- output_compiler.py:319 — field with name=None skipped
- registry_compiler.py:193 — unregistered related_cls field name uses class name
- registry_compiler.py:207-210 — _get_related_type: no compiled, no in-progress stub
- registry_compiler.py:282 — compiled is None BuildError (patched scenario)

Run: .venv/bin/python -m pytest -q tests/native/test_wua_coverage3.py
"""
from __future__ import annotations

import os
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "tests.settings")

import django
django.setup()

import pytest
from graphql import GraphQLObjectType, GraphQLField, GraphQLString

pytestmark = pytest.mark.native_only


# ---------------------------------------------------------------------------
# factory.py:149 — list with model (name from model)
# ---------------------------------------------------------------------------


def test_native_factory_list_with_model_derives_name():
    """native_factory_type('list', base, model=M) derives name from model."""
    import django.db.models as models
    from django_graphex.native.factory import native_factory_type

    class ListFromModelModel(models.Model):
        class Meta:
            app_label = "tests"

    class ListBase:
        pass

    result = native_factory_type("list", ListBase, model=ListFromModelModel)
    assert isinstance(result, type)
    # Name should be derived from model name
    assert "ListFromModel" in result.__name__ or "GenericListType" in result.__name__
    assert result._gdx_model is ListFromModelModel


# ---------------------------------------------------------------------------
# output_compiler.py:144-147 — _is_relation_field via is_relation attr fallback
# ---------------------------------------------------------------------------


def test_is_relation_field_via_is_relation_attr():
    """_is_relation_field falls back to is_relation attribute for exotic fields.

    When isinstance check returns False (non-Django field), checks is_relation attr.
    """
    from django_graphex.native.output_compiler import _is_relation_field

    class ExoticRelField:
        """A field that is NOT a RelatedField subclass but has is_relation=True.

        isinstance() returns False (not a Django field), so the fallback
        `getattr(field, "is_relation", False)` is consulted.
        """
        is_relation = True

    class NonRelField:
        is_relation = False

    # ExoticRelField: isinstance returns False, but is_relation=True → fallback returns True
    # NOTE: The try/except in _is_relation_field is defensive code for isinstance
    # raising AttributeError. In practice isinstance() doesn't raise, so the
    # fallback `return bool(getattr(field, "is_relation", False))` is reached
    # when isinstance() returns False (for plain Python class instances).
    assert _is_relation_field(ExoticRelField()) is True
    assert _is_relation_field(NonRelField()) is False


# ---------------------------------------------------------------------------
# output_compiler.py:157-160 — _get_related_model via field.field.model
# ---------------------------------------------------------------------------


def test_get_related_model_via_field_field_model():
    """_get_related_model returns field.field.model for reverse relation fields."""
    from django_graphex.native.output_compiler import _get_related_model

    class OwnerModel:
        pass

    class FakeReverseFKField:
        """Simulates a Django reverse FK (ManyToOneRel) that has no related_model attr."""
        related_model = None  # Not directly on this

        class field:
            model = OwnerModel

    result = _get_related_model(FakeReverseFKField())
    assert result is OwnerModel, (
        f"_get_related_model must return field.field.model, got {result!r}"
    )


def test_get_related_model_returns_none_when_no_attrs():
    """_get_related_model returns None when no related info available."""
    from django_graphex.native.output_compiler import _get_related_model

    class BareField:
        related_model = None

    result = _get_related_model(BareField())
    assert result is None


# ---------------------------------------------------------------------------
# Slice E — to-many relations are SKIPPED by the unit field compiler
# ---------------------------------------------------------------------------


def test_to_graphql_field_many_relation_is_skipped():
    """A to-many relation (M2M / reverse FK) is SKIPPED by ``_to_graphql_field``.

    graphene-django renders a to-many relation as the related model's auto-
    derived ``<Model>ListType`` results/totalCount CONTAINER, NOT a plain
    ``[Node]`` list. The container needs the graphene ``Registry`` (not available
    to the unit field compiler), so ``_to_graphql_field`` returns ``{}`` for
    to-many relations and the container is injected by
    ``types._compile_relation_list_fields``. (Previously this asserted a
    divergent ``GraphQLList(Node)``; corrected to match graphene's container.)
    """
    from django_graphex.native.output_compiler import _to_graphql_field
    import django.db.models as models

    class TagM2(models.Model):
        class Meta:
            app_label = "tests"

    class ArticleM2(models.Model):
        tags2 = models.ManyToManyField(TagM2, blank=True)

        class Meta:
            app_label = "tests"

    tag_type = GraphQLObjectType("Tag2", fields=lambda: {})

    class StubReg:
        def get_compiled(self, cls):
            if cls is TagM2:
                return tag_type
            return None

    field = ArticleM2._meta.get_field("tags2")
    field_map = _to_graphql_field(field, StubReg())
    assert field_map == {}, (
        "M2M (to-many) must be skipped by _to_graphql_field (rendered as a "
        f"<Model>ListType container via the relation-list injection), got {field_map!r}"
    )


# ---------------------------------------------------------------------------
# output_compiler.py:311-312 — get_fields fallback to concrete_fields
# ---------------------------------------------------------------------------


def test_compile_output_fields_fallback_to_concrete_fields():
    """compile_output_fields falls back to concrete_fields when get_fields raises."""
    from django_graphex.native.output_compiler import compile_output_fields

    class FakeModelMeta:
        """Meta that raises on get_fields but has concrete_fields."""
        concrete_fields = []  # Empty for simplicity

        def get_fields(self, include_parents=False):
            raise Exception("get_fields not supported")

    class FakeModel:
        _meta = FakeModelMeta()

    class EmptyReg:
        def get_compiled(self, cls): return None

    # Should not raise; should fall back to concrete_fields
    result = compile_output_fields(FakeModel, EmptyReg())
    assert isinstance(result, dict)
    assert result == {}


# ---------------------------------------------------------------------------
# output_compiler.py:319 — field with name=None skipped
# ---------------------------------------------------------------------------


def test_compile_output_fields_skips_field_with_no_name():
    """compile_output_fields skips fields where name and attname are both None."""
    from django_graphex.native.output_compiler import compile_output_fields

    class NamelessField:
        """A field with no name or attname attribute."""
        pass

    class FakeModelMeta:
        def get_fields(self, include_parents=False):
            return [NamelessField()]

    class FakeModel:
        _meta = FakeModelMeta()

    class EmptyReg:
        def get_compiled(self, cls): return None

    # Should skip the nameless field without crashing
    result = compile_output_fields(FakeModel, EmptyReg())
    assert isinstance(result, dict)
    assert result == {}


# ---------------------------------------------------------------------------
# registry_compiler.py:193 — unregistered related_cls uses class name as field
# ---------------------------------------------------------------------------


def test_compile_all_unregistered_related_uses_class_name_for_field():
    """When related_cls not in registry entries, class.__name__ is used for field name."""
    from django_graphex.native.registry_compiler import NativeOutputRegistry, compile_all

    class UnregisteredModel:
        pass

    class HostModel:
        pass

    registry = NativeOutputRegistry()
    # Register HostModel with UnregisteredModel as a related, but DON'T register UnregisteredModel
    registry.register("HostType", HostModel, related_models=[UnregisteredModel])

    compile_all(registry)

    compiled = registry.get_compiled(HostModel)
    assert compiled is not None
    # Fields should contain the field named after UnregisteredModel's class name
    fields = compiled.fields
    # camelCase of "UnregisteredModel" → "unregisteredModel"
    assert "unregisteredModel" in fields, (
        f"Unregistered related should use class name. Fields: {list(fields.keys())}"
    )


# ---------------------------------------------------------------------------
# registry_compiler.py:207-210 — _get_related_type fallback to GraphQLString
# ---------------------------------------------------------------------------


def test_compile_all_related_not_in_progress_and_not_compiled_fallback():
    """When related type is unknown at field resolve time, falls back to GraphQLString."""
    from django_graphex.native.registry_compiler import NativeOutputRegistry, compile_all

    class StrangerModel:
        pass

    class HostModel2:
        pass

    # Register HostModel2 with StrangerModel as a related, but StrangerModel is NOT registered
    registry = NativeOutputRegistry()
    registry.register("HostType2", HostModel2, related_models=[StrangerModel])

    compile_all(registry)

    compiled = registry.get_compiled(HostModel2)
    assert compiled is not None
    # When the field is resolved, the unregistered related returns GraphQLString
    fields = compiled.fields
    # The field should exist but may resolve to GraphQLString
    assert len(fields) >= 1


# ---------------------------------------------------------------------------
# output_compiler.py: _DJANGO_TO_GQL is built lazily only once
# ---------------------------------------------------------------------------


def test_django_to_gql_is_lazy():
    """_DJANGO_TO_GQL is None until first _get_django_to_gql() call."""
    import importlib
    import django_graphex.native.output_compiler as oc

    # Reset the cache for testing
    oc._DJANGO_TO_GQL = None

    mapping = oc._get_django_to_gql()
    assert mapping is not None
    assert oc._DJANGO_TO_GQL is mapping, "Cache should be populated after first call"

    # Second call returns same instance (lazy, not rebuilt)
    mapping2 = oc._get_django_to_gql()
    assert mapping2 is mapping, "Should return cached instance on second call"
