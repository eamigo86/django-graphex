"""Native polymorphic-type compiler: DjangoUnionType / DjangoInterfaceType.

DEFECT #8 (Track 2) — the native compiler historically treated a
``DjangoUnionType`` / ``DjangoInterfaceType`` as a plain ``ObjectType`` (both are
now ``native.base.ObjectType`` subclasses, S6d), so a union field compiled to a
``GraphQLObjectType`` and an interface was never wired onto its implementors.
graphql-core has ``GraphQLUnionType`` + ``GraphQLInterfaceType`` built in; this
module compiles the registry-only metadata carriers into those real graphql-core
abstract types, mirroring what the legacy graphene path produced.

What the legacy graphene path did (for parity):
- ``DjangoUnionType`` derived from graphene ``Union`` -> graphene built a
  ``GraphQLUnionType`` whose ``types`` were the members' ``GraphQLObjectType`` and
  whose ``resolve_type`` was the union's classmethod mapping a resolved Django row
  to its registered ``DjangoObjectType`` (``registry.get_type_for_model``).
- ``DjangoInterfaceType`` derived from graphene ``Interface`` -> graphene built a
  ``GraphQLInterfaceType`` with the declared shared fields and the same
  ``resolve_type`` contract; concrete object types named it via ``Meta.interfaces``
  and graphene listed it under their ``interfaces=``.

Native parity below:
- ``compile_union_type`` -> memoized ``GraphQLUnionType`` with member
  ``graphql_output_type`` instances + a ``resolve_type`` bridging the union's own
  ``resolve_type`` to a graphql-core type NAME (graphql-core accepts a type, type
  name, or ``GraphQLObjectType``).
- ``compile_interface_type`` -> memoized ``GraphQLInterfaceType`` with the
  declared shared fields (compiled via the SAME declared-field compiler the object
  types use) + the bridged ``resolve_type``.
- Both carry ``extensions['gdx']`` (``graphene_type=<polymorphic cls>``) so
  dual-backend read-sites recover the source class.

No top-level graphene import; member types are resolved through their canonical
``_meta.graphql_output_type`` (the shared output-registry instance).
"""

from __future__ import annotations

from typing import Any

from graphql import (
    GraphQLInterfaceType,
    GraphQLObjectType,
    GraphQLUnionType,
)

from django_graphex.native.base import (
    SchemaRegistries,
    default_schema_registries,
)
from django_graphex.native.bridge import GdxPayload
from django_graphex.native.ir import GdxMeta

# Memo so a union/interface referenced by multiple fields (or by a field AND
# ``types=``) compiles to ONE instance — identity-stable, no duplicate-name
# TypeError. Keyed by the polymorphic source class.
#
# item-b (B2): these dicts are the DEFAULT pair's union/interface cache
# namespaces — ``default_schema_registries().union_cache`` /
# ``.interface_cache`` ARE these very objects (bound by identity). Every
# entrypoint resolves its cache from the threaded ``SchemaRegistries`` pair, so
# the default path keeps writing here (byte-identical) while a forked pair (later
# slices) owns its own namespace.
_UNION_TYPE_CACHE: dict[type, GraphQLUnionType] = {}
_INTERFACE_TYPE_CACHE: dict[type, GraphQLInterfaceType] = {}


def _resolve_registries(registries: SchemaRegistries | None) -> SchemaRegistries:
    """Return *registries* or the process-wide default pair (byte-identical)."""
    return registries if registries is not None else default_schema_registries()


def is_union_type(cls: Any) -> bool:
    """Return whether *cls* is a ``DjangoUnionType`` subclass."""
    import inspect

    if not inspect.isclass(cls):
        return False
    from django_graphex.types import DjangoUnionType

    return issubclass(cls, DjangoUnionType)


def is_interface_type(cls: Any) -> bool:
    """Return whether *cls* is a ``DjangoInterfaceType`` subclass."""
    import inspect

    if not inspect.isclass(cls):
        return False
    from django_graphex.types import DjangoInterfaceType

    return issubclass(cls, DjangoInterfaceType)


def _member_output_type(
    member_cls: Any, registries: SchemaRegistries | None = None
) -> GraphQLObjectType:
    """Return the ``GraphQLObjectType`` for a union/interface member.

    The member is a ``DjangoObjectType`` whose native type lives on
    ``_meta.graphql_output_type`` (built at the member's class-def time, populated
    by ``compile_all_outputs``). Reuse it (NEVER recompile) so the union member is
    the SAME instance the schema resolves objects to.

    item-b (B5): under a non-default (forked) pair, return the member's FORKED
    instance so the union member matches the SAME schema's object types (default
    pair / no fork -> the class-def instance -> byte-identical).

    Args:
        member_cls: A ``DjangoObjectType`` subclass (a union member or interface
            implementor).
        registries: The ``SchemaRegistries`` pair (forked member resolution);
            ``None`` -> the class-def instance (byte-identical).

    Returns:
        The member's ``GraphQLObjectType`` (forked or canonical).

    Raises:
        RuntimeError: When the member has no compiled ``graphql_output_type``
            (its class-def native compile must have run first).
    """
    from django_graphex.native.base import resolved_output_type

    compiled = resolved_output_type(member_cls, registries)
    if compiled is None:  # pragma: no cover — defensive
        raise RuntimeError(
            f"Polymorphic member {member_cls!r} has no compiled "
            "graphql_output_type. DjangoObjectType class-def native compile must "
            "run before union/interface compilation."
        )
    return compiled


def _make_resolve_type(polymorphic_cls: Any) -> Any:
    """Build the graphql-core ``resolve_type`` for a union/interface.

    graphql-core calls ``resolve_type(value, info, abstract_type)`` and accepts a
    return of a ``GraphQLObjectType``, a type NAME (str), or ``None``. The
    polymorphic class' own ``resolve_type(instance, info)`` returns the registered
    ``DjangoObjectType`` for the row's concrete model; we map that to its GraphQL
    type NAME so graphql-core resolves to the right member instance (returning the
    name avoids any identity mismatch between the member's compiled instance and
    the one threaded into ``GraphQLUnionType.types``).

    A ``TypeError`` from the polymorphic ``resolve_type`` (an unregistered member
    model) PROPAGATES — a silent ``None`` would surface as the opaque "Abstract
    type must resolve to an Object type" graphql-core error far from the cause.
    """

    def _resolve_type(value: Any, info: Any, _abstract: Any) -> Any:
        object_type = polymorphic_cls.resolve_type(value, info)
        # Return the GraphQL NAME; graphql-core looks it up in the schema's type
        # map (identity-safe vs. returning a possibly-distinct instance).
        return getattr(object_type._meta, "name", None) or object_type.__name__

    return _resolve_type


def compile_union_type(
    union_cls: Any, registries: SchemaRegistries | None = None
) -> GraphQLUnionType:
    """Compile a ``DjangoUnionType`` to a graphql-core ``GraphQLUnionType``.

    Memoized (single instance per union class). The member ``types`` are the
    members' canonical ``graphql_output_type`` instances (lazy thunk so members
    declared after the union still resolve), and ``resolve_type`` bridges the
    union's own classmethod to a graphql-core type name.

    Args:
        union_cls: A ``DjangoUnionType`` subclass.
        registries: The ``SchemaRegistries`` pair owning the union cache
            namespace; defaults to the global pair (byte-identical, item-b B1/B2).

    Returns:
        The canonical (memoized) ``GraphQLUnionType`` for *union_cls*.
    """
    registries = _resolve_registries(registries)
    cache = registries.union_cache
    cached = cache.get(union_cls)
    if cached is not None:
        return cached

    name = getattr(union_cls._meta, "name", None) or union_cls.__name__
    member_types = tuple(getattr(union_cls._meta, "types", ()) or ())

    def _types(
        _members: tuple[Any, ...] = member_types,
        _registries: SchemaRegistries = registries,
    ) -> list[GraphQLObjectType]:
        # Lazy: a union member's ``graphql_output_type`` may not be populated until
        # ``compile_all_outputs`` runs; defer the read to schema-build time.
        # item-b (B5): resolve members against THIS pair (forked under a
        # non-default pair; class-def instances under the default pair).
        return [_member_output_type(m, _registries) for m in _members]

    gql_union = GraphQLUnionType(
        name=name,
        types=_types,
        resolve_type=_make_resolve_type(union_cls),
        extensions={"gdx": GdxPayload(GdxMeta(name=name, graphene_type=union_cls))},
    )
    cache[union_cls] = gql_union
    return gql_union


def compile_interface_type(
    interface_cls: Any, registries: SchemaRegistries | None = None
) -> GraphQLInterfaceType:
    """Compile a ``DjangoInterfaceType`` to a graphql-core ``GraphQLInterfaceType``.

    Memoized (single instance per interface class). The shared fields are the
    interface's declared ``_meta.fields`` compiled via the SAME declared-field
    compiler the object types use (so an interface ``name = graphene.String()``
    becomes a matching ``name: String`` field). ``resolve_type`` bridges the
    interface's own classmethod to a graphql-core type name.

    Args:
        interface_cls: A ``DjangoInterfaceType`` subclass.
        registries: The ``SchemaRegistries`` pair owning the interface cache
            namespace (and threaded into the declared-field compile); defaults to
            the global pair (byte-identical, item-b B1/B2).

    Returns:
        The canonical (memoized) ``GraphQLInterfaceType`` for *interface_cls*.
    """
    registries = _resolve_registries(registries)
    cache = registries.interface_cache
    cached = cache.get(interface_cls)
    if cached is not None:
        return cached

    name = getattr(interface_cls._meta, "name", None) or interface_cls.__name__

    def _fields(
        _cls: type = interface_cls,
        _registries: SchemaRegistries = registries,
    ) -> dict[str, Any]:
        # Lazy thunk (cache-before-eval): the cache entry is registered BEFORE this
        # evaluates so a self-referential field closes through this instance.
        from django_graphex.native.schema_compiler import compile_declared_field

        declared = getattr(getattr(_cls, "_meta", None), "fields", None) or {}
        from django_graphex._strconv import to_camel_case

        out: dict[str, Any] = {}
        for field_name, field in declared.items():
            out[to_camel_case(field_name)] = compile_declared_field(
                _cls, field_name, field, _registries
            )
        return out

    gql_interface = GraphQLInterfaceType(
        name=name,
        fields=_fields,
        resolve_type=_make_resolve_type(interface_cls),
        extensions={
            "gdx": GdxPayload(GdxMeta(name=name, graphene_type=interface_cls))
        },
    )
    cache[interface_cls] = gql_interface
    return gql_interface


def compile_polymorphic_type(
    cls: Any, registries: SchemaRegistries | None = None
) -> Any:
    """Dispatch a union/interface class to its native compiler.

    Args:
        cls: A ``DjangoUnionType`` or ``DjangoInterfaceType`` subclass.
        registries: The ``SchemaRegistries`` pair owning the union/interface
            caches; defaults to the global pair (byte-identical, item-b B1/B2).

    Returns:
        A ``GraphQLUnionType`` or ``GraphQLInterfaceType``.

    Raises:
        TypeError: If *cls* is neither a union nor an interface.
    """
    registries = _resolve_registries(registries)
    if is_union_type(cls):
        return compile_union_type(cls, registries)
    if is_interface_type(cls):
        return compile_interface_type(cls, registries)
    raise TypeError(
        f"compile_polymorphic_type expects a DjangoUnionType or "
        f"DjangoInterfaceType, received {cls!r}."
    )
