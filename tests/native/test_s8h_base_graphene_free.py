# -*- coding: utf-8 -*-
"""S8h (graphene-removal): native/base.py off graphene — the LAST top-level import.

``native/base.py`` held the final two TOP-LEVEL graphene imports in the entire
``django_graphex`` package::

    from graphene.types.mountedtype import MountedType
    from graphene.types.unmountedtype import UnmountedType

They existed ONLY to DETECT + ignore graphene field descriptors
(``name = graphene.String()``) declared on a NATIVE ``ObjectType`` class body —
a 1.x back-compat shim. The native public field-declaration API is now
``field()`` (``NativeField`` / ``NativeMountedField``), so the 2.0 contract drops
graphene-descriptor support entirely: a graphene descriptor on a native type is
NO LONGER recognized; users migrate ``name = graphene.String()`` ->
``name = field(GraphQLString)``.

This module proves:
  1. native/base.py has ZERO top-level graphene imports (AST probe).
  2. The WHOLE ``django_graphex`` package has ZERO top-level graphene imports —
     ``import django_graphex`` pulls graphene at NO module's top level.
  3. The native descriptor-detection tuples retain the NATIVE currency
     (``NativeField`` / ``NativeMountedField`` / ``GraphQLField``) so a
     ``field()`` declaration and a re-parented ``Django*Field`` still land in
     ``_meta.fields`` (no silent drop).
"""

import ast
from pathlib import Path

import django_graphex.native.base as base_mod

_BASE_PATH = Path(base_mod.__file__)
_PKG_ROOT = Path(base_mod.__file__).resolve().parent.parent  # django_graphex/


def _toplevel_graphene_imports(path: Path) -> list[str]:
    """Return the source lines of any TOP-LEVEL graphene import in *path*."""
    tree = ast.parse(path.read_text())
    hits: list[str] = []
    for node in tree.body:  # module body only -> top-level statements
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name == "graphene" or alias.name.startswith("graphene."):
                    hits.append(f"import {alias.name}")
        elif isinstance(node, ast.ImportFrom):
            mod = node.module or ""
            if mod == "graphene" or mod.startswith("graphene."):
                names = ", ".join(a.name for a in node.names)
                hits.append(f"from {mod} import {names}")
    return hits


def test_no_toplevel_graphene_import_in_native_base():
    """native/base.py must have ZERO top-level graphene imports (AST probe)."""
    hits = _toplevel_graphene_imports(_BASE_PATH)
    assert hits == [], (
        "native/base.py still has top-level graphene imports "
        f"(uninstall-blocking): {hits}"
    )


def test_zero_toplevel_graphene_imports_in_whole_package():
    """The ENTIRE ``django_graphex`` package has ZERO top-level graphene imports.

    This is the S8h milestone: ``import django_graphex`` materializes graphene at
    NO module's import time. (Lazy / in-function imports are out of scope here —
    they are still permitted on the transitional graphene backend.)
    """
    hits: list[str] = []
    for py in sorted(_PKG_ROOT.rglob("*.py")):
        for line in _toplevel_graphene_imports(py):
            hits.append(f"{py.relative_to(_PKG_ROOT)}: {line}")
    assert hits == [], (
        "django_graphex still has top-level graphene imports somewhere: " f"{hits}"
    )


def test_descriptor_tuples_keep_native_currency_drop_graphene():
    """The field-descriptor detection tuple keeps NATIVE currency only.

    ``_FIELD_DESCRIPTOR_TYPES`` (the union recognized as a field descriptor) must
    NOT contain graphene ``MountedType`` / ``UnmountedType`` (2.0 contract) but
    MUST keep ``NativeField`` / ``NativeMountedField`` (+ ``GraphQLField`` for the
    field union) so a ``field()`` declaration and a re-parented ``Django*Field``
    still land in ``_meta.fields`` — no silent drop.

    S-del-backend-11: the dead ``_GRAPHENE_DESCRIPTOR_TYPES`` tuple was deleted
    (``_FIELD_DESCRIPTOR_TYPES`` is the live collector).
    """
    from graphql import GraphQLField

    from django_graphex.native.descriptors import NativeField, NativeMountedField

    field_types = base_mod._FIELD_DESCRIPTOR_TYPES

    # Native currency retained.
    assert NativeField in field_types
    assert NativeMountedField in field_types
    assert GraphQLField in field_types

    # The dead graphene-named descriptor tuple is gone.
    assert not hasattr(base_mod, "_GRAPHENE_DESCRIPTOR_TYPES"), (
        "_GRAPHENE_DESCRIPTOR_TYPES (dead) must be deleted in S-del-backend-11"
    )

    # Graphene markers GONE — assert by class name so we never import graphene
    # here (the whole point is base.py is graphene-free).
    leaked = [
        t.__name__
        for t in field_types
        if t.__name__ in ("MountedType", "UnmountedType")
    ]
    assert leaked == [], f"graphene descriptor markers still present: {leaked}"


def test_native_field_declaration_lands_in_meta_fields():
    """A class-body ``field()`` descriptor on a native ``ObjectType`` reaches ``_meta.fields``.

    The silent-drop guard: dropping the graphene markers must NOT drop the native
    ``field()`` currency. A ``hello = field(GraphQLString)`` on a plain native
    ``ObjectType`` must still be collected into ``_meta.fields`` (the compiler's
    field set) — exactly as the graphene descriptor used to be.
    """
    from graphql import GraphQLString

    from django_graphex import field
    from django_graphex.native.base import ObjectType

    class _NativeRoot(ObjectType):
        hello = field(GraphQLString)

    fields = _NativeRoot._meta.fields
    assert "hello" in fields, fields
    # The descriptor exposes ``.type`` (the compiler's read attr) = the scalar.
    assert fields["hello"].type is GraphQLString
