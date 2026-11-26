"""The documentation's Playground guide quotes the budget the Playground ships."""

from __future__ import annotations

import re
from pathlib import Path

from tests._repo_only import requires_repo_paths

ROOT = Path(__file__).resolve().parents[1]
SETTINGS = ROOT / "examples" / "playground" / "config" / "settings.py"
GUIDE = ROOT / "docs" / "usage" / "examples" / "playground.md"


@requires_repo_paths("examples/playground/config/settings.py")
def test_guide_quotes_the_measured_playground_cost_budget() -> None:
    """The guide names the commented MAX_QUERY_COST of the Playground settings.

    The budget is re-measured whenever the cost model changes, so a stale number
    in the guide would send readers to a value that no longer fits the examples.
    """
    match = re.search(r'#\s+"MAX_QUERY_COST": ([0-9_]+),', SETTINGS.read_text())
    assert match, "the Playground settings no longer carry a commented budget"

    guide = GUIDE.read_text(encoding="utf-8")

    assert f"`MAX_QUERY_COST = {match.group(1)}`" in guide
    assert "would refuse even a one-row list query" not in guide
