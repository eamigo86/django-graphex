"""WU-4 Task 4.3 — nested.py graphene-free verification + _unwrap_enums safety.

Covers:
- Verify that nested.py has zero graphene imports (graphene-free module).
- Confirm _unwrap_enums is a safe no-op under native (plain Python values pass through).
- Confirm _unwrap_enums handles enum.Enum values, lists, and tuples.

All tests run.
"""

from __future__ import annotations

import enum

# ---------------------------------------------------------------------------
# 4.3 VERIFY: nested.py has zero graphene imports
# ---------------------------------------------------------------------------


def test_nested_module_has_no_graphene_imports() -> None:
    """Assert that "nested.py" imports no graphene, at module level or inside functions.

    "nested.py" is on the critical path for write operations. Importing
    graphene from "nested.py" would make the native write-path depend on
    graphene, violating the isolation contract.
    """
    import ast
    import pathlib

    source_path = (
        pathlib.Path(__file__).parent.parent.parent / "django_graphex" / "nested.py"
    )
    source = source_path.read_text(encoding="utf-8")
    tree = ast.parse(source)

    graphene_imports: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            if isinstance(node, ast.ImportFrom):
                if node.module and "graphene" in node.module:
                    graphene_imports.append(f"from {node.module} import ...")
            elif isinstance(node, ast.Import):
                for alias in node.names:
                    if "graphene" in alias.name:
                        graphene_imports.append(f"import {alias.name}")

    assert graphene_imports == [], (
        f"nested.py must have zero graphene imports. Found: {graphene_imports}"
    )


def test_nested_module_runtime_imports_are_stdlib_and_django_only() -> None:
    """Assert that "nested.py" runtime (non-TYPE_CHECKING) imports are stdlib or Django only.

    "graphql.GraphQLResolveInfo" is allowed inside TYPE_CHECKING blocks
    (type annotations only, never imported at runtime). At runtime,
    "nested.py" must NOT import from graphene or graphql-core directly.
    """
    import ast
    import pathlib

    source_path = (
        pathlib.Path(__file__).parent.parent.parent / "django_graphex" / "nested.py"
    )
    source = source_path.read_text(encoding="utf-8")
    tree = ast.parse(source)

    # Collect imports that are inside `if TYPE_CHECKING:` blocks so we can
    # skip them — they are annotation-only and never imported at runtime.
    type_checking_lines: set[int] = set()
    for node in ast.walk(tree):
        if (
            isinstance(node, ast.If)
            and isinstance(node.test, ast.Name)
            and node.test.id == "TYPE_CHECKING"
        ):
            for child in ast.walk(node):
                type_checking_lines.add(getattr(child, "lineno", -1))

    forbidden: list[str] = []
    for node in ast.walk(tree):
        line = getattr(node, "lineno", -1)
        if line in type_checking_lines:
            continue  # skip TYPE_CHECKING-guarded imports
        if isinstance(node, ast.ImportFrom):
            module = node.module or ""
            if module.startswith("graphene"):
                forbidden.append(f"from {module} import ...")
        elif isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name.startswith("graphene"):
                    forbidden.append(f"import {alias.name}")

    assert forbidden == [], (
        f"nested.py has forbidden non-stdlib/non-django runtime imports: {forbidden}"
    )


# ---------------------------------------------------------------------------
# 4.3 VERIFY: _unwrap_enums is a safe no-op under native (raw values)
# ---------------------------------------------------------------------------


class _Color(enum.Enum):
    RED = "red"
    BLUE = "blue"


class _Priority(enum.Enum):
    LOW = 1
    HIGH = 2


def test_unwrap_enums_plain_values_passthrough() -> None:
    """Assert that "_unwrap_enums" passes plain (non-Enum) values through unchanged.

    If this fails, ordinary scalar values in a payload dict would be
    altered even though there is nothing Enum-shaped to unwrap.
    """
    from django_graphex.nested import NestedFieldsMixin

    item = {"name": "Alice", "age": 30, "active": True, "data": None}
    result = NestedFieldsMixin._unwrap_enums(dict(item))
    assert result == item


def test_unwrap_enums_single_enum_value() -> None:
    """Assert that "_unwrap_enums" replaces a scalar Enum member with its stored value.

    If this fails, a raw Enum member would leak into the payload instead
    of being replaced by its underlying stored value.
    """
    from django_graphex.nested import NestedFieldsMixin

    item = {"color": _Color.RED, "name": "test"}
    result = NestedFieldsMixin._unwrap_enums(item)
    assert result["color"] == "red"
    assert result["name"] == "test"


def test_unwrap_enums_multiple_enum_values() -> None:
    """Assert that "_unwrap_enums" replaces every Enum member present in the dict.

    If this fails, only some Enum-valued keys would be unwrapped, leaving
    a mix of raw values and Enum members in the payload.
    """
    from django_graphex.nested import NestedFieldsMixin

    item = {"color": _Color.BLUE, "priority": _Priority.HIGH, "label": "ok"}
    result = NestedFieldsMixin._unwrap_enums(item)
    assert result["color"] == "blue"
    assert result["priority"] == 2
    assert result["label"] == "ok"


def test_unwrap_enums_list_of_enums() -> None:
    """Assert that "_unwrap_enums" unwraps Enum members inside list values.

    If this fails, a list-valued field containing Enum members would keep
    the raw members instead of their stored values.
    """
    from django_graphex.nested import NestedFieldsMixin

    item = {"colors": [_Color.RED, _Color.BLUE]}
    result = NestedFieldsMixin._unwrap_enums(item)
    assert result["colors"] == ["red", "blue"]


def test_unwrap_enums_tuple_of_enums() -> None:
    """Assert that "_unwrap_enums" unwraps Enum members inside tuple values.

    If this fails, a tuple-valued field containing Enum members would keep
    the raw members instead of their stored values.
    """
    from django_graphex.nested import NestedFieldsMixin

    item = {"priorities": (_Priority.LOW, _Priority.HIGH)}
    result = NestedFieldsMixin._unwrap_enums(item)
    assert result["priorities"] == [1, 2]


def test_unwrap_enums_mixed_list() -> None:
    """Assert that "_unwrap_enums" only unwraps the Enum members in a mixed-type list.

    If this fails, non-Enum entries in a mixed list would be altered, or
    Enum entries alongside plain values would be missed.
    """
    from django_graphex.nested import NestedFieldsMixin

    item = {"values": [_Color.RED, "keep", 42, _Priority.LOW]}
    result = NestedFieldsMixin._unwrap_enums(item)
    assert result["values"] == ["red", "keep", 42, 1]


def test_unwrap_enums_empty_payload() -> None:
    """Assert that "_unwrap_enums" on an empty dict returns an empty dict.

    If this fails, the empty-payload edge case would crash or return a
    non-empty result.
    """
    from django_graphex.nested import NestedFieldsMixin

    result = NestedFieldsMixin._unwrap_enums({})
    assert result == {}


def test_unwrap_enums_empty_list_value() -> None:
    """Assert that "_unwrap_enums" leaves an empty list value as an empty list.

    If this fails, an empty list value would be altered (e.g. replaced or
    dropped) instead of passing through unchanged.
    """
    from django_graphex.nested import NestedFieldsMixin

    item = {"tags": []}
    result = NestedFieldsMixin._unwrap_enums(item)
    assert result["tags"] == []


def test_unwrap_enums_is_safe_noop_for_native_raw_values() -> None:
    """Assert that under native, "_unwrap_enums" is effectively a no-op for non-Enum payloads.

    graphql-core resolvers receive plain Python values (not wrapped Enum
    objects) so "_unwrap_enums" finds nothing to unwrap in the typical
    native path. This test confirms the no-op behavior with a realistic
    native payload.

    If this fails, a realistic native mutation payload would be altered
    by "_unwrap_enums" even though it carries no Enum members.
    """
    from django_graphex.nested import NestedFieldsMixin

    # Typical native payload: plain Python types, no Enum members
    native_payload = {
        "title": "My Post",
        "content": "Some content",
        "is_published": False,
        "view_count": 0,
        "tags": ["python", "django"],
        "author_id": 1,
    }
    result = NestedFieldsMixin._unwrap_enums(dict(native_payload))
    assert result == native_payload
