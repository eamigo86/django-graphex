"""ObjectType and InputType base classes for the native backend.

Pydantic ``ModelMetaclass`` is the sole metaclass for all public input types.
Zero custom metaclass written — ``InputType`` is a plain ``BaseModel`` subclass.

Design contracts:
- ``type(AnyInputSubclass) is pydantic.ModelMetaclass``
- ``ConfigDict(alias_generator=to_camel, populate_by_name=True)``
- ``__init_subclass__`` pushes every ``InputType`` subclass to the module-level
  ``_gdx_input_registry`` list.
- ``compile_all_inputs()`` runs in two passes after ``AppConfig.ready()``:
    PASS 1: ``model_rebuild(raise_errors=True)`` for all registered classes.
    PASS 2: ``compile_input_type(...)`` for all; duplicate GraphQL names →
            ``ImproperlyConfigured``.
- ``_GdxGetItemMixin.__getitem__`` enables ``data["field_name"]`` access on
  validated instances.
"""

from __future__ import annotations

from dataclasses import dataclass
from inspect import cleandoc, isclass
from typing import Any

# ``graphene.types.mountedtype.MountedType`` / ``unmountedtype.UnmountedType``
# are the graphene field-descriptor base classes. They are imported ONLY for two
# graphene-free purposes here:
#   1. ``ignored_types`` — tell Pydantic NOT to mis-parse class-body descriptors
#      (``ok = Boolean(...)``, ``errors = List(...)``, ``Field(...)``) as model
#      fields (which crashes with PydanticUserError 'non-annotated attribute').
#   2. ``_collect_descriptor_fields`` — recover those descriptors from the class
#      ``__dict__`` into ``_meta.fields`` WITHOUT Pydantic field inference.
# Importing these base classes does NOT couple the native runtime to graphene's
# schema machinery; they are plain marker classes. They are removed entirely in
# the final graphene-removal slice (S8). Until then the public ``Django*`` types
# still declare their descriptors as graphene instances, so the native base must
# recognize them.
from graphene.types.mountedtype import MountedType
from graphene.types.unmountedtype import UnmountedType
from pydantic import BaseModel, ConfigDict
from pydantic.alias_generators import to_camel

# A class-attribute name (or value) is treated as a graphene FIELD DESCRIPTOR
# when it is an instance of one of these. ``MountedType`` covers ``Field(...)``;
# ``UnmountedType`` covers scalars/structures like ``Boolean()`` / ``List(...)``.
_GRAPHENE_DESCRIPTOR_TYPES = (UnmountedType, MountedType)


def _trim_docstring(docstring: str | None) -> str | None:
    """Graphene-free re-implementation of ``graphene.utils.trim_docstring``.

    graphene's helper is literally ``inspect.cleandoc(docstring) if docstring
    else None`` (graphene/utils/trim_docstring.py). We must not import graphene
    in the native runtime, so this replicates it byte-for-byte with the stdlib:
    PEP 257 indentation cleanup via ``inspect.cleandoc``, returning ``None`` for
    a falsy (``None`` / empty) docstring so ``_meta.description`` stays ``None``
    rather than an empty string (graphene parity).
    """
    return cleandoc(docstring) if docstring else None


def _props(meta_cls: type) -> dict[str, Any]:
    """Graphene-free re-implementation of ``graphene.utils.props.props``.

    Returns the user-declared attributes of a ``Meta`` class as a dict,
    skipping the attributes every bare class already carries (``__dict__``,
    ``__weakref__``, dunders, etc.). This matches graphene's behavior of
    turning a ``class Meta: ...`` body into keyword options.
    """

    class _Old:
        pass

    base_attrs = set(dir(_Old))
    return {
        key: vars(meta_cls).get(key, getattr(meta_cls, key))
        for key in dir(meta_cls)
        if key not in base_attrs
    }


def _collect_descriptor_fields(cls: type) -> dict[str, Any]:
    """Collect graphene field descriptors declared across the MRO into a dict.

    Mirrors graphene's ``yank_fields_from_attrs`` collection performed inside
    ``ObjectType.__init_subclass_with_meta__``: walk the MRO (base-first, so
    subclass declarations win on name collisions) and pick up every attribute
    whose VALUE is a graphene ``UnmountedType`` / ``MountedType`` descriptor.

    The descriptors are returned AS-IS (not wrapped into graphene ``Field``s);
    the native compiler reads ``_meta.fields`` via ``getattr(...)`` and inspects
    each value's ``type`` / kind, so the raw descriptor is the right currency
    here and keeps S6a graphene-free at the call sites that follow.
    """
    fields: dict[str, Any] = {}
    for base in reversed(cls.__mro__):
        for attr_name, value in vars(base).items():
            if isinstance(value, _GRAPHENE_DESCRIPTOR_TYPES):
                fields[attr_name] = value
    return fields


# ---------------------------------------------------------------------------
# __getitem__ mixin
# ---------------------------------------------------------------------------


class _GdxGetItemMixin:
    """Mixin that adds ``data["key"]`` access to Pydantic model instances.

    ``model_dump()`` is called once per ``__getitem__`` call, which is
    acceptable at resolve time (not a hot path).
    """

    def __getitem__(self, key: str) -> Any:
        return self.model_dump()[key]  # type: ignore[attr-defined]


# ---------------------------------------------------------------------------
# _GdxInputOptions — carries the compiled GraphQLInputObjectType
# ---------------------------------------------------------------------------


@dataclass
class _GdxInputOptions:
    """Options object stored on ``InputType`` subclasses after compilation.

    Accessed via ``cls._meta.graphql_input_type``.
    """

    graphql_input_type: Any = None  # set by compile_all_inputs()


class _GdxInputMeta:
    """Simple proxy over ``_GdxInputOptions`` to expose ``graphql_input_type``."""

    __slots__ = ("_opts",)

    def __init__(self, opts: _GdxInputOptions) -> None:
        object.__setattr__(self, "_opts", opts)

    @property
    def graphql_input_type(self) -> Any:
        return object.__getattribute__(self, "_opts").graphql_input_type


# ---------------------------------------------------------------------------
# NativeObjectTypeOptions — graphene-free, MUTABLE _meta Options
# ---------------------------------------------------------------------------


class NativeObjectTypeOptions:
    """Graphene-free replacement for graphene's frozen ``*Options`` objects.

    Reproduces the load-bearing surface of graphene's ``BaseOptions`` chain
    (``DjangoObjectOptions`` / ``DjangoModelTypeOptions`` / list / mutation /
    subscription Options) but as a SINGLE, MUTABLE object so later slices
    (S6b-S6f) can plain-assign (``cls._meta.graphql_output_type = ...``) instead
    of the current ``object.__setattr__(_meta, ...)`` freeze-bypass workaround
    (types.py:655,1341).

    Every attribute in the parity table (#1534) is enumerated here with the SAME
    default graphene's per-type Options used, so a re-parented public type never
    hits a silent ``AttributeError`` reading ``_meta.<attr>`` at build or
    runtime. Unknown attributes are NOT silently swallowed: instances behave like
    a normal object, so a typo in a later slice surfaces immediately as an
    ``AttributeError`` on read (parity with graphene's class-attribute defaults).
    """

    # Mutable on purpose — NO freeze() / frozen guard (the whole point of S6a).

    def __init__(
        self, class_type: type | None = None, **overrides: Any
    ) -> None:
        """Initialize every parity-table attribute with its graphene default.

        Args:
            class_type: The owning GraphQL type class (graphene's
                ``BaseOptions.class_type``).
            **overrides: Attribute values that replace the graphene defaults,
                applied last (used by the driver to seed dispatched options).
        """
        # graphene.BaseOptions stores the owning class as ``class_type``.
        self.class_type = class_type

        # --- shared / output (DjangoObjectOptions, types.py:334-391) ---
        self.name: str | None = None
        self.description: str | None = None
        self.model: Any = None
        self.registry: Any = None
        self.queryset: Any = None
        self.fields: Any = None
        self.input_fields: Any = None
        self.interfaces: tuple[Any, ...] = ()
        self.connection: Any = None
        self.create_container: Any = None
        self.filter_fields: tuple[Any, ...] = ()
        self.input_for: Any = None
        self.max_deep: int | None = None
        self.complexity: int | None = None
        self.gfk_unions: Any = None
        self.graphql_input_type: Any = None
        self.graphql_output_type: Any = None

        # --- list container (DjangoListObjectOptions parity) ---
        self.baseType: Any = None
        self.results_field_name: str | None = None
        self.pagination: Any = None

        # --- model / mutation (DjangoModelTypeOptions, SerializerMutationOptions) ---
        self.backend: Any = None
        self.action: Any = None
        self.resolver: Any = None
        self.arguments: Any = None
        self.input_field_name: str | None = None
        self.output: Any = None
        self.output_field_name: str | None = None
        self.output_type: Any = None
        self.output_list_type: Any = None
        self.mutation_output: Any = None
        self.nested_fields: Any = None
        self.model_operations: tuple[str, ...] = ("create", "update", "delete")

        # --- subscription (SubscriptionOptions, subscription.py:63-79) ---
        self.stream: Any = None
        self.serialize_data: Any = None
        self.subscription_index_fields: tuple[Any, ...] = ()
        self.index_fields: tuple[Any, ...] = ()

        # --- union / interface (registry-only) ---
        self.types: Any = None
        self.possible_types: Any = None
        self.default_resolver: Any = None

        # --- input-container shim (deleted in S6c; here for parity) ---
        self.container: Any = None

        # Any kwargs passed through the driver/dispatch override defaults.
        for key, value in overrides.items():
            setattr(self, key, value)

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        """Return a short debug representation showing the type name."""
        return f"<NativeObjectTypeOptions name={self.name!r}>"


# ---------------------------------------------------------------------------
# ObjectType base (model-free output, Phase 3+)
# ---------------------------------------------------------------------------


class ObjectType(_GdxGetItemMixin, BaseModel):
    """Base class for model-free GraphQL output types.

    Uses Pydantic's ``ModelMetaclass`` as the class metaclass — NO custom
    metaclass — so ``type(AnySubclass) is pydantic.ModelMetaclass`` holds (the
    systemic metaclass-identity constraint #1452). The graphene-free driver
    machinery that graphene's ``SubclassWithMeta_Meta`` used to provide is
    reproduced here on ``__init_subclass__`` instead:

    1. Read a ``Meta`` (class OR dict), turn it into keyword options via
       ``_props``, pop ``abstract``.
    2. Collect graphene field descriptors (``Boolean()`` / ``List(...)`` /
       ``Field(...)``) declared on the class body into ``_meta.fields`` WITHOUT
       routing them through Pydantic field inference.
    3. Dispatch ``cls.__init_subclass_with_meta__(**options)`` (skipped for
       abstract bases), then ``delattr(cls, "Meta")``.

    ``ignored_types=(UnmountedType, MountedType)`` is the critical escape: it
    tells Pydantic to NOT treat class-body graphene descriptors as model fields
    (which otherwise crashes with ``PydanticUserError`` 'non-annotated
    attribute'). The descriptors remain in ``cls.__dict__`` for step 2.

    ``alias_generator=to_camel`` wires camelCase SDL names automatically.
    ``populate_by_name=True`` lets callers construct with either snake or camel
    keys. The container constructor stashes descriptor-named payload values (the
    graphene ``cls(**resp)`` pattern) via ``object.__setattr__`` in ``__init__``,
    NOT via Pydantic ``extra='allow'`` (this ``ConfigDict`` does not set
    ``extra``): the descriptor keys are popped from ``kwargs`` before Pydantic's
    own ``__init__`` runs and re-applied as plain instance attributes afterward,
    so Pydantic never sees them and cannot drop them.
    """

    model_config = ConfigDict(
        alias_generator=to_camel,
        populate_by_name=True,
        ignored_types=_GRAPHENE_DESCRIPTOR_TYPES,
    )

    def __init_subclass__(cls, **kwargs: Any) -> None:
        """Graphene-free ``SubclassWithMeta`` driver (see class docstring).

        Mirrors ``graphene.utils.subclass_with_meta.SubclassWithMeta.__init_subclass__``
        plus the field-collection ``ObjectType.__init_subclass_with_meta__`` did.
        Runs for EVERY ``ObjectType`` subclass; for plain subclasses with no
        ``Meta`` and no ``__init_subclass_with_meta__`` it is a clean no-op
        (which is exactly what ``InputType`` and its subclasses need — they keep
        their own Pydantic/``_meta`` flow untouched below).
        """
        super().__init_subclass__(**kwargs)

        # --- read Meta (class OR dict) -> meta_props, mirror graphene ---
        meta = cls.__dict__.get("Meta", None)
        meta_props: dict[str, Any] = {}
        if meta is not None:
            if isinstance(meta, dict):
                meta_props = dict(meta)
            elif isclass(meta):
                meta_props = _props(meta)
            else:
                raise TypeError(
                    f"{cls.__name__}.Meta has to be either a class or a dict. "
                    f"Received {meta!r}."
                )
            delattr(cls, "Meta")

        options = dict(kwargs, **meta_props)
        abstract = options.pop("abstract", False)

        if abstract:
            # Abstract base: graphene asserts no other options accompany it.
            assert not options, (
                "Abstract types can only contain the abstract attribute. "
                f"Received: abstract, {', '.join(options)}"
            )
            return

        # --- collect graphene field descriptors into _meta.fields ---
        # Only meaningful for OUTPUT types that declare descriptors; for plain
        # InputType subclasses this is an empty dict and is ignored below.
        descriptor_fields = _collect_descriptor_fields(cls)

        # --- dispatch into the concrete type's __init_subclass_with_meta__ ---
        # ``ObjectType`` now defines a TERMINAL ``__init_subclass_with_meta__``
        # (the graphene-free chain endpoint below), so ``getattr`` would always
        # resolve to *something*. We must dispatch ONLY when the subclass (or an
        # intermediate non-ObjectType base) declares its OWN driver distinct from
        # the base terminal — that driver is each public ``Django*`` type's
        # ``__init_subclass_with_meta__`` (re-homed onto this base in S6b-S6f),
        # and it ends by calling ``super().__init_subclass_with_meta__`` into the
        # terminal. A plain subclass that merely INHERITS the base terminal has
        # no concrete driver and must take the minimal-_meta else-branch.
        init_with_meta = getattr(cls, "__init_subclass_with_meta__", None)
        base_terminal = ObjectType.__init_subclass_with_meta__.__func__
        has_concrete_driver = (
            init_with_meta is not None
            and getattr(init_with_meta, "__func__", None) is not base_terminal
        )
        if has_concrete_driver:
            # Surface collected descriptors to the concrete implementation so it
            # can fold them into its own _meta.fields (graphene parity). Passed
            # only when present so existing zero-arg signatures keep working.
            if descriptor_fields:
                options.setdefault("_declared_fields", descriptor_fields)
            init_with_meta(**options)
        else:
            # No concrete driver: attach a minimal mutable _meta so the type is
            # still introspectable (name defaults to class name; collected
            # descriptors land in _meta.fields). This is the path the S6a unit
            # tests exercise on throwaway subclasses.
            opts = NativeObjectTypeOptions(class_type=cls)
            opts.name = options.get("name") or cls.__name__
            opts.description = options.get("description") or _trim_docstring(
                cls.__doc__
            )
            opts.fields = descriptor_fields or None
            for key, value in options.items():
                if key == "_declared_fields":
                    continue
                setattr(opts, key, value)
            cls._meta = opts  # type: ignore[attr-defined]

    @classmethod
    def __init_subclass_with_meta__(
        cls,
        name: str | None = None,
        description: str | None = None,
        _meta: Any = None,
        **_kwargs: Any,
    ) -> None:
        """Graphene-free terminal of the ``__init_subclass_with_meta__`` chain.

        Reproduces ``graphene.types.base.BaseType.__init_subclass_with_meta__``
        (graphene/types/base.py) WITHOUT graphene's ``freeze()`` — the whole
        point of S6a is a MUTABLE ``_meta``. The 8 public ``Django*`` drivers
        each build their own ``_meta`` fully (types.py:495,799,855,1194,1710;
        mutation.py:430; subscriptions/subscription.py:235) and end with
        ``super().__init_subclass_with_meta__(_meta=_meta, ...)``; today that
        super() resolves into graphene's ``BaseType`` terminal, and after S6b
        re-parents the public types onto this native base it must resolve HERE.

        graphene's ``BaseType`` terminal does exactly: return early on a falsy
        ``_meta``; set ``_meta.name = name or cls.__name__``; set
        ``_meta.description = description or trim_docstring(cls.__doc__)``;
        ``_meta.freeze()``; ``cls._meta = _meta``. Every concrete driver builds
        its ``_meta`` completely BEFORE calling super() and forwards ``types`` /
        ``interfaces`` only for graphene ``Union`` / ``Interface`` to consume in
        THEIR own ``__init_subclass_with_meta__`` before super() — graphene's
        ``BaseType`` ignores them via ``**_kwargs``. So this terminal needs only
        name/description/assign; no driver relies on super() handling
        interfaces, registry, or freezing.
        """
        if _meta is None:
            return
        _meta.name = name or cls.__name__
        _meta.description = description or _trim_docstring(cls.__doc__)
        # NO freeze() — S6a keeps _meta mutable so later slices plain-assign
        # instead of the object.__setattr__ workaround (types.py:655,1341).
        cls._meta = _meta  # type: ignore[attr-defined]

    def __init__(self, **kwargs: Any) -> None:
        """Container-style constructor: round-trip ``cls(**kwargs)`` payloads.

        Mirrors graphene's value-object / mutation payload pattern
        ``cls(**resp)`` / ``cls(**errors_dict)`` (mutation.py:504,519;
        types.py:1750,1828). Keys that name a graphene FIELD DESCRIPTOR (e.g.
        ``ok`` / ``errors`` on a mutation payload) are stashed as plain instance
        attributes — they are NOT Pydantic fields, so Pydantic's own
        ``__init__`` would silently drop them. Remaining keys are real Pydantic
        model fields and flow through normal validation.
        """
        descriptor_names = _collect_descriptor_fields(type(self))
        if descriptor_names:
            descriptor_payload = {
                k: kwargs.pop(k) for k in list(kwargs) if k in descriptor_names
            }
        else:
            descriptor_payload = {}
        super().__init__(**kwargs)
        for key, value in descriptor_payload.items():
            object.__setattr__(self, key, value)


# ---------------------------------------------------------------------------
# Module-level registry of all InputType subclasses
# ---------------------------------------------------------------------------

_gdx_input_registry: list[type["InputType"]] = []

# ---------------------------------------------------------------------------
# Module-level registry of all DjangoObjectType / DjangoListObjectType subclasses
# ---------------------------------------------------------------------------


@dataclass
class _GdxOutputEntry:
    """Registration record stored in ``_gdx_output_registry``.

    Created by ``DjangoObjectType.__init_subclass_with_meta__`` (and the
    ``DjangoListObjectType`` equivalent) when ``GDX_BACKEND=native``.
    ``compile_all_outputs()`` reads these entries to perform the deferred
    compilation at app-ready time.
    """

    cls: type  # the DjangoObjectType / DjangoListObjectType subclass
    gql_name: str  # GraphQL type name (cls.__name__)
    model: type  # Django model class
    only_fields: list[str] | None
    exclude_fields: list[str] | None
    max_deep: int | None
    complexity: int | None


_gdx_output_registry: list[_GdxOutputEntry] = []

# ---------------------------------------------------------------------------
# Shared output registry singleton
# ---------------------------------------------------------------------------
# A SINGLE process-wide ``NativeOutputRegistry`` shared by BOTH the class-def
# compile (``DjangoObjectType.__init_subclass_with_meta__`` native branch) AND
# ``compile_all_outputs()``.  This is the heart of the identity invariant:
# exactly ONE ``GraphQLObjectType`` instance per ``DjangoObjectType``, created
# once at class definition with relation-field THUNKS that resolve against this
# shared registry.  ``compile_all_outputs()`` POPULATES/validates the existing
# instances against this same registry — it NEVER creates a second instance for
# an already-registered type.  Relations therefore resolve to the related
# type's real ``GraphQLObjectType`` (not a ``GraphQLString`` fallback), because
# every type is registered in the same registry before any thunk evaluates.
#
# Typed as ``Any`` to avoid importing ``registry_compiler`` (which imports
# graphql/bridge/ir) at ``base`` import time.
_gdx_shared_output_registry: Any = None


def get_shared_output_registry() -> Any:
    """Return the process-wide shared ``NativeOutputRegistry`` singleton.

    Lazily created on first use so ``base`` has no import-time dependency on
    ``registry_compiler``.  Both the class-def native compile and
    ``compile_all_outputs()`` MUST use this single instance so relation thunks
    resolve cross-type references against the same registry (identity-stable).
    """
    global _gdx_shared_output_registry
    if _gdx_shared_output_registry is None:
        from django_graphex.native.registry_compiler import NativeOutputRegistry

        _gdx_shared_output_registry = NativeOutputRegistry()
    return _gdx_shared_output_registry


# ---------------------------------------------------------------------------
# InputType base (model-free inputs)
# ---------------------------------------------------------------------------


class InputType(ObjectType):
    """Base class for model-free GraphQL input types.

    Every subclass is automatically registered in ``_gdx_input_registry`` via
    ``__init_subclass__`` and compiled by ``compile_all_inputs()`` at startup.

    Usage::

        from django_graphex import InputType

        class SearchInput(InputType):
            query: str
            limit: int = 10
    """

    def __init_subclass__(cls, **kwargs: Any) -> None:
        """Register the subclass and attach its input ``_meta``.

        ``super().__init_subclass__()`` runs the ``ObjectType`` graphene-free
        driver first (a clean no-op for plain ``InputType`` subclasses: no
        ``Meta``, no ``__init_subclass_with_meta__``, no graphene descriptors).
        That driver may seed a ``NativeObjectTypeOptions`` ``_meta``; this method
        then OVERWRITES it with the input-specific ``_GdxInputMeta`` so the
        existing ``cls._meta.graphql_input_type`` flow (populated later by
        ``compile_all_inputs``) is unchanged. The InputType behavior is therefore
        identical to before S6a.
        """
        super().__init_subclass__(**kwargs)
        _gdx_input_registry.append(cls)

        # Attach an empty _meta (graphql_input_type populated by compile_all_inputs)
        opts = _GdxInputOptions()
        cls._meta = _GdxInputMeta(opts)  # type: ignore[attr-defined]
        # Keep a reference to the options so compile_all_inputs can mutate it
        cls._gdx_opts = opts  # type: ignore[attr-defined]


# ---------------------------------------------------------------------------
# compile_all_inputs
# ---------------------------------------------------------------------------


def compile_all_inputs() -> None:
    """Compile all registered ``InputType`` subclasses into ``GraphQLInputObjectType``.

    Called by ``DjangoGraphexConfig.ready()`` after all app models are loaded.

    Algorithm (two-pass to resolve forward refs deterministically):
    1. ``model_rebuild(raise_errors=True)`` for every registered class.
       ``PydanticUserError(code='model-not-fully-defined')`` is re-raised as
       ``ImproperlyConfigured`` naming the class and the unresolved ref.
    2. ``compile_input_type(...)`` for every class.
       Duplicate GraphQL names raise ``ImproperlyConfigured``.
    """
    from django.core.exceptions import ImproperlyConfigured

    from django_graphex.native.input_compiler import compile_input_type

    # PASS 1: model_rebuild for all (resolves cross-module forward refs)
    for cls in _gdx_input_registry:
        try:
            cls.model_rebuild(raise_errors=True)
        except Exception as exc:
            raise ImproperlyConfigured(
                f"compile_all_inputs: could not rebuild model for {cls.__name__!r}. "
                f"Unresolved forward reference in annotations. "
                f"Original error: {exc}"
            ) from exc

    # PASS 2: compile_input_type for all (detect duplicates)
    seen_names: dict[str, type] = {}
    for cls in _gdx_input_registry:
        # GraphQL type name defaults to the class name
        gql_name = cls.__name__
        if gql_name in seen_names:
            raise ImproperlyConfigured(
                f"compile_all_inputs: duplicate GraphQL input type name "
                f"{gql_name!r} — defined by both "
                f"{seen_names[gql_name].__module__}.{seen_names[gql_name].__qualname__} "
                f"and {cls.__module__}.{cls.__qualname__}."
            )
        seen_names[gql_name] = cls

        # Compile and store on _meta
        graphql_input_type = compile_input_type(
            cls,
            name=gql_name,
            description=getattr(cls, "__doc__", None),
        )
        cls._gdx_opts.graphql_input_type = graphql_input_type  # type: ignore[attr-defined]
