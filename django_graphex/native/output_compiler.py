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
    GraphQLList,
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
    """Return True if this is a to-many relation (M2M, reverse FK, GenericRelation).

    IMPORTANT: ``OneToOneRel`` (the reverse side of a forward ``OneToOneField``)
    is a SUBCLASS of ``ManyToOneRel`` (``issubclass(OneToOneRel, ManyToOneRel)``
    is True), so a naive ``isinstance(field, ManyToOneRel)`` check would
    misclassify a reverse O2O as to-many and render it as a ``<Model>ListType``
    container. graphene-django renders a reverse O2O as a SINGLE nullable Field
    (``converter.convert_onetoone_field_to_djangomodel``, registered on
    ``models.OneToOneRel``), NOT a list container. We must therefore EXCLUDE
    ``OneToOneRel`` BEFORE the ``ManyToOneRel`` check so reverse O2O flows
    through the to-ONE relation arm of ``_to_graphql_field``.

    DEFECT B: a ``GenericRelation`` (django.contrib.contenttypes) is a to-MANY
    relation rendered by graphene as the related model's ``<Model>ListType``
    results/totalCount container (``converter.convert_generic_relation_to_object_list``
    -> ``_nested_list_object_field``). It does NOT subclass any of the rel classes
    below (it is a forward ``ForeignObject`` descriptor), so it must be matched
    explicitly — otherwise it falls through to the to-ONE arm and renders as a
    SINGLE object instead of the list container.
    """
    from django.contrib.contenttypes.fields import GenericRelation
    from django.db.models import (
        ManyToManyField,
        ManyToManyRel,
        ManyToOneRel,
        OneToOneRel,
    )
    if isinstance(field, OneToOneRel):
        return False
    if isinstance(field, GenericRelation):
        return True
    return isinstance(field, (ManyToManyField, ManyToManyRel, ManyToOneRel))


# ---------------------------------------------------------------------------
# GenericForeignKey output (DEFECT B — basic GFK -> flat object)
# ---------------------------------------------------------------------------
# graphene-django renders a model's GenericForeignKey OUTPUT field as a flat
# ``GenericForeignKeyType`` (base_types.GenericForeignKeyType) with three fields:
# ``app_label: String``, ``id: ID``, ``model_name: String``. Its default_resolver
# reads ``instance._meta.app_label`` / ``instance.id`` / ``instance._meta.model.__name__``
# from the RESOLVED content object. The native flat type below mirrors that shape
# and resolver semantics byte-for-byte (camelCase keys ``appLabel``/``id``/``modelName``).
#
# NOTE (#8 / Track 2, OUT OF SCOPE here): when the owning type declares
# ``Meta.gfk_unions`` for this GFK, graphene emits a typed GraphQLUnion instead of
# the flat type. That union output path is a SEPARATE, larger defect and is NOT
# implemented here — this only handles the basic GFK -> flat object case.


def _is_generic_foreign_key(field: Any) -> bool:
    """Return True if ``field`` is a django.contrib.contenttypes GenericForeignKey."""
    from django.contrib.contenttypes.fields import GenericForeignKey

    return isinstance(field, GenericForeignKey)


# Module-level cache for the single shared flat GFK GraphQLObjectType.
_GFK_FLAT_TYPE: Any = None


def _gfk_flat_resolver(attr_name: str):
    """Build a resolver reading ``attr_name`` from the resolved content object.

    Mirrors ``base_types.resolver`` used by graphene's ``GenericForeignKeyType``:
    ``app_label`` -> ``instance._meta.app_label``, ``id`` -> ``instance.id``,
    ``model_name`` -> ``instance._meta.model.__name__``. A null content object
    (unresolved / unregistered target) yields ``None`` for every sub-field.
    """

    def _resolve(root: Any, _info: Any) -> Any:
        if root is None:
            return None
        if attr_name == "app_label":
            return root._meta.app_label
        if attr_name == "id":
            return root.id
        if attr_name == "model_name":
            return root._meta.model.__name__
        return None  # pragma: no cover - defensive

    return _resolve


def _get_gfk_flat_type() -> Any:
    """Return the shared flat ``GenericForeignKeyType`` GraphQLObjectType (lazy).

    SDL parity: name ``GenericForeignKeyType``, fields ``appLabel: String``,
    ``id: ID``, ``modelName: String`` — matching graphene's
    ``base_types.GenericForeignKeyType``.
    """
    global _GFK_FLAT_TYPE
    if _GFK_FLAT_TYPE is None:
        from graphql import GraphQLObjectType

        _GFK_FLAT_TYPE = GraphQLObjectType(
            name="GenericForeignKeyType",
            description=(
                " Auto generated Type for a model's GenericForeignKey field "
            ),
            fields={
                "appLabel": GraphQLField(
                    GraphQLString, resolve=_gfk_flat_resolver("app_label")
                ),
                "id": GraphQLField(
                    GraphQLID, resolve=_gfk_flat_resolver("id")
                ),
                "modelName": GraphQLField(
                    GraphQLString, resolve=_gfk_flat_resolver("model_name")
                ),
            },
        )
    return _GFK_FLAT_TYPE


def _compile_generic_foreign_key(field: Any) -> dict[str, GraphQLField]:
    """Compile a GenericForeignKey output field -> flat ``GenericForeignKeyType``.

    The field resolver reads the GFK accessor (e.g. ``note.content_object``) from
    the parent row; a null / unregistered-target content object renders as null
    (the field and all its sub-fields are nullable, matching graphene).
    """
    field_name: str = field.name
    camel_name: str = _to_camel_case(field_name)

    def _gfk_resolver(root: Any, _info: Any, *, _name: str = field_name) -> Any:
        if isinstance(root, dict):
            return root.get(_name)
        return getattr(root, _name, None)

    return {
        camel_name: GraphQLField(
            type_=_get_gfk_flat_type(),
            resolve=_gfk_resolver,
        )
    }


# ---------------------------------------------------------------------------
# Choices fields -> GraphQLEnumType (S-enum-1)
# ---------------------------------------------------------------------------


def _is_multiselect_field(field: Any) -> bool:
    """Return True for a django-multiselectfield ``MultiSelectField``.

    Detected via ``isinstance`` when the optional package is installed (covers
    subclasses); falls back to a class-name check when the import fails, so the
    compiler works without the optional dependency. Mirrors the converter's
    detection (``converter.convert_django_field_with_choices``).
    """
    try:
        from multiselectfield import MultiSelectField as _MSField  # noqa: PLC0415

        return isinstance(field, _MSField)  # pragma: no cover
    except ImportError:
        return type(field).__name__ == "MultiSelectField"


def _compile_choices_enum_field(
    field: Any,
    graphene_registry: Any,
) -> GraphQLField | None:
    """Compile a choices field to a ``GraphQLField`` wrapping a ``GraphQLEnumType``.

    Builds (or fetches the shared) enum via the graphene-free canonical builder
    ``converter.build_choices_enum_type``, which memoizes the enum in the
    ``graphene_registry`` slot the native filter-input path also reads — so
    OUTPUT and FILTER-INPUT share ONE enum instance per ``(model, field)``.

    A ``MultiSelectField`` renders ``GraphQLList(enum)`` (mirroring the
    converter's ``DjangoListField(enum)`` branch); a plain choices field renders
    the enum directly. OUTPUT scalars are always nullable (graphene #1494
    parity), so the enum is NOT wrapped in ``GraphQLNonNull``.

    Returns ``None`` when the field has no usable choices (caller falls through
    to the scalar mapping).
    """
    from django_graphex.converter import build_choices_enum_type  # noqa: PLC0415

    field_name: str = field.name if hasattr(field, "name") else field.attname

    enum_type = build_choices_enum_type(field, graphene_registry)
    if enum_type is None:
        return None

    gql_type: Any = GraphQLList(enum_type) if _is_multiselect_field(field) else enum_type

    def _default_resolver(root: Any, _info: Any, *, _name: str = field_name) -> Any:
        if isinstance(root, dict):
            return root.get(_name)
        return getattr(root, _name, None)

    return GraphQLField(type_=gql_type, resolve=_default_resolver)


# ---------------------------------------------------------------------------
# Single field compiler
# ---------------------------------------------------------------------------


def _to_graphql_field(
    field: Any,
    registry: Any,
    graphene_registry: Any = None,
) -> dict[str, GraphQLField]:
    """Map a single Django model field to a ``{camelCase_key: GraphQLField}`` dict.

    Returns a single-entry dict (keyed by camelCase field name) or an empty dict
    if the field cannot be mapped (unknown type, generic FK, etc.).

    Args:
        field: A Django model field instance.
        registry: An object with ``get_compiled(model_cls)`` → GraphQLObjectType.
        graphene_registry: The graphene ``Registry`` whose enum slot is SHARED
            with the native filter-input path (``register_enum`` /
            ``get_type_for_enum``). A choices field compiles to the SAME
            ``GraphQLEnumType`` instance both paths resolve. May be ``None`` for
            callers that never reach a choices field (the enum branch falls back
            to the scalar mapping when no shared registry is available).

    Returns:
        A dict ``{camel_name: GraphQLField}`` (one entry) or ``{}`` if skipped.
    """
    field_name: str = field.name if hasattr(field, "name") else field.attname
    camel_name: str = _to_camel_case(field_name)

    # --- Choices fields -> GraphQLEnumType (S-enum-1) -------------------------
    # A field with ``.choices`` renders as a real ``GraphQLEnumType`` (graphene
    # parity), NOT a scalar. The enum is built by the GRAPHENE-FREE canonical
    # builder ``converter.build_choices_enum_type`` and memoized in the SHARED
    # graphene ``Registry`` slot, so the native filter-input path
    # (``filtering.native_schema._choices_enum``) resolves the SAME instance for
    # one ``(model, field)``. A ``MultiSelectField`` (django-multiselectfield)
    # wraps the enum in ``GraphQLList`` to mirror the converter's
    # ``DjangoListField(enum)`` branch.
    if graphene_registry is not None and getattr(field, "choices", None):
        enum_field = _compile_choices_enum_field(field, graphene_registry)
        if enum_field is not None:
            return {camel_name: enum_field}

    # --- GenericForeignKey (DEFECT B) -----------------------------------------
    # A GFK has ``is_relation == True`` but NO fixed ``related_model`` (it is
    # polymorphic), so it would otherwise fall through ``_is_relation_field`` ->
    # ``_get_related_model() is None`` -> ``{}`` (silently dropped). Render it as
    # the flat ``GenericForeignKeyType`` BEFORE the relation arm. (The
    # gfk_unions -> GraphQLUnion variant is #8 / Track 2, out of scope.)
    if _is_generic_foreign_key(field):
        return _compile_generic_foreign_key(field)

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
    include_fields: list[str] | tuple[str, ...] | None = None,
    graphene_registry: Any = None,
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
        include_fields: If provided, FORCE-include these fields even when they
            would be skipped by ``only_fields`` / ``exclude_fields`` (issue #65).
            ``include_fields`` does NOT restrict the output (use ``only_fields``
            for that); it overrides the skip filters for the named fields,
            mirroring ``converter.construct_fields`` on the graphene path.
        graphene_registry: The graphene ``Registry`` whose enum slot is SHARED
            with the native filter-input path. Threaded into ``_to_graphql_field``
            so a choices field compiles to the SAME ``GraphQLEnumType`` instance
            both paths resolve (S-enum-1). When ``None``, choices fields fall
            back to the scalar mapping.

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

        # ``include_fields`` force-includes a field even when only/exclude would
        # skip it (issue #65). Mirrors ``converter.construct_fields`` on the
        # graphene path: a force-included field bypasses BOTH skip filters.
        _force_included = include_fields is not None and field_name in include_fields

        # Apply only_fields filter
        if (
            not _force_included
            and only_fields is not None
            and field_name not in only_fields
        ):
            continue

        # Apply exclude_fields filter
        if (
            not _force_included
            and exclude_fields is not None
            and field_name in exclude_fields
        ):
            continue

        # Skip auto-created reverse relations unless explicitly requested.
        #
        # NOTE on reverse O2O (#1581): a reverse ``OneToOneField`` is an
        # auto-created ``OneToOneRel`` (to-ONE) that is ALSO skipped here. Unlike
        # to-MANY reverse relations (reverse FK / reverse M2M) — which are
        # re-injected as ``<Model>ListType`` containers by
        # ``types._compile_relation_list_fields`` — a reverse O2O has no
        # compensating injection in THIS compiler, because rendering it
        # graphene-faithfully requires the PER-TYPE registry (graphene drops the
        # field when the target model is not registered in that registry, see
        # ``converter.convert_onetoone_field_to_djangomodel``). This compiler only
        # sees the SHARED output registry, so reverse-O2O injection is delegated
        # to ``types._compile_reverse_o2o_fields`` inside the output thunk, which
        # has the per-type registry and mirrors graphene exactly.
        if getattr(field, "auto_created", False) and not getattr(field, "concrete", True):
            if only_fields is None or field_name not in (only_fields or []):
                continue

        field_map = _to_graphql_field(field, registry, graphene_registry)
        fields.update(field_map)

    return fields
