"""TDD 1.1 RED — _strconv.py tests.

Tests:
- to_camel_case("created_at") == "createdAt"
- to_snake_case("createdAt") == "created_at"
- round-trip: to_snake_case(to_camel_case(x)) == x for snake_case strings
- props(cls) returns only non-underscore attrs
- warn_deprecation emits DeprecationWarning

Zero graphene imports required.

Run: GDX_BACKEND=native .venv/bin/python -m pytest tests/native/test_strconv.py -q
"""
from __future__ import annotations

import warnings

import pytest

pytestmark = pytest.mark.native_only


# ---------------------------------------------------------------------------
# to_camel_case
# ---------------------------------------------------------------------------


def test_to_camel_case_basic():
    """to_camel_case("created_at") should return "createdAt"."""
    from django_graphex._strconv import to_camel_case

    assert to_camel_case("created_at") == "createdAt"


def test_to_camel_case_single_word():
    """to_camel_case("name") should return "name" (no change)."""
    from django_graphex._strconv import to_camel_case

    assert to_camel_case("name") == "name"


def test_to_camel_case_multi_word():
    """to_camel_case("first_name_last") should return "firstNameLast"."""
    from django_graphex._strconv import to_camel_case

    assert to_camel_case("first_name_last") == "firstNameLast"


def test_to_camel_case_already_camel():
    """to_camel_case("createdAt") should return "createdAt" (idempotent on camel)."""
    from django_graphex._strconv import to_camel_case

    assert to_camel_case("createdAt") == "createdAt"


# ---------------------------------------------------------------------------
# to_snake_case
# ---------------------------------------------------------------------------


def test_to_snake_case_basic():
    """to_snake_case("createdAt") should return "created_at"."""
    from django_graphex._strconv import to_snake_case

    assert to_snake_case("createdAt") == "created_at"


def test_to_snake_case_single_word():
    """to_snake_case("name") should return "name" (no change)."""
    from django_graphex._strconv import to_snake_case

    assert to_snake_case("name") == "name"


def test_to_snake_case_multi_word():
    """to_snake_case("firstNameLast") should return "first_name_last"."""
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
def test_round_trip_snake_to_camel_back(snake):
    """to_snake_case(to_camel_case(s)) == s for all snake_case inputs."""
    from django_graphex._strconv import to_camel_case, to_snake_case

    assert to_snake_case(to_camel_case(snake)) == snake, (
        f"Round-trip failed for {snake!r}: "
        f"to_snake_case(to_camel_case({snake!r})) != {snake!r}"
    )


# ---------------------------------------------------------------------------
# props
# ---------------------------------------------------------------------------


def test_props_returns_only_public_attrs():
    """props(cls) returns only attrs that do NOT start with underscore."""
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


def test_props_returns_dict():
    """props(cls) returns a dict."""
    from django_graphex._strconv import props

    class Simple:
        x = 1
        y = 2

    result = props(Simple)
    assert isinstance(result, dict)
    assert result["x"] == 1
    assert result["y"] == 2


def test_props_empty_class():
    """props(cls) on a class with no public attrs returns empty dict."""
    from django_graphex._strconv import props

    class AllPrivate:
        _a = 1
        __b__ = 2

    result = props(AllPrivate)
    assert result == {}


# ---------------------------------------------------------------------------
# warn_deprecation
# ---------------------------------------------------------------------------


def test_warn_deprecation_emits_deprecation_warning():
    """warn_deprecation(msg) emits a DeprecationWarning."""
    from django_graphex._strconv import warn_deprecation

    with warnings.catch_warnings(record=True) as w:
        warnings.simplefilter("always")
        warn_deprecation("This feature is deprecated.")
        assert len(w) == 1
        assert issubclass(w[0].category, DeprecationWarning)


def test_warn_deprecation_message_content():
    """warn_deprecation(msg) includes the given message in the warning."""
    from django_graphex._strconv import warn_deprecation

    msg = "Use the new API instead."
    with warnings.catch_warnings(record=True) as w:
        warnings.simplefilter("always")
        warn_deprecation(msg)
        assert msg in str(w[0].message)
