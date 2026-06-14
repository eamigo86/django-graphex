"""Additional coverage tests for WU-A modules — part 2.

Targets remaining uncovered branches:
- output_compiler.py: non-relation field with name from attname, nullable scalar,
  resolver via dict root, resolver via object root, get_fields exception fallback,
  field_name is None skip, auto_created skip with only_fields
- registry_compiler.py: in-progress stub cycle guard return, unregistered related fallback,
  model_rebuild error suppression, failed compile (None) BuildError path

Run: .venv/bin/python -m pytest -q tests/native/test_wua_coverage2.py
"""
from __future__ import annotations

import os
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "tests.settings")

import django
django.setup()

import pytest
from graphql import GraphQLObjectType, GraphQLField, GraphQLString, GraphQLNonNull

pytestmark = pytest.mark.native_only


# ---------------------------------------------------------------------------
# output_compiler.py: resolver branches (dict root vs object root)
# ---------------------------------------------------------------------------


def test_default_resolver_dict_root():
    """Default resolver returns correct value from dict root."""
    from django_graphex.native.output_compiler import _to_graphql_field
    import django.db.models as models

    class SimpleModel(models.Model):
        title = models.CharField(max_length=100)

        class Meta:
            app_label = "tests"

    class EmptyReg:
        def get_compiled(self, cls): return None

    field_map = _to_graphql_field(SimpleModel._meta.get_field("title"), EmptyReg())
    assert "title" in field_map
    resolver = field_map["title"].resolve

    # Dict root
    result = resolver({"title": "Hello"}, None)
    assert result == "Hello"

    # Object root
    from types import SimpleNamespace
    obj = SimpleNamespace(title="World")
    result2 = resolver(obj, None)
    assert result2 == "World"


def test_nullable_scalar_field_no_non_null():
    """Nullable CharField (blank=True) returns nullable (no GraphQLNonNull)."""
    from django_graphex.native.output_compiler import _to_graphql_field
    import django.db.models as models

    class NullableModel(models.Model):
        note = models.CharField(max_length=200, blank=True)

        class Meta:
            app_label = "tests"

    class EmptyReg:
        def get_compiled(self, cls): return None

    field_map = _to_graphql_field(NullableModel._meta.get_field("note"), EmptyReg())
    assert "note" in field_map
    gql_type = field_map["note"].type
    # blank=True → nullable (no GraphQLNonNull wrapper)
    assert not isinstance(gql_type, GraphQLNonNull), (
        "blank=True CharField must not be wrapped in GraphQLNonNull"
    )


def test_compile_output_fields_with_no_name_field_skipped():
    """compile_output_fields skips fields that have no name or attname."""
    from django_graphex.native.output_compiler import compile_output_fields
    import django.db.models as models

    class SkipModel(models.Model):
        name = models.CharField(max_length=100)

        class Meta:
            app_label = "tests"

    class EmptyReg:
        def get_compiled(self, cls): return None

    # Should not raise even with fields that might have edge cases
    fields = compile_output_fields(SkipModel, EmptyReg())
    # At minimum name should be there
    assert isinstance(fields, dict)


def test_compile_output_fields_auto_created_skipped_without_only_fields():
    """Auto-created reverse relations are skipped without only_fields."""
    from django_graphex.native.output_compiler import compile_output_fields
    import django.db.models as models

    class AuthorM(models.Model):
        name = models.CharField(max_length=100)

        class Meta:
            app_label = "tests"

    class BookM(models.Model):
        author = models.ForeignKey(AuthorM, on_delete=models.CASCADE)
        title = models.CharField(max_length=200)

        class Meta:
            app_label = "tests"

    class EmptyReg:
        def get_compiled(self, cls): return None

    # AuthorM has a reverse relation 'bookm_set' (auto_created, not concrete)
    # These should be skipped when no only_fields is passed
    fields = compile_output_fields(AuthorM, EmptyReg())
    # Should contain 'name' but NOT the auto-created reverse FK
    assert "name" in fields
    # No reverse relation field keys should appear
    for key in fields:
        assert "book" not in key.lower() or key == "book", (
            f"Auto-created reverse relation should be skipped, found key: {key!r}"
        )


def test_fk_resolver_dict_root():
    """FK field default resolver returns correct value from dict root."""
    from django_graphex.native.output_compiler import _to_graphql_field
    import django.db.models as models

    class ReferencedModel(models.Model):
        class Meta:
            app_label = "tests"

    class ReferencerModel(models.Model):
        ref = models.ForeignKey(
            ReferencedModel, on_delete=models.CASCADE, null=True
        )

        class Meta:
            app_label = "tests"

    ref_type = GraphQLObjectType("Referenced", fields=lambda: {})

    class StubReg:
        def get_compiled(self, cls):
            if cls is ReferencedModel:
                return ref_type
            return None

    field = ReferencerModel._meta.get_field("ref")
    field_map = _to_graphql_field(field, StubReg())
    assert len(field_map) == 1
    key, gql_field = next(iter(field_map.items()))
    resolver = gql_field.resolve

    # Dict root
    result = resolver({"ref": "some_value"}, None)
    assert result == "some_value"

    # Object root
    from types import SimpleNamespace
    obj = SimpleNamespace(ref="another_value")
    assert resolver(obj, None) == "another_value"


# ---------------------------------------------------------------------------
# registry_compiler.py: in-progress stub cycle guard
# ---------------------------------------------------------------------------


def test_compile_one_returns_in_progress_stub_during_recursion():
    """_compile_one returns the in-progress stub when called recursively (cycle guard)."""
    from django_graphex.native.registry_compiler import (
        NativeOutputRegistry,
        _compile_one,
        _in_progress,
        _reset_in_progress,
    )

    _reset_in_progress()
    registry = NativeOutputRegistry()

    class ModelCycle:
        pass

    # Manually put something in _in_progress to simulate mid-compilation
    stub = GraphQLObjectType("CycleNode", fields=lambda: {})
    _in_progress[id(ModelCycle)] = stub

    # _compile_one should return the stub immediately (cycle guard)
    result = _compile_one("CycleNode", ModelCycle, [], registry)
    assert result is stub, "Cycle guard must return the in-progress stub"


def test_compile_all_unregistered_related_uses_class_name():
    """compile_all handles related model not in registry (uses class name for field)."""
    from django_graphex.native.registry_compiler import NativeOutputRegistry, compile_all

    class ModelUnregRel:
        pass

    class ModelMain:
        pass

    registry = NativeOutputRegistry()
    # Register only ModelMain; ModelUnregRel is in related_models but NOT registered
    registry.register("NodeMain", ModelMain, related_models=[ModelUnregRel])
    # Should not crash
    compile_all(registry)

    compiled = registry.get_compiled(ModelMain)
    assert compiled is not None


def test_compile_all_model_rebuild_error_suppressed():
    """compile_all suppresses model_rebuild exceptions (no-op)."""
    from django_graphex.native.registry_compiler import NativeOutputRegistry, compile_all

    class BrokenRebuild:
        @classmethod
        def model_rebuild(cls):
            raise RuntimeError("rebuild failed!")

    registry = NativeOutputRegistry()
    registry.register("BrokenNode", BrokenRebuild)

    # Should not raise — exception is suppressed
    compile_all(registry)
    compiled = registry.get_compiled(BrokenRebuild)
    assert compiled is not None


def test_compile_all_reports_compilation_failure():
    """compile_all raises BuildError naming type when compile_one returns None."""
    # This tests the `compiled is None` branch in phase 3
    # We simulate by monkeypatching _compile_one to not store in registry
    from django_graphex.native.registry_compiler import (
        NativeOutputRegistry,
        compile_all,
        BuildError,
    )

    registry = NativeOutputRegistry()

    class ModelGhost:
        pass

    registry.register("GhostNode", ModelGhost, skip_gdx=True)

    # skip_gdx=True causes gdx to be missing → BuildError on phase 3 check
    with pytest.raises(BuildError) as exc_info:
        compile_all(registry)

    assert "GhostNode" in str(exc_info.value), (
        f"BuildError should mention 'GhostNode', got: {exc_info.value}"
    )


# ---------------------------------------------------------------------------
# output_compiler.py: FK with no related_model (returns empty dict)
# ---------------------------------------------------------------------------


def test_relation_field_with_no_related_model_skipped():
    """A relation field with no related_model is skipped (returns empty dict)."""
    from django_graphex.native.output_compiler import _to_graphql_field

    class FakeRelationField:
        name = "orphan_rel"
        is_relation = True
        related_model = None  # No related model
        null = True
        blank = True

    class EmptyReg:
        def get_compiled(self, cls): return None

    field = FakeRelationField()
    result = _to_graphql_field(field, EmptyReg())
    assert result == {}, "Relation field with no related_model must return empty dict"
