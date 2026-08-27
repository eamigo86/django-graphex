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

THE PROJECTION BOUNDARY, and where it stops:
    "Meta.only_fields" / "Meta.exclude_fields" are a security boundary, so a
    "filter_fields" path reaching a column the serving type does not publish
    fails the BUILD ("_assert_filter_surface_published"). The answer comes from
    "core.output_compiler.publishes_column_value", the one predicate the
    ordering axis consumes too, so neither axis can invent its own notion of
    "hidden".

    Two things that guard cannot close, stated so they are not mistaken for
    covered:

    - The BODY of an "@filter_field" method. Its argument is an opaque scalar
      and its ORM lookup lives in user Python, where no build-time analysis can
      see it, so a method named anything that is not a column may still filter
      one the type hides. Only the NAME is checked, which closes the one-line
      rename out of a refused "filter_fields" entry and nothing more.
    - Per-TYPE narrowing. The filter input is compiled per MODEL and shared by
      every type over it, and every context converges on the model's root
      declaration, so one type's projection governs the single
      "<Model>FilterInput". A second, narrower type over the same model cannot
      get a narrower input under the current naming: two instances under one
      name is a hard build failure, and per-type inputs would need an
      "<Type>FilterInput" rename. Refusing at build time is the chosen shape.
"""

from __future__ import annotations

from collections.abc import Sequence
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
    get_named_type,
)

from django_graphex._strconv import to_camel_case
from django_graphex.registry import get_global_registry

from .lookups import default_lookups_for

if TYPE_CHECKING:
    from django_graphex.core.base import SchemaRegistries
    from django_graphex.registry import Registry

__all__ = (
    "build_filter_input_type",
    "build_subscription_filter_input_type",
    "_assert_filter_type_complete",
    "_assert_filter_input_out_names",
    "_canonical_filter_fields",
)

#: The ONLY lookups a subscription client filter may use (2.0.1 security fix,
#: mirrored from "subscriptions.streaming._ALLOWED_LOOKUPS"). Equality and
#: membership answer "is it exactly this value?"; an ordered or pattern lookup
#: answers a comparison, which event delivery turns into a boolean oracle an
#: attacker composes into a prefix walk. Declared in the ORDER the generated
#: SDL renders them.
SUBSCRIPTION_FILTER_LOOKUPS: tuple[str, ...] = ("exact", "iexact", "in", "isnull")


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
        # ``NullBooleanField`` reports "BooleanField" from
        # ``get_internal_type()``, so this single key covers it too.
        "BooleanField": GraphQLBoolean,
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

    # The root covers the requested context only when every requested path is
    # present AND the root's lookup tuple actually contains the requested
    # lookups. Testing path membership alone discarded the requested lookups
    # wholesale, so a nested "author__name": ("icontains",) silently compiled
    # to the root's "name": ("exact",) and became unusable.
    if all(
        path in root_normalized and _lookups_cover(root_normalized[path], lookups)
        for path, lookups in requested.items()
    ):
        return root_normalized

    # Genuine fork: the model is filtered with paths its root does NOT expose.
    # Reconcile by building the UNION (root ∪ requested) under the canonical
    # name so a single type serves both contexts. Root paths come FIRST so the
    # field order is the same whichever context is compiled first.
    merged = dict(root_normalized)
    _union_filter_paths(merged, requested)
    return merged


def _lookups_cover(
    root_lookups: tuple[str, ...] | None,
    requested_lookups: tuple[str, ...] | None,
) -> bool:
    """Report whether a root lookup tuple already serves a requested one.

    A "None" declaration means "the default lookup set for the field's type",
    which is neither provably wider nor provably narrower than an explicit
    tuple. Only the "both are None" case is therefore treated as covered; every
    other mismatch falls through to the union path, which resolves "None" as
    the widest declaration.

    Args:
        root_lookups: The lookup tuple the model's root declaration exposes,
            or "None" for the default set.
        requested_lookups: The lookup tuple this context asked for, or "None"
            for the default set.

    Returns:
        "True" when the root declaration already exposes every requested
        lookup, so the canonical root shape can be reused verbatim.
    """
    if root_lookups is None or requested_lookups is None:
        return root_lookups is None and requested_lookups is None
    return set(requested_lookups) <= set(root_lookups)


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
        relations declared without a tail (filtered by primary key). The two
        relation buckets are DISJOINT by construction.
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

    # A relation declared BOTH ways ("author" plus "author__name") landed in
    # both buckets, and the two compile loops write the SAME camelCase key, so
    # the second one silently dropped the first's field. Fold the plain-pk
    # declaration into the nested sub-declaration under the related model's own
    # primary-key name instead: "author__<pk>" is the same ORM lookup, and the
    # buckets stay disjoint so neither loop can overwrite the other.
    for head in list(relation_direct):
        if head not in relations:
            continue
        related = _relation_model(model, head)
        if related is None:  # pragma: no cover - head is a relation by construction
            continue
        _union_filter_paths(
            relations[head], {related._meta.pk.name: relation_direct.pop(head)}
        )

    return own, relations, relation_direct


#: Wire keys the field thunk always adds LAST, after the custom "@filter_field"
#: arguments, so a custom filter named like one of them is silently swallowed.
_COMBINATOR_KEYS: tuple[str, ...] = ("and", "or", "not")


def _assert_no_custom_filter_collision(
    model: type[models.Model],
    canonical: dict[str, tuple[str, ...] | None],
    custom_filters: list | None,
) -> None:
    """Refuse a "@filter_field" name that a compiled filter key already owns.

    The field thunk writes every entry under "to_camel_case(...)", and the
    custom-filter loop runs after the declared ones, so a "@filter_field" named
    like a "filter_fields" key silently REPLACED that key's
    "<Model><Field>Lookups" input. The field then became unfilterable both
    ways, and the only symptom was a raw "AttributeError" out of "to_q" at
    query time. This mirrors the "RESERVED_FILTER_ARGS" check the type
    metaclass already performs, but against the keys THIS declaration compiles.

    Called before the type is built, not from inside the field thunk:
    graphql-core wraps any exception a thunk raises in a "TypeError", which
    would bury the explanation.

    Args:
        model: The model the filter input is built for.
        canonical: The canonical "{path: lookups}" declaration being compiled.
        custom_filters: The "(arg_name, method, metadata)" triples collected
            from "@filter_field"-decorated methods, or "None".
        declared_on: The "{path: declaring type name}" provenance of the
            declaration, so a refusal names the "Meta" the entry has to leave.

    Raises:
        ImproperlyConfigured: When a custom filter's argument name equals a
            wire key the declaration already compiles.
    """
    if not custom_filters:
        return

    own, relations, relation_direct = _split_filter_paths(model, canonical)
    compiled = {
        to_camel_case(key)
        for key in (*own, *relations, *relation_direct, *_COMBINATOR_KEYS)
    }
    for arg_name, _fn, _meta in custom_filters:
        if to_camel_case(arg_name) in compiled:
            raise ImproperlyConfigured(
                f"{model._meta.object_name}: @filter_field method name "
                f"{arg_name!r} collides with a filter field compiled from "
                "Meta.filter_fields (or with an and/or/not combinator). "
                "Rename the method, or drop the conflicting filter_fields entry."
            )


def _type_name(node_type: Any) -> str:
    """Return a compiled type's SDL name for an error message.

    Args:
        node_type: A compiled "GraphQLObjectType", or any object standing in
            for one when the caller named no type at all.

    Returns:
        The SDL name, or a literal placeholder when there is no type to name.
    """
    return getattr(node_type, "name", None) or "<no type>"


def _node_of(compiled: Any) -> Any:
    """Unwrap a "<Model>ListType" container to the node type it paginates.

    A list field's declared type IS the container, and a to-many relation is
    published as one too, but the projection boundary lives on the NODE: the
    container publishes only its results and its count. Reached through the gdx
    payload's own results field name so a container configured with a custom
    one ("results_field_name") is unwrapped just the same.

    Args:
        compiled: A compiled type, a container or not, or "None".

    Returns:
        The node type the container paginates, or "compiled" unchanged when it
        is not a container.
    """
    payload = (getattr(compiled, "extensions", None) or {}).get("gdx")
    results = getattr(getattr(payload, "_meta", None), "results_field_name", None)
    fields = getattr(compiled, "fields", None)
    if results and isinstance(fields, dict) and results in fields:
        return get_named_type(fields[results].type)
    return compiled


def _traversed_type(node_type: Any, name: str) -> Any:
    """Return the compiled type a PUBLISHED relation resolves to, or "None".

    The traversal question, which is NOT the one
    "core.output_compiler.publishes_column_value" answers: "author__bio" says
    nothing about "author_id", so a hop is cleared by the relation being in the
    SDL at all, and the column behind it is the next hop's business. This is
    rule 2's first half, asked on its own.

    Descending through the COMPILED field is what makes the walk describe the
    schema that will serve the request rather than a model-keyed index: a
    relation the output compiler dropped (its target model has no registered
    type) is simply absent here, and a masked declaration carries the stamp, so
    both fail closed with no extra rule.

    A to-many relation is published as a "<Model>ListType" CONTAINER, not as
    the node itself, so the rows a nested filter reaches live one level down
    (see "_node_of").

    Args:
        node_type: The compiled type owning the hop, or any object carrying no
            field map (which fails closed).
        name: The snake relation field name being traversed.

    Returns:
        The compiled type the relation resolves to, or "None" when the type
        does not publish that relation.
    """
    from django_graphex.core.output_compiler import MASKED_COLUMN_EXT

    fields = getattr(node_type, "fields", None)
    if not isinstance(fields, dict):
        return None
    relation = fields.get(to_camel_case(name))
    if relation is None or (getattr(relation, "extensions", None) or {}).get(
        MASKED_COLUMN_EXT
    ):
        return None

    return _node_of(get_named_type(relation.type))


def filter_key_is_published(
    model: type[models.Model], key: str | None, serving_types: Sequence[Any]
) -> bool:
    """Report whether every type serving a model still publishes a filter key.

    The compiled read-side of the same boundary "_assert_filter_surface_published"
    enforces at build time, phrased as a question instead of a refusal because
    its caller cannot refuse. "core.schema_pruner" rebuilds the schema for a
    permission-scoped caller, and the clone publishes LESS: a relation whose
    target model the caller may not read is gone from the pruned node type, and
    the ordering allowlist is already re-derived against that clone. The filter
    argument rode through the prune verbatim, so one schema answered two ways.

    Asks the same two questions the build-time guard asks, of the same two
    helpers, so neither axis can drift: a relation key needs the relation to be
    TRAVERSABLE ("_traversed_type"), and a column key needs its VALUE published
    ("core.output_compiler.publishes_column_value").

    Deliberately NOT asked here: whether the relation's target publishes the
    key a relation-direct filter compares against. The build-time guard asks
    it, because a declaration can name a target type that projects its own key
    away; a PRUNE cannot produce that shape (it drops fields by permission
    label, and a model's key carries none), and asking it anyway would withdraw
    a legitimate nested filter from a caller who lost nothing.

    Args:
        model: The model the filter input belongs to.
        key: The snake ORM key the input field carries as its "out_name", or
            "None" for a field carrying none (which is left alone).
        serving_types: The compiled types that will serve this model's rows in
            the schema being built. Empty means nothing to measure against, and
            the key is left alone exactly as the build-time guard leaves a
            caller that named no type.

    Returns:
        True when every serving type still publishes what the key names.
    """
    from django_graphex.core.output_compiler import publishes_column_value

    if not key or key in _COMBINATOR_KEYS:
        return True
    head = key.split("__")[0]
    try:
        field = model._meta.get_field(head)
    except FieldDoesNotExist:
        # A custom "@filter_field" argument: its body is user Python and stays
        # the one documented open boundary, here as at build time.
        return True
    for serving in serving_types:
        if field.is_relation:
            if _traversed_type(serving, head) is None:
                return False
        elif not publishes_column_value(serving, field):
            return False
    return True


def _walk_filter_path(
    model: type[models.Model], path: str
) -> Sequence[tuple[type[models.Model], str]]:
    """Return the "(owner model, segment)" pairs a filter path traverses.

    "author__bio" declared on "Post" yields "(Post, "author")" then
    "(Author, "bio")", so each segment is checked against the type that
    actually publishes it. The walk stops at the first segment that is not a
    relation, which is also what makes a trailing lookup spelling harmless: in
    "name__icontains" the "icontains" tail is never reached.

    Args:
        model: The model the declaration belongs to.
        path: One "filter_fields" key, e.g. "author__bio".

    Returns:
        The ordered "(owner model, segment)" pairs, one per hop.
    """
    hops: list[tuple[type[models.Model], str]] = []
    current = model
    for segment in path.split("__"):
        hops.append((current, segment))
        related = _relation_model(current, segment)
        if related is None:
            break
        current = related
    return hops


#: Closes every refusal in this module with the same statement of the rule.
_BOUNDARY = (
    "A projection is a security boundary, not an output shape: a column a type "
    "hides must not be readable, orderable or filterable through it, and one "
    "filter request returns the hidden value exactly. "
)


def _declaration(model: type[models.Model], declared_on: str | None) -> str:
    """Name the "Meta.filter_fields" a refused entry has to be edited out of.

    Every refusal in this module ends with "or drop the entry", and a model has
    no "Meta.filter_fields" to drop it from: the declaration lives on a TYPE,
    and the filter input is shared per MODEL, so the type that contributed the
    entry is not always the type serving the rows the guard measured. The
    contributing type is carried alongside the path it declared (see
    "_DECLARED_ON_ATTR") and named here.

    Args:
        model: The model the filter input is built for, used for the fallback.
        declared_on: The name of the type whose "Meta" contributed the entry,
            or "None" when this build had no declaring class to name (a direct
            call to this builder, or to the public backend seam).

    Returns:
        The subject of the refusal sentence.
    """
    if declared_on:
        return f"{declared_on}.Meta.filter_fields"
    return f"{model._meta.object_name}.filter_fields"


def _refusal(
    model: type[models.Model],
    entry: str,
    segment: str,
    owner: Any,
    declared_on: str | None = None,
) -> str:
    """Build the message refusing one filter entry over a COLUMN.

    "owner" is the type that OWNS the hop, which is not always the type the
    walk started from: a deep path is measured against whatever the previous
    relation resolved to, and naming the root instead sent the reader to edit a
    "Meta" that never held the column.

    Args:
        model: The model the filter input is built for.
        entry: The declaration key being refused (a path, or a method name).
        segment: The hop within that key the serving type does not publish.
        owner: The compiled type that owns that hop.
        declared_on: The name of the type whose "Meta" declared the entry, or
            "None" when there is none to name.

    Returns:
        The full "ImproperlyConfigured" message.
    """
    name = _type_name(owner)
    return (
        f"{_declaration(model, declared_on)} entry {entry!r} names "
        f"{segment!r}, which {name} does not publish -- Meta.only_fields / "
        "Meta.exclude_fields removed it, or a declared attribute publishes the "
        f"name over a different value. {_BOUNDARY}"
        f"Publish {segment!r} on {name}, or drop the entry."
    )


def _relation_refusal(
    model: type[models.Model],
    entry: str,
    segment: str,
    owner: Any,
    field: Any,
    declared_on: str | None = None,
) -> str:
    """Build the message refusing a filter entry that cannot TRAVERSE a hop.

    A relation goes missing for one cause the column refusal above does not
    have, and it is the cause a reader cannot guess: the output compiler DROPS
    a to-one relation whose target model has no registered type. Telling them
    to "publish it" on the owning type is a no-op for that case -- no "Meta"
    edit brings the relation back, only registering a type for the target
    does -- so the target is named here and the remedy says so.

    Args:
        model: The model the filter input is built for.
        entry: The declaration key being refused.
        segment: The relation hop the owning type does not publish.
        owner: The compiled type that owns that hop.
        field: The model field for that hop, whose "related_model" is the
            target the compiler may be missing a type for.
        declared_on: The name of the type whose "Meta" declared the entry, or
            "None" when there is none to name.

    Returns:
        The full "ImproperlyConfigured" message.
    """
    name = _type_name(owner)
    related = getattr(field, "related_model", None)
    target = getattr(getattr(related, "_meta", None), "object_name", None)
    cause = (
        f"the output compiler dropped it because {target} has no registered "
        "DjangoObjectType"
        if target
        else "the output compiler dropped it"
    )
    remedy = (
        f"Publish {segment!r} on {name} -- registering a DjangoObjectType for "
        f"{target} if that is what is missing -- or drop the entry."
        if target
        else f"Publish {segment!r} on {name}, or drop the entry."
    )
    return (
        f"{_declaration(model, declared_on)} entry {entry!r} traverses "
        f"{segment!r}, which {name} does not publish as a relation -- "
        "Meta.only_fields / Meta.exclude_fields removed it, a declared "
        "attribute publishes the name over a resolver of its own or over a "
        f"leaf, or {cause}. {_BOUNDARY}"
        f"{remedy}"
    )


def _assert_entries_name_fields(
    model: type[models.Model],
    canonical: dict[str, tuple[str, ...] | None],
    declared_on: dict[str, str] | None = None,
) -> None:
    """Refuse a filter entry whose segments are not fields on the models they hop.

    Independent of any serving type, unlike every other check in this module:
    an entry naming nothing compiles to nothing whatever the projection says,
    so there is no type to measure it against and no reason to wait for one.

    That is also why a LOOKUP-SUFFIXED spelling is refused rather than exempted.
    "name__icontains" as a KEY is not how a lookup is declared -- lookups are
    the VALUE ("name": ("icontains",)) -- and "_split_filter_paths" files the
    whole key under the model's own leaves, where "_meta.get_field" does not
    answer to it and the field thunk drops it. It compiled to exactly as much
    as "pk" does: nothing. Exempting it refused one dead spelling and accepted
    the byte-equivalent other, which is the one thing this guard exists to
    stop.

    Args:
        model: The model the filter input is built for.
        canonical: The canonical "{path: lookups}" declaration being compiled.
        declared_on: The "{path: declaring type name}" provenance of that
            declaration, or "None" when no declaring class was named.

    Raises:
        ImproperlyConfigured: When a hop names no field on the model owning it,
            or when the path carries a tail past its last real hop.
    """
    for path in canonical:
        declarer = (declared_on or {}).get(path)
        hops = _walk_filter_path(model, path)
        for owner, segment in hops:
            try:
                owner._meta.get_field(segment)
            except FieldDoesNotExist:
                raise ImproperlyConfigured(
                    _unknown_entry_refusal(model, owner, path, segment, declarer)
                ) from None
        owner, segment = hops[-1]
        if path.split("__")[len(hops) :]:
            raise ImproperlyConfigured(
                _unknown_entry_refusal(
                    model, owner, path, path.split("__")[len(hops)], declarer
                )
            )


def _unknown_entry_refusal(
    model: type[models.Model],
    owner: type[models.Model],
    entry: str,
    segment: str,
    declared_on: str | None = None,
) -> str:
    """Build the message refusing an entry whose segment names nothing.

    "pk" is an ORM alias no "_meta.get_field" answers to, "id" names no column
    on a natural-key model, and a lookup spelled into the KEY
    ("name__icontains") names no field either. Every one of them compiled to
    NOTHING: the field thunk swallowed the "FieldDoesNotExist" and dropped the
    entry, so the declaration was accepted and ignored -- an operator reading
    their own "Meta" believed the list was filterable by that key while every
    request returned the unfiltered set.

    The entry is attributed to the type that DECLARED it, and the segment to
    the model that fails to hold it: a deep path hops models, and naming the
    hop's owner as the declarer sent the reader to a "Meta" that never held
    the entry.

    Args:
        model: The model the filter input is built for, named when there is no
            declaring type to name.
        owner: The model owning the failed hop, which is the model whose
            primary key the message can usefully name.
        entry: The declaration key being refused.
        segment: The segment of that key the owner does not hold.
        declared_on: The name of the type whose "Meta" declared the entry, or
            "None" when there is none to name.

    Returns:
        The full "ImproperlyConfigured" message.
    """
    return (
        f"{_declaration(model, declared_on)} entry {entry!r} names "
        f"{segment!r}, which is not a field on {owner._meta.object_name} -- its "
        f"primary key is spelled {owner._meta.pk.name!r}, and a lookup belongs "
        "in the entry's VALUE, not in its key. The entry compiled to nothing, "
        "so it was accepted and ignored; declare the real field name, or drop "
        "the entry."
    )


#: The projection checks currently on the stack, keyed by the model, the
#: identity of the serving type, and the surface being checked. Read the
#: re-entrancy note in "_assert_filter_surface_published" for why this exists;
#: a schema is built by one thread, so a plain set is enough.
_GUARDS_IN_FLIGHT: set[
    tuple[type[models.Model], int, frozenset[str], tuple[str, ...]]
] = set()


def _assert_filter_surface_published(
    model: type[models.Model],
    canonical: dict[str, tuple[str, ...] | None],
    node_type: Any,
    custom_filters: list | None = None,
    declared_on: dict[str, str] | None = None,
) -> None:
    """Refuse a filter surface naming a column its serving type projects away.

    "Meta.only_fields" / "Meta.exclude_fields" define a SECURITY BOUNDARY, not
    merely an output shape: a column a type hides must not be readable,
    orderable OR filterable through it. Filtering is the sharpest of the three
    axes — an "exact" lookup answers in ONE request and "icontains" walks the
    value prefix by prefix, with the whole lookup set advertised in the SDL as
    "<Model>FilterInput.<hidden>" so the oracle needs no guessing.

    The answer comes from "core.output_compiler.publishes_column_value", the
    ONE predicate both projection axes consume. It replaces a hand copy of the
    output compiler's skip rules that read "Meta" directly, and the copy had
    already drifted: a column re-published verbatim by a declared attribute is
    ORDERABLE (the compiled type demonstrably serves its value) and was refused
    here. Two implementations of "hidden" is the defect; the predicate is the
    fix, and every rule below is either the predicate or the one question it
    deliberately declines to answer.

    That question is TRAVERSAL. "author__bio" leaks nothing about "author_id",
    so an intermediate hop asks only whether the relation is published
    ("_traversed_type") and then measures the tail against the type that
    relation resolves to. A LAST hop is different: a relation declared without a
    tail is filtered by the TARGET's primary key. A CONCRETE one -- a forward
    foreign key -- owns that key as a column on THIS model and is the
    predicate's own rule 2; a reverse foreign key or a many-to-many owns no
    column here at all, so the predicate declines it and the key has to be
    asked of the target type directly. Skipping that second shape refused the
    byte-identical "posts__id" spelling while letting "posts" through.

    The contradiction is REFUSED, not silently dropped, following the guard
    2.2.0 added for a projection that would otherwise be discarded: dropping
    the entry would accept an option and ignore it, which is the exact defect
    that guard exists to prevent.

    Measured PER SERVING TYPE, and its caller measures the UNION of every
    declaration that will share the compiled input: the filter input is cached
    per MODEL and every context converges on the model's ROOT declaration, so
    two "DjangoObjectType"s over one model in one schema share the single
    "<Model>FilterInput" name and the widened shape one of them asks for is
    served to both. See the union loop in "build_filter_input_type". The whole
    path is walked eagerly instead of leaning on the recursive relation build,
    because that recursion happens inside the field thunk and graphql-core
    rewraps anything a thunk raises as a "TypeError", which would bury the
    explanation.

    Fails CLOSED on every hop of a path: a relation the SDL does not publish
    stops the walk with a refusal, because the output compiler DROPS a to-one
    relation whose target model has no registered type, and keeping a nested
    filter input over a model unreachable in the schema is a substring oracle
    over rows nothing can name.

    An "@filter_field" body is user Python and cannot be read at build time,
    but its NAME can: a method spelled like a column the type hides publishes
    the very same "<Model>FilterInput.<hidden>" the paths above refuse, and it
    is the one-line rename every refusal here would otherwise invite. The body
    stays a documented open boundary.

    Re-entrant, and it has to be. Reading a compiled field map FORCES it, and a
    nested list field compiles its filter argument from INSIDE the host type's
    own field thunk: "Comment" filtering by its "post" relation is guarded from
    inside "Post", whose thunk mounts the comment list, so forcing "Post" from
    that guard re-enters a "cached_property" already on the stack and recurses
    until the interpreter stops it. The inner entry is skipped rather than
    answered, and nothing is lost by that: it is the SAME (model, serving type)
    check as the outer one, which resumes and answers it once the map it was
    waiting for is built.

    Args:
        model: The model the filter input is built for.
        canonical: The canonical "{path: lookups}" declaration being compiled.
        node_type: One COMPILED type serving the model's rows in the schema
            being built. Never "None": a caller that named no type contributes
            no serving type at all, so the loop that drives this simply does
            not run (see "_serving_types").
        custom_filters: The "(arg_name, method, metadata)" triples collected
            from "@filter_field"-decorated methods, or "None".
        declared_on: The "{path: declaring type name}" provenance of the
            declaration, so a refusal names the "Meta" the entry has to leave.

    Raises:
        ImproperlyConfigured: When a declared path or custom-filter name reaches
            a column the serving type does not publish.
    """
    from django_graphex.core.output_compiler import publishes_column_value

    # The DECLARATION is part of the key, not just the type: a re-entry always
    # carries the same one, so keying on it still breaks the cycle -- while a
    # third context reaching this model with paths of its own is a different
    # question and gets answered instead of skipped.
    in_flight = (
        model,
        id(node_type),
        frozenset(canonical),
        tuple(name for name, _f, _m in custom_filters or ()),
    )
    if in_flight in _GUARDS_IN_FLIGHT:
        return
    _GUARDS_IN_FLIGHT.add(in_flight)
    try:
        for path in canonical:
            current = node_type
            declarer = (declared_on or {}).get(path)
            hops = _walk_filter_path(model, path)
            for index, (owner, segment) in enumerate(hops):
                # Every hop is a real field: "_assert_entries_name_fields" ran
                # first and refused any path with a segment the model does not
                # hold. A trailing lookup spelling ("icontains") is never a hop
                # -- the walk stops at the first non-relation segment.
                field = owner._meta.get_field(segment)
                last = index == len(hops) - 1
                if last and getattr(field, "concrete", False):
                    if not publishes_column_value(current, field):
                        raise ImproperlyConfigured(
                            _refusal(model, path, segment, current, declarer)
                        )
                    break
                target = _traversed_type(current, segment)
                if target is None:
                    raise ImproperlyConfigured(
                        _relation_refusal(
                            model, path, segment, current, field, declarer
                        )
                    )
                if last:
                    # A relation declared without a tail is filtered by the
                    # TARGET's primary key. A CONCRETE one (a forward FK) owns
                    # that key as a column here and is answered above by the
                    # predicate's rule 2; a reverse FK or a many-to-many owns
                    # NO column on this model, so the predicate declines it and
                    # the key has to be asked of the target type directly --
                    # otherwise the byte-identical "posts__id" spelling of the
                    # same query is refused while "posts" is not. A generic
                    # foreign key resolves to no single model, so it has no key
                    # to ask any type about and leaves "pk" None.
                    related = getattr(field, "related_model", None)
                    pk = getattr(getattr(related, "_meta", None), "pk", None)
                    if pk is not None and not publishes_column_value(target, pk):
                        raise ImproperlyConfigured(
                            _refusal(model, path, pk.name, target, declarer)
                        )
                    break
                current = target

        for arg_name, _fn, _meta in custom_filters or []:
            try:
                field = model._meta.get_field(arg_name)
            except FieldDoesNotExist:
                # A name that is not a column says nothing about what the body
                # touches, which is the boundary this guard cannot cross.
                continue
            if not publishes_column_value(node_type, field):
                raise ImproperlyConfigured(
                    f"{model._meta.object_name}: @filter_field method "
                    f"{arg_name!r} is spelled like a column "
                    f"{_type_name(node_type)} does not publish, so it compiles "
                    "the same <Model>FilterInput field a filter_fields entry "
                    "naming it is refused. Rename the method, or publish "
                    f"{arg_name!r} on {_type_name(node_type)}."
                )
    finally:
        _GUARDS_IN_FLIGHT.discard(in_flight)


#: Instance attribute holding a compiled filter input's accumulated
#: ``{path: lookups}`` declaration. The field thunk closes over that very dict,
#: so widening it (plus ``_recompile_filter_input``) reshapes the type WITHOUT
#: minting a second instance under the same ``<Model>FilterInput`` name.
_CANONICAL_PATHS_ATTR = "_gdx_canonical_filter_paths"

#: Instance attribute holding the "{path: declaring type name}" provenance of a
#: cached filter input's accumulated declaration. The input is shared per MODEL,
#: so the type that contributed a path is not always the type serving the rows a
#: refusal measured -- and "drop the entry" has to name a "Meta" that holds it.
_DECLARED_ON_ATTR = "_gdx_filter_declared_on"

#: Instance attribute holding every COMPILED type that will serve rows through
#: a cached filter input. One model has ONE ``<Model>FilterInput`` name, so two
#: ``DjangoObjectType``s over that model share the instance -- and the union
#: they end up sharing has to clear the projection of BOTH.
_SERVING_TYPES_ATTR = "_gdx_filter_serving_types"


def _serving_types(gql_input_type: Any, node_type: Any) -> list[Any]:
    """Return every type that will serve rows through a filter input.

    Args:
        gql_input_type: A filter input previously built by this module, or
            "None" when this context is the first to build it.
        node_type: The type this context is compiling the input for, or "None"
            when the caller named none.

    Returns:
        The recorded serving types plus "node_type", identity-deduped, with the
        recorded list left untouched so a refusal cannot mutate the cache.
    """
    served = list(getattr(gql_input_type, _SERVING_TYPES_ATTR, None) or ())
    if node_type is not None and not any(seen is node_type for seen in served):
        served.append(node_type)
    return served


def _record_serving_type(gql_input_type: Any, node_type: Any) -> None:
    """Remember that "node_type" serves rows through this filter input.

    Called only once the union has cleared that type's projection, so the
    record is of a type the input is allowed to serve.

    Args:
        gql_input_type: The cached filter input.
        node_type: The compiled type to record, or "None" for a caller that
            named none (recorded as nothing, exactly as it is measured).
    """
    if node_type is None:
        return
    served = getattr(gql_input_type, _SERVING_TYPES_ATTR, None)
    if served is None:
        served = []
        setattr(gql_input_type, _SERVING_TYPES_ATTR, served)
    if not any(seen is node_type for seen in served):
        served.append(node_type)


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


def _declared_on(gql_input_type: Any) -> dict[str, str]:
    """Return the provenance recorded on a cached filter input.

    Args:
        gql_input_type: A filter input previously built by this module, or
            "None" when this context is the first to build it.

    Returns:
        The "{path: declaring type name}" map, empty when nothing recorded one.
    """
    return dict(getattr(gql_input_type, _DECLARED_ON_ATTR, None) or {})


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
    node_type: Any = None,
    declared_on: str | None = None,
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
        declared_on: The name of the class whose "Meta.filter_fields" this
            build compiles, carried onto every path it contributes so a
            refusal names the "Meta" the entry has to leave. Left "None" by a
            direct caller, which leaves the refusal naming the model.
        node_type: The COMPILED "GraphQLObjectType" that will serve this
            model's rows, which is what the projection boundary is measured
            against. The compiler NAMES it (see
            "core.schema_compiler._filter_arg") because no index can: the
            registry is model-keyed and last-wins, and a type opts out of it
            entirely with the public "Meta.skip_registry". Left "None", it is
            recovered from "registry" as a best effort for direct callers of
            this builder and of the "FilterBackend.build" seam.

    Returns:
        A "GraphQLInputObjectType", or "None" when no filterable fields were
        declared (and no custom filters provided).
    """
    if not filter_fields and not custom_filters:
        return None

    if registry is None:
        registry = get_global_registry()

    if node_type is None:
        node_type = getattr(
            getattr(registry.get_type_for_model(model), "_meta", None),
            "graphql_output_type",
            None,
        )

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

    # Measure the UNION that will actually be served, against EVERY type that
    # will serve it. The declaration in front of this call is neither: the input
    # is shared per MODEL, so two ``DjangoObjectType``s over one model in one
    # schema resolve to the same instance, and the second context's build
    # WIDENS the shape the first one already handed out. Checking only the
    # declaration being compiled left the narrower type's list field filterable
    # by a column it projects away, with no build failure at all -- and
    # per-type inputs are not buildable without a ``<Type>FilterInput`` SDL
    # rename.
    #
    # Both run BEFORE any widening below, so a refused build never mutates the
    # declaration every other context already references.
    #
    # "mine" is the provenance of the paths THIS call contributes, merged below
    # with whatever earlier contexts recorded on the cached instance, so a
    # refusal over a path another type declared names THAT type.
    mine = {path: declared_on for path in normalized} if declared_on else {}

    _assert_entries_name_fields(model, normalized, mine)

    # Measured in a LOOP, because the assertion can invalidate its own input.
    # Reading a compiled field map FORCES it, and forcing one re-enters this
    # builder for the same model (a nested list field compiles its filter
    # argument from inside the host type's own field thunk) -- so the cache
    # entry this build is about to serve can be BORN inside the very assertion
    # that was supposed to clear it. Measured once against the pre-assertion
    # read, the guard cleared a shape that no longer existed and the branch
    # below then recorded this type as a server of paths nothing had checked.
    # Re-reading and measuring again until the cache stops moving is what makes
    # the measurement unstaleable; it terminates because an entry is minted at
    # most once per key, so the second pass reads the same instance.
    while True:
        cached = cache.get(cache_key)
        union = dict(_canonical_paths(cached)) if cached is not None else {}
        _union_filter_paths(union, normalized)
        provenance = {**_declared_on(cached), **mine}
        for serving in _serving_types(cached, node_type):
            _assert_filter_surface_published(
                model, union, serving, custom_filters, provenance
            )
        if cache.get(cache_key) is cached:
            break

    # The cache read above is the POST-assertion one: reusing a pre-assertion
    # miss built and registered a SECOND instance under the one
    # ``<Model>FilterInput`` name, which graphql-core rejects outright.
    if cached is not None:
        _record_serving_type(cached, node_type)
        setattr(cached, _DECLARED_ON_ATTR, provenance)
        if _union_filter_paths(_canonical_paths(cached), normalized):
            _assert_no_custom_filter_collision(
                model, _canonical_paths(cached), custom_filters
            )
            _recompile_filter_input(cached)
        return cached

    # The accumulated declaration this type compiles from. Mutable and captured
    # by the field thunk below, so a later widening recompiles from it.
    canonical = dict(normalized)
    _assert_no_custom_filter_collision(model, canonical, custom_filters)

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
            # Every own leaf is a real field: "_assert_entries_name_fields" ran
            # before this thunk was built and refused any entry naming
            # something the model does not hold -- including a lookup spelled
            # into the KEY, which lands here as a whole compound name and used
            # to be swallowed by a "FieldDoesNotExist" pass.
            field = model._meta.get_field(field_name)
            lookups_type = _lookups_input_type(
                model, field, field_name, lookups, registry
            )
            # Wire key = camelCase; out_name = snake ORM field name (footgun).
            out[to_camel_case(field_name)] = GraphQLInputField(
                lookups_type, out_name=field_name
            )

        for head, sub_fields in relations.items():
            # A relation head by construction: "_split_filter_paths" only files
            # a head here when "_relation_model" already answered for it.
            related = _relation_model(model, head)
            # The nested build re-runs the guard against the RELATED model's own
            # canonical declaration, which may reach paths the walk above never
            # saw. Hand it the type this very relation resolves to, so the
            # nested boundary is the one THIS schema serves rather than
            # whichever type the model-keyed registry happens to hold.
            nested = build_filter_input_type(
                related,
                sub_fields,
                registry,
                registries=registries,
                node_type=_traversed_type(node_type, head),
                declared_on=declared_on,
            )
            if nested is not None:
                out[to_camel_case(head)] = GraphQLInputField(nested, out_name=head)

        for head, lookups in relation_direct.items():
            related = _relation_model(model, head)
            pk_lookups = _pk_lookups_input_type(model, head, related, lookups)
            out[to_camel_case(head)] = GraphQLInputField(pk_lookups, out_name=head)

        # Collisions with an already-compiled key are refused up front by
        # ``_assert_no_custom_filter_collision`` (a raise from inside this thunk
        # would reach the caller wrapped in graphql-core's TypeError).
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
    setattr(input_type, _DECLARED_ON_ATTR, provenance)
    # Carry the types this instance serves too, so a LATER context widening it
    # re-measures the grown union against the ones already served.
    _record_serving_type(input_type, node_type)
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


def build_subscription_filter_input_type(
    model: type[models.Model],
    field_names: Sequence[str],
    registry: Registry | None = None,
) -> GraphQLInputObjectType | None:
    """Build the FLAT "<Model>SubscriptionFilterInput" for a subscription field.

    Deliberately a separate builder from "build_filter_input_type", not a mode
    of it. The query filter input is wide by design — every declared lookup,
    nested relation inputs, recursive and/or/not combinators, and one cached
    canonical instance per model that later contexts WIDEN in place. A
    subscription filter is the opposite on all four counts:

      * only "exact"/"iexact"/"in"/"isnull" (the 2.0.1 allow list), because
        event delivery turns any ordered or pattern lookup into a boolean
        oracle over a column the subscriber may not select;
      * FLAT — no relation traversal, which the 2.0.1 validator rejects for the
        same reason;
      * no combinators, because the delivery path consumes a flat mapping of
        ORM lookups that cannot express them;
      * NOT cached, and NOT sharing the query builder's per-model cache slot —
        widening one from the other would silently hand a subscriber the query's
        full lookup set.

    Every field carries the snake ORM "out_name", exactly like the query
    builder, so a camelCase wire key maps back to a real column.

    Args:
        model: The subscribed Django model.
        field_names: The subscription's PROJECTED output field names (what
            "Meta.only_fields"/"Meta.exclude_fields" left), in model order.
        registry: The registry providing the shared choices enums; defaults to
            the global registry.

    Returns:
        A "GraphQLInputObjectType", or "None" when the projection left no
        filterable field.
    """
    if not field_names:
        return None

    if registry is None:
        registry = get_global_registry()

    object_name = model._meta.object_name
    fields: dict[str, GraphQLInputField] = {}
    for field_name in field_names:
        try:
            field = model._meta.get_field(field_name)
        except FieldDoesNotExist:  # pragma: no cover - projection yields real fields
            continue
        if field.is_relation:
            # Relations are filtered by primary key (the payload carries pks).
            scalar: Any = _pk_scalar(field.related_model)
        elif getattr(field, "choices", None):
            scalar = _choices_enum(field, registry)
        else:
            scalar = _field_scalar(field)
        camel = to_camel_case(field_name)
        lookups_name = f"{object_name}{camel[:1].upper()}{camel[1:]}SubscriptionLookups"
        fields[camel] = GraphQLInputField(
            _build_lookups_type(lookups_name, scalar, SUBSCRIPTION_FILTER_LOOKUPS),
            out_name=field_name,
        )

    if not fields:  # pragma: no cover - a non-empty projection yields fields
        return None

    name = f"{object_name}SubscriptionFilterInput"
    return GraphQLInputObjectType(
        name=name,
        fields=fields,
        extensions={"gdx": GdxFilterInputSpec(model=model, name=name)},
    )


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
