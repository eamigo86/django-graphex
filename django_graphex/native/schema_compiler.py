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

from graphene.utils.str_converters import to_camel_case
from graphql import GraphQLField, GraphQLObjectType
from graphql.execution import default_field_resolver

from django_graphex.native.bridge import GdxPayload
from django_graphex.native.ir import GdxMeta

# Map of not-yet-supported field-kind class names → the WU that owns the native
# builder. Used to produce a precise NotImplementedError instead of a silent skip.
_DEFERRED_FIELD_KINDS: dict[str, str] = {
    "DjangoFilterListField": "WU3 (native filter-arg fields)",
    "DjangoFilterPaginateListField": "WU3/WU6 (native filter + pagination fields)",
    "DjangoListObjectField": "WU5/WU6 (native pagination/list fields)",
    "DjangoNestedListObjectField": "WU6 (native nested pagination/list fields)",
}


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
    from django_graphex.mutation import _NATIVE_FIELD_REGISTRY

    # Identity set of the exact GraphQLField instances the mutation machinery
    # registered; membership proves a recovered attr is a native mutation field.
    native_field_ids = {id(f) for f in _NATIVE_FIELD_REGISTRY.values()}

    found: dict[str, Any] = {}
    for klass in reversed(root.__mro__):
        for attr_name, value in vars(klass).items():
            if isinstance(value, GraphQLField) and id(value) in native_field_ids:
                found[attr_name] = value
    return found


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


def _build_scalar_field(field: Any) -> GraphQLField:
    """Convert a plain graphene scalar field to a graphql-core ``GraphQLField``.

    Args:
        field: A plain ``graphene.Field`` whose mounted type is a scalar/enum.

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
    resolve = field.wrap_resolve(default_field_resolver)
    return GraphQLField(
        gql_type,
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
    from django_graphex.fields import DjangoObjectField

    fields: dict[str, GraphQLField] = {}

    # 1) graphene-mounted fields (DjangoObjectField, plain scalars, …).
    meta_fields = getattr(getattr(root, "_meta", None), "fields", None) or {}
    for field_name, field in meta_fields.items():
        kind = type(field).__name__
        if kind in _DEFERRED_FIELD_KINDS:
            raise NotImplementedError(
                f"Native root compiler cannot yet build field {field_name!r} "
                f"of kind {kind!r} on root {name!r}. The native field builder "
                f"for this kind is owned by {_DEFERRED_FIELD_KINDS[kind]}."
            )
        if isinstance(field, DjangoObjectField):
            fields[to_camel_case(field_name)] = _build_object_field(field)
        else:
            # Plain graphene scalar/enum field (e.g. CustomDateTime).
            fields[to_camel_case(field_name)] = _build_scalar_field(field)

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
