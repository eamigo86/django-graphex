"""Schema helpers for field-level authorization.

"ExtraGraphQLSchema" lets you declare which top-level fields are private
right where the schema is built ("private_query" / "private_mutation" /
"private_subscription"). It computes the set of protected field names once and
attaches it to the underlying graphql-core schema, where the
"AuthenticatedFieldsMiddleware" reads it at resolve time via "info.schema".
"""

from __future__ import annotations

import warnings
from typing import TYPE_CHECKING, Any

import graphene
from django.conf import settings
from graphene.utils.str_converters import to_camel_case

if TYPE_CHECKING:
    from graphene import ObjectType

__all__ = ("collect_field_names", "DenyAllRegistry", "ExtraGraphQLSchema")


def collect_field_names(
    *object_types: type[ObjectType] | None, camelcase: bool = True
) -> frozenset[str]:
    """Return the (camelCased) field names declared on the given ObjectTypes.

    Names are taken from "ObjectType._meta.fields" and camelCased to match
    "info.field_name" under the default "auto_camelcase=True".

    Args:
        *object_types: The graphene ObjectTypes to collect field names from.
        camelcase: Whether to camelCase the collected field names.

    Returns:
        The set of collected field names.
    """
    names = set()
    for object_type in object_types:
        if object_type is None:
            continue
        fields = getattr(getattr(object_type, "_meta", None), "fields", None) or {}
        for key in fields:
            names.add(to_camel_case(key) if camelcase else key)
    return frozenset(names)


class DenyAllRegistry(frozenset):
    """Fail-closed sentinel whose "__contains__" returns True for everything.

    Use it from a subclassed "get_protected_fields" when the schema/registry
    cannot be built, so a broken schema fails closed (every field requires
    auth) instead of open.
    """

    def __contains__(self, item: Any) -> bool:
        """Treat every field as protected."""
        return True

    def __repr__(self) -> str:
        """Return a readable marker for logs/tests."""
        return "DenyAllRegistry(*)"


def _auth_middleware_configured() -> bool:
    """Check that the AuthenticatedFieldsMiddleware is in the GRAPHENE config.

    This is a best-effort check.
    """
    graphene_conf = getattr(settings, "GRAPHENE", None) or {}
    for entry in graphene_conf.get("MIDDLEWARE", []) or []:
        name = entry if isinstance(entry, str) else getattr(entry, "__name__", "")
        if "AuthenticatedFieldsMiddleware" in name:
            return True
    return False


class ExtraGraphQLSchema(graphene.Schema):
    """A "graphene.Schema" that records private fields for the auth middleware.

    Each ``private_*`` ObjectType is **unioned** into its root, so you can keep
    public and private fields in separate roots and the schema exposes the union
    while the private fields require authentication. Nothing is protected unless
    declared in a ``private_*`` root.

    - "private_query" / "private_mutation" / "private_subscription": their
      fields are merged into the corresponding root and require authentication::

          # disjoint public / private roots -> the schema exposes the union
          ExtraGraphQLSchema(
              query=PublicQuery, private_query=PrivateQuery,
              subscription=PublicSubs, private_subscription=PrivateSubs,
          )

      Passing a single full root plus a ``private_*`` marker subset (the field
      names to protect) also works unchanged.
    """

    def __init__(
        self,
        *args,
        private_query: type[ObjectType] | None = None,
        private_mutation: type[ObjectType] | None = None,
        private_subscription: type[ObjectType] | None = None,
        **kwargs,
    ) -> None:
        """Build the schema and attach the protected-field registry.

        The public root and its ``private_*`` counterpart are **unioned** into
        the actual schema root, so callers may pass disjoint public/private roots
        (each app contributes a public and a private subset; the private subset
        both *defines* and *protects* its fields). Passing a single full root
        plus a ``private_*`` marker subset still works unchanged.

        Args:
            *args: Positional arguments forwarded to "graphene.Schema" (a single
                positional is treated as the ``query`` root).
            private_query: An ObjectType whose fields require authentication.
            private_mutation: An ObjectType whose fields require authentication.
            private_subscription: An ObjectType whose fields require
                authentication.
            **kwargs: Keyword arguments forwarded to "graphene.Schema".
        """
        query = kwargs.pop("query", None)
        mutation = kwargs.pop("mutation", None)
        subscription = kwargs.pop("subscription", None)
        if args and query is None:  # support the Schema(Query, ...) positional idiom
            query, args = args[0], args[1:]

        query = self._merge_root("Query", query, private_query)
        mutation = self._merge_root("Mutation", mutation, private_mutation)
        subscription = self._merge_root(
            "Subscription", subscription, private_subscription
        )

        super().__init__(
            *args,
            query=query,
            mutation=mutation,
            subscription=subscription,
            **kwargs,
        )

        protected = (
            collect_field_names(private_query)
            | collect_field_names(private_mutation)
            | collect_field_names(private_subscription)
        )

        # Attached to the graphql-core schema; read by the middleware as
        # info.schema._gde_protected_fields (info.schema is self.graphql_schema).
        self.graphql_schema._gde_protected_fields = frozenset(protected)

        if (
            private_query or private_mutation or private_subscription
        ) and not _auth_middleware_configured():
            warnings.warn(
                "ExtraGraphQLSchema received private_query/private_mutation/"
                "private_subscription but AuthenticatedFieldsMiddleware is not in "
                "settings.GRAPHENE['MIDDLEWARE']; private fields will NOT be "
                "protected.",
                RuntimeWarning,
                stacklevel=2,
            )

    @staticmethod
    def _merge_root(
        name: str,
        public: type[ObjectType] | None,
        private: type[ObjectType] | None,
    ) -> type[ObjectType] | None:
        """Union a public root with its private counterpart for the schema.

        Args:
            name: The GraphQL name for the merged root ("Query" / "Mutation" /
                "Subscription").
            public: The public root ObjectType (or "None").
            private: The private root ObjectType (or "None").

        Returns:
            The root ObjectType to hand to graphene: the public root unchanged
            when there is no private root (or when the private fields are already
            a subset of the public root -- the legacy "full root + marker subset"
            usage); the private root when there is no public one; otherwise a new
            ObjectType inheriting from both (the union).
        """
        if private is None:
            return public
        if public is None or public is private:
            return private if public is None else public

        def _field_names(obj: Any) -> set:
            return set(getattr(getattr(obj, "_meta", None), "fields", None) or {})

        if _field_names(private) <= _field_names(public):
            # The private subset is already contained in the (full) public root,
            # so the schema root needs no change -- only protection is recorded.
            return public
        return type(name, (public, private, graphene.ObjectType), {})
