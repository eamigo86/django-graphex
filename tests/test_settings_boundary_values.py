# -*- coding: utf-8 -*-
"""Boundary values of the limit settings must not silently mean the opposite.

Three settings used to invert an operator's intent at their boundary:

- "MAX_QUERY_DEPTH" / "MAX_QUERY_COST" at 0 disabled their guard, so a limit
  that reads as "allow nothing" allowed everything; a negative value enforced
  a nonsense budget that rejected every query.
- "PERMISSION_SCHEMA_CACHE_MAXSIZE" at 0 fell back to the default 64, and the
  bound was frozen at import so "override_settings" never reached it.
- "CAMELCASE_ERRORS" was documented with a default but had no consumer at all.
"""

from __future__ import annotations

import pytest
from django.core.exceptions import ImproperlyConfigured
from django.test import override_settings
from graphql import (
    GraphQLField,
    GraphQLObjectType,
    GraphQLSchema,
    GraphQLString,
    parse,
    validate,
)

from django_graphex import settings as gdx_settings
from django_graphex.core import permission_signature_cache as psc
from django_graphex.cost import CostLimitValidationRule
from django_graphex.validation import DepthLimitValidationRule

# --------------------------------------------------------------------------- #
# 1. MAX_QUERY_DEPTH / MAX_QUERY_COST — 0 and negatives are refused loudly
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("name", ["MAX_QUERY_DEPTH", "MAX_QUERY_COST"])
@pytest.mark.parametrize("value", [0, -1])
def test_zero_or_negative_query_limit_is_refused(name: str, value: int) -> None:
    """Assert a query limit at 0 or below raises instead of changing meaning.

    Zero used to be a second, silent way to disable the guard -- the opposite
    of what an operator writing a limit of zero can mean -- and a negative
    value rejected every query with a nonsense message naming that negative.

    Args:
        name: The limit setting under test.
        value: The boundary value an operator might write.

    If this fails, a mistyped limit is back to disabling the guard it was
    meant to tighten.
    """
    with override_settings(DJANGO_GRAPHEX={name: value}):
        with pytest.raises(ImproperlyConfigured) as excinfo:
            getattr(gdx_settings.graphql_api_settings, name)

    assert name in str(excinfo.value)
    assert "None" in str(excinfo.value)


@override_settings(DJANGO_GRAPHEX={"MAX_QUERY_DEPTH": 0, "MAX_QUERY_COST": 0})
@pytest.mark.parametrize("rule", [DepthLimitValidationRule, CostLimitValidationRule])
def test_zero_limit_stops_the_rule_instead_of_passing_every_query(rule: type) -> None:
    """Assert the depth and cost rules refuse a zero limit at validation time.

    This is the consequence the operator actually meets: both rules used to
    treat a zero limit as falsy and return early, so a deeply nested query
    validated clean under a limit that reads as "allow nothing".

    Args:
        rule: The validation rule reading the zero limit.

    If this fails, the guard is disabled by the very value meant to make it
    strictest, and nothing says so.
    """
    node: GraphQLObjectType = GraphQLObjectType(
        "Node",
        lambda: {"name": GraphQLField(GraphQLString), "child": GraphQLField(node)},
    )
    schema = GraphQLSchema(
        query=GraphQLObjectType("Query", {"root": GraphQLField(node)})
    )
    deep = parse("{ root { child { child { child { name } } } } }")

    with pytest.raises(ImproperlyConfigured):
        validate(schema, deep, [rule])


@pytest.mark.parametrize("name", ["MAX_QUERY_DEPTH", "MAX_QUERY_COST"])
def test_none_remains_the_documented_way_to_disable_a_query_limit(name: str) -> None:
    """Assert "None" still disables a query limit without raising.

    Args:
        name: The limit setting under test.

    If this fails, the documented off switch became an error and every
    project running on the defaults breaks at the first request.
    """
    with override_settings(DJANGO_GRAPHEX={name: None}):
        assert getattr(gdx_settings.graphql_api_settings, name) is None


# --------------------------------------------------------------------------- #
# 2. PERMISSION_SCHEMA_CACHE_MAXSIZE — 0 is honored, and it is read per pass
# --------------------------------------------------------------------------- #


def _labeled_schema() -> GraphQLSchema:
    """Build a tiny labeled schema the signature cache can prune.

    Returns:
        A "GraphQLSchema" whose "gdx_label_set" extension holds the two
        permission codenames the fake users below are built from.
    """
    query = GraphQLObjectType("Query", {"public": GraphQLField(GraphQLString)})
    return GraphQLSchema(
        query=query,
        extensions={"gdx_label_set": frozenset({"app.view_pub", "app.view_secret"})},
    )


class _FakeUser:
    """A duck-typed user carrying a fixed permission set.

    Enough surface for the cache: the two flags its superuser fast path reads
    and the "get_all_permissions" call its signature is built from.
    """

    def __init__(self, perms: set[str]) -> None:
        """Store the permission set this user reports.

        Args:
            perms: The permission codenames "get_all_permissions" returns.
        """
        self._perms = perms
        self.is_superuser = False
        self.is_active = True

    def get_all_permissions(self) -> set[str]:
        """Return the fixed permission set.

        Returns:
            The permission codenames given at construction.
        """
        return self._perms


def _fill(cache: psc._SignatureSchemaCache, full: GraphQLSchema) -> None:
    """Drive three distinct permission signatures through a cache.

    Args:
        cache: The cache under test.
        full: The labeled full schema to prune.
    """
    for perms in ({"app.view_pub"}, {"app.view_secret"}, set()):
        cache.pruned_schema_for(_FakeUser(perms), full, prune=lambda schema, _g: schema)


@override_settings(DJANGO_GRAPHEX={"PERMISSION_SCHEMA_CACHE_MAXSIZE": 0})
def test_cache_maxsize_zero_caches_nothing() -> None:
    """Assert a bound of 0 disables caching instead of restoring the default 64.

    If this fails, an operator who turned the pruned-schema cache off is
    silently running the 64-entry default.
    """
    cache = psc._SignatureSchemaCache()
    _fill(cache, _labeled_schema())

    assert len(cache) == 0


@override_settings(DJANGO_GRAPHEX={"PERMISSION_SCHEMA_CACHE_MAXSIZE": 1})
def test_cache_maxsize_follows_the_setting_after_construction() -> None:
    """Assert the LRU bound is re-read per eviction pass, not frozen at import.

    The module singleton is built at import, so a bound captured in
    "__init__" made "override_settings" inert for this setting.

    If this fails, the cache bound is un-testable and un-tunable without a
    process restart.
    """
    full = _labeled_schema()
    cache = psc._SignatureSchemaCache()
    _fill(cache, full)
    assert len(cache) == 1

    with override_settings(DJANGO_GRAPHEX={"PERMISSION_SCHEMA_CACHE_MAXSIZE": 3}):
        _fill(cache, full)
        assert len(cache) == 3


def test_negative_cache_maxsize_is_refused() -> None:
    """Assert a negative LRU bound raises instead of quietly caching nothing.

    If this fails, a typo in the bound degrades every request to a full
    schema prune with no signal at all.
    """
    with override_settings(DJANGO_GRAPHEX={"PERMISSION_SCHEMA_CACHE_MAXSIZE": -1}):
        with pytest.raises(ImproperlyConfigured):
            psc._resolve_maxsize()


# --------------------------------------------------------------------------- #
# 3. CAMELCASE_ERRORS — gone, and reported as unknown to whoever still sets it
# --------------------------------------------------------------------------- #


def test_camelcase_errors_is_reported_as_an_unknown_setting() -> None:
    """Assert the inert "CAMELCASE_ERRORS" key is flagged by the system check.

    The setting had zero consumers, so it promised camelCased error keys and
    changed nothing. It is removed rather than implemented, which means an
    operator who still sets it must be told it does nothing.

    If this fails, the key is back in the defaults and reads as supported.
    """
    assert "CAMELCASE_ERRORS" not in gdx_settings.DEFAULTS

    with override_settings(DJANGO_GRAPHEX={"CAMELCASE_ERRORS": True}):
        messages = gdx_settings.check_unknown_settings()

    assert len(messages) == 1
    assert "CAMELCASE_ERRORS" in messages[0].msg
