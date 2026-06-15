"""Native field-descriptor currency for the duck-typed compiler (S-ROOTS-a).

The native schema compiler consumes DECLARED / ROOT fields purely by DUCK
TYPING — it reads ``field.type`` / ``field.args`` / ``field.name`` /
``field.description`` and calls ``field.wrap_resolve(parent_resolver)`` with NO
``isinstance(graphene.Field)`` guard (see ``schema_compiler.compile_declared_field``
:369 and ``schema_compiler.compile_native_root`` :719). Historically the only
things that exposed that shape were graphene ``Field`` / ``UnmountedType``
instances.

``NativeField`` is the graphene-free replacement for that currency. It exposes
the EXACT read-contract the compiler relies on, so a ``field(...)``-declared
field drops straight into the existing dispatch and compiles to the right
graphql-core field — never silently vanishing (the paramount S-ROOTS risk).

The public ``field()`` helper (decision #1554) is the single idiom users write
to declare a custom (non-model) field on a root / ``ObjectType``::

    from django_graphex import ObjectType, field
    from graphql import GraphQLString, GraphQLList, GraphQLNonNull

    class Query(ObjectType):
        server_time = field(GraphQLString, description="ISO timestamp")
        me = field(UserType)                         # a DjangoObjectType ref
        tags = field(GraphQLList(GraphQLString))     # list via graphql-core wrapper
        name = field(GraphQLNonNull(GraphQLString))  # non-null via wrapper

        def resolve_server_time(self, info): ...

Type expression (decision #1554):
- A graphql-core type (``GraphQLScalarType`` / ``GraphQLObjectType`` /
  ``GraphQLEnumType`` / ``GraphQLInputObjectType``) is used VERBATIM.
- ``GraphQLList`` / ``GraphQLNonNull`` express list / non-null — there is ONE
  idiom (the graphql-core wrappers), no parallel graphene-clone surface.
- A django-graphex output type CLASS (``DjangoObjectType`` /
  ``DjangoListObjectType``, or anything carrying
  ``_meta.graphql_output_type``) is accepted and resolved LAZILY to its
  compiled graphql-core type when ``.type`` is read by the compiler — so the
  field can reference an output type declared after the descriptor.

Graphene import policy:
- This module is the NATIVE currency. It has ZERO top-level ``import graphene``
  (and zero lazy one) so it imports cleanly under both backends and after
  graphene is uninstalled (S8).
"""

from __future__ import annotations

from typing import Any, Callable, Optional


def _resolve_field_type(declared_type: Any) -> Any:
    """Resolve a declared ``field()`` type to the graphql-core type the compiler reads.

    Resolution order:
    1. A django-graphex output type class carrying a compiled
       ``_meta.graphql_output_type`` (``DjangoObjectType`` /
       ``DjangoListObjectType``) -> that canonical graphql-core type. This is
       evaluated LAZILY (on every ``.type`` read) so a forward reference to a
       type compiled later (``compile_all_outputs()`` runs before root
       compilation) resolves to the real instance, not ``None``.
    2. Anything else (a graphql-core ``GraphQLType``: scalar / object / enum /
       input / ``GraphQLList`` / ``GraphQLNonNull`` wrapper, OR a graphene type
       left as a transitional fallback) -> returned VERBATIM. The compiler's
       ``_unwrap_graphene_type`` / ``_is_plain_object_type`` /
       ``_plain_django_output_type`` dispatch already handles each of those
       shapes, so the descriptor stays a thin pass-through.

    Args:
        declared_type: The ``type`` argument passed to ``field()`` / ``NativeField``.

    Returns:
        The graphql-core type (or a class the compiler can dispatch) the field
        should expose as ``.type``.
    """
    meta = getattr(declared_type, "_meta", None)
    if meta is not None:
        compiled = getattr(meta, "graphql_output_type", None)
        if compiled is not None:
            return compiled
    return declared_type


class NativeField:
    """Graphene-free field descriptor matching the compiler's read-contract.

    The native schema compiler reads exactly these off a declared / root field
    (all via ``getattr`` — no ``isinstance`` guard):

    - ``type`` -> the field's graphql-core output type (resolved lazily for a
      django-graphex output-type class reference).
    - ``args`` -> a ``{name: GraphQLArgument}`` dict, or ``None``.
    - ``name`` -> an explicit wire name (``field(name=...)``) or ``None``
      (the compiler camelCases the attribute name when ``None``).
    - ``description`` -> the field description, or ``None``.
    - ``wrap_resolve(parent_resolver)`` -> the final resolver. Mirrors graphene
      ``Field.wrap_resolve``: the field's own ``resolver`` wins, else the
      ``parent_resolver`` the compiler supplies (the source class'
      ``resolve_<name>`` or graphql-core's default attribute/dict resolver).
    """

    __slots__ = ("_declared_type", "_args", "_name", "_description", "_resolver")

    def __init__(
        self,
        type: Any,  # noqa: A002 - mirrors the public field() positional name
        *,
        description: Optional[str] = None,
        args: Optional[dict[str, Any]] = None,
        resolver: Optional[Callable[..., Any]] = None,
        name: Optional[str] = None,
    ) -> None:
        """Build a native field descriptor.

        Args:
            type: The field's graphql-core type, OR a django-graphex output type
                class (resolved lazily to its compiled graphql-core type).
                List / non-null are expressed with graphql-core ``GraphQLList`` /
                ``GraphQLNonNull`` wrappers.
            description: Optional field description.
            args: Optional ``{name: GraphQLArgument}`` argument dict.
            resolver: Optional field-level resolver. When set it WINS in
                ``wrap_resolve`` over the compiler-supplied parent resolver
                (graphene parity).
            name: Optional explicit wire name. When set the compiler uses it
                verbatim (no camelCase pass); when ``None`` the compiler
                camelCases the declared attribute name.
        """
        self._declared_type = type
        self._args = args
        self._name = name
        self._description = description
        self._resolver = resolver

    @property
    def type(self) -> Any:  # noqa: A003 - matches the compiler's read attr
        """Return the field's graphql-core type (django output refs resolved lazily)."""
        return _resolve_field_type(self._declared_type)

    @property
    def args(self) -> Optional[dict[str, Any]]:
        """Return the ``{name: GraphQLArgument}`` arg dict, or ``None``."""
        return self._args

    @property
    def name(self) -> Optional[str]:
        """Return the explicit wire name, or ``None`` (compiler camelCases)."""
        return self._name

    @property
    def description(self) -> Optional[str]:
        """Return the field description, or ``None``."""
        return self._description

    @property
    def resolver(self) -> Optional[Callable[..., Any]]:
        """Return the field-level resolver, or ``None``."""
        return self._resolver

    def wrap_resolve(self, parent_resolver: Any) -> Any:
        """Return the final resolver (own resolver wins, else the parent).

        Byte-equivalent to graphene ``Field.wrap_resolve`` (which is simply
        ``return self.resolver or parent_resolver``), so the compiler's
        ``field.wrap_resolve(...)`` call at schema_compiler.py:404-432 works
        unchanged against a ``NativeField``.

        Args:
            parent_resolver: The fallback resolver the compiler supplies (the
                source class' ``resolve_<name>`` or graphql-core's default).

        Returns:
            ``self.resolver`` when set, else ``parent_resolver``.
        """
        return self._resolver or parent_resolver

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        """Return a short debug representation of the descriptor."""
        return (
            f"<NativeField type={self._declared_type!r} name={self._name!r}>"
        )


def field(
    type: Any,  # noqa: A002 - public positional API (decision #1554)
    *,
    description: Optional[str] = None,
    args: Optional[dict[str, Any]] = None,
    resolver: Optional[Callable[..., Any]] = None,
    name: Optional[str] = None,
) -> NativeField:
    """Declare a custom (non-model) field on a root / ``ObjectType``.

    The single graphene-free idiom (decision #1554) for hand-declared fields::

        server_time = field(GraphQLString, description="ISO timestamp")
        me = field(UserType)
        tags = field(GraphQLList(GraphQLString))

    Args:
        type: A graphql-core type used verbatim (``GraphQLScalarType`` /
            ``GraphQLObjectType`` / ``GraphQLEnumType`` /
            ``GraphQLInputObjectType`` / ``GraphQLList`` / ``GraphQLNonNull``),
            OR a django-graphex output type class (``DjangoObjectType`` /
            ``DjangoListObjectType``) resolved lazily to its compiled
            graphql-core type. List / non-null are expressed with the
            graphql-core wrappers.
        description: Optional field description.
        args: Optional ``{name: GraphQLArgument}`` argument dict.
        resolver: Optional field-level resolver (wins over the parent resolver).
        name: Optional explicit wire name (verbatim; no camelCase pass).

    Returns:
        A ``NativeField`` the native compiler consumes directly.
    """
    return NativeField(
        type,
        description=description,
        args=args,
        resolver=resolver,
        name=name,
    )
