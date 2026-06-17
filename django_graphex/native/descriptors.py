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

import inspect
import sys
from functools import partial, total_ordering
from typing import Any, Callable, Optional

# ---------------------------------------------------------------------------
# Graphene-free ordering counter (graphene OrderedType replica)
# ---------------------------------------------------------------------------
# ``_yank_fields`` (types.py) sorts the mounted descriptors by their
# ``creation_counter`` so the SDL field order matches declaration order — exactly
# what graphene's ``OrderedType`` provided. ``NativeMountedField`` carries one so
# a field declared off graphene keeps stable, declaration-ordered output. The
# counter is a SHARED, monotonically-increasing process-global integer (graphene
# parity: graphene's ``OrderedType.creation_counter`` is one global counter, so a
# graphene ``Field`` and a ``NativeMountedField`` interleave in a single order
# space during the transitional dual-currency window).
#
# We deliberately reuse graphene's OWN global counter at runtime (when graphene is
# importable) so a class body mixing a graphene descriptor (e.g. a relation
# ``Dynamic`` mounted via ``_as``) and a native list field keeps the SAME relative
# order graphene would have produced. The lazy import is wrapped so the descriptor
# stays import-safe after graphene is uninstalled (S8i): it then falls back to a
# local counter.
_LOCAL_COUNTER = [0]


def _next_creation_counter() -> int:
    """Return the next monotonic creation counter (graphene-free on the native path).

    Mirrors ``graphene.utils.orderedtype.OrderedType.gen_counter``: a single
    process-global, monotonically-increasing integer that lets ``_yank_fields``
    sort ``_meta.fields`` by declaration order for SDL parity.

    The native path NEVER imports graphene to obtain this counter (S-milestone-9
    zero-graphene gate): a ``field()`` / ``Django*Field`` declared at RUNTIME must
    not drag in the whole graphene tree. ``_yank_fields`` only keeps native
    descriptors (``NativeMountedField`` / ``NativeField``) — the migration retired
    the graphene-marker branch (S-input-5) — so there is no longer a mixed
    native+graphene order space to share, and a local counter is sufficient.

    For belt-and-suspenders parity during the brief window where a graphene-ROOT
    schema is built in the SAME process AND graphene is ALREADY imported, we keep
    advancing graphene's OWN counter so the two stay interleaved — but ONLY when
    graphene is already in ``sys.modules`` (we never trigger the import ourselves).
    After graphene is uninstalled (S8i) the local counter is the only path.
    """
    g = sys.modules.get("graphene.utils.orderedtype")
    if g is not None:  # pragma: no cover - graphene already loaded by another path
        ordered_type = getattr(g, "OrderedType", None)
        if ordered_type is not None:
            counter = ordered_type.creation_counter
            ordered_type.creation_counter += 1
            return counter
    _LOCAL_COUNTER[0] += 1
    return _LOCAL_COUNTER[0]


def _source_resolver(source: str, root: Any, info: Any, **args: Any) -> Any:
    """Graphene-free replica of ``graphene.types.field.source_resolver``.

    A ``field(..., source="attr")`` declaration resolves by reading ``attr`` off
    the root (dict-key for a mapping, attribute otherwise), then CALLING the
    result when it is a function / method (graphene parity — lets a source point
    at a zero-arg method). Used by ``NativeMountedField`` to honor the graphene
    ``source=`` kwarg (e.g. ``graphene.String(source="name")`` declared on a
    ``DjangoModelType``) without importing graphene.

    Args:
        source: The attribute / key name to read off the root.
        root: The resolved parent value.
        info: The GraphQL resolve info (unused; signature parity).
        **args: Field arguments (unused; signature parity).

    Returns:
        The source value (called when it is a function / method).
    """
    import inspect as _inspect

    if isinstance(root, dict):
        resolved = root.get(source, None)
    else:
        resolved = getattr(root, source, None)
    if _inspect.isfunction(resolved) or _inspect.ismethod(resolved):
        return resolved()
    return resolved


def _resolve_thunk(_type: Any) -> Any:
    """Graphene-free replica of ``graphene.types.utils.get_type``.

    Resolves a deferred field/arg type expression to the concrete value the
    compiler reads:

    - a dotted import-path string -> the imported object;
    - a zero-arg function / ``functools.partial`` -> its return value (a lazy
      forward reference, e.g. ``lambda: SomeType``);
    - anything else (a class, a graphql-core type, a native wrapper) -> verbatim.

    Byte-equivalent to graphene's ``get_type`` so a ``NativeMountedField`` resolves
    the same thunk shapes the field classes historically relied on.
    """
    if isinstance(_type, str):
        from django.utils.module_loading import import_string

        return import_string(_type)
    if inspect.isfunction(_type) or isinstance(_type, partial):
        return _type()
    return _type


@total_ordering
class NativeMountedField:
    """Graphene-free field-descriptor base for the ``Django*Field`` classes (S8c).

    The native schema compiler consumes a DECLARED / ROOT field purely by DUCK
    TYPING — it reads ``field.type`` / ``field.args`` / ``field.name`` /
    ``field.description`` / ``field.resolver`` and calls
    ``field.wrap_resolve(parent_resolver)`` with NO ``isinstance(graphene.Field)``
    guard (the same contract :class:`NativeField` documents). The
    ``django_graphex.fields`` field classes (``DjangoObjectField`` /
    ``DjangoListObjectField`` / ``DjangoFilterListField`` /
    ``DjangoFilterPaginateListField`` / ``DjangoNestedListObjectField`` /
    ``AnnotatedField``) historically subclassed graphene ``Field`` to get that
    shape; S8c re-parents them onto THIS base so they expose the same contract
    with ZERO graphene dependency.

    Read-contract (every attribute is read via ``getattr`` by the compiler):

    - ``type`` -> the field's output type: a graphql-core ``GraphQLType``, a
      django-graphex output-type CLASS (``DjangoObjectType`` /
      ``DjangoListObjectType``, resolved to its node by the list builders), or a
      ``NativeList`` / ``NativeNonNull`` lazy wrapper. Thunks (str / callable) are
      resolved lazily, byte-equivalent to graphene ``Field.type``.
    - ``args`` -> a ``{name: arg}`` dict. Each value is forwarded to
      ``graphene_arg_to_graphql_argument`` (which accepts a graphql-core type, a
      ``GraphQLArgument``, OR a transitional graphene Argument), so the field's
      own ``__init__`` decides the arg currency.
    - ``name`` -> an explicit wire name or ``None`` (compiler camelCases).
    - ``description`` -> the field description or ``None``.
    - ``resolver`` -> the field-level resolver or ``None``.
    - ``wrap_resolve(parent_resolver)`` -> ``self.resolver or parent_resolver``
      (byte-equivalent to graphene ``Field.wrap_resolve``).

    Ordering: ``creation_counter`` (a process-global monotonic int) lets
    ``_yank_fields`` sort mounted descriptors into declaration order for SDL
    parity, exactly as graphene's ``OrderedType`` did.

    Graphene import policy: ZERO top-level ``import graphene``; the only graphene
    touch is the transitional shared-counter read in ``_next_creation_counter``
    (wrapped so it degrades to a local counter once graphene is uninstalled).
    """

    def __init__(
        self,
        type_: Any,
        args: Optional[dict[str, Any]] = None,
        resolver: Optional[Callable[..., Any]] = None,
        *,
        name: Optional[str] = None,
        description: Optional[str] = None,
        required: bool = False,
        source: Optional[str] = None,
        _creation_counter: Optional[int] = None,
        **extra_args: Any,
    ) -> None:
        """Build a native field descriptor (graphene ``Field.__init__`` parity).

        Args:
            type_: The field's output type (graphql-core type, django output-type
                class, ``NativeList`` / ``NativeNonNull`` wrapper, or a thunk).
            args: Optional explicit ``{name: arg}`` argument mapping.
            resolver: Optional field-level resolver (wins in ``wrap_resolve``).
            name: Optional explicit wire name (verbatim; no camelCase pass).
            description: Optional field description.
            required: When ``True``, wrap *type_* in a ``NativeNonNull`` (graphene
                ``Field(required=True)`` parity).
            source: Optional source attribute name. When set (and no explicit
                ``resolver``), the field resolves by reading ``source`` off the
                root (graphene ``Field(source=...)`` parity).
            _creation_counter: Optional explicit counter (preserves order when a
                descriptor is re-mounted / copied).
            **extra_args: Extra ``name=arg`` field arguments, merged into ``args``
                (graphene ``Field`` parity — e.g. ``DjangoObjectField`` passes
                ``id=...``).
        """
        if required:
            type_ = NativeNonNull(type_)
        self._type = type_
        merged_args: dict[str, Any] = dict(args or {})
        merged_args.update(extra_args)
        self.args = merged_args
        if source and resolver is None:
            # graphene parity: a ``source`` becomes a resolver reading it off root.
            resolver = partial(_source_resolver, source)
        self.resolver = resolver
        self.name = name
        self.description = description
        self.creation_counter = (
            _creation_counter
            if _creation_counter is not None
            else _next_creation_counter()
        )

    @classmethod
    def mounted(cls, unmounted: Any) -> "NativeMountedField":
        """Mount a graphene ``UnmountedType`` (transitional converter scalar) AS-IS.

        ``_yank_fields`` (types.py) passes this class as the ``_as`` mount target.
        On native the converter omits dead scalars, so this is reached ONLY on the
        transitional graphene backend, where ``construct_fields`` still emits real
        graphene scalar ``UnmountedType`` instances (e.g. ``String(required=True)``).
        Byte-equivalent to graphene's ``MountedType.mounted``: the scalar's
        ``get_type()`` (its class) becomes the field type, the ``required`` /
        ``description`` / ``name`` kwargs carry over, and the creation counter is
        preserved so ordering is stable. The native compiler then reads ``.type``
        and resolves the graphene scalar via ``_unwrap_graphene_type``. (The mounted
        descriptor is METADATA only — the schema is compiled from
        ``_meta.graphql_output_type`` / ``_meta.graphql_input_type``, not from these.)

        Args:
            unmounted: A graphene ``UnmountedType`` scalar/enum instance.

        Returns:
            A ``NativeMountedField`` wrapping the unmounted type's class.
        """
        kwargs = dict(getattr(unmounted, "kwargs", {}) or {})
        required = bool(kwargs.pop("required", False))
        description = kwargs.pop("description", None)
        name = kwargs.pop("name", None)
        source = kwargs.pop("source", None)
        return cls(
            unmounted.get_type(),
            required=required,
            description=description,
            name=name,
            source=source,
            _creation_counter=getattr(unmounted, "creation_counter", None),
        )

    @property
    def type(self) -> Any:  # noqa: A003 - matches the compiler's read attr
        """Return the field's output type, resolving thunks (graphene parity)."""
        return _resolve_thunk(self._type)

    def wrap_resolve(self, parent_resolver: Any) -> Any:
        """Return ``self.resolver`` when set, else *parent_resolver* (graphene parity)."""
        return self.resolver or parent_resolver

    def wrap_subscribe(self, parent_subscribe: Any) -> Any:
        """Return *parent_subscribe* unchanged (graphene ``Field`` parity)."""
        return parent_subscribe

    # -- ordering (graphene OrderedType parity, for _yank_fields sort) --------
    def __eq__(self, other: Any) -> bool:
        """Equality by ``creation_counter`` among ordered descriptors."""
        if isinstance(other, NativeMountedField):
            return self.creation_counter == other.creation_counter
        return NotImplemented

    def __lt__(self, other: Any) -> bool:
        """Order by ``creation_counter`` (declaration order)."""
        if hasattr(other, "creation_counter"):
            return self.creation_counter < other.creation_counter
        return NotImplemented

    def __hash__(self) -> int:
        """Hash by ``creation_counter`` (graphene ``OrderedType`` parity)."""
        return hash(self.creation_counter)


class NativeRelationField(NativeMountedField):
    """Graphene-free PRESENCE/ORDERING marker for a to-ONE relation (S-rel-2).

    Why this exists (import-removal, SDL-neutral)
    ---------------------------------------------
    On the native OUTPUT path the converter historically emitted a graphene
    ``Dynamic`` for every to-ONE relation (ForeignKey / forward OneToOne /
    reverse OneToOne) via ``converter.convert_field_to_djangomodel`` /
    ``convert_onetoone_field_to_djangomodel``. Building that ``Dynamic`` imports
    graphene (``converter._g()``), yet its output is NEVER read on the native
    path: the native output type is compiled ENTIRELY from
    ``model._meta.get_fields()`` —

    - FK / forward-O2O by ``output_compiler._to_graphql_field`` (the to-ONE arm);
    - reverse-O2O by ``types._compile_reverse_o2o_fields``.

    So the ``Dynamic`` is built-then-DISCARDED (dead weight that nonetheless
    pins graphene). The ONLY thing the relation descriptor in ``_meta.fields``
    is used for on the native path is PRESENCE + ORDERING: ``_yank_fields``
    keeps it (so ``"spouse" in Type._meta.fields`` holds — the issue #52
    self-ref-O2O canary) and sorts ``_meta.fields`` by ``creation_counter``.

    ``NativeRelationField`` replaces the graphene ``Dynamic`` on the native
    OUTPUT path with a graphene-free marker that:

    - subclasses :class:`NativeMountedField`, so ``_yank_fields`` recognizes it
      in its FIRST branch (``isinstance(value, (NativeMountedField, NativeField))``)
      and keeps it AS-IS — NO ``_yank_fields`` change, and NEVER the silent-drop
      ``continue`` (the test_issue52 trap);
    - carries the SAME ``creation_counter`` graphene's ``Dynamic`` would have
      received (sourced from :func:`_next_creation_counter`, the shared global
      counter), so ``_meta.fields`` ordering — and therefore SDL field order —
      is byte-identical to the graphene-descriptor era;
    - exposes an INERT ``.type`` (it is never read on the native output path;
      the field is a presence/ordering marker only).

    The INPUT path is unchanged (it stays on graphene until S-input-5): this
    marker is OUTPUT-only.
    """

    __slots__ = ("related_model",)

    def __init__(
        self,
        related_model: Any = None,
        *,
        _creation_counter: Optional[int] = None,
    ) -> None:
        """Build a to-ONE relation presence/ordering marker.

        Args:
            related_model: The Django model the relation targets (metadata only;
                the native compiler resolves the related type from
                ``model._meta`` independently — this is never read to build the
                field).
            _creation_counter: The graphene-parity creation counter to carry so
                ``_meta.fields`` ordering matches the legacy ``Dynamic`` order.
                When ``None`` a fresh counter is allocated (graphene-shared in
                the transitional window).
        """
        super().__init__(
            type_=None,
            _creation_counter=_creation_counter,
        )
        self.related_model = related_model

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        """Return a short debug representation of the relation marker."""
        return (
            f"<NativeRelationField related_model={self.related_model!r} "
            f"counter={self.creation_counter}>"
        )


class NativeList:
    """Graphene-free, LAZY ``[T]`` wrapper for a deferred-compile element type.

    Why this exists (S-ROOTS-c): graphql-core's ``GraphQLList.__init__`` raises
    ``TypeError`` unless ``of_type`` is already a ``GraphQLType``. A native plain
    ``ObjectType`` class (e.g. ``ErrorType``) has NO compiled graphql-core type
    until ``schema_compiler._compile_plain_object_type`` runs at schema-build, so
    ``field(GraphQLList(ErrorType))`` is impossible to construct eagerly. graphql-core
    wrappers also reject a thunk for ``of_type``.

    ``NativeList`` is the lazy answer: it is an INERT carrier of the element type
    (a graphql-core type, OR a deferred django-graphex / native ObjectType class)
    and exposes the SAME ``.of_type`` read attribute graphene ``List`` /
    graphql-core ``GraphQLList`` expose. The compiler's ``_compile_wrapped_field_type``
    recurses through ``.of_type`` and compiles the inner element to the right
    graphql-core type, preserving the list wrapper shape. This is how
    ``errors = field(NativeList(ErrorType))`` compiles to ``[ErrorType]`` —
    byte-identical to the graphene ``errors = List(ErrorType)`` original.

    No ``import graphene``, no eager ``GraphQLList`` construction — the wrapper
    stays valid under both backends and after graphene is uninstalled (S8).
    """

    __slots__ = ("of_type",)

    def __init__(self, of_type: Any) -> None:
        """Carry the (possibly deferred) element type; never builds eagerly.

        Args:
            of_type: The list element — a graphql-core ``GraphQLType``, OR a
                django-graphex / native ``ObjectType`` class resolved lazily by
                the compiler at schema-build time.
        """
        self.of_type = of_type

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        """Return a short debug representation of the lazy list wrapper."""
        return f"<NativeList of_type={self.of_type!r}>"


class NativeNonNull:
    """Graphene-free, LAZY ``T!`` wrapper for a deferred-compile element type.

    The non-null sibling of :class:`NativeList` (same rationale): graphql-core's
    ``GraphQLNonNull`` cannot wrap an uncompiled class, so the non-null shape over
    a deferred native/django output type is expressed lazily here and resolved by
    ``_compile_wrapped_field_type`` (which recurses through ``.of_type`` preserving
    the non-null wrapper). Exposes the same ``.of_type`` read attribute as
    graphene ``NonNull`` / graphql-core ``GraphQLNonNull``.
    """

    __slots__ = ("of_type",)

    def __init__(self, of_type: Any) -> None:
        """Carry the (possibly deferred) wrapped type; never builds eagerly.

        Args:
            of_type: The wrapped type — a graphql-core ``GraphQLType``, OR a
                django-graphex / native ``ObjectType`` class resolved lazily by
                the compiler at schema-build time. May itself be a
                :class:`NativeList` to express ``[T]!`` / ``[T!]!`` shapes.
        """
        self.of_type = of_type

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        """Return a short debug representation of the lazy non-null wrapper."""
        return f"<NativeNonNull of_type={self.of_type!r}>"


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
