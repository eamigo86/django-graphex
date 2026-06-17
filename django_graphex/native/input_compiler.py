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
    GraphQLList,
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
    metadata.  ``nested_fields`` carries the resolved nested object-input specs
    injected for a ``Meta.nested_fields`` host (empty for a plain input).
    """

    pydantic_model: Any = None
    name: str | None = None
    description: str | None = None
    nested_fields: tuple[NestedInputField, ...] = ()


@dataclass(frozen=True)
class NestedInputField:
    """A resolved nested object-input field to merge into a parent input type.

    Mirrors the legacy graphene nested-converter semantics natively: a
    ``Meta.nested_fields`` entry becomes either a single object input (forward
    FK / reverse-O2O) or a list of object inputs (M2M / reverse-FK), wrapping
    the CHILD model's compiled ``GraphQLInputObjectType`` (its generic input,
    already registered on demand by ``_ensure_child_generic_input``).

    Attributes:
        out_name: snake_case field/accessor name (the ``nested_fields`` dict key
            and the Django relation accessor; resolvers receive this via
            graphql-core ``out_name`` so ``data.pop(field)`` matches).
        alias: camelCase wire key the client sends.
        child_input_type: the child model's compiled ``GraphQLInputObjectType``
            (or a ``lambda`` thunk returning it, for lazy/forward refs).
        is_list: ``True`` -> ``[<Child>!]`` list input (to-many relation);
            ``False`` -> single ``<Child>`` object input (to-one relation).
    """

    out_name: str
    alias: str
    child_input_type: Any
    is_list: bool


@dataclass(frozen=True)
class RelationInputField:
    """A Django relation rendered as an ``ID`` / ``[ID]`` input field.

    Mirrors the legacy graphene non-nested relation converters: forward FK /
    reverse-O2O -> a single ``ID`` (``ID!`` when required on create); M2M and
    reverse-FK (to-many) -> a ``[ID!]`` list. The graphql-core ``ID`` scalar
    coerces both string and integer literals, so a client may send the related
    pk either way; pydantic then coerces the delivered value back to the model's
    pk Python type during validation.

    Attributes:
        out_name: snake_case field/accessor name (delivered to the resolver).
        alias: camelCase wire key the client sends.
        is_list: ``True`` -> ``[ID!]`` (to-many); ``False`` -> single ``ID``.
        required: ``True`` -> wrap the single ``ID`` in ``GraphQLNonNull``
            (ignored for lists, which are always nullable to match graphene).
        inject_only: ``True`` -> this relation is NOT a base ``model_fields``
            entry (a reverse relation) and must be ADDED; ``False`` -> it
            REPLACES the scalar the base loop emitted for the same out_name.
    """

    out_name: str
    alias: str
    is_list: bool
    required: bool
    inject_only: bool


@dataclass(frozen=True)
class ChoicesInputField:
    """A Django choices field rendered as a ``GraphQLEnumType`` input field.

    S-input-5 (choices INPUT off graphene): a choices field's INPUT surface
    historically rendered as ``GraphQLString`` (the ``_python_type_to_gql`` enum
    fallback) while the graphene converter built a dead ``graphene.Enum``. This
    spec carries the SHARED native ``GraphQLEnumType`` (the SAME canonical enum
    the OUTPUT + FILTER-INPUT paths resolve, S-enum-1) so the choices field is
    enum-typed on INPUT too — graphene-free and output/input symmetric.

    Attributes:
        out_name: snake_case field/accessor name (the base ``model_fields`` key it
            REPLACES, delivered to the resolver via graphql-core ``out_name``).
        alias: camelCase wire key the client sends.
        enum_type: the shared ``GraphQLEnumType`` instance (built via
            ``converter.build_choices_enum_type``).
        is_list: ``True`` -> ``[Enum]`` (a ``MultiSelectField``); ``False`` ->
            single ``Enum``.
        required: ``True`` -> wrap the single enum in ``GraphQLNonNull`` (a
            required field on create).
    """

    out_name: str
    alias: str
    enum_type: Any
    is_list: bool
    required: bool


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


def _resolve_child_input_type(child: Any) -> Any:
    """Unwrap a nested child input spec into its graphql-core input type.

    ``NestedInputField.child_input_type`` may be a compiled
    ``GraphQLInputObjectType`` directly, or a zero-arg ``lambda`` thunk
    returning one (lazy/forward-ref resolution inside the parent's own field
    thunk). This normalizes both to the concrete graphql-core type.

    Args:
        child: The compiled input type or a thunk returning it.

    Returns:
        The resolved graphql-core input type.
    """
    return child() if callable(child) and not isinstance(child, type) else child


def compile_input_type(
    model: type[BaseModel],
    *,
    name: str,
    description: str | None = None,
    nested_fields: tuple[NestedInputField, ...] = (),
    relation_fields: tuple[RelationInputField, ...] = (),
    choices_fields: tuple[ChoicesInputField, ...] = (),
    only_fields: tuple[str, ...] | list[str] | None = None,
    exclude_fields: tuple[str, ...] | list[str] | None = None,
    include_fields: tuple[str, ...] | list[str] | None = None,
) -> GraphQLInputObjectType:
    """Compile a Pydantic ``BaseModel`` into a ``GraphQLInputObjectType``.

    Wire-key contract per field:
    - dict key = camelCase **alias** (wire format)
    - ``out_name`` = snake_case **field_name** (delivered to resolver)
    - Build-time ``assert out_name != alias`` for multi-word fields

    The resulting type carries ``extensions={"gdx": GdxInputSpec(...)}`` so the
    ``assert_gdx_bridge`` assertion passes.

    When ``nested_fields`` is non-empty, each entry injects (or REPLACES, for a
    relation whose scalar fk/id surface the base model already emitted) a nested
    object-input field on the parent, mirroring the legacy graphene nested
    converters: forward FK / reverse-O2O -> single ``<Child>`` object input;
    M2M / reverse-FK -> ``[<Child>!]`` list input. The child input type is the
    related model's compiled generic ``GraphQLInputObjectType``.

    Args:
        model: The Pydantic ``BaseModel`` class describing the input.
        name: The GraphQL type name (e.g. ``"PersonInput"``).
        description: Optional SDL description.
        nested_fields: Resolved nested object-input specs to merge into the
            parent's fields (empty for a plain input type).
        relation_fields: Django relations to render as ``ID`` / ``[ID]`` inputs
            (forward FK / O2O / M2M / reverse-FK), mirroring graphene's
            non-nested relation converters (empty for a relation-free input).

    Returns:
        A ``GraphQLInputObjectType`` with a ``lambda`` thunk for fields.
    """

    def _build_fields() -> dict[str, GraphQLInputField]:
        fields: dict[str, GraphQLInputField] = {}

        # The snake out_names claimed by nested object inputs; the base scalar
        # loop below skips these so a forward-FK ``author_id``-style scalar does
        # not shadow the nested ``author`` object input (and vice versa).
        _nested_out_names = {nf.out_name for nf in nested_fields}
        # out_names a relation spec REPLACES on the base model (the scalar the
        # pydantic model emitted for a forward FK / M2M) -> skip them so the
        # ``ID`` / ``[ID]`` relation field is the one that lands.
        _relation_replace = {
            rf.out_name for rf in relation_fields if not rf.inject_only
        }
        # out_names a choices spec REPLACES (the ``String`` the base loop would
        # emit from the pydantic Enum annotation) -> skip so the enum field lands.
        _choices_replace = {cf.out_name for cf in choices_fields}

        # issue #65: Meta only/include/exclude field selection on the INPUT type.
        # ``include_fields`` force-includes a field even when only/exclude would
        # skip it (mirrors ``converter.construct_fields`` + the native output
        # compiler). The pydantic validation model still carries every field; the
        # GraphQL input type is the WIRE contract, so a field omitted here simply
        # cannot be sent by a client.
        _only = set(only_fields) if only_fields else None
        _excl = set(exclude_fields) if exclude_fields else None
        _incl = set(include_fields) if include_fields else None

        for field_name, field_info in model.model_fields.items():
            if field_name in _nested_out_names:
                continue
            if field_name in _relation_replace:
                continue
            if field_name in _choices_replace:
                continue
            _forced = _incl is not None and field_name in _incl
            if not _forced and _only is not None and field_name not in _only:
                continue
            if not _forced and _excl is not None and field_name in _excl:
                continue
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

        # ----------------------------------------------------------------
        # Relation ID-surface injection (non-nested relations). Mirrors the
        # legacy graphene relation converters: forward FK / reverse-O2O ->
        # single ``ID`` (``ID!`` when required on create); M2M / reverse-FK ->
        # ``[ID!]`` list. graphql-core's ``ID`` scalar coerces both string and
        # int literals; the snake out_name routes the value to the resolver,
        # where pydantic coerces it back to the model's pk type. A nested
        # object input for the SAME accessor (see below) overrides this.
        # ----------------------------------------------------------------
        _nested_aliases = {nf.alias for nf in nested_fields}
        for rf in relation_fields:
            if rf.alias in _nested_aliases:
                # A nested object input claims this accessor — skip the ID form.
                continue
            if rf.is_list:
                rel_type: Any = GraphQLList(GraphQLNonNull(GraphQLID))
            elif rf.required:
                rel_type = GraphQLNonNull(GraphQLID)
            else:
                rel_type = GraphQLID
            fields[rf.alias] = GraphQLInputField(
                type_=rel_type,
                out_name=rf.out_name,
            )

        # ----------------------------------------------------------------
        # Choices enum injection (S-input-5). A choices field's INPUT surface is
        # the SHARED native ``GraphQLEnumType`` (the SAME canonical enum the
        # OUTPUT + FILTER-INPUT paths use, S-enum-1) instead of the ``String``
        # fallback the pydantic Enum annotation would otherwise produce. A
        # ``MultiSelectField`` becomes ``[Enum]`` (mirroring the converter's
        # ``DjangoListField(enum)``); a plain choices field becomes a single
        # ``Enum`` (``Enum!`` when required on create). out_name routes the value
        # to the resolver, where pydantic coerces it (the enum value carries the
        # RAW python value, so resolution is identical to graphene's).
        # ----------------------------------------------------------------
        for cf in choices_fields:
            # issue #65: honor Meta only/include/exclude on the choices INPUT
            # field too. ``include_fields`` force-includes even when only/exclude
            # would skip it — EXACT same gating the base ``model_fields`` loop
            # applies on the snake field_name (cf.out_name is the same snake key
            # space). Without this a choices field excluded via ``exclude_fields``
            # (or filtered out by ``only_fields``) would LEAK onto the input.
            _forced = _incl is not None and cf.out_name in _incl
            if not _forced and _only is not None and cf.out_name not in _only:
                continue
            if not _forced and _excl is not None and cf.out_name in _excl:
                continue
            if cf.is_list:
                ch_type: Any = GraphQLList(cf.enum_type)
            elif cf.required:
                ch_type = GraphQLNonNull(cf.enum_type)
            else:
                ch_type = cf.enum_type
            fields[cf.alias] = GraphQLInputField(
                type_=ch_type,
                out_name=cf.out_name,
            )

        # ----------------------------------------------------------------
        # Nested object-input injection (Meta.nested_fields). Mirrors the
        # legacy graphene nested converters: a to-one relation becomes a
        # single ``<Child>`` object input, a to-many relation becomes a
        # ``[<Child>!]`` list input. The child input type is the related
        # model's compiled generic ``GraphQLInputObjectType`` (ensured on
        # demand upstream). out_name is the snake accessor so the resolver's
        # ``data.pop(field)`` matches the Django relation name.
        # ----------------------------------------------------------------
        for nf in nested_fields:
            child_type = _resolve_child_input_type(nf.child_input_type)
            if child_type is None:
                # Child input unresolved (no registered type) -> skip rather
                # than emit a broken field; mirrors the legacy converter's
                # ``if not _type: return`` silent-skip for unresolved children.
                continue
            if nf.is_list:
                field_type: Any = GraphQLList(GraphQLNonNull(child_type))
            else:
                field_type = child_type
            fields[nf.alias] = GraphQLInputField(
                type_=field_type,
                out_name=nf.out_name,
            )

        return fields

    # Wrap in a lambda thunk for lazy evaluation
    return GraphQLInputObjectType(
        name=name,
        fields=lambda: _build_fields(),
        description=description,
        extensions={
            "gdx": GdxInputSpec(
                pydantic_model=model,
                name=name,
                description=description,
                nested_fields=tuple(nested_fields),
            )
        },
    )
