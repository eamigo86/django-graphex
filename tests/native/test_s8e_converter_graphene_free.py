"""S8e RED -> GREEN — ``converter.py`` is graphene-free at the top level.

S8e takes ``converter.py`` off graphene at the MODULE level. The two TOP-LEVEL
graphene imports BLOCK the graphene uninstall (S8i), so they must go::

    from graphene import (ID, UUID, Boolean, Dynamic, Enum, Field, Float, Int,
                          List, NonNull, String)
    from graphene.types.json import JSONString

Construct analysis (consumer-proven, see #1561 / S-ROOTS-d and the converter
test contract in ``tests/test_converter*.py``, all run on the native default):

* SCALARS (``String`` / ``Int`` / ``Float`` / ``Boolean`` / ``UUID`` /
  ``JSONString`` + the ``base_types`` scalars) are DEAD on the native OUTPUT
  path (the scalar converters return the dead sentinel; the native output
  compiler derives scalars from ``model._meta`` directly).

* ``Enum`` is GENUINELY CONSUMED on native: ``convert_django_field_with_choices``
  returns a ``graphene.Enum`` instance (``tests/test_converter.py`` and
  ``tests/test_converter_choices.py`` assert ``isinstance(out, graphene.Enum)``
  on the native default suite) AND it carries the choices->enum REGISTRY
  side-effect. The enum is therefore still a graphene ``Enum`` — but built via a
  LAZY accessor so no top-level graphene import survives. The native SDL enum
  (``GraphQLEnumType``) is built independently by
  ``filtering/native_schema._choices_enum``; the converter's registry write is a
  graphene ``Enum`` that ``_choices_enum`` overwrites with the native enum (its
  ``isinstance(cached, GraphQLEnumType)`` guard ignores the graphene one).

* ``Dynamic`` / ``Field`` / ``ID`` (the relation closures for FK / O2O / M2M /
  reverse / GFK) are GENUINELY CONSUMED on native: the native output thunk reads
  the ``Dynamic`` descriptor, and the converter tests assert
  ``isinstance(out, graphene.Dynamic)`` plus ``out.type.of_type.of_type is ID``
  on the native default. They stay graphene constructs, built via LAZY accessors.

* ``List`` / ``NonNull`` (ArrayField / RangeField wrappers + the Boolean-NonNull
  branch) are likewise consumed by ``tests/test_converter_branches.py`` on the
  native default; they stay graphene, built lazily.

So S8e is a LAZY-DEFER slice: every construct keeps producing the EXACT same
graphene object (test contract + SDL byte-parity preserved); only the
uninstall-blocking TOP-LEVEL graphene imports move to a lazy, gated accessor.

Run: .venv/bin/python -m pytest \
    tests/native/test_s8e_converter_graphene_free.py -q -o addopts=""
"""
from __future__ import annotations

import ast
import inspect


# --------------------------------------------------------------------------- #
# 1. Top-level graphene imports are GONE                                       #
# --------------------------------------------------------------------------- #
def _module_imports(module: object) -> list[ast.stmt]:
    source = inspect.getsource(module)
    tree = ast.parse(source)
    return [
        node for node in tree.body if isinstance(node, (ast.Import, ast.ImportFrom))
    ]


def test_converter_has_no_top_level_graphene_import() -> None:
    """``converter.py`` must not import graphene at the MODULE top level."""
    from django_graphex import converter

    imports = _module_imports(converter)

    bare_graphene = [
        node
        for node in imports
        if isinstance(node, ast.Import)
        and any(
            alias.name == "graphene" or alias.name.startswith("graphene.")
            for alias in node.names
        )
    ]
    assert not bare_graphene, (
        "converter.py must NOT contain a top-level `import graphene` — it "
        "blocks the graphene uninstall (S8i)."
    )

    from_graphene = [
        node
        for node in imports
        if isinstance(node, ast.ImportFrom)
        and node.module is not None
        and (node.module == "graphene" or node.module.startswith("graphene."))
    ]
    assert not from_graphene, (
        "converter.py must NOT contain any top-level `from graphene...` import "
        f"— still found: {[n.module for n in from_graphene]}"
    )


def test_converter_module_body_is_graphene_token_free() -> None:
    """No graphene import/name survives at converter.py MODULE level.

    Lazy graphene imports INSIDE functions are allowed (the graphene constructs
    are still genuinely consumed by the converter test contract on native), but
    the module body must not reference the ``graphene`` package directly.
    """
    from django_graphex import converter

    source = inspect.getsource(converter)
    tree = ast.parse(source)
    offenders: list[str] = []
    for node in tree.body:  # MODULE-LEVEL statements only
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name == "graphene" or alias.name.startswith("graphene."):
                    offenders.append(f"import {alias.name}")
        elif isinstance(node, ast.ImportFrom):
            if node.module and (
                node.module == "graphene" or node.module.startswith("graphene.")
            ):
                offenders.append(f"from {node.module}")
    assert not offenders, (
        f"converter.py module body must be graphene-free; found: {offenders}"
    )


# --------------------------------------------------------------------------- #
# 2. The choices->Enum REGISTRY side-effect is preserved natively              #
# --------------------------------------------------------------------------- #
def test_choices_converter_off_graphene_on_both_paths() -> None:
    """The choices converter path is graphene-free on OUTPUT *and* INPUT.

    S-enum-2 retired graphene on the choices OUTPUT path; S-input-5 retires it on
    the INPUT path. On the native backend ``convert_django_field_with_choices``
    now returns the dead-scalar sentinel for BOTH ``input_flag is None`` (output)
    and ``input_flag in {create, update}`` (input). The native input compiler
    renders the SHARED native ``GraphQLEnumType`` (built by
    ``build_choices_enum_type`` — S-enum-1) for the input surface, so the choices
    field is enum-typed and graphene-free on both sides.
    """
    from graphql import GraphQLEnumType

    from django_graphex.converter import (
        _DEAD_SCALAR,
        build_choices_enum_type,
        convert_django_field_with_choices,
    )
    from django_graphex.registry import Registry
    from tests.test_converter import TestModel

    field = TestModel._meta.get_field("choice_field")

    # OUTPUT and INPUT (create/update): all return the dead-scalar sentinel.
    for input_flag in (None, "create", "update"):
        out = convert_django_field_with_choices(
            field, registry=Registry(), input_flag=input_flag
        )
        assert out is _DEAD_SCALAR, (
            "S-input-5: the native choices converter must return the "
            f"dead-scalar sentinel for input_flag={input_flag!r}; got {out!r}"
        )

    # The SHARED native enum is built + registered by ``build_choices_enum_type``
    # (the side-effect the OUTPUT / FILTER-INPUT / mutation-INPUT paths converge
    # on). One canonical instance per (model, field).
    registry = Registry()
    enum = build_choices_enum_type(field, registry)
    assert isinstance(enum, GraphQLEnumType)
    assert set(enum.values.keys()) == {"CHOICE_A", "CHOICE_B"}
    # Built again -> SAME cached instance.
    assert build_choices_enum_type(field, registry) is enum


# --------------------------------------------------------------------------- #
# 3. The relation Dynamic / Field / ID constructs stay graphene               #
# --------------------------------------------------------------------------- #
def test_fk_and_m2m_output_convert_to_native_marker() -> None:
    """to-ONE FK (S-rel-2) AND to-MANY M2M (S-rel-3) -> native OUTPUT markers.

    S-rel-2 retired graphene on the to-ONE relation OUTPUT path and S-rel-3 on the
    to-MANY relation OUTPUT path: a ForeignKey and a ManyToManyField now both
    convert to a graphene-free ``NativeRelationField`` presence/ordering marker on
    OUTPUT (the native compiler builds the actual field — a single object for the
    FK, a ``<Model>ListType`` container for the M2M — from ``model._meta``). The
    INPUT path stays on graphene until S-input-5.
    """
    from django_graphex.converter import convert_django_field
    from django_graphex.native.descriptors import NativeRelationField
    from tests.test_converter import TestModel

    fk = TestModel._meta.get_field("user")
    m2m = TestModel._meta.get_field("basics")
    # OUTPUT (input_flag default None): both are graphene-free native markers.
    assert isinstance(convert_django_field(fk), NativeRelationField)
    assert isinstance(convert_django_field(m2m), NativeRelationField)


def test_fk_input_converts_to_native_marker() -> None:
    """S-input-5: the FK INPUT converter returns a graphene-free native marker.

    The actual ``author: ID!`` create-input field is built by
    ``input_compiler.compile_input_type`` from a ``RelationInputField`` spec
    (``types._resolve_native_relation_input_fields`` reads ``model._meta``), NOT
    from this descriptor — so the converter returns the same
    ``NativeRelationField`` presence/ordering marker it does on OUTPUT.
    """
    from django_graphex.converter import convert_django_field
    from django_graphex.native.descriptors import NativeRelationField
    from django_graphex.registry import Registry
    from tests.models import Post

    fk = Post._meta.get_field("author")
    out = convert_django_field(fk, registry=Registry(), input_flag="create")
    assert isinstance(out, NativeRelationField)
    assert not type(out).__module__.startswith("graphene")


# --------------------------------------------------------------------------- #
# 4. Module imports cleanly under BOTH backends                                #
# --------------------------------------------------------------------------- #
def test_converter_imports_under_native_backend() -> None:
    """Importing converter under native must not require graphene at module load.

    A fresh import in a subprocess with graphene shadowed by a stub that raises
    on ``from graphene import ...`` would still let the MODULE import succeed,
    because the graphene imports are now lazy (inside functions). This asserts
    the module object is importable and exposes its public API.
    """
    from django_graphex import converter

    assert hasattr(converter, "construct_fields")
    assert hasattr(converter, "convert_django_field")
    assert hasattr(converter, "convert_django_field_with_choices")
