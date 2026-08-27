"""Security middlewares: disable introspection and enforce field-level auth."""

from __future__ import annotations

import re
from typing import TYPE_CHECKING, Any, Callable

from graphql import GraphQLError

from .settings import graphql_api_settings

if TYPE_CHECKING:
    from graphql import GraphQLResolveInfo

__all__ = (
    "DisableIntrospectionMiddleware",
    "AuthenticatedFieldsMiddleware",
    "introspection_disabled",
    "format_graphql_error",
)

#: GraphQL meta-fields that perform schema introspection.
_INTROSPECTION_FIELDS = ("__schema", "__type")

#: Message prefixes graphql-core writes immediately before a suggestion built
#: from SCHEMA members - the only messages whose trailing "Did you mean ...?"
#: is an oracle. A validation error carries no rule identifier (the rules
#: construct a bare "GraphQLError(message, node)", so "extensions" is empty and
#: the node type does not discriminate - "FieldsOnCorrectTypeRule" and
#: "ScalarLeafsRule" both report on a "FieldNode"), which leaves the message
#: prefix as the only thing that names the emitting rule.
#:
#: Deliberately ABSENT: "ScalarLeafsRule", whose "Did you mean 'x { ... }'?" is
#: built from the field name the client already typed, and any resolver-raised
#: application error that happens to end in a question. Neither names a schema
#: member, and a strip keyed on the SHAPE of the sentence destroys both.
_SCHEMA_ORACLE_PREFIXES = (
    # FieldsOnCorrectTypeRule - suggests sibling field names and type names.
    r"Cannot query field '[^']*' on type '[^']*'\.",
    # KnownTypeNamesRule - suggests type names.
    r"Unknown type '[^']*'\.",
    # KnownArgumentNamesRule / KnownArgumentNamesOnDirectivesRule.
    r"Unknown argument '[^']*' on (?:field|directive) '[^']*'\.",
    # ValuesOfCorrectTypeRule and coerce_input_value - suggest input fields.
    r"Field '[^']*' is not defined by type '[^']*'\.",
    # GraphQLEnumType.parse_value / parse_literal - suggest enum members.
    r"Value '[^']*' does not exist in '[^']*' enum\.",
    r"Enum '[^']*' cannot represent non-(?:string|enum) value: .*?",
)

#: The coercion wrapper "coerce_variable_values" puts in FRONT of a rule's own
#: message when the bad value arrived through a variable rather than inline:
#: "Variable '$input' got invalid value {...}; Field 'nam' is not defined by
#: type 'UserInput'. Did you mean 'name'?". Anchoring the rule prefixes at the
#: start of the string made the strip a no-op on that whole path, which is where
#: two of the prefixes above are reached in practice.
_COERCION_WRAPPER = r"(?:Variable '\$[^']*' got invalid value .*?; )?"

#: The schema-derived suggestion sentence, and only that. Anchored at BOTH ends:
#: at the start on the rules above (behind the optional coercion wrapper), and at
#: the end because "did_you_mean" is concatenated last and nothing is ever
#: written after it - so prose following the sentence proves the message did not
#: come from these rules. Group 1 spans everything before the suggestion, so the
#: substitution keeps the wrapper and the rule's own message intact.
_SUGGESTION_RE = re.compile(
    "^("
    + _COERCION_WRAPPER
    + "(?:"
    + "|".join(_SCHEMA_ORACLE_PREFIXES)
    + r"))\s+Did you mean .*\?$"
)


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
            # A DEACTIVATED superuser keeps no privilege: authentication
            # backends that skip "user_can_authenticate" (token / JWT) can put
            # an inactive user on the request.
            return bool(
                getattr(user, "is_active", False)
                and getattr(user, "is_superuser", False)
            )
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
        # Only enforce at the top level, read from the RESOLVE PATH: a
        # top-level field has no previous path segment. "root" is not a valid
        # proxy for depth — "root_value" is a public seam (a "GraphQLView"
        # kwarg / "get_root_value") and the subscription delivery pass feeds
        # the event payload in as the root. An unreadable path is treated as
        # top level, so the gate fails closed.
        if getattr(getattr(info, "path", None), "prev", None) is not None:
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


def introspection_disabled(middleware: Any = None) -> bool:
    """Return whether a surface running this middleware chain really hides the schema.

    Both halves are needed. "ALLOW_INTROSPECTION" is False by DEFAULT, but it is
    inert on its own: nothing enforces it until "DisableIntrospectionMiddleware"
    is in the execution chain. Reading the setting alone would treat every stock
    project as locked down.

    The verdict is deliberately request-independent, so the superuser bypass
    ("INTROSPECTION_ALLOW_SUPERUSER") does NOT count as introspection being
    open: an HTTP error body is stored in the response cache, and a per-user
    verdict there would serve one caller's body to another.

    Args:
        middleware: The chain to inspect - a "MiddlewareManager", a plain list
            of instances or classes, or None to read
            "DJANGO_GRAPHEX['MIDDLEWARE']". The subscription transports build
            their chain from that setting, so None is exact for them.

    Returns:
        True when the middleware is installed and the setting withholds
        introspection.
    """
    if graphql_api_settings.ALLOW_INTROSPECTION:
        return False
    if middleware is None:
        middleware = graphql_api_settings.MIDDLEWARE
    # A MiddlewareManager keeps the chain under "middlewares"; a plain list IS
    # the chain. Entries are normally instances, but "MIDDLEWARE" is an
    # IMPORT_STRINGS key, so the setting hands back the resolved CLASSES and a
    # manager built by the caller may hold classes too.
    chain = getattr(middleware, "middlewares", middleware) or ()
    return any(
        issubclass(entry, DisableIntrospectionMiddleware)
        if isinstance(entry, type)
        else isinstance(entry, DisableIntrospectionMiddleware)
        for entry in chain
    )


def format_graphql_error(error: Any, middleware: Any = None) -> dict:
    """Format one error for a response / frame, stripping the schema oracle.

    Single source of the wire shape for the HTTP view AND both subscription
    transports: a "GraphQLError" is serialized via its "formatted" mapping, any
    other exception is wrapped as a "{'message': str(error)}" entry.

    When introspection is actually disabled (see "introspection_disabled") the
    trailing "Did you mean ...?" suggestion is removed from the messages listed
    in "_SCHEMA_ORACLE_PREFIXES": those name real schema members, so probing
    with invented names rebuilds much of the schema the operator meant to hide.
    Nothing else is touched - the rest of the message, "locations" and "path"
    all survive, and a message that merely ENDS that way (ScalarLeafsRule's
    guidance, a resolver-raised application error) keeps every word.

    Args:
        error: The error (or exception) to format.
        middleware: The chain the surface runs, forwarded to
            "introspection_disabled"; None reads the setting.

    Returns:
        The error mapping suitable for a response "errors" list or a transport
        error frame.
    """
    formatted: dict[str, Any] = (
        dict(error.formatted)
        if isinstance(error, GraphQLError)
        else {"message": str(error)}
    )
    if not introspection_disabled(middleware):
        return formatted
    # Group 1 is the rule's own message, so the result is never empty.
    formatted["message"] = _SUGGESTION_RE.sub(r"\1", str(formatted.get("message", "")))
    return formatted
