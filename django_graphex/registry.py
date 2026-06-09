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
        """Initialize empty registry stores."""
        #: (model, for_input) -> object/input type. ``for_input`` is None for
        #: output types, else the action key ("create"/"update"/"delete").
        self._types: dict[tuple[type[Model], str | None], Any] = {}
        #: model -> canonical DjangoListObjectType.
        self._list_types: dict[type[Model], Any] = {}
        #: enum name -> enum type (its own namespace; never clashes with types).
        self._enums: dict[str, Any] = {}
        self._registry_directives: dict[str, Any] = {}

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
        from .types import DjangoInputObjectType, DjangoObjectType

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


def reset_global_registry() -> None:
    """Reset the global registry to None."""
    global registry
    registry = None
