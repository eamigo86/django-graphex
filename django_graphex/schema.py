"""Schema helpers for field-level authorization.

"DjangoGraphQLSchema" lets you declare which top-level fields are private
right where the schema is built ("private_query" / "private_mutation" /
"private_subscription"). It computes the set of protected field names once and
attaches it to the underlying graphql-core schema, where the
"AuthenticatedFieldsMiddleware" reads it at resolve time via "info.schema".
"""

from __future__ import annotations

import os
import warnings
from typing import TYPE_CHECKING, Any

import graphene
from django.conf import settings
from graphene.utils.str_converters import to_camel_case
from graphql import GraphQLError

if TYPE_CHECKING:
    from graphene import ObjectType

__all__ = ("collect_field_names", "DenyAllRegistry", "DjangoGraphQLSchema")

# Backend flag read once at import time, consistent with every other
# GDX_BACKEND check in the codebase (the flag is never toggled per-call).
_NATIVE_BACKEND: bool = os.environ.get("GDX_BACKEND", "graphene") == "native"


def collect_field_names(
    *object_types: Any, camelcase: bool = True
) -> frozenset[str]:
    """Return the (camelCased) field names declared on the given ObjectTypes.

    Reads field names from EITHER a native graphql-core ``GraphQLObjectType``
    (its ``.fields`` keys are ALREADY camelCase — no second ``to_camel_case``
    pass) OR a graphene ``ObjectType`` (snake_case ``_meta.fields`` keys,
    camelCased here to match ``info.field_name`` under ``auto_camelcase=True``).

    Args:
        *object_types: The native ``GraphQLObjectType`` or graphene ObjectTypes
            to collect field names from.
        camelcase: Whether to camelCase graphene snake_case keys (ignored for
            native types whose keys are already camelCase).

    Returns:
        The set of collected field names.
    """
    names: set[str] = set()
    for object_type in object_types:
        if object_type is None:
            continue
        # Native graphql-core type: keys are already camelCase — read as-is.
        native_fields = getattr(object_type, "fields", None)
        if native_fields is not None and not hasattr(object_type, "_meta"):
            names.update(native_fields.keys())
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
    """Check that the AuthenticatedFieldsMiddleware is configured.

    Checks both ``settings.GRAPHEX`` (new canonical namespace) and
    ``settings.GRAPHENE`` (legacy namespace) so that projects using either
    namespace get the warning-check. This is a best-effort check.
    """
    # Check GRAPHEX first (new canonical namespace), then fall back to GRAPHENE.
    graphex_conf = getattr(settings, "GRAPHEX", None) or {}
    graphene_conf = getattr(settings, "GRAPHENE", None) or {}
    # Union: check whichever namespace the project uses (or both).
    middleware_entries = list(graphex_conf.get("MIDDLEWARE", []) or []) + list(
        graphene_conf.get("MIDDLEWARE", []) or []
    )
    for entry in middleware_entries:
        name = entry if isinstance(entry, str) else getattr(entry, "__name__", "")
        if "AuthenticatedFieldsMiddleware" in name:
            return True
    return False


class DjangoGraphQLSchema(graphene.Schema):
    """A "graphene.Schema" that records private fields for the auth middleware.

    Each ``private_*`` ObjectType is **unioned** into its root, so you can keep
    public and private fields in separate roots and the schema exposes the union
    while the private fields require authentication. Nothing is protected unless
    declared in a ``private_*`` root.

    - "private_query" / "private_mutation" / "private_subscription": their
      fields are merged into the corresponding root and require authentication::

          # disjoint public / private roots -> the schema exposes the union
          DjangoGraphQLSchema(
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

        # A query root is REQUIRED on BOTH backends. Native graphql-core raises
        # naturally when query is missing; graphene historically built a
        # query-less schema silently — guard explicitly so the failure is loud
        # and consistent across backends.
        if query is None:
            raise GraphQLError(
                "DjangoGraphQLSchema requires a 'query' root ObjectType; got None."
            )

        # graphene.Schema ALWAYS needs graphene roots; the native field-union +
        # collision check is performed separately on the native path (C12).
        merged_query = self._graphene_merge_root("Query", query, private_query)
        merged_mutation = self._graphene_merge_root(
            "Mutation", mutation, private_mutation
        )
        merged_subscription = self._graphene_merge_root(
            "Subscription", subscription, private_subscription
        )

        super().__init__(
            *args,
            query=merged_query,
            mutation=merged_mutation,
            subscription=merged_subscription,
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

        # NATIVE PATH (WU2/C11 + WU7/C12-C14): rebuild self.graphql_schema as a
        # graphql-core GraphQLSchema assembled DIRECTLY from the native root
        # compiler. _merge_root (native) field-unions public + private into a
        # native GraphQLObjectType, RAISING ValueError on a field-name collision
        # (the inverse-MRO security hazard graphene silently shadows). Protected
        # fields land on schema.extensions['gdx_protected_fields'] (C14).
        #
        # NO try/except fallback to graphene: if native assembly fails it MUST
        # raise (loud). A NotImplementedError for a not-yet-built field kind
        # propagates by design.
        if _NATIVE_BACKEND:
            native_query = self._merge_root("Query", query, private_query)
            native_mutation = self._merge_root("Mutation", mutation, private_mutation)
            native_subscription = self._merge_root(
                "Subscription", subscription, private_subscription
            )
            native_schema = self._build_native_graphql_schema(
                native_query,
                native_mutation,
                native_subscription,
                protected_fields=frozenset(protected),
                **kwargs,
            )
            # Carry the protected-field marker onto the native schema too
            # (legacy reader compatibility) — the canonical native read location
            # is schema.extensions['gdx_protected_fields'] (set at build, C14).
            native_schema._gde_protected_fields = frozenset(protected)
            self.graphql_schema = native_schema

        if (
            private_query or private_mutation or private_subscription
        ) and not _auth_middleware_configured():
            warnings.warn(
                "DjangoGraphQLSchema received private_query/private_mutation/"
                "private_subscription but AuthenticatedFieldsMiddleware is not in "
                "settings.GRAPHENE['MIDDLEWARE']; private fields will NOT be "
                "protected.",
                RuntimeWarning,
                stacklevel=2,
            )

    @staticmethod
    def _build_native_graphql_schema(
        query: Any,
        mutation: Any,
        subscription: Any,
        *,
        protected_fields: frozenset[str] | None = None,
        **kwargs: Any,
    ) -> Any:
        """Assemble a graphql-core ``GraphQLSchema`` from the native root compiler.

        BYPASSES graphene.Schema for the graphql_schema: each merged root is
        either ALREADY a native ``GraphQLObjectType`` (the C12 field-union case,
        produced by ``_merge_root`` under native) or a graphene root class
        (short-circuit cases) compiled here into a native ``GraphQLObjectType``
        whose field types are the canonical native instances (``extensions['gdx']``,
        identity-stable), eliminating the duplicate-name TypeError the first WU2
        attempt hit.

        Args:
            query: The merged query root — a native ``GraphQLObjectType`` or a
                graphene root class (required, never ``None`` here).
            mutation: The merged mutation root (native type, graphene class, or
                ``None``).
            subscription: The merged subscription root (native type, graphene
                class, or ``None``).
            protected_fields: The frozenset of protected top-level field names to
                store on ``schema.extensions['gdx_protected_fields']`` (C14).
            **kwargs: Extra graphene.Schema kwargs. ``directives`` is consumed
                here and forwarded to ``GraphQLSchema`` EXACTLY as graphene does
                (``GraphQLSchema(..., directives=<list>)``): a non-None list
                REPLACES the graphql-core spec built-ins, so the native SDL's
                directive block matches graphene's byte-for-byte (e.g.
                ``directives=all_directives``). ``None`` keeps graphql-core's
                ``specified_directives`` default.

        Returns:
            A ``graphql.GraphQLSchema``.

        Raises:
            NotImplementedError: Propagated from the native root compiler for a
                field kind whose native builder does not exist yet. NEVER
                swallowed by a graphene fallback.
        """
        from graphql import GraphQLObjectType, GraphQLSchema

        from django_graphex.native.schema_compiler import compile_native_root

        def _root_name(root: Any, default: str) -> str:
            """Use the root's GraphQL type name (class name by default).

            graphene names the root after ``_meta.name`` and renders an explicit
            ``schema { query: <Name> }`` block; matching that name keeps the
            native SDL byte-identical to graphene.
            """
            if root is None:
                return default
            if isinstance(root, GraphQLObjectType):
                return root.name
            meta_name = getattr(getattr(root, "_meta", None), "name", None)
            return meta_name or getattr(root, "__name__", None) or default

        def _native_root(root: Any, default: str) -> Any:
            """Return the native ``GraphQLObjectType`` for a merged root.

            Already-native roots (the C12 union) pass through unchanged; graphene
            root classes (short-circuit cases) are compiled on the spot.
            """
            if root is None:
                return None
            if isinstance(root, GraphQLObjectType):
                return root
            return compile_native_root(root, name=_root_name(root, default))

        native_query = _native_root(query, "Query")
        native_mutation = _native_root(mutation, "Mutation")
        native_subscription = _native_root(subscription, "Subscription")

        extensions: dict[str, Any] = {}
        if protected_fields is not None:
            # C14: canonical native read location for protected top-level fields.
            extensions["gdx_protected_fields"] = protected_fields

        # Forward ``directives`` exactly like graphene: a non-None custom list
        # REPLACES graphql-core's specified_directives (so SDL parity holds for
        # schemas built with ``directives=all_directives``); None keeps the
        # graphql-core default.
        directives = kwargs.get("directives")

        return GraphQLSchema(
            query=native_query,
            mutation=native_mutation,
            subscription=native_subscription,
            directives=directives,
            extensions=extensions,
        )

    @staticmethod
    def _merge_root(
        name: str,
        public: Any,
        private: Any,
    ) -> Any:
        """Union a public root with its private counterpart.

        Backend-aware (C12). On the native backend this performs the field-union
        DIRECTLY on the compiled native roots and RAISES ``ValueError`` on a
        field-name collision between public and private — the inverse-MRO security
        hazard graphene silently shadows (one root quietly overrides the other).
        On the graphene backend it delegates to :meth:`_graphene_merge_root`
        (MRO-based union, unchanged).

        The short-circuits are preserved on BOTH backends:
        - no private root -> public unchanged
        - no public root -> private
        - public is private -> public
        - private fields are a SUBSET of public (the "full root + marker subset"
          idiom) -> public unchanged (only protection is recorded)

        Args:
            name: The GraphQL name for the merged root ("Query" / "Mutation" /
                "Subscription").
            public: The public root ObjectType (or ``None``).
            private: The private root ObjectType (or ``None``).

        Returns:
            On graphene: the merged graphene ObjectType (or ``None``). On native:
            a native ``GraphQLObjectType`` for the genuine union, or the graphene
            root class for short-circuit cases (compiled later by
            ``_build_native_graphql_schema``), or ``None``.

        Raises:
            ValueError: On the native backend when public and private declare a
                field with the same name (collision).
        """
        if not _NATIVE_BACKEND:
            return DjangoGraphQLSchema._graphene_merge_root(name, public, private)

        # --- NATIVE field-union with collision guard (C12) -------------------
        if private is None:
            return public
        if public is None:
            return private
        if public is private:
            return public

        def _field_names(obj: Any) -> set:
            return set(getattr(getattr(obj, "_meta", None), "fields", None) or {})

        public_names = _field_names(public)
        private_names = _field_names(private)

        # The "full root + marker subset" idiom: the private root MARKS fields
        # already present in the public root, so there is no real union and no
        # collision. Two signals identify it:
        #   1. public is a SUBCLASS of private (e.g. ``class Root(Private, ...)``)
        #      — the public root is built FROM the private one (inheritance);
        #   2. private fields are a PROPER subset of public — every private field
        #      intentionally marks an existing public field.
        # In both cases the schema root needs no change; only protection is
        # recorded.
        is_inheritance_marker = isinstance(private, type) and issubclass(
            public, private
        )
        if is_inheritance_marker or private_names < public_names:
            return public

        # Genuine union of two INDEPENDENT roots: a name appearing in BOTH is a
        # security hazard (one root silently shadows the other under graphene's
        # inverse MRO). Native must NOT shadow — RAISE.
        collisions = sorted(public_names & private_names)
        if collisions:
            raise ValueError(
                f"DjangoGraphQLSchema cannot merge root {name!r}: field-name "
                f"collision between public and private roots: {collisions}. "
                "A colliding field would let one root silently shadow the other "
                "(a field-level authorization hazard); declare distinct field "
                "names or move the field into a single root."
            )

        # Compile both sides natively, then field-union into one GraphQLObjectType
        # using the cache-before-eval thunk pattern so a self-referential field
        # closes through the registered instance.
        from graphql import GraphQLObjectType

        from django_graphex.native.bridge import GdxPayload
        from django_graphex.native.ir import GdxMeta
        from django_graphex.native.schema_compiler import compile_native_root

        public_native = compile_native_root(
            public, name=DjangoGraphQLSchema._root_type_name(public, name)
        )
        private_native = compile_native_root(
            private, name=DjangoGraphQLSchema._root_type_name(private, name)
        )

        def _merged_fields(
            _pub: GraphQLObjectType = public_native,
            _priv: GraphQLObjectType = private_native,
        ) -> dict:
            return {**_pub.fields, **_priv.fields}

        return GraphQLObjectType(
            name=name,
            fields=_merged_fields,
            extensions={"gdx": GdxPayload(GdxMeta(name=name, graphene_type=public))},
        )

    @staticmethod
    def _root_type_name(root: Any, default: str) -> str:
        """Return the GraphQL type name for a graphene root class."""
        meta_name = getattr(getattr(root, "_meta", None), "name", None)
        return meta_name or getattr(root, "__name__", None) or default

    @staticmethod
    def _graphene_merge_root(
        name: str,
        public: type[ObjectType] | None,
        private: type[ObjectType] | None,
    ) -> type[ObjectType] | None:
        """Union a public root with its private counterpart (graphene backend).

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
