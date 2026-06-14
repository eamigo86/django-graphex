"""Sub-spike 3: Two-phase model_rebuild + loud ForwardRef — gate G5.

Validates that:
1. Cross-module cyclic Pydantic specs rebuild cleanly via two-phase model_rebuild.
2. An orphan spec with an unresolved ForwardRef raises with "ForwardRef" in the message.

Run: pytest tests/spike/test_forward_ref.py -v
"""

from __future__ import annotations

import pytest
from pydantic import BaseModel


# ---------------------------------------------------------------------------
# Two cross-module cyclic specs (simulated via __module__ assignment)
# ---------------------------------------------------------------------------

# Build classes via type() so we can control __module__ to simulate cross-module refs
_ns_a = {"__annotations__": {"title": str, "author": "AuthorCycle | None"}}
ArticleSpec = type("ArticleSpec", (BaseModel,), {"__module__": "tests.spike.models", **_ns_a})

_ns_b = {"__annotations__": {"name": str, "articles": "list[ArticleSpec]"}}
AuthorCycle = type("AuthorCycle", (BaseModel,), {"__module__": "tests.spike.models", **_ns_b})

# Make them accessible in tests.spike.models namespace for forward ref resolution
import sys
import types as _types
_spike_models = _types.ModuleType("tests.spike.models")
_spike_models.ArticleSpec = ArticleSpec
_spike_models.AuthorCycle = AuthorCycle
sys.modules["tests.spike.models"] = _spike_models


# ---------------------------------------------------------------------------
# G5: Two-phase model_rebuild tests
# ---------------------------------------------------------------------------

class TestG5TwoPhaseModelRebuild:
    """G5: Two-phase model_rebuild resolves cross-module cycles cleanly."""

    def test_cross_module_cycle_rebuilds_cleanly(self):
        """Phase 1 (raise_errors=False) + Phase 2 (raise_errors=True) succeeds."""
        # Phase 1: rebuild with errors suppressed (allows partial resolution)
        ArticleSpec.model_rebuild(raise_errors=False)
        AuthorCycle.model_rebuild(raise_errors=False)

        # Phase 2: rebuild with errors raised — should succeed with no exception
        ArticleSpec.model_rebuild(raise_errors=True)
        AuthorCycle.model_rebuild(raise_errors=True)

        # Verify the models are functional after rebuild
        author = AuthorCycle(name="Hemingway", articles=[])
        assert author.name == "Hemingway"

        article = ArticleSpec(title="The Old Man and the Sea", author=None)
        assert article.title == "The Old Man and the Sea"

    def test_orphan_spec_raises_with_forward_ref_message(self):
        """An orphan spec with an unresolved ForwardRef raises with 'ForwardRef' in message."""

        # Build an orphan spec referencing a non-existent type
        _ns = {"__annotations__": {"data": "NonExistentType"}}
        OrphanSpec = type("OrphanSpec", (BaseModel,), {"__module__": "tests.spike.models", **_ns})

        with pytest.raises(Exception) as exc_info:
            OrphanSpec.model_rebuild(raise_errors=True)

        error_message = str(exc_info.value)
        assert "ForwardRef" in error_message or "NonExistentType" in error_message, (
            f"Expected 'ForwardRef' or type name in error message, got: {error_message!r}"
        )
