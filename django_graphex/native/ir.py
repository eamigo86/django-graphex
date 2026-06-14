"""Pure-Python IR dataclasses for the native output compiler.

Zero imports from django, graphene, or graphql.  These are value objects only:
frozen dataclasses that the compiler reads at schema-build time.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable


@dataclass(frozen=True)
class TypeRef:
    """Reference to a named type (by string name).

    ``inner`` enables nested wrapping such as ``[T!]!``.
    """

    name: str
    list: bool = False
    non_null: bool = False
    inner: "TypeRef | None" = None


@dataclass(frozen=True)
class GdxMeta:
    """Carrier for GraphQL-only metadata Pydantic cannot express.

    Holds ``Any`` for ``model`` so no Django import is required.
    """

    model: Any = None
    max_deep: int | None = None
    complexity: int | None = None
    relation_accessor: str | None = None
    name: str | None = None
    only_fields: tuple[str, ...] | None = None
    exclude_fields: tuple[str, ...] | None = None
    skip_registry: bool = False
    input_for: str | None = None
    gfk_unions: Any = None
    interfaces: tuple | None = None
    max_page_size: int | None = None
    results_field_name: str | None = None
    pagination: Any = None
    nested_fields: Any = None
    backend: str | None = None
    node: Any = None
    filter_fields: Any = None
    arguments: Any = None
    output_field_name: str | None = None
    input_field_name: str | None = None
    output: Any = None
    model_operations: Any = None
    registry: Any = None
    graphql_input_type: Any = None


@dataclass(frozen=True)
class FieldSpec:
    """Descriptor for a single output field.

    ``name`` is the **snake_case** source name; camelCase is derived at
    compile time by the compiler.
    """

    name: str
    type: TypeRef
    description: str | None = None
    resolver: Callable | None = None
    gdx: GdxMeta | None = None


@dataclass(frozen=True)
class TypeSpec:
    """Descriptor for a GraphQL object type."""

    name: str
    fields: tuple[FieldSpec, ...]
    description: str | None = None
    gdx: GdxMeta | None = None


@dataclass(frozen=True)
class EnumSpec:
    """Descriptor for a GraphQL enum type.

    ``values`` is a sequence of ``(graphql_name, raw_value)`` pairs.
    The raw value is delivered via ``GraphQLEnumValue(value=raw)`` so callers
    receive the raw Python value, not a wrapped enum member.
    """

    name: str
    values: tuple[tuple[str, Any], ...]
    descriptions: dict[str, str] | None = None
