"""Tests for core/ir.py — pure-Python IR dataclasses.

No Django settings required. No django_db markers.
Run with: pytest tests/core/test_ir.py -x --no-cov
"""

from __future__ import annotations

import pathlib
import sys

# ---------------------------------------------------------------------------
# No-import gate: ir.py must import zero symbols from django/graphene/graphql
# ---------------------------------------------------------------------------


def test_ir_has_no_django_graphene_graphql_imports() -> None:
    """Assert that "ir.py" carries zero top-level django/graphene/graphql imports.

    If this fails, the pure-Python IR module would have picked up a
    forbidden dependency, breaking its no-import guarantee.
    """
    import pathlib
    import re

    ir_path = (
        pathlib.Path(__file__).parent.parent.parent
        / "django_graphex"
        / "core"
        / "ir.py"
    )
    src = ir_path.read_text()
    forbidden = re.compile(
        r"^(from django[.\s]|import django[.\s]|from graphene[.\s]|import graphene[.\s]|from graphql[.\s]|import graphql[.\s])",
        re.MULTILINE,
    )
    matches = forbidden.findall(src)
    assert matches == [], f"Forbidden imports found in ir.py: {matches}"


def test_ir_importable_without_django_settings() -> None:
    """Assert that "ir.py" imports cleanly with DJANGO_SETTINGS_MODULE unset.

    Uses importlib to load the file directly, bypassing
    "django_graphex/__init__.py". The module is registered in sys.modules so
    the dataclass decorator resolves "__module__" correctly.
    """
    import importlib.util

    ir_path = (
        pathlib.Path(__file__).parent.parent.parent
        / "django_graphex"
        / "core"
        / "ir.py"
    )
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
    """Tests for the "TypeRef" frozen dataclass.

    Covers defaulting, immutability, equality, and hashing.
    """

    def test_basic_creation(self) -> None:
        """Assert that "TypeRef" defaults list/non_null/inner when only name is given.

        If this fails, a bare scalar type reference would carry unexpected
        list, non-null, or inner-type state.
        """
        from django_graphex.core.ir import TypeRef

        ref = TypeRef(name="String")
        assert ref.name == "String"
        assert ref.list is False
        assert ref.non_null is False
        assert ref.inner is None

    def test_non_null(self) -> None:
        """Assert that the "non_null" flag is stored as passed.

        If this fails, a required (non-null) type reference could be
        silently treated as optional.
        """
        from django_graphex.core.ir import TypeRef

        ref = TypeRef(name="Int", non_null=True)
        assert ref.non_null is True

    def test_list_of_non_null(self) -> None:
        """Assert that a list "TypeRef" wraps its non-null inner reference.

        If this fails, list-of-non-null type references would lose their
        inner type or the list/inner relationship.
        """
        from django_graphex.core.ir import TypeRef

        inner = TypeRef(name="String", non_null=True)
        ref = TypeRef(name="String", list=True, inner=inner)
        assert ref.list is True
        assert ref.inner is inner

    def test_frozen(self) -> None:
        """Assert that "TypeRef" instances are immutable after construction.

        If this fails, callers could mutate a shared type reference and
        corrupt other IR structures referencing it.
        """
        import dataclasses

        from django_graphex.core.ir import TypeRef

        ref = TypeRef(name="String")
        with __import__("pytest").raises(
            (dataclasses.FrozenInstanceError, TypeError, AttributeError)
        ):
            ref.name = "Int"  # type: ignore[misc]

    def test_equality(self) -> None:
        """Assert that "TypeRef" equality compares by field values.

        If this fails, structurally identical type references could compare
        unequal (or distinct ones could compare equal), breaking dedup logic.
        """
        from django_graphex.core.ir import TypeRef

        assert TypeRef(name="String") == TypeRef(name="String")
        assert TypeRef(name="String") != TypeRef(name="Int")

    def test_hashable(self) -> None:
        """Assert that equal "TypeRef" instances hash identically.

        If this fails, "TypeRef" values could not be safely deduplicated in
        sets or used as dict keys.
        """
        from django_graphex.core.ir import TypeRef

        s = {TypeRef(name="String"), TypeRef(name="String")}
        assert len(s) == 1


# ---------------------------------------------------------------------------
# GdxMeta
# ---------------------------------------------------------------------------


class TestGdxMeta:
    """Tests for the "GdxMeta" frozen dataclass.

    Covers defaulting, explicit field values, and immutability.
    """

    def test_defaults(self) -> None:
        """Assert that "GdxMeta" defaults every field to None when unset.

        If this fails, an empty meta declaration would carry unexpected
        model, depth, complexity, or name state.
        """
        from django_graphex.core.ir import GdxMeta

        meta = GdxMeta()
        assert meta.model is None
        assert meta.max_depth is None
        assert meta.complexity is None
        assert meta.name is None

    def test_with_values(self) -> None:
        """Assert that "GdxMeta" stores explicitly passed field values.

        If this fails, max_depth, complexity, or name overrides declared on
        a type would be silently dropped.
        """
        from django_graphex.core.ir import GdxMeta

        meta = GdxMeta(max_depth=5, complexity=2, name="MyType")
        assert meta.max_depth == 5
        assert meta.complexity == 2
        assert meta.name == "MyType"

    def test_frozen(self) -> None:
        """Assert that "GdxMeta" instances are immutable after construction.

        If this fails, callers could mutate a shared meta object and corrupt
        other IR structures referencing it.
        """
        import dataclasses

        from django_graphex.core.ir import GdxMeta

        meta = GdxMeta(max_depth=3)
        with __import__("pytest").raises(
            (dataclasses.FrozenInstanceError, TypeError, AttributeError)
        ):
            meta.max_depth = 5  # type: ignore[misc]


# ---------------------------------------------------------------------------
# FieldSpec
# ---------------------------------------------------------------------------


class TestFieldSpec:
    """Tests for the "FieldSpec" frozen dataclass.

    Covers defaulting, resolver wiring, and immutability.
    """

    def test_basic(self) -> None:
        """Assert that "FieldSpec" defaults description/resolver/gdx to None.

        If this fails, a minimal field declaration would carry unexpected
        description, resolver, or gdx metadata.
        """
        from django_graphex.core.ir import FieldSpec, TypeRef

        field = FieldSpec(name="title", type=TypeRef(name="String"))
        assert field.name == "title"
        assert field.description is None
        assert field.resolver is None
        assert field.gdx is None

    def test_with_resolver(self) -> None:
        """Assert that a "FieldSpec" resolver callable is stored as passed.

        If this fails, a custom field resolver would be dropped, forcing
        the field back onto default attribute resolution.
        """
        from django_graphex.core.ir import FieldSpec, TypeRef

        def resolver(root, info):
            return "hello"

        field = FieldSpec(name="name", type=TypeRef(name="String"), resolver=resolver)
        assert field.resolver is resolver

    def test_frozen(self) -> None:
        """Assert that "FieldSpec" instances are immutable after construction.

        If this fails, callers could mutate a shared field spec and corrupt
        other IR structures referencing it.
        """
        import dataclasses

        from django_graphex.core.ir import FieldSpec, TypeRef

        field = FieldSpec(name="x", type=TypeRef(name="String"))
        with __import__("pytest").raises(
            (dataclasses.FrozenInstanceError, TypeError, AttributeError)
        ):
            field.name = "y"  # type: ignore[misc]


# ---------------------------------------------------------------------------
# TypeSpec
# ---------------------------------------------------------------------------


class TestTypeSpec:
    """Tests for the "TypeSpec" frozen dataclass.

    Covers field storage, immutability, and the empty-fields case.
    """

    def test_basic(self) -> None:
        """Assert that "TypeSpec" stores its name and field tuple as passed.

        If this fails, an object type declaration would lose fields or
        default description/gdx metadata unexpectedly.
        """
        from django_graphex.core.ir import FieldSpec, TypeRef, TypeSpec

        spec = TypeSpec(
            name="Post",
            fields=(FieldSpec(name="title", type=TypeRef(name="String")),),
        )
        assert spec.name == "Post"
        assert len(spec.fields) == 1
        assert spec.description is None
        assert spec.gdx is None

    def test_frozen(self) -> None:
        """Assert that "TypeSpec" instances are immutable after construction.

        If this fails, callers could mutate a shared type spec and corrupt
        other IR structures referencing it.
        """
        import dataclasses

        from django_graphex.core.ir import TypeSpec

        spec = TypeSpec(name="X", fields=())
        with __import__("pytest").raises(
            (dataclasses.FrozenInstanceError, TypeError, AttributeError)
        ):
            spec.name = "Y"  # type: ignore[misc]

    def test_empty_fields(self) -> None:
        """Assert that "TypeSpec" accepts an empty fields tuple.

        If this fails, a type with no declared fields (yet) could not be
        represented, e.g. during incremental schema construction.
        """
        from django_graphex.core.ir import TypeSpec

        spec = TypeSpec(name="Empty", fields=())
        assert spec.fields == ()


# ---------------------------------------------------------------------------
# EnumSpec
# ---------------------------------------------------------------------------


class TestEnumSpec:
    """Tests for the "EnumSpec" frozen dataclass.

    Covers value storage, string-backed values, descriptions, and
    immutability.
    """

    def test_basic(self) -> None:
        """Assert that "EnumSpec" stores its name and value tuple as passed.

        If this fails, an enum declaration would lose its member
        name/value pairs.
        """
        from django_graphex.core.ir import EnumSpec

        spec = EnumSpec(name="Status", values=(("ACTIVE", 1), ("INACTIVE", 0)))
        assert spec.name == "Status"
        assert spec.values == (("ACTIVE", 1), ("INACTIVE", 0))

    def test_string_values(self) -> None:
        """Assert that "EnumSpec" values may be strings, not just ints.

        If this fails, string-backed enum members would be rejected or
        coerced, breaking enums whose underlying values are strings.
        """
        from django_graphex.core.ir import EnumSpec

        spec = EnumSpec(name="Color", values=(("RED", "red"), ("BLUE", "blue")))
        assert spec.values[0] == ("RED", "red")

    def test_descriptions_optional(self) -> None:
        """Assert that "descriptions" defaults to None and can be supplied.

        If this fails, enums without per-member descriptions would error,
        or supplied descriptions would be dropped.
        """
        from django_graphex.core.ir import EnumSpec

        spec = EnumSpec(name="Status", values=(("ACTIVE", 1),))
        assert spec.descriptions is None

        spec_with_desc = EnumSpec(
            name="Status",
            values=(("ACTIVE", 1),),
            descriptions={"ACTIVE": "Active status"},
        )
        assert spec_with_desc.descriptions == {"ACTIVE": "Active status"}

    def test_frozen(self) -> None:
        """Assert that "EnumSpec" instances are immutable after construction.

        If this fails, callers could mutate a shared enum spec and corrupt
        other IR structures referencing it.
        """
        import dataclasses

        from django_graphex.core.ir import EnumSpec

        spec = EnumSpec(name="X", values=())
        with __import__("pytest").raises(
            (dataclasses.FrozenInstanceError, TypeError, AttributeError)
        ):
            spec.name = "Y"  # type: ignore[misc]
