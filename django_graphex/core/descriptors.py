"""Native field-descriptor currency for the duck-typed compiler (S-ROOTS-a).

The native schema compiler consumes DECLARED / ROOT fields purely by DUCK
TYPING — it reads "field.type" / "field.args" / "field.name" /
"field.description" and calls "field.wrap_resolve(parent_resolver)" with NO
"isinstance(graphene.Field)" guard (see "schema_compiler.compile_declared_field"
:369 and "schema_compiler.compile_native_root" :719). Historically the only
things that exposed that shape were graphene "Field" / "UnmountedType"
instances.

"NativeField" is the graphene-free replacement for that currency. It exposes
the EXACT read-contract the compiler relies on, so a "field(...)"-declared
field drops straight into the existing dispatch and compiles to the right
graphql-core field — never silently vanishing (the paramount S-ROOTS risk).

The public "field()" helper (decision #1554) is the single idiom users write
to declare a custom (non-model) field on a root / "ObjectType":

    from django_graphex.core import ObjectType, field
    from graphql import GraphQLString, GraphQLList, GraphQLNonNull

    class Query(ObjectType):
        server_time = field(GraphQLString, description="ISO timestamp")
        me = field(UserType)                         # a DjangoObjectType ref
        tags = field(GraphQLList(GraphQLString))     # list via graphql-core wrapper
        name = field(GraphQLNonNull(GraphQLString))  # non-null via wrapper

        def resolve_server_time(self, info): ...

Type expression (decision #1554):
- A graphql-core type ("GraphQLScalarType" / "GraphQLObjectType" /
  "GraphQLEnumType" / "GraphQLInputObjectType") is used VERBATIM.
- "GraphQLList" / "GraphQLNonNull" express list / non-null — there is ONE
  idiom (the graphql-core wrappers), no parallel graphene-clone surface.
- A django-graphex output type CLASS ("DjangoObjectType" /
  "DjangoListObjectType", or anything carrying
  "_meta.graphql_output_type") is accepted and resolved LAZILY to its
  compiled graphql-core type when ".type" is read by the compiler — so the
  field can reference an output type declared after the descriptor.

Graphene import policy:
- This module is the NATIVE currency. It has ZERO top-level "import graphene"
  (and zero lazy one) so it imports cleanly under both backends and after
  graphene is uninstalled (S8).
"""

from __future__ import annotations

import inspect
from functools import partial, total_ordering
from typing import Any, Callable, Optional

# Sentinel distinguishing an EXPLICIT ``default=None`` (a GraphQL null default)
# from "no default supplied" on an ``InputField``. ``None`` is a legitimate
# GraphQL default value, so it cannot double as the "unset" marker.
_UNSET: Any = object()

# ---------------------------------------------------------------------------
# Graphene-free ordering counter (graphene OrderedType replica)
# ---------------------------------------------------------------------------
# ``_yank_fields`` (types.py) sorts the mounted descriptors by their
# ``creation_counter`` so the SDL field order matches declaration order — exactly
# what graphene's ``OrderedType`` provided. ``NativeMountedField`` carries one so
# a field declared off graphene keeps stable, declaration-ordered output. The
# counter is a process-global, monotonically-increasing integer.
#
# S-del-backend-11: the graphene backend is deleted, so the transitional shared-
# counter sync with graphene's ``OrderedType`` (consulted via ``sys.modules`` when
# a graphene-ROOT schema was built in the same process) is GONE. ``_yank_fields``
# only keeps native descriptors (``NativeMountedField`` / ``NativeField``), so
# there is no mixed native+graphene order space to share — the local counter is
# the only path.
_LOCAL_COUNTER = [0]


def _next_creation_counter() -> int:
    """Return the next monotonic creation counter (graphene-free).

    Mirrors "graphene.utils.orderedtype.OrderedType.gen_counter": a single
    process-global, monotonically-increasing integer that lets "_yank_fields"
    sort "_meta.fields" by declaration order for SDL parity. The native path
    NEVER imports graphene to obtain this counter: a "field()" / "Django*Field"
    declared at RUNTIME must not drag in graphene. "_yank_fields" only keeps
    native descriptors ("NativeMountedField" / "NativeField"), so a local
    counter is sufficient.

    Returns:
        counter: The next monotonic process-global creation counter.
    """
    _LOCAL_COUNTER[0] += 1
    return _LOCAL_COUNTER[0]


def _source_resolver(source: str, root: Any, info: Any, **args: Any) -> Any:
    """Graphene-free replica of "graphene.types.field.source_resolver".

    A 'field(..., source="attr")' declaration resolves by reading "attr" off
    the root (dict-key for a mapping, attribute otherwise), then CALLING the
    result when it is a function / method (graphene parity — lets a source point
    at a zero-arg method). Used by "NativeMountedField" to honor the graphene
    "source=" kwarg (e.g. 'graphene.String(source="name")' declared on a
    "DjangoModelType") without importing graphene.

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
    """Graphene-free replica of "graphene.types.utils.get_type".

    Resolves a deferred field/arg type expression to the concrete value the
    compiler reads:

    - a dotted import-path string -> the imported object;
    - a zero-arg function / "functools.partial" -> its return value (a lazy
      forward reference, e.g. "lambda: SomeType");
    - anything else (a class, a graphql-core type, a native wrapper) -> verbatim.

    Byte-equivalent to graphene's "get_type" so a "NativeMountedField" resolves
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
    """Graphene-free field-descriptor base for the "Django*Field" classes (S8c).

    The native schema compiler consumes a DECLARED / ROOT field purely by DUCK
    TYPING — it reads "field.type" / "field.args" / "field.name" /
    "field.description" / "field.resolver" and calls
    "field.wrap_resolve(parent_resolver)" with NO "isinstance(graphene.Field)"
    guard (the same contract "NativeField" documents). The
    "django_graphex.fields" field classes ("DjangoObjectField" /
    "DjangoListObjectField" / "DjangoFilterListField" /
    "DjangoFilterPaginateListField" / "DjangoNestedListObjectField" /
    "AnnotatedField") historically subclassed graphene "Field" to get that
    shape; S8c re-parents them onto THIS base so they expose the same contract
    with ZERO graphene dependency.

    Read-contract (every attribute is read via "getattr" by the compiler):

    - "type" -> the field's output type: a graphql-core "GraphQLType", a
      django-graphex output-type CLASS ("DjangoObjectType" /
      "DjangoListObjectType", resolved to its node by the list builders), or a
      "NativeList" / "NativeNonNull" lazy wrapper. Thunks (str / callable) are
      resolved lazily, byte-equivalent to graphene "Field.type".
    - "args" -> a "{name: arg}" dict. Each value is forwarded to
      "to_graphql_argument" (which accepts a graphql-core type, a
      "GraphQLArgument", OR a transitional graphene Argument), so the field's
      own "__init__" decides the arg currency.
    - "name" -> an explicit wire name or "None" (compiler camelCases).
    - "description" -> the field description or "None".
    - "resolver" -> the field-level resolver or "None".
    - "wrap_resolve(parent_resolver)" -> "self.resolver or parent_resolver"
      (byte-equivalent to graphene "Field.wrap_resolve").

    Ordering: "creation_counter" (a process-global monotonic int) lets
    "_yank_fields" sort mounted descriptors into declaration order for SDL
    parity, exactly as graphene's "OrderedType" did.

    Graphene import policy: ZERO top-level "import graphene"; the only graphene
    touch is the transitional shared-counter read in "_next_creation_counter"
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
        deprecation_reason: Optional[str] = None,
        _creation_counter: Optional[int] = None,
        **extra_args: Any,
    ) -> None:
        """Build a native field descriptor (graphene "Field.__init__" parity).

        Args:
            type_: The field's output type (graphql-core type, django output-type
                class, "NativeList" / "NativeNonNull" wrapper, or a thunk).
            args: Optional explicit "{name: arg}" argument mapping.
            resolver: Optional field-level resolver (wins in "wrap_resolve").
            name: Optional explicit wire name (verbatim; no camelCase pass).
            description: Optional field description.
            required: When True, wrap "type_" in a "NativeNonNull" (graphene
                "Field(required=True)" parity).
            source: Optional source attribute name. When set (and no explicit
                "resolver"), the field resolves by reading "source" off the
                root (graphene "Field(source=...)" parity).
            deprecation_reason: Optional deprecation reason. Read by the native
                schema compiler's root choke point and stamped onto the compiled
                "GraphQLField" so the SDL renders "@deprecated(reason: ...)".
                Declared as an EXPLICIT parameter (not swallowed into
                "**extra_args") so it never leaks into "self.args" — where it
                would crash arg conversion with a misleading "Cannot convert
                ... to a graphql-core type" "TypeError". Honored uniformly by
                every "NativeMountedField" subclass ("DjangoObjectField" /
                the list / filter field builders).
            _creation_counter: Optional explicit counter (preserves order when a
                descriptor is re-mounted / copied).
            **extra_args: Extra "name=arg" field arguments, merged into "args"
                (graphene "Field" parity — e.g. "DjangoObjectField" passes
                "id=...").
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
        # Stored on a private backing attr (exposed via the ``deprecation_reason``
        # property below) so a subclass — the unified :class:`Field` — that also
        # declares a read-only ``deprecation_reason`` property does NOT trip the
        # "property has no setter" ``AttributeError`` when the base ``__init__``
        # runs. Both read from the SAME ``_deprecation_reason`` backing attr.
        self._deprecation_reason = deprecation_reason
        self.creation_counter = (
            _creation_counter
            if _creation_counter is not None
            else _next_creation_counter()
        )

    @property
    def deprecation_reason(self) -> Optional[str]:
        """Return the field's deprecation reason (compiler reads via "getattr").

        The native schema compiler's root choke point stamps this onto the compiled
        "GraphQLField" (SDL "@deprecated(reason: ...)"). "None" leaves the
        field non-deprecated.

        Returns:
            reason: The deprecation reason, or None when the field is not
                deprecated.
        """
        return self._deprecation_reason

    @classmethod
    def mounted(cls, unmounted: Any) -> "NativeMountedField":
        """Mount a graphene "UnmountedType" (transitional converter scalar) AS-IS.

        "_yank_fields" (types.py) passes this class as the "_as" mount target.
        On native the converter omits dead scalars, so this is reached ONLY on the
        transitional graphene backend, where "construct_fields" still emits real
        graphene scalar "UnmountedType" instances (e.g. "String(required=True)").
        Byte-equivalent to graphene's "MountedType.mounted": the scalar's
        "get_type()" (its class) becomes the field type, the "required" /
        "description" / "name" kwargs carry over, and the creation counter is
        preserved so ordering is stable. The native compiler then reads ".type"
        and resolves the graphene scalar via "_unwrap_graphql_type". (The mounted
        descriptor is METADATA only — the schema is compiled from
        "_meta.graphql_output_type" / "_meta.graphql_input_type", not from these.)

        Args:
            unmounted: A graphene "UnmountedType" scalar/enum instance.

        Returns:
            mounted: A "NativeMountedField" wrapping the unmounted type's class.
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
        """Return the field's output type, resolving thunks (graphene parity).

        Returns:
            output_type: The resolved output type — a graphql-core type, an
                output-type class, or a lazy wrapper — with str / callable
                thunks resolved.
        """
        return _resolve_thunk(self._type)

    def wrap_resolve(self, parent_resolver: Any) -> Any:
        """Return the field's own resolver when set, else the parent (graphene parity).

        Args:
            parent_resolver: The fallback resolver the compiler supplies.

        Returns:
            resolver: "self.resolver" when set, else "parent_resolver".
        """
        return self.resolver or parent_resolver

    def wrap_subscribe(self, parent_subscribe: Any) -> Any:
        """Return the parent subscribe callable unchanged (graphene "Field" parity).

        Args:
            parent_subscribe: The subscribe callable the compiler supplies.

        Returns:
            subscribe: The "parent_subscribe" argument, unchanged.
        """
        return parent_subscribe

    # -- ordering (graphene OrderedType parity, for _yank_fields sort) --------
    def __eq__(self, other: Any) -> bool:
        """Equality by "creation_counter" among ordered descriptors."""
        if isinstance(other, NativeMountedField):
            return self.creation_counter == other.creation_counter
        return NotImplemented

    def __lt__(self, other: Any) -> bool:
        """Order by "creation_counter" (declaration order)."""
        if hasattr(other, "creation_counter"):
            return self.creation_counter < other.creation_counter
        return NotImplemented

    def __hash__(self) -> int:
        """Hash by "creation_counter" (graphene "OrderedType" parity)."""
        return hash(self.creation_counter)


class NativeRelationField(NativeMountedField):
    """Graphene-free PRESENCE/ORDERING marker for a to-ONE relation (S-rel-2).

    Why this exists (import-removal, SDL-neutral)
    ---------------------------------------------
    On the native OUTPUT path the converter historically emitted a graphene
    "Dynamic" for every to-ONE relation (ForeignKey / forward OneToOne /
    reverse OneToOne) via "converter.convert_field_to_djangomodel" /
    "convert_onetoone_field_to_djangomodel". Building that "Dynamic" imports
    graphene ("converter._g()"), yet its output is NEVER read on the native
    path: the native output type is compiled ENTIRELY from
    "model._meta.get_fields()" —

    - FK / forward-O2O by "output_compiler._to_graphql_field" (the to-ONE arm);
    - reverse-O2O by "types._compile_reverse_o2o_fields".

    So the "Dynamic" is built-then-DISCARDED (dead weight that nonetheless
    pins graphene). The ONLY thing the relation descriptor in "_meta.fields"
    is used for on the native path is PRESENCE + ORDERING: "_yank_fields"
    keeps it (so '"spouse" in Type._meta.fields' holds — the issue #52
    self-ref-O2O canary) and sorts "_meta.fields" by "creation_counter".

    "NativeRelationField" replaces the graphene "Dynamic" on the native
    OUTPUT path with a graphene-free marker that:

    - subclasses "NativeMountedField", so "_yank_fields" recognizes it
      in its FIRST branch ("isinstance(value, (NativeMountedField, NativeField))")
      and keeps it AS-IS — NO "_yank_fields" change, and NEVER the silent-drop
      "continue" (the test_issue52 trap);
    - carries the SAME "creation_counter" graphene's "Dynamic" would have
      received (sourced from "_next_creation_counter", the shared global
      counter), so "_meta.fields" ordering — and therefore SDL field order —
      is byte-identical to the graphene-descriptor era;
    - exposes an INERT ".type" (it is never read on the native output path;
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
                "model._meta" independently — this is never read to build the
                field).
            _creation_counter: The graphene-parity creation counter to carry so
                "_meta.fields" ordering matches the legacy "Dynamic" order.
                When None a fresh counter is allocated (graphene-shared in
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
    """Graphene-free, LAZY "[T]" wrapper for a deferred-compile element type.

    Why this exists (S-ROOTS-c): graphql-core's "GraphQLList.__init__" raises
    "TypeError" unless "of_type" is already a "GraphQLType". A native plain
    "ObjectType" class (e.g. "ErrorType") has NO compiled graphql-core type
    until "schema_compiler._compile_plain_object_type" runs at schema-build, so
    "field(GraphQLList(ErrorType))" is impossible to construct eagerly. graphql-core
    wrappers also reject a thunk for "of_type".

    "NativeList" is the lazy answer: it is an INERT carrier of the element type
    (a graphql-core type, OR a deferred django-graphex / native ObjectType class)
    and exposes the SAME ".of_type" read attribute graphene "List" /
    graphql-core "GraphQLList" expose. The compiler's "_compile_wrapped_field_type"
    recurses through ".of_type" and compiles the inner element to the right
    graphql-core type, preserving the list wrapper shape. This is how
    "errors = field(NativeList(ErrorType))" compiles to "[ErrorType]" —
    byte-identical to the graphene "errors = List(ErrorType)" original.

    No "import graphene", no eager "GraphQLList" construction — the wrapper
    stays valid under both backends and after graphene is uninstalled (S8).
    """

    __slots__ = ("of_type",)

    def __init__(self, of_type: Any) -> None:
        """Carry the (possibly deferred) element type; never builds eagerly.

        Args:
            of_type: The list element — a graphql-core "GraphQLType", OR a
                django-graphex / native "ObjectType" class resolved lazily by
                the compiler at schema-build time.
        """
        self.of_type = of_type

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        """Return a short debug representation of the lazy list wrapper."""
        return f"<NativeList of_type={self.of_type!r}>"


class NativeNonNull:
    """Graphene-free, LAZY "T!" wrapper for a deferred-compile element type.

    The non-null sibling of "NativeList" (same rationale): graphql-core's
    "GraphQLNonNull" cannot wrap an uncompiled class, so the non-null shape over
    a deferred native/django output type is expressed lazily here and resolved by
    "_compile_wrapped_field_type" (which recurses through ".of_type" preserving
    the non-null wrapper). Exposes the same ".of_type" read attribute as
    graphene "NonNull" / graphql-core "GraphQLNonNull".
    """

    __slots__ = ("of_type",)

    def __init__(self, of_type: Any) -> None:
        """Carry the (possibly deferred) wrapped type; never builds eagerly.

        Args:
            of_type: The wrapped type — a graphql-core "GraphQLType", OR a
                django-graphex / native "ObjectType" class resolved lazily by
                the compiler at schema-build time. May itself be a
                "NativeList" to express "[T]!" / "[T!]!" shapes.
        """
        self.of_type = of_type

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        """Return a short debug representation of the lazy non-null wrapper."""
        return f"<NativeNonNull of_type={self.of_type!r}>"


def _resolve_field_type(declared_type: Any) -> Any:
    """Resolve a declared "field()" type to the graphql-core type the compiler reads.

    Resolution order:
    1. A django-graphex output type class carrying a compiled
       "_meta.graphql_output_type" ("DjangoObjectType" /
       "DjangoListObjectType") -> that canonical graphql-core type. This is
       evaluated LAZILY (on every ".type" read) so a forward reference to a
       type compiled later ("compile_all_outputs()" runs before root
       compilation) resolves to the real instance, not None.
    2. Anything else (a graphql-core "GraphQLType": scalar / object / enum /
       input / "GraphQLList" / "GraphQLNonNull" wrapper, OR a graphene type
       left as a transitional fallback) -> returned VERBATIM. The compiler's
       "_unwrap_graphql_type" / "_is_plain_object_type" /
       "_plain_django_output_type" dispatch already handles each of those
       shapes, so the descriptor stays a thin pass-through.

    Args:
        declared_type: The "type" argument passed to "field()" / "NativeField".

    Returns:
        resolved: The graphql-core type (or a class the compiler can dispatch)
            the field should expose as ".type".
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
    (all via "getattr" — no "isinstance" guard):

    - "type" -> the field's graphql-core output type (resolved lazily for a
      django-graphex output-type class reference).
    - "args" -> a "{name: GraphQLArgument}" dict, or None.
    - "name" -> an explicit wire name ("field(name=...)") or None
      (the compiler camelCases the attribute name when None).
    - "description" -> the field description, or None.
    - "wrap_resolve(parent_resolver)" -> the final resolver. Mirrors graphene
      "Field.wrap_resolve": the field's own "resolver" wins, else the
      "parent_resolver" the compiler supplies (the source class'
      "resolve_<name>" or graphql-core's default attribute/dict resolver).
    """

    __slots__ = (
        "_declared_type",
        "_args",
        "_name",
        "_description",
        "_resolver",
        "_required_perms",
        "_deprecation_reason",
    )

    def __init__(
        self,
        type: Any,  # noqa: A002 - mirrors the public field() positional name
        *,
        description: Optional[str] = None,
        args: Optional[dict[str, Any]] = None,
        resolver: Optional[Callable[..., Any]] = None,
        name: Optional[str] = None,
        required_perms: Optional[Any] = None,
        deprecation_reason: Optional[str] = None,
    ) -> None:
        """Build a native field descriptor.

        Args:
            type: The field's graphql-core type, OR a django-graphex output type
                class (resolved lazily to its compiled graphql-core type).
                List / non-null are expressed with graphql-core "GraphQLList" /
                "GraphQLNonNull" wrappers.
            description: Optional field description.
            args: Optional "{name: GraphQLArgument}" argument dict.
            resolver: Optional field-level resolver. When set it WINS in
                "wrap_resolve" over the compiler-supplied parent resolver
                (graphene parity).
            name: Optional explicit wire name. When set the compiler uses it
                verbatim (no camelCase pass); when None the compiler
                camelCases the declared attribute name.
            required_perms: Optional opt-in permission override (P0). A sequence
                of Django codenames a caller must hold to see this field. When
                set, the compiler stamps it onto the built field's
                'extensions["gdx_required_perms"]' (an untagged field is
                treated as public).
            deprecation_reason: Optional deprecation reason wired into the compiled
                "GraphQLField" so the SDL renders "@deprecated(reason: ...)".
        """
        self._declared_type = type
        self._args = args
        self._name = name
        self._description = description
        self._resolver = resolver
        self._required_perms = required_perms
        self._deprecation_reason = deprecation_reason

    @property
    def type(self) -> Any:  # noqa: A003 - matches the compiler's read attr
        """Return the field's graphql-core type (django output refs resolved lazily).

        Returns:
            output_type: The resolved graphql-core output type; a django-graphex
                output-type class reference is resolved to its compiled type.
        """
        return _resolve_field_type(self._declared_type)

    @property
    def args(self) -> Optional[dict[str, Any]]:
        """Return the argument mapping the compiler reads.

        Returns:
            args: The "{name: GraphQLArgument}" arg dict, or None when the field
                declares no arguments.
        """
        return self._args

    @property
    def name(self) -> Optional[str]:
        """Return the explicit wire name.

        Returns:
            name: The explicit wire name, or None (the compiler camelCases the
                attribute name).
        """
        return self._name

    @property
    def description(self) -> Optional[str]:
        """Return the field description.

        Returns:
            description: The field description, or None when unset.
        """
        return self._description

    @property
    def resolver(self) -> Optional[Callable[..., Any]]:
        """Return the field-level resolver.

        Returns:
            resolver: The field-level resolver, or None when unset.
        """
        return self._resolver

    @property
    def required_perms(self) -> Optional[Any]:
        """Return the opt-in permission override (P0).

        Returns:
            required_perms: The permission override, or None (the field is
                public).
        """
        return self._required_perms

    @property
    def deprecation_reason(self) -> Optional[str]:
        """Return the deprecation reason (compiler reads via getattr).

        Returns:
            reason: The deprecation reason, or None when the field is not
                deprecated.
        """
        return self._deprecation_reason

    def wrap_resolve(self, parent_resolver: Any) -> Any:
        """Return the final resolver (own resolver wins, else the parent).

        Byte-equivalent to graphene "Field.wrap_resolve" (which is simply
        "return self.resolver or parent_resolver"), so the compiler's
        "field.wrap_resolve(...)" call at schema_compiler.py:404-432 works
        unchanged against a "NativeField".

        Args:
            parent_resolver: The fallback resolver the compiler supplies (the
                source class' "resolve_<name>" or graphql-core's default).

        Returns:
            resolver: "self.resolver" when set, else "parent_resolver".
        """
        return self._resolver or parent_resolver

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        """Return a short debug representation of the descriptor."""
        return f"<NativeField type={self._declared_type!r} name={self._name!r}>"


def field(
    type: Any,  # noqa: A002 - public positional API (decision #1554)
    *,
    description: Optional[str] = None,
    args: Optional[dict[str, Any]] = None,
    resolver: Optional[Callable[..., Any]] = None,
    name: Optional[str] = None,
    required_perms: Optional[Any] = None,
    deprecation_reason: Optional[str] = None,
) -> NativeField:
    """Declare a custom (non-model) field on a root / "ObjectType".

    The single graphene-free idiom (decision #1554) for hand-declared fields:

        server_time = field(GraphQLString, description="ISO timestamp")
        me = field(UserType)
        tags = field(GraphQLList(GraphQLString))

    Args:
        type: A graphql-core type used verbatim ("GraphQLScalarType" /
            "GraphQLObjectType" / "GraphQLEnumType" /
            "GraphQLInputObjectType" / "GraphQLList" / "GraphQLNonNull"),
            OR a django-graphex output type class ("DjangoObjectType" /
            "DjangoListObjectType") resolved lazily to its compiled
            graphql-core type. List / non-null are expressed with the
            graphql-core wrappers.
        description: Optional field description.
        args: Optional "{name: GraphQLArgument}" argument dict.
        resolver: Optional field-level resolver (wins over the parent resolver).
        name: Optional explicit wire name (verbatim; no camelCase pass).
        required_perms: Optional opt-in permission override (P0). A sequence of
            Django codenames a caller must hold to see this field; stamped onto
            the built field's 'extensions["gdx_required_perms"]'. Omit (the
            default) to leave the field PUBLIC.
        deprecation_reason: Optional deprecation reason wired into the compiled
            "GraphQLField" so the SDL renders "@deprecated(reason: ...)".

    Returns:
        native_field: A "NativeField" the native compiler consumes directly.
    """
    return NativeField(
        type,
        description=description,
        args=args,
        resolver=resolver,
        name=name,
        required_perms=required_perms,
        deprecation_reason=deprecation_reason,
    )


# ---------------------------------------------------------------------------
# Django-style capitalized field descriptors (field-descriptor-api)
# ---------------------------------------------------------------------------
# Additive sugar over the native substrate. Every descriptor compiles to the
# SAME graphql-core output as ``field()`` / ``GraphQLArgument``, so SDL is
# byte-identical and the compiler read-contract is untouched.


class Field(NativeMountedField):
    """Django-style capitalized field descriptor — usable in BOTH positions.

    ONE descriptor, Strawberry-style: the same "Field" is declared in an OUTPUT
    position (an "ObjectType" / "Mutation" payload body) AND in an INPUT
    position (a "class Arguments" body or a "field(args={...})" /
    "Field(args={...})" dict). Direction is NEVER declared on the descriptor — it
    comes entirely from the DECLARATION SITE, which reads the descriptor through
    the matching contract:

    - OUTPUT: the compiler duck-reads ".type" (lazy "_meta.graphql_output_type"
      for a django-graphex output-type class), ".args", ".description",
      ".deprecation_reason", and calls ".wrap_resolve(parent)". "required="
      wraps a lazy "NativeNonNull" at ".type" read. "source=" becomes a
      root-reading resolver.
    - INPUT: the arg builders ("native_arg" / "to_graphql_argument" in
      "core/_args") call "to_graphql_argument", which resolves the INPUT
      type ("_meta.graphql_input_type" for an "InputType" class, else a bare
      graphql-core scalar verbatim) with an EAGER "GraphQLNonNull" when
      "required", and carries "default=" / "description" /
      "deprecation_reason".

    C1 — the ".type" collision. The OUTPUT ".type" property (inherited from
    "NativeMountedField") eagerly wraps "NativeNonNull" and resolves the
    OUTPUT type; the INPUT route must NEVER read it. "to_graphql_argument"
    therefore resolves from the RAW pre-wrap type stashed in "_raw_type" and
    builds a REAL graphql-core "GraphQLNonNull" itself — the two directions share
    no wrapping code.

    Contextual validation. Wrong-position parameters fail LOUD rather than silently
    doing nothing:

    - INPUT-only "default=" on an OUTPUT-position field is caught at output
      compile/mount ("schema_compiler.compile_declared_field"), not here — the
      descriptor cannot know its position at construction.
    - OUTPUT-only "resolver=" / "source=" / "args=" set on a field used in an
      INPUT position raise a clear "TypeError" from "to_graphql_argument".

    Usage:

        from django_graphex.core import Field
        from graphql import GraphQLString, GraphQLInt

        class Query(ObjectType):
            title = Field(GraphQLString, description="a title")
            email = Field(GraphQLString, source="user_email")   # reads root.user_email
            count = Field(GraphQLInt, required=True)             # -> Int!

        class Arguments:
            data = Field(SearchInput, required=True)             # -> SearchInput!
            limit = Field(GraphQLInt, default=10)                # default 10
    """

    def __init__(
        self,
        type: Any,  # noqa: A002 - public positional API, mirrors field()
        *,
        source: Optional[str] = None,
        required: bool = False,
        default: Any = _UNSET,
        description: Optional[str] = None,
        name: Optional[str] = None,
        resolver: Optional[Callable[..., Any]] = None,
        args: Optional[dict[str, Any]] = None,
        deprecation_reason: Optional[str] = None,
    ) -> None:
        """Build a unified field descriptor.

        Args:
            type: The field's type. In an OUTPUT position: a graphql-core
                "GraphQLType", a django-graphex output-type class (resolved
                lazily), or a "NativeList" / "NativeNonNull" wrapper. In an
                INPUT position: an "InputType" / "DjangoInputObjectType" class
                (resolved lazily to "_meta.graphql_input_type") or a bare
                graphql-core scalar used verbatim.
            source: OUTPUT-only. Source attribute name; when set (and no explicit
                "resolver") the field resolves by reading it off the root.
            required: When True, wrap "type" in a non-null ("T!") — a lazy
                "NativeNonNull" at ".type" read on OUTPUT, an eager
                "GraphQLNonNull" in "to_graphql_argument" on INPUT.
            default: INPUT-only. The GraphQL default value. Defaults to the private
                "_UNSET" sentinel so an explicit "default=None" (a null default)
                stays distinguishable from 'no default supplied'. Set in an OUTPUT
                position, it raises a "TypeError" at output compile/mount.
            description: Optional field / argument description.
            name: Optional explicit wire name (verbatim; no camelCase pass on
                OUTPUT; drives "out_name" on INPUT).
            resolver: OUTPUT-only. Field-level resolver (wins in "wrap_resolve").
            args: OUTPUT-only. Explicit "{name: arg}" argument mapping.
            deprecation_reason: Optional deprecation reason. Wired into the compiled
                "GraphQLField" (SDL "@deprecated") on OUTPUT and into the
                "GraphQLArgument" on INPUT.
        """
        # Stash the RAW, pre-wrap type BEFORE ``NativeMountedField`` eagerly wraps a
        # ``required=True`` output type in ``NativeNonNull`` (C1): the INPUT route
        # must resolve from this raw type via ``_meta.graphql_input_type`` and build
        # its own eager ``GraphQLNonNull``, never reading the OUTPUT ``.type``.
        self._raw_type = type
        self._required = required
        self._default = default
        # ``NativeMountedField`` folds ``source=`` into ``resolver`` (a root-reader),
        # so the raw source flag is stashed separately to give a precise INPUT-side
        # error that names ``source`` instead of the derived ``resolver``.
        self._source = source
        # ``deprecation_reason`` is forwarded to the base ``__init__`` (which stores
        # it on ``self._deprecation_reason`` and exposes the inherited
        # ``deprecation_reason`` property) — a single storage point shared with every
        # other ``NativeMountedField`` subclass.
        super().__init__(
            type,
            args=args,
            resolver=resolver,
            name=name,
            description=description,
            required=required,
            source=source,
            deprecation_reason=deprecation_reason,
        )

    @property
    def default_value(self) -> Any:
        """Return the GraphQL default for the "field(args=...)" route (INPUT position).

        "to_graphql_argument" (the args-dict route) reads this via "getattr".

        Returns:
            default: The declared default value, or graphql-core "Undefined"
                when no "default=" was supplied so the argument renders with NO
                default. An explicit "default=None" stays a real null default —
                the "_UNSET" sentinel keeps them distinct.
        """
        from graphql import Undefined

        return Undefined if self._default is _UNSET else self._default

    def _resolve_input_type(self) -> Any:
        """Resolve the RAW type to its INPUT graphql-core type (C1: never ".type").

        - An input CLASS carrying a compiled "_meta.graphql_input_type" resolves
          to that graphql-core input type (resolved LAZILY, at call time — after
          "compile_all_inputs").
        - A bare graphql-core scalar (no "_meta.graphql_input_type") is returned
          verbatim (the scalar-shortcut / "Field(GraphQLString)" branch).

        Returns:
            input_type: The resolved graphql-core input type.
        """
        meta = getattr(self._raw_type, "_meta", None)
        if meta is not None:
            compiled = getattr(meta, "graphql_input_type", None)
            if compiled is not None:
                return compiled
        return self._raw_type

    def _guard_output_only_params(self) -> None:
        """Raise a clear "TypeError" when an OUTPUT-only param is set on INPUT.

        "resolver=" / "source=" / "args=" have no meaning in an argument
        position; silently ignoring them would mask a declaration mistake. "source"
        is checked FIRST off its raw flag ("NativeMountedField" folds it into
        "resolver", so it would otherwise surface as a misleading "resolver="
        error).

        Raises:
            TypeError: When "source=", "resolver=", or "args=" was set on this
                INPUT-position field.
        """
        if self._source is not None:
            raise TypeError(
                "source= is output-only; it was declared in an argument position. "
                "Remove source= from this Field."
            )
        if self.resolver is not None:
            raise TypeError(
                "resolver= is output-only; it was declared in an argument "
                "position. Remove resolver= from this Field."
            )
        if self.args:
            raise TypeError(
                "args= is output-only; it was declared in an argument position. "
                "Remove args= from this Field."
            )

    def to_graphql_argument(self, name: Optional[str] = None) -> Any:
        """Build the "GraphQLArgument" for the INPUT ("native_arg" / args) route.

        Resolves the INPUT type from "_raw_type" NOW (Field()/compile time, after
        "compile_all_inputs"), wraps it in an EAGER "GraphQLNonNull" when
        "required", and returns a "GraphQLArgument" with the snake_case
        "out_name" plus the declared default / description / deprecation reason.
        Never reads the OUTPUT ".type" property (C1).

        Args:
            name: The declared key (drives "out_name"); falls back to the
                descriptor's own "name".

        Returns:
            argument: A graphql-core "GraphQLArgument".

        Raises:
            TypeError: When an OUTPUT-only param ("resolver" / "source" /
                "args") was set on this INPUT-position field.
        """
        from graphql import GraphQLArgument, GraphQLNonNull, Undefined

        from django_graphex._strconv import to_snake_case

        self._guard_output_only_params()

        gtype = self._resolve_input_type()
        if self._required:
            gtype = GraphQLNonNull(gtype)
        declared = name if name is not None else self.name
        out_name = to_snake_case(declared) if declared is not None else None
        default_value = Undefined if self._default is _UNSET else self._default
        return GraphQLArgument(
            gtype,
            default_value=default_value,
            description=self.description,
            out_name=out_name,
            deprecation_reason=self._deprecation_reason,
        )


# ---------------------------------------------------------------------------
# Typed scalar shortcuts (field-descriptor-api G2)
# ---------------------------------------------------------------------------
# ONE capitalized shortcut per scalar in the inventory below (plus the bespoke
# ``JSONField``), usable in BOTH positions (unification): each routes through the
# unified :class:`Field`, which provides the OUTPUT surface
# (``source=`` / ``required=`` / ``resolver=``) AND the INPUT surface
# (``required=`` / ``default=`` via :meth:`Field.to_graphql_argument`). The
# shortcuts are pure sugar — every one compiles byte-identical to the
# ``Field(scalar, ...)`` equivalent, so SDL and the compiler read-contract are
# untouched. The 12 former ``*InputField`` twins are GONE (2.0 unification): the
# same ``CharField`` works in an ``ObjectType`` body AND a ``class Arguments`` body.
# ``JSONField`` is the ONE non-inventory shortcut: it takes an ``as_str`` flag
# selecting the raw ``JSON`` scalar (default) or the ``JSONString`` escape hatch.
#
# The inventory is the SINGLE source of truth for the shortcuts and the exports:
# ``(shortcut_name, scalar_singleton)``. The ``Gdx*`` custom singletons and the
# graphql-core builtins are imported lazily inside ``_scalar_inventory`` so this
# module keeps ZERO eager graphql import at the descriptor layer (parity with the
# native-currency import policy of the rest of the file).


def _scalar_inventory() -> list[tuple[str, Any]]:
    """Return the "[(shortcut_name, bound_scalar_singleton), ...]" inventory.

    The 10-entry inventory drives the single-scalar (position-agnostic) shortcuts
    and the "__all__" exports; the bespoke "JSONField" ("as_str"-aware) is
    defined separately. Scalars are imported HERE (function-local) so the shortcut
    names are the only module-level additions and the import stays lazy.

    Returns:
        inventory: The "(shortcut_name, scalar_singleton)" pairs the shortcuts
            and exports are built from.
    """
    from graphql import (
        GraphQLBoolean,
        GraphQLFloat,
        GraphQLID,
        GraphQLInt,
        GraphQLString,
    )

    from .scalars import (
        GdxDate,
        GdxDateTime,
        GdxDecimal,
        GdxTime,
        GdxUUID,
    )

    # ``JSONField`` is NOT in this inventory: it is a bespoke shortcut (it takes
    # an ``as_str`` flag that switches between the raw ``JSON`` scalar and the
    # ``JSONString`` escape hatch), built by ``_make_json_shortcut`` below rather
    # than the plain single-scalar ``_make_scalar_shortcut`` factory.
    return [
        ("IntField", GraphQLInt),
        ("CharField", GraphQLString),
        ("FloatField", GraphQLFloat),
        ("BooleanField", GraphQLBoolean),
        ("IDField", GraphQLID),
        ("DateField", GdxDate),
        ("DateTimeField", GdxDateTime),
        ("TimeField", GdxTime),
        ("DecimalField", GdxDecimal),
        ("UUIDField", GdxUUID),
    ]


def _make_scalar_shortcut(
    scalar_singleton: Any,
) -> Callable[..., Field]:
    """Build a position-agnostic scalar-shortcut factory bound to *scalar_singleton*.

    The returned callable exposes the FULL unified "Field" surface — the
    OUTPUT ergonomics ("source=" / "resolver=") AND the INPUT ergonomics
    ("default=") plus the shared "required=" / "description=" / "name=" /
    "deprecation_reason=" — and returns a "Field" over the bound scalar, so
    "CharField(...)" is exactly "Field(GraphQLString, ...)" and works in BOTH an
    "ObjectType" body and a "class Arguments" body. "default" defaults to the
    "_UNSET" sentinel so an explicit "default=None" (a null default) stays
    distinguishable from 'no default'.

    Args:
        scalar_singleton: The graphql-core scalar the shortcut binds.

    Returns:
        factory: A "(*, source, required, default, description, name, resolver,
            deprecation_reason) -> Field" factory.
    """

    def _shortcut(
        *,
        source: Optional[str] = None,
        required: bool = False,
        default: Any = _UNSET,
        description: Optional[str] = None,
        name: Optional[str] = None,
        resolver: Optional[Callable[..., Any]] = None,
        deprecation_reason: Optional[str] = None,
    ) -> Field:
        return Field(
            scalar_singleton,
            source=source,
            required=required,
            default=default,
            description=description,
            name=name,
            resolver=resolver,
            deprecation_reason=deprecation_reason,
        )

    return _shortcut


# Explicit scalar-shortcut bindings. Each name is a statically-visible module
# attribute (so mypy / import tooling see them) produced by the single
# ``_make_scalar_shortcut`` factory bound to the inventory scalar. The inventory
# order and the scalar mapping are the SINGLE source of truth (see
# ``_scalar_inventory``); these bindings restate the names explicitly so static
# analysis and IDEs resolve every shortcut. Each is usable in BOTH positions
# (unification): the 12 former ``*InputField`` twins are gone.
IntField = _make_scalar_shortcut(_scalar_inventory()[0][1])
CharField = _make_scalar_shortcut(_scalar_inventory()[1][1])
FloatField = _make_scalar_shortcut(_scalar_inventory()[2][1])
BooleanField = _make_scalar_shortcut(_scalar_inventory()[3][1])
IDField = _make_scalar_shortcut(_scalar_inventory()[4][1])
DateField = _make_scalar_shortcut(_scalar_inventory()[5][1])
DateTimeField = _make_scalar_shortcut(_scalar_inventory()[6][1])
TimeField = _make_scalar_shortcut(_scalar_inventory()[7][1])
DecimalField = _make_scalar_shortcut(_scalar_inventory()[8][1])
UUIDField = _make_scalar_shortcut(_scalar_inventory()[9][1])


def JSONField(  # noqa: N802 - Django-style capitalized field descriptor
    *,
    as_str: bool = False,
    source: Optional[str] = None,
    required: bool = False,
    default: Any = _UNSET,
    description: Optional[str] = None,
    name: Optional[str] = None,
    resolver: Optional[Callable[..., Any]] = None,
    deprecation_reason: Optional[str] = None,
) -> Field:
    """Position-agnostic JSON field descriptor with a string-encoding escape hatch.

    "as_str=False" (the default) binds the RAW "JSON" scalar ("GdxJSON"):
    objects / lists / scalars pass through structurally on BOTH the output and
    the input (argument) surface. "as_str=True" binds the string-encoded
    "JSONString" scalar ("GdxJSONString") — the escape hatch for clients that
    want the value transported as a JSON string.

    Works in BOTH positions (unification): usable in an "ObjectType" body AND a
    "class Arguments" body, exactly like every other scalar shortcut.

    Args:
        as_str: Bind "JSONString" (string-encoded) instead of the raw "JSON"
            scalar. Defaults to False (raw structured JSON).
        source: OUTPUT source attribute override.
        required: Wrap the type in "NonNull".
        default: INPUT default (a bare "_UNSET" means no default).
        description: Field / argument description.
        name: Explicit GraphQL name override.
        resolver: OUTPUT resolver override.
        deprecation_reason: Marks the field / argument deprecated.

    Returns:
        json_field: A "Field" bound to "GdxJSON" (or "GdxJSONString" when
            "as_str" is true).
    """
    from .scalars import GdxJSON, GdxJSONString

    scalar = GdxJSONString if as_str else GdxJSON
    return Field(
        scalar,
        source=source,
        required=required,
        default=default,
        description=description,
        name=name,
        resolver=resolver,
        deprecation_reason=deprecation_reason,
    )
