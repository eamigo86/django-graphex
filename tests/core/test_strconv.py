"""TDD 1.1 RED — _strconv.py tests.

Tests:
- to_camel_case("created_at") == "createdAt"
- to_snake_case("createdAt") == "created_at"
- round-trip: to_snake_case(to_camel_case(x)) == x for snake_case strings
- props(cls) returns only non-underscore attrs
- warn_deprecation emits DeprecationWarning

Zero graphene imports required.

Run: .venv/bin/python -m pytest tests/core/test_strconv.py -q
"""

from __future__ import annotations

import warnings

import pytest

# ---------------------------------------------------------------------------
# to_camel_case
# ---------------------------------------------------------------------------


def test_to_camel_case_basic() -> None:
    """Ships broken if to_camel_case("created_at") stops returning
    "createdAt".
    """
    from django_graphex._strconv import to_camel_case

    assert to_camel_case("created_at") == "createdAt"


def test_to_camel_case_single_word() -> None:
    """Ships broken if to_camel_case("name") stops returning "name"
    unchanged.
    """
    from django_graphex._strconv import to_camel_case

    assert to_camel_case("name") == "name"


def test_to_camel_case_multi_word() -> None:
    """Ships broken if to_camel_case("first_name_last") stops returning
    "firstNameLast".
    """
    from django_graphex._strconv import to_camel_case

    assert to_camel_case("first_name_last") == "firstNameLast"


def test_to_camel_case_already_camel() -> None:
    """Ships broken if to_camel_case("createdAt") stops being idempotent on
    an already-camel input.
    """
    from django_graphex._strconv import to_camel_case

    assert to_camel_case("createdAt") == "createdAt"


def test_to_camel_case_lowercases_internal_capitals_like_graphene() -> None:
    """Ships broken if component capitals stop being lower-cased exactly like
    graphene's to_camel_case.

    Enum / type NAMES are built from values that already carry internal capitals
    (e.g. "meta.object_name" = "SeedArticle"). graphene's
    "to_camel_case" "str.capitalize()"-es each later component, lower-casing
    the remainder ("SeedArticle" -> "Seedarticle"). The stdlib replacement
    MUST match byte-for-byte, else filter-input enum-registry lookups (keyed by
    this name) miss and the SDL silently degrades the choices field to String.
    """
    from django_graphex._strconv import to_camel_case

    assert (
        to_camel_case("tests_SeedArticle_status_Enum") == "testsSeedarticleStatusEnum"
    )


@pytest.mark.parametrize(
    ("snake", "expected"),
    [
        ("tests_SeedArticle_status_Enum", "testsSeedarticleStatusEnum"),
        ("tests_SeedArticle_status_Enum_create", "testsSeedarticleStatusEnumCreate"),
        ("tests_Category_status_Enum", "testsCategoryStatusEnum"),
        ("created_at", "createdAt"),
        ("first_name_last", "firstNameLast"),
        ("foo__bar", "foo_Bar"),
        ("_leading", "Leading"),
        ("leading_", "leading_"),
        ("name", "name"),
        ("a_1_b", "a1B"),
    ],
)
def test_to_camel_case_matches_canonical_naming_contract(
    snake: str, expected: str
) -> None:
    """Ships broken if "to_camel_case" stops rendering the canonical
    camelCase name for any of the parametrized forms.

    This is the cross-module-naming contract: converter.py, filtering/schema.py,
    filtering/native_schema.py and native/* all key the SAME registry by names
    built from this function. The expected values are the FROZEN canonical spec
    (they were the byte-for-byte output of the historical graphene
    "to_camel_case" that the stdlib replacement reproduced); any drift would
    split a single logical registry name into two keys. graphene is no longer
    imported (v2.0) — the native output IS the spec.

    Args:
        snake: The snake_case (or otherwise-cased) input string.
        expected: The canonical camelCase name it must convert to.
    """
    from django_graphex._strconv import to_camel_case

    assert to_camel_case(snake) == expected


# ---------------------------------------------------------------------------
# to_snake_case
# ---------------------------------------------------------------------------


def test_to_snake_case_basic() -> None:
    """Ships broken if to_snake_case("createdAt") stops returning
    "created_at".
    """
    from django_graphex._strconv import to_snake_case

    assert to_snake_case("createdAt") == "created_at"


def test_to_snake_case_single_word() -> None:
    """Ships broken if to_snake_case("name") stops returning "name"
    unchanged.
    """
    from django_graphex._strconv import to_snake_case

    assert to_snake_case("name") == "name"


def test_to_snake_case_multi_word() -> None:
    """Ships broken if to_snake_case("firstNameLast") stops returning
    "first_name_last".
    """
    from django_graphex._strconv import to_snake_case

    assert to_snake_case("firstNameLast") == "first_name_last"


# ---------------------------------------------------------------------------
# Round-trip
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "snake",
    [
        "created_at",
        "first_name",
        "some_long_field_name",
        "id",
        "user_id",
    ],
)
def test_round_trip_snake_to_camel_back(snake: str) -> None:
    """Ships broken if to_snake_case(to_camel_case(s)) stops equaling s for
    any parametrized snake_case input.

    Args:
        snake: The snake_case string round-tripped through both converters.
    """
    from django_graphex._strconv import to_camel_case, to_snake_case

    assert to_snake_case(to_camel_case(snake)) == snake, (
        f"Round-trip failed for {snake!r}: "
        f"to_snake_case(to_camel_case({snake!r})) != {snake!r}"
    )


# ---------------------------------------------------------------------------
# props
# ---------------------------------------------------------------------------


def test_props_returns_only_public_attrs() -> None:
    """Ships broken if props(cls) stops filtering out attrs that start with
    an underscore.
    """
    from django_graphex._strconv import props

    class SampleClass:
        public_field = "hello"
        another = 42
        _private = "hidden"
        __dunder__ = "also hidden"

    result = props(SampleClass)

    assert "public_field" in result
    assert "another" in result
    assert "_private" not in result
    assert "__dunder__" not in result


def test_props_returns_dict() -> None:
    """Ships broken if props(cls) stops returning a dict.

    Also checks the returned mapping carries the expected key/value pairs.
    """
    from django_graphex._strconv import props

    class Simple:
        x = 1
        y = 2

    result = props(Simple)
    assert isinstance(result, dict)
    assert result["x"] == 1
    assert result["y"] == 2


def test_props_empty_class() -> None:
    """Ships broken if props(cls) on a class with no public attrs stops
    returning an empty dict.
    """
    from django_graphex._strconv import props

    class AllPrivate:
        _a = 1
        __b__ = 2

    result = props(AllPrivate)
    assert result == {}


# ---------------------------------------------------------------------------
# warn_deprecation
# ---------------------------------------------------------------------------


def test_warn_deprecation_emits_deprecation_warning() -> None:
    """Ships broken if warn_deprecation(msg) stops emitting a
    DeprecationWarning.
    """
    from django_graphex._strconv import warn_deprecation

    with warnings.catch_warnings(record=True) as w:
        warnings.simplefilter("always")
        warn_deprecation("This feature is deprecated.")
        assert len(w) == 1
        assert issubclass(w[0].category, DeprecationWarning)


def test_warn_deprecation_message_content() -> None:
    """Ships broken if warn_deprecation(msg) stops including the given
    message in the warning.
    """
    from django_graphex._strconv import warn_deprecation

    msg = "Use the new API instead."
    with warnings.catch_warnings(record=True) as w:
        warnings.simplefilter("always")
        warn_deprecation(msg)
        assert msg in str(w[0].message)


def test_props_includes_inherited_public_attrs() -> None:
    """Ships broken if props(cls) stops walking the MRO.

    A "class Arguments(CommonArgs)" that factors shared mutation arguments
    into a base class must still expose the inherited attributes: the
    "vars(cls)"-based implementation dropped every one of them SILENTLY, so a
    required "tenant: String!" argument simply vanished from the compiled SDL.
    """
    from django_graphex._strconv import props

    class CommonArgs:
        tenant = "tenant-arg"
        _private = "hidden"

    class Arguments(CommonArgs):
        name = "name-arg"

    assert props(Arguments) == {"tenant": "tenant-arg", "name": "name-arg"}


def test_props_subclass_overrides_base_attr() -> None:
    """Ships broken if a subclass attribute stops shadowing the base one.

    Most-derived wins is the only sane precedence for an inherited
    "class Arguments" declaration.
    """
    from django_graphex._strconv import props

    class Base:
        shared = "base"

    class Child(Base):
        shared = "child"

    assert props(Child) == {"shared": "child"}


def test_props_inherited_arguments_compile_into_mutation_args() -> None:
    """Ships broken if inherited "class Arguments" attributes stop compiling.

    This is the user-visible half of the same defect: "_compile_args" reads
    "props", so an inherited required argument disappeared from the mutation's
    GraphQL signature with no error at all.
    """
    from graphql import GraphQLArgument, GraphQLNonNull, GraphQLString

    from django_graphex.core.mutation import _compile_args

    class CommonArgs:
        tenant = GraphQLArgument(GraphQLNonNull(GraphQLString))

    class Arguments(CommonArgs):
        name = GraphQLArgument(GraphQLString)

    compiled = _compile_args(Arguments)
    assert set(compiled) == {"tenant", "name"}
