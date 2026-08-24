"""Pydantic to GraphQLInputObjectType compiler.

Implements the input compile path for the native backend:

- "compile_input_type": iterates "model.model_fields" and emits a
  "GraphQLInputObjectType" with camelCase wire keys and "out_name=snake_name".
- "coerce_input": validates a raw dict via "model_validate" and returns the
  validated "BaseModel" instance, or raises "GraphQLError" on failure.
- "translate_validation_error": converts a Pydantic "ValidationError" to a
  "{field: [messages]}" dict using "exc.errors(include_url=False)" so the
  "errors.pydantic.dev" URL is NEVER included.

Design contracts:
- Wire-key = camelCase alias (the dict key in the fields map).
- "out_name" = snake_case "field_name" (graphql-core delivers this to resolvers).
- Build-time "assert out_name != alias" for multi-word fields (guards slip).
- "fields=lambda" thunk (graphql-core lazy evaluation, safe for forward refs).
- "extensions={gdx: GdxInputSpec(...)}" on every compiled input type.
- "errors.pydantic.dev" URL MUST NEVER appear in any error extension.
"""

from __future__ import annotations

import datetime
import decimal
import uuid
import warnings
from dataclasses import dataclass
from typing import Any

from graphql import (
    GraphQLBoolean,
    GraphQLError,
    GraphQLFloat,
    GraphQLID,
    GraphQLInputField,
    GraphQLInputObjectType,
    GraphQLInt,
    GraphQLList,
    GraphQLNonNull,
    GraphQLScalarType,
    GraphQLString,
    Undefined,
)
from pydantic import BaseModel, ValidationError
from pydantic.alias_generators import to_camel

# ---------------------------------------------------------------------------
# GdxInputSpec — extensions["gdx"] payload for input types
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class GdxInputSpec:
    """Payload stored in "extensions[gdx]" on every compiled input type.

    Mirrors the "GdxPayload" used for output types but carries input-specific
    metadata.  "nested_fields" carries the resolved nested object-input specs
    injected for a "Meta.nested_fields" host (empty for a plain input).
    """

    pydantic_model: Any = None
    name: str | None = None
    description: str | None = None
    nested_fields: tuple[NestedInputField, ...] = ()


@dataclass(frozen=True)
class NestedInputField:
    """A resolved nested object-input field to merge into a parent input type.

    Mirrors the legacy graphene nested-converter semantics natively: a
    "Meta.nested_fields" entry becomes either a single object input (forward
    FK / reverse-O2O) or a list of object inputs (M2M / reverse-FK), wrapping
    the CHILD model's compiled "GraphQLInputObjectType" as built for THIS parent
    (see "nested_child_input").

    Attributes:
        out_name: snake_case field/accessor name (the "nested_fields" dict key
            and the Django relation accessor; resolvers receive this via
            graphql-core "out_name" so "data.pop(field)" matches).
        alias: camelCase wire key the client sends.
        child_input_type: the child model's compiled "GraphQLInputObjectType"
            (or a "lambda" thunk returning it, for lazy/forward refs).
        is_list: True -> "[<Child>!]" list input (to-many relation);
            False -> single "<Child>" object input (to-one relation).
        required_perms: the CHILD model's write permissions, stamped onto the
            emitted input field as "extensions[gdx_required_perms]" so the
            permission-scoped-schema pruner removes the nested write surface
            from a caller who may not write the child directly either. A
            callable is resolved when the field map is built, which is what the
            generated specs pass so the label is read from the same host list as
            the child type beside it. None leaves the field unlabeled (public),
            which is what every hand-built spec wants.
    """

    out_name: str
    alias: str
    child_input_type: Any
    is_list: bool
    required_perms: Any = None


@dataclass(frozen=True)
class RelationInputField:
    """A Django relation rendered as an "ID" / "[ID]" input field.

    Mirrors the legacy graphene non-nested relation converters: forward FK /
    reverse-O2O -> a single "ID" ("ID!" when required on create); M2M and
    reverse-FK (to-many) -> a "[ID!]" list. The graphql-core "ID" scalar
    coerces both string and integer literals, so a client may send the related
    pk either way; pydantic then coerces the delivered value back to the model's
    pk Python type during validation.

    Attributes:
        out_name: snake_case field/accessor name (delivered to the resolver).
        alias: camelCase wire key the client sends.
        is_list: True -> "[ID!]" (to-many); False -> single "ID".
        required: True -> wrap the single "ID" in "GraphQLNonNull" (ignored for
            lists, which are always nullable to match graphene).
        inject_only: True -> this relation is NOT a base "model_fields" entry (a
            reverse relation) and must be ADDED; False -> it REPLACES the scalar
            the base loop emitted for the same out_name.
    """

    out_name: str
    alias: str
    is_list: bool
    required: bool
    inject_only: bool


@dataclass(frozen=True)
class ChoicesInputField:
    """A Django choices field rendered as a "GraphQLEnumType" input field.

    S-input-5 (choices INPUT off graphene): a choices field's INPUT surface
    historically rendered as "GraphQLString" (the "_python_type_to_gql" enum
    fallback) while the graphene converter built a dead "graphene.Enum". This
    spec carries the SHARED native "GraphQLEnumType" (the SAME canonical enum
    the OUTPUT + FILTER-INPUT paths resolve, S-enum-1) so the choices field is
    enum-typed on INPUT too — graphene-free and output/input symmetric.

    Attributes:
        out_name: snake_case field/accessor name (the base "model_fields" key it
            REPLACES, delivered to the resolver via graphql-core "out_name").
        alias: camelCase wire key the client sends.
        enum_type: the shared "GraphQLEnumType" instance (built via
            "converter.build_choices_enum_type").
        is_list: True -> "[Enum]" (a "MultiSelectField"); False -> single "Enum".
        required: True -> wrap the single enum in "GraphQLNonNull" (a required
            field on create).
    """

    out_name: str
    alias: str
    enum_type: Any
    is_list: bool
    required: bool


# ---------------------------------------------------------------------------
# Pydantic FieldInfo → graphql-core type mapping
# ---------------------------------------------------------------------------

# Map from Python annotation (unwrapped) to a GraphQL scalar type. Two maps
# feed ``_python_type_to_gql``: ``_BUILTIN_MAP`` (str/int/float/bool/bytes,
# defined below) and ``_native_scalar_map()`` (the GDX custom scalars, imported
# lazily so the heavy scalars module is not loaded just for the input compiler).


# Deferred import of native scalars to avoid circular imports at module load.
def _native_scalar_map() -> dict[type, GraphQLScalarType]:
    """Return the extended scalar map including GDX custom scalars."""
    try:
        # GDX_SCALAR_MAP is keyed by name; we need type→scalar mapping.
        # The scalars module maps Python types we care about here:
        from django_graphex.core.fields import (  # type: ignore[import]
            IDScalar,
            JSONScalar,
        )
        from django_graphex.core.scalars import (  # type: ignore[import]
            GdxDate,
            GdxDateTime,
            GdxDecimal,
            GdxJSON,
            GdxTime,
            GdxUUID,
        )

        return {
            datetime.date: GdxDate,
            datetime.datetime: GdxDateTime,
            datetime.time: GdxTime,
            decimal.Decimal: GdxDecimal,
            uuid.UUID: GdxUUID,
            # DurationField -> ``Float`` SECONDS, the SAME scalar the OUTPUT
            # compiler emits (it resolves through ``timedelta.total_seconds()``).
            # Pydantic coerces a number straight back to a ``timedelta``, so the
            # value a query returns can be written back unchanged. Without this
            # the annotation fell through to the loud ``String`` degradation.
            datetime.timedelta: GraphQLFloat,
            # The synthetic update-input pk -> ``ID``, matching the ``id: ID!``
            # the OUTPUT type and the sibling delete mutation already expose.
            IDScalar: GraphQLID,
            # HStoreField -> dict; JSONField -> the dedicated JSONScalar marker.
            # v2 RAW-JSON default: BOTH render as the raw ``JSON`` scalar
            # (structured passthrough via GdxJSON.parse_literal/parse_value),
            # NOT the string-encoded ``JSONString``.
            dict: GdxJSON,
            JSONScalar: GdxJSON,
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


# Attribute name the standalone (unregistered) compiled input type is memoized
# under, so a plain ``BaseModel`` subclass referenced as a nested input resolves
# to the SAME ``GraphQLInputObjectType`` instance on every access (a schema
# forbids two distinct types with one name).
_STANDALONE_INPUT_ATTR = "_gdx_standalone_input_type"


def _resolve_input_model_type(py_type: Any) -> Any:
    """Resolve a nested input-model annotation to its compiled input type.

    A field annotated with ANOTHER input model — a hand-authored ``InputType``
    subclass, or any bare ``pydantic.BaseModel`` subclass — must compile to that
    child's ``GraphQLInputObjectType``, NEVER the ``GraphQLString`` fallback (the
    pre-fix silent-corruption bug). Resolution mirrors the descriptor input path
    (``descriptors.py`` "_resolve_input_type"): prefer the compiled type already
    stamped on ``_meta.graphql_input_type`` (populated by ``compile_all_inputs``
    for registered ``InputType`` subclasses), so the schema reuses the ONE
    canonical instance. When no registered type exists (an unregistered
    ``BaseModel`` referenced directly, e.g. in isolation/tests), compile it once
    and memoize the result on the class so repeat resolutions return the SAME
    instance.

    Called from inside the parent's ``fields`` thunk, so resolution is LAZY: a
    child compiled AFTER the parent (later in ``compile_all_inputs`` registration
    order) is still resolved by the time graphql-core forces the parent's fields
    at schema-assembly time.

    Args:
        py_type: The (already optionality-unwrapped) annotation to resolve.

    Returns:
        The child ``GraphQLInputObjectType`` when "py_type" is a ``BaseModel``
        subclass; ``None`` when it is not (the caller keeps its scalar mapping).
    """
    if not (isinstance(py_type, type) and issubclass(py_type, BaseModel)):
        return None

    # Prefer the canonical compiled type registered by ``compile_all_inputs``.
    meta = getattr(py_type, "_meta", None)
    if meta is not None:
        compiled = getattr(meta, "graphql_input_type", None)
        if compiled is not None:
            return compiled

    # No registered type (unregistered ``BaseModel``): compile once and memoize
    # the instance on the class so every resolution returns the SAME type.
    cached = py_type.__dict__.get(_STANDALONE_INPUT_ATTR)
    if cached is not None:
        return cached
    compiled = compile_input_type(py_type, name=py_type.__name__)
    setattr(py_type, _STANDALONE_INPUT_ATTR, compiled)
    return compiled


def _python_type_to_gql(py_type: Any) -> Any:
    """Map a Python type to a graphql-core scalar/type.

    Returns ``GraphQLString`` as a fallback for unknown types so the schema
    still builds. Unlike the pre-fix silent fallback, a truly-unknown CLASS
    annotation (not a scalar, not an ``Enum``, not a ``BaseModel`` input model)
    now emits a loud ``UserWarning`` so the degradation is visible rather than
    silently corrupting a structured field into a ``String``.
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

    # FileField/ImageField -> the ``FileScalar`` marker. Matched by ``issubclass``
    # (not the identity lookup above) because the type resolver mints a per-column
    # -width SUBCLASS. The wire type stays ``String``: a client writes a storage
    # path, and a real upload arrives out of band in the multipart body, so
    # introducing an ``Upload`` scalar here would be a breaking wire change.
    from django_graphex.core.fields import FileScalar

    if isinstance(py_type, type) and issubclass(py_type, FileScalar):
        return GraphQLString

    # Nested input model (InputType / BaseModel subclass) -> its compiled input.
    nested = _resolve_input_model_type(py_type)
    if nested is not None:
        return nested

    # Enum types → GraphQLString fallback (Phase 3 will wire enums properly)
    import enum as _enum

    if isinstance(py_type, type) and issubclass(py_type, _enum.Enum):
        return GraphQLString

    # Truly-unknown CLASS: keep the String fallback (schema still builds) but
    # warn LOUDLY — a silent String here historically corrupted structured data.
    if isinstance(py_type, type):
        warnings.warn(
            f"compile_input_type: unsupported input field type {py_type.__name__!r} "
            f"({py_type.__module__}.{py_type.__qualname__}) — falling back to the "
            f"GraphQLString scalar. Annotate the field with a supported scalar, an "
            f"Enum, or an InputType/BaseModel subclass to avoid this degradation.",
            UserWarning,
            stacklevel=2,
        )

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


def _unwrap_list(annotation: Any) -> tuple[Any, bool]:
    """Detect a ``list[T]`` origin and return ``(inner_type, is_list)``.

    Handles ``list[T]`` (PEP 585 builtin generic) and ``typing.List[T]`` (both
    carry a ``list`` origin under ``typing.get_origin``). The annotation passed
    here is expected to already be optionality-unwrapped by ``_unwrap_optional``
    so ``Optional[list[T]]`` / ``list[T] | None`` reach this as bare ``list[T]``.

    Unsupported origins (``dict[...]``, ``tuple[...]``, etc.) are NOT lists and
    return ``(annotation, False)`` so the caller falls back to the existing
    scalar mapping — the file does not invent new behavior for those origins.

    Returns:
        ``(inner_type, True)`` for a list annotation (``inner_type`` is the
        element type, e.g. ``str`` for ``list[str]``, or ``str | None`` for
        ``list[str | None]``); ``(annotation, False)`` otherwise.
    """
    import typing

    origin = typing.get_origin(annotation)
    if origin is list:
        args = typing.get_args(annotation)
        # ``list`` (bare, no parameter) has no args -> element type unknown;
        # fall back to the scalar String path via a None inner.
        inner = args[0] if args else None
        return inner, True
    return annotation, False


def _default_value_for(field_info: Any) -> Any:
    """Resolve the graphql-core ``default_value`` for a Pydantic ``FieldInfo``.

    Distinguishes the four Pydantic v2 default states so the SDL renders the
    correct default marker:

    - ``PydanticUndefined`` (no default) -> graphql-core ``Undefined`` (the SDL
      omits the ``= ...`` marker entirely).
    - explicit ``None`` default -> ``None`` (SDL renders ``= null``).
    - a concrete value (``1``, ``False``, ...) -> that value (SDL ``= <value>``).
    - a ``default_factory`` -> the factory is invoked ONCE here at compile time
      and the produced value is used. SINGLE-EVALUATION CONSTRAINT: the factory
      runs exactly once (when the fields thunk builds), so a mutable factory
      default (e.g. ``list``) yields one shared default instance baked into the
      SDL — this matches graphql-core's static-default model and never re-runs
      the factory per request.
    - a Pydantic 2.10+ VALIDATED-DATA factory (``default_factory=lambda data:
      ...``) -> graphql-core ``Undefined``. Such a factory needs the partially
      validated instance data, so it has no compile-time value and cannot be a
      static SDL default; Pydantic still applies it per instance at validation
      time.

    Returns:
        The graphql-core ``default_value`` (``Undefined`` when there is none).
    """
    from pydantic_core import PydanticUndefined

    if field_info.default_factory is not None:
        if getattr(field_info, "default_factory_takes_validated_data", False):
            # Needs the validated data -> no compile-time value exists.
            return Undefined
        # Single evaluation: call the factory exactly once at compile time.
        return field_info.default_factory()
    if field_info.default is PydanticUndefined:
        return Undefined
    return field_info.default


# ---------------------------------------------------------------------------
# translate_validation_error
# ---------------------------------------------------------------------------


def translate_validation_error(exc: ValidationError) -> dict[str, list[str]]:
    """Convert a Pydantic "ValidationError" to a "{field: [messages]}" dict.

    Critically, calls "exc.errors(include_url=False)" so the
    "errors.pydantic.dev" documentation URL is NEVER included in the output.
    Integer path parts (list indices) are dropped from the field key, and an
    empty resulting key collapses to "non_field_errors".

    Args:
        exc: The Pydantic validation error to translate.

    Returns:
        A mapping of field key to its list of error messages.
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
    """Validate "raw" against "cls" and return the validated instance.

    On validation failure, translates the Pydantic "ValidationError" into a
    "GraphQLError" with "extensions={code: VALIDATION_ERROR, fields: ...}".
    The "errors.pydantic.dev" URL is NEVER included in the extensions.

    Args:
        cls: A Pydantic "BaseModel" subclass (the input model).
        raw: The raw dict received from the GraphQL client (camelCase keys).

    Returns:
        A validated "BaseModel" instance.

    Raises:
        GraphQLError: On validation failure, carrying
            "extensions.code == VALIDATION_ERROR" and the per-field messages.
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
    thunk). This normalizes both to the concrete graphql-core type. A compiled
    type is an INSTANCE, never a callable, so the two cases cannot be confused.

    Args:
        child: The compiled input type or a thunk returning it.

    Returns:
        The resolved graphql-core input type.
    """
    return child() if callable(child) else child


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
    emit_defaults: bool | None = None,
) -> GraphQLInputObjectType:
    """Compile a Pydantic "BaseModel" into a "GraphQLInputObjectType".

    Wire-key contract per field:
    - dict key = camelCase alias (wire format)
    - "out_name" = snake_case field_name (delivered to resolver)
    - Build-time "assert out_name != alias" for multi-word fields

    The resulting type carries "extensions={gdx: GdxInputSpec(...)}" so the
    "assert_gdx_bridge" assertion passes.

    When "nested_fields" is non-empty, each entry injects (or REPLACES, for a
    relation whose scalar fk/id surface the base model already emitted) a nested
    object-input field on the parent, mirroring the legacy graphene nested
    converters: forward FK / reverse-O2O -> single "<Child>" object input;
    M2M / reverse-FK -> "[<Child>!]" list input. The child input type is the
    related model's compiled generic "GraphQLInputObjectType".

    Args:
        model: The Pydantic "BaseModel" class describing the input.
        name: The GraphQL type name (e.g. "PersonInput").
        description: Optional SDL description.
        nested_fields: Resolved nested object-input specs to merge into the
            parent's fields (empty for a plain input type).
        relation_fields: Django relations to render as "ID" / "[ID]" inputs
            (forward FK / O2O / M2M / reverse-FK), mirroring graphene's
            non-nested relation converters (empty for a relation-free input).
        choices_fields: Django choices fields to render as shared
            "GraphQLEnumType" inputs (empty for a choices-free input).
        only_fields: When set, restricts the emitted wire fields to these names.
        exclude_fields: When set, omits these field names from the wire surface.
        include_fields: Field names force-included even when "only_fields" /
            "exclude_fields" would skip them (issue #65).
        emit_defaults: Whether to surface Pydantic field defaults as graphql-core
            "default_value" (so the SDL renders "= <value>"). None (the default)
            AUTO-DETECTS: a hand-authored "InputType" subclass (it carries
            "_gdx_opts") emits its user-declared defaults; a Django-model-derived
            schema from "build_model_schema" (no "_gdx_opts") does NOT. This gate
            is load-bearing: graphql-core injects an input field's "default_value"
            into the coerced dict for OMITTED fields, and the mutation
            "save_object" path relies on "model_fields_set" to distinguish an
            omitted field from an explicit "null" (omit = leave untouched on
            update, explicit null = clear). Emitting the synthetic "None" that
            "build_model_schema" stamps on every optional/partial field would
            materialize omitted fields as "None" and break that omit-vs-null
            semantics. Pass True/False to force the behavior.

    Returns:
        A "GraphQLInputObjectType" with a "lambda" thunk for fields.
    """
    # AUTO-DETECT (emit_defaults=None): only hand-authored ``InputType`` subclasses
    # (which carry ``_gdx_opts``) surface their declared defaults into the SDL.
    # Django-model-derived schemas (``<Model>Native`` from ``build_model_schema``)
    # must NOT, so the mutation omit-vs-null contract stays intact (see the
    # ``emit_defaults`` docstring above).
    _emit_defaults = (
        hasattr(model, "_gdx_opts") if emit_defaults is None else emit_defaults
    )

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

            # Resolve the Python type from annotation. First strip Optional
            # (``Optional[list[T]]`` / ``list[T] | None`` -> ``list[T]``), then
            # detect a list origin so ``list[T]`` compiles to a GraphQL list
            # type instead of the scalar String fallback.
            annotation = field_info.annotation
            inner_type, is_optional_flag = _unwrap_optional(annotation)
            list_inner, is_list = _unwrap_list(inner_type)

            if is_list:
                # Element type: recurse the optionality strip so ``list[T | None]``
                # yields a nullable element and ``list[T]`` a non-null element,
                # mirroring the relation-list inner-NonNull precedent (:503-504).
                element_type, element_optional = _unwrap_optional(list_inner)
                gql_element = _python_type_to_gql(element_type)
                gql_base_type: Any = (
                    gql_element if element_optional else GraphQLNonNull(gql_element)
                )
                gql_base_type = GraphQLList(gql_base_type)
            else:
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

            # Build the GraphQLInputField with out_name = snake field_name.
            # ``default_value`` carries the Pydantic default (Undefined when the
            # field has none) so the SDL renders the correct ``= ...`` marker.
            # Gated on ``_emit_defaults``: the Django-mutation path leaves it
            # Undefined so graphql-core does NOT inject a value for omitted fields
            # (preserving the ``model_fields_set`` omit-vs-null contract).
            default_value = (
                _default_value_for(field_info) if _emit_defaults else Undefined
            )
            gql_field = GraphQLInputField(
                type_=gql_type,
                out_name=field_name,
                description=field_info.description,
                default_value=default_value,
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
            # issue #65 (audit rank 1): honor Meta only/include/exclude on the
            # relation ID-surface INPUT field too. ``include_fields``
            # force-includes even when only/exclude would skip it — EXACT same
            # gating the base ``model_fields`` + choices loops apply on the snake
            # name (rf.out_name is the same snake key space). Without this a
            # relation excluded via ``exclude_fields`` (or filtered out by
            # ``only_fields``) would LEAK onto the input — an access-control hole.
            _forced = _incl is not None and rf.out_name in _incl
            if not _forced and _only is not None and rf.out_name not in _only:
                continue
            if not _forced and _excl is not None and rf.out_name in _excl:
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
        # model's ``GraphQLInputObjectType`` as built FOR THIS PARENT (see
        # ``mutation.nested_child_input``). out_name is the snake accessor so
        # the resolver's ``data.pop(field)`` matches the Django relation name.
        # ----------------------------------------------------------------
        for nf in nested_fields:
            # issue #65 (audit rank 2): honor Meta only/include/exclude on the
            # nested object-input field too — same gating as the base, choices,
            # and relation loops on the snake name (nf.out_name is the same snake
            # key space). Without this a nested input excluded via
            # ``exclude_fields`` (or filtered out by ``only_fields``) would LEAK
            # onto the mutation input.
            _forced = _incl is not None and nf.out_name in _incl
            if not _forced and _only is not None and nf.out_name not in _only:
                continue
            if not _forced and _excl is not None and nf.out_name in _excl:
                continue
            child_type = _resolve_child_input_type(nf.child_input_type)
            if nf.is_list:
                field_type: Any = GraphQLList(GraphQLNonNull(child_type))
            else:
                field_type = child_type
            # Resolved HERE, beside the child type above, because the two are
            # halves of one host declaration and reading them at different
            # moments let a host reach only one of them.
            perms = nf.required_perms
            if callable(perms):
                perms = perms()
            fields[nf.alias] = GraphQLInputField(
                type_=field_type,
                out_name=nf.out_name,
                extensions=({"gdx_required_perms": perms} if perms is not None else {}),
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
