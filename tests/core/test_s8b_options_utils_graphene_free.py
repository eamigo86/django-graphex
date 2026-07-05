"""S8b RED — types.py / mutation.py Options + utils off graphene.

S8b (graphene-removal final sub-phase) removes the graphene Options/descriptor
UTILITY imports from the public-type modules, replacing them with the native
equivalents already built in S6a ("native.base"):

- "graphene.utils.props.props"           -> "native.base._props" (stdlib).
- "graphene.utils.deprecated.warn_deprecation" -> "warnings.warn(...,
  DeprecationWarning, stacklevel=2)".
- "graphene.types.base.BaseOptions"      -> DELETED (the graphene-era
  "DjangoObjectOptions" / "DjangoModelTypeOptions" /
  "SerializerMutationOptions" classes were DEAD; the native path uses
  "NativeObjectTypeOptions").
- "graphene.types.utils.yank_fields_from_attrs" -> a graphene-free local
  yank that mounts the construct_fields / class-attr descriptors (the
  descriptor SURFACE itself — graphene "Field" / "InputField" — is S8c).
- "schema.py" TYPE_CHECKING "from graphene import ObjectType" -> dropped
  (the annotation degrades to "Any").

These tests are AST-based so a regression is caught even while graphene is still
installed (it is not uninstalled until S8i).

Run: .venv/bin/python -m pytest \
    tests/core/test_s8b_options_utils_graphene_free.py -q -o addopts=""
"""

from __future__ import annotations

import ast
import inspect
from types import ModuleType


def _top_level_imported_names(module: ModuleType) -> set[str]:
    """Return the set of names imported at MODULE TOP LEVEL (incl. lazy-free).

    Walks only "tree.body" (top-level statements), so a function-local /
    lazy import inside a method body is NOT counted — exactly the surface S8b
    must scrub.
    """
    source = inspect.getsource(module)
    tree = ast.parse(source)
    names: set[str] = set()
    for node in tree.body:
        if isinstance(node, ast.ImportFrom):
            mod = node.module or ""
            for alias in node.names:
                names.add(f"{mod}::{alias.name}")
        elif isinstance(node, ast.Import):
            for alias in node.names:
                names.add(f"::{alias.name}")
    return names


# ---------------------------------------------------------------------------
# types.py — Options/utils symbols off graphene at top level
# ---------------------------------------------------------------------------


def test_types_no_top_level_graphene_baseoptions() -> None:
    """Ships broken if "types.py" starts importing "graphene.types.base.BaseOptions"
    again at top level.
    """
    from django_graphex import types

    names = _top_level_imported_names(types)
    assert "graphene.types.base::BaseOptions" not in names, (
        "types.py must NOT import graphene BaseOptions at top level (S8b)."
    )


def test_types_no_top_level_graphene_yank() -> None:
    """Ships broken if "types.py" starts importing
    "graphene.types.utils.yank_fields_from_attrs" again at top level.
    """
    from django_graphex import types

    names = _top_level_imported_names(types)
    assert "graphene.types.utils::yank_fields_from_attrs" not in names, (
        "types.py must NOT import graphene yank_fields_from_attrs at top level (S8b)."
    )


def test_types_no_top_level_graphene_props() -> None:
    """Ships broken if "types.py" starts importing "graphene.utils.props.props"
    again at top level.
    """
    from django_graphex import types

    names = _top_level_imported_names(types)
    assert "graphene.utils.props::props" not in names, (
        "types.py must NOT import graphene props at top level (S8b)."
    )


def test_types_no_top_level_graphene_warn_deprecation() -> None:
    """Ships broken if "types.py" starts importing
    "graphene.utils.deprecated.warn_deprecation" again at top level.
    """
    from django_graphex import types

    names = _top_level_imported_names(types)
    assert "graphene.utils.deprecated::warn_deprecation" not in names, (
        "types.py must NOT import graphene warn_deprecation at top level (S8b)."
    )


def test_types_dead_graphene_options_classes_removed() -> None:
    """Ships broken if the DEAD graphene-era Options classes reappear on
    "types.py".

    The native path builds "NativeObjectTypeOptions"; "DjangoObjectOptions"
    / "DjangoModelTypeOptions" here subclassed graphene "BaseOptions" and
    were never referenced. (The native-friendly variants live in
    "django_graphex._options" and are unaffected.)
    """
    from django_graphex import types

    assert not hasattr(types, "DjangoObjectOptions"), (
        "types.DjangoObjectOptions (graphene BaseOptions subclass) must be removed."
    )
    assert not hasattr(types, "DjangoModelTypeOptions"), (
        "types.DjangoModelTypeOptions (graphene BaseOptions subclass) must be removed."
    )


# ---------------------------------------------------------------------------
# mutation.py — Options/utils symbols off graphene at top level
# ---------------------------------------------------------------------------


def test_mutation_no_top_level_graphene_baseoptions() -> None:
    """Ships broken if "mutation.py" starts importing
    "graphene.types.base.BaseOptions" again at top level.
    """
    from django_graphex import mutation

    names = _top_level_imported_names(mutation)
    assert "graphene.types.base::BaseOptions" not in names, (
        "mutation.py must NOT import graphene BaseOptions at top level (S8b)."
    )


def test_mutation_no_top_level_graphene_props() -> None:
    """Ships broken if "mutation.py" starts importing
    "graphene.utils.props.props" again at top level.
    """
    from django_graphex import mutation

    names = _top_level_imported_names(mutation)
    assert "graphene.utils.props::props" not in names, (
        "mutation.py must NOT import graphene props at top level (S8b)."
    )


def test_mutation_no_top_level_graphene_warn_deprecation() -> None:
    """Ships broken if "mutation.py" starts importing
    "graphene.utils.deprecated.warn_deprecation" again at top level.
    """
    from django_graphex import mutation

    names = _top_level_imported_names(mutation)
    assert "graphene.utils.deprecated::warn_deprecation" not in names, (
        "mutation.py must NOT import graphene warn_deprecation at top level (S8b)."
    )


def test_mutation_dead_graphene_options_class_removed() -> None:
    """Ships broken if "SerializerMutationOptions" (graphene BaseOptions
    subclass) reappears on the mutation module.
    """
    from django_graphex import mutation

    assert not hasattr(mutation, "SerializerMutationOptions"), (
        "mutation.SerializerMutationOptions (graphene BaseOptions subclass) must "
        "be removed; the native path uses NativeObjectTypeOptions."
    )


# ---------------------------------------------------------------------------
# schema.py — TYPE_CHECKING graphene ObjectType annotation dropped
# ---------------------------------------------------------------------------


def test_schema_no_graphene_import_anywhere() -> None:
    """Ships broken if "schema.py" reintroduces a graphene import anywhere
    (including the TYPE_CHECKING block).

    The TYPE_CHECKING "from graphene import ObjectType" at schema.py:20 is the
    last graphene reference in the module; S8b drops it (the annotation degrades
    to "Any" / the native "GraphQLObjectType").
    """
    from django_graphex import schema

    source = inspect.getsource(schema)
    tree = ast.parse(source)
    found: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name.split(".")[0] == "graphene":
                    found.append(f"import {alias.name}")
        elif isinstance(node, ast.ImportFrom):
            if (node.module or "").split(".")[0] == "graphene":
                found.append(f"from {node.module} import ...")
    assert not found, (
        f"schema.py must have ZERO graphene imports (S8b); found: {found}."
    )


# ---------------------------------------------------------------------------
# Behavior preserved: native _props + warnings.warn swaps work
# ---------------------------------------------------------------------------


def test_native_props_matches_graphene_props_for_arguments_class() -> None:
    """Ships broken if "native.base._props" stops extracting the same user
    attrs graphene's "props" used to extract.

    The mutation/model-type "Arguments" -> kwargs conversion relied on graphene
    "props"; the native "_props" must produce the SAME dict for a plain
    "Arguments"-style class body.
    """
    from django_graphex.core.base import _props

    class Arguments:
        alpha = 1
        beta = "two"

    extracted = _props(Arguments)
    assert extracted == {"alpha": 1, "beta": "two"}


def test_legacy_input_deprecation_uses_stdlib_warnings() -> None:
    """Ships broken if the legacy-"Input" deprecation path stops emitting a
    stdlib "DeprecationWarning" or a "warn_deprecation" reference reappears.

    "warn_deprecation" was a graphene helper; S8b swaps it for
    "warnings.warn(..., DeprecationWarning, stacklevel=2)". Assert the source
    of "mutation.py" / "types.py" carries the stdlib call and references the
    legacy-"Input" migration text, and that no "warn_deprecation" name
    survives.
    """
    from django_graphex import mutation, types

    for module in (mutation, types):
        source = inspect.getsource(module)
        assert "warn_deprecation" not in source, (
            f"{module.__name__} must not reference warn_deprecation (S8b)."
        )
        assert "DeprecationWarning" in source, (
            f"{module.__name__} must emit DeprecationWarning via stdlib warnings (S8b)."
        )
        assert ".Arguments instead of" in source, (
            f"{module.__name__} must keep the legacy-Input migration message (S8b)."
        )
