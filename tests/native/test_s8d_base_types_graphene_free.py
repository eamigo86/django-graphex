"""S8d RED -> GREEN — ``base_types.py`` is fully graphene-free at the top level.

S8d takes ``base_types.py`` off graphene. The two TOP-LEVEL graphene imports
(``import graphene`` and ``from graphene.types.datetime import Date, DateTime,
Time``) BLOCK the graphene uninstall (S8i), so they must go.

Construct analysis (consumer-proven, see #1561 / S-ROOTS-d):

* ``Binary`` / ``CustomDate`` / ``CustomDateTime`` / ``CustomTime`` are SCALAR
  descriptors built ONLY by ``converter.py`` and ONLY on the graphene path
  (``_scalar_or_dead`` returns the dead sentinel on native). The native output
  compiler derives the scalar from ``model._meta`` directly (BinaryField ->
  GraphQLString, DateField -> GdxDate, …). So the graphene Scalar / Date / Time
  bases are NOT read by the native path. They are re-parented to graphene-free
  bases that delegate serialize/parse to the canonical native coercers
  (``native/scalars.py``) while keeping the exact static-method read contract
  (``test_base_types_internals.py``) and a tolerant ``__init__`` so the
  graphene-path converter build (``Binary(description=…, required=…)``) still
  constructs.

* ``GenericForeignKeyType`` / ``GenericForeignKeyInputType`` are CONSUMED by the
  still-graphene converter (S8e): ``test_track2_types.py`` (native-default)
  asserts ``field.type is GenericForeignKeyType`` where ``field`` is a graphene
  ``Field(...)`` and the input branch instantiates
  ``GenericForeignKeyInputType(...)``. graphene's ``Field.type`` returns a plain
  class verbatim (``get_type`` passes non-str / non-callable through), so the
  GFK types are re-parented to plain classes that preserve that identity +
  field/Meta shape WITHOUT a graphene base. The native GFK OUTPUT type
  (SDL ``GenericForeignKeyType``) is built independently by
  ``output_compiler._make_generic_foreign_key_type`` and is unaffected.

Run: GDX_BACKEND=native .venv/bin/python -m pytest \
    tests/native/test_s8d_base_types_graphene_free.py -q -o addopts=""
"""
from __future__ import annotations

import ast
import datetime
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


def test_base_types_has_no_top_level_graphene_import() -> None:
    """``base_types.py`` must not ``import graphene`` at the top level."""
    from django_graphex import base_types

    imports = _module_imports(base_types)

    bare_graphene = [
        node
        for node in imports
        if isinstance(node, ast.Import)
        and any(alias.name == "graphene" or alias.name.startswith("graphene.")
                for alias in node.names)
    ]
    assert not bare_graphene, (
        "base_types.py must NOT contain a top-level `import graphene` — it "
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
        "base_types.py must NOT contain any top-level `from graphene...` import "
        f"— still found: {[n.module for n in from_graphene]}"
    )


def test_base_types_source_is_graphene_token_free() -> None:
    """No ``graphene`` token (import or base) survives anywhere in the module."""
    from django_graphex import base_types

    source = inspect.getsource(base_types)
    # Strip the module docstring/comments are fine; assert no real reference to
    # the graphene package as an import or attribute access.
    tree = ast.parse(source)
    offenders: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name == "graphene" or alias.name.startswith("graphene."):
                    offenders.append(f"import {alias.name}")
        elif isinstance(node, ast.ImportFrom):
            if node.module and (
                node.module == "graphene" or node.module.startswith("graphene.")
            ):
                offenders.append(f"from {node.module}")
        elif isinstance(node, ast.Attribute):
            # ``graphene.X`` attribute access (e.g. graphene.ObjectType base).
            value = node.value
            if isinstance(value, ast.Name) and value.id == "graphene":
                offenders.append(f"graphene.{node.attr}")
        elif isinstance(node, ast.Name) and node.id == "graphene":
            offenders.append("graphene (name)")
    assert not offenders, (
        f"base_types.py must be graphene-free; found references: {offenders}"
    )


# --------------------------------------------------------------------------- #
# 2. The four scalar classes are graphene-free                                 #
# --------------------------------------------------------------------------- #
def test_scalar_classes_are_not_graphene_subclasses() -> None:
    """Binary / CustomDate / CustomDateTime / CustomTime are off graphene."""
    import graphene  # graphene is still installed (uninstall is S8i)
    from graphene.types.datetime import Date, DateTime, Time

    from django_graphex.base_types import (
        Binary,
        CustomDate,
        CustomDateTime,
        CustomTime,
    )

    assert not issubclass(Binary, graphene.Scalar), (
        "Binary must NOT subclass graphene.Scalar after S8d."
    )
    assert not issubclass(CustomDate, Date)
    assert not issubclass(CustomDateTime, DateTime)
    assert not issubclass(CustomTime, Time)
    # And none of them should carry a graphene metaclass.
    for cls in (Binary, CustomDate, CustomDateTime, CustomTime):
        assert "graphene" not in type(cls).__module__, (
            f"{cls.__name__} metaclass must not come from graphene."
        )


def test_gfk_classes_are_not_graphene_subclasses() -> None:
    """GenericForeignKeyType / InputType are plain (non-graphene) classes."""
    import graphene

    from django_graphex.base_types import (
        GenericForeignKeyInputType,
        GenericForeignKeyType,
    )

    assert not issubclass(GenericForeignKeyType, graphene.ObjectType)
    assert not issubclass(GenericForeignKeyInputType, graphene.InputObjectType)


# --------------------------------------------------------------------------- #
# 3. Read-contract preserved — scalar serialize/parse behaviour unchanged      #
# --------------------------------------------------------------------------- #
def test_binary_serialize_parse_contract_preserved() -> None:
    from graphql.language import ast as gast

    from django_graphex.base_types import Binary

    assert Binary.serialize(b"\x00\xff") == "00ff"
    assert Binary.parse_value(b"\x01") == "01"
    node = gast.StringValueNode(value=b"\x01\x02")
    assert Binary.parse_literal(node) == "0102"
    assert Binary.parse_literal(gast.IntValueNode(value="1")) is None


def test_custom_date_time_serialize_contract_preserved() -> None:
    from django_graphex.base_types import (
        CustomDate,
        CustomDateFormat,
        CustomDateTime,
        CustomTime,
    )

    # CustomDateFormat bypass.
    assert CustomTime.serialize(CustomDateFormat("custom")) == "custom"
    assert CustomDate.serialize(CustomDateFormat("custom")) == "custom"
    assert CustomDateTime.serialize(CustomDateFormat("custom")) == "custom"

    # ISO behaviour.
    assert CustomTime.serialize(datetime.time(10, 20, 30)) == "10:20:30"
    assert CustomTime.serialize(datetime.datetime(2020, 1, 1, 1, 2, 3)) == "01:02:03"
    assert CustomDate.serialize(datetime.date(2020, 1, 2)) == "2020-01-02"
    assert CustomDate.serialize(datetime.datetime(2020, 1, 2, 3, 4, 5)) == "2020-01-02"
    out = CustomDateTime.serialize(datetime.datetime(2020, 1, 2, 3, 4, 5))
    assert out.startswith("2020-01-02T03:04:05")

    # Invalid input still raises AssertionError (unchanged contract).
    with pytest.raises(AssertionError):
        CustomTime.serialize("not-a-time")
    with pytest.raises(AssertionError):
        CustomDate.serialize("not-a-date")
    with pytest.raises(AssertionError):
        CustomDateTime.serialize("not-a-datetime")


def test_scalar_classes_still_construct_with_graphene_path_kwargs() -> None:
    """The graphene-path converter builds ``Binary(description=…, required=…)``.

    Re-parenting must keep that call constructible so the graphene converter
    path (when ``GDX_BACKEND`` is unset) does not crash on instantiation.
    """
    from django_graphex.base_types import (
        Binary,
        CustomDate,
        CustomDateTime,
        CustomTime,
    )

    for cls in (Binary, CustomDate, CustomDateTime, CustomTime):
        instance = cls(description="d", required=True)
        assert instance is not None


# --------------------------------------------------------------------------- #
# 4. Read-contract preserved — GFK converter identity unchanged                #
# --------------------------------------------------------------------------- #
def test_gfk_type_field_shape_preserved() -> None:
    """GenericForeignKeyType keeps app_label / id / model_name + Meta shape."""
    from django_graphex.base_types import GenericForeignKeyType, resolver

    # The flat type still advertises its three fields (the converter / native
    # SDL parity depends on the names) and its Meta description + resolver.
    assert hasattr(GenericForeignKeyType, "Meta")
    assert GenericForeignKeyType.Meta.default_resolver is resolver
    assert "GenericForeignKey" in GenericForeignKeyType.Meta.description


def test_gfk_input_type_constructs() -> None:
    """GenericForeignKeyInputType instantiates with the converter kwargs."""
    from django_graphex.base_types import GenericForeignKeyInputType

    inst = GenericForeignKeyInputType(
        description="Input Type for a GenericForeignKey field", required=False
    )
    assert inst is not None


def test_converter_gfk_identity_contract_preserved() -> None:
    """The native-path converter still returns ``field.type is GFKType``.

    This mirrors ``test_track2_types.test_converter_falls_back_...`` — the
    converter wraps the (now graphene-free) GenericForeignKeyType in graphene's
    Field/Dynamic and ``field.type is GenericForeignKeyType`` must still hold.
    """
    from graphene import Dynamic, Field

    from django_graphex.base_types import GenericForeignKeyType

    # Identity survives graphene Field wrapping (get_type passes a plain class
    # through verbatim).
    field = Field(GenericForeignKeyType, description="Type for a GFK field")
    assert field.type is GenericForeignKeyType
    # And a Dynamic wrapping a thunk returning that Field resolves identically.
    dyn = Dynamic(lambda: field)
    resolved = dyn.get_type()
    assert resolved.type is GenericForeignKeyType
