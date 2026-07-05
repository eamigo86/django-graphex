"""OUTPUT-compiler naming parity + GFK/Range bridge fixes.

Covers four confirmed defects in the native OUTPUT compiler
("django_graphex.core.output_compiler") and the shared string helper
("django_graphex._strconv"):

FIX 1 — camelCase digit/component parity.
    The compiler's local "_to_camel_case" used a regex "_([a-z])" that only
    uppercased a letter after an underscore, so a digit component was NEVER
    joined: "phone_1" stayed "phone_1" and "iso_8601_date" became
    "iso_8601Date". The INPUT path ("pydantic.alias_generators.to_camel") and
    the canonical "_strconv.to_camel_case" both produce "phone1" /
    "iso8601Date" — so the OUTPUT and INPUT wire names DIVERGED for the same
    model field. The fix routes the compiler through "_strconv.to_camel_case"
    (single source of truth), restoring output/input parity.

FIX 3 — GFK flat "id" sub-resolver on a custom-PK model.
    "_gfk_flat_resolver('id')" read "root.id" on the resolved content object.
    A model with a NON-"id" primary key (e.g. a slug PK) has no "id" attr, so
    the resolver raised AttributeError. The fix reads "root.pk" (the pk
    whatever its column name).

FIX 4 — GFK flat type + Range composite types must carry the "gdx" bridge.
    Every native object/interface/input type must carry
    "extensions['gdx']" ("bridge.assert_gdx_bridge" hard-fails on a missing
    one). The shared flat "GenericForeignKeyType" and the per-bound Range
    composite objects were built with EMPTY extensions, so a schema containing a
    GFK field or a RangeField would trip the bridge assertion. The fix attaches
    a "GdxPayload(GdxMeta(name=...))" exactly like every sibling object type.

This is a COMPILER-level (build-time) test suite — it constructs models/fields
and compiles the output types. No live PostgreSQL / no migrations are required.
"""

from __future__ import annotations

import os

import django

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "tests.settings")
django.setup()

# Imports below are intentionally after ``django.setup()`` (the established
# pattern in tests/core/test_output_postgres.py): the native compiler modules
# touch Django model machinery on import, so settings must be configured first.
import pytest  # noqa: E402
from django.db import models  # noqa: E402
from graphql import GraphQLID, GraphQLNonNull  # noqa: E402

from django_graphex._strconv import to_camel_case  # noqa: E402
from django_graphex.core.bridge import assert_gdx_bridge  # noqa: E402
from django_graphex.core.output_compiler import (  # noqa: E402
    _get_gfk_flat_type,
    _get_range_composite_type,
    _gfk_flat_resolver,
    compile_output_fields,
)

# ---------------------------------------------------------------------------
# psycopg-free RangeField stand-in (same technique as test_output_postgres.py)
# ---------------------------------------------------------------------------


class _FakeIntegerRangeField(models.Field):
    """Stand-in for "django.contrib.postgres.fields.IntegerRangeField"."""

    def __init__(self, **kwargs: object) -> None:
        """Default the column to nullable, mirroring the real range field.

        Args:
            **kwargs: Extra field options forwarded to "models.Field".
        """
        kwargs.setdefault("null", True)
        super().__init__(**kwargs)

    def get_internal_type(self) -> str:
        """Report the internal type string the output compiler keys on.

        Returns:
            internal_type: The literal string "IntegerRangeField".
        """
        return "IntegerRangeField"


# ---------------------------------------------------------------------------
# Test models (pure-python, app_label="tests"; never migrated — build-time only)
# ---------------------------------------------------------------------------


class DigitFieldModel(models.Model):
    """Model whose field names carry digits after an underscore (FIX 1).

    Registered under the "tests" app label; never migrated since this is a
    build-time-only (SDL compilation) fixture.
    """

    phone_1 = models.CharField(max_length=20)
    address_2 = models.CharField(max_length=200)
    iso_8601_date = models.CharField(max_length=40)

    class Meta:
        """Django model options.

        Declares the app label so the model registers cleanly under the
        test app without a matching database migration.
        """

        app_label = "tests"


class RangeBridgeModel(models.Model):
    """Model with a RangeField, to exercise the composite type's gdx bridge.

    Registered under the "tests" app label; never migrated since this is a
    build-time-only (SDL compilation) fixture.
    """

    age_range = _FakeIntegerRangeField()

    class Meta:
        """Django model options.

        Declares the app label so the model registers cleanly under the
        test app without a matching database migration.
        """

        app_label = "tests"


# ---------------------------------------------------------------------------
# Minimal registry stub (only get_compiled is read by the output compiler)
# ---------------------------------------------------------------------------


class StubRegistry:
    """Minimal registry for the output compiler.

    Only "get_compiled" is used by the code paths exercised in this file.
    """

    def __init__(self) -> None:
        self._compiled: dict = {}

    def get_compiled(self, model_cls: type) -> object | None:
        """Return the compiled GraphQL type registered for a model class.

        Args:
            model_cls: The Django model class to look up.

        Returns:
            compiled: The registered compiled type, or None if unregistered.
        """
        return self._compiled.get(model_cls)


def _unwrap_nonnull(gql_type: object) -> object:
    """Strip a GraphQLNonNull wrapper, returning the inner type unchanged otherwise.

    Args:
        gql_type: The GraphQL type to unwrap.

    Returns:
        inner: The wrapped type's "of_type" if non-null, else "gql_type" as-is.
    """
    return gql_type.of_type if isinstance(gql_type, GraphQLNonNull) else gql_type


# ===========================================================================
# FIX 1 — camelCase digit/component parity between OUTPUT and INPUT.
# ===========================================================================


def test_output_compiler_joins_digit_component_no_underscore() -> None:
    """The fields "phone_1" / "address_2" must render as "phone1" / "address2".

    Contract: OUTPUT/INPUT wire-name parity ships broken if the digit
    component is left underscore-separated instead of joined.
    """
    registry = StubRegistry()
    fields = compile_output_fields(DigitFieldModel, registry)

    assert "phone1" in fields, (
        "field 'phone_1' must render as camelCase 'phone1' (digit joined); got "
        f"{sorted(fields)!r}"
    )
    assert "address2" in fields, (
        f"field 'address_2' must render as camelCase 'address2'; got {sorted(fields)!r}"
    )
    assert "phone_1" not in fields, (
        "the underscore-preserving 'phone_1' wire name must NOT be emitted"
    )
    assert "address_2" not in fields, (
        "the underscore-preserving 'address_2' wire name must NOT be emitted"
    )


def test_output_compiler_multi_digit_component_matches_canonical() -> None:
    """The field "iso_8601_date" must render as "iso8601Date" (canonical wire name).

    Contract: multi-digit camelCase parity ships broken if the compiler
    keeps the "iso_8601" underscore instead of joining it fully.
    """
    registry = StubRegistry()
    fields = compile_output_fields(DigitFieldModel, registry)

    assert "iso8601Date" in fields, (
        "field 'iso_8601_date' must render as canonical 'iso8601Date'; got "
        f"{sorted(fields)!r}"
    )
    assert "iso_8601Date" not in fields, (
        "the local-regex 'iso_8601Date' (underscore kept before the digit) must "
        "NOT be emitted"
    )


def test_output_input_wire_name_parity_for_digit_fields() -> None:
    """The OUTPUT wire name for a digit field must equal the canonical INPUT name.

    Contract: a single model field must resolve to exactly ONE wire name;
    OUTPUT/INPUT parity ships broken if the two paths diverge.
    """
    registry = StubRegistry()
    fields = compile_output_fields(DigitFieldModel, registry)

    for snake in ("phone_1", "address_2", "iso_8601_date"):
        expected = to_camel_case(snake)
        assert expected in fields, (
            f"OUTPUT wire name for {snake!r} must equal the canonical "
            f"{expected!r} (input/output parity); got {sorted(fields)!r}"
        )


# ===========================================================================
# FIX 3 — GFK flat ``id`` sub-resolver on a custom-PK model.
# ===========================================================================


@pytest.mark.django_db
def test_gfk_flat_id_resolver_reads_pk_on_custom_pk_model() -> None:
    """The GFK flat "id" sub-resolver must read "root.pk" (not "root.id").

    Contract: GFK resolution on a custom-PK model ships broken (raises
    AttributeError) if the sub-resolver still assumes an "id" attribute.
    """
    from tests.models import CustomPKProduct

    # A model whose pk is a slug CharField — it has NO ``id`` attribute.
    product = CustomPKProduct(slug="widget-42", title="Widget")

    resolve_id = _gfk_flat_resolver("id")
    value = resolve_id(product, None)

    assert value == "widget-42", (
        "the GFK flat 'id' sub-resolver must return the model's pk "
        f"('widget-42') via root.pk on a custom-PK model; got {value!r}"
    )


@pytest.mark.django_db
def test_gfk_flat_id_resolver_still_reads_standard_pk() -> None:
    """Regression guard: on a standard id-pk model the resolver still returns the pk.

    Contract: the custom-PK fix (FIX 3) must not regress the common case
    where "root.pk" equals "root.id".
    """
    from tests.models import Track2Account

    account = Track2Account(id=7, balance=0, label="acct")
    resolve_id = _gfk_flat_resolver("id")
    assert resolve_id(account, None) == 7


# ===========================================================================
# FIX 4 — GFK flat type + Range composite carry the gdx bridge.
# ===========================================================================


def test_gfk_flat_type_carries_gdx_extension() -> None:
    """The shared flat GenericForeignKeyType must carry extensions['gdx'].

    Contract: the gdx bridge invariant ships broken if the shared GFK flat
    type still carries empty extensions (every native object type must
    carry the gdx payload, or "assert_gdx_bridge" hard-fails).
    """
    gfk_type = _get_gfk_flat_type()
    assert "gdx" in (gfk_type.extensions or {}), (
        "GenericForeignKeyType must carry extensions['gdx'] (bridge invariant); "
        f"got extensions {gfk_type.extensions!r}"
    )


def test_range_composite_type_carries_gdx_extension() -> None:
    """A Range composite object type must carry extensions['gdx'].

    Contract: the gdx bridge invariant ships broken if a Range composite
    type is built with empty extensions.
    """
    from graphql import GraphQLInt

    composite = _get_range_composite_type(GraphQLInt)
    assert "gdx" in (composite.extensions or {}), (
        "the Range composite type must carry extensions['gdx'] (bridge "
        f"invariant); got extensions {composite.extensions!r}"
    )


@pytest.mark.django_db
def test_gfk_flat_type_passes_assert_gdx_bridge_in_schema() -> None:
    """A schema whose type map contains the flat GenericForeignKeyType passes the bridge.

    Contract: "assert_gdx_bridge" must accept a schema containing the GFK
    flat type; it did not before FIX 4 (the type had empty extensions).
    """
    from graphql import (
        GraphQLField,
        GraphQLObjectType,
        GraphQLSchema,
        GraphQLString,
    )

    from django_graphex.core.bridge import GdxPayload
    from django_graphex.core.ir import GdxMeta

    gfk_type = _get_gfk_flat_type()

    query = GraphQLObjectType(
        name="Query",
        fields={
            "hello": GraphQLField(GraphQLString),
            "gfk": GraphQLField(gfk_type),
        },
        extensions={"gdx": GdxPayload(GdxMeta(name="Query"))},
    )
    schema = GraphQLSchema(query=query)

    # Must not raise — the GFK flat type now carries the gdx bridge.
    assert_gdx_bridge(schema)


@pytest.mark.django_db
def test_range_composite_passes_assert_gdx_bridge_in_schema() -> None:
    """A schema containing a model's Range composite output type passes the bridge.

    Contract: "assert_gdx_bridge" must accept a schema containing a
    compiled Range composite type (build-time bridge invariant).
    """
    from graphql import (
        GraphQLField,
        GraphQLObjectType,
        GraphQLSchema,
        GraphQLString,
    )

    from django_graphex.core.bridge import GdxPayload
    from django_graphex.core.ir import GdxMeta

    registry = StubRegistry()
    fields = compile_output_fields(RangeBridgeModel, registry)
    assert "ageRange" in fields, "the RangeField must be compiled (not dropped)"
    composite = _unwrap_nonnull(fields["ageRange"].type)

    query = GraphQLObjectType(
        name="Query",
        fields={
            "hello": GraphQLField(GraphQLString),
            "ageRange": GraphQLField(composite),
        },
        extensions={"gdx": GdxPayload(GdxMeta(name="Query"))},
    )
    schema = GraphQLSchema(query=query)

    # Must not raise — the Range composite now carries the gdx bridge.
    assert_gdx_bridge(schema)


# A sanity guard so the GFK flat type shape (ID for the pk) is unchanged by the
# resolver fix: the "id" sub-field is still typed "ID".
def test_gfk_flat_type_id_field_still_typed_id() -> None:
    """The GFK flat type's "id" sub-field must remain typed ID.

    Contract: the FIX 3 resolver change (reading root.pk) must not alter
    the GFK flat type's public schema shape.
    """
    gfk_type = _get_gfk_flat_type()
    assert _unwrap_nonnull(gfk_type.fields["id"].type) is GraphQLID
