"""Security middlewares: disable introspection and enforce field-level auth."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Callable

from graphql import GraphQLError

from .settings import graphql_api_settings

if TYPE_CHECKING:
    from graphql import GraphQLResolveInfo

__all__ = ("DisableIntrospectionMiddleware", "AuthenticatedFieldsMiddleware")

#: GraphQL meta-fields that perform schema introspection.
_INTROSPECTION_FIELDS = ("__schema", "__type")


class DisableIntrospectionMiddleware:
    """Block schema introspection ("__schema" / "__type") unless allowed.

    Introspection is allowed when the
    "DJANGO_GRAPHEX['ALLOW_INTROSPECTION']" setting is truthy, or (when
    "INTROSPECTION_ALLOW_SUPERUSER" is on) the request user is a superuser. The
    "__typename" field is never affected.
    """

    def resolve(
        self, next: Callable, root: Any, info: GraphQLResolveInfo, **kwargs: Any
    ) -> Any:
        """Raise on introspection fields when introspection is not allowed.

        Args:
            next: The next resolver in the middleware chain.
            root: The root value passed to the resolver.
            info: The GraphQL resolve info for the current field.
            **kwargs: Arguments forwarded to the next resolver.

        Returns:
            The result of the next resolver.

        Raises:
            GraphQLError: If an introspection field is requested while
                introspection is disabled.
        """
        if info.field_name in _INTROSPECTION_FIELDS and not self._allowed(info):
            raise GraphQLError(
                "GraphQL introspection is disabled.",
                extensions={"code": "INTROSPECTION_DISABLED", "status_code": 403},
            )
        return next(root, info, **kwargs)

    @staticmethod
    def _allowed(info: GraphQLResolveInfo) -> bool:
        """Return whether introspection is permitted for this request."""
        if graphql_api_settings.ALLOW_INTROSPECTION:
            return True
        if graphql_api_settings.INTROSPECTION_ALLOW_SUPERUSER:
            user = getattr(getattr(info, "context", None), "user", None)
            return bool(getattr(user, "is_superuser", False))
        return False


class AuthenticatedFieldsMiddleware:
    """Require an authenticated user on the schema's private top-level fields.

    The protected field set comes from (in order):

    1. the native schema extensions
       ("info.schema.extensions['gdx_protected_fields']", set by
       "DjangoGraphQLSchema"), or
    2. the legacy registry attribute attached by "DjangoGraphQLSchema"
       (the "info.schema._gde_protected_fields" attribute), or
    3. the "DJANGO_GRAPHEX['PROTECTED_FIELDS']" setting.

    Nothing is protected unless declared. Override "get_protected_fields" /
    "get_error_extensions" to source the field set differently or to enrich
    the error.
    """

    def resolve(
        self, next: Callable, root: Any, info: GraphQLResolveInfo, **kwargs: Any
    ) -> Any:
        """Gate private top-level fields on an authenticated user.

        Args:
            next: The next resolver in the middleware chain.
            root: The root value passed to the resolver.
            info: The GraphQL resolve info for the current field.
            **kwargs: Arguments forwarded to the next resolver.

        Returns:
            The result of the next resolver.

        Raises:
            GraphQLError: If a protected top-level field is requested without
                an authenticated user.
        """
        # Only enforce at the top level; nested fields have a non-None root.
        if root is not None:
            return next(root, info, **kwargs)

        if info.field_name not in self.get_protected_fields(info):
            return next(root, info, **kwargs)

        user = getattr(getattr(info, "context", None), "user", None)
        # `is_authenticated` is a bool property on modern Django (never called).
        if user is None or not user.is_authenticated:
            raise GraphQLError(
                "Authentication required.",
                extensions=self.get_error_extensions(info, user),
            )
        return next(root, info, **kwargs)

    def get_protected_fields(self, info: GraphQLResolveInfo) -> Any:
        """Return the set of protected top-level field names for this request.

        Resolves the protected-field set from the first available source: the
        native schema extensions, then the legacy schema attribute, then the
        "PROTECTED_FIELDS" setting (see the class docstring for the order).

        Args:
            info: The GraphQL resolve info for the current field.

        Returns:
            The collection of protected top-level field names (a set/frozenset).
        """
        schema = getattr(info, "schema", None)
        # 1) Native canonical location: schema.extensions['gdx_protected_fields'].
        extensions = getattr(schema, "extensions", None) or {}
        from_extensions = extensions.get("gdx_protected_fields")
        if from_extensions is not None:
            return from_extensions
        # 2) Legacy attribute (graphene path / dual-backend fallback).
        attached = getattr(schema, "_gde_protected_fields", None)
        if attached is not None:
            return attached
        # 3) Settings fallback.
        return set(graphql_api_settings.PROTECTED_FIELDS or ())

    def get_error_extensions(
        self, info: GraphQLResolveInfo, user: Any
    ) -> dict[str, Any]:
        """Return the GraphQL error "extensions" for an auth failure.

        Override this to enrich the authentication-error payload (for example
        to add a hint or a login URL).

        Args:
            info: The GraphQL resolve info for the current field.
            user: The (missing or unauthenticated) request user.

        Returns:
            The "extensions" mapping attached to the raised "GraphQLError".
        """
        return {"code": "UNAUTHENTICATED", "status_code": 401}
