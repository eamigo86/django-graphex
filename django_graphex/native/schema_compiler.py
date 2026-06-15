"""Native root-ObjectType compiler (Phase 5 / WU2).

Turns a plain ``graphene.ObjectType`` schema root (Query / Mutation /
Subscription) into a graphql-core ``GraphQLObjectType`` whose per-field types
are the CANONICAL native instances (``_meta.graphql_output_type`` carrying
``extensions['gdx']``), not graphene-built types. This is the GENUINE native
seam that lets ``DjangoGraphQLSchema`` build a ``graphql.GraphQLSchema`` without
graphene.Schema and without the duplicate-name TypeError.

Why this exists (WU2 rework, see sdd/filtering-pagination-schema/wu2-design-gap):
- The user's roots are plain ``graphene.ObjectType`` subclasses with NO
  ``_meta.graphql_output_type``; nothing compiled them into native types.
- Query-root field classes (``DjangoObjectField``, ``DjangoListObjectField``,
  ``DjangoFilterListField`` …) emit NO native ``GraphQLField`` — only mutation
  fields do (mutation.py ``_NATIVE_FIELD_REGISTRY`` / ``_build_native_mutation_field``).
- The first WU2 attempt kept graphene.Schema and injected native types via
  ``GraphQLSchema(types=…)``, which duplicate-named the graphene-built types and
  silently fell back to graphene (a tautology). FORBIDDEN.

Per-field-kind dispatch (extensible by WU3/WU5/WU6):
- raw graphql-core ``GraphQLField`` attribute (a native mutation field graphene
  dropped from ``_meta.fields``) → REUSE as-is.
- ``DjangoObjectField`` (single object) → build a native ``GraphQLField`` whose
  type is the canonical ``field.type._meta.graphql_output_type``, with converted
  args and the field's wired resolver.
- plain graphene scalar field → convert to a graphql-core scalar ``GraphQLField``.
- ``DjangoListObjectField`` / ``DjangoFilterListField`` /
  ``DjangoFilterPaginateListField`` / ``DjangoNestedListObjectField`` → RAISE
  ``NotImplementedError`` naming the field + the WU that will add the builder.
  NO silent skip, NO graphene fallback.
"""

from __future__ import annotations

from typing import Any

from django_graphex._strconv import to_camel_case
from graphql import (
    GraphQLArgument,
    GraphQLField,
    GraphQLList,
    GraphQLNonNull,
    GraphQLObjectType,
)
from graphql.execution import default_field_resolver

from django_graphex.native.bridge import GdxPayload
from django_graphex.native.ir import GdxMeta

# Map of not-yet-supported field-kind class names → the WU that owns the native
# builder. Used to produce a precise NotImplementedError instead of a silent skip.
#
# WU6a (this slice) emptied the list/filter/pagination kinds: the native builders
# now exist (see _build_list_object_field / _build_filter_list_field). Anything
# left here still raises a precise NotImplementedError instead of a silent skip.
_DEFERRED_FIELD_KINDS: dict[str, str] = {}


def _rendered_field_name(field: Any, attr_name: str) -> str:
    """Return the wire name graphene would render for a declared field.

    graphene's ``MountedType`` carries an explicit ``name`` attribute (the
    ``name=`` kwarg, e.g. ``CustomDate(name="date")``). When set, graphene uses
    it VERBATIM as the final SDL field name — NO camelCase pass is applied (the
    explicit name is already the wire name). When unset (``None``), graphene
    camelCases the snake_case attribute name under ``auto_camelcase=True``.

    Mirroring this is REQUIRED for full-schema SDL parity: the test schema
    declares ``date_ = CustomDate(name="date")`` / ``datetime_`` / ``time_`` to
    dodge the Python keyword-collision trailing underscore; graphene renders
    ``date`` / ``datetime`` / ``time`` while a naive ``to_camel_case(attr)``
    would render ``date_`` / ``datetime_`` / ``time_`` — an SDL divergence.

    Args:
        field: The mounted graphene field (may expose an explicit ``.name``).
        attr_name: The snake_case attribute name under which the field is
            declared on the root.

    Returns:
        The explicit ``field.name`` when set, else ``to_camel_case(attr_name)``.
    """
    explicit = getattr(field, "name", None)
    if explicit:
        return explicit
    return to_camel_case(attr_name)


def _collect_root_attrs(root: type) -> dict[str, Any]:
    """Collect native mutation ``GraphQLField`` attributes graphene dropped.

    graphene's ObjectType metaclass does NOT mount raw graphql-core
    ``GraphQLField`` objects (e.g. native mutation fields returned by
    ``DjangoModelType.CreateField()`` under GDX_BACKEND=native): they stay as
    plain class attributes in ``__dict__`` but never enter ``_meta.fields``.
    Walk the MRO so subclassed roots still surface them; the most-derived class
    wins on name collisions.

    Membership in ``_NATIVE_FIELD_REGISTRY`` (not a blanket
    ``isinstance(value, GraphQLField)`` scan) is the gate: a recovered attribute
    is treated as a native mutation field ONLY when it is one of the exact
    ``GraphQLField`` instances the mutation machinery registered. This prevents
    an unrelated user-declared raw ``GraphQLField`` class attribute from being
    silently mounted onto the native root.

    Args:
        root: The graphene root ObjectType class.

    Returns:
        Mapping of attribute name → ``GraphQLField`` for every dropped native
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


def _is_subscription_field(field: Any) -> bool:
    """Return whether *field* is a subscription root field (WU7).

    Duck-typed (NOT a hard ``import django_graphex.subscriptions``) so the native
    root compiler never pulls the optional ``[subscriptions]`` extra (Channels)
    onto the base build path. A subscription root field is a graphene-mounted
    field whose ``type`` is a ``Subscription`` subclass carrying the native
    compile-path method ``_build_native_field`` (added by WU6). The class name
    gate (``SubscriptionField``) avoids matching an unrelated field that happens
    to expose a callable of that name.

    Args:
        field: A graphene-mounted root field.

    Returns:
        ``True`` when *field* is a ``SubscriptionField`` whose target class
        builds a native subscription field.
    """
    if type(field).__name__ != "SubscriptionField":
        return False
    target = getattr(field, "type", None)
    return callable(getattr(target, "_build_native_field", None))


def _build_object_field(field: Any) -> GraphQLField:
    """Build a native ``GraphQLField`` for a ``DjangoObjectField`` (single object).

    The field TYPE is the canonical native ``GraphQLObjectType`` stored on the
    target ``DjangoObjectType._meta.graphql_output_type`` — the SAME instance the
    shared output registry holds (identity-stable). The resolver is wired via the
    field's own ``wrap_resolve`` so it is NOT a dead no-op.

    Args:
        field: A ``DjangoObjectField`` instance (graphene-mounted).

    Returns:
        A graphql-core ``GraphQLField``.
    """
    from django_graphex.native._args import graphene_arg_to_graphql_argument

    output_type = field.type._meta.graphql_output_type
    if output_type is None:  # pragma: no cover — defensive
        raise RuntimeError(
            f"DjangoObjectField target {field.type!r} has no compiled "
            "graphql_output_type. compile_all_outputs() must run before "
            "native root compilation."
        )

    args = {
        arg_name: graphene_arg_to_graphql_argument(arg, name=arg_name)
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
    field: Any, *, source_cls: type | None = None, field_name: str | None = None
) -> GraphQLField:
    """Convert a plain graphene scalar field to a graphql-core ``GraphQLField``.

    Args:
        field: A plain ``graphene.Field`` whose mounted type is a scalar/enum.
        source_cls: The source ObjectType class declaring the field; used to
            recover a ``resolve_<field_name>`` parent resolver (graphene parity).
        field_name: The snake_case field name (for the ``resolve_<name>`` lookup).

    Returns:
        A graphql-core ``GraphQLField``.
    """
    from django_graphex.native._args import _unwrap_graphene_type

    gql_type = _unwrap_graphene_type(field.type)
    args = {}
    if getattr(field, "args", None):
        from django_graphex.native._args import graphene_arg_to_graphql_argument

        args = {
            arg_name: graphene_arg_to_graphql_argument(arg, name=arg_name)
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


def _resolver_for(source_cls: type | None, field_name: str | None) -> Any:
    """Return the graphene parent resolver for a field, or the default resolver.

    Mirrors graphene's TypeMap wiring: the source ObjectType's
    ``resolve_<field_name>`` (unbound) when declared, else graphql-core's default
    attribute/dict resolver. ``field.wrap_resolve`` still prefers a field-level
    resolver over this fallback.

    Args:
        source_cls: The ObjectType class declaring the field (may be ``None``).
        field_name: The snake_case field name (may be ``None``).

    Returns:
        The parent resolver callable.
    """
    if source_cls is None or field_name is None:
        return default_field_resolver
    from graphene.utils.get_unbound_function import get_unbound_function

    method = getattr(source_cls, f"resolve_{field_name}", None)
    if method is not None:
        return get_unbound_function(method)
    return default_field_resolver


# Module-level memo so repeated references to the same plain graphene ObjectType
# (within one schema build OR across roots) compile to ONE native instance —
# identity-stable, no duplicate-name TypeError. Keyed by the source class.
_PLAIN_OBJECT_TYPE_CACHE: dict[type, GraphQLObjectType] = {}


def _is_plain_object_type(graphene_cls: Any) -> bool:
    """Return whether *graphene_cls* is a plain ``graphene.ObjectType`` subclass.

    "Plain" excludes the django-graphex output container/model types
    (``DjangoObjectType`` / ``DjangoListObjectType``), which carry their own
    canonical ``_meta.graphql_output_type`` and are compiled by the output
    registry — NOT on-the-fly here. It also excludes scalars/enums (handled by
    ``_build_scalar_field``) and non-class field types (wrappers).

    Args:
        graphene_cls: The mounted field ``type`` (``field.type``).

    Returns:
        ``True`` when *graphene_cls* is a class that is EITHER a native plain
        ``ObjectType`` (the S-ROOTS-b marker — e.g. ``ErrorType``) OR a graphene
        ``ObjectType`` subclass (transitional fallback), but is NOT a
        django-graphex container/model output type.
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

    # NATIVE-MARKER (S-ROOTS-b) — checked BEFORE the graphene fallback. A native
    # plain ``ObjectType`` (e.g. ``ErrorType``) is a ``native.base.ObjectType``
    # subclass with ``type(cls) is pydantic.ModelMetaclass``; it is NOT a
    # ``graphene.ObjectType``, so without this branch a native ErrorType would
    # fall through to the scalar arm (``_unwrap_graphene_type``) and KeyError /
    # silently vanish (the silent-drop EPICENTER). ``InputType`` is EXCLUDED: it
    # shares the native base but is an INPUT type, never a plain output object.
    from django_graphex.native.base import InputType
    from django_graphex.native.base import ObjectType as NativeObjectType

    if issubclass(graphene_cls, NativeObjectType):
        if issubclass(graphene_cls, InputType):
            return False
        return True

    # Transitional graphene fallback — graphene stays installed until S8; nested
    # plain-object fields may still be graphene ``ObjectType`` subclasses until the
    # remaining sub-slices convert them.
    import graphene

    return issubclass(graphene_cls, graphene.ObjectType)


def _compile_plain_object_type(graphene_cls: type) -> GraphQLObjectType:
    """Compile a plain ``graphene.ObjectType`` to a native type (memoized).

    Single-instance, on-the-fly. Each declared field becomes a native field:
    - a nested plain ``graphene.ObjectType`` field recurses through this builder
      (so ``Field(Plain)`` chains compile fully native, never falling into the
      scalar arm);
    - a ``DjangoObjectType`` / ``DjangoListObjectType`` field reuses its
      canonical ``_meta.graphql_output_type``;
    - anything else is a scalar/enum converted via ``_unwrap_graphene_type``.

    Resolvers are wired EXACTLY like graphene's TypeMap: the field's own
    ``resolver`` wins; otherwise the source class' ``resolve_<name>`` method (if
    any) or graphql-core's default attribute/dict resolver. The compiled type
    carries ``extensions['gdx']`` (D8) with the source graphene class so
    dual-backend read-sites can recover ``resolve_<field>`` methods.

    Args:
        graphene_cls: A plain ``graphene.ObjectType`` subclass.

    Returns:
        The canonical (memoized) native ``GraphQLObjectType`` for *graphene_cls*.
    """
    cached = _PLAIN_OBJECT_TYPE_CACHE.get(graphene_cls)
    if cached is not None:
        return cached

    type_name = (
        getattr(getattr(graphene_cls, "_meta", None), "name", None)
        or graphene_cls.__name__
    )

    def _make_fields(
        _cls: type = graphene_cls,
    ) -> dict[str, GraphQLField]:
        # Built lazily via a thunk so a self-referential plain ObjectType
        # (A → A) closes through the cache entry registered below BEFORE this
        # thunk evaluates — mirroring the GraphQLInputObjectType cache-before-eval
        # pattern (D5) on the output side.
        return _compile_plain_object_fields(_cls)

    native_type = GraphQLObjectType(
        name=type_name,
        fields=_make_fields,
        extensions={
            "gdx": GdxPayload(GdxMeta(name=type_name, graphene_type=graphene_cls))
        },
    )
    # Register BEFORE returning so recursive references resolve to this instance.
    _PLAIN_OBJECT_TYPE_CACHE[graphene_cls] = native_type
    return native_type


def _compile_plain_object_fields(graphene_cls: type) -> dict[str, GraphQLField]:
    """Build the native field dict for a plain ``graphene.ObjectType`` subclass.

    Args:
        graphene_cls: A plain ``graphene.ObjectType`` subclass.

    Returns:
        A ``{camelCase_name: GraphQLField}`` dict.
    """
    fields: dict[str, GraphQLField] = {}
    meta_fields = getattr(getattr(graphene_cls, "_meta", None), "fields", None) or {}
    for field_name, field in meta_fields.items():
        fields[to_camel_case(field_name)] = compile_declared_field(
            graphene_cls, field_name, field
        )
    return fields


def compile_declared_field(
    source_cls: type, field_name: str, field: Any
) -> GraphQLField:
    """Convert a single DECLARED graphene field to a native ``GraphQLField``.

    Shared by ``_compile_plain_object_fields`` (plain ObjectType compilation) and
    by ``types._compile_declared_fields`` (Slice D: declared NON-model fields on a
    ``DjangoObjectType`` — ``graphene.String()`` / ``graphene.Field(PlainType)`` /
    ``graphene.Int()`` / custom-resolver fields — that never enter ``model._meta``
    and so are not derived by ``compile_output_fields``).

    The field's mounted type is dispatched EXACTLY like graphene's TypeMap:

    - a nested plain ``graphene.ObjectType`` -> on-the-fly native type;
    - a ``DjangoObjectType`` / ``DjangoListObjectType`` -> its canonical
      ``_meta.graphql_output_type``;
    - a ``List`` / ``NonNull`` wrapper -> the inner leaf compiled, wrapper shape
      preserved;
    - any other leaf (scalar / enum) -> ``_unwrap_graphene_type``.

    Resolvers are wired EXACTLY like graphene: the field's own ``resolver`` wins,
    else the source class' ``resolve_<field_name>`` method, else graphql-core's
    default attribute/dict resolver.

    Args:
        source_cls: The class declaring the field (for the ``resolve_<name>``
            lookup).
        field_name: The snake_case declared field name.
        field: The mounted graphene field (``graphene.Field`` / scalar / etc.).

    Returns:
        A graphql-core ``GraphQLField`` mirroring the graphene declaration.
    """
    from django_graphex.native._args import graphene_arg_to_graphql_argument

    field_type = getattr(field, "type", None)
    if _is_plain_object_type(field_type):
        gql_type: Any = _compile_plain_object_type(field_type)
    else:
        target = _plain_django_output_type(field_type)
        if target is not None:
            gql_type = target
        else:
            # A graphene List/NonNull wrapper around a plain ObjectType
            # (e.g. ``errors: [ErrorType]`` on a mutation payload) must
            # compile the inner plain type and preserve the wrapper shape;
            # _unwrap_graphene_type only handles scalar leaves and would
            # raise a GDX_SCALAR_MAP KeyError for an inner ObjectType.
            gql_type = _compile_wrapped_field_type(field_type)

    args = {}
    if getattr(field, "args", None):
        args = {
            arg_name: graphene_arg_to_graphql_argument(arg, name=arg_name)
            for arg_name, arg in field.args.items()
        }

    resolve = field.wrap_resolve(_resolver_for(source_cls, field_name))
    return GraphQLField(
        gql_type,
        args=args,
        resolve=resolve,
        description=getattr(field, "description", None),
    )


def _compile_wrapped_field_type(field_type: Any) -> Any:
    """Compile a (possibly wrapped) graphene field type to a graphql-core type.

    Unwraps graphene ``List`` / ``NonNull`` structures, preserving the wrapper
    shape, and dispatches the inner leaf to the correct compiler:

    - an inner plain ``graphene.ObjectType`` (e.g. ``ErrorType``) compiles
      on-the-fly via ``_compile_plain_object_type`` (single-instance, memoized);
    - an inner ``DjangoObjectType`` / ``DjangoListObjectType`` reuses its
      canonical ``_meta.graphql_output_type``;
    - any other leaf (scalar/enum) goes through ``_unwrap_graphene_type``.

    This is what lets a mutation-payload field like ``errors: [ErrorType]`` —
    a ``graphene.List`` wrapping a plain ObjectType — compile natively instead of
    raising a ``GDX_SCALAR_MAP`` KeyError on ``ErrorType``.

    Args:
        field_type: The mounted graphene field ``type`` (a ``Structure`` wrapper
            or a leaf class).

    Returns:
        The corresponding graphql-core type (wrappers preserved).
    """
    from graphene.types.structures import List as GList
    from graphene.types.structures import NonNull as GNonNull

    from django_graphex.native._args import _unwrap_graphene_type

    if isinstance(field_type, GNonNull):
        return GraphQLNonNull(_compile_wrapped_field_type(field_type.of_type))
    if isinstance(field_type, GList):
        return GraphQLList(_compile_wrapped_field_type(field_type.of_type))

    if _is_plain_object_type(field_type):
        return _compile_plain_object_type(field_type)
    target = _plain_django_output_type(field_type)
    if target is not None:
        return target
    return _unwrap_graphene_type(field_type)


def _plain_django_output_type(field_type: Any) -> GraphQLObjectType | None:
    """Return the canonical native output type for a django-graphex output field.

    A plain ObjectType may reference a ``DjangoObjectType`` /
    ``DjangoListObjectType`` whose canonical native type lives on
    ``_meta.graphql_output_type``. Reuse it (identity-stable) instead of
    recompiling. Returns ``None`` for non-django types.

    Args:
        field_type: The mounted field ``type``.

    Returns:
        The canonical container ``GraphQLObjectType`` or ``None``.
    """
    import inspect

    if not inspect.isclass(field_type):
        return None
    from django_graphex.types import DjangoListObjectType, DjangoObjectType

    if issubclass(field_type, (DjangoObjectType, DjangoListObjectType)):
        compiled = getattr(
            getattr(field_type, "_meta", None), "graphql_output_type", None
        )
        return compiled
    return None


def _build_plain_object_field(
    field: Any, *, source_cls: type | None = None, field_name: str | None = None
) -> GraphQLField:
    """Build a native ``GraphQLField`` for a plain ``graphene.ObjectType`` field.

    Compiles the field's target plain ObjectType on-the-fly (single-instance,
    memoized) and converts the field's args. The resolver is wired via the
    field's own ``wrap_resolve`` so a field-level resolver still wins; otherwise
    the source class' ``resolve_<field_name>`` (graphene parity) or graphql-core's
    default attribute/dict resolver.

    Args:
        field: A ``graphene.Field`` whose ``type`` is a plain ``graphene.ObjectType``.
        source_cls: The ObjectType class declaring the field (for the
            ``resolve_<field_name>`` parent-resolver lookup).
        field_name: The snake_case field name.

    Returns:
        A graphql-core ``GraphQLField``.
    """
    from django_graphex.native._args import graphene_arg_to_graphql_argument

    output_type = _compile_plain_object_type(field.type)

    args = {}
    if getattr(field, "args", None):
        args = {
            arg_name: graphene_arg_to_graphql_argument(arg, name=arg_name)
            for arg_name, arg in field.args.items()
        }

    resolve = field.wrap_resolve(_resolver_for(source_cls, field_name))
    return GraphQLField(
        output_type,
        args=args,
        resolve=resolve,
        description=getattr(field, "description", None),
    )


def _filter_arg(field: Any) -> dict[str, GraphQLArgument]:
    """Return the native ``filter`` arg dict for a list field, or ``{}``.

    The native ``<Model>FilterInput`` is built by the WU3 native filter input
    builder and stored on the field's ``filter_type`` attribute (set in the
    field's ``__init__`` via the graphene builder for the graphene path) — but
    the GRAPHENE filter type is NOT usable as a native arg. We rebuild the native
    input here from the field's declared ``fields`` + ``custom_filters`` via the
    native backend so the arg is a real ``GraphQLInputObjectType`` whose coerced
    value (snake out_name keys) flows straight into ``to_q``.

    Args:
        field: A list field carrying ``filter_backend`` / ``fields`` /
            ``custom_filters`` (set by ``_build_filter_arg``).

    Returns:
        ``{"filter": GraphQLArgument(<Model>FilterInput)}`` when filterable
        fields are declared, else ``{}``.
    """
    declared_fields = getattr(field, "fields", None)
    custom_filters = getattr(field, "custom_filters", None) or []
    if not declared_fields and not custom_filters:
        return {}

    model = field.model
    node_type = _unwrap_to_node_type(field)
    registry = getattr(getattr(node_type, "_meta", None), "registry", None)

    from django_graphex.filtering.native_schema import build_filter_input_type

    native_input = build_filter_input_type(
        model, declared_fields, registry, custom_filters=custom_filters
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


def _list_container_output_type(field: Any) -> GraphQLObjectType:
    """Return the canonical native container type for a list-object field.

    Reuses the WU1b list-container ``_meta.graphql_output_type`` (identity-stable,
    carries ``extensions['gdx']``). NEVER rebuilds a second container instance.

    Args:
        field: A ``DjangoListObjectField`` (or subclass) whose ``type`` is a
            ``DjangoListObjectType``.

    Returns:
        The canonical container ``GraphQLObjectType``.

    Raises:
        RuntimeError: When the container has no compiled ``graphql_output_type``
            (compile_all_outputs() must run before native root compilation).
    """
    container = getattr(getattr(field.type, "_meta", None), "graphql_output_type", None)
    if container is None:  # pragma: no cover — defensive
        raise RuntimeError(
            f"DjangoListObjectField target {field.type!r} has no compiled "
            "graphql_output_type. compile_all_outputs() must run before native "
            "root compilation (WU1b list-container compile)."
        )
    return container


def _build_list_object_field(field: Any) -> GraphQLField:
    """Build a native ``GraphQLField`` for a ``DjangoListObjectField``.

    The output type is the WU1b list-container (``results`` + ``totalCount``
    [+ ``pageInfo``]); the container's ``results`` field carries the pagination
    args + slicing resolver (wired in types.py WU6a). The list field itself
    carries the ``filter`` arg (when filterable) and a resolver that filters the
    queryset and returns a ``DjangoListObjectBase`` — the page slicing then
    happens on the container's results field.

    Args:
        field: A ``DjangoListObjectField`` (or ``DjangoNestedListObjectField``).

    Returns:
        A graphql-core ``GraphQLField``.
    """
    output_type = _list_container_output_type(field)
    args = _filter_arg(field)
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
    """Unwrap a list field's ``type`` to the inner ``DjangoObjectType`` node.

    ``DjangoFilterListField.type`` is a ``graphene.List`` (possibly wrapping a
    ``graphene.NonNull``) around the node ``DjangoObjectType``. graphql-core
    wrappers may also be present in mixed states. Peel every wrapper to reach the
    node class that carries ``_meta.graphql_output_type``.

    Args:
        field: A list field whose ``type`` wraps a ``DjangoObjectType``.

    Returns:
        The inner node type class (carrying ``_meta``).
    """
    from graphene.types.structures import Structure

    current = field.type
    while True:
        if isinstance(current, (GraphQLList, GraphQLNonNull)):
            current = current.of_type
        elif isinstance(current, Structure):
            current = current.of_type
        else:
            return current


def _build_filter_list_field(field: Any) -> GraphQLField:
    """Build a native ``GraphQLField`` for a plain filtered list field.

    Covers ``DjangoFilterListField`` (no pagination → ``[Node]``) and
    ``DjangoFilterPaginateListField`` (filter + in-resolver pagination →
    ``[Node!]``). The output type mirrors the graphene shape: a
    ``GraphQLList`` of the node's canonical ``graphql_output_type``. Pagination
    args (when present) are added directly to the field; filtering + slicing
    happen inside the field's own ``list_resolver`` (reused via ``wrap_resolve``).

    Args:
        field: A ``DjangoFilterListField`` or ``DjangoFilterPaginateListField``.

    Returns:
        A graphql-core ``GraphQLField``.
    """
    node_type = _unwrap_to_node_type(field)
    node_output = node_type._meta.graphql_output_type
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

    args = _filter_arg(field)
    # Pagination args (DjangoFilterPaginateListField only): the paginator slices
    # inside list_resolver, so the args must be on THIS field.
    paginator = getattr(field, "pagination", None)
    if paginator is not None:
        args.update(paginator.to_graphql_fields(native=True))

    resolve = field.wrap_resolve(default_field_resolver)
    return GraphQLField(
        list_type,
        args=args,
        resolve=resolve,
        description=getattr(field, "description", None),
    )


def compile_native_root(root: type, *, name: str) -> GraphQLObjectType:
    """Compile a graphene root ObjectType into a native ``GraphQLObjectType``.

    Args:
        root: The graphene root ObjectType class (Query / Mutation /
            Subscription). May be ``None``.
        name: The GraphQL type name for the compiled root.

    Returns:
        A graphql-core ``GraphQLObjectType`` whose fields' types are the
        canonical native instances, or ``None`` if ``root`` is ``None``.

    Raises:
        NotImplementedError: If the root declares a field kind whose native
            builder does not exist yet (list/filter/pagination — WU3/WU5/WU6).
            The error names the field and the owning WU. NEVER silently skipped.
    """
    if root is None:
        return None  # type: ignore[return-value]

    # Import field classes lazily to avoid a hard import cycle at module load.
    from django_graphex.fields import (
        DjangoFilterListField,
        DjangoFilterPaginateListField,
        DjangoListObjectField,
        DjangoObjectField,
    )

    fields: dict[str, GraphQLField] = {}

    # 1) graphene-mounted fields (DjangoObjectField, list/filter fields, scalars).
    meta_fields = getattr(getattr(root, "_meta", None), "fields", None) or {}
    for field_name, field in meta_fields.items():
        kind = type(field).__name__
        if kind in _DEFERRED_FIELD_KINDS:
            raise NotImplementedError(
                f"Native root compiler cannot yet build field {field_name!r} "
                f"of kind {kind!r} on root {name!r}. The native field builder "
                f"for this kind is owned by {_DEFERRED_FIELD_KINDS[kind]}."
            )
        # The wire name honors an explicit ``name=`` kwarg (e.g.
        # ``CustomDate(name="date")``) exactly as graphene does; the snake
        # ``field_name`` is still used for the ``resolve_<field_name>`` lookup.
        wire_name = _rendered_field_name(field, field_name)
        if _is_subscription_field(field):
            # Subscription root field (WU7): the mounted ``SubscriptionField``
            # carries the Subscription subclass as its ``type`` (``_meta.output``).
            # Build the DIRECT native subscription field (event type + subscribe
            # source factory + reduced {action,id,filters} args) via the class'
            # own ``_build_native_field``. schema/document are supplied by the
            # transport at delivery time (the source build does not need them).
            fields[wire_name] = field.type._build_native_field()
        elif isinstance(field, DjangoObjectField):
            fields[wire_name] = _build_object_field(field)
        elif isinstance(field, DjangoListObjectField):
            # DjangoListObjectField (and DjangoNestedListObjectField) → the WU1b
            # list-container output type; pagination args/resolver live on the
            # container's results field (WU6a), filter arg on this field.
            fields[wire_name] = _build_list_object_field(field)
        elif isinstance(field, (DjangoFilterListField, DjangoFilterPaginateListField)):
            # Plain filtered list ([Node] / [Node!]); pagination (when present)
            # slices inside the field's own list_resolver (args on this field).
            fields[wire_name] = _build_filter_list_field(field)
        elif _is_plain_object_type(getattr(field, "type", None)):
            # Slice A: a plain graphene.ObjectType field (NOT a DjangoObjectType,
            # NOT a scalar) compiles on-the-fly to a single-instance native
            # GraphQLObjectType (recurses; carries extensions['gdx']). Without
            # this it would fall to _build_scalar_field → _unwrap_graphene_type →
            # GDX_SCALAR_MAP KeyError (e.g. the test_security `_Nested` field).
            fields[wire_name] = _build_plain_object_field(
                field, source_cls=root, field_name=field_name
            )
        else:
            # Plain graphene scalar/enum field (e.g. CustomDateTime).
            fields[wire_name] = _build_scalar_field(
                field, source_cls=root, field_name=field_name
            )

    # 2) raw native mutation fields graphene dropped from _meta.fields.
    for attr_name, gql_field in _collect_root_attrs(root).items():
        fields[to_camel_case(attr_name)] = gql_field

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
