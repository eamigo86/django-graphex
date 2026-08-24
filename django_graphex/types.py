"""GraphQL type definitions for Django models."""

from __future__ import annotations

import warnings
from collections import OrderedDict
from typing import TYPE_CHECKING, Any, ClassVar, Optional, Sequence

from django.core.exceptions import ImproperlyConfigured
from django.db.models import Manager, QuerySet
from django.utils.functional import SimpleLazyObject
from graphql import GraphQLBoolean, GraphQLError

from .backends import resolve_backend
from .base_types import DjangoListObjectBase, factory_type
from .converter import construct_fields
from .core.base import InputType as NativeInputType
from .core.base import NativeObjectTypeOptions, _props
from .core.base import ObjectType as NativeObjectType
from .core.descriptors import NativeField, NativeList, NativeMountedField
from .core.descriptors import field as native_field
from .core.validators import build_validator_model
from .errors import ErrorType
from .fields import DjangoListObjectField, DjangoObjectField
from .filtering.filter_field import (
    RESERVED_FILTER_ARGS,
    collect_custom_filters,
)
from .nested import NestedFieldsMixin, hosts_serving, register_nested_host
from .paginations.pagination import BaseDjangoGraphqlPagination
from .permissions import supported_kwargs
from .registry import Registry, get_global_registry
from .settings import graphql_api_settings
from .utils import (
    _apply_optimizations,
    apply_object_type_get_queryset,
    get_Object_or_None,
    is_valid_django_model,
    maybe_queryset,
    not_found_error,
    queryset_factory,
)

if TYPE_CHECKING:
    from django.db.models import Model
    from graphql import GraphQLResolveInfo as ResolveInfo

__all__ = (
    "DjangoObjectType",
    "DjangoInputObjectType",
    "DjangoListObjectType",
    "DjangoModelType",
    "DjangoUnionType",
    "DjangoInterfaceType",
)

#: Every operation a "DjangoModelType" generates, and its "Meta.model_operations"
#: default. A "DjangoModelMutation" generates the three write verbs only; this
#: type bundles the query fields as well, so its option covers all five.
MODEL_TYPE_OPERATIONS = ("create", "update", "delete", "list", "retrieve")


def _yank_fields(attrs: dict[str, Any], _as: Any, sort: bool = True) -> dict[str, Any]:
    """Graphene-free re-implementation of ``graphene.utils.yank_fields_from_attrs``.

    Walks an attribute mapping (the ``construct_fields`` output or a class
    ``__dict__``), keeping only the values that are NATIVE field-shaped
    descriptors (``NativeMountedField`` / ``NativeField``) and dropping everything
    else (plain attributes, dunders, etc.). Results are sorted by the descriptor's
    ``creation_counter`` (declaration order) so SDL field ordering is preserved.

    S-input-5 (Part B retirement): the legacy graphene-descriptor branch — which
    lazily imported ``graphene`` ``MountedType`` / ``UnmountedType`` and mounted a
    raw graphene ``UnmountedType`` (a relation ``Dynamic``) via
    ``_as.mounted(value)`` — is GONE. After S-rel-2/3/4 + S-enum-2 (OUTPUT) and
    S-input-5 (INPUT + choices), the converter emits graphene-free markers
    (``NativeRelationField`` / ``_DEAD_SCALAR``) on EVERY native path, so NO
    graphene descriptor ever reaches here (proven: a comprehensive OUTPUT + INPUT
    create/update/delete + choices build reaches ``_yank_fields`` with zero
    graphene-module values). The ``_as`` mount parameter is retained for call-site
    compatibility but is now unused.

    Args:
        attrs: A ``{name: value}`` mapping to extract field descriptors from.
        _as: Retained for call-site compatibility (unused since Part B retirement).
        sort: Whether to order results by ``creation_counter``.

    Returns:
        An ordered ``{name: field}`` dict of the native field-shaped descriptors.
    """
    fields_with_names: list[tuple[str, Any]] = []
    for attname, value in list(attrs.items()):
        # A native ``NativeMountedField`` (the re-parented ``Django*Field``
        # classes, e.g. ``DjangoNestedListObjectField`` / ``DjangoListField`` /
        # ``NativeRelationField``) or a native ``field()`` (``NativeField``) is a
        # field-shaped descriptor (carries ``.type`` / ``.args`` /
        # ``creation_counter``); keep it AS-IS. Anything else is a plain attribute
        # and is skipped. This is the silent-drop guard: a relation/choices marker
        # must be a recognized native descriptor or it would vanish from
        # ``_meta.fields`` (the test_issue52 self-ref-O2O canary).
        if isinstance(value, (NativeMountedField, NativeField)):
            fields_with_names.append((attname, value))

    if sort:
        # Order by graphene ``creation_counter`` (declaration order, SDL parity).
        # A ``NativeMountedField`` and a graphene mounted field both expose it; a
        # native ``NativeField`` (the ``field()`` currency) does NOT carry one, so
        # fall back to +inf — declared scalar ``field()`` fields keep a stable
        # relative order AFTER the counter-bearing descriptors (their absolute SDL
        # position is then alphabetized by the output compiler).
        fields_with_names = sorted(
            fields_with_names,
            key=lambda f: getattr(f[1], "creation_counter", float("inf")),
        )
    return dict(fields_with_names)


# Options that graphene's base classes or the factory_type helper pass through
# in **options; these are legitimately forwarded to super() and must not be
# flagged as unknown.
_GRAPHENE_BASE_OPTIONS: frozenset[str] = frozenset(
    {
        # graphene ObjectType / InputObjectType base class options
        "_meta",
        "interfaces",
        "possible_types",
        "default_resolver",
        "container",
        # graphene SubclassWithMeta options consumed by the metaclass
        "name",
        "description",
    }
)


def _compile_declared_list_fields(
    src_cls: type, registries: Any = None
) -> dict[str, Any]:
    """Compile DECLARED list/nested-list fields on a ``DjangoObjectType`` (WU6b).

    The native output compiler (``compile_output_fields``) only derives fields
    from ``model._meta.get_fields()``. A declared list field — e.g.
    ``posts = DjangoNestedListObjectField(PostList, accessor="posts")`` — is a
    graphene class attribute that never enters the model meta, so it would be
    silently dropped from the native ``GraphQLObjectType``.

    This recovers those declared fields from the source class's graphene
    ``_meta.fields`` and compiles each into a native list-container
    ``GraphQLField`` via the SAME builder the root compiler uses
    (``schema_compiler._build_list_object_field``). That builder wires the
    pagination args + slicing resolver onto the container's results field, so a
    nested paginated list is reachable AND its page is DB-side window-sliced by
    the optimizer (the WU6b seam).

    Only list-shaped fields are injected; plain relation/scalar fields are
    already handled by ``compile_output_fields`` and must NOT be duplicated here.

    Args:
        src_cls: The source ``DjangoObjectType`` subclass.

    Returns:
        A ``{camelCase_name: GraphQLField}`` dict of declared list fields
        (empty when the class declares none).
    """
    from ._strconv import to_camel_case
    from .core.schema_compiler import _build_list_object_field
    from .fields import DjangoListObjectField

    meta_fields = getattr(getattr(src_cls, "_meta", None), "fields", None) or {}
    out: dict[str, Any] = {}
    for field_name, field in meta_fields.items():
        # DjangoNestedListObjectField is a subclass of DjangoListObjectField, so
        # this single isinstance covers both the nested and the flat list field.
        if isinstance(field, DjangoListObjectField):
            out[to_camel_case(field_name)] = _build_list_object_field(field, registries)
    return out


def _model_derived_fields(model: type) -> list[Any]:
    """Return every field Django derives for "model", PARENTS INCLUDED.

    The single choke point every native compiler in this module goes through to
    enumerate a model's fields. It deliberately uses the DEFAULT
    "include_parents=True": passing "include_parents=False" is a no-op for an
    ABSTRACT base (Django copies those columns onto the child) but silently
    drops everything a MULTI-TABLE-INHERITANCE child inherits -- its "id", the
    parent's own columns, and the parent's reverse relations -- which left MTI
    child types carrying nothing but their own table's columns.

    The parent link itself is NOT filtered out here; each caller already
    discriminates on the field kind it cares about.

    Args:
        model: The Django model to enumerate.

    Returns:
        The derived fields, or the concrete fields when "_meta.get_fields" is
        unavailable.
    """
    try:
        return list(model._meta.get_fields())
    except Exception:  # pragma: no cover — defensive
        return list(model._meta.concrete_fields)


def _model_field_names(model: type) -> set[str]:
    """Return the set of names Django derives for *model* (Slice D/E helper).

    Includes concrete + relation fields AND reverse-relation accessor names, so a
    DECLARED graphene field can be told apart from a model-derived one. Used to
    avoid double-emitting model fields (already handled by the output compiler /
    relation-list injection) when scanning ``_meta.fields`` for declared fields.
    """
    names: set[str] = set()
    for f in _model_derived_fields(model):
        name = getattr(f, "name", None) or getattr(f, "attname", None)
        if name:
            names.add(name)
        # Reverse relations expose their parent accessor via get_accessor_name().
        get_accessor = getattr(f, "get_accessor_name", None)
        if callable(get_accessor):
            try:
                names.add(get_accessor())
            except Exception:  # pragma: no cover — defensive
                pass  # nosec B110 — accessor probing is best-effort
    return names


def _is_declared_class_attr(src_cls: type, field_name: str) -> bool:
    """Return True when *field_name* is a user-DECLARED class attribute (Slice D).

    A field can land in ``_meta.fields`` two ways: (a) AUTO-DERIVED from
    ``model._meta`` by ``construct_fields`` (no corresponding entry in any class
    ``__dict__``), or (b) EXPLICITLY DECLARED by the user as a class attribute
    (e.g. ``posts = field(NativeList(PostType))``), which DOES appear in the
    declaring class's ``__dict__``.

    The DEFECT C override rule needs to tell these apart: a declared override of
    a model-relation name must WIN over the auto-derived container, while a
    purely model-derived field must NOT be re-emitted here (it is owned by
    ``compile_output_fields`` / the relation-list injection). Scanning the full
    MRO ``__dict__`` chain is the reliable discriminator — graphene's
    ``yank_fields_from_attrs`` merges declared attrs INTO ``_meta.fields`` so the
    field type alone cannot distinguish the two.
    """
    return any(field_name in base.__dict__ for base in src_cls.__mro__)


def _compile_declared_fields(src_cls: type, registries: Any = None) -> dict[str, Any]:
    """Compile DECLARED non-model, non-list fields on a ``DjangoObjectType`` (Slice D).

    ``compile_output_fields`` only derives fields from ``model._meta.get_fields()``;
    the WU6b ``_compile_declared_list_fields`` recovers declared LIST fields. Still
    dropped under native: declared NON-model scalar / object fields — e.g.
    ``extra = graphene.String()``, ``computed = graphene.Int()``,
    ``profile = graphene.Field(SomePlainType)``, or a custom-resolver field. graphene
    captures these via ``_meta.fields`` and renders them on the output type; native
    must MATCH (same name + type + nullability + resolver).

    This scans the class's graphene ``_meta.fields`` and compiles each field that
    is (a) NOT a Django list field (already handled by
    ``_compile_declared_list_fields``) and (b) NOT a model-derived field name
    (already handled by ``compile_output_fields`` / the relation-list injection).
    Each surviving declared field is converted via the SAME per-field graphene->
    native converter the plain-ObjectType compiler uses, so resolver wiring and
    type dispatch are byte-identical to graphene.

    Args:
        src_cls: The source ``DjangoObjectType`` subclass.

    Returns:
        A ``{camelCase_name: GraphQLField}`` dict of declared non-model fields
        (empty when the class declares none).
    """
    from ._strconv import to_camel_case
    from .core.schema_compiler import _build_filter_list_field, compile_declared_field
    from .fields import (
        DjangoFilterListField,
        DjangoFilterPaginateListField,
        DjangoListObjectField,
    )

    meta = getattr(src_cls, "_meta", None)
    meta_fields = getattr(meta, "fields", None) or {}
    model = getattr(meta, "model", None)
    model_names = _model_field_names(model) if model is not None else set()

    out: dict[str, Any] = {}
    for field_name, field in meta_fields.items():
        # Skip declared LIST fields — owned by _compile_declared_list_fields.
        if isinstance(field, DjangoListObjectField):
            continue
        # DEFECT #7: a declared NESTED filtered/paginated list field on a
        # DjangoObjectType (``posts = DjangoFilterListField(PostType)`` /
        # ``paginated_posts = DjangoFilterPaginateListField(...)``) is NOT a
        # ``DjangoListObjectField`` subclass, so it falls through to the generic
        # ``compile_declared_field`` below — which renders the wrong return type
        # AND drops the ``filter`` / pagination args (no nested filtering was
        # reachable under native). Route it to the SAME native builder the root
        # compiler uses (``schema_compiler._build_filter_list_field``) so the
        # nested field carries the DECLARED node type as ``[Node]`` / ``[Node!]``
        # and its filter + pagination args — byte-identical to the root path.
        if isinstance(field, (DjangoFilterListField, DjangoFilterPaginateListField)):
            out[to_camel_case(field_name)] = _build_filter_list_field(field, registries)
            continue
        # DEFECT C: a field whose name matches a model relation/field is usually
        # the AUTO-DERIVED graphene field (owned by compile_output_fields / the
        # to-many relation-list injection) and must be skipped here. BUT when the
        # user EXPLICITLY declares a class attribute of the SAME name (e.g.
        # ``posts = field(NativeList(PostType))`` to override the auto-derived
        # PostListType container), that declared override must WIN — graphene
        # allowed this; native silently dropped it. The discriminator: a genuine
        # class attribute is present on ``src_cls`` (or a base) in ``__dict__``,
        # whereas a purely model-derived field only exists in ``_meta.fields``.
        if field_name in model_names and not _is_declared_class_attr(
            src_cls, field_name
        ):
            continue
        out[to_camel_case(field_name)] = compile_declared_field(
            src_cls, field_name, field, registries
        )
    return out


def _compile_gfk_union_output_fields(
    src_cls: type, registries: Any = None
) -> dict[str, Any]:
    """Compile typed GFK-union OUTPUT fields declared via ``Meta.unions`` (#8).

    ``compile_output_fields`` renders a model's ``GenericForeignKey`` as the flat
    ``GenericForeignKeyType`` (DEFECT-B basic path). When the owning type declares
    ``Meta.unions = {"<gfk_name>": SomeDjangoUnionType}`` (Track 2), graphene
    instead emitted a typed ``GraphQLUnion`` for that GFK
    (``converter.convert_generic_foreign_key_to_object``). Native must MATCH:
    override the flat field with a field whose type is the compiled
    ``GraphQLUnionType`` and whose resolver reads the GFK accessor off the parent.

    Added in the output thunk AFTER ``compile_output_fields`` so the union field
    REPLACES the flat ``GenericForeignKeyType`` field (last-wins). A declared union
    that is NOT registered (mis-ordered declaration) is skipped here, leaving the
    flat field — byte-identical to graphene's warn-and-fall-back semantics (the
    warning itself fires on the converter path).

    Args:
        src_cls: The source ``DjangoObjectType`` subclass.

    Returns:
        A ``{camelCase_name: GraphQLField}`` dict of typed GFK-union fields
        (empty when the class declares no ``unions``).
    """
    from django.contrib.contenttypes.fields import GenericForeignKey
    from graphql import GraphQLField

    from ._strconv import to_camel_case

    meta = getattr(src_cls, "_meta", None)
    unions = getattr(meta, "unions", None) or {}
    model = getattr(meta, "model", None)
    registry = getattr(meta, "registry", None)
    if not unions or model is None or registry is None:
        return {}

    from .core.polymorphic_compiler import compile_union_type

    gfk_names = {
        f.name for f in model._meta.get_fields() if isinstance(f, GenericForeignKey)
    }

    out: dict[str, Any] = {}
    for fk_name in unions:
        if fk_name not in gfk_names:
            continue
        # Only emit when the companion union is actually registered (mirrors
        # converter/registry.get_gfk_union: a mis-ordered, unregistered union
        # leaves the flat GenericForeignKeyType in place + warns on the converter).
        union_cls = registry.get_gfk_union(model, fk_name)
        if union_cls is None:
            continue
        # item-b (B5): thread the pair so the union members resolve to THIS
        # schema's forked instances (default pair -> class-def -> byte-identical).
        gql_union = compile_union_type(union_cls, registries)

        def _gfk_resolver(root: Any, _info: Any, *, _name: str = fk_name) -> Any:
            if isinstance(root, dict):
                return root.get(_name)
            return getattr(root, _name, None)

        out[to_camel_case(fk_name)] = GraphQLField(
            gql_union,
            resolve=_gfk_resolver,
            description="Typed union for a GenericForeignKey field",
        )
    return out


def _compile_relation_list_fields(
    src_cls: type,
    model: type,
    registry: Any,
    *,
    only_fields: list[str] | None = None,
    exclude_fields: list[str] | None = None,
    registries: Any = None,
) -> dict[str, Any]:
    """Compile AUTO-DERIVED to-many relation fields as list containers (Slice E).

    graphene-django renders a model's to-many relations (``ManyToManyField`` /
    reverse FK ``ManyToOneRel`` / reverse M2M ``ManyToManyRel`` / ``GenericRel``)
    as the related model's auto-derived ``<Model>ListType`` results/totalCount
    CONTAINER — NOT a plain ``[Node]`` list (see
    ``converter.convert_field_to_list_or_connection`` /
    ``convert_many_rel_to_djangomodel`` -> ``_nested_list_object_field``). The
    native output compiler deliberately SKIPS to-many relations
    (``output_compiler._to_graphql_field``) because building the container needs
    the graphene ``Registry`` (``get_or_create_list_object_type``), which it does
    not have. This helper injects those container fields, reusing the EXACT same
    ``_nested_list_object_field`` -> ``DjangoNestedListObjectField`` ->
    ``_build_list_object_field`` path the graphene converter and the WU6b declared
    list-field injection use — so the native to-many SDL is byte-identical to
    graphene (container name, ``results``/``totalCount`` shape, pagination args).

    Honors ``only_fields`` / ``exclude_fields`` exactly as
    ``compile_output_fields`` does (filtering on the relation NAME, mirroring
    graphene's ``construct_fields`` projection) so projected types stay consistent.

    Args:
        src_cls: The source ``DjangoObjectType`` subclass.
        model: The Django model the type wraps.
        registry: The graphene ``Registry`` (needed to resolve / auto-create the
            related model's ``DjangoListObjectType`` container).
        only_fields: Restrict to these field names, or ``None`` for all.
        exclude_fields: Drop these field names.

    Returns:
        A ``{camelCase_name: GraphQLField}`` dict of to-many container fields
        (empty when the model has none / they are all projected out).
    """
    from ._strconv import to_camel_case
    from .converter import _nested_list_object_field
    from .core.output_compiler import _get_related_model, _is_many_relation
    from .core.schema_compiler import _build_list_object_field

    only_set = set(only_fields) if only_fields else None
    exclude_set = set(exclude_fields) if exclude_fields else None

    all_fields = _model_derived_fields(model)

    out: dict[str, Any] = {}
    for field in all_fields:
        if not _is_many_relation(field):
            continue
        related_cls = _get_related_model(field)
        if related_cls is None:
            continue
        # Resolve the parent accessor name (reverse relations use
        # get_accessor_name(); forward M2M uses field.name).
        get_accessor = getattr(field, "get_accessor_name", None)
        if callable(get_accessor):
            try:
                accessor = get_accessor()
            except Exception:  # pragma: no cover — defensive
                accessor = getattr(field, "name", None)
        else:
            accessor = getattr(field, "name", None)
        if accessor is None:
            continue
        # Projection: also gate on field.name (forward M2M projects by name;
        # reverse relations are typically named by their accessor).
        field_name = getattr(field, "name", accessor)
        if (
            only_set is not None
            and accessor not in only_set
            and field_name not in only_set
        ):
            continue
        if exclude_set is not None and (
            accessor in exclude_set or field_name in exclude_set
        ):
            continue

        nested = _nested_list_object_field(
            field, related_cls, registry, accessor=accessor
        )
        if nested is None:
            # Related node type not registered — graphene skips it too.
            continue
        # item-b (B5): thread the pair so the nested list container resolves to
        # THIS schema's FORKED container instance (default pair -> the class-def
        # container -> byte-identical).
        out[to_camel_case(accessor)] = _build_list_object_field(nested, registries)
    return out


def _compile_reverse_o2o_fields(
    src_cls: type,
    model: type,
    registry: Any,
    *,
    only_fields: list[str] | None = None,
    exclude_fields: list[str] | None = None,
    registries: Any = None,
) -> dict[str, Any]:
    """Compile AUTO-DERIVED reverse-OneToOne fields as single nullable objects (#1581).

    A reverse ``OneToOneField`` is an auto-created ``OneToOneRel`` (to-ONE). The
    native output compiler (``output_compiler.compile_output_fields``) skips ALL
    auto-created reverse relations. To-MANY reverse relations get re-injected as
    ``<Model>ListType`` containers by ``_compile_relation_list_fields``, but a
    reverse O2O is to-ONE and had NO compensating injection — so it was SILENTLY
    DROPPED on the native path (e.g. ``author { authorProfile { bio } }``).

    graphene-django renders a reverse O2O as a SINGLE nullable ``Field`` whose
    target type is resolved from the SAME per-type ``Registry`` and DROPPED when
    the target model is not registered there (see
    ``converter.convert_onetoone_field_to_djangomodel`` -> it returns ``None``
    when ``registry.get_type_for_model(model)`` is falsy). This helper mirrors
    that EXACTLY: it uses the per-type graphene ``registry`` (NOT the shared
    output registry) so the reverse-O2O field is only emitted when the target's
    type lives in this schema's registry — which prevents dragging an unrelated
    model's subgraph (and its ``<Model>ListType`` container) into the schema and
    causing a duplicate-type-name collision.

    Honors ``only_fields`` / ``exclude_fields`` on the reverse accessor name,
    matching ``compile_output_fields`` / ``construct_fields`` projection.

    Args:
        src_cls: The source ``DjangoObjectType`` subclass.
        model: The Django model the type wraps.
        registry: The per-type graphene ``Registry`` (``Meta.registry``).
        only_fields: Restrict to these field names, or ``None`` for all.
        exclude_fields: Drop these field names.

    Returns:
        A ``{camelCase_name: GraphQLField}`` dict of reverse-O2O object fields
        (empty when the model has none / they are all projected out / unregistered).
    """
    from django.core.exceptions import ObjectDoesNotExist
    from django.db.models import OneToOneRel
    from graphql import GraphQLField

    from ._strconv import to_camel_case

    only_set = set(only_fields) if only_fields else None
    exclude_set = set(exclude_fields) if exclude_fields else None

    all_fields = _model_derived_fields(model)

    out: dict[str, Any] = {}
    for field in all_fields:
        # Only AUTO-CREATED reverse OneToOneRel (the reverse side of a forward
        # OneToOneField). A forward O2O is a concrete RelatedField and is handled
        # by compile_output_fields' to-ONE arm.
        if not isinstance(field, OneToOneRel):
            continue
        if not getattr(field, "auto_created", False):
            continue

        # Accessor name on the OWNER (related_name, or "<model>" default).
        get_accessor = getattr(field, "get_accessor_name", None)
        if callable(get_accessor):
            try:
                accessor = get_accessor()
            except Exception:  # pragma: no cover — defensive
                accessor = getattr(field, "name", None)
        else:
            accessor = getattr(field, "name", None)
        if accessor is None:
            continue

        field_name = getattr(field, "name", accessor)
        if (
            only_set is not None
            and accessor not in only_set
            and field_name not in only_set
        ):
            continue
        if exclude_set is not None and (
            accessor in exclude_set or field_name in exclude_set
        ):
            continue

        # graphene parity: resolve the target type via the PER-TYPE registry and
        # DROP the field when the target model is not registered there.
        target_model = field.related_model
        target_type = registry.get_type_for_model(target_model)
        if target_type is None:
            continue
        # item-b (B5): resolve to THIS schema's FORKED target instance when a
        # non-default pair is in play; default pair -> the class-def instance ->
        # byte-identical.
        from .core.base import resolved_output_type

        compiled = resolved_output_type(target_type, registries)
        if compiled is None:
            continue

        # Single nullable object field (graphene renders reverse O2O ALWAYS
        # nullable: required=is_required(field) and input_flag=='create' is
        # always False for output). The resolver reads the reverse accessor;
        # Django raises RelatedObjectDoesNotExist when the row has no related
        # instance — return None in that case (a nullable field).
        def _resolver(root: Any, _info: Any, *, _name: str = accessor) -> Any:
            if isinstance(root, dict):
                return root.get(_name)
            try:
                return getattr(root, _name, None)
            except ObjectDoesNotExist:
                return None

        out[to_camel_case(accessor)] = GraphQLField(
            type_=compiled,
            resolve=_resolver,
        )
    return out


def _make_output_thunk_for(
    src_cls: type,
    model: type,
    output_registry: Any,
    graphene_registry: Any,
    only_fields: list[str] | None,
    exclude_fields: list[str] | None,
    registries: Any,
    include_fields: list[str] | None = None,
) -> Any:
    """Build the lazy fields thunk for a ``DjangoObjectType``'s output type.

    item-b (B5): the SHARED instance-creation seam. BOTH the class-def native
    branch (DEFAULT pair) AND ``registry_compiler.compile_outputs_into`` (a
    FORKED pair) call this so the two paths build IDENTICAL field thunks, only
    differing in the registry pair they close over:

    - the FK relation lookup runs ``compile_output_fields(model, output_registry)``
      against the PAIR's ``NativeOutputRegistry`` (default = the global shared
      registry = byte-identical);
    - the to-many list containers, reverse-O2O, declared, and GFK-union injectors
      receive ``registries`` so they resolve the SCHEMA's FORKED instances
      (default pair -> the class-def instances -> byte-identical).

    Args:
        src_cls: The source ``DjangoObjectType`` subclass.
        model: The Django model the type wraps.
        output_registry: The ``NativeOutputRegistry`` whose ``get_compiled`` the
            FK relation thunk reads (the pair's ``output`` member).
        graphene_registry: The per-type graphene ``Registry`` (used by the
            relation-list / reverse-O2O injectors for ``get_type_for_model`` /
            ``get_or_create_list_object_type``).
        only_fields / exclude_fields: Projection passed to ``compile_output_fields``.
        registries: The ``SchemaRegistries`` pair threaded into the container /
            reverse-O2O injectors so they resolve forked instances.

    Returns:
        A zero-arg thunk that returns the ``{camelCase: GraphQLField}`` dict.
    """
    from .core.output_compiler import compile_output_fields

    def _thunk(
        _model: type = model,
        _reg: Any = output_registry,
        _graphene_reg: Any = graphene_registry,
        _only_f: list[str] | None = only_fields,
        _excl_f: list[str] | None = exclude_fields,
        _src_cls: type = src_cls,
        _registries: Any = registries,
        _incl_f: list[str] | None = include_fields,
    ) -> dict:
        _fields = compile_output_fields(
            _model,
            _reg,
            only_fields=_only_f,
            exclude_fields=_excl_f,
            include_fields=_incl_f,
            graphene_registry=_graphene_reg,
        )
        _fields.update(
            _compile_relation_list_fields(
                _src_cls,
                _model,
                _graphene_reg,
                only_fields=_only_f,
                exclude_fields=_excl_f,
                registries=_registries,
            )
        )
        _fields.update(
            _compile_reverse_o2o_fields(
                _src_cls,
                _model,
                _graphene_reg,
                only_fields=_only_f,
                exclude_fields=_excl_f,
                registries=_registries,
            )
        )
        _fields.update(_compile_declared_list_fields(_src_cls, _registries))
        _fields.update(_compile_declared_fields(_src_cls, _registries))
        _fields.update(_compile_gfk_union_output_fields(_src_cls, _registries))
        return _fields

    return _thunk


def _make_list_fields_thunk_for(
    list_model: type,
    results_field_name: str,
    output_registry: Any,
    paginator: Any,
) -> Any:
    """Build the lazy fields thunk for a ``DjangoListObjectType`` container.

    item-b (B5): the SHARED list-container instance-creation seam (mirrors
    ``_make_output_thunk_for``). The ``results`` element type is read from the
    pair's ``NativeOutputRegistry`` so a FORKED container's results node is THIS
    schema's forked node (default pair -> the class-def node -> byte-identical).

    Args:
        list_model: The Django model the list container wraps.
        results_field_name: The container's results field name (e.g. ``results``).
        output_registry: The ``NativeOutputRegistry`` whose ``get_compiled``
            resolves the node element type (the pair's ``output`` member).
        paginator: The configured paginator (or ``None`` for a plain list).

    Returns:
        A zero-arg thunk that returns the container's field dict.
    """
    from graphql import GraphQLField, GraphQLInt, GraphQLList

    def _thunk(
        _m: type = list_model,
        _rfn: str = results_field_name,
        _reg: Any = output_registry,
        _pg: Any = paginator,
    ) -> dict:
        node_gql = _reg.get_compiled(_m)
        if node_gql is None:
            from graphql import GraphQLString as _S

            node_gql = _S  # type: ignore[assignment]

        from django_graphex.paginations.utils import NativePaginationField

        _results_args: dict = {}
        _results_resolve = None
        if _pg is not None:
            _results_args = _pg.to_graphql_fields(native=True)
            _native_field = NativePaginationField(type=node_gql, paginator=_pg)
            from graphql.execution import default_field_resolver as _dfr

            _results_resolve = _native_field.wrap_resolve(_dfr)

        def _total_count_resolve(root: Any, info: Any, **_kw: Any) -> Any:
            return getattr(root, "count", None)

        fields: dict = {
            _rfn: GraphQLField(
                GraphQLList(node_gql),
                args=_results_args,
                resolve=_results_resolve,
            ),
            "totalCount": GraphQLField(GraphQLInt, resolve=_total_count_resolve),
        }

        if _pg is not None:
            _native_page_info = _pg.get_native_page_info_field(node_gql)
            if _native_page_info is not None:
                fields["pageInfo"] = _native_page_info

        return fields

    return _thunk


def _check_unknown_options(cls_name: str, remaining: dict[str, Any]) -> None:
    """Raise ImproperlyConfigured for any unknown Meta options.

    After all recognised django-graphex options are consumed from **options,
    only keys that graphene's own base classes accept should remain.  Any other
    key is almost certainly a typo (e.g. ``max_dep`` instead of ``max_depth``)
    that would otherwise be silently swallowed.

    Private names (those starting with an underscore) are ignored: they may
    arise from ``from app.models import Foo as _Foo`` inside a ``Meta`` class
    body, where the import alias leaks as a class attribute.

    Args:
        cls_name: the name of the class being constructed (for error messages).
        remaining: the leftover **options dict after consuming dgx options.

    Raises:
        ImproperlyConfigured: if any public key in *remaining* is not a known
            graphene base option.
    """
    # Filter out private names (underscore-prefix) — these are conventional
    # aliases from ``import ... as _X`` inside Meta bodies, not user typos.
    unknown = sorted(
        k for k in set(remaining) - _GRAPHENE_BASE_OPTIONS if not k.startswith("_")
    )
    if unknown:
        raise ImproperlyConfigured(
            "{cls}: unknown Meta option(s) {opts!r}. "
            "Check for typos — e.g. 'max_dep' instead of 'max_depth'.".format(
                cls=cls_name,
                opts=unknown,
            )
        )


# S8b: the graphene-era ``DjangoObjectOptions`` / ``DjangoModelTypeOptions``
# ``BaseOptions`` subclasses were DEAD — the native path builds a single mutable
# ``NativeObjectTypeOptions`` (native.base) on every re-parented type. The
# native-friendly Options containers (used by tests) live in
# ``django_graphex._options``. The graphene ``BaseOptions`` import is removed with
# these classes.


class DjangoObjectType(NativeObjectType):
    """A Django model GraphQL type with enhanced features.

    Subclasses may override "get_queryset(cls, queryset, info)" to scope
    the base queryset per-request (e.g. to the current user's rows). The
    override is called by "DjangoObjectField", "DjangoFilterListField",
    and "DjangoFilterPaginateListField" BEFORE the query optimizer runs,
    so "select_related"/"prefetch_related" are applied on top of the
    already-narrowed queryset.
    """

    #: Sentinel checked by ``queryset_factory`` to distinguish a plain
    #: ``DjangoObjectType`` subclass (``queryset, info`` contract) from a
    #: ``DjangoModelType`` subclass (``manager, info, **kwargs`` contract).
    #: ``DjangoModelType`` does NOT inherit from ``DjangoObjectType``, so it
    #: never acquires this attribute.
    _dgx_has_object_type_get_queryset: bool = True

    @classmethod
    def __init_subclass_with_meta__(
        cls,
        model: type[Model] | None = None,
        registry: Registry | None = None,
        skip_registry: bool = False,
        only_fields: tuple[str, ...] = (),
        exclude_fields: tuple[str, ...] = (),
        include_fields: tuple[str, ...] = (),
        filter_fields: Any = None,
        interfaces: tuple[Any, ...] = (),
        max_depth: int | None = None,
        complexity: int | None = None,
        unions: dict | None = None,
        **options,
    ) -> None:
        """Initialize the subclass with meta options for a Django object type.

        Args:
            model: Django model this type represents.
            registry: Registry to register this type in; defaults to the
                global registry.
            skip_registry: When True, do not register this type.
            only_fields: Model field names to include exclusively.
            exclude_fields: Model field names to exclude.
            include_fields: Extra model field names to include.
            filter_fields: Field names usable for filtering.
            interfaces: GraphQL interfaces this type implements.
            max_depth: Max nested-object depth allowed below this type, enforced
                by "DepthLimitValidationRule"; "None" means no per-type limit.
            complexity: Cost weight of a field returning this type, used by
                "CostLimitValidationRule"; "None" means the default weight (1).
            unions: Optional mapping of GenericForeignKey field name to a
                companion "DjangoUnionType" (Track 2). When set, the GFK
                converter emits a typed Union field for that FK instead of the
                flat "GenericForeignKeyType".
            **options: Extra options forwarded to the parent implementation.

        Raises:
            ImproperlyConfigured: If the legacy "Meta.gfk_unions" key is declared
                (renamed to "unions" in v2.0).
        """
        # HARD rename guard (v2.0): ``Meta.gfk_unions`` -> ``Meta.unions`` (mirrors
        # the ``gfk_types`` -> ``types`` rename). A subclass still declaring the old
        # name lands it in **options; fail loudly with the new spelling BEFORE the
        # generic unknown-option check swallows it into a vague "unknown option".
        if "gfk_unions" in options:
            raise ImproperlyConfigured(
                f"{cls.__name__}: gfk_unions was renamed to unions in v2.0. "
                f"Declare the typed GFK unions via Meta.unions = {{...}}."
            )

        _check_unknown_options(cls.__name__, options)

        assert is_valid_django_model(model), (
            'You need to pass a valid Django Model in {}.Meta, received "{}".'
        ).format(cls.__name__, model)

        if not registry:
            registry = get_global_registry()

        assert isinstance(registry, Registry), (
            "The attribute registry in {} needs to be an instance of "
            'Registry, received "{}".'
        ).format(cls.__name__, registry)

        # Collect @filter_field-decorated methods and validate reserved names.
        custom_filters = collect_custom_filters(cls)
        for arg_name, _fn, _meta_ff in custom_filters:
            if arg_name in RESERVED_FILTER_ARGS:
                raise ImproperlyConfigured(
                    "{cls}: @filter_field method name {name!r} collides with a "
                    "reserved pagination / ordering argument. Choose a different "
                    "name. Reserved names: {reserved}.".format(
                        cls=cls.__name__,
                        name=arg_name,
                        reserved=sorted(RESERVED_FILTER_ARGS),
                    )
                )
        cls._dgx_custom_filters = custom_filters

        django_fields = _yank_fields(
            construct_fields(
                model, registry, only_fields, include_fields, exclude_fields
            ),
            _as=NativeMountedField,
        )

        _meta = NativeObjectTypeOptions(cls)
        _meta.model = model
        _meta.registry = registry
        _meta.filter_fields = filter_fields
        _meta.fields = django_fields
        _meta.max_depth = max_depth
        _meta.complexity = complexity
        _meta.unions = dict(unions) if unions else None

        super().__init_subclass_with_meta__(
            _meta=_meta, interfaces=interfaces, **options
        )

        if not skip_registry:
            registry.register(cls)

        # ----------------------------------------------------------------
        # NATIVE PATH: create EXACTLY ONE GraphQLObjectType per DjangoObjectType,
        # ONCE, here at class definition — identity-stable.  Its relation fields
        # are LAZY THUNKS that resolve against the SHARED GLOBAL output registry
        # (django_graphex.core.base.get_shared_output_registry()), NEVER a
        # per-class local registry.
        #
        # Why a single instance + shared-registry thunks: relations CANNOT be
        # resolved at class-definition time (the related type may be defined
        # later).  By closing the field thunk over the GLOBAL registry, the
        # relation lookup runs lazily — after compile_all_outputs() has
        # registered every type's stub — so it resolves to the related type's
        # real GraphQLObjectType instead of degrading to GraphQLString.
        #
        # compile_all_outputs() (called at app-ready) POPULATES/validates these
        # existing instances against the SAME shared registry.  It NEVER creates
        # a second GraphQLObjectType for an already-registered type, so the
        # instance pinned by mutation.py (mutation.py:434/456) at mutation
        # class-def time is the SAME object that ends up in the assembled
        # GraphQLSchema — eliminating the duplicate-name TypeError hazard.
        #
        # S6b: DjangoObjectType is NATIVE-ONLY (re-parented onto
        # ``native.base.ObjectType``). The native compile is UNCONDITIONAL.
        # ``model is not None`` is still guarded because abstract bases (no model)
        # must not build an output type.
        # ----------------------------------------------------------------
        if model is not None:
            from graphql import GraphQLObjectType

            from django_graphex.core.base import (
                _gdx_output_registry,
                _GdxOutputEntry,
                is_forking,
            )
            from django_graphex.core.bridge import GdxPayload
            from django_graphex.core.ir import GdxMeta

            # Resolve the GraphQL type NAME the SAME way graphene does: an
            # explicit ``Meta.name`` (forwarded via **options) wins, otherwise the
            # class name. Auto-generated types (factory_type) set ``Meta.name``
            # (e.g. ``<Model>GenericType``); honoring it keeps native type NAMES
            # byte-identical to graphene's. Without this the native type would be
            # named ``GenericType`` while graphene names it ``<Model>GenericType``.
            _gql_name = options.get("name") or cls.__name__

            # item-b (B5): during a FORKED schema build, a type AUTO-CREATED by a
            # relation thunk is pair-scoped — it must NOT enter the GLOBAL
            # app-ready compile list (``compile_all_outputs``), or several
            # same-named pair containers would poison the global namespace. Skip
            # the global append while forking; the type is forked into its pair
            # instead. Outside a fork (the default path) this is byte-identical.
            _forking = is_forking()

            # Register in the global entry list for compile_all_outputs() at
            # app-ready (carries projection / depth / complexity metadata).
            _entry = _GdxOutputEntry(
                cls=cls,
                gql_name=_gql_name,
                model=model,
                only_fields=list(only_fields) if only_fields else None,
                exclude_fields=list(exclude_fields) if exclude_fields else None,
                max_depth=max_depth,
                complexity=complexity,
                include_fields=list(include_fields) if include_fields else None,
            )
            if not _forking:
                _gdx_output_registry.append(_entry)

            # OUTPUT registry: the source of truth for this type's relation
            # thunks. Keyed by MODEL with last-registration-wins semantics,
            # mirroring the graphene Registry (registry.get_type_for_model(model)).
            # Relation thunks of OTHER types resolve a FK/M2M to whatever instance
            # is the canonical (last-registered) type for the related model.
            #
            # Registry-scoped: use the class's OWN registry companion, NOT the
            # process-global shared registry directly. For the GLOBAL registry
            # (``Meta.registry`` unset -> ``get_global_registry()``) the companion
            # IS ``get_shared_output_registry()``, so the default/production/
            # playground path is BYTE-IDENTICAL. A LOCAL ``Meta.registry`` gets
            # its OWN companion, so a sibling relation resolves within that
            # registry group WITHOUT leaking the node into the global namespace
            # (the cross-schema duplicate-name leak). ``is_forking()`` still means
            # the shared/global registry must not be touched — a forked build
            # binds the PAIR's ``output`` registry via ``compile_outputs_into``.
            _shared_registry = registry.output_registry()

            # EXACTLY ONE instance PER CLASS, created ONCE here.  Distinct
            # classes wrapping the same model (e.g. different only_fields /
            # complexity) each get their OWN identity-stable instance; the GraphQL
            # type NAME is the resolved name so there is no name collision.
            _gdx_meta_obj = GdxMeta(
                name=_gql_name,
                model=model,
                max_depth=max_depth,
                complexity=complexity,
                # DEFECT A: carry the source DjangoObjectType subclass so the
                # optimizer can recover AnnotatedField annotations
                # (utils._collect_annotated_fields) and per-field
                # ``optimize_<field>`` hooks (utils._get_field_optimize_hook) on
                # NESTED types — exactly as the root compiler does
                # (schema_compiler.py:854 ``graphene_type=root``). Without this
                # the bridge (_gdx_graphene_type) returns None on nested types
                # and every optimizer hook is silently inert.
                graphene_type=cls,
            )
            _gdx_payload = GdxPayload(_gdx_meta_obj)

            _only = list(only_fields) if only_fields else None
            _excl = list(exclude_fields) if exclude_fields else None
            _incl = list(include_fields) if include_fields else None

            # LAZY field thunk bound to the SHARED registry.  Evaluated on first
            # `.fields` access; by app-ready (compile_all_outputs) every model's
            # canonical instance is in the shared registry so relation lookups
            # resolve to the real related GraphQLObjectType (not GraphQLString).
            #
            # item-b (B5): built via the SHARED ``_make_output_thunk_for`` factory
            # so the class-def (DEFAULT pair) and ``compile_outputs_into`` (FORKED
            # pair) produce IDENTICAL thunks. The class-def path passes
            # ``registries=None`` so the container / reverse-O2O injectors resolve
            # the class-def instances — byte-identical to the pre-B5 inline thunk.
            _make_output_thunk = _make_output_thunk_for(
                cls,
                model,
                _shared_registry,
                registry,
                _only,
                _excl,
                None,
                include_fields=_incl,
            )

            # DEFECT #8: wire any DjangoInterfaceType this type implements onto the
            # native GraphQLObjectType as graphql-core ``interfaces=`` (a lazy
            # thunk so the interface compiles after this type's class-def). graphene
            # listed implemented interfaces under the object type's ``interfaces=``;
            # native must do the same or the interface is never an implementor and
            # ``... on <Interface>`` / interface fields fail at schema build.
            _declared_interfaces = tuple(interfaces or ())

            def _make_interfaces(
                _ifaces: tuple[Any, ...] = _declared_interfaces,
            ) -> list[Any]:
                if not _ifaces:
                    return []
                from django_graphex.core.polymorphic_compiler import (
                    compile_interface_type,
                    is_interface_type,
                )

                compiled: list[Any] = []
                for iface in _ifaces:
                    if is_interface_type(iface):
                        compiled.append(compile_interface_type(iface))
                return compiled

            _graphql_output_type = GraphQLObjectType(
                name=_gql_name,
                fields=_make_output_thunk,
                interfaces=_make_interfaces if _declared_interfaces else None,
                extensions={"gdx": _gdx_payload},
            )

            # Last-wins: make THIS class's instance the canonical one for the
            # model so relation thunks resolve to it — consistent with the
            # graphene Registry's (model, None) last-registration-wins rule and
            # with registry.register(cls) above.  When skip_registry=True the
            # class is NOT canonical in the graphene Registry, so do not let it
            # claim the shared slot either.
            #
            # item-b (B5): during a FORKED build, the GLOBAL shared output
            # registry must NOT be touched (an auto-created pair type would
            # overwrite the global model slot, leaking into default-pair schemas).
            # The forked type is registered in its PAIR output registry by
            # ``compile_outputs_into`` / ``fork_output_class`` instead. Outside a
            # fork this is byte-identical (the global last-wins write a custom- or
            # global-registry type relies on for default-pair relation resolution).
            #
            # Registry-scoped stamping: ``_shared_registry`` is the class's OWN
            # registry companion (``registry.output_registry()``). For the GLOBAL
            # registry it IS the process-wide shared singleton, so this stamps the
            # global slot exactly as before (byte-identical). For a LOCAL
            # ``Meta.registry`` it stamps that registry's OWN companion, so a
            # sibling relation resolves within the group WITHOUT depositing the
            # node into the GLOBAL namespace — the fix for the cross-schema leak
            # where a later DEFAULT-pair schema resolved a relation (e.g. an FK) to
            # a leaked local-registry node and, transitively, to its leaked
            # ``<Model>ListType`` container ("multiple types named '<Model>ListType'"
            # at assembly). ``_forking`` still skips the write entirely (a forked
            # build binds the PAIR's ``output`` registry via ``compile_outputs_into``).
            if not skip_registry and not _forking:
                _shared_registry.set_compiled(model, _graphql_output_type)

            # S6b: ``_meta`` is now a MUTABLE ``NativeObjectTypeOptions`` (no
            # freeze() — the native terminal does not freeze), so this is a PLAIN
            # assignment. The old ``object.__setattr__`` freeze-bypass workaround
            # is gone.
            _meta.graphql_output_type = _graphql_output_type

    def resolve_id(self, info: ResolveInfo) -> Any:
        """Resolve the "id" field for the object.

        Args:
            info: GraphQL resolve info for the current request.

        Returns:
            The primary key of the underlying model instance.
        """
        return self.pk

    @classmethod
    def is_type_of(cls, root: Any, info: ResolveInfo) -> bool:
        """Check whether the root object is an instance of this type.

        Args:
            root: Object being resolved.
            info: GraphQL resolve info for the current request.

        Returns:
            True if "root" is compatible with this type.

        Raises:
            Exception: If "root" is not a valid Django model instance.
        """
        if isinstance(root, SimpleLazyObject):
            root._setup()
            root = root._wrapped
        if isinstance(root, cls):
            return True
        if not is_valid_django_model(type(root)):
            raise TypeError(f'Received incompatible instance "{root}".')
        return isinstance(root, cls._meta.model)

    @classmethod
    def get_queryset(cls, queryset: QuerySet, info: ResolveInfo) -> QuerySet:
        """Return the queryset for this type.

        Args:
            queryset: Base queryset to scope.
            info: GraphQL resolve info for the current request.

        Returns:
            The queryset to use, unchanged by default.
        """
        return queryset

    @classmethod
    def get_node(cls, info: ResolveInfo, id: Any) -> Model | None:
        """Return a single node by its primary key.

        Args:
            info: GraphQL resolve info for the current request.
            id: Primary key of the object to fetch.

        Returns:
            The matching model instance, or None if it does not exist or the
            "get_queryset" scope excludes it.
        """
        # SECURITY: the primary key comes straight from the caller, so this
        # lookup goes through the same "get_queryset" choke point every other
        # row-serving path uses -- resolving it on the bare manager would hand
        # back exactly the rows the scope exists to hide.
        try:
            scoped = apply_object_type_get_queryset(
                cls._meta.model._default_manager.all(), cls, info
            )
            return scoped.get(pk=id)
        except cls._meta.model.DoesNotExist:
            return None


def _schema_scoped_registry(info: ResolveInfo) -> Any:
    """Return the request schema's scoped graphene ``Registry``, or ``None``.

    item-b (B4): the ONLY genuine query-time registry read. A
    ``DjangoGraphQLSchema`` stows its ``SchemaRegistries`` pair on
    ``graphql_schema.extensions['gdx_registry']`` (B3); a polymorphic
    ``resolve_type`` recovers the pair via ``info.schema`` and returns its
    ``graphene`` member so a schema built with a FORKED registry (later slices)
    resolves rows against ITS namespace instead of the class-def binding.

    Reads exactly like the protected-fields channel (``security.py``): defensive
    ``getattr`` so a ``None`` info (the unit-test ``resolve_type(instance, None)``
    call style) or a schema with no extensions degrades to ``None`` — the caller
    then falls back to the per-class / global chain (byte-identical).

    With the DEFAULT pair the ``graphene`` member IS ``get_global_registry()``,
    so the scoped read is the same registry the chain would reach anyway.
    """
    schema = getattr(info, "schema", None)
    extensions = getattr(schema, "extensions", None) or {}
    pair = extensions.get("gdx_registry")
    if pair is None:
        return None
    return getattr(pair, "graphene", None)


def _resolve_polymorphic_type(cls: Any, instance: Any, info: ResolveInfo) -> Any:
    """Map a plain Django model instance to its registered DjangoObjectType.

    Shared by "DjangoUnionType" and "DjangoInterfaceType". Each prefetched /
    resolved row is a CONCRETE member model, so ``type(instance)`` yields the
    concrete class and the registry maps it to the right output type.

    Registry resolution order (item-b, B4):

    1. the SCHEMA-SCOPED registry from ``info.schema.extensions['gdx_registry']``
       (so a forked-registry schema resolves against ITS namespace);
    2. the per-class binding ``cls._dgx_registry``;
    3. the process-wide global registry.

    Candidates are tried in order and the FIRST that maps the model wins; an
    earlier candidate that does not register the model (returns ``None``) falls
    through to the next. With the default pair the schema-scoped registry IS the
    global, so the per-class / global chain still catches every row it caught
    before B4 — byte-identical for the single/default-schema case.

    Args:
        cls: the union or interface class whose registry is consulted.
        instance: the Django model instance being resolved.
        info: GraphQL resolve info for the current request. ``info.schema`` is
            read for the schema-scoped registry (B4); ``None`` degrades to the
            class chain.

    Returns:
        The registered "DjangoObjectType" subclass for ``type(instance)``.

    Raises:
        TypeError: if NO candidate registry has a "DjangoObjectType" for the
            instance's model. This is intentional: a silent None would surface
            later as the opaque "Abstract type must resolve to an Object type"
            runtime error.
    """
    model = type(instance)
    # Ordered, de-duplicated candidate registries: schema-scoped first, then the
    # per-class binding, then the global. ``None`` entries (no info / no binding)
    # are skipped; a registry already tried is not consulted twice.
    candidates: list[Any] = []
    for registry in (
        _schema_scoped_registry(info),
        getattr(cls, "_dgx_registry", None),
        get_global_registry(),
    ):
        if registry is not None and not any(registry is c for c in candidates):
            candidates.append(registry)

    for registry in candidates:
        object_type = registry.get_type_for_model(model)
        if object_type is not None:
            return object_type

    raise TypeError(
        "{cls}.resolve_type: no DjangoObjectType registered for "
        "{model!r}. Every member/implementor model must have a "
        "DjangoObjectType registered in the same registry.".format(
            cls=cls.__name__, model=model.__name__
        )
    )


class DjangoUnionType(NativeObjectType):
    """A GraphQL Union over explicitly enumerated DjangoObjectType members.

    Members are declared via "Meta.types" (a sequence of DjangoObjectType
    subclasses); they are NEVER discovered from the ContentType table.
    "resolve_type" maps a resolved Django row to its registered
    DjangoObjectType. "Meta.possible_types" is intentionally NOT set (it would
    collide with the DjangoObjectType "is_type_of" discrimination).

    S6d re-parents this off graphene "Union" onto the native graphene-free
    "ObjectType" base. The union is REGISTRY-ONLY: there is NO compiled native
    Union "GraphQLUnionType" today (the native compiler consumes the union via
    the registry + "resolve_type", reading "_meta.types" / the member-model
    tuple). The native ObjectType base supplies exactly what this metadata
    carrier needs: "type(cls) is pydantic.ModelMetaclass" (#1452), a
    graphene-free MUTABLE "_meta" ("NativeObjectTypeOptions" -- which carries
    "name" and the "types" slot the union sets below), and the
    "__init_subclass_with_meta__" dispatch that sets "_meta.name". Reusing
    "ObjectType" is sound precisely because nothing compiles this class as a
    graphene Union -- it is a name + member-list registry record.
    """

    class Meta:
        """Meta configuration for DjangoUnionType.

        Marks the base class as abstract so it is never itself registered or
        compiled; only concrete union subclasses are.
        """

        abstract = True

    @classmethod
    def __init_subclass_with_meta__(
        cls,
        types: tuple[Any, ...] = (),
        registry: Registry | None = None,
        _meta: Any = None,
        **options,
    ) -> None:
        """Initialize the union with its explicit member types.

        "types" MUST be an explicit named parameter: the native ObjectType
        terminal would otherwise swallow an unconsumed "types" kwarg into its
        "**_kwargs" and silently drop it (see the "_meta.types" note below).

        Args:
            types: the DjangoObjectType members of this union (>= 1).
            registry: registry to self-register in; defaults to the global one.
            _meta: optional pre-built meta options object.
            **options: extra options forwarded to the native base.
        """
        # v2.0 rename: ``Meta.gfk_types`` -> ``Meta.types``. A subclass still
        # declaring the old name lands it in **options; fail loudly instead of
        # silently building an empty union.
        if "gfk_types" in options:
            raise ImproperlyConfigured(
                f"{cls.__name__}: gfk_types was renamed to types in v2.0. "
                f"Declare the union members via Meta.types = (...)."
            )

        if not registry:
            registry = get_global_registry()

        member_types = tuple(types)
        assert member_types, (
            "{} must declare Meta.types with at least one "
            "DjangoObjectType member.".format(cls.__name__)
        )

        cls._dgx_member_models = tuple(t._meta.model for t in member_types)
        cls._dgx_registry = registry

        # Build the union's own mutable ``_meta`` carrying the member ``types``.
        # graphene's ``Union`` driver set ``_meta.types`` from the ``types=``
        # kwarg; the native ObjectType terminal does NOT consume ``types`` (it
        # would be swallowed into ``**_kwargs`` and dropped), so the driver sets
        # it here directly. ``_meta.types`` stays the registry-only member list
        # the polymorphic machinery reads (utils.py:682); the name is set by the
        # native terminal below.
        if _meta is None:
            _meta = NativeObjectTypeOptions(cls)
        _meta.types = member_types

        # Native terminal sets ``_meta.name`` (= cls.__name__ unless overridden).
        super().__init_subclass_with_meta__(_meta=_meta, **options)

        # After super() so ``cls._meta.name`` is set.
        registry.register_polymorphic(cls)

    @classmethod
    def resolve_type(cls, instance: Any, info: ResolveInfo) -> Any:
        """Resolve a Django instance to its registered DjangoObjectType.

        Args:
            instance: the resolved Django model instance.
            info: GraphQL resolve info for the current request.

        Returns:
            The matching "DjangoObjectType" subclass.

        Raises:
            TypeError: if the instance's model has no registered type.
        """
        return _resolve_polymorphic_type(cls, instance, info)


class DjangoInterfaceType(NativeObjectType):
    """A GraphQL Interface enabling shared field declarations across types.

    Concrete "DjangoObjectType" subclasses declare membership via the existing
    "Meta.interfaces" kwarg. Field sharing is structural (schema-level) only;
    this MVP introduces no new queryset fetch path for interfaces.
    "resolve_type" follows the same model -> registry -> DjangoObjectType
    contract as "DjangoUnionType". "Meta.possible_types" is intentionally NOT
    set.

    S6d re-parents this off graphene "Interface" onto the native graphene-free
    "ObjectType" base. Like "DjangoUnionType" it is REGISTRY-ONLY: there is
    NO compiled native "GraphQLInterfaceType" today -- concrete object types
    name it via "Meta.interfaces" and the interface itself is a name +
    "resolve_type" registry record. The native ObjectType base supplies the
    ModelMetaclass identity (#1452), the graphene-free MUTABLE "_meta" (with
    the "name" the terminal sets), and the field-descriptor collection so
    declared interface fields (e.g. "name = graphene.String()") still land in
    "_meta.fields" without Pydantic mis-parsing them.
    """

    class Meta:
        """Meta configuration for DjangoInterfaceType.

        Marks the base class as abstract so it is never itself registered or
        compiled; only concrete interface subclasses are.
        """

        abstract = True

    @classmethod
    def __init_subclass_with_meta__(
        cls,
        registry: Registry | None = None,
        _meta: Any = None,
        **options,
    ) -> None:
        """Initialize the interface and self-register it.

        Args:
            registry: registry to self-register in; defaults to the global one.
            _meta: optional pre-built meta options object.
            **options: extra options forwarded to the native base.
        """
        if not registry:
            registry = get_global_registry()

        cls._dgx_registry = registry

        # Native terminal sets ``_meta.name`` (= cls.__name__ unless overridden)
        # and merges any declared graphene field descriptors into ``_meta.fields``.
        super().__init_subclass_with_meta__(_meta=_meta, **options)

        # After super() so ``cls._meta.name`` is set.
        registry.register_polymorphic(cls)

    @classmethod
    def resolve_type(cls, instance: Any, info: ResolveInfo) -> Any:
        """Resolve a Django instance to its registered DjangoObjectType.

        Args:
            instance: the resolved Django model instance.
            info: GraphQL resolve info for the current request.

        Returns:
            The matching "DjangoObjectType" subclass.

        Raises:
            TypeError: if the instance's model has no registered type.
        """
        return _resolve_polymorphic_type(cls, instance, info)


def _nested_input_perms(
    child_model: type[Model], input_for: str, registry: Registry
) -> frozenset[str]:
    """Return the permissions a parent's nested input field for a child requires.

    It is the composite default for the verbs the nested surface actually
    enables, and NOT simply ``required_perms_for(child, input_for)``: a nested
    payload's ``id`` is OPTIONAL on an UPDATE input, so omitting it CREATES a
    child row. Stamping the parent's verb alone left a caller who holds
    ``change_child`` but not ``add_child`` with the child's own create root
    pruned away while the identical create stayed reachable through the parent's
    update payload -- the same front-door / back-door shape the stamp exists to
    close. The CREATE input carries no ``id`` at all, so it stays a create
    surface only.

    The ``required_perms`` of every host that SERVES one of those verbs is then
    UNIONED onto that default, never substituted for it. The override can
    therefore only ever ADD a requirement, which is what makes it safe in both
    directions. Honouring it as a REPLACEMENT read a READ label as a licence to
    WRITE: an ordinary read host declaring ``required_perms =
    ["app.view_child"]``, the most common shape there is, collapsed the nested
    write stamp to a view permission. Ignoring it outright was the mirror image:
    a WRITE host declaring a stricter label (say ``["app.manage_child"]``) never
    reached the nested surface, so a caller holding only ``add_child`` wrote
    child rows through the parent that the child's own root -- pruned away from
    that caller's schema -- refuses.

    The label follows the same operation rule the allowance axis follows (see
    ``nested.hosts_serving``): a host that does not generate the verb the nested
    field enables has no say over it, so a delete-only host's destructive label
    no longer deletes the nested CREATE field for a caller who may legitimately
    write the child.

    This runs LAZILY, in the parent input's field thunk, from the same host list
    and at the same moment as the projection in ``nested_child_input``. Resolved
    eagerly at the parent's class-definition time it read a DIFFERENT host list
    than the projection did: a child host declared after the parent had its
    ``exclude_fields`` honoured and its ``required_perms`` silently dropped,
    and the late-host guard -- which keys off the thunk-time watermark -- never
    fired for it.

    A child writable only through its parent needs no override at all: the
    caller doing that write holds the child's write label, and what the project
    withholds is the child's own root -- which, never mounted, gives the pruner
    nothing to prune.

    Args:
        child_model: The nested child's Django model.
        input_for: The PARENT's operation ("create" or "update").
        registry: The registry whose declared hosts the stamp is read from.

    Returns:
        The permission codenames the nested input field is stamped with.
    """
    from django_graphex.core.perm_labels import required_perms_for

    perms: frozenset[str] = frozenset()
    verbs = ("create", "update") if input_for == "update" else ("create",)
    for verb in verbs:
        perms |= required_perms_for(child_model, verb)
        for host in hosts_serving(registry, child_model, verb):
            perms |= frozenset(getattr(host, "required_perms", None) or ())
    return perms


def _resolve_native_nested_input_fields(
    model: type[Model],
    registry: Registry,
    input_for: str,
    nested_fields: Any,
) -> tuple[Any, ...]:
    """Resolve ``Meta.nested_fields`` into native nested object-input specs.

    Mirrors the legacy graphene nested converters (``convert_*`` with
    ``nested_field=True``) on the native input path: each ``{field: ChildModel}``
    entry becomes a ``NestedInputField`` wrapping the CHILD model's compiled
    ``GraphQLInputObjectType`` as built FOR THIS PARENT (see
    ``nested_child_input``). Relation kind decides the shape exactly as graphene
    did:

    * forward FK / reverse-O2O (to-one) -> single ``<Child>`` object input,
    * M2M / reverse-FK (to-many) -> ``[<Child>!]`` list input.

    The child input type is BUILT LAZILY (via a thunk) inside the parent's own
    ``fields`` thunk, so a self-referential nested model
    (``nested_fields={"children": Self}``) terminates: the child is built with
    EMPTY ``nested_fields`` (its own relation stays the scalar ``[ID!]``
    surface), so no unbounded recursion.

    Args:
        model: The Django model the parent input is built for.
        registry: The active type registry (it owns the child-input memo).
        input_for: The operation ("create" or "update"); the child input is
            looked up for the same operation.
        nested_fields: The ``Meta.nested_fields`` mapping (or empty/falsy).

    Returns:
        A tuple of ``NestedInputField`` specs (empty when there is nothing to
        inject).
    """
    from django_graphex.core.input_compiler import NestedInputField

    from ._strconv import to_camel_case

    nested_map = nested_fields if isinstance(nested_fields, dict) else {}
    if not nested_map:
        return ()

    # to-many relation kinds emit a list input; to-one emit a single object.
    _to_many = {"one_to_many", "many_to_many"}

    specs: list[Any] = []
    for accessor, child_model in nested_map.items():
        try:
            relation = model._meta.get_field(accessor)
        except Exception:  # noqa: BLE001 — unknown accessor: skip, never crash
            continue  # nosec B112 — deliberate skip of unknown accessors

        if relation.many_to_one:
            is_list = False
        elif getattr(relation, "one_to_one", False):
            is_list = False
        elif relation.one_to_many or relation.many_to_many:
            is_list = True
        else:
            # Not an introspectable to-one/to-many relation: leave it out of
            # the nested object surface (parent backend handles it raw).
            continue

        def _child_thunk(_child_model: type[Model] = child_model) -> Any:
            """Build the child's input for THIS parent lazily (self-ref safe)."""
            from .mutation import nested_child_input

            return nested_child_input(
                _child_model, input_for, registry, model
            )._meta.graphql_input_type

        def _stamp_thunk(_child_model: type[Model] = child_model) -> frozenset[str]:
            """Read the child's nested write label lazily (host-order safe)."""
            return _nested_input_perms(_child_model, input_for, registry)

        specs.append(
            NestedInputField(
                out_name=accessor,
                alias=to_camel_case(accessor),
                child_input_type=_child_thunk,
                is_list=is_list,
                # SECURITY: the nested field IS a write surface for the child,
                # so it carries the child's write label. Without it the pruner
                # removed the child's own mutation root and cloned the parent's
                # input verbatim, leaving the same write reachable through the
                # parent -- worse than no feature, because it grants false
                # confidence.
                #
                # A THUNK, resolved by the input compiler in the same field-map
                # pass that calls "_child_thunk" above, so the stamp and the
                # projection are read from one host list at one moment. Frozen
                # here instead, it lost every host declared after the parent.
                required_perms=_stamp_thunk,
            )
        )
    return tuple(specs)


def _resolve_native_relation_input_fields(
    model: type[Model],
    input_for: str,
    nested_parent_model: type[Model] | None = None,
) -> tuple[Any, ...]:
    """Resolve a model's Django relations into ``ID`` / ``[ID]`` input specs.

    Mirrors the legacy graphene non-nested relation converters on the native
    input path so a mutation input exposes relations as id references:

    * forward FK / forward O2O -> single ``ID`` (``ID!`` when the FK is required
      and ``input_for == "create"``); these REPLACE the raw pk scalar the
      pydantic model emitted for the same attribute (e.g. ``author: Int!`` ->
      ``author: ID!``).
    * M2M -> ``[ID!]`` list (REPLACES the pydantic ``list[int]`` scalar surface).
    * reverse FK (to-many) -> ``[ID!]`` list, INJECTED (the pydantic model does
      not carry reverse relations).
    * reverse O2O -> single ``ID``, INJECTED.

    graphql-core's ``ID`` scalar coerces both string and integer literals, so a
    client may send the related pk either way; the snake out_name routes it to
    the resolver where pydantic coerces it to the model's pk type. The
    auto-created MTI parent-link O2O is skipped (it is Django-internal).

    Args:
        model: The Django model the input is built for.
        input_for: The operation ("create" or "update").
        nested_parent_model: When this input is a nested child, the nesting
            parent model; a forward FK / O2O on this child pointing back to that
            parent is rendered OPTIONAL (the FK is injected at save time).

    Returns:
        A tuple of ``RelationInputField`` specs (empty when the model has no
        introspectable relations).
    """
    from django.db import models as _dj_models

    from django_graphex.core.input_compiler import RelationInputField

    from ._strconv import to_camel_case

    is_create = input_for == "create"
    specs: list[Any] = []
    for field in model._meta.get_fields():
        # Skip the model's own primary key and plain concrete scalars.
        if getattr(field, "primary_key", False):
            continue

        # Server-managed relations are not client input. "construct_fields" and
        # "_resolve_native_choices_input_fields" already honour "editable", so a
        # non-editable SCALAR was excluded while a non-editable FK / O2O / M2M
        # was still advertised as writable and then silently dropped on save.
        # The guard is deliberately restricted to CONCRETE fields: Django sets
        # "editable = False" on every "ForeignObjectRel", so applying it to the
        # reverse branches below would delete the reverse-relation injection.
        if isinstance(field, _dj_models.Field) and not field.editable:
            continue

        # Forward FK / O2O (concrete, holds the key on this model).
        if isinstance(field, (_dj_models.ForeignKey, _dj_models.OneToOneField)):
            # Skip Django's MTI auto parent-link O2O (internal, not user input).
            if getattr(getattr(field, "remote_field", None), "parent_link", False):
                continue
            # Back-reference FK to the nesting parent -> optional (injected at
            # save time by the nested mixin; required-ness is still enforced by
            # the child's pydantic validation model for the standalone path).
            points_to_parent = (
                nested_parent_model is not None
                and field.related_model is nested_parent_model
            )
            required = (
                is_create
                and not points_to_parent
                and not field.null
                and not field.blank
                and not field.has_default()
            )
            specs.append(
                RelationInputField(
                    out_name=field.name,
                    alias=to_camel_case(field.name),
                    is_list=False,
                    required=required,
                    inject_only=False,  # REPLACES the pk scalar (Int -> ID)
                )
            )
            continue

        # Forward M2M (REPLACES the pydantic list[int] surface).
        if isinstance(field, _dj_models.ManyToManyField):
            specs.append(
                RelationInputField(
                    out_name=field.name,
                    alias=to_camel_case(field.name),
                    is_list=True,
                    required=False,
                    inject_only=False,
                )
            )
            continue

        # Reverse relations (no concrete column on this model) -> INJECT.
        if isinstance(field, _dj_models.ManyToManyRel):
            accessor = field.get_accessor_name()
            specs.append(
                RelationInputField(
                    out_name=accessor,
                    alias=to_camel_case(accessor),
                    is_list=True,
                    required=False,
                    inject_only=True,
                )
            )
            continue
        if isinstance(field, _dj_models.ManyToOneRel):
            # reverse FK (to-many) or reverse O2O (to-one).
            accessor = field.get_accessor_name()
            is_o2o = getattr(field, "one_to_one", False)
            specs.append(
                RelationInputField(
                    out_name=accessor,
                    alias=to_camel_case(accessor),
                    is_list=not is_o2o,
                    required=False,
                    inject_only=True,
                )
            )
            continue
    return tuple(specs)


def _resolve_native_choices_input_fields(
    model: type[Model],
    registry: Registry,
    input_for: str,
) -> tuple[Any, ...]:
    """Resolve a model's choices fields into native ``GraphQLEnumType`` input specs.

    S-input-5 (choices INPUT off graphene): the choices field's INPUT surface
    becomes the SHARED native ``GraphQLEnumType`` (the SAME canonical enum the
    OUTPUT + FILTER-INPUT paths resolve, S-enum-1) instead of the ``String``
    fallback the input compiler would otherwise emit from the pydantic Enum
    annotation. This is built GRAPHENE-FREE via ``converter.build_choices_enum_type``
    (``input_flag=None`` so it shares the OUTPUT slot — one enum per
    ``(model, field)`` across output + filter-input + mutation input).

    A ``MultiSelectField`` renders ``[Enum]`` (mirroring the converter's
    ``DjangoListField(enum)`` branch); a plain choices field renders a single
    ``Enum`` (``Enum!`` when required on create). Non-editable / auto fields and
    fields without usable choices are skipped (the enum builder returns ``None``).

    Args:
        model: The Django model the input is built for.
        registry: The registry whose shared enum slot the native paths converge on.
        input_for: The operation ("create", "update"); required-ness only applies
            to "create".

    Returns:
        A tuple of ``ChoicesInputField`` specs (empty when the model has no
        choices fields).
    """
    from django_graphex.core.input_compiler import ChoicesInputField

    from ._strconv import to_camel_case
    from .converter import build_choices_enum_type
    from .utils import is_required

    is_create = input_for == "create"
    specs: list[Any] = []
    for field in model._meta.get_fields():
        if not getattr(field, "choices", None):
            continue
        # Skip non-editable fields on input (mirrors construct_fields' editable
        # guard) so an auto/computed choices field is not exposed for write.
        if not getattr(field, "editable", True):
            continue
        enum_type = build_choices_enum_type(field, registry)
        if enum_type is None:
            continue
        is_multiselect = type(field).__name__ == "MultiSelectField"
        specs.append(
            ChoicesInputField(
                out_name=field.name,
                alias=to_camel_case(field.name),
                enum_type=enum_type,
                is_list=is_multiselect,
                required=is_create and is_required(field),
            )
        )
    return tuple(specs)


class DjangoInputObjectType(NativeInputType):
    """A Django model GraphQL input type.

    Compiles its "graphql_input_type" from a Pydantic model generated from the
    declared Django model ("build_model_schema(model)") instead of from
    annotation-driven fields, so it is model-driven rather than
    annotation-driven like a plain native "InputType".
    """

    def __init_subclass__(cls, **kwargs: Any) -> None:
        """Run the graphene-free ObjectType driver WITHOUT InputType registration.

        S6c re-parents ``DjangoInputObjectType`` off graphene ``InputObjectType``
        onto the native ``InputType`` base (the Pydantic engine: same
        ``ConfigDict`` / ``ModelMetaclass`` / ``ignored_types`` surface). But
        ``DjangoInputObjectType`` is MODEL-driven, not annotation-driven: its
        ``graphql_input_type`` is compiled from a generated Pydantic model
        (``build_model_schema(model)``) inside ``__init_subclass_with_meta__``,
        and the driver assigns its OWN ``_meta`` (a ``NativeObjectTypeOptions``
        carrying that compiled type).

        Native ``InputType.__init_subclass__`` is designed for PLAIN
        annotation-driven inputs (``class SearchInput(InputType): query: str``):
        it appends every subclass to ``_gdx_input_registry`` and OVERWRITES
        ``cls._meta`` with an empty ``_GdxInputMeta`` so ``compile_all_inputs()``
        can compile it from ``model_fields`` at app-ready. For a model-driven
        ``DjangoInputObjectType`` subclass that behavior is HARMFUL: it would (a)
        clobber the driver's ``_meta.graphql_input_type`` (read at
        mutation.py / DjangoModelType arg-building time) and (b) re-compile an
        EMPTY input type at app-ready (no annotations) under a DUPLICATE name.

        So this class bypasses ``InputType.__init_subclass__`` and dispatches the
        ObjectType graphene-free driver directly via ``NativeObjectType``. That
        runs the ``__init_subclass_with_meta__`` chain (the DjangoInputObjectType
        driver builds + assigns its own ``_meta``) and does NOT touch the input
        registry. The native ``InputType`` Pydantic ``ConfigDict`` is still
        inherited (the base IS ``InputType``), so the type keeps the input
        engine's alias/camelCase config — only the registration side effect is
        skipped.
        """
        NativeObjectType.__init_subclass__.__func__(cls, **kwargs)

    @classmethod
    def __init_subclass_with_meta__(
        cls,
        model: type[Model] | None = None,
        container: Any = None,
        registry: Registry | None = None,
        skip_registry: bool = False,
        connection: Any = None,
        use_connection: Any = None,
        only_fields: tuple[str, ...] = (),
        exclude_fields: tuple[str, ...] = (),
        include_fields: tuple[str, ...] = (),
        filter_fields: Any = None,
        input_for: str = "create",
        nested_fields: Any = (),
        nested_parent_model: type[Model] | None = None,
        **options,
    ) -> None:
        """Initialize the subclass with meta options for a Django input type.

        Args:
            model: Django model this input type represents.
            container: Container class used to hold input values; one is
                generated when None. Retained for graphene-path compatibility
                until Phase 7 removes the graphene path entirely.
            registry: Registry to register this type in; defaults to the
                global registry.
            skip_registry: When True, do not register this type.
            connection: Connection type associated with this input type.
            use_connection: Whether to use a connection for this input type.
            only_fields: Model field names to include exclusively.
            exclude_fields: Model field names to exclude.
            include_fields: Extra model field names to force-include regardless
                of only_fields / exclude_fields filters.
            filter_fields: Field names usable for filtering.
            input_for: Operation the input is built for ("create", "update"
                or "delete").
            nested_fields: Nested fields to build into the input type.
            nested_parent_model: When this input is a NESTED CHILD of another
                model, the nesting parent model; its back-reference FK on this
                child is rendered optional on the input surface (the FK is
                injected at save time by the nested mixin).
            **options: Extra options forwarded to the parent implementation.
        """
        _check_unknown_options(cls.__name__, options)

        assert is_valid_django_model(model), (
            'You need to pass a valid Django Model in {}.Meta, received "{}".'
        ).format(cls.__name__, model)

        if not registry:
            registry = get_global_registry()

        assert isinstance(registry, Registry), (
            "The attribute registry in {} needs to be an instance of "
            'Registry, received "{}".'
        ).format(cls.__name__, registry)

        assert input_for.lower() in ("create", "delete", "update"), (
            'You need to pass a valid input_for value in {}.Meta, received "{}".'
        ).format(cls.__name__, input_for)

        input_for = input_for.lower()

        # ----------------------------------------------------------------
        # NATIVE PATH (S6c: UNCONDITIONAL). DjangoInputObjectType is parented on
        # ``native.base.InputType``. Resolvers receive a VALIDATED Pydantic model (built from
        # ``build_model_schema(model)`` and exposed as ``graphql_input_type``),
        # never a container — so no ``_meta.container`` is needed.
        #
        # ``input_for == "delete"`` compiles NO input object type: a delete
        # mutation exposes an ``id: ID!`` argument (built by DjangoModelType /
        # DjangoModelMutation), not an input object. ``graphql_input_type`` stays
        # ``None`` in that case.
        # ----------------------------------------------------------------
        graphql_input_type = None
        if input_for != "delete":
            from django_graphex.core.fields import build_model_schema
            from django_graphex.core.input_compiler import compile_input_type

            pydantic_model = build_model_schema(
                model,
                partial=(input_for == "update"),
            )
            # Resolve the GraphQL type name: prefer explicit Meta.name passed
            # via **options, then fall back to the class name.
            gql_type_name = options.get("name") or cls.__name__
            # Resolve ``Meta.nested_fields`` into native nested object-input
            # specs (relation introspection + child input type lookup). Empty
            # for a plain input -> identical SDL to before this fix.
            native_nested = _resolve_native_nested_input_fields(
                model, registry, input_for, nested_fields
            )
            # Resolve Django relations into ``ID`` / ``[ID]`` input specs
            # (forward FK / O2O / M2M / reverse-FK), mirroring graphene's
            # non-nested relation converters. A relation also named in
            # ``nested_fields`` is rendered as the nested OBJECT input instead.
            native_relations = _resolve_native_relation_input_fields(
                model, input_for, nested_parent_model=nested_parent_model
            )
            # Resolve choices fields into shared native ``GraphQLEnumType`` input
            # specs (S-input-5): the choices INPUT surface becomes the SAME
            # canonical enum the OUTPUT + FILTER-INPUT paths use, instead of the
            # ``String`` fallback. Graphene-free; output/input symmetric.
            native_choices = _resolve_native_choices_input_fields(
                model, registry, input_for
            )
            graphql_input_type = compile_input_type(
                pydantic_model,
                name=gql_type_name,
                description=getattr(cls, "__doc__", None),
                nested_fields=native_nested,
                relation_fields=native_relations,
                choices_fields=native_choices,
                # issue #65: honor Meta only/include/exclude on the input wire type.
                only_fields=only_fields or None,
                exclude_fields=exclude_fields or None,
                include_fields=include_fields or None,
            )

        # The native compiler reads ``_meta.graphql_input_type``; the
        # ``input_fields`` dict is kept on ``_meta`` for runtime metadata readers
        # (registry / converter child lookups) that inspect declared input fields.
        django_input_fields = _yank_fields(
            construct_fields(
                model,
                registry,
                only_fields,
                include_fields,
                exclude_fields,
                input_for,
                nested_fields,
            ),
            _as=NativeMountedField,
            sort=False,
        )
        for base in reversed(cls.__mro__):
            django_input_fields.update(
                _yank_fields(base.__dict__, _as=NativeMountedField)
            )

        _meta = NativeObjectTypeOptions(cls)
        _meta.model = model
        _meta.registry = registry
        _meta.filter_fields = filter_fields
        _meta.fields = django_input_fields
        _meta.input_fields = django_input_fields
        _meta.connection = connection
        _meta.input_for = input_for
        # Native extension: compiled GraphQLInputObjectType (None for delete).
        _meta.graphql_input_type = graphql_input_type

        super().__init_subclass_with_meta__(
            _meta=_meta,
            **options,
        )

        if not skip_registry:
            registry.register(cls, for_input=input_for)

    @classmethod
    def get_type(cls) -> type[DjangoInputObjectType]:
        """Return the type when the unmounted type is mounted.

        This method is called when the unmounted type (an "InputObjectType"
        instance) is mounted as a "Field", "InputField" or "Argument".

        Returns:
            This input object type class.
        """
        return cls


class DjangoListObjectType(NativeObjectType):
    """A GraphQL type for paginated Django model lists.

    Wraps a node "DjangoObjectType" as its "_meta.baseType" and exposes a
    "results" list (its name configurable via "results_field_name") plus a
    "totalCount", optionally applying pagination and filter configuration.
    """

    class Meta:
        """Meta configuration for DjangoListObjectType.

        Marks the base class as abstract so it is never itself registered or
        compiled; only concrete list subclasses are.
        """

        abstract = True

    @classmethod
    def __init_subclass_with_meta__(
        cls,
        model: type[Model] | None = None,
        registry: Registry | None = None,
        results_field_name: str | None = None,
        pagination: Any = None,
        only_fields: tuple[str, ...] = (),
        exclude_fields: tuple[str, ...] = (),
        include_fields: tuple[str, ...] = (),
        filter_fields: Any = None,
        queryset: QuerySet | None = None,
        max_depth: int | None = None,
        complexity: int | None = None,
        **options,
    ) -> None:
        """Initialize the subclass with meta options for a Django list type.

        Args:
            model: Django model this list type represents.
            registry: Registry to register this type in; defaults to the
                global registry.
            results_field_name: Name of the field holding the result list;
                defaults to "results".
            pagination: Pagination instance to apply to the list.
            only_fields: Model field names to include exclusively.
            exclude_fields: Model field names to exclude.
            include_fields: Extra model field names to force-include regardless
                of only_fields / exclude_fields filters.
            filter_fields: Field names usable for filtering.
            queryset: Base queryset used to build the list type.
            max_depth: Max nested-object depth allowed below this list type,
                enforced by "DepthLimitValidationRule"; "None" means no limit.
            complexity: Cost weight of a field returning this list type, used by
                "CostLimitValidationRule"; "None" means the default weight (1).
            **options: Extra options forwarded to the parent implementation.
        """
        _check_unknown_options(cls.__name__, options)

        assert is_valid_django_model(model), (
            'You need to pass a valid Django Model in {}.Meta, received "{}".'
        ).format(cls.__name__, model)

        if not registry:
            registry = get_global_registry()

        assert isinstance(queryset, QuerySet) or queryset is None, (
            "The attribute queryset in {} needs to be an instance of "
            'Django model queryset, received "{}".'
        ).format(cls.__name__, queryset)

        results_field_name = results_field_name or "results"

        baseType = registry.get_type_for_model(model)

        if not baseType:
            factory_kwargs = {
                "model": model,
                "only_fields": only_fields,
                "include_fields": include_fields,
                "exclude_fields": exclude_fields,
                "filter_fields": filter_fields,
                "pagination": pagination,
                "queryset": queryset,
                "registry": registry,
                "skip_registry": False,
            }
            baseType = factory_type("output", DjangoObjectType, **factory_kwargs)

        filter_fields = filter_fields or baseType._meta.filter_fields

        # ----------------------------------------------------------------
        # S-ROOTS-e / S-page-7: select the PAGINATOR INSTANCE here. The native
        # list container is thunk-built on ``_meta.graphql_output_type`` (the
        # native block below) from ``paginator.to_graphql_fields(native=True)`` +
        # ``NativePaginationField`` + ``get_native_page_info_field``; the native
        # compiler reads ``_meta.graphql_output_type`` — NEVER ``_meta.fields``.
        # S-page-7 removed the dead graphene branch that called the graphene
        # ``get_pagination_field``/``get_page_info_field`` (it only allocated dead
        # graphene ``GenericPaginationField``/``CursorPageInfo`` objects that never
        # reached the schema), so ``_meta.fields`` is now an empty native-only
        # container (verified SDL byte-identical).
        # ----------------------------------------------------------------
        paginator = None
        if pagination:
            paginator = pagination
        else:
            global_paginator = graphql_api_settings.DEFAULT_PAGINATION_CLASS
            if global_paginator:
                assert issubclass(global_paginator, BaseDjangoGraphqlPagination), (
                    'You need to pass a valid DjangoGraphqlPagination class in {}.Meta, received "{}".'
                ).format(cls.__name__, global_paginator)

                paginator = global_paginator()

        _meta = NativeObjectTypeOptions(cls)
        _meta.model = model
        _meta.registry = registry
        _meta.queryset = queryset
        _meta.baseType = baseType
        _meta.results_field_name = results_field_name
        _meta.filter_fields = filter_fields
        _meta.exclude_fields = exclude_fields
        _meta.only_fields = only_fields
        _meta.pagination = pagination
        # item-b (B6): store the RESOLVED paginator (``Meta.pagination`` OR the
        # ``DEFAULT_PAGINATION_CLASS`` fallback) so a FORKED list container
        # (registry_compiler ``_fork_output_class``) builds its results-field
        # thunk with the SAME paginator the class-def used. Reading the raw
        # ``_meta.pagination`` (often ``None`` when only the global default
        # applies) would drop the pagination resolver on the fork — the
        # container's renamed results field (e.g. ``items``) would then fall to
        # the default attribute resolver and return ``None``.
        _meta.paginator = paginator
        _meta.max_depth = max_depth
        _meta.complexity = complexity

        # The pagination container is NATIVE-ONLY. ``_meta.fields`` is unused by
        # the native compiler (which reads ``_meta.graphql_output_type``,
        # thunk-built below from ``to_graphql_fields(native=True)`` +
        # ``NativePaginationField`` + ``get_native_page_info_field``), so leave it
        # empty.
        _meta.fields = OrderedDict()

        super().__init_subclass_with_meta__(_meta=_meta, **options)

        # Register as the model's canonical `list` type so nested relations can
        # reuse it (honoring this type's pagination/filter config). Last one wins.
        registry.register_list_type(model, cls)

        # ----------------------------------------------------------------
        # NATIVE PATH: create EXACTLY ONE GraphQLObjectType for the list
        # container (results + totalCount), identity-stable, following the
        # same single-instance/shared-registry/thunk pattern as DjangoObjectType
        # above (types.py ~289-395).
        #
        # The results field's element type is resolved LAZILY via the SHARED
        # GLOBAL output registry so it always yields the node type's single
        # canonical GraphQLObjectType (identity-stable, not a GraphQLString
        # fallback), regardless of definition order.
        #
        # compile_all_outputs() POPULATES/validates the existing instance via
        # the same Phase-2 thunk-eval + Phase-3 gdx assertion already in place
        # for DjangoObjectType entries — no second instance is ever created.
        #
        # S6b: DjangoListObjectType is NATIVE-ONLY (parented on
        # ``native.base.ObjectType``). The native compile is UNCONDITIONAL.
        # ----------------------------------------------------------------
        if model is not None:
            from graphql import GraphQLObjectType

            from django_graphex.core.base import (
                _gdx_output_registry,
                _GdxOutputEntry,
                is_forking,
            )
            from django_graphex.core.bridge import GdxPayload
            from django_graphex.core.ir import GdxMeta

            # Registry-scoped output registry: the container's ``results`` element
            # type resolves the NODE from the class's OWN registry companion. For
            # the GLOBAL registry this IS ``get_shared_output_registry()`` (the
            # container's element node lives in the shared singleton -> byte-
            # identical). For a LOCAL ``Meta.registry`` the node lives in that
            # registry's own companion, so the list's ``results`` resolves the
            # sibling node WITHOUT reaching into the global namespace.
            _shared_registry = registry.output_registry()

            # Resolve the GraphQL list-type NAME the SAME way graphene does:
            # ``Meta.name`` (forwarded via **options) wins, else the class name.
            # Auto-generated list types (factory_type "list") set ``Meta.name`` to
            # ``<Model>ListType`` (e.g. ``TagListType``); the class name is the
            # opaque ``GenericListType``. Honoring ``Meta.name`` makes the native
            # auto-derived to-many CONTAINER name byte-identical to graphene's.
            _list_gql_name = options.get("name") or cls.__name__

            # item-b (B5): built via the SHARED ``_make_list_fields_thunk_for``
            # factory so the class-def (DEFAULT pair) and ``compile_outputs_into``
            # (FORKED pair) produce IDENTICAL container thunks. The class-def path
            # binds the SHARED global output registry (byte-identical); a forked
            # pair binds its own ``output`` member so the container's ``results``
            # node is THIS schema's forked node.
            _make_list_fields_thunk = _make_list_fields_thunk_for(
                model,
                results_field_name,
                _shared_registry,
                paginator,
            )

            _list_gdx_meta = GdxMeta(
                name=_list_gql_name,
                model=model,
                results_field_name=results_field_name,
                max_depth=max_depth,
                complexity=complexity,
                # DEFECT A: carry the source DjangoListObjectType subclass so the
                # optimizer's bridge (_gdx_graphene_type) resolves the wrapper's
                # source class on nested list containers, mirroring the root
                # compiler (schema_compiler.py:854).
                graphene_type=cls,
            )
            _list_gdx_payload = GdxPayload(_list_gdx_meta)

            _list_gql_type = GraphQLObjectType(
                name=_list_gql_name,
                fields=_make_list_fields_thunk,
                extensions={"gdx": _list_gdx_payload},
            )

            # Register entry so compile_all_outputs() validates (thunk-eval +
            # gdx assertion) this container alongside DjangoObjectType entries.
            # item-b (B5): skip the GLOBAL append during a FORKED build (a
            # pair-scoped auto-created container must not leak into the global
            # app-ready compile); the container is forked into its pair instead.
            _list_entry = _GdxOutputEntry(
                cls=cls,
                gql_name=_list_gql_name,
                model=model,
                only_fields=None,
                exclude_fields=None,
                max_depth=max_depth,
                complexity=complexity,
            )
            if not is_forking():
                _gdx_output_registry.append(_list_entry)

            # S6b: ``_meta`` is now a MUTABLE ``NativeObjectTypeOptions`` (no
            # freeze), so this is a PLAIN assignment — matching the DjangoObjectType
            # pattern. The old ``object.__setattr__`` freeze-bypass workaround is gone.
            _meta.graphql_output_type = _list_gql_type

    @classmethod
    def RetrieveField(cls, *args: Any, **kwargs: Any) -> DjangoObjectField:
        """Create a field for retrieving a single object.

        Args:
            *args: Positional arguments (currently unused).
            **kwargs: Keyword arguments forwarded to the field.

        Returns:
            A field that resolves a single object of the base type.
        """
        return DjangoObjectField(cls._meta.baseType, **kwargs)

    @classmethod
    def BaseType(cls) -> type[DjangoObjectType]:
        """Return the base GraphQL type for this list type.

        Returns:
            The base object type wrapped by this list type.
        """
        return cls._meta.baseType


def get_or_create_list_object_type(
    model: type[Model], registry: Registry | None = None
) -> type[DjangoListObjectType]:
    """Return the model's registered list type, creating one if needed.

    Reuses a user-defined or model list type (so its "pagination" and
    "filter_fields" are honored when the model appears nested under another
    model). Falls back to an auto-generated list type using the default
    paginator ("DEFAULT_PAGINATION_CLASS" or "LimitOffsetGraphqlPagination").

    Args:
        model: Django model whose list type is requested.
        registry: Registry to look up and register in; defaults to the global
            registry.

    Returns:
        The existing or newly created "DjangoListObjectType" subclass.
    """
    if registry is None:
        registry = get_global_registry()

    existing = registry.get_list_type_for_model(model)
    if existing is not None:
        return existing

    paginator_cls = graphql_api_settings.DEFAULT_PAGINATION_CLASS
    if paginator_cls is not None:
        pagination = paginator_cls()
    else:
        from .paginations.pagination import LimitOffsetGraphqlPagination

        pagination = LimitOffsetGraphqlPagination()

    # Inherit the node type's filter config so nested lists stay filterable.
    node = registry.get_type_for_model(model)
    filter_fields = getattr(node._meta, "filter_fields", None) if node else None

    # factory_type builds a DjangoListObjectType subclass which self-registers.
    return factory_type(
        "list",
        DjangoListObjectType,
        model=model,
        pagination=pagination,
        registry=registry,
        filter_fields=filter_fields,
    )


class DjangoModelType(NestedFieldsMixin, NativeObjectType):
    """A batteries-included CRUD, list, and subscription type for a Django model.

    Bundles the query fields ("RetrieveField"/"ListField"), mutation fields
    ("CreateField"/"UpdateField"/"DeleteField"), and an optional subscription in
    a single declaration. Each operation runs through the permission and
    "get_queryset"/"filter_queryset" hooks before touching the database, and
    mutation results are returned as this type with its "ok" / "errors" payload
    fields.
    """

    # S-ROOTS-c: ``ok`` / ``errors`` are NATIVE ``field()`` descriptors (not
    # graphene ``Boolean()`` / ``List(ErrorType)``). The SDL is byte-identical
    # (``ok: Boolean``, ``errors: [ErrorType]``). ``errors`` uses ``NativeList``
    # because ``ErrorType`` is a native plain ``ObjectType`` whose graphql-core
    # type compiles lazily — ``GraphQLList(ErrorType)`` cannot be built eagerly.
    ok = native_field(
        GraphQLBoolean,
        description="Boolean field that return mutation result request.",
    )
    errors = native_field(
        NativeList(ErrorType), description="Errors list for the field"
    )

    #: Permission classes checked per action before each CRUD operation. Empty
    #: (the default) means no checks. See "django_graphex.permissions".
    #: ``ClassVar`` is REQUIRED post-S6c: the native base uses Pydantic's
    #: ``ModelMetaclass``, which raises ``PydanticUserError`` on a plain
    #: non-annotated class attribute (it cannot tell it apart from a model
    #: field). ``ClassVar`` declares it as type-level config, not a GraphQL/model
    #: field.
    permission_classes: ClassVar[tuple[Any, ...]] = ()

    #: Opt-in override (P0) for the permissions the CRUD fields this class
    #: generates require; it REPLACES the composite-table default on each of
    #: them. Read at field-build time whether or not it is declared here, but
    #: declared for the same reason ``permission_classes`` is: without a base
    #: ``ClassVar``, the plain assignment the guides spell out raises
    #: ``PydanticUserError`` at class-definition time.
    required_perms: ClassVar[Optional[Sequence[str]]] = None

    class Meta:
        """Meta configuration for DjangoModelType.

        Marks the base class as abstract so it is never itself registered or
        compiled; only concrete model subclasses are.
        """

        abstract = True

    @classmethod
    def __init_subclass_with_meta__(
        cls,
        model: Any = None,
        pydantic_model: Any = None,
        queryset: QuerySet | None = None,
        only_fields: tuple[str, ...] = (),
        include_fields: tuple[str, ...] = (),
        exclude_fields: tuple[str, ...] = (),
        pagination: Any = None,
        input_field_name: str | None = None,
        output_field_name: str | None = None,
        results_field_name: str | None = None,
        nested_fields: Any = (),
        filter_fields: Any = None,
        description: str = "",
        stream: str | None = None,
        payload_mode: str | None = None,
        subscription_index_fields: tuple[str, ...] | list[str] | None = None,
        max_depth: int | None = None,
        complexity: int | None = None,
        model_operations: Any = MODEL_TYPE_OPERATIONS,
        **options,
    ) -> None:
        """Initialize the subclass with meta options for a model type.

        Args:
            queryset: Base queryset used for retrieve and list operations.
            only_fields: Model field names to include exclusively.
            include_fields: Extra model field names to include.
            exclude_fields: Model field names to exclude.
            pagination: Pagination instance to apply to list results.
            input_field_name: Name of the mutation input argument.
            output_field_name: Name of the field holding the mutation output.
            results_field_name: Name of the field holding list results.
            nested_fields: Nested fields to build into the input types.
            filter_fields: Field names usable for filtering.
            description: GraphQL description for this type.
            stream: Subscription stream name; required to expose a subscription.
            payload_mode: Force "full" or "id_only" subscription payloads, or
                "None" to inherit the global setting.
            subscription_index_fields: Optional model field names routing
                notifications to value-scoped groups (only matching subscribers
                are woken). Must be a subset of what "subscription_scope" returns.
            max_depth: Max nested-object depth allowed below this type's output
                type, enforced by "DepthLimitValidationRule"; "None" = no limit.
            complexity: Cost weight of a field returning this type's output type,
                used by "CostLimitValidationRule"; "None" = default weight (1).
            model_operations: The operations this type serves; any subset of
                ("create", "update", "delete", "list", "retrieve"). The default
                is ALL of them, so a type that declares nothing behaves exactly
                as it did before the option existed. Operations left out have
                their "*Field()" builder raise, and -- the reason the option is
                here -- the type stops counting as a host for them when a PARENT
                nests this model: a type declared ("list", "retrieve") is a READ
                host, so its "Meta.queryset" and its "only_fields" no longer
                reach the nested write path.
            **options: Extra options forwarded to the parent implementation.

        Raises:
            ImproperlyConfigured: If "Meta.model" is not provided, if any
                unknown Meta option is supplied, or if "model_operations"
                contains an unknown operation.
        """
        # HARD rename guard (v2.0): the legacy ``Meta.serialize_data`` key is
        # caught in ``**options`` — fail loudly with the new spelling before the
        # generic unknown-option check.
        if "serialize_data" in options:
            raise ImproperlyConfigured(
                "{}.Meta.serialize_data was renamed to payload_mode in v2.0 "
                '(use "full" or "id_only").'.format(cls.__name__)
            )
        if payload_mode not in (None, "full", "id_only"):
            raise ImproperlyConfigured(
                '{}.Meta.payload_mode must be "full", "id_only" or None, '
                'received "{}".'.format(cls.__name__, payload_mode)
            )
        _check_unknown_options(cls.__name__, options)

        # Collect @filter_field-decorated methods and validate reserved names.
        custom_filters = collect_custom_filters(cls)
        for arg_name, _fn, _meta_ff in custom_filters:
            if arg_name in RESERVED_FILTER_ARGS:
                raise ImproperlyConfigured(
                    "{cls}: @filter_field method name {name!r} collides with a "
                    "reserved pagination / ordering argument. Choose a different "
                    "name. Reserved names: {reserved}.".format(
                        cls=cls.__name__,
                        name=arg_name,
                        reserved=sorted(RESERVED_FILTER_ARGS),
                    )
                )
        cls._dgx_custom_filters = custom_filters

        pydantic_model = build_validator_model(cls, model, pydantic_model)
        backend = resolve_backend(model, pydantic_model=pydantic_model)
        model = backend.get_model()

        description = description or f"DjangoModelType for {model.__name__} model"

        input_field_name = input_field_name or f"new_{model._meta.model_name}"
        output_field_name = output_field_name or model._meta.model_name

        input_class = getattr(cls, "Arguments", None)
        if not input_class:
            input_class = getattr(cls, "Input", None)
            if input_class:
                warnings.warn(
                    (
                        "Please use {name}.Arguments instead of {name}.Input."
                        "Input is now only used in ClientMutationID.\nRead more: "
                        "https://github.com/graphql-python/graphene/blob/2.0/UPGRADE-v2.0.md#mutation-input"
                    ).format(name=cls.__name__),
                    DeprecationWarning,
                    stacklevel=2,
                )
        if input_class:
            arguments = _props(input_class)
        else:
            arguments = {}

        registry = get_global_registry()

        model_operations = tuple(op.lower() for op in model_operations)
        unknown = set(model_operations) - set(MODEL_TYPE_OPERATIONS)
        if unknown:
            raise ImproperlyConfigured(
                "Meta.model_operations of {} contains unknown operation(s) {}; "
                "only {} are valid.".format(
                    cls.__name__,
                    sorted(unknown),
                    ", ".join('"{}"'.format(op) for op in MODEL_TYPE_OPERATIONS),
                )
            )

        # Custom graphene fields declared on this DjangoModelType -- or on
        # any of its bases up to (but excluding) DjangoModelType, e.g. an
        # abstract mixin -- are collected and added to the generated output type,
        # so a separate DjangoObjectType is not required just to expose extra
        # fields. Bases are walked first so a subclass can override an inherited
        # field; the base DjangoModelType is skipped because its `ok` /
        # `errors` are wrapper fields, not output fields. The collected fields are
        # later kept off the wrapper type itself (see below).
        extra_fields: dict = {}
        for klass in reversed(cls.__mro__):
            if issubclass(klass, DjangoModelType) and klass is not DjangoModelType:
                extra_fields.update(
                    _yank_fields(dict(vars(klass)), _as=NativeMountedField)
                )

        # Forward each custom field's `resolve_<name>` method (most-derived wins)
        # onto the generated output type so the field resolves through it.
        extra_resolvers: dict = {}
        for klass in reversed(cls.__mro__):
            if issubclass(klass, DjangoModelType) and klass is not DjangoModelType:
                for attr_name, attr in vars(klass).items():
                    if (
                        attr_name.startswith("resolve_")
                        and attr_name[len("resolve_") :] in extra_fields
                        and callable(attr)
                    ):
                        extra_resolvers[attr_name] = attr

        factory_kwargs = {
            "model": model,
            "only_fields": only_fields,
            "include_fields": include_fields,
            "exclude_fields": exclude_fields,
            "filter_fields": filter_fields,
            "pagination": pagination,
            "queryset": queryset,
            "nested_fields": nested_fields,
            "registry": registry,
            "skip_registry": False,
            "results_field_name": results_field_name,
            "extra_fields": extra_fields,
            "extra_resolvers": extra_resolvers,
            "max_depth": max_depth,
            "complexity": complexity,
        }

        output_type = registry.get_type_for_model(model)

        if not output_type:
            output_type = factory_type("output", DjangoObjectType, **factory_kwargs)
        else:
            # SECURITY: the reused output type was built from ITS OWN Meta, so a
            # projection declared here would be dropped and the column it was
            # meant to hide would stay queryable. "exclude_fields" is documented
            # as THE way to keep a sensitive column out (docs/api/types.md), so
            # this fails the schema build instead of warning: a warning is
            # filterable and would leave the leak live in production. Only the
            # already-leaking configuration is affected -- move the projection to
            # the registered type, or drop the option.
            dropped = [
                option
                for option, value in (
                    ("only_fields", only_fields),
                    ("include_fields", include_fields),
                    ("exclude_fields", exclude_fields),
                )
                if value
            ]
            if dropped:
                raise ImproperlyConfigured(
                    "{name}.Meta.{options} cannot be honored: the output type for "
                    "{model} is reused from {registered}, which was built from its "
                    "own Meta, so the projection would be silently dropped and any "
                    "field it hides would stay exposed. Declare {options} on "
                    "{registered} instead, or remove the option.".format(
                        name=cls.__name__,
                        options="/".join(dropped),
                        model=model.__name__,
                        registered=output_type.__name__,
                    )
                )
            if extra_fields:
                warnings.warn(
                    "{name}: custom fields declared on the type are ignored because a "
                    "DjangoObjectType is already registered for {model}; declare them "
                    "on that DjangoObjectType instead.".format(
                        name=cls.__name__, model=model.__name__
                    ),
                    stacklevel=2,
                )

        # The container MUST NOT be minted as "<Model>ListType": that is exactly
        # the name the docs teach users to give their own
        # "DjangoListObjectType", so declaring both put two distinct classes
        # with one name into the same schema and graphql-core refused to build
        # it ("Schema must contain uniquely named types"). Reusing the
        # registered container instead was rejected: a "DjangoModelType" carries
        # its OWN "pagination" / "results_field_name" / projection, and a
        # user-declared container built from its own Meta would silently discard
        # them. So the generated container takes the "Generic" name-space this
        # type already mints its output ("<Model>GenericType") and input
        # ("<Model>CreateGenericType") into, which no user convention claims.
        from ._strconv import to_camel_case

        output_list_type = factory_type(
            "list",
            DjangoListObjectType,
            **{
                **factory_kwargs,
                "name": to_camel_case("{}_List_Generic_Type".format(model.__name__)),
            },
        )

        django_fields = OrderedDict(
            {output_field_name: NativeMountedField(output_type)}
        )

        global_arguments = {}
        for operation in ("create", "delete", "update"):
            # A declared READ host builds no write argument at all -- and, more
            # to the point, registers no input into the shared "(model,
            # operation)" slot, so the project's real write host still owns it.
            if operation not in model_operations:
                continue
            global_arguments.update({operation: OrderedDict()})

            if operation != "delete":
                nested_map = nested_fields if isinstance(nested_fields, dict) else {}
                if nested_map:
                    # Mirror of the DjangoModelMutation gate (see mutation.py):
                    # a nested ``DjangoModelType`` builds a DISTINCT input with
                    # ``skip_registry=True`` so the generic ``(model, operation)``
                    # slot stays pristine for plain hosts and the converter's
                    # child lookups. The helper lives in mutation.py; importing
                    # it lazily here avoids the module-load circular import
                    # (mutation.py imports this module).
                    from .mutation import _nested_input_name

                    input_type = factory_type(
                        "input",
                        DjangoInputObjectType,
                        operation,
                        **{
                            **factory_kwargs,
                            "name": _nested_input_name(
                                model,
                                operation,
                                nested_map,
                                only_fields,
                                exclude_fields,
                                include_fields,
                            ),
                            "skip_registry": True,
                        },
                    )
                else:
                    from .mutation import generic_input_type

                    input_type = generic_input_type(
                        registry, model, operation, factory_kwargs
                    )

                # S6c: DjangoModelType is NATIVE-ONLY (parented on
                # ``native.base.ObjectType``). The input argument is wrapped in a
                # graphql-core ``GraphQLArgument`` UNCONDITIONALLY.
                from graphql import GraphQLArgument as _GQLArg
                from graphql import GraphQLNonNull as _GQLNonNull

                _gql_input_type = input_type._meta.graphql_input_type
                global_arguments[operation].update(
                    {
                        input_field_name: _GQLArg(
                            _GQLNonNull(_gql_input_type),
                            out_name=input_field_name,
                        )
                    }
                )
            else:
                # S6c: native-only ``id`` argument (graphene else-branch removed).
                from graphql import GraphQLArgument as _GQLArgDT
                from graphql import GraphQLID as _GraphQLIDDT
                from graphql import GraphQLNonNull as _GQLNonNullDT

                global_arguments[operation].update(
                    {
                        "id": _GQLArgDT(
                            _GQLNonNullDT(_GraphQLIDDT),
                            description="Django object unique identification field",
                            out_name="id",
                        )
                    }
                )
            global_arguments[operation].update(arguments)

        _meta = NativeObjectTypeOptions(cls)
        _meta.mutation_output = cls
        _meta.arguments = global_arguments
        _meta.fields = django_fields
        _meta.output_type = output_type
        _meta.output_list_type = output_list_type
        _meta.model = model
        _meta.registry = registry
        # `is not None` (not `or`): a QuerySet's truthiness would execute it here.
        _meta.queryset = queryset if queryset is not None else model._default_manager
        _meta.backend = backend
        _meta.input_field_name = input_field_name
        _meta.output_field_name = output_field_name
        _meta.nested_fields = nested_fields
        _meta.stream = stream
        _meta.payload_mode = payload_mode
        _meta.subscription_index_fields = tuple(subscription_index_fields or ())
        # Stored so ``subscription_type()`` can forward the SAME projection to the
        # generated ``Subscription`` (docs/api/types.md documents
        # ``exclude_fields`` as THE way to keep a sensitive column out).
        _meta.only_fields = tuple(only_fields or ())
        _meta.exclude_fields = tuple(exclude_fields or ())
        _meta.max_depth = max_depth
        _meta.complexity = complexity
        # Read by "nested.hosts_serving" as well as by this type's own field
        # builders: a project that declares itself a READ host takes its
        # "Meta.queryset" and its "only_fields" out of the nested WRITE path.
        _meta.model_operations = model_operations

        super().__init_subclass_with_meta__(
            _meta=_meta, description=description, **options
        )

        # Declared here, not on demand: a child writable ONLY through its parent
        # never mounts a field of its own, so any registry filled by field
        # construction would be EMPTY for exactly the configuration the nested
        # gate has to cover, and would fail open.
        register_nested_host(model, cls, registry)

        # The custom fields belong on the generated output type, not on this
        # wrapper. graphene's ObjectType base re-collects them from the class
        # body (and bases) into `_meta.fields`, so drop them here.
        for field_name in extra_fields:
            cls._meta.fields.pop(field_name, None)

    @classmethod
    def list_object_type(cls) -> type[DjangoListObjectType]:
        """Return the list object type for this model type.

        Returns:
            The configured list object type.
        """
        return cls._meta.output_list_type

    @classmethod
    def object_type(cls) -> type[DjangoObjectType]:
        """Return the output object type for this model type.

        Returns:
            The configured output object type.
        """
        return cls._meta.output_type

    @classmethod
    def get_errors(cls, errors: list) -> DjangoModelType:
        """Create an error response object from validation errors.

        Args:
            errors: List of error entries describing the failure.

        Returns:
            An instance of this type flagged as not "ok" carrying the errors.
        """
        errors_dict = {cls._meta.output_field_name: None, "ok": False, "errors": errors}

        return cls(**errors_dict)

    @classmethod
    def perform_mutate(cls, obj: Model, info: ResolveInfo) -> DjangoModelType:
        """Create a successful mutation response with the given object.

        The object is re-read through "get_queryset" so annotated and related
        fields resolve in the response; it falls back to "obj" when the re-read
        yields nothing (e.g. "filter_queryset" excludes it), so a mutation
        never returns null for an object it just wrote.

        When the mutation selection set contains a sub-field for the output
        object (named by "Meta.output_field_name"), the re-read queryset is
        passed through the query optimizer using that sub-selection.  This
        eliminates N+1 queries for to-one relations (e.g. ForeignKey,
        OneToOneField) that are selected in the mutation response.

        Args:
            obj: Model instance produced by the mutation.
            info: GraphQL resolve info for the current request.

        Returns:
            An instance of this type flagged as "ok" carrying the object.
        """
        base_qs = cls.get_queryset(
            cls._meta.model._default_manager, info, obj=obj
        ).filter(pk=obj.pk)

        # Locate the sub-field node for the output object within the mutation
        # selection set (e.g. "post" inside "{ ok post { title author { name } } }").
        # If found, optimise the re-read queryset using that sub-selection so
        # to-one relations are joined via select_related instead of lazy-loading.
        output_field_name = cls._meta.output_field_name
        sub_field_node = None
        try:
            root_node = info.field_nodes[0] if info.field_nodes else None
            if root_node is not None and getattr(root_node, "selection_set", None):
                for sel in root_node.selection_set.selections:
                    sel_name = getattr(getattr(sel, "name", None), "value", None)
                    if sel_name == output_field_name:
                        sub_field_node = sel
                        break
        except Exception:  # pragma: no cover — defensive; never raise on best-effort
            sub_field_node = None

        if sub_field_node is not None and getattr(
            sub_field_node, "selection_set", None
        ):
            from types import SimpleNamespace

            sub_info = SimpleNamespace(
                field_nodes=[sub_field_node],
                fragments=getattr(info, "fragments", {}),
                variable_values=getattr(info, "variable_values", {}) or {},
                return_type=None,
                schema=getattr(info, "schema", None),
                context=getattr(info, "context", None),
            )
            try:
                base_qs = _apply_optimizations(
                    base_qs,
                    cls._meta.model,
                    sub_info,  # type: ignore[arg-type]
                    {},
                    False,
                )
            except Exception:  # pragma: no cover — degrade gracefully  # nosec B110
                # Best-effort optimization: an optimizer failure must never
                # break the mutation; the unoptimized re-read is still correct.
                pass

        refreshed = base_qs.first()
        resp = {
            output_field_name: refreshed or obj,
            "ok": True,
            "errors": None,
        }

        return cls(**resp)

    @classmethod
    def get_queryset(
        cls, manager: Manager | QuerySet, info: ResolveInfo, **kwargs: Any
    ) -> QuerySet:
        """Return the base queryset for retrieve, list and mutation responses.

        Override to customize the base queryset (e.g. "select_related" or
        "annotate"). "info.context" is the request. The default uses
        "Meta.queryset" (else the field's manager) and applies
        "filter_queryset".

        Args:
            manager: Default manager or queryset to fall back to.
            info: GraphQL resolve info for the current request.
            **kwargs: Extra arguments forwarded to "filter_queryset".

        Returns:
            The scoped queryset to use.
        """
        qs = cls._meta.queryset if cls._meta.queryset is not None else manager
        if isinstance(qs, Manager):
            qs = qs.all()
        return cls.filter_queryset(qs, info, **kwargs)

    @classmethod
    def filter_queryset(
        cls, qs: QuerySet, info: ResolveInfo, **kwargs: Any
    ) -> QuerySet:
        """Scope the queryset per request.

        This is a hook meant to be overridden. The default returns "qs"
        unchanged.

        Args:
            qs: Queryset to scope.
            info: GraphQL resolve info for the current request.
            **kwargs: Extra arguments available for scoping.

        Returns:
            The (optionally) scoped queryset.
        """
        return qs

    @classmethod
    def subscription_scope(cls, info: ResolveInfo, **kwargs: Any) -> dict | None:
        """Return server-forced notification filters for a subscriber.

        Hook meant to be overridden when the subscription must be row-scoped
        (e.g. '{"owner": info.context.user.pk}'). It is evaluated at subscribe
        time (the user is available) and enforced per event at delivery, in
        memory when possible, so the client can neither widen nor drop it.

        Unlike "filter_queryset" (an opaque queryset transform used by the
        query/list resolvers), this returns a plain filter mapping so it can be
        applied to a single changed instance without a per-event query. The
        default returns None (no scoping).

        Args:
            info: GraphQL resolve info for the subscribe request.
            **kwargs: The subscription arguments.

        Returns:
            The forced filter mapping, or None.
        """
        return None

    # -- permissions -------------------------------------------------------- #
    @classmethod
    def get_permissions(cls) -> list[Any]:
        """Instantiate the configured "permission_classes".

        Returns:
            A list of permission instances.
        """
        return [permission() for permission in cls.permission_classes]

    @classmethod
    def check_permissions(cls, info: ResolveInfo, action: str, **kwargs: Any) -> None:
        """Raise "GraphQLError" if any permission denies the action.

        Args:
            info: GraphQL resolve info for the current request.
            action: Action name being checked (e.g. "create", "list").
            **kwargs: Extra arguments passed to each permission check. Any a
                given check cannot accept are dropped for that check.

        Raises:
            GraphQLError: If any permission denies the action.
        """
        method_name = f"has_{action}_permission"
        for permission in cls.get_permissions():
            check = getattr(permission, method_name)
            # SECURITY: fail closed on ANY falsy result, not just the "False"
            # singleton. "return user and user.is_staff" -- the idiomatic
            # one-liner -- yields None/an empty value for an anonymous caller,
            # and an identity check would have granted the action.
            if not check(info, cls._meta.model, **supported_kwargs(check, kwargs)):
                raise GraphQLError(
                    "You do not have permission to perform this action.",
                    extensions={"code": "PERMISSION_DENIED", "status_code": 403},
                )

    @classmethod
    def authorize(cls, info: ResolveInfo, action: str, **kwargs: Any) -> None:
        """Authorize an action before it runs via permission checks.

        Called by every CRUD method; override to customize (e.g. skip checks
        in local development). Raises "GraphQLError" when denied.

        Args:
            info: GraphQL resolve info for the current request.
            action: Action name being authorized (e.g. "create", "list").
            **kwargs: Extra arguments passed to the permission checks.

        Raises:
            GraphQLError: If the action is not allowed.
        """
        cls.check_permissions(info, action, **kwargs)

    @classmethod
    def create(cls, root: Any, info: ResolveInfo, **kwargs: Any) -> DjangoModelType:
        """Create a new object using the serializer.

        Nested children declared in "Meta.nested_fields" are written atomically
        with the parent (see "NestedFieldsMixin.save_with_nested").

        Args:
            root: Root value passed to the resolver.
            info: GraphQL resolve info for the current request.
            **kwargs: Resolver arguments including the input data.

        Returns:
            A success response with the created object, or an error response.
        """
        data = kwargs.get(cls._meta.input_field_name)
        cls.authorize(info, "create", data=data)
        request_type = info.context.META.get("CONTENT_TYPE", "")
        if "multipart/form-data" in request_type:
            data.update({name: value for name, value in info.context.FILES.items()})

        ok, obj = cls.save_with_nested(root, info, data, instance=None)
        if not ok:
            return cls.get_errors(obj)
        return cls.perform_mutate(obj, info)

    @classmethod
    def delete(cls, root: Any, info: ResolveInfo, **kwargs: Any) -> DjangoModelType:
        """Delete an object by its primary key.

        Args:
            root: Root value passed to the resolver.
            info: GraphQL resolve info for the current request.
            **kwargs: Resolver arguments including the object "id".

        Returns:
            A success response with the deleted object, or an error response
            when no matching object exists or it falls outside the scoped
            queryset.
        """
        cls.authorize(info, "delete", data=kwargs)
        pk = kwargs.get("id")

        # SECURITY: resolve the target row through the SAME scoped queryset the
        # read path uses ("get_queryset" -> "filter_queryset"), never the bare
        # model. A row outside the caller's scope must be "not found" for a
        # write exactly as it already is for a read, so the response cannot be
        # used to probe another tenant's primary keys.
        scoped = cls.get_queryset(cls._meta.model._default_manager, info, **kwargs)
        old_obj = get_Object_or_None(scoped, pk=pk)
        if old_obj:
            old_obj.delete()
            setattr(old_obj, old_obj._meta.pk.attname, pk)
            return cls.perform_mutate(old_obj, info)
        else:
            return cls.get_errors(not_found_error(cls._meta.model, pk))

    @classmethod
    def update(cls, root: Any, info: ResolveInfo, **kwargs: Any) -> DjangoModelType:
        """Update an existing object using the serializer.

        Args:
            root: Root value passed to the resolver.
            info: GraphQL resolve info for the current request.
            **kwargs: Resolver arguments including the input data.

        Returns:
            A success response with the updated object, or an error response
            when no matching object exists or it falls outside the scoped
            queryset.
        """
        data = kwargs.get(cls._meta.input_field_name)
        cls.authorize(info, "update", data=data)
        request_type = info.context.META.get("CONTENT_TYPE", "")
        if "multipart/form-data" in request_type:
            data.update({name: value for name, value in info.context.FILES.items()})

        # Use .pop('id', None) so that an update input where 'id' was excluded
        # via only_fields/exclude_fields does not raise KeyError.  A None pk
        # means no object can be found, so old_obj will be None and the resolver
        # returns a clean "not found" error rather than a 500.
        pk = data.pop("id", None)
        # SECURITY: same scoped lookup as "delete" -- see the comment there.
        scoped = cls.get_queryset(cls._meta.model._default_manager, info, **kwargs)
        old_obj = get_Object_or_None(scoped, pk=pk)
        if old_obj:
            ok, obj = cls.save_with_nested(
                root,
                info,
                data,
                instance=old_obj,
            )
            if not ok:
                return cls.get_errors(obj)
            return cls.perform_mutate(obj, info)
        else:
            return cls.get_errors(not_found_error(cls._meta.model, pk))

    @classmethod
    def retrieve(
        cls, manager: Manager | QuerySet, root: Any, info: ResolveInfo, **kwargs: Any
    ) -> Model | None:
        """Retrieve a single object by primary key, optimized for selection.

        Args:
            manager: Default manager or queryset to retrieve from.
            root: Root value passed to the resolver.
            info: GraphQL resolve info for the current request.
            **kwargs: Resolver arguments including the object "id".

        Returns:
            The matching model instance, or None if it does not exist.
        """
        cls.authorize(info, "retrieve")
        pk = kwargs.pop("id", None)

        base = cls.get_queryset(manager, info, **kwargs)
        try:
            qs = queryset_factory(base, root, info, **kwargs)
            return qs.get(pk=pk)
        except manager.model.DoesNotExist:
            return None

    @classmethod
    def list(
        cls,
        manager: Manager | QuerySet,
        filter_backend: Any,
        root: Any,
        info: ResolveInfo,
        **kwargs: Any,
    ) -> DjangoListObjectBase:
        """List objects with filtering and pagination support.

        Composition order: "get_queryset" (which applies "filter_queryset")
        scopes the base queryset first -> standard ORM lookups (via
        filter_backend, collapsed into one "Q") -> custom "@filter_field"
        methods (in declaration order).

        Args:
            manager: Default manager or queryset to list from.
            filter_backend: The native filter backend applied to the queryset.
            root: Root value passed to the resolver.
            info: GraphQL resolve info for the current request.
            **kwargs: Resolver arguments including the "filter" value.

        Returns:
            A list result container with the count and matching objects.
        """
        from .filtering.filter_field import apply_custom_filters

        cls.authorize(info, "list")
        base = cls.get_queryset(manager, info, **kwargs)
        qs = queryset_factory(base, root, info, **kwargs)

        filter_value = kwargs.get("filter")
        qs = filter_backend.apply(qs, filter_value)

        # Apply custom @filter_field methods in declaration order.
        custom_filters = getattr(cls, "_dgx_custom_filters", None) or []
        qs = apply_custom_filters(qs, custom_filters, info, filter_value)

        count = qs.count()

        return DjangoListObjectBase(
            count=count,
            results=maybe_queryset(qs),
            results_field_name=cls.list_object_type()._meta.results_field_name,
        )

    @classmethod
    def _assert_operation(cls, operation: str) -> None:
        """Ensure "operation" is enabled in Meta.model_operations.

        Mirrors the twin on "DjangoModelMutation". It is what keeps the
        declaration honest in both directions: a type that says it serves reads
        only -- and is therefore skipped by the nested WRITE path -- must not
        quietly mount a write root of its own.

        Args:
            operation: The operation whose field is being built.

        Raises:
            AttributeError: If the operation was excluded from model_operations.
        """
        if operation not in cls._meta.model_operations:
            raise AttributeError(
                '"{}" is not enabled on {}; Meta.model_operations is {}.'.format(
                    operation, cls.__name__, cls._meta.model_operations
                )
            )

    @classmethod
    def RetrieveField(cls, *args: Any, **kwargs: Any) -> DjangoObjectField:
        """Create a field for retrieving a single object.

        Args:
            *args: Positional arguments (currently unused).
            **kwargs: Keyword arguments forwarded to the field.

        Returns:
            A field that resolves a single object via "retrieve".

        Raises:
            AttributeError: If "retrieve" is not in Meta.model_operations.
        """
        cls._assert_operation("retrieve")
        return DjangoObjectField(cls._meta.output_type, resolver=cls.retrieve, **kwargs)

    @classmethod
    def ListField(cls, *args: Any, **kwargs: Any) -> DjangoListObjectField:
        """Create a field for listing objects.

        Args:
            *args: Positional arguments (currently unused).
            **kwargs: Keyword arguments forwarded to the field.

        Returns:
            A field that resolves a list of objects via "list".

        Raises:
            AttributeError: If "list" is not in Meta.model_operations.
        """
        cls._assert_operation("list")
        return DjangoListObjectField(
            cls._meta.output_list_type, resolver=cls.list, **kwargs
        )

    @classmethod
    def _build_native_mutation_field(cls, operation: str) -> Any:
        """Build a graphql-core GraphQLField for the given mutation operation.

        Used by CreateField / DeleteField / UpdateField.

        WU9 parity fix — this path now mirrors the DjangoModelMutation native
        field (mutation.py) and graphene's own DjangoModelType mutation shape:

        1. **Output is the PAYLOAD, not the node.** Graphene mounts
           ``cls._meta.mutation_output`` (= ``cls``) as the field type, so the SDL
           is ``create(...): <ThisType>`` where ``<ThisType>`` is the wrapper
           carrying ``ok`` / ``errors`` + the output field (the node).  The prior
           code used ``_meta.output_type._meta.graphql_output_type`` (the bare
           node) — ``ok`` / ``errors`` were unqueryable.  We now compile ``cls``
           itself (a plain graphene ObjectType subclass) via
           ``_compile_plain_object_type`` → the payload GraphQLObjectType.
        2. **camelCase wire arg keys.** graphql-core does NOT auto-camelCase arg
           names; the dict keys must be the camelCase WIRE names while each
           GraphQLArgument keeps ``out_name`` = the snake Python kwarg (already
           set when the arg was built in ``__init_subclass_with_meta__``).
        3. **Registration.** The built field is stored in
           ``_NATIVE_FIELD_REGISTRY[(model, operation, "native")]`` so the native
           root compiler's ``_collect_root_attrs`` (gated on registry membership)
           mounts it onto the native Mutation root.  The SAME instance is cached
           and returned on repeat calls so the mounted field IS the registered
           field (identity), exactly like the DjangoModelMutation path.

        Args:
            operation: One of ``"create"``, ``"delete"``, or ``"update"``.

        Returns:
            A ``GraphQLField`` whose ``.type`` is the compiled mutation payload,
            whose ``.args`` are ``GraphQLArgument`` instances keyed by camelCase
            wire names, and whose ``.resolve`` is the corresponding classmethod
            (adapted via ``_adapt_self``).
        """
        from graphql import GraphQLField as _GQLField

        from django_graphex.core._compat import _adapt_self
        from django_graphex.core.schema_compiler import (
            _compile_plain_object_type,
        )
        from django_graphex.mutation import (
            _NATIVE_FIELD_IDENTITIES,
            _NATIVE_FIELD_REGISTRY,
        )

        from ._strconv import to_camel_case as _to_camel

        model = cls._meta.model
        _reg_key = (model, operation, "native")

        # Per-CLASS idempotency: repeated *Field() calls on THIS exact subclass
        # return the SAME field instance (identity-stable so the mounted field is
        # the registered one). Keyed on the class — NOT on (model, op) — so two
        # distinct DjangoModelType subclasses for the same model each build their
        # OWN field (their resolvers/payloads differ). The shared
        # ``_NATIVE_FIELD_REGISTRY`` slot is still keyed by model+op and is
        # OVERWRITTEN below (last-built wins) to mirror the DjangoModelMutation
        # registration semantics; ``_collect_root_attrs`` recovers whichever
        # field instance is mounted via identity, so a root assembled from THIS
        # class always finds THIS class' field.
        _cache: dict[str, Any] = cls.__dict__.get("_dgx_native_mutation_fields", {})
        if "_dgx_native_mutation_fields" not in cls.__dict__:
            cls._dgx_native_mutation_fields = _cache
        cached = _cache.get(operation)
        if cached is not None:
            # Re-assert this class' slot in the shared registry (a sibling
            # subclass for the same model may have overwritten it since).
            _NATIVE_FIELD_REGISTRY[_reg_key] = cached
            return cached

        _resolver_map = {
            "create": cls.create,
            "delete": cls.delete,
            "update": cls.update,
        }

        # Output type = the compiled PAYLOAD (this wrapper class), not the node.
        _gql_output_type = _compile_plain_object_type(cls)

        # camelCase the wire arg keys; each GraphQLArgument keeps out_name=snake.
        # Non-GraphQLArgument values (unified ``Field`` descriptors used in an INPUT
        # position, typed scalar shortcuts, bare graphql-core types) are normalized
        # through ``to_graphql_argument`` — the same currency conversion the
        # DjangoModelMutation builder applies to its ``Arguments`` members.
        from graphql import GraphQLArgument as _GQLArg

        from django_graphex.core._args import to_graphql_argument as _arg_conv

        _args = {}
        for _arg_name, _arg in cls._meta.arguments[operation].items():
            _wire = _to_camel(_arg_name)
            if isinstance(_arg, _GQLArg):
                _args[_wire] = _arg
            else:
                _args[_wire] = _arg_conv(_arg, name=_arg_name)

        _gql_field = _GQLField(
            _gql_output_type,
            args=_args,
            resolve=_adapt_self(_resolver_map[operation], owner=cls),
            description=getattr(cls._meta, "description", None)
            or f"Native {operation} mutation for {model.__name__}",
        )
        # P0: stamp composite permissions for the pruner. An explicit
        # ``required_perms`` class attr (opt-in) wins; else the composite table
        # maps the write op to write+view.
        from django_graphex.core.perm_labels import required_perms_for

        _override = getattr(cls, "required_perms", None)
        _perms = (
            frozenset(_override)
            if _override is not None
            else required_perms_for(model, operation)
        )
        _gql_field.extensions = {
            **(_gql_field.extensions or {}),
            # item-b (B6), same contract as DjangoModelMutation: the payload
            # above was compiled ONCE against the pair this class was DEFINED
            # under, pinning its output field (e.g. "post: PostGenericType") to
            # the GLOBAL node. "schema_compiler._maybe_refork_mutation_field"
            # re-compiles that payload for a FORKED schema, but it keys off THIS
            # extension -- without it the field kept the global node and mixing
            # the mutation into a "registries=" schema died on a duplicate type
            # name / "assert_schema_pair_isolation".
            "gdx_mutation_source": cls,
            "gdx_required_perms": _perms,
        }
        _cache[operation] = _gql_field
        _NATIVE_FIELD_REGISTRY[_reg_key] = _gql_field
        _NATIVE_FIELD_IDENTITIES.add(id(_gql_field))
        return _gql_field

    @staticmethod
    def _with_deprecation(field: Any, deprecation_reason: str | None) -> Any:
        """Return *field* deprecated by *deprecation_reason* (a copy when set).

        The native mutation field is built ONCE and cached per class + operation
        (identity-stable so the mounted field is the registered one). A caller-
        supplied ``deprecation_reason`` must therefore NOT mutate the shared cached
        field — return a shallow ``GraphQLField`` copy carrying the reason instead,
        preserving every other attribute (type / args / resolver / description /
        extensions). ``None`` returns the field unchanged.

        Args:
            field: The compiled graphql-core ``GraphQLField``.
            deprecation_reason: The deprecation reason, or ``None`` for no change.

        Returns:
            The field unchanged (``None`` reason) or a deprecated copy.
        """
        if deprecation_reason is None:
            return field
        from graphql import GraphQLField as _GQLField

        return _GQLField(
            field.type,
            args=field.args,
            resolve=field.resolve,
            subscribe=field.subscribe,
            description=field.description,
            deprecation_reason=deprecation_reason,
            extensions=field.extensions,
        )

    @classmethod
    def CreateField(
        cls, *args: Any, deprecation_reason: str | None = None, **kwargs: Any
    ) -> Any:
        """Create a field for creating objects.

        Returns a graphql-core "GraphQLField" wired to the "create" resolver.

        Args:
            *args: Positional arguments (currently unused).
            deprecation_reason: Optional reason wired onto the compiled field so the
                SDL renders "@deprecated(reason: ...)".
            **kwargs: Keyword arguments (currently unused).

        Returns:
            A mutation field wired to the "create" resolver.

        Raises:
            AttributeError: If "create" is not in Meta.model_operations.
        """
        cls._assert_operation("create")
        return cls._with_deprecation(
            cls._build_native_mutation_field("create"), deprecation_reason
        )

    @classmethod
    def DeleteField(
        cls, *args: Any, deprecation_reason: str | None = None, **kwargs: Any
    ) -> Any:
        """Create a field for deleting objects.

        Returns a graphql-core "GraphQLField" wired to the "delete" resolver.

        Args:
            *args: Positional arguments (currently unused).
            deprecation_reason: Optional reason wired onto the compiled field so the
                SDL renders "@deprecated(reason: ...)".
            **kwargs: Keyword arguments (currently unused).

        Returns:
            A mutation field wired to the "delete" resolver.

        Raises:
            AttributeError: If "delete" is not in Meta.model_operations.
        """
        cls._assert_operation("delete")
        return cls._with_deprecation(
            cls._build_native_mutation_field("delete"), deprecation_reason
        )

    @classmethod
    def UpdateField(
        cls, *args: Any, deprecation_reason: str | None = None, **kwargs: Any
    ) -> Any:
        """Create a field for updating objects.

        Returns a graphql-core "GraphQLField" wired to the "update" resolver.

        Args:
            *args: Positional arguments (currently unused).
            deprecation_reason: Optional reason wired onto the compiled field so the
                SDL renders "@deprecated(reason: ...)".
            **kwargs: Keyword arguments (currently unused).

        Returns:
            A mutation field wired to the "update" resolver.

        Raises:
            AttributeError: If "update" is not in Meta.model_operations.
        """
        cls._assert_operation("update")
        return cls._with_deprecation(
            cls._build_native_mutation_field("update"), deprecation_reason
        )

    @classmethod
    def QueryFields(cls, *args: Any, **kwargs: Any) -> tuple[Any, ...]:
        """Return the query fields enabled by Meta.model_operations.

        Args:
            *args: Positional arguments forwarded to the field builders.
            **kwargs: Keyword arguments forwarded to the field builders.

        Returns:
            The retrieve field and the list field (in that order) for every
            operation enabled in "Meta.model_operations".
        """
        builders = (("retrieve", cls.RetrieveField), ("list", cls.ListField))
        return tuple(
            build(*args, **kwargs)
            for operation, build in builders
            if operation in cls._meta.model_operations
        )

    @classmethod
    def MutationFields(cls, *args: Any, **kwargs: Any) -> tuple[Any, ...]:
        """Return the mutation fields enabled by Meta.model_operations.

        Args:
            *args: Positional arguments forwarded to the field builders.
            **kwargs: Keyword arguments forwarded to the field builders.

        Returns:
            The create, delete and update fields (in that order) for every
            operation enabled in "Meta.model_operations".
        """
        builders = (
            ("create", cls.CreateField),
            ("delete", cls.DeleteField),
            ("update", cls.UpdateField),
        )
        return tuple(
            build(*args, **kwargs)
            for operation, build in builders
            if operation in cls._meta.model_operations
        )

    @classmethod
    def subscription_type(cls) -> Any:
        """Return the cached "Subscription" subclass for this model type.

        Built lazily from "Meta.model" / "Meta.stream" /
        "Meta.payload_mode" so that the base install never imports the
        optional "[subscriptions]" extra (Channels) until subscriptions are
        actually used. Mount it on the subscription root via "SubscriptionField"
        and serve it over the native SSE/WS transports.

        Returns:
            The generated "Subscription" subclass.

        Raises:
            ImproperlyConfigured: If "Meta.stream" was not set.
        """
        sub = cls.__dict__.get("_subscription_cls")
        if sub is None:
            if not cls._meta.stream:
                raise ImproperlyConfigured(
                    "{}.Meta.stream must be set to expose a subscription.".format(
                        cls.__name__
                    )
                )
            # Lazy import keeps the base install free of Channels.
            from django_graphex.subscriptions import Subscription

            parent = cls

            def _authorize_subscription(_sub_cls, info, **kwargs):
                # Honor the type's permission_classes / authorize at subscribe.
                # Forward the requested subscription action (create/update/delete/
                # all_actions) so per-action permission classes can enforce it at
                # RUNTIME — defense in depth alongside the pruned action enum.
                # ``authorize`` takes the CRUD ``action`` positionally ("subscribe")
                # so the subscription's own action value is threaded under the
                # distinct ``subscription_action`` kwarg to avoid the positional
                # collision; ``has_subscribe_permission`` reads it back.
                return parent.authorize(
                    info,
                    "subscribe",
                    subscription_action=kwargs.get("action"),
                )

            def _subscription_scope(_sub_cls, info, **kwargs):
                # Honor the type's row-scoping as server-forced notify filters.
                return parent.subscription_scope(info, **kwargs)

            meta_attrs = {
                "model": cls._meta.model,
                "pydantic_model": getattr(cls._meta.backend, "pydantic_model", None),
                "stream": cls._meta.stream,
                "payload_mode": cls._meta.payload_mode,
                "subscription_index_fields": cls._meta.subscription_index_fields,
                # SECURITY (2.0.1): forward the output projection. Without it the
                # generated subscription's backend stayed UNPROJECTED, so an
                # ``exclude_fields = ("password",)`` column was still serialized
                # into every event AND still accepted as a client filter root.
                "only_fields": cls._meta.only_fields,
                "exclude_fields": cls._meta.exclude_fields,
            }

            # S6e (#1452): ``Subscription`` is now a native (pydantic
            # ``ModelMetaclass``) type. Building a subclass via the 3-arg
            # ``type(name, bases, ns)`` form does NOT auto-carry
            # ``__module__`` / ``__qualname__`` into the namespace (unlike a real
            # ``class`` statement), and pydantic's ``inspect_namespace`` reads
            # ``namespace['__module__']`` eagerly — so a missing key raises
            # ``KeyError('__module__')`` (the same factory_type fix S6b applied in
            # base_types.py). Inject both, and re-stamp the nested ``Meta``'s
            # qualname to ``"<Name>.Meta"`` so pydantic's nested-class guard
            # treats ``Meta`` as an ignorable nested class exactly as if it had
            # been written inside a real ``class <Name>(Subscription)`` body.
            sub_name = f"{cls.__name__}Subscription"
            meta_cls = type("Meta", (), meta_attrs)
            meta_cls.__qualname__ = f"{sub_name}.Meta"
            meta_cls.__module__ = __name__

            sub = type(
                sub_name,
                (Subscription,),
                {
                    "__module__": __name__,
                    "__qualname__": sub_name,
                    "Meta": meta_cls,
                    "authorize_subscription": classmethod(_authorize_subscription),
                    "subscription_scope": classmethod(_subscription_scope),
                },
            )
            cls._subscription_cls = sub
        return sub

    @classmethod
    def SubscriptionField(cls, *args: Any, **kwargs: Any) -> Any:
        """Mount this type's subscription on a root subscription "ObjectType".

        Args:
            *args: Positional arguments forwarded to the field builder.
            **kwargs: Keyword arguments forwarded to the field builder.

        Returns:
            The "SubscriptionField" carrying the generated subscription's
            resolver.
        """
        return cls.subscription_type().Field(*args, **kwargs)
