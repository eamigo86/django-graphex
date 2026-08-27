"""Registry for GraphQL types and directives.

This module provides a central registry for managing GraphQL types,
input types, and directives in the django-graphex package.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from django.db.models import Model


class Registry:
    """Custom registry for DjangoObjectType and DjangoInputObjectType.

    Provide a central store for GraphQL types, input types, enums, and
    directives used across the django-graphex package.

    Types are keyed by the **model class** (and input action), not by a derived
    string name, so models that share a class name across Django apps -- or a
    model whose name overlaps a list/input/enum suffix -- never collide.
    """

    def __init__(self) -> None:
        """Initialize empty registry stores.

        Creates the separate keyed stores for object/input types, list types,
        enums, directives, unions and interfaces.
        """
        #: (model, for_input) -> object/input type. ``for_input`` is None for
        #: output types, else the action key ("create"/"update"/"delete").
        self._types: dict[tuple[type[Model], str | None], Any] = {}
        #: model -> canonical DjangoListObjectType.
        self._list_types: dict[type[Model], Any] = {}
        #: enum name -> enum type (its own namespace; never clashes with types).
        self._enums: dict[str, Any] = {}
        self._registry_directives: dict[str, Any] = {}
        #: GraphQL type name -> DjangoUnionType subclass. Parallel to ``_types``
        #: (which is (model, for_input)-keyed); a union has no single model so it
        #: cannot live in ``_types`` without breaking that invariant.
        self._union_types: dict[str, Any] = {}
        #: GraphQL type name -> DjangoInterfaceType subclass. Implementors are
        #: NOT stored alongside it: ``get_member_models`` derives them from
        #: ``_types`` on demand, so a second store could only go stale.
        self._interface_types: dict[str, Any] = {}
        #: child_model -> every host class declared for it IN THIS REGISTRY, in
        #: declaration order. It drives the nested projection merge, the nested
        #: permission stamp, the write-time row scoping and the write-time
        #: authorize loop, so it has to die with the registry exactly like the
        #: two memos below: a host bound to a second registry through
        #: ``Meta.registry`` describes THAT schema's surface, and must not
        #: rewrite this one's.
        #:
        #: A LIST, not a last-wins slot, so two hosts for one model fail CLOSED:
        #: every declared host must allow a nested write. A last-wins slot would
        #: let a permissive sibling shadow a restrictive one, which is the
        #: failure mode the model-keyed field registry
        #: (``_NATIVE_FIELD_REGISTRY``) already documents.
        self.nested_hosts: dict[Any, list[Any]] = {}
        #: (child_model, op, parent_model) -> the child's input type as built for
        #: THAT parent's nested surface. Lives here, not in a module global, so
        #: it dies with the registry; the memo is load-bearing, since two parents
        #: nesting one child (or one parent's create and update) must not mint
        #: two identically named types.
        self.nested_input_cache: dict[tuple, Any] = {}
        #: child_model -> the parent models its nested input has been built for
        #: IN THIS REGISTRY. Read only to refuse a host declared too late to
        #: reach that surface (see ``nested.register_nested_host``), never to
        #: change what gets built. Lives beside the memo it shadows, and dies
        #: with it: a second registry has frozen nothing, so a host bound to one
        #: through ``Meta.registry`` must not be refused for the first's build.
        self.nested_materialized: dict[Any, list[Any]] = {}
        #: (model, op, projection signature) -> the input type a host declaring
        #: THAT projection uses. The shared ``(model, op)`` slot below holds one
        #: input per model, so a projection declared behind an already-registered
        #: host was silently dropped and its root accepted every writable column;
        #: a projected input therefore gets its own memoized type instead (see
        #: ``mutation.generic_input_type``). Keyed by the projection so two hosts
        #: declaring the same one SHARE a type rather than minting two under one
        #: name, which graphql-core refuses.
        self.projected_input_cache: dict[tuple, Any] = {}
        #: Companion NativeOutputRegistry holding this registry's compiled output
        #: nodes (get_compiled/set_compiled), keyed by model. Lazily created by
        #: output_registry(). For the global registry this is bound to the
        #: process-wide shared singleton so global stamping stays byte-identical;
        #: a local (Meta.registry) registry gets its own, so its compiled nodes
        #: never leak into the global namespace.
        self._output_registry: Any = None

    def output_registry(self) -> Any:
        """Return this registry's companion NativeOutputRegistry.

        The companion stores the compiled GraphQLObjectType per model
        (get_compiled/set_compiled) for the types registered here, so a relation
        thunk of one type resolves a sibling type within the same registry
        without stamping the process-global shared registry.

        For the global registry (get_global_registry) the companion is the
        process-wide shared singleton (get_shared_output_registry), so the
        default/production path is byte-identical: every global-registry class
        continues to stamp and read that one shared registry. A local registry
        (declared via Meta.registry) gets its own companion, keeping its compiled
        nodes schema-scoped and out of the global slot (the leak fix).

        Returns:
            registry: The companion NativeOutputRegistry for this registry.
        """
        from django_graphex.core.base import get_shared_output_registry

        # The GLOBAL registry's companion is the shared singleton (byte-identical).
        if self is get_global_registry():
            return get_shared_output_registry()

        if self._output_registry is None:
            from django_graphex.core.registry_compiler import NativeOutputRegistry

            self._output_registry = NativeOutputRegistry()
        return self._output_registry

    def register_enum(self, key: str, enum: Any) -> None:
        """Register an enum type with the given key.

        Args:
            key: registry key under which to store the enum.
            enum: enum type to register.
        """
        self._enums[key] = enum

    def get_type_for_enum(self, key: str) -> Any | None:
        """Return the enum type registered for the given key.

        Args:
            key: registry key to look up.

        Returns:
            The registered enum type, or None if absent.
        """
        return self._enums.get(key)

    def register_directive(self, name: str, directive: Any) -> None:
        """Register a directive with the given name.

        Args:
            name: name under which to store the directive.
            directive: directive instance to register.
        """
        self._registry_directives[name] = directive

    def get_directive(self, name: str) -> Any | None:
        """Return the directive registered for the given name.

        Args:
            name: directive name to look up.

        Returns:
            The registered directive, or None if absent.
        """
        return self._registry_directives.get(name)

    def register(self, cls: Any, for_input: str | None = None) -> None:
        """Register a Django model GraphQL type or input type.

        Args:
            cls: the DjangoObjectType or DjangoInputObjectType to register.
            for_input: input action key, or None for an output type.

        Raises:
            TypeError: if "cls" is not a DjangoObjectType/DjangoInputObjectType.
            ValueError: if the type's registry does not match this instance.
        """
        from .types import (
            DjangoInputObjectType,
            DjangoInterfaceType,
            DjangoObjectType,
            DjangoUnionType,
        )

        # Polymorphic bases have no single (model, for_input) key; route them to
        # their parallel stores and return BEFORE the _types write so the
        # (model, for_input) invariant of ``_types`` is preserved.
        if isinstance(cls, type) and issubclass(
            cls, (DjangoUnionType, DjangoInterfaceType)
        ):
            return self.register_polymorphic(cls)

        if not issubclass(cls, (DjangoInputObjectType, DjangoObjectType)):
            raise TypeError(
                "Only DjangoInputObjectType or DjangoObjectType can be "
                'registered, received "{}"'.format(cls.__name__)
            )
        if cls._meta.registry is not self:
            raise ValueError("Registry for a Model must match.")

        if not getattr(cls._meta, "skip_registry", False):
            self._types[(cls._meta.model, for_input)] = cls

    def get_type_for_model(
        self, model: type[Model], for_input: str | None = None
    ) -> Any | None:
        """Return the GraphQL type registered for the given Django model.

        Args:
            model: Django model class to look up.
            for_input: input action key, or None for an output type.

        Returns:
            The registered GraphQL type, or None if absent.
        """
        return self._types.get((model, for_input))

    # -- polymorphic (union / interface) types ----------------------------- #
    def register_polymorphic(self, cls: Any) -> None:
        """Register a DjangoUnionType or DjangoInterfaceType by its name.

        Routes a union to "_union_types" and an interface to
        "_interface_types", keyed by "cls._meta.name" (set by graphene's
        "__init_subclass_with_meta__"). Never writes "_types".

        Idempotent by construction: a same-name re-registration overwrites the
        existing entry harmlessly. Both the auto-registration in the base's
        "__init_subclass_with_meta__" and a manual "register()" land here, so
        the second is a benign overwrite.

        Args:
            cls: the polymorphic type to register.

        Raises:
            ValueError: if "cls" is bound to a different registry. This mirrors
                the object-type "register()" guard so a union/interface built
                in registry A cannot be silently registered into registry B
                (which would leave its "resolve_type" consulting A's "_types").
            TypeError: if "cls" is neither a DjangoUnionType nor a
                DjangoInterfaceType, so direct misuse fails loud instead of
                silently dropping the class from every store.
        """
        from .types import DjangoInterfaceType, DjangoUnionType

        # Mirror the object-type registry-match guard (see ``register`` above):
        # a polymorphic type bound to another registry must not be written here,
        # otherwise its ``resolve_type`` would consult the wrong ``_types``.
        bound_registry = getattr(cls, "_dgx_registry", None)
        if bound_registry is not None and bound_registry is not self:
            raise ValueError("Registry for a polymorphic type must match.")

        name = cls._meta.name
        if issubclass(cls, DjangoUnionType):
            self._union_types[name] = cls
        elif issubclass(cls, DjangoInterfaceType):
            self._interface_types[name] = cls
        else:
            raise TypeError(
                "register_polymorphic expects a DjangoUnionType or "
                "DjangoInterfaceType, received {!r}.".format(cls.__name__)
            )

    def get_model_for_type_name(self, name: str) -> type[Model] | None:
        """Resolve a GraphQL output-type name to its Django model.

        Reverse-scans "_types" for the OUTPUT entry ("for_input" is None)
        whose value's "_meta.name" matches; input entries and the polymorphic
        stores are ignored so a union name never resolves to a member model.

        Args:
            name: the GraphQL type name to resolve.

        Returns:
            The Django model class, or None if no output type matches.
        """
        for (model, for_input), cls in self._types.items():
            if for_input is None and getattr(cls._meta, "name", None) == name:
                return model
        return None

    def get_member_models(self, polymorphic_type: Any) -> list[type[Model]]:
        """Return the ordered member models of a union or interface.

        For a union: the explicitly enumerated "_dgx_member_models" (stable
        order, never derived from ContentType rows).
        For an interface: the models of every registered output DjangoObjectType
        whose "Meta.interfaces" includes this interface. This is a PURE QUERY
        HELPER with no MVP runtime consumer — it is only meaningful once the
        schema is fully built and all implementors are registered.

        Args:
            polymorphic_type: a DjangoUnionType or DjangoInterfaceType subclass.

        Returns:
            The list of member/implementor models.
        """
        from .types import DjangoUnionType

        if isinstance(polymorphic_type, type) and issubclass(
            polymorphic_type, DjangoUnionType
        ):
            return list(getattr(polymorphic_type, "_dgx_member_models", ()))

        implementors: list[type[Model]] = []
        for (model, for_input), cls in self._types.items():
            if for_input is not None:
                continue
            interfaces = getattr(cls._meta, "interfaces", ()) or ()
            if polymorphic_type in interfaces:
                implementors.append(model)
        return implementors

    def get_gfk_union(self, model: type[Model], fk_name: str) -> Any | None:
        """Return the companion DjangoUnionType for a model's GFK, if declared.

        Looks up the registered OUTPUT DjangoObjectType for "model" and reads
        "_meta.unions.get(fk_name)". The returned union must itself be
        registered (its name present in "_union_types"); a union referenced by
        an owning type's Meta but absent from the registry (mis-ordered
        declaration) yields None so the caller can warn and fall back.

        Args:
            model: the GFK-owning Django model.
            fk_name: the GenericForeignKey field name.

        Returns:
            The registered companion union, or None.
        """
        owner = self.get_type_for_model(model)
        if owner is None:
            return None
        unions = getattr(owner._meta, "unions", None) or {}
        union = unions.get(fk_name)
        if union is None:
            return None
        if getattr(union._meta, "name", None) not in self._union_types:
            return None
        return union

    # -- list (object) types: one canonical "list" entry per model --------- #
    def register_list_type(self, model: type[Model], cls: Any) -> None:
        """Register the canonical "DjangoListObjectType" for a model.

        Mirror the per-(model, action) scheme of the node/input types: one entry
        per model (last registration wins).

        Args:
            model: Django model class the list type describes.
            cls: the DjangoListObjectType to register.
        """
        self._list_types[model] = cls

    def get_list_type_for_model(self, model: type[Model]) -> Any | None:
        """Return the registered "DjangoListObjectType" for a model.

        Args:
            model: Django model class to look up.

        Returns:
            The registered list type, or None if absent.
        """
        return self._list_types.get(model)


registry = None


def get_global_registry() -> Registry:
    """Return the global registry instance, creating it if necessary.

    Returns:
        The shared global registry instance.
    """
    global registry
    if not registry:
        registry = Registry()
    return registry
