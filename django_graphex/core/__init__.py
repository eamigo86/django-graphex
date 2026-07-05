"""Core schema engine — graphql-core + Pydantic compile / validate / execute (DRF-free).

Public surface: the schema-root base classes and the field descriptor are
re-exported here so callers import them from "django_graphex.core"
("from django_graphex.core import ObjectType, field") rather than reaching
into the implementation modules.
"""

from .base import InputType, ObjectType
from .descriptors import (
    BooleanField,
    CharField,
    DateField,
    DateTimeField,
    DecimalField,
    Field,
    FloatField,
    IDField,
    IntField,
    JSONField,
    TimeField,
    UUIDField,
    field,
)
from .mutation import Mutation
from .scalars import (
    GdxDate,
    GdxDateTime,
    GdxDecimal,
    GdxJSON,
    GdxJSONString,
    GdxTime,
    GdxUUID,
)

__all__ = (
    "ObjectType",
    "InputType",
    "field",
    "Mutation",
    # Django-style capitalized field descriptor (field-unify) — the single
    # position-agnostic ``Field``, usable in BOTH output and input positions.
    "Field",
    # Typed scalar shortcuts (field-unify) — one per scalar, usable in BOTH
    # positions; alphabetical. The former ``*InputField`` twins are gone.
    "BooleanField",
    "CharField",
    "DateField",
    "DateTimeField",
    "DecimalField",
    "FloatField",
    "IDField",
    "IntField",
    "JSONField",
    "TimeField",
    "UUIDField",
    # Native GraphQL scalar singletons — exported so users can wire custom
    # fields (e.g. ``from django_graphex.core import GdxJSONString``).
    "GdxDate",
    "GdxDateTime",
    "GdxTime",
    "GdxDecimal",
    "GdxUUID",
    "GdxJSONString",
    "GdxJSON",
)
