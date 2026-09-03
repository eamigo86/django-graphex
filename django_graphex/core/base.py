"""ObjectType and InputType base classes for the native backend.

Pydantic "ModelMetaclass" is the sole metaclass for all public input types.
Zero custom metaclass written — "InputType" is a plain "BaseModel" subclass.

Design contracts:
- "type(AnyInputSubclass) is pydantic.ModelMetaclass"
- "ConfigDict(alias_generator=to_camel, populate_by_name=True)"
- "__init_subclass__" pushes every "InputType" subclass to the module-level
  "_gdx_input_registry" list.
- "compile_all_inputs()" runs in two passes after "AppConfig.ready()":
    PASS 1: "model_rebuild(raise_errors=True)" for all registered classes.
    PASS 2: "compile_input_type(...)" for all; duplicate GraphQL names raise
            "ImproperlyConfigured".
- "_GdxGetItemMixin.__getitem__" enables "data['field_name']" access on
  validated instances.
"""

from __future__ import annotations

from dataclasses import dataclass
from inspect import cleandoc, isclass
from typing import Any

# S8h (graphene-removal): core/base.py is now FULLY graphene-free at the top
# level — these were the LAST two top-level graphene imports in the whole
# ``django_graphex`` package. They previously imported the graphene
# field-descriptor base classes (``MountedType`` / ``UnmountedType``) ONLY to
# DETECT + ignore graphene descriptors (``name = graphene.String()``) declared on
# a NATIVE ``ObjectType`` class body — a 1.x back-compat shim. The 2.0 public
# field-declaration API is ``field()`` (``NativeField`` / ``NativeMountedField``),
# so graphene descriptors on a native type are NO LONGER supported: users migrate
# ``name = graphene.String()`` -> ``name = field(GraphQLString)``. The native
# descriptor currency below (``NativeField`` / ``NativeMountedField`` /
# ``GraphQLField``) is what the detection tuples recognize now.
from graphql import GraphQLField
from pydantic import BaseModel, ConfigDict
from pydantic.alias_generators import to_camel

from django_graphex.core.descriptors import NativeField, NativeMountedField

# A class-attribute name (or value) is treated as a FIELD DESCRIPTOR (a payload
# key the container ``__init__`` round-trips) when it is an instance of this.
# ``NativeMountedField`` (S8c) covers the re-parented ``Django*Field`` classes —
# graphene-free mounted descriptors — so a ``posts = DjangoNestedListObjectField(...)``
# class attribute is recognized AND shielded from Pydantic model-field inference.
# S8h dropped the graphene ``MountedType`` / ``UnmountedType`` markers (graphene
# descriptors on a native type are no longer supported in 2.0; users migrate to
# ``field()``). S-del-backend-11 removed the dead ``_GRAPHENE_DESCRIPTOR_TYPES``
# tuple — ``_FIELD_DESCRIPTOR_TYPES`` (below) is the live collector.

# A class-attribute is treated as a FIELD DESCRIPTOR (collected into
# ``_meta.fields`` and shielded from Pydantic model-field inference) when it is an
# instance of one of these. After S8h this is the pure-native field currency:
# ``NativeMountedField`` (re-parented ``Django*Field`` classes), ``NativeField``
# (the ``field()`` descriptor), and a raw graphql-core ``GraphQLField``. The
# graphene ``MountedType`` / ``UnmountedType`` markers were removed — graphene
# descriptors declared on a native type are no longer recognized (2.0 contract).
#
# Recognizing ``NativeField`` here lets a class-body ``field()`` declaration —
# e.g. ``errors.py``'s native ``ErrorType`` (S-ROOTS-b) — land in ``_meta.fields``
# instead of being silently inferred as a Pydantic model field (PydanticUserError)
# or dropped.
#
# Recognizing ``GraphQLField`` (S-ROOTS-h) lets a NATIVE ``ObjectType`` root hold
# a raw graphql-core ``GraphQLField`` class attribute — e.g.
# ``create_x = CreateX.Field()`` (hand-written ``Mutation``) or
# ``post_create = PostMutation.CreateField()`` (``DjangoModelMutation``) — without
# crashing at class-def with ``PydanticUserError`` ('non-annotated attribute'). The
# raw field is collected into ``_meta.fields`` AS-IS; the native root compiler
# reuses it verbatim (it is already a compiled graphql-core field — never recompiled
# or scalar-converted). Previously only a GRAPHENE root tolerated these (graphene's
# metaclass silently DROPPED them, and ``_collect_root_attrs`` recovered the
# registered ones); a native root could not declare one at all.
_FIELD_DESCRIPTOR_TYPES = (
    NativeMountedField,
    NativeField,
    GraphQLField,
)
# The unified ``Field`` (field-unify) subclasses ``NativeMountedField``, so it is
# already recognized by the tuple above in BOTH positions: declared on an
# ObjectType body (OUTPUT) it lands in ``_meta.fields``; declared in a
# ``class Arguments`` body / ``Field(args=...)`` (INPUT) it is consumed by the arg
# builders. The former separate ``InputField`` entry (a distinct class) is gone.


def _django_model_field_type() -> type | None:
    """Return django.db.models.Field (imported lazily), or None if absent.

    Imported LAZILY (design decision #4 — preserve the lazy-defer convention: no
    top-level django.db import in base.py). Tolerates ImportError so a
    non-Django import context degrades gracefully to "no guard" rather than
    crashing at module import.
    """
    try:
        from django.db.models import Field as _DjangoModelField
    except Exception:  # pragma: no cover - Django always importable in this pkg
        return None
    return _DjangoModelField


def _ignored_types_with_django_field() -> tuple[type, ...]:
    """_FIELD_DESCRIPTOR_TYPES plus django.db.models.Field for Pydantic.

    Adding Django's Field to Pydantic ignored_types stops Pydantic's
    metaclass from raising its cryptic PydanticUserError ('non-annotated
    attribute') the instant a name = models.CharField(...) lands on the body —
    BEFORE __init_subclass__ (and thus our loud guard) ever runs. With it
    ignored, the class body evaluates and __init_subclass__'s
    _guard_django_model_field_on_body scan fires the LOUD, actionable
    TypeError instead.
    """
    django_field = _django_model_field_type()
    if django_field is None:  # pragma: no cover - Django always present here
        return _FIELD_DESCRIPTOR_TYPES
    return (*_FIELD_DESCRIPTOR_TYPES, django_field)


def _guard_django_model_field_on_body(name: str, value: object) -> None:
    """Raise a LOUD TypeError for a django.db.models.Field on a type body.

    The ObjectType-body twin of _args._guard_django_model_field: catches
    name = models.CharField(max_length=10) on an ObjectType / Mutation
    class body (the likely mistake being an import from django.db.models
    instead of django_graphex.core). Django Field is resolved LAZILY to
    preserve the lazy-defer convention. Intentionally NOT deduplicated with the
    native_arg site (design decision #4) — each entry point fails on its own.
    """
    django_field = _django_model_field_type()
    if django_field is not None and isinstance(value, django_field):
        raise TypeError(
            f"{name!r}: got a django.db.models.Field ({value!r}). Did you import "
            f"CharField from django.db.models instead of django_graphex.core? Use "
            f"django_graphex.core.CharField (or Field) for GraphQL "
            f"fields."
        )


def _trim_docstring(docstring: str | None) -> str | None:
    """Graphene-free re-implementation of graphene.utils.trim_docstring.

    graphene's helper is literally inspect.cleandoc(docstring) if docstring
    else None (graphene/utils/trim_docstring.py). We must not import graphene
    in the native runtime, so this replicates it byte-for-byte with the stdlib:
    PEP 257 indentation cleanup via inspect.cleandoc, returning None for
    a falsy (None / empty) docstring so _meta.description stays None
    rather than an empty string (graphene parity).
    """
    return cleandoc(docstring) if docstring else None


def _props(meta_cls: type) -> dict[str, Any]:
    """Graphene-free re-implementation of graphene.utils.props.props.

    Returns the user-declared attributes of a Meta class as a dict,
    skipping the attributes every bare class already carries (__dict__,
    __weakref__, dunders, etc.). This matches graphene's behavior of
    turning a class Meta: ... body into keyword options.
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
    """Collect native field descriptors declared across the MRO into a dict.

    Walks the MRO (base-first, so subclass declarations win on name collisions)
    and picks up every attribute whose VALUE is a NATIVE field descriptor
    (NativeMountedField / NativeField / a raw graphql-core GraphQLField
    — see _FIELD_DESCRIPTOR_TYPES).

    The descriptors are returned AS-IS; the native compiler reads _meta.fields
    via getattr(...) and inspects each value's type / kind, so the raw
    descriptor is the right currency here. S8h dropped the graphene
    UnmountedType / MountedType recognition (graphene descriptors on a
    native type are no longer supported in 2.0; users migrate to field()).
    """
    fields: dict[str, Any] = {}
    for base in reversed(cls.__mro__):
        for attr_name, value in vars(base).items():
            if isinstance(value, _FIELD_DESCRIPTOR_TYPES):
                fields[attr_name] = value
    return fields


def _mount_descriptor_fields(cls: type) -> dict[str, Any]:
    """Collect class-body NATIVE field descriptors into {name: descriptor}.

    Walks the MRO base-first (so a subclass declaration wins on a name collision)
    and collects every NATIVE field descriptor: a NativeMountedField (the
    re-parented Django*Field classes, e.g. DjangoListObjectField), a
    NativeField (a class-body field() declaration, e.g. the native
    ErrorType), or a raw graphql-core GraphQLField (a mounted mutation
    field on a native root). Each is ALREADY field-shaped — it exposes .type /
    .args / .wrap_resolve (the currency the native declared-field compiler
    reads) — so it is merged in AS-IS.

    S8h: the graphene-mount half (yank_fields_from_attrs(base.__dict__,
    _as=Field)) was removed. It existed only to mount graphene UnmountedType
    / MountedType descriptors declared on a native type into a graphene
    Field; the 2.0 contract drops graphene-descriptor support, so that path is
    dead and base.py is now graphene-free (no lazy graphene import either).
    Recognizing the native currency here is the MOUNT half of the silent-drop
    guard — without it a class-body field() / mounted GraphQLField would
    vanish from _meta.fields.
    """
    fields: dict[str, Any] = {}
    for base in reversed(cls.__mro__):
        for attr_name, value in vars(base).items():
            if isinstance(value, _FIELD_DESCRIPTOR_TYPES):
                fields[attr_name] = value
    return fields


# ---------------------------------------------------------------------------
# __getitem__ mixin
# ---------------------------------------------------------------------------


class _GdxGetItemMixin:
    """Mixin that adds data["key"] access to Pydantic model instances.

    model_dump() is called once per __getitem__ call, which is
    acceptable at resolve time (not a hot path).
    """

    def __getitem__(self, key: str) -> Any:
        return self.model_dump()[key]  # type: ignore[attr-defined]


# ---------------------------------------------------------------------------
# _GdxInputOptions — carries the compiled GraphQLInputObjectType
# ---------------------------------------------------------------------------


@dataclass
class _GdxInputOptions:
    """Options object stored on InputType subclasses after compilation.

    Accessed via cls._meta.graphql_input_type.
    """

    graphql_input_type: Any = None  # set by compile_all_inputs()


class _GdxInputMeta:
    """Simple proxy over _GdxInputOptions to expose graphql_input_type."""

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
    """Graphene-free replacement for graphene's frozen "*Options" objects.

    Reproduces the load-bearing surface of graphene's "BaseOptions" chain
    ("DjangoObjectOptions" / "DjangoModelTypeOptions" / list / mutation /
    subscription Options) but as a SINGLE, MUTABLE object so later slices
    (S6b-S6f) can plain-assign ("cls._meta.graphql_output_type = ...") instead
    of the current "object.__setattr__(_meta, ...)" freeze-bypass workaround
    (types.py:655,1341).

    Every attribute in the parity table (#1534) is enumerated here with the SAME
    default graphene's per-type Options used, so a re-parented public type never
    hits a silent "AttributeError" reading "_meta.<attr>" at build or
    runtime. Unknown attributes are NOT silently swallowed: instances behave like
    a normal object, so a typo in a later slice surfaces immediately as an
    "AttributeError" on read (parity with graphene's class-attribute defaults).
    """

    # Mutable on purpose — NO freeze() / frozen guard (the whole point of S6a).

    def __init__(self, class_type: type | None = None, **overrides: Any) -> None:
        """Initialize every parity-table attribute with its graphene default.

        Args:
            class_type: The owning GraphQL type class (graphene's
                "BaseOptions.class_type").
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
        self.max_depth: int | None = None
        self.complexity: int | None = None
        self.unions: Any = None
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
        self.payload_mode: Any = None
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

    Uses Pydantic's "ModelMetaclass" as the class metaclass — NO custom
    metaclass — so "type(AnySubclass) is pydantic.ModelMetaclass" holds (the
    systemic metaclass-identity constraint #1452). The graphene-free driver
    machinery that graphene's "SubclassWithMeta_Meta" used to provide is
    reproduced here on "__init_subclass__" instead:

    1. Read a "Meta" (class OR dict), turn it into keyword options via
       "_props", pop "abstract".
    2. Collect NATIVE field descriptors (a "field()" / "NativeField" scalar,
       a re-parented "Django*Field" / "NativeMountedField", or a raw
       graphql-core "GraphQLField") declared on the class body into
       "_meta.fields" WITHOUT routing them through Pydantic field inference.
    3. Dispatch "cls.__init_subclass_with_meta__(**options)" (skipped for
       abstract bases), then "delattr(cls, 'Meta')".

    "ignored_types=_FIELD_DESCRIPTOR_TYPES" is the critical escape: it tells
    Pydantic to NOT treat class-body native field descriptors as model fields
    (which otherwise crashes with "PydanticUserError" 'non-annotated
    attribute'). The descriptors remain in "cls.__dict__" for step 2. S8h: the
    tuple is now pure-native (graphene "UnmountedType" / "MountedType" markers
    removed — graphene descriptors on a native type are unsupported in 2.0).

    "alias_generator=to_camel" wires camelCase SDL names automatically.
    "populate_by_name=True" lets callers construct with either snake or camel
    keys. The container constructor stashes descriptor-named payload values (the
    graphene "cls(**resp)" pattern) via "object.__setattr__" in "__init__",
    NOT via Pydantic "extra='allow'" (this "ConfigDict" does not set
    "extra"): the descriptor keys are popped from "kwargs" before Pydantic's
    own "__init__" runs and re-applied as plain instance attributes afterward,
    so Pydantic never sees them and cannot drop them.
    """

    model_config = ConfigDict(
        alias_generator=to_camel,
        populate_by_name=True,
        # Include ``django.db.models.Field`` so a mistaken model field on the body
        # is IGNORED by Pydantic (no cryptic ``PydanticUserError``) and instead
        # caught by the loud ``_guard_django_model_field_on_body`` guard in
        # ``__init_subclass__`` (field-descriptor-api, design decision #4).
        ignored_types=_ignored_types_with_django_field(),
    )

    def __init_subclass__(cls, **kwargs: Any) -> None:
        """Graphene-free SubclassWithMeta driver (see class docstring).

        Mirrors graphene.utils.subclass_with_meta.SubclassWithMeta.__init_subclass__
        plus the field-collection ObjectType.__init_subclass_with_meta__ did.
        Runs for EVERY ObjectType subclass; for plain subclasses with no
        Meta and no __init_subclass_with_meta__ it is a clean no-op
        (which is exactly what InputType and its subclasses need — they keep
        their own Pydantic/_meta flow untouched below).
        """
        super().__init_subclass__(**kwargs)

        # --- collision guard: a django.db.models.Field on the class body ---
        # Fires the LOUD, named TypeError (field-descriptor-api, decision #4).
        # Runs BEFORE any _meta / descriptor work so the mistake surfaces early.
        for attr_name, attr_value in vars(cls).items():
            _guard_django_model_field_on_body(attr_name, attr_value)

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

        # --- dispatch into the PARENT's __init_subclass_with_meta__ ---
        # CRITICAL: mirror graphene's
        # ``graphene.utils.subclass_with_meta.SubclassWithMeta.__init_subclass__``
        # dispatch EXACTLY — it calls ``super(cls, cls).__init_subclass_with_meta__``,
        # i.e. the PARENT's driver, NOT ``cls``'s own. This is load-bearing for the
        # re-parented ``Django*`` types: each one DEFINES a driver that asserts a
        # Django ``model`` is present, and the BASE class carries no model. With a
        # naive ``cls.__init_subclass_with_meta__`` dispatch the base's OWN driver
        # would fire on the base at import time and raise
        # ``AssertionError: ... received "None"`` (the S6b crasher). graphene avoids
        # this because a class's declared driver only runs for its SUBCLASSES:
        # when ``DjangoObjectType`` itself is defined, ``super(DjangoObjectType,
        # DjangoObjectType).__init_subclass_with_meta__`` resolves to THIS native
        # ``ObjectType`` terminal (benign empty _meta); when ``class Foo(
        # DjangoObjectType)`` is defined, it resolves to ``DjangoObjectType``'s
        # real driver.
        super_class = super(cls, cls)
        init_with_meta = getattr(super_class, "__init_subclass_with_meta__", None)
        if init_with_meta is not None:
            init_with_meta(**options)

    @classmethod
    def __init_subclass_with_meta__(
        cls,
        name: str | None = None,
        description: str | None = None,
        interfaces: tuple[Any, ...] = (),
        _meta: Any = None,
        **_kwargs: Any,
    ) -> None:
        """Graphene-free terminal of the __init_subclass_with_meta__ chain.

        Collapses graphene's two-step ObjectType.__init_subclass_with_meta__
        + BaseType.__init_subclass_with_meta__ chain into ONE graphene-free
        endpoint, WITHOUT graphene's freeze() (the whole point of S6a/S6b is a
        MUTABLE _meta so later slices plain-assign instead of the old
        object.__setattr__ workaround).

        Two call shapes reach here (both via super(cls, cls) dispatch in
        __init_subclass__, mirroring graphene's SubclassWithMeta):

        1. **Plain subclass** (no concrete driver in the MRO above this base): the
           dispatcher calls this terminal directly with _meta=None. We build a
           fresh mutable NativeObjectTypeOptions, collect class-body graphene
           field descriptors into _meta.fields (graphene's
           yank_fields_from_attrs equivalent), then set name/description and
           assign. This is graphene ObjectType.__init_subclass_with_meta__'s
           job for a plain ObjectType.

        2. **Re-parented Django* driver** (DjangoObjectType /
           DjangoListObjectType and S6c-S6f): the driver builds its _meta
           fully (model/registry/fields/...) and ends with
           super().__init_subclass_with_meta__(_meta=_meta, interfaces=...,
           **options). Here _meta is non-None, so we MERGE any collected
           descriptor fields the driver did not already account for, default the
           interfaces, then set name/description and assign.

        graphene's BaseType terminal does exactly: _meta.name = name or
        cls.__name__; _meta.description = description or
        trim_docstring(cls.__doc__); freeze(); cls._meta = _meta. We
        replicate that minus freeze(). graphene's ObjectType step also
        merges interface fields + yanked attrs and sets interfaces /
        possible_types / default_resolver; the native compiler reads
        _meta.fields and _meta.interfaces, so we replicate the
        field-merge + interface-default and leave possible_types/default_resolver
        at their Options defaults.
        """
        # Collect class-body NATIVE field descriptors across the MRO. This is
        # load-bearing: the native output compiler (``types._compile_declared_fields``
        # -> ``schema_compiler.compile_declared_field``) reads ``field.type`` off
        # each ``_meta.fields`` value. Every native descriptor (``NativeField`` /
        # ``NativeMountedField`` / raw ``GraphQLField``) is already field-shaped and
        # carries ``.type``, so it is collected AS-IS. S8h removed the graphene-mount
        # half (``yank_fields_from_attrs(..., _as=Field)``) — graphene descriptors on
        # a native type are unsupported in 2.0, and ``base.py`` is now graphene-free.
        mounted_fields = _mount_descriptor_fields(cls)

        if _meta is None:
            # Plain subclass path — build a fresh mutable Options object.
            _meta = NativeObjectTypeOptions(class_type=cls)

        # Merge mounted descriptor fields into _meta.fields. A concrete driver may
        # have already populated _meta.fields (e.g. model-derived Field-wrapped
        # fields); graphene MERGES yanked attrs ON TOP, so declared descriptors win
        # on a name collision — replicate that precedence.
        if mounted_fields:
            if _meta.fields:
                merged = dict(_meta.fields)
                merged.update(mounted_fields)
                _meta.fields = merged
            else:
                _meta.fields = mounted_fields

        # Default interfaces only when the driver did not set them (graphene
        # parity: ``if not _meta.interfaces: _meta.interfaces = interfaces``).
        if not _meta.interfaces:
            _meta.interfaces = interfaces

        _meta.name = name or cls.__name__
        _meta.description = description or _trim_docstring(cls.__doc__)
        # NO freeze() — S6a/S6b keep _meta mutable so later slices plain-assign.
        cls._meta = _meta  # type: ignore[attr-defined]

    def __init__(self, **kwargs: Any) -> None:
        """Container-style constructor: round-trip "cls(**kwargs)" payloads.

        Mirrors graphene's value-object / mutation payload pattern
        "cls(**resp)" / "cls(**errors_dict)" (mutation.py:504,519;
        types.py:1750,1828). graphene builds its value-object "__init__" as a
        "dataclass" over EVERY key in "_meta.fields" (graphene
        "ObjectTypeMeta.__new__"), so ALL GraphQL-field-named keys round-trip —
        not only the class-body descriptors.

        The native equivalent: any kwarg whose key names a GraphQL FIELD on this
        type is stashed as a plain instance attribute (it is NOT a Pydantic
        model field, so Pydantic's own "__init__" would silently DROP it — the
        S6c silent-null mutation-payload bug). The authoritative field set is
        "cls._meta.fields" (populated by the driver + the terminal's
        descriptor merge), which includes BOTH the class-body descriptors
        ("ok" / "errors") AND driver-injected fields with a DYNAMIC name
        (the mutation/model-type "output_field_name" — e.g. "category" /
        "post" — that is NOT a class attribute). When "_meta" is absent or
        carries no fields (abstract base, pre-driver), we fall back to the
        class-body descriptor names so the plain-"ObjectType" payload pattern
        still works. Remaining keys are real Pydantic model fields ("InputType"
        / annotated output fields) and flow through normal validation.

        Args:
            **kwargs: Constructor keyword arguments; keys naming a GraphQL field
                on this type are stashed as plain instance attributes and the
                rest flow through Pydantic validation.
        """
        meta = getattr(type(self), "_meta", None)
        field_names: Any = getattr(meta, "fields", None) if meta is not None else None
        if field_names:
            stash_names = set(field_names)
        else:
            # Fallback: no _meta.fields (abstract base / plain payload) — use the
            # class-body graphene descriptors collected across the MRO.
            stash_names = set(_collect_descriptor_fields(type(self)))

        if stash_names:
            value_object_payload = {
                k: kwargs.pop(k) for k in list(kwargs) if k in stash_names
            }
        else:
            value_object_payload = {}
        super().__init__(**kwargs)
        for key, value in value_object_payload.items():
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
    """Registration record stored in _gdx_output_registry.

    Created by DjangoObjectType.__init_subclass_with_meta__ (and the
    DjangoListObjectType equivalent).
    compile_all_outputs() reads these entries to perform the deferred
    compilation at app-ready time.
    """

    cls: type  # the DjangoObjectType / DjangoListObjectType subclass
    gql_name: str  # GraphQL type name (cls.__name__)
    model: type  # Django model class
    only_fields: list[str] | None
    exclude_fields: list[str] | None
    max_depth: int | None
    complexity: int | None
    # issue #65: force-included field names (override only/exclude on the fork).
    include_fields: list[str] | None = None


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


def buried_config_error(error: BaseException) -> Exception | None:
    """Dig a configuration error out of a graphql-core thunk wrapper.

    Args:
        error: The exception graphql-core raised.

    Returns:
        The "ImproperlyConfigured" somewhere in the cause chain, or None when
        the failure is genuinely a graphql-core type error.
    """
    from django.core.exceptions import ImproperlyConfigured

    cause: BaseException | None = error
    while cause is not None:
        if isinstance(cause, ImproperlyConfigured):
            return cause
        cause = cause.__cause__
    return None


def recompile_fields(gql_type: Any) -> None:
    """Drop a compiled type's cached field map and build it again, eagerly.

    Every eager force site routes through here, and the reason is the SECOND
    line: graphql-core rewraps ANYTHING a fields thunk raises as a plain
    "TypeError" whose message is a chain of type names. A build-time refusal --
    a projection contradiction, a filter entry naming nothing -- is raised
    inside such a thunk, so it reached the operator as a "TypeError" naming
    types they never declared, and every doc stating the contract had to lie
    about it. Which site happens to force the thunk first is an implementation
    detail; the exception the operator sees must not depend on it.

    The cached map is dropped first because "GraphQLObjectType.fields" is a
    "cached_property": a premature read (a test, a mid-thunk peek) may have
    cached a fallback for a relation whose target was not registered yet.

    Args:
        gql_type: The compiled type whose field map is forced.

    Raises:
        Exception: The buried "ImproperlyConfigured", when the thunk raised
            one; otherwise graphql-core's own wrapper, untouched.
    """
    gql_type.__dict__.pop("fields", None)
    try:
        _ = gql_type.fields
    except TypeError as error:
        buried = buried_config_error(error)
        if buried is None:
            raise
        raise buried from None


def get_shared_output_registry() -> Any:
    """Return the process-wide shared "NativeOutputRegistry" singleton.

    Lazily created on first use so "base" has no import-time dependency on
    "registry_compiler". Both the class-def native compile and
    "compile_all_outputs()" MUST use this single instance so relation thunks
    resolve cross-type references against the same registry (identity-stable).

    Returns:
        The single process-wide "NativeOutputRegistry" instance.
    """
    global _gdx_shared_output_registry
    if _gdx_shared_output_registry is None:
        from django_graphex.core.registry_compiler import NativeOutputRegistry

        _gdx_shared_output_registry = NativeOutputRegistry()
    return _gdx_shared_output_registry


# ---------------------------------------------------------------------------
# SchemaRegistries — the per-schema registry pair (item-b, B0)
# ---------------------------------------------------------------------------
# A single container that bundles the TWO registries every compile-time thunk
# reads from:
#   1. ``output``  — the ``NativeOutputRegistry`` (relation/list-container
#      cross-type resolution; the central ``get_shared_output_registry()`` one).
#   2. ``graphene`` — the graphene ``Registry`` (``get_global_registry()``):
#      ``get_type_for_model`` / ``get_list_type_for_model`` / choices-enum memo
#      used by the filter-input + optimizer + relation-list builders.
#
# Plus the per-build COMPILE CACHES (item-b, B2) so a distinct registry pair can
# own its OWN cache namespace instead of the process-global module-level dicts.
# The DEFAULT pair (``default_schema_registries()``) reuses the EXISTING global
# instances AND the EXISTING module-level cache dicts, so every call site that
# defaults to it is BYTE-IDENTICAL to the pre-item-b single-namespace behavior.
#
# This is PURE PLUMBING for B0-B2: nothing yet builds a non-default pair, so the
# whole compile path keeps reading the one global namespace. Later slices
# (B3-B5) thread a forked pair into a schema's own thunks.


@dataclass
class SchemaRegistries:
    """A registry pair (plus compile caches) threaded through the native compiler.

    Holds the graphene "Registry" and the "NativeOutputRegistry" a single
    schema build resolves types against, plus the four compile caches that were
    historically process-global module-level dicts:

    - "plain_object_cache" -> "schema_compiler._PLAIN_OBJECT_TYPE_CACHE"
    - "union_cache" -> "polymorphic_compiler._UNION_TYPE_CACHE"
    - "interface_cache" -> "polymorphic_compiler._INTERFACE_TYPE_CACHE"
    - "filter_input_cache" -> "filtering.native_schema._NATIVE_INPUT_CACHE"

    The DEFAULT pair ("default_schema_registries()") seeds every field with the
    EXISTING global instance / module-level dict, so the default compile path is
    byte-identical to the single-namespace behavior. A non-default pair gets
    fresh empty caches so its compiled types live in their own namespace (used by
    later slices; no caller builds one in B0-B2).

    "Any" annotations avoid importing "registry_compiler" / "registry" at
    "base" import time (import-safety on both backends).
    """

    graphene: Any = None
    output: Any = None
    plain_object_cache: dict | None = None
    union_cache: dict | None = None
    interface_cache: dict | None = None
    filter_input_cache: dict | None = None
    # item-b (B5, the lazy-fork): pair-local FORKED per-class output instances,
    # keyed by the source ``DjangoObjectType`` / ``DjangoListObjectType`` class.
    # ``None`` / empty means "no fork" — the DEFAULT pair leaves it empty, so
    # ``resolved_output_type`` falls through to the class-def
    # ``_meta.graphql_output_type`` (byte-identical single-schema path). A
    # NON-default pair populates it via ``compile_outputs_into`` so two schemas
    # over the same model own DISTINCT same-named instances (no graphql-core
    # "uniquely named types" collision).
    output_instances: dict | None = None


def resolved_output_type(cls: Any, registries: Any) -> Any:
    """Return the output "GraphQLObjectType" for "cls" under "registries".

    item-b (B5): the SINGLE choke point that decides whether a read-site sees the
    DEFAULT class-def instance or a FORKED pair-local instance.

    - When "registries" carries a non-empty "output_instances" map AND it holds
      "cls" (a NON-default pair that ran "compile_outputs_into"), return the
      FORKED instance bound to that pair.
    - Otherwise (the default pair, or a class not forked into this pair) return
      the class-def canonical "cls._meta.graphql_output_type" — byte-identical
      to the pre-B5 single-schema behavior.

    Args:
        cls: A "DjangoObjectType" / "DjangoListObjectType" subclass.
        registries: The "SchemaRegistries" pair the current build compiles
            against (None degrades to the class-def instance).

    Returns:
        The pair-appropriate "GraphQLObjectType" (forked or canonical), or
        None when the class has no compiled output type.
    """
    forks = getattr(registries, "output_instances", None) if registries else None
    if forks:
        forked = forks.get(cls)
        if forked is not None:
            return forked
    return getattr(getattr(cls, "_meta", None), "graphql_output_type", None)


# ---------------------------------------------------------------------------
# Forked-build guard (item-b, B5)
# ---------------------------------------------------------------------------
# When a NON-default (forked) ``DjangoGraphQLSchema`` is being built, its relation
# thunks may AUTO-CREATE per-pair ``<Model>ListType`` containers. Those class-def
# blocks unconditionally append to the process-global ``_gdx_output_registry`` and
# (for object types) write to the global shared output registry — leaking
# pair-scoped, often duplicate-named types into the GLOBAL app-ready compile and
# poisoning later default-pair builds. This depth counter is raised for the WHOLE
# forked-build lifetime (compile + root assembly + lazy thunk eval) so those
# class-def blocks SKIP the global registrations: the auto-created types stay in
# their PAIR registry (forked there), never the global namespace. The DEFAULT pair
# never raises it, so the single/default-schema path is byte-identical.
_forking_depth: int = 0


def is_forking() -> bool:
    """Report whether a forked (non-default) schema build is in progress (B5).

    Returns:
        True while the forked-build depth counter is positive, so class-def
        auto-creation of pair-scoped types skips the global registry writes.
    """
    return _forking_depth > 0


class _forking_build:
    """Context manager that marks a forked-schema build in progress (B5).

    Raises _forking_depth for the duration so class-def auto-creation of
    pair-scoped types skips the GLOBAL registry writes. Re-entrant (depth-counted)
    so nested fork operations are safe.
    """

    def __enter__(self) -> "_forking_build":
        global _forking_depth
        _forking_depth += 1
        return self

    def __exit__(self, *exc: Any) -> None:
        global _forking_depth
        _forking_depth -= 1


# Process-wide DEFAULT pair, created once. Its members ARE the existing global
# registries + module-level cache dicts, so defaulting to it changes NOTHING.
_default_schema_registries: SchemaRegistries | None = None


def default_schema_registries() -> SchemaRegistries:
    """Return the process-wide DEFAULT "SchemaRegistries" pair (singleton).

    The default pair's members are the EXISTING global instances:

    - "graphene" = "get_global_registry()"
    - "output" = "get_shared_output_registry()"

    and its four cache fields are the EXISTING module-level cache dicts (bound by
    identity, NOT copied), so every compile entrypoint that defaults to this pair
    reads/writes the same single namespace it always did — byte-identical
    behavior. Lazily built so "base" keeps no import-time dependency on the
    cache-owning modules.

    Returns:
        The single process-wide default "SchemaRegistries" pair.
    """
    global _default_schema_registries
    if _default_schema_registries is None:
        from django_graphex.core.polymorphic_compiler import (
            _INTERFACE_TYPE_CACHE,
            _UNION_TYPE_CACHE,
        )
        from django_graphex.core.schema_compiler import _PLAIN_OBJECT_TYPE_CACHE
        from django_graphex.filtering.native_schema import _NATIVE_INPUT_CACHE
        from django_graphex.registry import get_global_registry

        _default_schema_registries = SchemaRegistries(
            graphene=get_global_registry(),
            output=get_shared_output_registry(),
            plain_object_cache=_PLAIN_OBJECT_TYPE_CACHE,
            union_cache=_UNION_TYPE_CACHE,
            interface_cache=_INTERFACE_TYPE_CACHE,
            filter_input_cache=_NATIVE_INPUT_CACHE,
        )
    return _default_schema_registries


# ---------------------------------------------------------------------------
# InputType base (model-free inputs)
# ---------------------------------------------------------------------------


class InputType(ObjectType):
    """Base class for model-free GraphQL input types.

    Every subclass is automatically registered in "_gdx_input_registry" via
    "__init_subclass__" and compiled by "compile_all_inputs()" at startup.

    Usage:

        from django_graphex.core import InputType

        class SearchInput(InputType):
            query: str
            limit: int = 10
    """

    def __init_subclass__(cls, **kwargs: Any) -> None:
        """Register the subclass and attach its input _meta.

        super().__init_subclass__() runs the ObjectType graphene-free
        driver first (a clean no-op for plain InputType subclasses: no
        Meta, no __init_subclass_with_meta__, no graphene descriptors).
        That driver may seed a NativeObjectTypeOptions _meta; this method
        then OVERWRITES it with the input-specific _GdxInputMeta so the
        existing cls._meta.graphql_input_type flow (populated later by
        compile_all_inputs) is unchanged. The InputType behavior is therefore
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
    """Compile all registered "InputType" subclasses into "GraphQLInputObjectType".

    Called by "DjangoGraphexConfig.ready()" after all app models are loaded.

    Algorithm (two-pass to resolve forward refs deterministically):
    1. "model_rebuild(raise_errors=True)" for every registered class.
       "PydanticUserError(code='model-not-fully-defined')" is re-raised as
       "ImproperlyConfigured" naming the class and the unresolved ref.
    2. "compile_input_type(...)" for every class.
       Duplicate GraphQL names raise "ImproperlyConfigured".

    Raises:
        ImproperlyConfigured: When a class cannot be rebuilt (unresolved forward
            reference) or two classes compile to the same GraphQL input name.
    """
    from django.core.exceptions import ImproperlyConfigured

    from django_graphex.core.input_compiler import compile_input_type

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
