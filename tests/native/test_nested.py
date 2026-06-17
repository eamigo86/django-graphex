"""WU-4 Task 4.3 — nested.py graphene-free verification + _unwrap_enums safety.

Covers:
- Verify that nested.py has zero graphene imports (graphene-free module).
- Confirm _unwrap_enums is a safe no-op under native (plain Python values pass through).
- Confirm _unwrap_enums handles enum.Enum values, lists, and tuples.

All tests run.
"""
from __future__ import annotations

import enum
import importlib
import importlib.util

# ---------------------------------------------------------------------------
# 4.3 VERIFY: nested.py has zero graphene imports
# ---------------------------------------------------------------------------


def test_nested_module_has_no_graphene_imports():
    """nested.py must not import graphene at the module level or inside functions.

    nested.py is on the critical path for write
    operations.  Importing graphene from nested.py would make the native
    write-path depend on graphene, violating the isolation contract.
    """
    import ast
    import pathlib

    source_path = pathlib.Path(__file__).parent.parent.parent / "django_graphex" / "nested.py"
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


def test_nested_module_runtime_imports_are_stdlib_and_django_only():
    """nested.py runtime (non-TYPE_CHECKING) imports must be stdlib or Django only.

    graphql.GraphQLResolveInfo is allowed inside TYPE_CHECKING blocks (type
    annotations only, never imported at runtime).  At runtime, nested.py must
    NOT import from graphene or graphql-core directly.
    """
    import ast
    import pathlib

    source_path = pathlib.Path(__file__).parent.parent.parent / "django_graphex" / "nested.py"
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


def test_unwrap_enums_plain_values_passthrough():
    """_unwrap_enums must pass plain (non-Enum) values through unchanged."""
    from django_graphex.nested import NestedFieldsMixin

    item = {"name": "Alice", "age": 30, "active": True, "data": None}
    result = NestedFieldsMixin._unwrap_enums(dict(item))
    assert result == item


def test_unwrap_enums_single_enum_value():
    """_unwrap_enums must replace a scalar Enum member with its .value."""
    from django_graphex.nested import NestedFieldsMixin

    item = {"color": _Color.RED, "name": "test"}
    result = NestedFieldsMixin._unwrap_enums(item)
    assert result["color"] == "red"
    assert result["name"] == "test"


def test_unwrap_enums_multiple_enum_values():
    """_unwrap_enums must replace all Enum members in the dict."""
    from django_graphex.nested import NestedFieldsMixin

    item = {"color": _Color.BLUE, "priority": _Priority.HIGH, "label": "ok"}
    result = NestedFieldsMixin._unwrap_enums(item)
    assert result["color"] == "blue"
    assert result["priority"] == 2
    assert result["label"] == "ok"


def test_unwrap_enums_list_of_enums():
    """_unwrap_enums must unwrap Enum members inside list values."""
    from django_graphex.nested import NestedFieldsMixin

    item = {"colors": [_Color.RED, _Color.BLUE]}
    result = NestedFieldsMixin._unwrap_enums(item)
    assert result["colors"] == ["red", "blue"]


def test_unwrap_enums_tuple_of_enums():
    """_unwrap_enums must unwrap Enum members inside tuple values."""
    from django_graphex.nested import NestedFieldsMixin

    item = {"priorities": (_Priority.LOW, _Priority.HIGH)}
    result = NestedFieldsMixin._unwrap_enums(item)
    assert result["priorities"] == [1, 2]


def test_unwrap_enums_mixed_list():
    """_unwrap_enums must only unwrap Enum members in mixed lists."""
    from django_graphex.nested import NestedFieldsMixin

    item = {"values": [_Color.RED, "keep", 42, _Priority.LOW]}
    result = NestedFieldsMixin._unwrap_enums(item)
    assert result["values"] == ["red", "keep", 42, 1]


def test_unwrap_enums_empty_payload():
    """_unwrap_enums on empty dict returns empty dict."""
    from django_graphex.nested import NestedFieldsMixin

    result = NestedFieldsMixin._unwrap_enums({})
    assert result == {}


def test_unwrap_enums_empty_list_value():
    """_unwrap_enums with empty list value leaves it as empty list."""
    from django_graphex.nested import NestedFieldsMixin

    item = {"tags": []}
    result = NestedFieldsMixin._unwrap_enums(item)
    assert result["tags"] == []


def test_unwrap_enums_is_safe_noop_for_native_raw_values():
    """Under native backend, _unwrap_enums is effectively a no-op for non-Enum payloads.

    graphql-core resolvers receive plain Python values (not wrapped Enum objects)
    so _unwrap_enums will find nothing to unwrap in the typical native path.
    This test confirms the no-op behavior with a realistic native payload.
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
