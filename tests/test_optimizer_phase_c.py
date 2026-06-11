"""Tests for optimizer-phase-c: DB-side window-function slicing of nested lists.

C1 slice: setting + flag + paginator hook.
"""

from __future__ import annotations

import pytest
from django.test import TestCase, override_settings


# ---------------------------------------------------------------------------
# Phase 1: Setting + flag foundation
# ---------------------------------------------------------------------------


class TestOptimizeNestedPaginationSetting(TestCase):
    """Tests for the OPTIMIZE_NESTED_PAGINATION setting (tasks 1.1 and 1.3)."""

    def test_setting_default(self):
        """OPTIMIZE_NESTED_PAGINATION absent from DJANGO_GRAPHEX defaults to True (task 1.1)."""
        from django_graphex import settings as settings_module

        # Read via the module-level singleton so override_settings reload is respected.
        s = settings_module.graphql_api_settings
        self.assertTrue(
            hasattr(s, "OPTIMIZE_NESTED_PAGINATION"),
            "graphql_api_settings must expose OPTIMIZE_NESTED_PAGINATION",
        )
        self.assertIs(
            s.OPTIMIZE_NESTED_PAGINATION,
            True,
            "Default value must be True",
        )

    @override_settings(DJANGO_GRAPHEX={"OPTIMIZE_NESTED_PAGINATION": False})
    def test_setting_explicit_false(self):
        """OPTIMIZE_NESTED_PAGINATION=False propagates via override_settings (task 1.3)."""
        from django_graphex import settings as settings_module

        s = settings_module.graphql_api_settings
        self.assertIs(
            s.OPTIMIZE_NESTED_PAGINATION,
            False,
            "Explicit False must be honoured",
        )


class TestAlreadyPaginatedFlag(TestCase):
    """Tests for the already_paginated field on DjangoListObjectBase (task 1.5)."""

    def test_already_paginated_flag_default(self):
        """already_paginated defaults to False, can be set True, old calls still valid (task 1.5)."""
        from django_graphex.base_types import DjangoListObjectBase

        # Old-style call with no already_paginated kwarg must still work.
        obj_old = DjangoListObjectBase(results=[], count=0)
        self.assertIs(
            getattr(obj_old, "already_paginated", False),
            False,
            "Default already_paginated must be False",
        )

        # Explicit False.
        obj_false = DjangoListObjectBase(results=[], count=0, already_paginated=False)
        self.assertIs(obj_false.already_paginated, False)

        # Explicit True.
        obj_true = DjangoListObjectBase(results=[], count=0, already_paginated=True)
        self.assertIs(obj_true.already_paginated, True)
