"""Native root-ObjectType compiler.

Turns a NATIVE root "ObjectType" (Query / Mutation / Subscription -- a
"native.base.ObjectType" subclass) into a graphql-core "GraphQLObjectType"
whose per-field types are the CANONICAL native instances
("_meta.graphql_output_type" carrying extensions["gdx"]). This is the seam
that lets "DjangoGraphQLSchema" build a "graphql.GraphQLSchema" directly,
without the duplicate-name TypeError.

(v2.0 is native-only: a leftover "graphene.ObjectType" root is NOT accepted --
see "_is_plain_object_type". The graphene backend was removed entirely.)

Per-field-kind dispatch:
- raw graphql-core "GraphQLField" attribute (e.g. a native mutation field) ->
  REUSE as-is.
- "DjangoObjectField" (single object) -> build a native "GraphQLField" whose
  type is the canonical "field.type._meta.graphql_output_type", with converted
  args and the field's wired resolver.
- a plain scalar field (declared via "field(GraphQLString)" etc.) -> build a
  graphql-core scalar "GraphQLField".
- "DjangoListObjectField" / "DjangoFilterListField" /
  "DjangoFilterPaginateListField" / "DjangoNestedListObjectField" -> RAISE
  "NotImplementedError" naming the field plus the WU that will add the builder.
  NO silent skip, NO graphene fallback.
"""

from __future__ import annotations

from copy import copy
from typing import Any

from graphql import (
    GraphQLArgument,
    GraphQLField,
    GraphQLList,
    GraphQLNonNull,
    GraphQLObjectType,
)
from graphql.execution import default_field_resolver

from django_graphex._strconv import to_camel_case
from django_graphex.core.base import (
    SchemaRegistries,
    default_schema_registries,
)
from django_graphex.core.bridge import GdxPayload
from django_graphex.core.ir import GdxMeta

# Map of not-yet-supported field-kind class names → the WU that owns the native
# builder. Used to produce a precise NotImplementedError instead of a silent skip.
#
# WU6a (this slice) emptied the list/filter/pagination kinds: the native builders
# now exist (see _build_list_object_field / _build_filter_list_field). Anything
# left here still raises a precise NotImplementedError instead of a silent skip.
_DEFERRED_FIELD_KINDS: dict[str, str] = {}


def _rendered_field_name(field: Any, attr_name: str) -> str:
    """Return the wire name graphene would render for a declared field.

    graphene's MountedType carries an explicit name attribute (the
    name= kwarg, e.g. CustomDate(name="date")). When set, graphene uses
    it VERBATIM as the final SDL field name — NO camelCase pass is applied (the
    explicit name is already the wire name). When unset (None), graphene
    camelCases the snake_case attribute name under auto_camelcase=True.

    Mirroring this is REQUIRED for full-schema SDL parity: the test schema
    declares date_ = CustomDate(name="date") / datetime_ / time_ to
    dodge the Python keyword-collision trailing underscore; graphene renders
    date / datetime / time while a naive to_camel_case(attr)
    would render date_ / datetime_ / time_ — an SDL divergence.

    Args:
        field: The mounted graphene field (may expose an explicit .name).
        attr_name: The snake_case attribute name under which the field is
            declared on the root.

    Returns:
        The explicit field.name when set, else to_camel_case(attr_name).
    """
    explicit = getattr(field, "name", None)
    if explicit:
        return explicit
    return to_camel_case(attr_name)


def _stamp_required_perms(gql_field: GraphQLField, perms: Any) -> GraphQLField:
    """Stamp extensions["gdx_required_perms"] on a built root field (P0).

    Records the permissions a caller must hold to see this field, so the P1
    pruner can rebuild a per-signature schema. The value is a frozenset for
    CRUD / declared / mutation fields, or a per-action dict{action: frozenset}
    for subscription fields. Uses the SAME extensions merge idiom as the
    gdx_mutation_source precedent (mutation.py) so the label rides the field
    verbatim through a clone.

    Args:
        gql_field: The compiled graphql-core field to label.
        perms: The composite perms (a frozenset or per-action dict).

    Returns:
        The same field, with its extensions merged in place.
    """
    gql_field.extensions = {
        **(gql_field.extensions or {}),
        "gdx_required_perms": perms,
    }
    return gql_field


def _label_model_field(
    gql_field: GraphQLField, descriptor: Any, action: str
) -> GraphQLField:
    """Stamp composite perms on a CRUD model field (retrieve / list).

    An explicit descriptor.required_perms override (P0 opt-in) wins; else the
    perms come from the composite table keyed by the field's model + action.

    Args:
        gql_field: The compiled graphql-core field.
        descriptor: The Django*Field descriptor (exposes .model and an
            optional .required_perms override).
        action: The CRUD action the field represents (retrieve / list).

    Returns:
        The labeled field.
    """
    from django_graphex.core.perm_labels import required_perms_for

    override = getattr(descriptor, "required_perms", None)
    if override is not None:
        perms = frozenset(override)
    else:
        perms = required_perms_for(descriptor.model, action)
    return _stamp_required_perms(gql_field, perms)


def _collect_root_attrs(root: type) -> dict[str, Any]:
    """Collect native mutation GraphQLField attributes the metaclass dropped.

    The ObjectType metaclass does NOT mount raw graphql-core
    GraphQLField objects (e.g. native mutation fields returned by
    DjangoModelType.CreateField()): they stay as plain class attributes in
    __dict__ but never enter _meta.fields. Walk the MRO so subclassed
    roots still surface them; the most-derived class wins on name collisions.

    Membership in _NATIVE_FIELD_REGISTRY (not a blanket
    isinstance(value, GraphQLField) scan) is the gate: a recovered attribute
    is treated as a native mutation field ONLY when it is one of the exact
    GraphQLField instances the mutation machinery registered. This prevents
    an unrelated user-declared raw GraphQLField class attribute from being
    silently mounted onto the native root.

    Args:
        root: The graphene root ObjectType class.

    Returns:
        Mapping of attribute name → GraphQLField for every dropped native
        mutation field found on the root (and its bases).
    """
    from django_graphex.mutation import (
        _NATIVE_FIELD_IDENTITIES,
        _NATIVE_FIELD_REGISTRY,
    )

    # Identity set of EVERY native mutation GraphQLField ever built; membership
    # proves a recovered attr is a native mutation field. We union the current
    # registry values (defensive, in case a field is registered out-of-band) with
    # the cumulative identity set so a field is still recovered after its single
    # ``(model, op)`` registry slot was overwritten by a sibling subclass for the
    # same model (DjangoModelType / DjangoModelMutation last-built-wins).
    native_field_ids = {id(f) for f in _NATIVE_FIELD_REGISTRY.values()}
    native_field_ids |= _NATIVE_FIELD_IDENTITIES

    found: dict[str, Any] = {}
    for klass in reversed(root.__mro__):
        for attr_name, value in vars(klass).items():
            if isinstance(value, GraphQLField) and id(value) in native_field_ids:
                found[attr_name] = value
    return found


def _collect_dropped_native_fields(root: type) -> dict[str, Any]:
    """Recover NativeMountedField attrs the graphene root metaclass dropped.

    S8c silent-drop guard: the Django*Field classes are re-parented off graphene
    Field onto NativeMountedField. graphene's ObjectType metaclass collects
    fields via yank_fields_from_attrs, which keeps ONLY graphene
    MountedType / UnmountedType instances — so a NativeMountedField
    declared on a graphene root (e.g. class Query(graphene.ObjectType):
    users = DjangoFilterListField(UserType)) NEVER reaches _meta.fields and
    would vanish from the compiled schema.

    This walks the root MRO (base-first, most-derived wins on a name collision —
    graphene parity) and recovers every class-body NativeMountedField so the
    native root compiler can mount it. A native ObjectType root already
    surfaces these via _mount_descriptor_fields (so they are in _meta.fields
    and not re-added here); this recovery is purely for the transitional
    graphene-root public API. Returns the recovered fields ordered by graphene
    creation_counter so declaration order (hence SDL field order) is preserved.

    Args:
        root: The root ObjectType class (graphene or native).

    Returns:
        An ordered {attr_name: NativeMountedField} mapping for every dropped
        native field, sorted by declaration order.
    """
    from django_graphex.core.descriptors import NativeMountedField

    found: dict[str, Any] = {}
    for klass in reversed(root.__mro__):
        for attr_name, value in vars(klass).items():
            if isinstance(value, NativeMountedField):
                found[attr_name] = value
    # Order by declaration (creation_counter) so SDL field order is byte-stable.
    ordered = sorted(found.items(), key=lambda kv: kv[1].creation_counter)
    return dict(ordered)


def _is_subscription_field(field: Any) -> bool:
    """Return whether *field* is a subscription root field (WU7).

    Duck-typed (NOT a hard import django_graphex.subscriptions) so the native
    root compiler never pulls the optional [subscriptions] extra (Channels)
    onto the base build path. A subscription root field is a graphene-mounted
    field whose type is a Subscription subclass carrying the native
    compile-path method _build_native_field (added by WU6). The class name
    gate (SubscriptionField) avoids matching an unrelated field that happens
    to expose a callable of that name.

    Args:
        field: A graphene-mounted root field.

    Returns:
        True when *field* is a SubscriptionField whose target class
        builds a native subscription field.
    """
    if type(field).__name__ != "SubscriptionField":
        return False
    target = getattr(field, "type", None)
    return callable(getattr(target, "_build_native_field", None))


def _build_object_field(
    field: Any, registries: SchemaRegistries | None = None
) -> GraphQLField:
    """Build a native GraphQLField for a DjangoObjectField (single object).

    The field TYPE is the canonical native GraphQLObjectType stored on the
    target DjangoObjectType._meta.graphql_output_type — the SAME instance the
    shared output registry holds (identity-stable). The resolver is wired via the
    field's own wrap_resolve so it is NOT a dead no-op.

    Args:
        field: A DjangoObjectField instance (graphene-mounted).
        registries: The SchemaRegistries pair (threaded for uniformity; the
            canonical instance is read from _meta). Defaults to the global
            pair (byte-identical, item-b B1).

    Returns:
        A graphql-core GraphQLField.
    """
    from django_graphex.core._args import to_graphql_argument
    from django_graphex.core.base import resolved_output_type

    registries = _resolve_registries(registries)
    # item-b (B5): resolve to THIS schema's FORKED instance when a non-default
    # pair is in play; default pair -> the class-def instance -> byte-identical.
    output_type = resolved_output_type(field.type, registries)
    if output_type is None:  # pragma: no cover — defensive
        raise RuntimeError(
            f"DjangoObjectField target {field.type!r} has no compiled "
            "graphql_output_type. compile_all_outputs() must run before "
            "native root compilation."
        )

    args = {
        arg_name: to_graphql_argument(arg, name=arg_name)
        for arg_name, arg in (field.args or {}).items()
    }

    # Wire the field's real resolver (built-in object_resolver or a custom one)
    # so the native field actually resolves — NOT a dead no-op.
    resolve = field.wrap_resolve(default_field_resolver)

    return GraphQLField(
        output_type,
        args=args,
        resolve=resolve,
        description=getattr(field, "description", None),
    )


def _build_scalar_field(
    field: Any,
    *,
    source_cls: type | None = None,
    field_name: str | None = None,
    registries: SchemaRegistries | None = None,
) -> GraphQLField:
    """Convert a plain graphene scalar field to a graphql-core GraphQLField.

    Args:
        field: A plain graphene.Field whose mounted type is a scalar/enum.
        source_cls: The source ObjectType class declaring the field; used to
            recover a resolve_<field_name> parent resolver (graphene parity).
        field_name: The snake_case field name (for the resolve_<name> lookup).
        registries: The SchemaRegistries pair the current build compiles
            against, threaded into the wrapped-type compile so an inner
            django-graphex output type resolves to THIS pair's forked instance;
            defaults to the global pair (byte-identical, item-b B1).

    Returns:
        A graphql-core GraphQLField.
    """
    # Resolve the (possibly native-wrapped) field type. A bare scalar leaf goes
    # through ``_unwrap_graphql_type`` verbatim (byte-identical to the historical
    # behavior), while a native ``NativeNonNull`` / ``NativeList`` wrapper — e.g.
    # ``IntField(required=True)`` / ``Field(scalar, required=True)`` at ROOT level
    # — is recursed into its graphql-core ``GraphQLNonNull`` / ``GraphQLList``
    # shape. Without this, a required scalar root field would raise a ``TypeError``
    # in ``_unwrap_graphql_type`` (which rejects the lazy wrapper). The declared
    # (non-root) field path already routes through ``_compile_wrapped_field_type``.
    #
    # ``registries`` MUST be threaded: this is the arm a WRAPPED native output
    # type lands on (``field(NativeList(SomeType))`` matches no typed arm of the
    # root loop), and without the pair the inner type resolves against the
    # process-global DEFAULT pair — a cross-schema leak ``assert_schema_pair_isolation``
    # then rejects, making a wrapped native root field unbuildable under ``registries=``.
    gql_type = _compile_wrapped_field_type(field.type, _resolve_registries(registries))
    args = {}
    if getattr(field, "args", None):
        from django_graphex.core._args import to_graphql_argument

        args = {
            arg_name: to_graphql_argument(arg, name=arg_name)
            for arg_name, arg in field.args.items()
        }
    parent_resolver = _resolver_for(source_cls, field_name)
    resolve = field.wrap_resolve(parent_resolver)
    return GraphQLField(
        gql_type,
        args=args,
        resolve=resolve,
        description=getattr(field, "description", None),
    )


def _get_unbound_function(func: Any) -> Any:
    """Return *func* unbound from its owning class (graphene-free inline).

    Replaces graphene.utils.get_unbound_function.get_unbound_function (S-args-8
    follow-up, decision #1603 — CLEAN BREAK). graphene's helper is a trivial 3-line
    routine: a bound method (__self__ is truthy) is returned as-is, while a
    method retrieved off a CLASS via getattr (func.__self__ is falsy /
    absent) is unwrapped to its plain __func__ so graphql-core can call it as a
    bare (root, info, **kw) resolver. Inlined here so a pure-native root with a
    resolve_<name> method no longer pulls graphene at compile time.

    Args:
        func: A callable, typically a method object fetched via
            getattr(cls, "resolve_<name>").

    Returns:
        The function unbound from its class when applicable, else *func* verbatim.
    """
    if not getattr(func, "__self__", True):
        return func.__func__
    return func


def _resolver_for(source_cls: type | None, field_name: str | None) -> Any:
    """Return the parent resolver for a field, or the default resolver.

    Mirrors graphene's TypeMap wiring: the source ObjectType's
    resolve_<field_name> (unbound) when declared, else graphql-core's default
    attribute/dict resolver. field.wrap_resolve still prefers a field-level
    resolver over this fallback.

    Args:
        source_cls: The ObjectType class declaring the field (may be None).
        field_name: The snake_case field name (may be None).

    Returns:
        The parent resolver callable.
    """
    if source_cls is None or field_name is None:
        return default_field_resolver

    method = getattr(source_cls, f"resolve_{field_name}", None)
    if method is not None:
        return _get_unbound_function(method)
    return default_field_resolver


# Module-level memo so repeated references to the same plain graphene ObjectType
# (within one schema build OR across roots) compile to ONE native instance —
# identity-stable, no duplicate-name TypeError. Keyed by the source class.
#
# item-b (B2): this dict is the DEFAULT pair's plain-object cache namespace —
# ``default_schema_registries().plain_object_cache`` IS this very object (bound by
# identity). Every entrypoint resolves its cache from the threaded
# ``SchemaRegistries`` pair, so the default path keeps writing here (byte-identical)
# while a forked pair (later slices) owns its own namespace.
_PLAIN_OBJECT_TYPE_CACHE: dict[type, GraphQLObjectType] = {}


def _resolve_registries(registries: SchemaRegistries | None) -> SchemaRegistries:
    """Return *registries* or the process-wide default pair (byte-identical)."""
    return registries if registries is not None else default_schema_registries()


def _is_plain_object_type(graphene_cls: Any) -> bool:
    """Return whether *graphene_cls* is a plain graphene.ObjectType subclass.

    "Plain" excludes the django-graphex output container/model types
    (DjangoObjectType / DjangoListObjectType), which carry their own
    canonical _meta.graphql_output_type and are compiled by the output
    registry — NOT on-the-fly here. It also excludes scalars/enums (handled by
    _build_scalar_field) and non-class field types (wrappers).

    Args:
        graphene_cls: The mounted field type (field.type).

    Returns:
        True when the field type is a native plain ObjectType (the
        S-ROOTS-b marker — e.g. ErrorType) that is NOT a django-graphex
        container/model output type, a union/interface, or an InputType.
        A leftover graphene.ObjectType is rejected (v2.0 is native-only;
        the graphene-root compile path was removed).
    """
    import inspect

    if not inspect.isclass(graphene_cls):
        return False

    # Exclude django-graphex container/model output types — they own a canonical
    # compiled type built by the output registry, reused via
    # ``_plain_django_output_type``. Checked FIRST so neither the native-marker nor
    # the graphene fallback below ever mis-claims a ``DjangoObjectType`` /
    # ``DjangoListObjectType`` as an on-the-fly plain object.
    from django_graphex.types import DjangoListObjectType, DjangoObjectType

    if issubclass(graphene_cls, (DjangoObjectType, DjangoListObjectType)):
        return False

    # Polymorphic types (DjangoUnionType / DjangoInterfaceType, DEFECT #8) share
    # the native ObjectType base but compile to graphql-core ``GraphQLUnionType`` /
    # ``GraphQLInterfaceType`` — NOT a plain ``GraphQLObjectType``. Excluded here
    # (BEFORE the native-marker branch below) so a union/interface field is routed
    # to ``compile_polymorphic_type`` instead of being mis-compiled as an object.
    from django_graphex.core.polymorphic_compiler import (
        is_interface_type,
        is_union_type,
    )

    if is_union_type(graphene_cls) or is_interface_type(graphene_cls):
        return False

    # NATIVE-MARKER (S-ROOTS-b) — checked BEFORE the graphene fallback. A native
    # plain ``ObjectType`` (e.g. ``ErrorType``) is a ``native.base.ObjectType``
    # subclass with ``type(cls) is pydantic.ModelMetaclass``; it is NOT a
    # ``graphene.ObjectType``, so without this branch a native ErrorType would
    # fall through to the scalar arm (``_unwrap_graphql_type``) and KeyError /
    # silently vanish (the silent-drop EPICENTER). ``InputType`` is EXCLUDED: it
    # shares the native base but is an INPUT type, never a plain output object.
    from django_graphex.core.base import InputType
    from django_graphex.core.base import ObjectType as NativeObjectType

    if issubclass(graphene_cls, NativeObjectType):
        if issubclass(graphene_cls, InputType):
            return False
        return True

    # S-del-backend-11: the graphene-ROOT compile capability is removed. A plain
    # output object MUST be a native ``ObjectType`` (the branch above); a leftover
    # ``graphene.ObjectType`` is no longer recognised as a plain object type (v2.0
    # cannot accept a graphene root). Anything else falls through to the scalar arm.
    return False


def _compile_plain_object_type(
    graphene_cls: type, registries: SchemaRegistries | None = None
) -> GraphQLObjectType:
    """Compile a plain graphene.ObjectType to a native type (memoized).

    Single-instance, on-the-fly. Each declared field becomes a native field:
    - a nested plain graphene.ObjectType field recurses through this builder
      (so Field(Plain) chains compile fully native, never falling into the
      scalar arm);
    - a DjangoObjectType / DjangoListObjectType field reuses its
      canonical _meta.graphql_output_type;
    - anything else is a scalar/enum converted via _unwrap_graphql_type.

    Resolvers are wired EXACTLY like graphene's TypeMap: the field's own
    resolver wins; otherwise the source class' resolve_<name> method (if
    any) or graphql-core's default attribute/dict resolver. The compiled type
    carries extensions['gdx'] (D8) with the source graphene class so
    dual-backend read-sites can recover resolve_<field> methods.

    Args:
        graphene_cls: A plain graphene.ObjectType subclass.
        registries: The SchemaRegistries pair owning the plain-object cache
            namespace; defaults to the global pair (byte-identical, item-b B1/B2).

    Returns:
        The canonical (memoized) native GraphQLObjectType for *graphene_cls*.
    """
    registries = _resolve_registries(registries)
    cache = registries.plain_object_cache
    cached = cache.get(graphene_cls)
    if cached is not None:
        return cached

    type_name = (
        getattr(getattr(graphene_cls, "_meta", None), "name", None)
        or graphene_cls.__name__
    )

    def _make_fields(
        _cls: type = graphene_cls,
        _registries: SchemaRegistries = registries,
    ) -> dict[str, GraphQLField]:
        # Built lazily via a thunk so a self-referential plain ObjectType
        # (A → A) closes through the cache entry registered below BEFORE this
        # thunk evaluates — mirroring the GraphQLInputObjectType cache-before-eval
        # pattern (D5) on the output side. The pair is captured so a nested plain
        # field recurses through the SAME namespace (item-b B2).
        return _compile_plain_object_fields(_cls, _registries)

    native_type = GraphQLObjectType(
        name=type_name,
        fields=_make_fields,
        extensions={
            "gdx": GdxPayload(GdxMeta(name=type_name, graphene_type=graphene_cls))
        },
    )
    # Register BEFORE returning so recursive references resolve to this instance.
    cache[graphene_cls] = native_type
    return native_type


def _native_field_declared_django_type(field: Any) -> type | None:
    """Return the DECLARED DjangoObjectType class behind a NativeField.

    item-b (B7): field(SomeDjangoObjectType) builds a NativeField whose
    .type property EAGERLY resolves the class-def graphql_output_type (a
    graphql-core GraphQLObjectType), losing the class reference the fork needs
    to resolve a PAIR-LOCAL instance. The class is still on the descriptor's
    _declared_type slot; recover it so the root compiler can route the field
    through _build_django_output_field (which forks via resolved_output_type).

    Returns None for any field that is not a NativeField carrying a bare
    DjangoObjectType / DjangoListObjectType class (so the existing
    dispatch is unchanged for every other field kind).
    """
    import inspect

    declared = getattr(field, "_declared_type", None)
    if declared is None or not inspect.isclass(declared):
        return None
    from django_graphex.types import DjangoListObjectType, DjangoObjectType

    if issubclass(declared, (DjangoObjectType, DjangoListObjectType)):
        return declared
    return None


class _NativeDjangoFieldView:
    """Adapt a NativeField so _build_django_output_field sees the CLASS type.

    item-b (B7): _build_django_output_field reads field.type and routes it
    through _plain_django_output_type (which needs a CLASS to fork). A
    NativeField.type is the already-compiled class-def instance, so this thin
    view exposes the declared DjangoObjectType class as .type while
    delegating args / description / wrap_resolve to the real field —
    so the fork resolves the pair-local instance and the resolver wiring is
    preserved verbatim.
    """

    def __init__(self, field: Any, django_cls: type) -> None:
        self._field = field
        self._django_cls = django_cls

    @property
    def type(self) -> Any:  # noqa: A003 - matches compiler read-contract
        return self._django_cls

    @property
    def args(self) -> Any:
        return getattr(self._field, "args", None)

    @property
    def description(self) -> Any:
        return getattr(self._field, "description", None)

    def wrap_resolve(self, parent_resolver: Any) -> Any:
        return self._field.wrap_resolve(parent_resolver)


def _is_forked_pair(registries: Any) -> bool:
    """Return whether *registries* is a FORKED (non-default) pair (item-b B5/B6).

    A forked pair is one whose compile_outputs_into populated
    output_instances with pair-local instances. The default pair leaves that
    map empty/None, so this is False for the single/default-schema path
    (byte-identical: no re-fork, the class-def payload is reused verbatim).
    """
    return bool(getattr(registries, "output_instances", None))


def _maybe_refork_mutation_field(
    field: GraphQLField, registries: SchemaRegistries | None
) -> GraphQLField:
    """Re-fork a native mutation field's payload into *registries* when forked.

    item-b (B6): a DjangoModelMutation builds its payload
    GraphQLObjectType ONCE at class-def time, pinning its output-field thunk
    (e.g. post: PostGenericType) to the registry pair the class was defined
    under — the GLOBAL pair. When that field is mounted into a FORKED schema
    (a distinct SchemaRegistries pair), the pinned payload's output field
    still resolves to the GLOBAL node, so a relation from it reaches another
    schema's same-named instance — the R1 crux that
    assert_schema_pair_isolation raises on.

    The fix: in a forked build, RE-COMPILE the payload via the pair's
    plain-object cache (_compile_plain_object_type(source_cls, registries))
    so every output/relation thunk closes over THIS schema's forked nodes, then
    return a shallow copy of the field carrying the re-forked payload type (args
    + resolver + description preserved verbatim).

    For the DEFAULT pair this is a no-op (returns *field* unchanged), keeping the
    single/default-schema path byte-identical.

    Args:
        field: A mounted graphql-core GraphQLField (possibly a native mutation
            field carrying extensions['gdx_mutation_source']).
        registries: The schema's SchemaRegistries pair.

    Returns:
        The field unchanged (default pair, or a non-mutation field), or a copy
        with the re-forked payload type (forked pair + mutation field).
    """
    if not _is_forked_pair(registries):
        return field
    source_cls = (field.extensions or {}).get("gdx_mutation_source")
    if source_cls is None:
        return field
    forked_payload = _compile_plain_object_type(source_cls, registries)
    return GraphQLField(
        forked_payload,
        args=field.args,
        resolve=field.resolve,
        subscribe=field.subscribe,
        description=field.description,
        deprecation_reason=field.deprecation_reason,
        extensions=field.extensions,
    )


def _compile_plain_object_fields(
    graphene_cls: type, registries: SchemaRegistries | None = None
) -> dict[str, GraphQLField]:
    """Build the native field dict for a plain graphene.ObjectType subclass.

    Args:
        graphene_cls: A plain graphene.ObjectType subclass.
        registries: The SchemaRegistries pair threaded into recursive field
            compilation; defaults to the global pair (byte-identical, item-b B1).

    Returns:
        A {wire_name: GraphQLField} dict, keyed by the explicit name=
        when one is declared and by the camelCased attribute name otherwise.
    """
    registries = _resolve_registries(registries)
    fields: dict[str, GraphQLField] = {}
    meta_fields = getattr(getattr(graphene_cls, "_meta", None), "fields", None) or {}
    for field_name, field in meta_fields.items():
        # Honor an explicit ``name=`` exactly as the ROOT loop does. A payload /
        # nested plain ObjectType used to camelCase the ATTRIBUTE name here, so
        # the documented keyword-collision escape hatch
        # (``date_ = field(GdxDate, name="date")``) leaked the trailing
        # underscore onto the wire everywhere except the root.
        fields[_rendered_field_name(field, field_name)] = compile_declared_field(
            graphene_cls, field_name, field, registries
        )
    return fields


def _guard_output_default(field_name: str, field: Any) -> None:
    """Raise TypeError when an INPUT-only default= is set on an OUTPUT field.

    default= on a unified Field only
    makes sense in an argument (INPUT) position. Declared in an OUTPUT position (a
    root or a payload/ObjectType body) it is a mistake — fail LOUD rather than
    silently ignore it (feasibility risk #2). Called from BOTH output choke points:
    the compile_native_root field loop and compile_declared_field.

    Args:
        field_name: The declared field name (for the error message).
        field: The declared field descriptor (read via getattr; a non-Field
            descriptor with no _default is a no-op).
    """
    from django_graphex.core.descriptors import _UNSET

    if getattr(field, "_default", _UNSET) is not _UNSET:
        raise TypeError(
            f"{field_name!r}: default= is input-only; it was declared in an "
            f"output position. Remove default= (it has no meaning on an output "
            f"field)."
        )


def compile_declared_field(
    source_cls: type,
    field_name: str,
    field: Any,
    registries: SchemaRegistries | None = None,
) -> GraphQLField:
    """Convert a single DECLARED graphene field to a native "GraphQLField".

    Shared by "_compile_plain_object_fields" (plain ObjectType compilation) and
    by "types._compile_declared_fields" (Slice D: declared NON-model fields on a
    "DjangoObjectType" -- "graphene.String()" / "graphene.Field(PlainType)" /
    "graphene.Int()" / custom-resolver fields -- that never enter "model._meta"
    and so are not derived by "compile_output_fields").

    The field's mounted type is dispatched EXACTLY like graphene's TypeMap:

    - a nested plain "graphene.ObjectType" -> on-the-fly native type;
    - a "DjangoObjectType" / "DjangoListObjectType" -> its canonical
      "_meta.graphql_output_type";
    - a "List" / "NonNull" wrapper -> the inner leaf compiled, wrapper shape
      preserved;
    - any other leaf (scalar / enum) -> "_unwrap_graphql_type".

    Resolvers are wired EXACTLY like graphene: the field's own "resolver" wins,
    else the source class' "resolve_<field_name>" method, else graphql-core's
    default attribute/dict resolver.

    Args:
        source_cls: The class declaring the field (for the "resolve_<name>"
            lookup).
        field_name: The snake_case declared field name.
        field: The mounted graphene field ("graphene.Field" / scalar / etc.).
        registries: The "SchemaRegistries" pair threaded into nested compiles;
            defaults to the global pair (byte-identical, item-b B1).

    Returns:
        field: A graphql-core "GraphQLField" mirroring the graphene declaration.
    """
    from django_graphex.core._args import to_graphql_argument

    registries = _resolve_registries(registries)

    # OUTPUT-position validation (field-unify): a unified ``Field`` declared in an
    # ObjectType / payload body with the INPUT-only ``default=`` set is a mistake.
    _guard_output_default(field_name, field)

    field_type = getattr(field, "type", None)
    polymorphic = _polymorphic_field_type(field_type, registries)
    if polymorphic is not None:
        gql_type: Any = polymorphic
    elif _is_plain_object_type(field_type):
        gql_type = _compile_plain_object_type(field_type, registries)
    else:
        target = _plain_django_output_type(field_type, registries)
        if target is not None:
            gql_type = target
        else:
            # A graphene List/NonNull wrapper around a plain ObjectType
            # (e.g. ``errors: [ErrorType]`` on a mutation payload) must
            # compile the inner plain type and preserve the wrapper shape;
            # _unwrap_graphql_type only handles scalar leaves and would
            # raise a GDX_SCALAR_MAP KeyError for an inner ObjectType.
            gql_type = _compile_wrapped_field_type(field_type, registries)

    args = {}
    if getattr(field, "args", None):
        args = {
            arg_name: to_graphql_argument(arg, name=arg_name)
            for arg_name, arg in field.args.items()
        }

    resolve = field.wrap_resolve(_resolver_for(source_cls, field_name))
    return GraphQLField(
        gql_type,
        args=args,
        resolve=resolve,
        description=getattr(field, "description", None),
        deprecation_reason=getattr(field, "deprecation_reason", None),
    )


def _compile_wrapped_field_type(
    field_type: Any, registries: SchemaRegistries | None = None
) -> Any:
    """Compile a (possibly wrapped) graphene field type to a graphql-core type.

    Unwraps graphene List / NonNull structures, preserving the wrapper
    shape, and dispatches the inner leaf to the correct compiler:

    - an inner plain graphene.ObjectType (e.g. ErrorType) compiles
      on-the-fly via _compile_plain_object_type (single-instance, memoized);
    - an inner DjangoObjectType / DjangoListObjectType reuses its
      canonical _meta.graphql_output_type;
    - any other leaf (scalar/enum) goes through _unwrap_graphql_type.

    This is what lets a mutation-payload field like errors: [ErrorType] —
    a graphene.List (transitional) OR a native NativeList (S-ROOTS-c)
    wrapping a plain ObjectType — compile natively instead of raising a
    GDX_SCALAR_MAP KeyError on ErrorType.

    DUAL-CURRENCY wrappers (S-ROOTS-c): the native NativeList / NativeNonNull
    descriptors (descriptors.py) are LAZY carriers — graphql-core's
    GraphQLList / GraphQLNonNull cannot wrap an uncompiled ObjectType
    class eagerly, so errors = field(NativeList(ErrorType)) defers the inner
    compile to here. They are recursed exactly like the graphene wrappers (same
    .of_type read-contract), preserving the wrapper shape.

    Args:
        field_type: The mounted field type — a graphene Structure wrapper,
            a native NativeList / NativeNonNull wrapper, or a leaf class.
        registries: The SchemaRegistries pair threaded into the inner leaf
            compile; defaults to the global pair (byte-identical, item-b B1).

    Returns:
        The corresponding graphql-core type (wrappers preserved).
    """
    from django_graphex.core._args import _unwrap_graphql_type
    from django_graphex.core.descriptors import NativeList, NativeNonNull

    registries = _resolve_registries(registries)

    # NATIVE wrappers FIRST (S-ROOTS-c) — checked WITHOUT importing graphene so a
    # fully-native field/root compiles graphene-free (the S-milestone-9 contract).
    if isinstance(field_type, NativeNonNull):
        return GraphQLNonNull(
            _compile_wrapped_field_type(field_type.of_type, registries)
        )
    if isinstance(field_type, NativeList):
        return GraphQLList(_compile_wrapped_field_type(field_type.of_type, registries))

    # S-del-backend-11: the graphene-ROOT wrapper handling (a graphene ``List`` /
    # ``NonNull`` wrapper consulted via ``sys.modules['graphene.types.structures']``)
    # is removed — v2.0 cannot accept a graphene root. Only the native ``NativeList``
    # / ``NativeNonNull`` wrappers (handled above) are recognised; a leaf falls
    # through to the polymorphic / plain-object / scalar arms below.

    polymorphic = _polymorphic_field_type(field_type, registries)
    if polymorphic is not None:
        return polymorphic
    if _is_plain_object_type(field_type):
        return _compile_plain_object_type(field_type, registries)
    target = _plain_django_output_type(field_type, registries)
    if target is not None:
        return target
    return _unwrap_graphql_type(field_type)


def _polymorphic_field_type(
    field_type: Any, registries: SchemaRegistries | None = None
) -> Any | None:
    """Return the compiled graphql-core abstract type for a union/interface field.

    DEFECT #8: a DjangoUnionType / DjangoInterfaceType field (e.g.
    payment = Field(PaymentUnion)) compiles to a graphql-core
    GraphQLUnionType / GraphQLInterfaceType via the memoized polymorphic
    compiler — NOT a plain GraphQLObjectType. Returns None for any
    non-polymorphic field type so the caller's normal dispatch continues.

    Args:
        field_type: The mounted field type.
        registries: The SchemaRegistries pair owning the union/interface
            cache namespace; defaults to the global pair (byte-identical, item-b
            B1/B2).

    Returns:
        A GraphQLUnionType / GraphQLInterfaceType or None.
    """
    import inspect

    if not inspect.isclass(field_type):
        return None
    from django_graphex.core.polymorphic_compiler import (
        compile_polymorphic_type,
        is_interface_type,
        is_union_type,
    )

    if is_union_type(field_type) or is_interface_type(field_type):
        return compile_polymorphic_type(field_type, _resolve_registries(registries))
    return None


def _plain_django_output_type(
    field_type: Any, registries: SchemaRegistries | None = None
) -> GraphQLObjectType | None:
    """Return the native output type for a django-graphex output field.

    A plain ObjectType may reference a DjangoObjectType /
    DjangoListObjectType whose native type lives on
    _meta.graphql_output_type. Reuse it (identity-stable) instead of
    recompiling. Returns None for non-django types.

    item-b (B5): when *registries* is a non-default pair that forked this class,
    return the FORKED instance instead of the class-def one (default pair / no
    fork -> the class-def instance -> byte-identical).

    Args:
        field_type: The mounted field type.
        registries: The SchemaRegistries pair (forked resolution); None
            -> the class-def instance (byte-identical).

    Returns:
        The container GraphQLObjectType (forked or canonical) or None.
    """
    import inspect

    if not inspect.isclass(field_type):
        return None
    from django_graphex.types import DjangoListObjectType, DjangoObjectType

    if issubclass(field_type, (DjangoObjectType, DjangoListObjectType)):
        from django_graphex.core.base import resolved_output_type

        return resolved_output_type(field_type, registries)
    return None


def _build_plain_object_field(
    field: Any,
    *,
    source_cls: type | None = None,
    field_name: str | None = None,
    registries: SchemaRegistries | None = None,
) -> GraphQLField:
    """Build a native GraphQLField for a plain graphene.ObjectType field.

    Compiles the field's target plain ObjectType on-the-fly (single-instance,
    memoized) and converts the field's args. The resolver is wired via the
    field's own wrap_resolve so a field-level resolver still wins; otherwise
    the source class' resolve_<field_name> (graphene parity) or graphql-core's
    default attribute/dict resolver.

    Args:
        field: A graphene.Field whose type is a plain graphene.ObjectType.
        source_cls: The ObjectType class declaring the field (for the
            resolve_<field_name> parent-resolver lookup).
        field_name: The snake_case field name.
        registries: The SchemaRegistries pair owning the plain-object cache;
            defaults to the global pair (byte-identical, item-b B1).

    Returns:
        A graphql-core GraphQLField.
    """
    from django_graphex.core._args import to_graphql_argument

    output_type = _compile_plain_object_type(
        field.type, _resolve_registries(registries)
    )

    args = {}
    if getattr(field, "args", None):
        args = {
            arg_name: to_graphql_argument(arg, name=arg_name)
            for arg_name, arg in field.args.items()
        }

    resolve = field.wrap_resolve(_resolver_for(source_cls, field_name))
    return GraphQLField(
        output_type,
        args=args,
        resolve=resolve,
        description=getattr(field, "description", None),
    )


def _build_django_output_field(
    field: Any,
    *,
    source_cls: type | None = None,
    field_name: str | None = None,
    registries: SchemaRegistries | None = None,
) -> GraphQLField:
    """Build a native GraphQLField for a plain Field(DjangoObjectType) root.

    Reuses the target DjangoObjectType / DjangoListObjectType's canonical
    _meta.graphql_output_type (identity-stable). The resolver is wired via the
    field's own wrap_resolve so a field-level resolver wins; otherwise the
    source class' resolve_<field_name> (graphene parity) or the default
    attribute/dict resolver.

    Args:
        field: A graphene.Field whose type is a DjangoObjectType /
            DjangoListObjectType.
        source_cls: The ObjectType class declaring the field.
        field_name: The snake_case field name.
        registries: The SchemaRegistries pair (threaded for uniformity with
            the other _build_*_field helpers; the canonical instance is read
            from _meta). Defaults to the global pair (byte-identical, B1).

    Returns:
        A graphql-core GraphQLField.
    """
    from django_graphex.core._args import to_graphql_argument

    registries = _resolve_registries(registries)
    output_type = _plain_django_output_type(field.type, registries)

    args = {}
    if getattr(field, "args", None):
        args = {
            arg_name: to_graphql_argument(arg, name=arg_name)
            for arg_name, arg in field.args.items()
        }

    resolve = field.wrap_resolve(_resolver_for(source_cls, field_name))
    return GraphQLField(
        output_type,
        args=args,
        resolve=resolve,
        description=getattr(field, "description", None),
    )


def _build_polymorphic_field(
    field: Any,
    *,
    source_cls: type | None = None,
    field_name: str | None = None,
    registries: SchemaRegistries | None = None,
) -> GraphQLField:
    """Build a native GraphQLField for a union/interface root field (DEFECT #8).

    The field type is the compiled GraphQLUnionType / GraphQLInterfaceType
    (memoized). The resolver is wired via the field's own wrap_resolve so a
    field-level resolver still wins; otherwise the source class' resolve_<name>
    (graphene parity) or graphql-core's default attribute/dict resolver.

    Args:
        field: A graphene.Field whose type is a DjangoUnionType /
            DjangoInterfaceType.
        source_cls: The ObjectType class declaring the field (for the
            resolve_<field_name> parent-resolver lookup).
        field_name: The snake_case field name.
        registries: The SchemaRegistries pair owning the union/interface
            cache; defaults to the global pair (byte-identical, item-b B1).

    Returns:
        A graphql-core GraphQLField whose type is the polymorphic abstract type.
    """
    from django_graphex.core._args import to_graphql_argument

    output_type = _polymorphic_field_type(field.type, _resolve_registries(registries))

    args = {}
    if getattr(field, "args", None):
        args = {
            arg_name: to_graphql_argument(arg, name=arg_name)
            for arg_name, arg in field.args.items()
        }

    resolve = field.wrap_resolve(_resolver_for(source_cls, field_name))
    return GraphQLField(
        output_type,
        args=args,
        resolve=resolve,
        description=getattr(field, "description", None),
    )


def _filter_arg(
    field: Any, registries: SchemaRegistries | None = None
) -> dict[str, GraphQLArgument]:
    """Return the native filter arg dict for a list field, or {}.

    The native <Model>FilterInput is built by the WU3 native filter input
    builder and stored on the field's filter_type attribute (set in the
    field's __init__ via the graphene builder for the graphene path) — but
    the GRAPHENE filter type is NOT usable as a native arg. We rebuild the native
    input here from the field's declared fields + custom_filters via the
    native backend so the arg is a real GraphQLInputObjectType whose coerced
    value (snake out_name keys) flows straight into to_q.

    Args:
        field: A list field carrying filter_backend / fields /
            custom_filters (set by _build_filter_arg).
        registries: The SchemaRegistries pair owning the filter-input cache;
            defaults to the global pair (byte-identical, item-b B1/B2).

    Returns:
        {"filter": GraphQLArgument(<Model>FilterInput)} when filterable
        fields are declared, else {}.
    """
    declared_fields = getattr(field, "fields", None)
    custom_filters = getattr(field, "custom_filters", None) or []
    if not declared_fields and not custom_filters:
        return {}

    registries = _resolve_registries(registries)
    model = field.model
    node_type = _unwrap_to_node_type(field)
    node_meta = getattr(node_type, "_meta", None)
    registry = getattr(node_meta, "registry", None)

    # NAME the type the projection boundary is measured against. The filter
    # guard used to look it up by model in the graphene registry — a last-wins
    # index a type opts out of with the public ``Meta.skip_registry``, which
    # made the guard a no-op for exactly the type about to serve the request.
    # ``resolved_output_type`` also picks THIS pair's forked instance, so a
    # permission-scoped clone is measured as itself.
    #
    # A list-object field declares the ``<Model>ListType`` CONTAINER, and the
    # projection lives on the node it paginates. Take that node from the pair's
    # output registry — the very map the container's own thunk reads — rather
    # than unwrapping the container's ``results`` field: forcing a container's
    # field map from HERE closes a cycle (container thunk -> ordering stamp ->
    # the host type's fields -> this nested field -> back to the container).
    from django_graphex.core.base import resolved_output_type
    from django_graphex.filtering.native_schema import build_filter_input_type

    serving_type = resolved_output_type(node_type, registries)
    if getattr(node_meta, "results_field_name", None):
        serving_type = registries.output.get_compiled(model)

    native_input = build_filter_input_type(
        model,
        declared_fields,
        registry,
        custom_filters=custom_filters,
        registries=registries,
        node_type=serving_type,
        # NAME the Meta this declaration was read from. The input is shared per
        # MODEL, so a refusal over a path another type contributed has to name
        # THAT type: "<Model>.filter_fields" points at a Meta no model has. A
        # container that declared none carries the node it inherited from.
        declared_on=(
            getattr(node_meta, "filter_fields_declared_on", None)
            or getattr(node_type, "__name__", None)
        ),
    )
    if native_input is None:
        return {}
    return {
        "filter": GraphQLArgument(
            native_input,
            out_name="filter",
            description="Filtering options for the list",
        )
    }


def _list_container_output_type(
    field: Any, registries: SchemaRegistries | None = None
) -> GraphQLObjectType:
    """Return the native container type for a list-object field.

    Reuses the WU1b list-container graphql_output_type (identity-stable,
    carries extensions['gdx']). NEVER rebuilds a second container instance.

    item-b (B5): resolves to THIS schema's FORKED container instance when a
    non-default pair is in play; default pair -> the class-def container ->
    byte-identical.

    Args:
        field: A DjangoListObjectField (or subclass) whose type is a
            DjangoListObjectType.
        registries: The SchemaRegistries pair (forked container resolution);
            defaults to the global pair (byte-identical).

    Returns:
        The container GraphQLObjectType (forked or canonical).

    Raises:
        RuntimeError: When the container has no compiled graphql_output_type
            (compile_all_outputs() must run before native root compilation).
    """
    from django_graphex.core.base import resolved_output_type

    registries = _resolve_registries(registries)
    # item-b (B5): a reverse-relation / nested ``<Model>ListType`` container is
    # often AUTO-CREATED lazily inside a relation thunk — AFTER
    # ``compile_outputs_into`` ran — so it is not yet in the pair's fork map.
    # Fork it ON DEMAND (no-op for the default pair) so the container's results
    # node resolves to THIS schema's forked node instead of the class-def one
    # (which would re-introduce the same-named-instance collision).
    if getattr(registries, "output_instances", None) is not None:
        from django_graphex.core.registry_compiler import fork_output_class

        forked = fork_output_class(field.type, registries)
        if forked is not None:
            return forked

    container = resolved_output_type(field.type, registries)
    if container is None:  # pragma: no cover — defensive
        raise RuntimeError(
            f"DjangoListObjectField target {field.type!r} has no compiled "
            "graphql_output_type. compile_all_outputs() must run before native "
            "root compilation (WU1b list-container compile)."
        )
    return container


def _build_list_object_field(
    field: Any, registries: SchemaRegistries | None = None
) -> GraphQLField:
    """Build a native GraphQLField for a DjangoListObjectField.

    The output type is the WU1b list-container (results + totalCount
    [+ pageInfo]); the container's results field carries the pagination
    args + slicing resolver (wired in types.py WU6a). The list field itself
    carries the filter arg (when filterable) and a resolver that filters the
    queryset and returns a DjangoListObjectBase — the page slicing then
    happens on the container's results field.

    Args:
        field: A DjangoListObjectField (or DjangoNestedListObjectField).
        registries: The SchemaRegistries pair owning the filter-input cache;
            defaults to the global pair (byte-identical, item-b B1/B2).

    Returns:
        A graphql-core GraphQLField.
    """
    registries = _resolve_registries(registries)
    output_type = _list_container_output_type(field, registries)
    args = _filter_arg(field, registries)
    # The field's wrap_resolve already returns a (root, info, **kwargs) callable
    # (a partial binding manager/filter_backend/output_type). Reuse it so the
    # filter/queryset logic is identical to the graphene path — NOT a no-op.
    resolve = field.wrap_resolve(default_field_resolver)
    return GraphQLField(
        output_type,
        args=args,
        resolve=resolve,
        description=getattr(field, "description", None),
    )


def _unwrap_to_node_type(field: Any) -> Any:
    """Unwrap a list field's type to the inner DjangoObjectType node.

    DjangoFilterListField.type is a NativeList (possibly wrapping a
    NativeNonNull) around the node DjangoObjectType (S8c). graphql-core
    GraphQLList / GraphQLNonNull wrappers may also be present in mixed
    states. Peel every wrapper to reach the node class that carries
    _meta.graphql_output_type.

    Args:
        field: A list field whose type wraps a DjangoObjectType.

    Returns:
        The inner node type class (carrying _meta).
    """
    from django_graphex.core.descriptors import NativeList, NativeNonNull

    current = field.type
    while isinstance(current, (GraphQLList, GraphQLNonNull, NativeList, NativeNonNull)):
        current = current.of_type
    return current


def _rescoped_paginate_field(field: Any, node_type: Any, node_output: Any) -> Any:
    """Rebind a flat paginated list field to THIS schema's ordering allowlist.

    Which columns may be named in "ordering" is a PER-SCHEMA fact, and every
    other stamper already treats it as one: the list container reads its pair's
    compiled element type, and the permission pruner re-derives the allowlist
    against the clone it just built. This one used to read
    "_type._meta.graphql_output_type" -- the CLASS-DEF canonical instance,
    stamped once while the root class body was still executing. That instance is
    not the object the schema serves: instrumenting every flat paginated field
    the test suite builds found twelve whose served node type is a different
    object. They agree only because a fork recompiles the same class from the
    same "Meta", and the disagreement a narrower schema would produce runs the
    dangerous way -- an allowlist naming a column the served SDL denies.

    Both the field and its paginator are COPIED, for the same reason the
    container copies: one paginator instance is routinely mounted on several
    fields and reaches every schema through the class-def field, so writing on
    the shared object would let the last schema built decide every earlier
    schema's allowlist.

    The stamp is a THUNK, unlike the container's plain value. This runs while
    the root (or a host node type's own field map) is still compiling, and
    "node_output" may be a type whose field map is a thunk back into that same
    walk. Forcing it here is re-entrant by construction: doing so eagerly raised
    "RecursionError" out of a node type's own thunk across the whole suite.

    Args:
        field: The "DjangoFilterPaginateListField" being compiled, whose
            "pagination" is not "None".
        node_type: The declared node class, which names the model.
        node_output: The compiled node type THIS schema will serve rows with.

    Returns:
        A copy of the field carrying a copy of the paginator, stamped with the
        allowlist the served type publishes.
    """
    from graphql import get_named_type

    from django_graphex.paginations.pagination import projected_ordering_attnames

    model = node_type._meta.model
    served = get_named_type(node_output)

    rescoped = copy(field)
    paginator = copy(field.pagination)
    paginator.ordering_allowed_attnames = lambda: projected_ordering_attnames(
        model, served
    )
    rescoped.pagination = paginator
    return rescoped


def _build_filter_list_field(
    field: Any, registries: SchemaRegistries | None = None
) -> GraphQLField:
    """Build a native GraphQLField for a plain filtered list field.

    Covers DjangoFilterListField (no pagination → [Node]) and
    DjangoFilterPaginateListField (filter + in-resolver pagination →
    [Node!]). The output type mirrors the graphene shape: a
    GraphQLList of the node's canonical graphql_output_type. Pagination
    args (when present) are added directly to the field; filtering + slicing
    happen inside the field's own list_resolver (reused via wrap_resolve).

    Args:
        field: A DjangoFilterListField or DjangoFilterPaginateListField.
        registries: The SchemaRegistries pair owning the filter-input cache;
            defaults to the global pair (byte-identical, item-b B1/B2).

    Returns:
        A graphql-core GraphQLField.
    """
    from django_graphex.core.base import resolved_output_type

    registries = _resolve_registries(registries)
    node_type = _unwrap_to_node_type(field)
    # item-b (B5): resolve the node to THIS schema's FORKED instance under a
    # non-default pair; default pair -> the class-def node -> byte-identical.
    node_output = resolved_output_type(node_type, registries)
    if node_output is None:  # pragma: no cover — defensive
        raise RuntimeError(
            f"Filter list field target {field.type!r} has no compiled "
            "graphql_output_type. compile_all_outputs() must run first."
        )

    # DjangoFilterListField wraps List(_type); DjangoFilterPaginateListField
    # wraps List(NonNull(_type)). Mirror the non-null inner shape so SDL parity
    # holds: the paginate variant emits [Node!], the plain variant [Node].
    if type(field).__name__ == "DjangoFilterPaginateListField":
        list_type: Any = GraphQLList(GraphQLNonNull(node_output))
    else:
        list_type = GraphQLList(node_output)

    args = _filter_arg(field, registries)
    # Pagination args (DjangoFilterPaginateListField only): the paginator slices
    # inside list_resolver, so the args must be on THIS field.
    paginator = getattr(field, "pagination", None)
    if paginator is not None:
        field = _rescoped_paginate_field(field, node_type, node_output)
        paginator = field.pagination
        args.update(paginator.to_graphql_fields(native=True))

    resolve = field.wrap_resolve(default_field_resolver)
    return GraphQLField(
        list_type,
        args=args,
        resolve=resolve,
        description=getattr(field, "description", None),
    )


def compile_native_root(
    root: type, *, name: str, registries: SchemaRegistries | None = None
) -> GraphQLObjectType:
    """Compile a graphene root ObjectType into a native "GraphQLObjectType".

    Args:
        root: The graphene root ObjectType class (Query / Mutation /
            Subscription). May be None.
        name: The GraphQL type name for the compiled root.
        registries: The "SchemaRegistries" pair threaded into every field
            builder (and on into the plain-object / union / interface / filter
            caches). Defaults to the process-wide global pair, so the single-
            namespace behavior is byte-identical (item-b B1/B2). No caller passes
            a non-default pair in B0-B2 -- pure plumbing.

    Returns:
        root_type: A graphql-core "GraphQLObjectType" whose fields' types are
            the canonical native instances, or None if "root" is None.

    Raises:
        NotImplementedError: If the root declares a field kind whose native
            builder does not exist yet (list/filter/pagination -- WU3/WU5/WU6).
            The error names the field and the owning WU. NEVER silently skipped.
    """
    if root is None:
        return None  # type: ignore[return-value]

    registries = _resolve_registries(registries)

    # Import field classes lazily to avoid a hard import cycle at module load.
    from django_graphex.fields import (
        DjangoFilterListField,
        DjangoFilterPaginateListField,
        DjangoListObjectField,
        DjangoObjectField,
    )

    fields: dict[str, GraphQLField] = {}

    # 1) graphene-mounted fields (DjangoObjectField, list/filter fields, scalars).
    meta_fields = dict(getattr(getattr(root, "_meta", None), "fields", None) or {})

    # S8c silent-drop guard: the ``Django*Field`` classes are now
    # ``NativeMountedField`` (off graphene ``Field``), so graphene's root metaclass
    # DROPS them from ``_meta.fields``. Recover any class-body native fields the
    # metaclass dropped and merge them in (only when absent — a native root already
    # surfaced them via ``_mount_descriptor_fields``). Ordered by declaration
    # counter so the combined field order — hence SDL field order — is byte-stable.
    dropped_native = _collect_dropped_native_fields(root)
    if dropped_native:
        combined = dict(meta_fields)
        for fname, fval in dropped_native.items():
            combined.setdefault(fname, fval)

        # Re-order the combined set by declaration counter where available so a
        # graphene-scalar + native-field mixed root keeps declaration order.
        def _decl_key(item: tuple[str, Any]) -> tuple[int, int]:
            cc = getattr(item[1], "creation_counter", None)
            return (0, cc) if isinstance(cc, int) else (1, 0)

        meta_fields = dict(sorted(combined.items(), key=_decl_key))

    for field_name, field in meta_fields.items():
        kind = type(field).__name__
        if kind in _DEFERRED_FIELD_KINDS:
            raise NotImplementedError(
                f"Native root compiler cannot yet build field {field_name!r} "
                f"of kind {kind!r} on root {name!r}. The native field builder "
                f"for this kind is owned by {_DEFERRED_FIELD_KINDS[kind]}."
            )
        # OUTPUT-position validation (field-unify): ``default=`` is INPUT-only. A
        # unified ``Field`` declared in an OUTPUT (root) position with ``default=``
        # set is a declaration mistake — fail LOUD here, the single choke point
        # every root output field traverses, rather than silently ignoring it.
        _guard_output_default(field_name, field)
        # The wire name honors an explicit ``name=`` kwarg (e.g.
        # ``CustomDate(name="date")``) exactly as graphene does; the snake
        # ``field_name`` is still used for the ``resolve_<field_name>`` lookup.
        wire_name = _rendered_field_name(field, field_name)
        if isinstance(field, GraphQLField):
            # S-ROOTS-h: a raw graphql-core ``GraphQLField`` declared on a NATIVE
            # ``ObjectType`` root (e.g. ``create_x = CreateX.Field()`` for a
            # hand-written ``Mutation``, or ``post_create = PostMutation.CreateField()``
            # for ``DjangoModelMutation``) is ALREADY a fully compiled field — its
            # type is the compiled payload, its args + resolver are wired. Reuse it
            # VERBATIM (never recompile / scalar-convert). On a graphene root these
            # never reach ``_meta.fields`` (graphene drops them); they are recovered
            # by ``_collect_root_attrs`` below instead. The native mount
            # (``_mount_descriptor_fields``) is what lands them here for a native root.
            fields[wire_name] = _maybe_refork_mutation_field(field, registries)
        elif _is_subscription_field(field):
            # Subscription root field (WU7): the mounted ``SubscriptionField``
            # carries the Subscription subclass as its ``type`` (``_meta.output``).
            # Build the DIRECT native subscription field (event type + subscribe
            # source factory + reduced {action,id,filters} args) via the class'
            # own ``_build_native_field``. schema/document are supplied by the
            # transport at delivery time (the source build does not need them).
            fields[wire_name] = field.type._build_native_field()
        elif isinstance(field, DjangoObjectField):
            built = _build_object_field(field, registries)
            fields[wire_name] = _label_model_field(built, field, "retrieve")
        elif isinstance(field, DjangoListObjectField):
            # DjangoListObjectField (and DjangoNestedListObjectField) → the WU1b
            # list-container output type; pagination args/resolver live on the
            # container's results field (WU6a), filter arg on this field.
            built = _build_list_object_field(field, registries)
            fields[wire_name] = _label_model_field(built, field, "list")
        elif isinstance(field, (DjangoFilterListField, DjangoFilterPaginateListField)):
            # Plain filtered list ([Node] / [Node!]); pagination (when present)
            # slices inside the field's own list_resolver (args on this field).
            built = _build_filter_list_field(field, registries)
            fields[wire_name] = _label_model_field(built, field, "list")
        elif (
            _polymorphic_field_type(getattr(field, "type", None), registries)
            is not None
        ):
            # DEFECT #8: a ``Field(PaymentUnion)`` / ``Field(ProductInterface)``
            # root field whose type is a DjangoUnionType / DjangoInterfaceType
            # compiles to a graphql-core GraphQLUnionType / GraphQLInterfaceType.
            # Without this it would fall to _build_scalar_field →
            # _unwrap_graphql_type → GDX_SCALAR_MAP KeyError on the member type.
            fields[wire_name] = _build_polymorphic_field(
                field, source_cls=root, field_name=field_name, registries=registries
            )
        elif _native_field_declared_django_type(field) is not None:
            # item-b (B7): a native ``field(SomeDjangoObjectType)`` (NativeField)
            # eagerly resolves ``field.type`` to the CLASS-DEF GraphQLObjectType, so
            # neither ``_plain_django_output_type(field.type)`` (needs a class) nor
            # the scalar arm forks it under a non-default pair — the class-def
            # instance leaks into a forked schema (assert_schema_pair_isolation R1).
            # Recover the DECLARED DjangoObjectType class and route it through
            # ``_build_django_output_field`` so it resolves to THIS pair's forked
            # instance (default pair -> class-def -> byte-identical).
            fields[wire_name] = _build_django_output_field(
                _NativeDjangoFieldView(
                    field, _native_field_declared_django_type(field)
                ),
                source_cls=root,
                field_name=field_name,
                registries=registries,
            )
        elif _plain_django_output_type(getattr(field, "type", None)) is not None:
            # A plain ``graphene.Field(SomeDjangoObjectType)`` on a root (instead
            # of a ``DjangoObjectField``) reuses the target's canonical
            # ``graphql_output_type``. Without this it would fall to the scalar arm
            # and KeyError on the DjangoObjectType name. Resolver wiring matches the
            # plain-field path (field resolver wins; else ``resolve_<name>``).
            fields[wire_name] = _build_django_output_field(
                field, source_cls=root, field_name=field_name, registries=registries
            )
        elif _is_plain_object_type(getattr(field, "type", None)):
            # Slice A: a plain graphene.ObjectType field (NOT a DjangoObjectType,
            # NOT a scalar) compiles on-the-fly to a single-instance native
            # GraphQLObjectType (recurses; carries extensions['gdx']). Without
            # this it would fall to _build_scalar_field → _unwrap_graphql_type →
            # GDX_SCALAR_MAP KeyError (e.g. the test_security `_Nested` field).
            fields[wire_name] = _build_plain_object_field(
                field, source_cls=root, field_name=field_name, registries=registries
            )
        else:
            # Plain graphene scalar/enum field (e.g. CustomDateTime).
            fields[wire_name] = _build_scalar_field(
                field,
                source_cls=root,
                field_name=field_name,
                registries=registries,
            )

        # P0: honor an explicit ``field(required_perms=...)`` override on a
        # declared ``NativeField``. The model CRUD arms above already stamp their
        # composite perms; this covers the hand-declared field opt-in (a
        # ``NativeField`` whose ``required_perms`` is set). Untagged fields stay
        # public (no ``gdx_required_perms`` key).
        _field_override = getattr(field, "required_perms", None)
        if _field_override is not None and "gdx_required_perms" not in (
            fields[wire_name].extensions or {}
        ):
            fields[wire_name] = _stamp_required_perms(
                fields[wire_name], frozenset(_field_override)
            )

        # F2 (field-unify): carry a declared ``deprecation_reason`` onto the built
        # root field so the SDL renders ``@deprecated(reason: ...)``. Stamped here
        # (the single root choke point) so it applies uniformly across every field
        # kind above; the per-builder ``GraphQLField`` never carries it. Only set
        # when the built field does not already carry one (a raw ``GraphQLField.Field()``
        # mount may have its own).
        _deprecation = getattr(field, "deprecation_reason", None)
        if _deprecation is not None and fields[wire_name].deprecation_reason is None:
            fields[wire_name].deprecation_reason = _deprecation

    # 2) raw native mutation fields graphene dropped from _meta.fields.
    for attr_name, gql_field in _collect_root_attrs(root).items():
        fields[to_camel_case(attr_name)] = _maybe_refork_mutation_field(
            gql_field, registries
        )

    # D8 invariant: every native object type carries extensions['gdx']. The
    # root's GdxMeta carries `graphene_type=root` so dual-backend read-sites
    # (e.g. utils._get_custom_resolver) can recover the source graphene root
    # class to look up `resolve_<field>` methods under native — graphene reads
    # `info.parent_type.graphene_type` directly; native reads it via the bridge.
    return GraphQLObjectType(
        name=name,
        fields=fields,
        extensions={"gdx": GdxPayload(GdxMeta(name=name, graphene_type=root))},
    )
