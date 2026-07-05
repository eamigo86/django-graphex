"""Native output/list factory.

"native_factory_type(op, base, **kw)" runs parallel to the UNTOUCHED
"base_types.factory_type". It builds Django output/list types for the native
compile path via "type(name, (base,), {...})".

- "output": creates a simple Django output type subclass.
- "list": creates a three-field list type subclass with
  "_gdx_list_fields = {results_field_name, totalCount, pageInfo}".
- "input": delegates to the Phase 2 input factory (not implemented in WU-A;
  raises "NotImplementedError" if called in this phase).

The factory does NOT mutate "base_types.factory_type" — that remains the
graphene path and MUST stay untouched.

"from_attributes=False" is the implicit contract: native output types never
use Pydantic's "model_validate", so the setting is irrelevant here, but the
returned class must NEVER set "model_config.from_attributes = True".

No imports from "graphene". No mutation of "converter.py".
"""

from __future__ import annotations

from typing import Any

from django_graphex._strconv import to_camel_case as _to_camel_case

# ---------------------------------------------------------------------------
# Three standard list field names (Phase 3 spec §B2)
# ---------------------------------------------------------------------------

_LIST_FIELD_NAMES = frozenset({"results_field_name", "totalCount", "pageInfo"})


# ---------------------------------------------------------------------------
# native_factory_type
# ---------------------------------------------------------------------------


def native_factory_type(op: str, base: type, *args: Any, **kwargs: Any) -> type:
    """Create a native factory type based on the operation.

    Args:
        op: One of "output", "list", or "input".
        base: Base class the generated type derives from.
        *args: Extra positional arguments (delegated to the input factory).
        **kwargs: Type configuration such as "model", "name", "only_fields",
            "exclude_fields", "results_field_name", "pagination", "queryset",
            "registry".

    Returns:
        The generated type class, a subclass of "base".

    Raises:
        NotImplementedError: For op="input" (delegated to Phase 2; call
            base_types.factory_type("input", ...) instead).
        ValueError: For unknown "op" values.
    """
    if op == "output":
        return _make_output_type(base, **kwargs)
    elif op == "list":
        return _make_list_type(base, **kwargs)
    elif op == "input":
        raise NotImplementedError(
            "native_factory_type: 'input' delegates to Phase 2. "
            "Use base_types.factory_type('input', ...) for the graphene path "
            "or compile_input_type() for the native path."
        )
    else:
        raise ValueError(
            f"native_factory_type: unknown op {op!r}. "
            f"Expected 'output', 'list', or 'input'."
        )


# ---------------------------------------------------------------------------
# Output type builder
# ---------------------------------------------------------------------------


def _make_output_type(base: type, **kwargs: Any) -> type:
    """Build a native output type class from ``base``.

    The generated class carries:
    - ``_gdx_model``: the Django model class (if provided).
    - ``_gdx_name``: the resolved GraphQL type name.
    - ``_gdx_options``: dict of all kwargs (for the registry compiler).

    Args:
        base: Base class to derive from.
        **kwargs: Configuration options including ``model``, ``name``,
                  ``only_fields``, ``exclude_fields``, ``registry``, etc.

    Returns:
        A new class that subclasses ``base``.
    """
    model = kwargs.get("model")
    name = kwargs.get("name")
    if name is None and model is not None:
        name = _to_camel_case(f"{model.__name__}_Generic_Type")
    elif name is None:
        name = "GenericOutputType"

    namespace: dict[str, Any] = {
        "_gdx_model": model,
        "_gdx_name": name,
        "_gdx_options": dict(kwargs),
        "__doc__": f"Auto-generated native output type for {model.__name__ if model else name}.",
    }

    cls = type(name, (base,), namespace)
    return cls


# ---------------------------------------------------------------------------
# List type builder
# ---------------------------------------------------------------------------


def _make_list_type(base: type, **kwargs: Any) -> type:
    """Build a native list type class from ``base``.

    The generated class carries:
    - ``_gdx_list_fields``: frozenset of the three standard field names.
    - ``_gdx_results_field_name``: the resolved results field name.
    - ``_gdx_model``: the Django model class (if provided).
    - ``_gdx_options``: dict of all kwargs.

    The three standard fields (per Phase 3 spec):
    1. ``results_field_name`` — configurable, defaults to ``"results"``.
    2. ``totalCount`` — total record count for pagination.
    3. ``pageInfo`` — pagination cursor/offset metadata.

    Args:
        base: Base class to derive from.
        **kwargs: Configuration options including ``model``, ``name``,
                  ``results_field_name``, ``pagination``, ``queryset``, etc.

    Returns:
        A new class that subclasses ``base``.
    """
    model = kwargs.get("model")
    name = kwargs.get("name")
    results_field_name = kwargs.get("results_field_name") or "results"

    if name is None and model is not None:
        name = _to_camel_case(f"{model.__name__}_List_Type")
    elif name is None:
        name = "GenericListType"

    # Three-field specification (Phase 3 contract)
    gdx_list_fields: dict[str, Any] = {
        "results_field_name": results_field_name,
        "totalCount": "Int",  # GraphQL scalar name (resolved at compile time)
        "pageInfo": "PageInfo",  # GraphQL type name (resolved at compile time)
    }

    namespace: dict[str, Any] = {
        "_gdx_model": model,
        "_gdx_name": name,
        "_gdx_list_fields": gdx_list_fields,
        "_gdx_results_field_name": results_field_name,
        "_gdx_options": dict(kwargs),
        "__doc__": f"Auto-generated native list type for {model.__name__ if model else name}.",
    }

    cls = type(name, (base,), namespace)
    return cls
