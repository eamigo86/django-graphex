"""R6 coverage — behavioral tests for "native.factory" uncovered branches.

"native_factory_type" builds native output / list type subclasses via
"type(name, (base,), {...})". The happy paths ("output" / "list" with a
model, "input" delegation) are covered by "test_factory.py"; this file pins
the remaining name-derivation and error branches by asserting actual behavior:

- "output" with NO "name" and NO "model" falls back to "GenericOutputType".
- "output" with NO "name" but a "model" derives a camelCased "<Model>GenericType".
- "list" with NO "name" and NO "model" falls back to "GenericListType".
- "list" with NO "name" but a "model" derives a camelCased "<Model>ListType".
- an unknown "op" raises "ValueError" naming the bad op.
- the "input" op raises "NotImplementedError" (Phase 2 delegation boundary).

Run: .venv/bin/python -m pytest \
    tests/core/test_factory_coverage.py -q -o addopts=""
"""

from __future__ import annotations

import os

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "tests.settings")

import django

django.setup()

import pytest  # noqa: E402
from django.db import models  # noqa: E402


class _FactoryCovBase:
    """Minimal base for factory subclassing tests."""


class FactoryCovModel(models.Model):
    """Minimal Django model fixture used to exercise model-derived naming.

    Only "name" is declared; the model itself carries no behavior.
    """

    name = models.CharField(max_length=50)

    class Meta:
        """Django model options for FactoryCovModel.

        Scopes the fixture model to the "tests" app registry.
        """

        app_label = "tests"


# ---------------------------------------------------------------------------
# output: name derivation
# ---------------------------------------------------------------------------


def test_output_no_name_no_model_uses_generic_output_type() -> None:
    """Assert that "output" with neither name nor model names GenericOutputType.

    If this fails, callers that omit both "name" and "model" would get an
    unpredictable or empty type name instead of the documented fallback.
    """
    from django_graphex.core.factory import native_factory_type

    cls = native_factory_type("output", _FactoryCovBase)
    assert cls._gdx_name == "GenericOutputType"
    assert cls.__name__ == "GenericOutputType"
    assert cls._gdx_model is None
    assert issubclass(cls, _FactoryCovBase)


def test_output_no_name_with_model_camelcases_generic_type() -> None:
    """Assert that "output" with a model (no name) derives a camelCased name.

    If this fails, model-derived output types would not follow the
    "<Model>GenericType" camelCase naming convention callers rely on.
    """
    from django_graphex._strconv import to_camel_case
    from django_graphex.core.factory import native_factory_type

    cls = native_factory_type("output", _FactoryCovBase, model=FactoryCovModel)
    expected = to_camel_case("FactoryCovModel_Generic_Type")
    assert cls._gdx_name == expected
    assert cls._gdx_model is FactoryCovModel


def test_output_explicit_name_is_honored() -> None:
    """Assert that an explicit "name" is used verbatim for the output type.

    If this fails, an explicit name argument would be silently overridden or
    transformed instead of taking precedence over any derived name.
    """
    from django_graphex.core.factory import native_factory_type

    cls = native_factory_type("output", _FactoryCovBase, name="MyOutput")
    assert cls._gdx_name == "MyOutput"
    assert cls.__name__ == "MyOutput"


# ---------------------------------------------------------------------------
# list: name derivation + three-field spec
# ---------------------------------------------------------------------------


def test_list_no_name_no_model_uses_generic_list_type() -> None:
    """Assert that "list" with neither name nor model names GenericListType.

    If this fails, callers that omit both "name" and "model" would get an
    unpredictable list type name and the default pagination field spec
    (results / totalCount / pageInfo) could silently drift.
    """
    from django_graphex.core.factory import native_factory_type

    cls = native_factory_type("list", _FactoryCovBase)
    assert cls._gdx_name == "GenericListType"
    # default results field name.
    assert cls._gdx_results_field_name == "results"
    assert cls._gdx_list_fields["results_field_name"] == "results"
    assert cls._gdx_list_fields["totalCount"] == "Int"
    assert cls._gdx_list_fields["pageInfo"] == "PageInfo"


def test_list_no_name_with_model_camelcases_list_type() -> None:
    """Assert that "list" with a model (no name) derives a camelCased name.

    If this fails, model-derived list types would not follow the
    "<Model>ListType" camelCase naming convention callers rely on.
    """
    from django_graphex._strconv import to_camel_case
    from django_graphex.core.factory import native_factory_type

    cls = native_factory_type("list", _FactoryCovBase, model=FactoryCovModel)
    expected = to_camel_case("FactoryCovModel_List_Type")
    assert cls._gdx_name == expected
    assert cls._gdx_model is FactoryCovModel


def test_list_custom_results_field_name_is_carried() -> None:
    """Assert that a custom "results_field_name" propagates to attr and spec.

    If this fails, a caller-supplied results field name would be dropped
    somewhere along the way, leaving the attr and the field spec out of sync.
    """
    from django_graphex.core.factory import native_factory_type

    cls = native_factory_type(
        "list", _FactoryCovBase, name="ThingList", results_field_name="items"
    )
    assert cls._gdx_results_field_name == "items"
    assert cls._gdx_list_fields["results_field_name"] == "items"


# ---------------------------------------------------------------------------
# op error paths
# ---------------------------------------------------------------------------


def test_unknown_op_raises_value_error_naming_op() -> None:
    """Assert that an unrecognized op raises ValueError naming the bad value.

    If this fails, an invalid "op" argument would fail silently or with an
    unhelpful error instead of clearly identifying the offending value.
    """
    from django_graphex.core.factory import native_factory_type

    with pytest.raises(ValueError, match="bogus"):
        native_factory_type("bogus", _FactoryCovBase)


def test_input_op_raises_not_implemented() -> None:
    """Assert that the "input" op raises NotImplementedError (Phase 2 boundary).

    If this fails, the deliberate Phase 2 delegation boundary for "input"
    would be silently removed, hiding that input-type construction is not yet
    implemented through this factory.
    """
    from django_graphex.core.factory import native_factory_type

    with pytest.raises(NotImplementedError, match="Phase 2"):
        native_factory_type("input", _FactoryCovBase, model=FactoryCovModel)
