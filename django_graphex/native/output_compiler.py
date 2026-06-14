"""Native output field compiler: Django model fields → GraphQL fields.

Implements the Django-aware layer on top of the base ``compiler.py`` thunk core:

- ``_to_graphql_field(field, registry)``: maps a single Django model field to a
  ``{camelCase_key: GraphQLField}`` dict.  Scalars come from ``DJANGO_TO_GQL``;
  relation fields become zero-arg lambda thunks resolved via the registry.

- ``compile_output_fields(model, registry, **opts)``: iterates the model's
  concrete fields and relation fields and returns the full ``{str: GraphQLField}``
  dict suitable for passing to ``GraphQLObjectType(fields=...)``.

Design contracts:
- camelCase via dict KEY (GraphQLField has no out_name for output types).
- FK/M2M relations are zero-arg lambda thunks: ``lambda t=cls: registry.get_compiled(t)``.
  The default-arg idiom ``t=cls`` fixes the loop-variable capture footgun.
- Scalars come from ``DJANGO_TO_GQL`` (map from Django field class → GraphQL type).
- ``GdxMeta`` as ``Annotated`` OUTPUT-only metadata: not eager-instantiated.
- No imports of graphene. No mutation of ``converter.py`` dispatchers.
- ``from_attributes=False`` is enforced at the factory/registry level, not here.
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING, Any

from graphql import (
    GraphQLBoolean,
    GraphQLField,
    GraphQLFloat,
    GraphQLID,
    GraphQLInt,
    GraphQLNonNull,
    GraphQLString,
)

from django_graphex.native.scalars import (
    GdxDate,
    GdxDateTime,
    GdxJSONString,
    GdxTime,
    GdxUUID,
)

if TYPE_CHECKING:
    pass


# ---------------------------------------------------------------------------
# camelCase conversion (reuse from compiler.py pattern)
# ---------------------------------------------------------------------------

_CAMEL_RE = re.compile(r"_([a-z])")


def _to_camel_case(snake: str) -> str:
    """Convert snake_case to camelCase.

    Examples:
        'created_at' → 'createdAt'
        'first_name_value' → 'firstNameValue'
        'title' → 'title'
    """
    return _CAMEL_RE.sub(lambda m: m.group(1).upper(), snake)


# ---------------------------------------------------------------------------
# Django field class → GraphQL scalar mapping
# ---------------------------------------------------------------------------
# Import Django models lazily to avoid Django-not-setup errors at import time.


def _build_django_to_gql() -> dict:
    """Build the mapping from Django field classes to graphql-core scalar types.

    Deferred to function call to allow Django settings to be configured before
    Django model classes are imported.
    """
    from django.db import models

    return {
        # String-like
        models.CharField: GraphQLString,
        models.TextField: GraphQLString,
        models.EmailField: GraphQLString,
        models.SlugField: GraphQLString,
        models.URLField: GraphQLString,
        models.FileField: GraphQLString,
        models.FilePathField: GraphQLString,
        models.IPAddressField: GraphQLString,
        models.GenericIPAddressField: GraphQLString,
        # Numeric
        models.IntegerField: GraphQLInt,
        models.SmallIntegerField: GraphQLInt,
        models.BigIntegerField: GraphQLInt,
        models.PositiveIntegerField: GraphQLInt,
        models.PositiveSmallIntegerField: GraphQLInt,
        models.PositiveBigIntegerField: GraphQLInt,
        models.AutoField: GraphQLID,
        models.BigAutoField: GraphQLID,
        models.SmallAutoField: GraphQLID,
        models.FloatField: GraphQLFloat,
        # graphene-django collapses DecimalField AND DurationField to OUTPUT
        # ``Float`` (converter.py convert_field_to_float). Match that exactly for
        # SDL parity — the ``Decimal`` scalar is reserved for the input/filter
        # path. (See #1508.)
        models.DecimalField: GraphQLFloat,
        models.DurationField: GraphQLFloat,
        # Boolean
        models.BooleanField: GraphQLBoolean,
        # Date/Time
        models.DateField: GdxDate,
        models.DateTimeField: GdxDateTime,
        models.TimeField: GdxTime,
        # Special
        models.UUIDField: GdxUUID,
        models.BinaryField: GraphQLString,
        models.JSONField: GdxJSONString,
    }


# Module-level cache, populated on first use
_DJANGO_TO_GQL: dict | None = None


def _get_django_to_gql() -> dict:
    """Return the Django→GraphQL scalar mapping (lazy-built once)."""
    global _DJANGO_TO_GQL
    if _DJANGO_TO_GQL is None:
        _DJANGO_TO_GQL = _build_django_to_gql()
    return _DJANGO_TO_GQL


# ---------------------------------------------------------------------------
# Relation field detection
# ---------------------------------------------------------------------------


def _is_relation_field(field: Any) -> bool:
    """Return True if ``field`` is a Django relation (FK, M2M, O2O, etc.).

    Primary check: ``isinstance`` against Django's RelatedField / ForeignObjectRel.
    Fallback: ``field.is_relation`` attribute (covers exotic custom field types
    that subclass neither but still declare the standard ``is_relation`` sentinel).
    """
    from django.db.models.fields.related import ForeignObjectRel, RelatedField
    if isinstance(field, (RelatedField, ForeignObjectRel)):
        return True
    # Fallback: check for the is_relation attribute (all relation fields have it)
    return bool(getattr(field, "is_relation", False))


def _get_related_model(field: Any) -> type | None:
    """Return the related model class for a relation field, or None."""
    # FK, O2O: field.related_model
    related = getattr(field, "related_model", None)
    if related is not None:
        return related
    # Reverse relations: field.field.model
    rel_field = getattr(field, "field", None)
    if rel_field is not None:
        return getattr(rel_field, "model", None)
    return None


def _is_many_relation(field: Any) -> bool:
    """Return True if this is a to-many relation (M2M, reverse FK, etc.).

    IMPORTANT: ``OneToOneRel`` (the reverse side of a forward ``OneToOneField``)
    is a SUBCLASS of ``ManyToOneRel`` (``issubclass(OneToOneRel, ManyToOneRel)``
    is True), so a naive ``isinstance(field, ManyToOneRel)`` check would
    misclassify a reverse O2O as to-many and render it as a ``<Model>ListType``
    container. graphene-django renders a reverse O2O as a SINGLE nullable Field
    (``converter.convert_onetoone_field_to_djangomodel``, registered on
    ``models.OneToOneRel``), NOT a list container. We must therefore EXCLUDE
    ``OneToOneRel`` BEFORE the ``ManyToOneRel`` check so reverse O2O flows
    through the to-ONE relation arm of ``_to_graphql_field``.
    """
    from django.db.models import (
        ManyToManyField,
        ManyToManyRel,
        ManyToOneRel,
        OneToOneRel,
    )
    if isinstance(field, OneToOneRel):
        return False
    return isinstance(field, (ManyToManyField, ManyToManyRel, ManyToOneRel))


# ---------------------------------------------------------------------------
# Single field compiler
# ---------------------------------------------------------------------------


def _to_graphql_field(
    field: Any,
    registry: Any,
) -> dict[str, GraphQLField]:
    """Map a single Django model field to a ``{camelCase_key: GraphQLField}`` dict.

    Returns a single-entry dict (keyed by camelCase field name) or an empty dict
    if the field cannot be mapped (unknown type, generic FK, etc.).

    Args:
        field: A Django model field instance.
        registry: An object with ``get_compiled(model_cls)`` → GraphQLObjectType.

    Returns:
        A dict ``{camel_name: GraphQLField}`` (one entry) or ``{}`` if skipped.
    """
    field_name: str = field.name if hasattr(field, "name") else field.attname
    camel_name: str = _to_camel_case(field_name)

    # --- Relation fields ------------------------------------------------------
    if _is_relation_field(field):
        related_cls = _get_related_model(field)
        if related_cls is None:
            return {}

        # To-MANY relations (M2M / reverse FK / reverse M2M) are NOT compiled
        # here. graphene-django renders a to-many relation as the related model's
        # auto-derived ``<Model>ListType`` results/totalCount CONTAINER (NOT a
        # plain ``[Node]`` list) — see converter.convert_field_to_list_or_connection
        # / convert_many_rel_to_djangomodel -> _nested_list_object_field. That
        # container needs the graphene ``Registry`` (get_or_create_list_object_type),
        # which is not available to this compiler (it only has get_compiled). The
        # to-many container fields are therefore injected by
        # ``types._compile_relation_list_fields`` inside the output thunk, which
        # reuses the SAME native list-container builder the root compiler uses.
        # Returning ``{}`` here avoids emitting a divergent ``[Node]`` field.
        if _is_many_relation(field):
            return {}

        # To-ONE relation (FK / O2O): a zero-arg lambda thunk resolved via the
        # registry. graphene-django renders the OUTPUT FK field ALWAYS NULLABLE —
        # ``Field(_type, required=is_required(field) and input_flag == 'create')``
        # with ``input_flag is None`` for output makes ``required`` always False
        # (converter.convert_field_to_djangomodel). Native MUST match: do NOT
        # wrap the FK output in ``GraphQLNonNull``, even when the DB column is
        # NOT NULL. (This mirrors the model-scalar #1494 OUTPUT nullability rule;
        # input/filter FK nullability is owned by the input/filter path.)
        def _make_relation_type(
            _cls: type = related_cls,
        ) -> Any:
            compiled = registry.get_compiled(_cls)
            if compiled is None:
                return GraphQLString  # fallback for unregistered relations
            return compiled

        resolved_type = _make_relation_type()

        def _default_resolver(
            root: Any,
            _info: Any,
            *,
            _name: str = field_name,
        ) -> Any:
            if isinstance(root, dict):
                return root.get(_name)
            return getattr(root, _name, None)

        gql_field = GraphQLField(
            type_=resolved_type,
            resolve=_default_resolver,
        )
        return {camel_name: gql_field}

    # --- Scalar fields: map via DJANGO_TO_GQL --------------------------------
    django_to_gql = _get_django_to_gql()
    gql_scalar = None

    # Walk the MRO to find the most specific mapping
    for klass in type(field).__mro__:
        if klass in django_to_gql:
            gql_scalar = django_to_gql[klass]
            break

    if gql_scalar is None:
        # Unknown field type — skip gracefully
        return {}

    # Nullability (#1494 parity): graphene-django renders OUTPUT model-scalar
    # fields as ALWAYS NULLABLE (converter passes
    # ``required=is_required(field) and input_flag == 'create'`` — output's
    # input_flag is None, so required is always False). Native MUST match: do
    # NOT reflect the DB NOT NULL constraint on output. The ONLY non-null
    # OUTPUT scalar is the primary key, which graphene renders ``id: ID!``.
    # NOTE: this is OUTPUT-only; INPUT / filter-input nullability is owned by
    # the input compiler / filtering builder and is unchanged.
    is_pk = getattr(field, "primary_key", False)

    if is_pk:
        gql_type: Any = GraphQLNonNull(gql_scalar)
    else:
        gql_type = gql_scalar

    def _default_resolver(
        root: Any,
        _info: Any,
        *,
        _name: str = field_name,
    ) -> Any:
        if isinstance(root, dict):
            return root.get(_name)
        return getattr(root, _name, None)

    gql_field = GraphQLField(
        type_=gql_type,
        resolve=_default_resolver,
    )
    return {camel_name: gql_field}


# ---------------------------------------------------------------------------
# Full model field compiler
# ---------------------------------------------------------------------------


def compile_output_fields(
    model: type,
    registry: Any,
    *,
    only_fields: list[str] | tuple[str, ...] | None = None,
    exclude_fields: list[str] | tuple[str, ...] | None = None,
) -> dict[str, GraphQLField]:
    """Compile all output fields for a Django model.

    Iterates model ``_meta.get_fields()`` (non-private, concrete and relation
    fields) and calls ``_to_graphql_field`` for each. The result is a flat
    ``{camelCase_name: GraphQLField}`` dict suitable for ``GraphQLObjectType``.

    Args:
        model: Django model class.
        registry: Object with ``get_compiled(model_cls)`` method.
        only_fields: If provided, only include fields in this list.
        exclude_fields: If provided, exclude fields in this list.

    Returns:
        Dict of ``{camelCase_name: GraphQLField}``.
    """
    fields: dict[str, GraphQLField] = {}

    # get_fields() returns concrete + relation fields
    # include_parents=False avoids duplicating parent-model fields
    try:
        all_fields = model._meta.get_fields(include_parents=False)
    except Exception:
        all_fields = model._meta.concrete_fields

    for field in all_fields:
        # Skip reverse relations (they are auto-created by Django for O2O/FK targets)
        # unless explicitly in only_fields
        field_name = getattr(field, "name", getattr(field, "attname", None))
        if field_name is None:
            continue

        # Apply only_fields filter
        if only_fields is not None and field_name not in only_fields:
            continue

        # Apply exclude_fields filter
        if exclude_fields is not None and field_name in exclude_fields:
            continue

        # Skip auto-created reverse relations unless explicitly requested
        if getattr(field, "auto_created", False) and not getattr(field, "concrete", True):
            if only_fields is None or field_name not in (only_fields or []):
                continue

        field_map = _to_graphql_field(field, registry)
        fields.update(field_map)

    return fields
