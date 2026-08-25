"""Serializer backend: the seam between the GraphQL types and validation/persistence.

"DjangoModelType" / "DjangoModelMutation" / "Subscription" don't
validate or persist directly; they go through a "SerializerBackend". The
package ships a single "PydanticBackend"
(selected by "Meta.model"); the abstraction keeps a clean seam and allows custom
backends.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from django.db.models import Model
    from graphql import GraphQLResolveInfo


class SerializerBackend:
    """Validate/persist/serialize one object for a model-backed type.

    A backend owns the *runtime* work (validation, create/update, output
    serialization); the GraphQL schema itself is built from the Django model by
    the converter, independent of any backend.
    """

    def get_model(self) -> type[Model]:
        """Return the Django model this backend writes.

        Returns:
            The Django model class this backend validates and persists.
        """
        raise NotImplementedError

    def save_object(
        self,
        host: Any,
        root: Any,
        info: GraphQLResolveInfo,
        data: dict[str, Any],
        *,
        instance: Model | None = None,
        partial: bool = False,
        serializer_kwargs: dict[str, Any] | None = None,
        save_kwargs: dict[str, Any] | None = None,
    ) -> tuple[bool, Any]:
        """Validate "data" and create/update a single object.

        Args:
            host: The owning type/mutation class.
            root: Root value passed to the resolver.
            info: GraphQL resolve info for the current request.
            data: The input data for this object.
            instance: Existing instance for an update, or None to create.
            partial: Whether this is a partial (update) write.
            serializer_kwargs: Reserved for backend-specific build options.
            save_kwargs: Attributes injected at save time (e.g. a reverse FK).

        Returns:
            "(True, instance)" or "(False, errors)" where "errors" is a
            list of "ErrorType" with flat field names (callers prefix nested
            fields).
        """
        raise NotImplementedError

    def to_representation(self, instance: Model) -> dict[str, Any]:
        """Serialize an instance to a plain dict (subscriptions output).

        Args:
            instance: The model instance to serialize.

        Returns:
            The instance serialized as a plain dict of output field values.
        """
        raise NotImplementedError

    def output_field_names(self) -> list[str]:
        """Return the field names that appear in "to_representation".

        Used to build a subscription's "<Model>Fields" enum (the "data"
        argument) when notifications carry the full serialized instance.

        Returns:
            The list of output field names.
        """
        raise NotImplementedError


#: Model -> the backend of the last host that declared CUSTOM validation, that
#: is inline "validate_*" methods or a "Meta.pydantic_model" (both reach
#: "resolve_backend" as a non-None "pydantic_model"). "backend_for_nested"
#: consults it so a nested write validates a child with the SAME rules the
#: child's own mutation applies; without it the nested path validated from the
#: child MODEL alone and the child type's rules never ran.
#:
#: A host with no custom validation is NOT recorded, so a plain child keeps the
#: previous path unchanged. Two hosts declaring custom validation for the SAME
#: model resolve last-defined-wins, matching every other model-keyed registry in
#: the package.
_VALIDATED_BACKENDS: dict[Any, SerializerBackend] = {}


def resolve_backend(
    model: Any | None = None,
    *,
    pydantic_model: Any | None = None,
) -> SerializerBackend:
    """Build the serializer backend for a type's "Meta.model".

    A backend carrying custom validation is also recorded under its model so
    "backend_for_nested" can reuse it, keeping a nested write and the child's
    own mutation on one validator.

    Args:
        model: The "Meta.model" the type is backed by.
        pydantic_model: Optional user Pydantic base carrying custom validators.

    Returns:
        A configured "SerializerBackend".

    Raises:
        ImproperlyConfigured: If no "model" is given.
    """
    from django.core.exceptions import ImproperlyConfigured

    if model is None:
        raise ImproperlyConfigured("A Meta.model is required.")

    from .core.backend import PydanticBackend

    backend = PydanticBackend(model, pydantic_model)
    if pydantic_model is not None:
        _VALIDATED_BACKENDS[model] = backend
    return backend


def backend_for_nested(spec: Any) -> SerializerBackend:
    """Resolve the backend for a "Meta.nested_fields" child spec.

    When a host for the child model declared custom validation (inline
    "validate_*" methods or a "Meta.pydantic_model"), its backend is reused so
    the nested write runs the child's own rules instead of validating from the
    bare model.

    Args:
        spec: The nested-field value — a Django model class.

    Returns:
        A configured "SerializerBackend" for the child.

    Raises:
        ImproperlyConfigured: If "spec" is not a Django model class.
    """
    from django.core.exceptions import ImproperlyConfigured
    from django.db.models import Model

    if not (isinstance(spec, type) and issubclass(spec, Model)):
        raise ImproperlyConfigured(
            f"nested_fields values must be Django model classes, received {spec!r}."
        )

    validated = _VALIDATED_BACKENDS.get(spec)
    if validated is not None:
        return validated

    from .core.backend import PydanticBackend

    return PydanticBackend(spec)
