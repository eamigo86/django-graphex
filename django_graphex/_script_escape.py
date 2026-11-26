"""Escape a value for injection into an inline "<script>" JavaScript string."""

from __future__ import annotations

import json


def escape_for_script(value: str) -> str:
    r"""Escape "value" for injection into an inline "<script>" JS string.

    "json.dumps" alone makes the value safe as a JavaScript string literal
    (quotes/backslashes/control chars), but it leaves "<" verbatim, so a value
    containing "</script>" would still close the inline script element in the
    browser. We additionally escape "<", ">" and "&" to their "\\uXXXX" forms
    (the same idiom Django's "json_script" uses). Inside a JS string literal
    each "\\uXXXX" decodes back to the original character, so the value the
    client sees is unchanged, but no literal "</script>" (or entity-forming "&")
    ever reaches the HTML parser.

    Args:
        value: The raw string to inject.

    Returns:
        The escaped inner content (WITHOUT the surrounding quotes), safe to
        splice into a double-quoted JS string literal in an inline script.
    """
    escaped = json.dumps(value)[1:-1]
    return (
        escaped.replace("<", "\\u003c").replace(">", "\\u003e").replace("&", "\\u0026")
    )
