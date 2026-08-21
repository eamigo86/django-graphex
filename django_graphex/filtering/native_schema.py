"""Native (graphql-core) "<Model>FilterInput" builder.

It produces the nested input shape:

    input <Model>FilterInput {
      <camelField>: <Model><Field>Lookups   # out_name = snake field name
      <relation>:   <Related>FilterInput     # out_name = snake relation name
      ...
    }

    input <Model><Field>Lookups {
      exact: <Scalar>          # out_name = "exact"
      icontains: String        # out_name = "icontains"
      isnull: Boolean          # out_name = "isnull"
      in: [<Scalar>]           # out_name = "in"
      range: [<Scalar>]        # out_name = "range"
    }

The cardinal footgun (see design D5 / explore risk #3):
    graphql-core uses the dict key as the WIRE key (camelCase, for SDL parity)
    and "out_name" as the key delivered to the resolver. "to_q" expects
    snake ORM keys. A field WITHOUT "out_name" would deliver the camelCase
    wire key to "to_q", which would build a WRONG / EMPTY "Q" with NO error.
    Therefore EVERY field carries "out_name" set to its snake ORM lookup key.

WU3 scope: scalar/relation lookups, "out_name" on every field, choices enum,
"extensions['gdx']" invariant (D8), custom "@filter_field" args (typed via
the native scalar bridge).

WU4 scope (here): the recursive "and" / "or" / "not" combinators (added
inside the field thunk so they close over the cached self-reference — the
"_NATIVE_INPUT_CACHE" cache-before-thunk recursion guard, D5), and the
build-time completeness assertion "_assert_filter_type_complete" (A6) wired
into "build_filter_input_type" to catch the silent empty-".fields" footgun
that a circular thunk would otherwise ship unnoticed.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from django.core.exceptions import FieldDoesNotExist, ImproperlyConfigured
from django.db import models
from graphql import (
    GraphQLBoolean,
    GraphQLFloat,
    GraphQLID,
    GraphQLInputField,
    GraphQLInputObjectType,
    GraphQLInt,
    GraphQLList,
    GraphQLScalarType,
    GraphQLString,
)

from django_graphex._strconv import to_camel_case
from django_graphex.registry import get_global_registry

from .lookups import default_lookups_for

if TYPE_CHECKING:
    from django_graphex.core.base import SchemaRegistries
    from django_graphex.registry import Registry

__all__ = (
    "build_filter_input_type",
    "_assert_filter_type_complete",
    "_assert_filter_input_out_names",
    "_canonical_filter_fields",
)


# ---------------------------------------------------------------------------
# filter_fields normalization + relation traversal (graphene-free helpers).
#
# S7 (graphene-removal): relocated VERBATIM from the now-deleted graphene
# ``filtering/schema.py``. Both are pure Django-introspection helpers (no
# graphene dependency), so they live here in the native filter-input builder's
# own module — the only remaining caller now that the graphene arm is gone.
# ---------------------------------------------------------------------------


def _normalize_filter_fields(filter_fields: Any) -> dict[str, tuple[str, ...] | None]:
    """Normalize a "filter_fields" declaration to "{path: lookups | None}".

    A "None" value in the result means "use the default lookup set for the
    field's type" and only ever appears when the list form is used (where the
    caller did not specify explicit lookups).

    Args:
        filter_fields: A list of field paths, or a "{path: lookups}" dict.

    Returns:
        A mapping of field path to an explicit lookup tuple, or "None" when
        the default lookup set should apply (list form).

    Raises:
        ImproperlyConfigured: When a dict value is explicitly "None".
            The correct way to declare custom per-field filters is via the
            "@filter_field" decorator.
    """
    result: dict[str, tuple[str, ...] | None] = {}
    if isinstance(filter_fields, dict):
        for path, lookups in filter_fields.items():
            if lookups is None:
                raise ImproperlyConfigured(
                    f"filter_fields[{path!r}] is None. "
                    "Use the @filter_field decorator to declare custom per-field "
                    "filters instead of a None sentinel in filter_fields."
                )
            result[path] = tuple(lookups)
    else:
        # List form: None means "use defaults" for the downstream helpers.
        for path in filter_fields or ():
            result[path] = None
    return result


def _relation_model(model: type[models.Model], name: str) -> type[models.Model] | None:
    """Return the related model for a relation field name, else "None"."""
    try:
        field = model._meta.get_field(name)
    except Exception:
        return None
    if field.is_relation:
        return field.related_model
    return None


# ---------------------------------------------------------------------------
# Django internal-type name -> graphql-core scalar singleton.
#
# Mirrors the graphene map in ``filtering/schema.py:35-65`` 1:1 but yields
# graphql-core scalars (reusing the owned native scalar singletons from
# ``core/scalars.py`` so SDL names match the output path).
# ---------------------------------------------------------------------------


def _scalar_by_internal() -> dict[str, GraphQLScalarType]:
    """Build the internal-type -> graphql-core scalar map.

    Deferred so importing this module never forces the heavy scalars module if
    the native backend is inactive.
    """
    from django_graphex.core.scalars import (
        GdxDecimal,
        GdxFilterDate,
        GdxFilterDateTime,
        GdxFilterTime,
        GdxJSON,
        GdxUUID,
    )

    return {
        "AutoField": GraphQLID,
        "BigAutoField": GraphQLID,
        "SmallAutoField": GraphQLID,
        "IntegerField": GraphQLInt,
        "SmallIntegerField": GraphQLInt,
        "BigIntegerField": GraphQLInt,
        "PositiveIntegerField": GraphQLInt,
        "PositiveSmallIntegerField": GraphQLInt,
        "PositiveBigIntegerField": GraphQLInt,
        "CharField": GraphQLString,
        "TextField": GraphQLString,
        "EmailField": GraphQLString,
        "URLField": GraphQLString,
        "SlugField": GraphQLString,
        "FilePathField": GraphQLString,
        "FileField": GraphQLString,
        "ImageField": GraphQLString,
        "GenericIPAddressField": GraphQLString,
        "BooleanField": GraphQLBoolean,
        "NullBooleanField": GraphQLBoolean,
        "FloatField": GraphQLFloat,
        "DecimalField": GdxDecimal,
        # Date/DateTime/Time use PLAIN-named filter-input scalars (Date /
        # DateTime / Time) to match graphene's filter-input map — NOT the
        # CustomDate-named OUTPUT singletons. graphene-django is internally
        # inconsistent here (CustomDate output, Date filter); native matches
        # graphene PER-PATH for full-schema SDL parity (discovery #1509).
        "DateField": GdxFilterDate,
        "DateTimeField": GdxFilterDateTime,
        "TimeField": GdxFilterTime,
        "DurationField": GraphQLString,
        "UUIDField": GdxUUID,
        "BinaryField": GraphQLString,
        # v2 RAW-JSON default: a JSONField filter arg is the raw ``JSON`` scalar.
        "JSONField": GdxJSON,
    }


# ---------------------------------------------------------------------------
# extensions["gdx"] payload for native filter input types (D8 invariant).
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class GdxFilterInputSpec:
    """Payload stored under 'extensions["gdx"]' on every native filter input.

    Carries the source model + the GraphQL type name so read-sites (and the
    compat bridge) can route without re-deriving them.
    """

    model: Any = None
    name: str | None = None
    is_lookups: bool = False


#: Memo of generated native input types keyed by ``(model, custom-filter identity)``.
#: The filter declaration is deliberately NOT part of the key: one model has ONE
#: ``<Model>FilterInput`` name, so every context filtering that model must share
#: a single instance, widened in place when a later context asks for paths the
#: current shape lacks. Separate from the graphene ``schema._INPUT_CACHE`` so the
#: two backends never cross-contaminate. The and/or/not combinators (WU4) close
#: over the cached reference registered here BEFORE the field thunk evaluates
#: (cache-before-thunk).
#:
#: item-b (B2): this dict is the DEFAULT pair's filter-input cache namespace —
#: ``default_schema_registries().filter_input_cache`` IS this very object (bound
#: by identity). ``build_filter_input_type`` resolves its cache from the threaded
#: ``SchemaRegistries`` pair, so the default path keeps writing here
#: (byte-identical) while a forked pair (later slices) owns its own namespace.
_NATIVE_INPUT_CACHE: dict[tuple[Any, Any], GraphQLInputObjectType] = {}


def _filter_input_cache(
    registries: SchemaRegistries | None,
) -> dict[tuple[Any, Any], GraphQLInputObjectType]:
    """Return the filter-input cache for *registries* (default pair when None).

    The default pair's "filter_input_cache" IS "_NATIVE_INPUT_CACHE" (bound by
    identity), so the default path is byte-identical. "base" is imported lazily
    here to keep "native_schema" import-safe ("base" lazily imports THIS
    module to seed the default pair — see "default_schema_registries").
    """
    if registries is not None:
        return registries.filter_input_cache
    from django_graphex.core.base import default_schema_registries

    return default_schema_registries().filter_input_cache


def _pk_scalar(model: type[models.Model]) -> GraphQLScalarType:
    """Return the graphql-core scalar for a model's primary key."""
    return _field_scalar(model._meta.pk)


def _field_scalar(field: models.Field) -> GraphQLScalarType:
    """Map a concrete model field to its graphql-core scalar singleton.

    Args:
        field: The Django model field.

    Returns:
        The graphql-core scalar for the field's value (String fallback for
        unknown internal types, mirroring the graphene builder).
    """
    if isinstance(field, (models.ForeignKey, models.OneToOneField)):
        return _pk_scalar(field.related_model)
    internal = field.get_internal_type()
    scalar = _scalar_by_internal().get(internal)
    if scalar is not None:
        return scalar
    return GraphQLString


def _choices_enum(field: models.Field, registry: Registry) -> Any:
    """Return the SHARED "GraphQLEnumType" for a choices field, or "GraphQLString".

    Delegates to the GRAPHENE-FREE canonical builder
    "converter.build_choices_enum_type", which memoizes ONE enum instance per
    "(model, field)" in the "registry" slot the native OUTPUT compiler also
    reads ("native.output_compiler._compile_choices_enum_field"). So a given
    field resolves the SAME "GraphQLEnumType" instance on BOTH the output and
    the filter-input path — no duplicate / divergent enum (S-enum-1).

    When the field has no usable choices we fall back to "GraphQLString" (the
    filter-input path always needs a concrete scalar; the caller never reaches
    this for a non-choices field).

    Args:
        field: The Django model field carrying choices.
        registry: The registry used to memoize the enum (shared with the OUTPUT
            compiler and the graphene path's name keying).

    Returns:
        A "GraphQLEnumType" for the field's choices, or "GraphQLString".
    """
    from django_graphex.converter import build_choices_enum_type

    enum_type = build_choices_enum_type(field, registry)
    if enum_type is None:
        return GraphQLString
    return enum_type


def _lookups_input_type(
    model: type[models.Model],
    field: models.Field,
    field_name: str,
    lookups: tuple[str, ...] | None,
    registry: Registry,
) -> GraphQLInputObjectType:
    """Build the "<Model><Field>Lookups" graphql-core input for a scalar field.

    Every lookup field carries "out_name" equal to its lookup name so the
    coerced dict delivers snake ORM keys to "to_q".

    Args:
        model: The owning model.
        field: The Django model field.
        field_name: The (possibly relation-qualified) leaf field name.
        lookups: The explicit lookup tuple, or "None" for the defaults.
        registry: The registry providing choices enums.

    Returns:
        A "GraphQLInputObjectType" for the field's lookups.
    """
    if lookups is None:
        lookups = default_lookups_for(field.get_internal_type())

    if getattr(field, "choices", None):
        scalar: Any = _choices_enum(field, registry)
    else:
        scalar = _field_scalar(field)

    name = to_camel_case(f"{model._meta.object_name}_{field_name}_Lookups")
    return _build_lookups_type(name, scalar, lookups)


def _pk_lookups_input_type(
    model: type[models.Model],
    field_name: str,
    related: type[models.Model],
    lookups: tuple[str, ...] | None,
) -> GraphQLInputObjectType:
    """Build a plain-pk lookups input for a relation declared directly.

    Args:
        model: The owning model.
        field_name: The relation field name.
        related: The related model.
        lookups: The explicit lookup tuple, or "None" for the defaults.

    Returns:
        A "GraphQLInputObjectType" for the relation's pk lookups.
    """
    if lookups is None:
        lookups = default_lookups_for(related._meta.pk.get_internal_type())
    scalar = _pk_scalar(related)
    name = to_camel_case(f"{model._meta.object_name}_{field_name}_Lookups")
    return _build_lookups_type(name, scalar, lookups)


def _build_lookups_type(
    name: str, scalar: Any, lookups: tuple[str, ...]
) -> GraphQLInputObjectType:
    """Assemble a "<...>Lookups" input type from a scalar and lookup names.

    Args:
        name: The GraphQL type name.
        scalar: The graphql-core scalar (or enum) for the field's value.
        lookups: The lookup names to expose.

    Returns:
        A "GraphQLInputObjectType" whose fields each carry "out_name".
    """

    def _fields() -> dict[str, GraphQLInputField]:
        out: dict[str, GraphQLInputField] = {}
        for lookup in lookups:
            if lookup == "isnull":
                out[lookup] = GraphQLInputField(GraphQLBoolean, out_name=lookup)
            elif lookup in ("in", "range"):
                out[lookup] = GraphQLInputField(GraphQLList(scalar), out_name=lookup)
            else:
                out[lookup] = GraphQLInputField(scalar, out_name=lookup)
        return out

    return GraphQLInputObjectType(
        name=name,
        fields=_fields,
        extensions={"gdx": GdxFilterInputSpec(name=name, is_lookups=True)},
    )


def _model_root_filter_fields(model: type[models.Model], registry: Registry) -> Any:
    """Return the model's canonical (root) "filter_fields" declaration, or "None".

    A model's CANONICAL filter shape is the one declared by its own
    "DjangoListObjectType" (preferred) or node "DjangoObjectType". Read-sites
    use this so that whenever the SAME model is filtered in two contexts — as a
    ROOT list (its own "filter_fields") AND as a NESTED relation-filter
    referenced from another type — both resolve to the SAME "<Model>FilterInput"
    shape (defect #6 / variant of #1571).

    Args:
        model: The model whose root filter declaration is requested.
        registry: The registry holding the model's list/node types.

    Returns:
        The model's "filter_fields" (list or dict), or "None" when the model
        has no registered root type that declares filtering.
    """
    list_type = registry.get_list_type_for_model(model)
    if list_type is not None:
        root = getattr(getattr(list_type, "_meta", None), "filter_fields", None)
        if root:
            return root
    node_type = registry.get_type_for_model(model)
    if node_type is not None:
        root = getattr(getattr(node_type, "_meta", None), "filter_fields", None)
        if root:
            return root
    return None


def _canonical_filter_fields(
    model: type[models.Model],
    requested: dict[str, tuple[str, ...] | None],
    registry: Registry,
) -> dict[str, tuple[str, ...] | None]:
    """Resolve the canonical filter declaration for a model build.

    Defect #6: the same model can be built as a ROOT list (its own
    "filter_fields") AND as a NESTED relation-filter (the narrow sub-declaration
    propagated from another type, e.g. "author__name"). Both produced a
    differently-shaped type sharing the single name "<Model>FilterInput" —
    graphene silently merged them (one shape won), graphql-core rejects the
    duplicate name.

    This seeds the convergence: when the model has a registered root filter
    declaration, every context (root or nested) starts from the root's paths, so
    the canonical shape does not depend on which context is compiled first. The
    cache then keeps ONE instance per model and widens it in place if a later
    context still asks for paths the root does not expose.

    Args:
        model: The model being built.
        requested: The normalized "{path: lookups}" declaration this call
            asked for (the root's own, or a nested relation sub-declaration).
        registry: The registry holding the model's root type.

    Returns:
        The declaration to build from: the canonical root when it covers
        "requested", the union (root then requested) when the contexts diverge,
        and "requested" unchanged when the model has no registered root.
    """
    root = _model_root_filter_fields(model, registry)
    if not root:
        # No registered root for this model: the requested (nested) declaration
        # IS the only / canonical shape. Single-context models (e.g. a relation
        # target with no root list type) keep their narrow shape + canonical name.
        return requested

    root_normalized = _normalize_filter_fields(root)

    # The root covers the requested context when every requested path is present
    # in the root declaration (lookups need not match exactly — the root's
    # superset of lookups still serves the narrower nested request: the extra
    # lookups are valid ORM lookups, and the nested query only uses its own).
    if all(path in root_normalized for path in requested):
        return root_normalized

    # Genuine fork: the model is filtered with paths its root does NOT expose.
    # Reconcile by building the UNION (root ∪ requested) under the canonical
    # name so a single type serves both contexts. Root paths come FIRST so the
    # field order is the same whichever context is compiled first.
    merged = dict(root_normalized)
    _union_filter_paths(merged, requested)
    return merged


def _union_filter_paths(
    base: dict[str, tuple[str, ...] | None],
    extra: dict[str, tuple[str, ...] | None],
) -> bool:
    """Merge "extra" into "base" in place and report whether "base" grew.

    Paths absent from "base" are appended; a path present in both keeps the
    union of the two lookup tuples (a "None" value means "the default lookup
    set" and always wins, since it is the widest declaration either side can
    ask for).

    Args:
        base: The accumulated declaration, mutated in place.
        extra: The declaration to merge in.

    Returns:
        "True" when "base" actually changed, so the caller knows the compiled
        input type has to be rebuilt.
    """
    changed = False
    for path, lookups in extra.items():
        if path not in base:
            base[path] = lookups
            changed = True
            continue
        current = base[path]
        if current == lookups:
            continue
        if current is None or lookups is None:
            merged: tuple[str, ...] | None = None
        else:
            merged = current + tuple(x for x in lookups if x not in current)
        if merged != current:
            base[path] = merged
            changed = True
    return changed


def _split_filter_paths(
    model: type[models.Model], paths: dict[str, tuple[str, ...] | None]
) -> tuple[
    dict[str, tuple[str, ...] | None],
    dict[str, dict[str, tuple[str, ...] | None]],
    dict[str, tuple[str, ...] | None],
]:
    """Split a canonical declaration into own leaves, relations and direct pks.

    Recomputed on every field-thunk evaluation so a filter input widened after
    its first build (a later context asking for paths the first one did not)
    recompiles from the CURRENT declaration.

    Args:
        model: The model the declaration belongs to.
        paths: The canonical "{path: lookups}" declaration.

    Returns:
        A "(own, relations, relation_direct)" triple: "own" holds this model's
        own leaf lookups, "relations" maps a relation name to the nested
        sub-declaration reached through it, and "relation_direct" holds
        relations declared without a tail (filtered by primary key).
    """
    own: dict[str, tuple[str, ...] | None] = {}
    relations: dict[str, dict[str, tuple[str, ...] | None]] = {}
    relation_direct: dict[str, tuple[str, ...] | None] = {}

    for path, lookups in paths.items():
        head, sep, tail = path.partition("__")
        related = _relation_model(model, head)
        if sep:
            if related is None:
                own[path] = lookups
            else:
                relations.setdefault(head, {})[tail] = lookups
        else:
            if related is not None:
                relation_direct[head] = lookups
            else:
                own[head] = lookups

    return own, relations, relation_direct


#: Instance attribute holding a compiled filter input's accumulated
#: ``{path: lookups}`` declaration. The field thunk closes over that very dict,
#: so widening it (plus ``_recompile_filter_input``) reshapes the type WITHOUT
#: minting a second instance under the same ``<Model>FilterInput`` name.
_CANONICAL_PATHS_ATTR = "_gdx_canonical_filter_paths"


def _canonical_paths(
    gql_input_type: GraphQLInputObjectType,
) -> dict[str, tuple[str, ...] | None]:
    """Return the accumulated declaration a cached filter input compiles from.

    Args:
        gql_input_type: A filter input previously built by this module.

    Returns:
        The mutable "{path: lookups}" dict the type's field thunk reads.
    """
    paths: dict[str, tuple[str, ...] | None] = getattr(
        gql_input_type, _CANONICAL_PATHS_ATTR
    )
    return paths


def _recompile_filter_input(gql_input_type: GraphQLInputObjectType) -> None:
    """Drop a filter input's memoized ".fields" so its thunk recompiles.

    "GraphQLInputObjectType.fields" is a "cached_property" over the thunk this
    module builds, and the build-time assertions force it immediately. Widening
    the canonical declaration therefore has to evict that memo and re-run the
    assertions, which recompiles the fields from the widened declaration WITHOUT
    replacing the type instance every other context already references.

    Args:
        gql_input_type: The cached filter input whose declaration just grew.
    """
    gql_input_type.__dict__.pop("fields", None)
    _assert_filter_type_complete(gql_input_type)
    _assert_filter_input_out_names(gql_input_type)


def build_filter_input_type(
    model: type[models.Model],
    filter_fields: Any,
    registry: Registry | None = None,
    custom_filters: list | None = None,
    registries: SchemaRegistries | None = None,
) -> GraphQLInputObjectType | None:
    """Build (or reuse) the native "<Model>FilterInput" graphql-core input type.

    Produces the same nested shape as the graphene builder (per-field
    "<Field>Lookups" inputs + nested relation filter inputs). Every field
    carries an "out_name" (snake ORM key). "and" / "or" / "not"
    combinators are added in WU4.

    Args:
        model: The Django model the input filters.
        filter_fields: The "Meta.filter_fields" declaration (list or dict).
        registry: The graphene "Registry" providing choices enums and related
            types; defaults to the global registry. (Distinct from "registries"
            below — this is the legacy single-registry param the graphene path
            also uses.)
        custom_filters: Optional list of "(arg_name, method, metadata)"
            triples from "@filter_field"-decorated methods. Each is added as
            a plain scalar argument to the filter input type.
        registries: The "SchemaRegistries" pair owning the filter-input cache
            namespace; defaults to the global pair (byte-identical, item-b B1/B2).

    Returns:
        A "GraphQLInputObjectType", or "None" when no filterable fields were
        declared (and no custom filters provided).
    """
    if not filter_fields and not custom_filters:
        return None

    if registry is None:
        registry = get_global_registry()

    cache = _filter_input_cache(registries)

    normalized = _normalize_filter_fields(filter_fields) if filter_fields else {}

    # Defect #6: converge same-named ``<Model>FilterInput`` shapes onto ONE
    # canonical type. When the model has its own root filter declaration, build
    # EVERY context (root list or nested relation-filter) from that single root
    # so the resulting type instance is identical and the cache dedupes it —
    # otherwise two differently-shaped types share the name and graphql-core
    # rejects the duplicate (graphene used to silently merge one shape away).
    if normalized:
        normalized = _canonical_filter_fields(model, normalized, registry)

    custom_key = tuple(
        (name, meta.get("graphql_type")) for name, _fn, meta in (custom_filters or [])
    )
    # ONE instance per (model, custom-filter identity): the declaration is NOT
    # part of the key, because the same model filtered from two contexts must
    # resolve to the SAME instance under the single ``<Model>FilterInput`` name.
    # A context asking for paths the cached shape lacks WIDENS that shape in
    # place instead of minting a second, same-named type — which is what made
    # graphql-core reject the schema outright ("Schema must contain uniquely
    # named types but contains multiple types named '<Model>FilterInput'").
    cache_key = (model, custom_key)
    cached = cache.get(cache_key)
    if cached is not None:
        if _union_filter_paths(_canonical_paths(cached), normalized):
            _recompile_filter_input(cached)
        return cached

    # The accumulated declaration this type compiles from. Mutable and captured
    # by the field thunk below, so a later widening recompiles from it.
    canonical = dict(normalized)

    # Build the PascalCase name directly. ``to_camel_case`` is a snake_case →
    # camelCase helper: feeding it the PascalCase compound ``User_FilterInput``
    # lower-cases the ``I`` (``str.capitalize()`` on the ``FilterInput`` component)
    # → ``UserFilterinput``. Assemble the name literally to keep the correct
    # PascalCase ``FilterInput`` suffix.
    name = f"{model._meta.object_name}FilterInput"

    def _fields() -> dict[str, GraphQLInputField]:
        out: dict[str, GraphQLInputField] = {}
        # Re-split on every evaluation: a widened declaration recompiles here.
        own, relations, relation_direct = _split_filter_paths(model, canonical)

        for field_name, lookups in own.items():
            try:
                field = model._meta.get_field(field_name)
            except FieldDoesNotExist:
                continue
            lookups_type = _lookups_input_type(
                model, field, field_name, lookups, registry
            )
            # Wire key = camelCase; out_name = snake ORM field name (footgun).
            out[to_camel_case(field_name)] = GraphQLInputField(
                lookups_type, out_name=field_name
            )

        for head, sub_fields in relations.items():
            related = _relation_model(model, head)
            if related is None:
                continue
            nested = build_filter_input_type(
                related, sub_fields, registry, registries=registries
            )
            if nested is not None:
                out[to_camel_case(head)] = GraphQLInputField(nested, out_name=head)

        for head, lookups in relation_direct.items():
            related = _relation_model(model, head)
            if related is None:
                continue
            pk_lookups = _pk_lookups_input_type(model, head, related, lookups)
            out[to_camel_case(head)] = GraphQLInputField(pk_lookups, out_name=head)

        for arg_name, _fn, meta in custom_filters or []:
            gql_type = _custom_filter_gql_type(meta)
            out[to_camel_case(arg_name)] = GraphQLInputField(
                gql_type, out_name=arg_name, description=meta.get("description")
            )

        # Recursive logical combinators. They reference THIS very input type, so
        # they close over ``input_type`` — which is registered in the cache
        # BEFORE this thunk can evaluate (cache-before-thunk recursion guard,
        # D5). ``and`` / ``or`` -> ``[<Self>]``; ``not`` -> ``<Self>``. Mirrors
        # the graphene builder (``filtering/schema.py:334-336``) for SDL parity.
        # ``out_name`` carries the snake combinator key so ``to_q`` reads it.
        out["and"] = GraphQLInputField(GraphQLList(input_type), out_name="and")
        out["or"] = GraphQLInputField(GraphQLList(input_type), out_name="or")
        out["not"] = GraphQLInputField(input_type, out_name="not")

        return out

    input_type = GraphQLInputObjectType(
        name=name,
        fields=_fields,
        extensions={"gdx": GdxFilterInputSpec(model=model, name=name)},
    )
    # Carry the accumulated declaration on the instance so a later context that
    # reaches this type through the cache can widen it (see ``_canonical_paths``).
    setattr(input_type, _CANONICAL_PATHS_ATTR, canonical)
    # Register BEFORE returning (and before the field thunk above can evaluate)
    # so the and/or/not combinators close over the cached reference without
    # re-entering the builder — the cache-before-thunk recursion guard (D5).
    cache[cache_key] = input_type
    # A6: force thunk evaluation NOW and raise if the type resolved to empty
    # ``.fields`` (the silent circular-reference footgun — a thunk that captured
    # an incomplete type would otherwise ship an empty input type unnoticed).
    _assert_filter_type_complete(input_type)
    # Audit rank 19: assert EVERY compiled top-level field carries a snake
    # ``out_name``. The cardinal footgun (see module docstring) is that a field
    # without ``out_name`` delivers the camelCase WIRE key to ``to_q``, which then
    # builds a WRONG/EMPTY Q with NO error. The builder always sets ``out_name``,
    # but a custom extension mutating ``.fields`` post-compile could strip it; this
    # build-time guard turns that silent failure into a loud one.
    _assert_filter_input_out_names(input_type)
    return input_type


def _assert_filter_type_complete(gql_input_type: GraphQLInputObjectType) -> None:
    """Force thunk evaluation and assert the input type has non-empty fields.

    The deferred-fields "lambda" means a filter input can be constructed and
    cached BEFORE its fields exist. If a recursive combinator (and/or/not) or a
    nested relation thunk captured an *incomplete* type — e.g. the circular
    "Category -> parent -> Category" case where the inner type's thunk hadn't
    populated yet — the resulting ".fields" could silently resolve to empty and
    the schema would ship a useless input type with NO error.

    Calling this at build time forces ".fields" to evaluate and raises if the
    result is empty, turning the silent footgun into a loud build-time failure.

    Args:
        gql_input_type: The native filter input type to validate.

    Raises:
        AssertionError: If the type's ".fields" evaluates to an empty dict.
    """
    fields = dict(gql_input_type.fields)  # forces the thunk to evaluate
    assert fields, (
        f"native filter input {gql_input_type.name!r} resolved to EMPTY .fields "
        "— a thunk likely captured an incomplete (circular) type before its "
        "fields were populated. Check the cache-before-thunk ordering."
    )


def _assert_filter_input_out_names(gql_input_type: GraphQLInputObjectType) -> None:
    """Assert every top-level field of a filter input carries a snake "out_name".

    The cardinal footgun (see the module docstring / D5): graphql-core uses a
    field's dict key as the WIRE key (camelCase, for SDL parity) and "out_name"
    as the key it delivers to the resolver. "to_q" expects snake ORM keys, so the
    builder sets "out_name" on EVERY field (scalar leaves, relations, custom
    "@filter_field" args, and the and/or/not combinators).

    A field WITHOUT "out_name" (e.g. a custom extension that mutated ".fields"
    after compilation) would silently deliver the camelCase wire key to "to_q",
    which would build a WRONG / EMPTY "Q" with NO error. This build-time guard
    forces the thunk to evaluate and raises a clear error if any top-level field is
    missing its "out_name", turning the silent footgun into a loud build failure.

    Nested relation filter inputs and per-field "<Field>Lookups" inputs are each
    validated on their own build (the recursive "build_filter_input_type" call and
    the per-field "out_name" already proven by the round-trip tests), so this only
    needs to re-check the top-level field surface of *this* type.

    Args:
        gql_input_type: The native filter input type to validate.

    Raises:
        AssertionError: If any top-level field lacks a truthy "out_name".
    """
    fields = dict(gql_input_type.fields)  # forces the thunk to evaluate
    missing = [
        name for name, field in fields.items() if not getattr(field, "out_name", None)
    ]
    assert not missing, (
        f"native filter input {gql_input_type.name!r} has field(s) WITHOUT a snake "
        f"out_name: {missing}. Every filter-input field MUST carry an out_name or "
        "to_q receives the camelCase wire key and silently builds an EMPTY Q. A "
        "custom extension likely mutated the compiled .fields and stripped it."
    )


def _custom_filter_gql_type(meta: dict[str, Any]) -> Any:
    """Resolve a custom "@filter_field" arg's graphql-core type from metadata.

    "@filter_field" stores the declared scalar/type under the "graphql_type"
    metadata key (see "filtering/filter_field.py"). The native backend mirrors
    that exact type so the argument renders faithfully (a
    "@filter_field(GraphQLInt)" arg renders "Int", not "String").

    S-del-backend-11: the graphene backend is deleted, so the legacy graphene
    scalar/type back-compat arm ("@filter_field(graphene.Int)" translated via the
    "core/_args.py" bridge) is removed. A native graphql-core type
    ("GraphQLScalarType" / "GraphQLList" / "GraphQLNonNull" /
    "GraphQLEnumType" / "GraphQLInputObjectType") is returned as-is (it is
    already what the compiler emits). A leftover graphene type raises "TypeError"
    via the bridge (the v2.0 CLEAN BREAK — declare "@filter_field" arg types with
    graphql-core types).

    Args:
        meta: The "@filter_field" metadata dict (carries "graphql_type").

    Returns:
        The graphql-core type for the argument. Falls back to "GraphQLString"
        only when no type is present (the historical default).
    """
    from graphql import GraphQLType

    graphql_type = meta.get("graphql_type")
    if graphql_type is None:
        return GraphQLString

    # Native callers: a graphql-core type is already what the compiler emits —
    # pass it through.
    if isinstance(graphql_type, GraphQLType):
        return graphql_type

    # Anything else (e.g. a leftover graphene type) is rejected by the bridge with
    # a clear TypeError (the v2.0 CLEAN BREAK off graphene).
    from django_graphex.core._args import _unwrap_graphql_type

    return _unwrap_graphql_type(graphql_type)
