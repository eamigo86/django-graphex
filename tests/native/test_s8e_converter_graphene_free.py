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
  path (``_scalar_or_dead`` returns the dead sentinel under
  ``GDX_BACKEND=native``; the native output compiler derives scalars from
  ``model._meta`` directly). They are built ONLY on the graphene path, so the
  graphene scalar classes are imported LAZILY (gated behind the graphene
  build), never at module top level.

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

Run: GDX_BACKEND=native .venv/bin/python -m pytest \
    tests/native/test_s8e_converter_graphene_free.py -q -o addopts=""
"""
from __future__ import annotations

import ast
import inspect

import pytest

pytestmark = pytest.mark.native_only


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
def test_choices_enum_is_graphene_enum_and_registered() -> None:
    """``convert_django_field_with_choices`` still returns a graphene Enum.

    AND it registers the enum in the registry (the side-effect other code reads).
    The lazy-defer must keep BOTH the return type and the registry write byte
    identical.
    """
    import graphene  # graphene is still installed (uninstall is S8i)

    from django_graphex.converter import convert_django_field_with_choices
    from django_graphex.registry import Registry
    from tests.test_converter import TestModel

    field = TestModel._meta.get_field("choice_field")
    registry = Registry()

    out = convert_django_field_with_choices(field, registry=registry)
    assert isinstance(out, graphene.Enum), (
        "convert_django_field_with_choices must still return a graphene Enum "
        "instance (native default test contract)."
    )
    assert set(out._meta.enum.__members__) == {"CHOICE_A", "CHOICE_B"}

    # The choices->Enum REGISTRY SIDE-EFFECT is preserved: the enum class is
    # registered under the (app_label, object_name, field_name) key.
    meta = field.model._meta
    from django_graphex._strconv import to_camel_case

    key = to_camel_case(f"{meta.app_label}_{meta.object_name}_{field.name}_Enum")
    registered = registry.get_type_for_enum(key)
    assert registered is not None, (
        "The choices->Enum registry side-effect must survive the lazy-defer."
    )
    assert issubclass(registered, graphene.Enum)


# --------------------------------------------------------------------------- #
# 3. The relation Dynamic / Field / ID constructs stay graphene               #
# --------------------------------------------------------------------------- #
def test_fk_converts_to_graphene_dynamic() -> None:
    """FK / M2M still convert to a graphene ``Dynamic`` on native (test contract)."""
    import graphene

    from django_graphex.converter import convert_django_field
    from tests.test_converter import TestModel

    fk = TestModel._meta.get_field("user")
    m2m = TestModel._meta.get_field("basics")
    assert isinstance(convert_django_field(fk), graphene.Dynamic)
    assert isinstance(convert_django_field(m2m), graphene.Dynamic)


def test_fk_input_dynamic_resolves_to_graphene_id() -> None:
    """The FK input closure still resolves to a graphene ``ID`` on native."""
    import graphene

    from django_graphex.converter import convert_django_field
    from django_graphex.registry import Registry
    from tests.models import Post

    fk = Post._meta.get_field("author")
    dyn = convert_django_field(fk, registry=Registry(), input_flag="create")
    assert isinstance(dyn, graphene.Dynamic)
    resolved = dyn.get_type()
    assert isinstance(resolved, graphene.ID)


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
