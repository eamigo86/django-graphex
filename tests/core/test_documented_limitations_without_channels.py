"""Keep non-subscription type-limit tests importable without Channels."""

from __future__ import annotations

import importlib
import importlib.util

import pytest


def test_documented_core_limitations_import_without_subscription_extra() -> None:
    """Keep range-limit tests available when optional Channels is absent.

    Scenario: A base installation collects core range tests without importing
    subscription implementation modules.
    """
    if importlib.util.find_spec("channels") is not None:
        pytest.skip("This collection contract applies to the base install.")
    module = importlib.import_module("tests.core.test_documented_type_limitations")
    assert callable(module.test_decimal_range_bounds_are_delivered_as_floats)
