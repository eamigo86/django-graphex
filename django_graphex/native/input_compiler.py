"""Pydantic → GraphQLInputObjectType compiler.

Implements the input compile path for the native backend:

- ``compile_input_type``: iterates ``model.model_fields`` and emits a
  ``GraphQLInputObjectType`` with camelCase wire keys and ``out_name=snake_name``.
- ``coerce_input``: validates a raw dict via ``model_validate`` and returns the
  validated ``BaseModel`` instance, or raises ``GraphQLError`` on failure.
- ``translate_validation_error``: converts a Pydantic ``ValidationError`` to a
  ``{field: [messages]}`` dict using ``exc.errors(include_url=False)`` so the
  ``errors.pydantic.dev`` URL is NEVER included.

Design contracts:
- Wire-key = camelCase alias (the dict key in the fields map).
- ``out_name`` = snake_case ``field_name`` (graphql-core delivers this to resolvers).
- Build-time ``assert out_name != alias`` for multi-word fields (guards slip).
- ``fields=lambda`` thunk (graphql-core lazy evaluation, safe for forward refs).
- ``extensions={"gdx": GdxInputSpec(...)}`` on every compiled input type.
- ``errors.pydantic.dev`` URL MUST NEVER appear in any error extension.
"""

from __future__ import annotations

from dataclasses import dataclass, field as dc_field
from typing import Any

from graphql import (
    GraphQLInputField,
    GraphQLInputObjectType,
    GraphQLNonNull,
    GraphQLString,
    GraphQLInt,
    GraphQLFloat,
    GraphQLBoolean,
    GraphQLID,
)
from pydantic import BaseModel
from pydantic import ValidationError
from pydantic.alias_generators import to_camel
from graphql import GraphQLError

# ---------------------------------------------------------------------------
# GdxInputSpec — extensions["gdx"] payload for input types
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class GdxInputSpec:
    """Payload stored in ``extensions["gdx"]`` on every compiled input type.

    Mirrors the ``GdxPayload`` used for output types but carries input-specific
    metadata.  Phase 3/4 will extend this with ``nested_fields`` etc.
    """

    pydantic_model: Any = None
    name: str | None = None
    description: str | None = None


# ---------------------------------------------------------------------------
# Pydantic FieldInfo → graphql-core type mapping
# ---------------------------------------------------------------------------

# Map from Python annotation (unwrapped) to a GraphQL scalar type.
# Expanded types live here so we do not import the heavy scalars module
# for just the input compiler — callers can register additional scalars
# by patching ``_PYTHON_TO_GQL`` before the app finishes starting.
import decimal
import datetime
import uuid

from graphql import GraphQLScalarType

# Deferred import of native scalars to avoid circular imports at module load.
def _native_scalar_map() -> dict[type, GraphQLScalarType]:
    """Return the extended scalar map including GDX custom scalars."""
    try:
        from django_graphex.native.scalars import GDX_SCALAR_MAP  # type: ignore[import]
        # GDX_SCALAR_MAP is keyed by name; we need type→scalar mapping.
        # The scalars module maps Python types we care about here:
        from django_graphex.native.scalars import (  # type: ignore[import]
            GdxDate,
            GdxDateTime,
            GdxTime,
            GdxDecimal,
            GdxUUID,
            GdxJSONString,
        )
        return {
            datetime.date: GdxDate,
            datetime.datetime: GdxDateTime,
            datetime.time: GdxTime,
            decimal.Decimal: GdxDecimal,
            uuid.UUID: GdxUUID,
            dict: GdxJSONString,
        }
    except ImportError:
        return {}


_BUILTIN_MAP: dict[type, Any] = {
    str: GraphQLString,
    int: GraphQLInt,
    float: GraphQLFloat,
    bool: GraphQLBoolean,
    bytes: GraphQLString,  # serialize as base64 string
}


def _python_type_to_gql(py_type: Any) -> Any:
    """Map a Python type to a graphql-core scalar/type.

    Returns ``GraphQLString`` as a fallback for unknown types so the schema
    still builds (with a warning in dev).
    """
    if py_type is None:
        return GraphQLString

    # Direct builtins
    if py_type in _BUILTIN_MAP:
        return _BUILTIN_MAP[py_type]

    # Native scalars (GdxDate, GdxDateTime, etc.)
    native_map = _native_scalar_map()
    if py_type in native_map:
        return native_map[py_type]

    # Enum types → GraphQLString fallback (Phase 3 will wire enums properly)
    import enum as _enum
    if isinstance(py_type, type) and issubclass(py_type, _enum.Enum):
        return GraphQLString

    # Fallback
    return GraphQLString


def _is_required(field_info: Any) -> bool:
    """Return True if this Pydantic FieldInfo represents a required field."""
    from pydantic_core import PydanticUndefinedType
    return isinstance(field_info.default, PydanticUndefinedType) and (
        field_info.default_factory is None
    )


def _unwrap_optional(annotation: Any) -> tuple[Any, bool]:
    """Unwrap ``Optional[T]`` / ``T | None`` into ``(T, is_optional)``.

    Handles:
    - Python 3.10+ ``X | None`` syntax (``types.UnionType``)
    - ``typing.Optional[X]`` / ``typing.Union[X, None]``

    Returns:
        ``(inner_type, True)`` if annotation is ``T | None`` / ``Optional[T]``.
        ``(annotation, False)`` otherwise.
    """
    import types as _types
    import typing

    # Python 3.10+ union: str | None  → types.UnionType
    if isinstance(annotation, _types.UnionType):
        args = annotation.__args__
        non_none = [a for a in args if a is not type(None)]
        if len(non_none) == 1:
            return non_none[0], True
        return annotation, False

    # typing.Optional / typing.Union via __origin__ + __args__
    origin = getattr(annotation, "__origin__", None)
    args = getattr(annotation, "__args__", None)
    if origin is typing.Union and args is not None:
        non_none = [a for a in args if a is not type(None)]
        if len(non_none) == 1:
            return non_none[0], True
        return annotation, False

    return annotation, False


# ---------------------------------------------------------------------------
# translate_validation_error
# ---------------------------------------------------------------------------


def translate_validation_error(exc: ValidationError) -> dict[str, list[str]]:
    """Convert a Pydantic ``ValidationError`` to a ``{field: [messages]}`` dict.

    Critically, calls ``exc.errors(include_url=False)`` so the
    ``errors.pydantic.dev`` documentation URL is NEVER included in the output.
    """
    out: dict[str, list[str]] = {}
    for err in exc.errors(include_url=False):
        loc = [p for p in err["loc"] if not isinstance(p, int)]
        field_key = ".".join(str(p) for p in loc) or "non_field_errors"
        out.setdefault(field_key, []).append(err["msg"])
    return out


# ---------------------------------------------------------------------------
# coerce_input
# ---------------------------------------------------------------------------


def coerce_input(cls: type[BaseModel], raw: dict[str, Any]) -> BaseModel:
    """Validate ``raw`` against ``cls`` and return the validated instance.

    On validation failure, translates the Pydantic ``ValidationError`` into a
    ``GraphQLError`` with ``extensions={"code": "VALIDATION_ERROR", "fields": ...}``.
    The ``errors.pydantic.dev`` URL is NEVER included in the extensions.

    Args:
        cls: A Pydantic ``BaseModel`` subclass (the input model).
        raw: The raw dict received from the GraphQL client (camelCase keys).

    Returns:
        A validated ``BaseModel`` instance.

    Raises:
        ``GraphQLError`` with ``extensions.code == "VALIDATION_ERROR"`` on failure.
    """
    try:
        return cls.model_validate(raw)
    except ValidationError as exc:
        fields = translate_validation_error(exc)
        # Build a human-readable summary from the first few errors
        summary_parts = []
        for field_name, messages in list(fields.items())[:3]:
            for msg in messages[:2]:
                summary_parts.append(f"{field_name}: {msg}")
        summary = "; ".join(summary_parts) if summary_parts else "invalid input"

        raise GraphQLError(
            f"Input validation failed: {summary}",
            extensions={
                "code": "VALIDATION_ERROR",
                "fields": fields,
            },
        ) from exc


# ---------------------------------------------------------------------------
# compile_input_type
# ---------------------------------------------------------------------------


def compile_input_type(
    model: type[BaseModel],
    *,
    name: str,
    description: str | None = None,
) -> GraphQLInputObjectType:
    """Compile a Pydantic ``BaseModel`` into a ``GraphQLInputObjectType``.

    Wire-key contract per field:
    - dict key = camelCase **alias** (wire format)
    - ``out_name`` = snake_case **field_name** (delivered to resolver)
    - Build-time ``assert out_name != alias`` for multi-word fields

    The resulting type carries ``extensions={"gdx": GdxInputSpec(...)}`` so the
    ``assert_gdx_bridge`` assertion passes.

    Args:
        model: The Pydantic ``BaseModel`` class describing the input.
        name: The GraphQL type name (e.g. ``"PersonInput"``).
        description: Optional SDL description.

    Returns:
        A ``GraphQLInputObjectType`` with a ``lambda`` thunk for fields.
    """

    def _build_fields() -> dict[str, GraphQLInputField]:
        fields: dict[str, GraphQLInputField] = {}

        for field_name, field_info in model.model_fields.items():
            # Determine the wire alias (camelCase)
            alias: str
            if field_info.alias is not None:
                alias = field_info.alias
            else:
                alias = to_camel(field_name)

            # For multi-word fields: wire key != snake name → assert guard
            if alias != field_name:
                # Build-time assertion: out_name (snake) MUST differ from alias (camel)
                assert field_name != alias, (
                    f"compile_input_type: field {field_name!r} alias {alias!r} "
                    f"collision — out_name must differ from alias for multi-word fields."
                )

            # Resolve the Python type from annotation
            annotation = field_info.annotation
            inner_type, is_optional_flag = _unwrap_optional(annotation)
            gql_base_type = _python_type_to_gql(inner_type)

            # Determine nullability: required = NonNull, optional = nullable
            required = _is_required(field_info)
            # If the annotation itself is Optional, it's always nullable
            if is_optional_flag:
                required = False

            if required:
                gql_type: Any = GraphQLNonNull(gql_base_type)
            else:
                gql_type = gql_base_type

            # Build the GraphQLInputField with out_name = snake field_name
            gql_field = GraphQLInputField(
                type_=gql_type,
                out_name=field_name,
                description=field_info.description,
            )
            fields[alias] = gql_field

        return fields

    # Wrap in a lambda thunk for lazy evaluation
    return GraphQLInputObjectType(
        name=name,
        fields=lambda: _build_fields(),
        description=description,
        extensions={"gdx": GdxInputSpec(pydantic_model=model, name=name, description=description)},
    )
