"""Native-path Options classes for django-graphex.

Provides a ``_GdxOptions`` base class and four concrete subclasses that mirror
the graphene ``BaseOptions`` subclasses used in ``types.py``, ``mutation.py``,
and ``subscriptions/subscription.py``, but with zero graphene dependency.

Each Options class stores the class it belongs to (``self.cls``) plus the same
attribute set as its graphene counterpart, all defaulting to ``None`` or the
same empty-collection defaults used in the graphene versions.

``_MetaView`` wraps any ``_GdxOptions`` instance to provide attribute access
that raises ``AttributeError`` (naming the unknown attr) on unknown attributes,
matching the strict-access pattern used by the native backend.
"""

from __future__ import annotations

from typing import Any


# ---------------------------------------------------------------------------
# _GdxOptions — base
# ---------------------------------------------------------------------------


class _GdxOptions:
    """Base class for all native Options containers.

    Stores the class that owns these options as ``self.cls``.  All concrete
    attrs are declared on subclasses and default to ``None`` (or the same
    empty-collection default used by the graphene equivalent).

    Args:
        cls: The class that owns this options container.
    """

    def __init__(self, cls: type) -> None:
        self.cls = cls


# ---------------------------------------------------------------------------
# DjangoObjectOptions — mirrors types.py DjangoObjectOptions
# ---------------------------------------------------------------------------


class DjangoObjectOptions(_GdxOptions):
    """Native options container for ``DjangoObjectType`` / ``DjangoListObjectType``."""

    fields: Any = None
    input_fields: Any = None
    interfaces: tuple = ()
    model: Any = None
    queryset: Any = None
    registry: Any = None
    connection: Any = None
    create_container: Any = None
    results_field_name: Any = None
    filter_fields: tuple = ()
    input_for: Any = None
    max_deep: Any = None
    complexity: Any = None
    gfk_unions: Any = None
    graphql_input_type: Any = None
    graphql_output_type: Any = None

    def __init__(self, cls: type) -> None:
        super().__init__(cls)
        # Initialise every class-level attr as an instance attr so mutations
        # (e.g. ``opts.model = MyModel``) don't bleed into the class.
        self.fields = None
        self.input_fields = None
        self.interfaces = ()
        self.model = None
        self.queryset = None
        self.registry = None
        self.connection = None
        self.create_container = None
        self.results_field_name = None
        self.filter_fields = ()
        self.input_for = None
        self.max_deep = None
        self.complexity = None
        self.gfk_unions = None
        self.graphql_input_type = None
        self.graphql_output_type = None


# ---------------------------------------------------------------------------
# DjangoModelTypeOptions — mirrors types.py DjangoModelTypeOptions
# ---------------------------------------------------------------------------


class DjangoModelTypeOptions(_GdxOptions):
    """Native options container for ``DjangoModelType``."""

    model: Any = None
    queryset: Any = None
    backend: Any = None
    arguments: Any = None
    fields: Any = None
    input_fields: Any = None
    input_field_name: Any = None
    mutation_output: Any = None
    output_field_name: Any = None
    output_type: Any = None
    output_list_type: Any = None
    nested_fields: Any = None
    interfaces: tuple = ()
    stream: Any = None
    serialize_data: Any = None
    subscription_index_fields: tuple = ()
    max_deep: Any = None
    complexity: Any = None

    def __init__(self, cls: type) -> None:
        super().__init__(cls)
        self.model = None
        self.queryset = None
        self.backend = None
        self.arguments = None
        self.fields = None
        self.input_fields = None
        self.input_field_name = None
        self.mutation_output = None
        self.output_field_name = None
        self.output_type = None
        self.output_list_type = None
        self.nested_fields = None
        self.interfaces = ()
        self.stream = None
        self.serialize_data = None
        self.subscription_index_fields = ()
        self.max_deep = None
        self.complexity = None


# ---------------------------------------------------------------------------
# SerializerMutationOptions — mirrors mutation.py SerializerMutationOptions
# ---------------------------------------------------------------------------


class SerializerMutationOptions(_GdxOptions):
    """Native options container for ``DjangoModelMutation``."""

    fields: Any = None
    input_fields: Any = None
    interfaces: tuple = ()
    backend: Any = None
    action: Any = None
    arguments: Any = None
    output: Any = None
    resolver: Any = None
    nested_fields: Any = None
    model_operations: tuple = ("create", "update", "delete")

    def __init__(self, cls: type) -> None:
        super().__init__(cls)
        self.fields = None
        self.input_fields = None
        self.interfaces = ()
        self.backend = None
        self.action = None
        self.arguments = None
        self.output = None
        self.resolver = None
        self.nested_fields = None
        self.model_operations = ("create", "update", "delete")


# ---------------------------------------------------------------------------
# SubscriptionOptions — mirrors subscriptions/subscription.py SubscriptionOptions
# ---------------------------------------------------------------------------


class SubscriptionOptions(_GdxOptions):
    """Native options container for ``Subscription``."""

    output: Any = None
    arguments: Any = None
    model: Any = None
    stream: Any = None
    backend: Any = None
    queryset: Any = None
    serialize_data: Any = None
    index_fields: tuple = ()

    def __init__(self, cls: type) -> None:
        super().__init__(cls)
        self.output = None
        self.arguments = None
        self.model = None
        self.stream = None
        self.backend = None
        self.queryset = None
        self.serialize_data = None
        self.index_fields = ()


# ---------------------------------------------------------------------------
# _MetaView — strict attribute proxy
# ---------------------------------------------------------------------------


class _MetaView:
    """Strict attribute proxy over a ``_GdxOptions`` instance.

    Delegates attribute access to the wrapped Options object for every attr
    that exists on the Options instance.  Raises ``AttributeError`` (naming the
    unknown attribute) for any attr that does not exist on the wrapped object.

    This mirrors the strict-access guarantee that graphene's ``BaseOptions``
    provides via its ``__setattr__`` check, but for the native path.

    Args:
        opts: A ``_GdxOptions`` (or subclass) instance.
    """

    __slots__ = ("_opts",)

    def __init__(self, opts: _GdxOptions) -> None:
        object.__setattr__(self, "_opts", opts)

    def __getattr__(self, name: str) -> Any:
        opts = object.__getattribute__(self, "_opts")
        try:
            return getattr(opts, name)
        except AttributeError:
            raise AttributeError(
                f"_MetaView: unknown attribute {name!r} on "
                f"{type(opts).__name__!r}. "
                f"Check the Options class definition for declared attrs."
            ) from None

    def __setattr__(self, name: str, value: Any) -> None:
        opts = object.__getattribute__(self, "_opts")
        setattr(opts, name, value)
