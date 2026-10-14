"""Keep core settings in the rendered Markdown table rather than raw prose."""

from pathlib import Path


def test_core_settings_rows_remain_in_one_markdown_table() -> None:
    """Require the core settings rows to form one contiguous Markdown table.

    Text between rows ends a Markdown table, even if later lines start with
    pipe characters. A string-presence assertion would miss that regression.
    """
    guide = (Path(__file__).resolve().parents[1] / "docs/usage/settings.md").read_text(
        encoding="utf-8"
    )
    section = guide.split("## Schema & middleware\n", 1)[1].split("\n## ", 1)[0]
    lines = section.splitlines()
    header = "| Setting | Default | Description |"
    start = lines.index(header)
    assert lines[start + 1] == "|---|---|---|"

    setting_names: set[str] = set()
    for line in lines[start + 2 :]:
        if not line.startswith("|"):
            break
        setting_names.add(line.split("|", 2)[1].strip().strip("`"))

    assert {
        "ATOMIC_MUTATIONS",
        "MAX_VALIDATION_ERRORS",
        "SUBSCRIPTION_CONNECTION_INIT_TIMEOUT",
    } <= setting_names
