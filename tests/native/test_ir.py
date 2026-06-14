"""Tests for native/ir.py — pure-Python IR dataclasses.

No Django settings required. No django_db markers.
Run with: pytest tests/native/test_ir.py -x
"""
import pathlib
import sys
import subprocess


# ---------------------------------------------------------------------------
# No-import gate: ir.py must import zero symbols from django/graphene/graphql
# ---------------------------------------------------------------------------

def test_ir_has_no_django_graphene_graphql_imports():
    """rg gate: no forbidden top-level imports in ir.py."""
    import re
    import pathlib

    ir_path = pathlib.Path(__file__).parent.parent.parent / "django_graphex" / "native" / "ir.py"
    src = ir_path.read_text()
    forbidden = re.compile(r"^(from django[.\s]|import django[.\s]|from graphene[.\s]|import graphene[.\s]|from graphql[.\s]|import graphql[.\s])", re.MULTILINE)
    matches = forbidden.findall(src)
    assert matches == [], f"Forbidden imports found in ir.py: {matches}"


def test_ir_importable_without_django_settings():
    """ir.py must be importable with DJANGO_SETTINGS_MODULE unset.

    Uses importlib to load the file directly, bypassing django_graphex/__init__.py.
    The module is registered in sys.modules so @dataclass resolves __module__
    correctly.
    """
    import importlib.util
    import os

    ir_path = pathlib.Path(__file__).parent.parent.parent / "django_graphex" / "native" / "ir.py"
    mod_name = "_test_ir_standalone_no_django"
    spec = importlib.util.spec_from_file_location(mod_name, str(ir_path))
    mod = importlib.util.module_from_spec(spec)
    # Register before exec so @dataclass can resolve __module__ from sys.modules
    sys.modules[mod_name] = mod
    try:
        # Must not raise ImproperlyConfigured or any Django-related error
        spec.loader.exec_module(mod)
    finally:
        sys.modules.pop(mod_name, None)
    # Verify all expected names are present
    for name in ("TypeRef", "FieldSpec", "TypeSpec", "EnumSpec", "GdxMeta"):
        assert hasattr(mod, name), f"Missing: {name}"


# ---------------------------------------------------------------------------
# TypeRef
# ---------------------------------------------------------------------------

class TestTypeRef:
    def test_basic_creation(self):
        from django_graphex.native.ir import TypeRef
        ref = TypeRef(name="String")
        assert ref.name == "String"
        assert ref.list is False
        assert ref.non_null is False
        assert ref.inner is None

    def test_non_null(self):
        from django_graphex.native.ir import TypeRef
        ref = TypeRef(name="Int", non_null=True)
        assert ref.non_null is True

    def test_list_of_non_null(self):
        from django_graphex.native.ir import TypeRef
        inner = TypeRef(name="String", non_null=True)
        ref = TypeRef(name="String", list=True, inner=inner)
        assert ref.list is True
        assert ref.inner is inner

    def test_frozen(self):
        from django_graphex.native.ir import TypeRef
        import dataclasses
        ref = TypeRef(name="String")
        with __import__("pytest").raises((dataclasses.FrozenInstanceError, TypeError, AttributeError)):
            ref.name = "Int"  # type: ignore[misc]

    def test_equality(self):
        from django_graphex.native.ir import TypeRef
        assert TypeRef(name="String") == TypeRef(name="String")
        assert TypeRef(name="String") != TypeRef(name="Int")

    def test_hashable(self):
        from django_graphex.native.ir import TypeRef
        s = {TypeRef(name="String"), TypeRef(name="String")}
        assert len(s) == 1


# ---------------------------------------------------------------------------
# GdxMeta
# ---------------------------------------------------------------------------

class TestGdxMeta:
    def test_defaults(self):
        from django_graphex.native.ir import GdxMeta
        meta = GdxMeta()
        assert meta.model is None
        assert meta.max_deep is None
        assert meta.complexity is None
        assert meta.name is None

    def test_with_values(self):
        from django_graphex.native.ir import GdxMeta
        meta = GdxMeta(max_deep=5, complexity=2, name="MyType")
        assert meta.max_deep == 5
        assert meta.complexity == 2
        assert meta.name == "MyType"

    def test_frozen(self):
        from django_graphex.native.ir import GdxMeta
        import dataclasses
        meta = GdxMeta(max_deep=3)
        with __import__("pytest").raises((dataclasses.FrozenInstanceError, TypeError, AttributeError)):
            meta.max_deep = 5  # type: ignore[misc]


# ---------------------------------------------------------------------------
# FieldSpec
# ---------------------------------------------------------------------------

class TestFieldSpec:
    def test_basic(self):
        from django_graphex.native.ir import FieldSpec, TypeRef
        field = FieldSpec(name="title", type=TypeRef(name="String"))
        assert field.name == "title"
        assert field.description is None
        assert field.resolver is None
        assert field.gdx is None

    def test_with_resolver(self):
        from django_graphex.native.ir import FieldSpec, TypeRef
        resolver = lambda root, info: "hello"
        field = FieldSpec(name="name", type=TypeRef(name="String"), resolver=resolver)
        assert field.resolver is resolver

    def test_frozen(self):
        from django_graphex.native.ir import FieldSpec, TypeRef
        import dataclasses
        field = FieldSpec(name="x", type=TypeRef(name="String"))
        with __import__("pytest").raises((dataclasses.FrozenInstanceError, TypeError, AttributeError)):
            field.name = "y"  # type: ignore[misc]


# ---------------------------------------------------------------------------
# TypeSpec
# ---------------------------------------------------------------------------

class TestTypeSpec:
    def test_basic(self):
        from django_graphex.native.ir import TypeSpec, FieldSpec, TypeRef
        spec = TypeSpec(
            name="Post",
            fields=(FieldSpec(name="title", type=TypeRef(name="String")),),
        )
        assert spec.name == "Post"
        assert len(spec.fields) == 1
        assert spec.description is None
        assert spec.gdx is None

    def test_frozen(self):
        from django_graphex.native.ir import TypeSpec, FieldSpec, TypeRef
        import dataclasses
        spec = TypeSpec(name="X", fields=())
        with __import__("pytest").raises((dataclasses.FrozenInstanceError, TypeError, AttributeError)):
            spec.name = "Y"  # type: ignore[misc]

    def test_empty_fields(self):
        from django_graphex.native.ir import TypeSpec
        spec = TypeSpec(name="Empty", fields=())
        assert spec.fields == ()


# ---------------------------------------------------------------------------
# EnumSpec
# ---------------------------------------------------------------------------

class TestEnumSpec:
    def test_basic(self):
        from django_graphex.native.ir import EnumSpec
        spec = EnumSpec(name="Status", values=(("ACTIVE", 1), ("INACTIVE", 0)))
        assert spec.name == "Status"
        assert spec.values == (("ACTIVE", 1), ("INACTIVE", 0))

    def test_string_values(self):
        from django_graphex.native.ir import EnumSpec
        spec = EnumSpec(name="Color", values=(("RED", "red"), ("BLUE", "blue")))
        assert spec.values[0] == ("RED", "red")

    def test_descriptions_optional(self):
        from django_graphex.native.ir import EnumSpec
        spec = EnumSpec(name="Status", values=(("ACTIVE", 1),))
        assert spec.descriptions is None

        spec_with_desc = EnumSpec(
            name="Status",
            values=(("ACTIVE", 1),),
            descriptions={"ACTIVE": "Active status"}
        )
        assert spec_with_desc.descriptions == {"ACTIVE": "Active status"}

    def test_frozen(self):
        from django_graphex.native.ir import EnumSpec
        import dataclasses
        spec = EnumSpec(name="X", values=())
        with __import__("pytest").raises((dataclasses.FrozenInstanceError, TypeError, AttributeError)):
            spec.name = "Y"  # type: ignore[misc]
