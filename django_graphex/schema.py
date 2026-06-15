"""Schema helpers for field-level authorization.

"DjangoGraphQLSchema" lets you declare which top-level fields are private
right where the schema is built ("private_query" / "private_mutation" /
"private_subscription"). It computes the set of protected field names once and
attaches it to the underlying graphql-core schema, where the
"AuthenticatedFieldsMiddleware" reads it at resolve time via "info.schema".
"""

from __future__ import annotations

import warnings
from typing import TYPE_CHECKING, Any

from django.conf import settings
from graphene.utils.str_converters import to_camel_case
from graphql import GraphQLError

if TYPE_CHECKING:
    from graphene import ObjectType

__all__ = ("collect_field_names", "DenyAllRegistry", "DjangoGraphQLSchema")


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

    Reads ``settings.GRAPHEX['MIDDLEWARE']`` only. This is a best-effort check.

    BREAKING CHANGE (2.0, S2): the legacy ``settings.GRAPHENE`` namespace is no
    longer consulted — consistent with the GRAPHEX-only settings reader. A
    project still configuring the middleware under ``GRAPHENE`` must rename the
    namespace to ``GRAPHEX``.
    """
    graphex_conf = getattr(settings, "GRAPHEX", None) or {}
    middleware_entries = list(graphex_conf.get("MIDDLEWARE", []) or [])
    for entry in middleware_entries:
        name = entry if isinstance(entry, str) else getattr(entry, "__name__", "")
        if "AuthenticatedFieldsMiddleware" in name:
            return True
    return False


class DjangoGraphQLSchema:
    """A schema wrapper that records private fields for the auth middleware.

    S6f closes the S6 metaclass-swap block: this is a **plain class** (no longer
    a ``graphene.Schema`` subclass). The underlying ``graphql_schema`` — a
    graphql-core ``GraphQLSchema`` — is built DIRECTLY from the native root
    compiler (:meth:`_build_native_graphql_schema`); the graphene
    schema-assembly path has been removed. The class preserves the public
    surface its callers depend on without inheriting graphene:

    - ``graphql_schema``: the graphql-core schema (read by ``views.py`` and the
      subscription transports);
    - ``query`` / ``mutation`` / ``subscription``: the (still-graphene) root
      classes, kept for legacy readers;
    - ``__str__``: renders the SDL via ``graphql.utilities.print_schema`` (same
      output graphene's ``Schema.__str__`` produced);
    - ``auto_camelcase``: exposed for parity readers (graphene default ``True``).

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
        auto_camelcase: bool = True,
        registries: Any = None,
        **kwargs,
    ) -> None:
        """Build the schema and attach the protected-field registry.

        The public root and its ``private_*`` counterpart are **unioned** into
        the actual schema root, so callers may pass disjoint public/private roots
        (each app contributes a public and a private subset; the private subset
        both *defines* and *protects* its fields). Passing a single full root
        plus a ``private_*`` marker subset still works unchanged.

        S6f: ``self.graphql_schema`` is built DIRECTLY from the native root
        compiler (no graphene ``Schema.__init__``). ``_merge_root`` field-unions
        public + private into a native ``GraphQLObjectType``, RAISING
        ``ValueError`` on a field-name collision (the inverse-MRO security hazard
        graphene silently shadowed). Protected fields land on
        ``schema.extensions['gdx_protected_fields']`` (C14). NO try/except
        fallback: if native assembly fails it MUST raise (loud); a
        ``NotImplementedError`` for a not-yet-built field kind propagates by
        design.

        Args:
            *args: Positional arguments (a single positional is treated as the
                ``query`` root, preserving the ``Schema(Query, ...)`` idiom).
            private_query: An ObjectType whose fields require authentication.
            private_mutation: An ObjectType whose fields require authentication.
            private_subscription: An ObjectType whose fields require
                authentication.
            auto_camelcase: Stored on the instance for parity readers (the native
                compiler camelCases field names unconditionally; this flag is kept
                for graphene-API compatibility). Defaults to ``True``.
            registries: The ``SchemaRegistries`` pair this schema compiles
                against (item-b, B3). ``None`` selects the process-wide global
                default pair (``default_schema_registries()``), so existing
                callers are byte-identical. The selected pair is threaded into the
                native build (compile caches/registry) AND stowed on
                ``graphql_schema.extensions['gdx_registry']`` so the polymorphic
                ``resolve_type`` can scope its registry read per-schema at query
                time (B4). For B3 every schema still uses the default pair (no
                fork yet — B5), so SDL + behavior stay byte-identical.
            **kwargs: ``query`` / ``mutation`` / ``subscription`` roots plus
                ``directives`` / ``types`` (forwarded to the graphql-core schema
                by :meth:`_build_native_graphql_schema`).
        """
        query = kwargs.pop("query", None)
        mutation = kwargs.pop("mutation", None)
        subscription = kwargs.pop("subscription", None)
        if args and query is None:  # support the Schema(Query, ...) positional idiom
            query, args = args[0], args[1:]

        # A query root is REQUIRED. Native graphql-core raises naturally when
        # query is missing; guard explicitly so the failure is loud and the
        # message is actionable.
        if query is None:
            raise GraphQLError(
                "DjangoGraphQLSchema requires a 'query' root ObjectType; got None."
            )

        # Exposed for parity readers (graphene's Schema accepted/consumed this).
        self.auto_camelcase = auto_camelcase
        # Kept for legacy readers; the (still-graphene) root classes. Execution
        # and SDL read self.graphql_schema, not these.
        self.query = query
        self.mutation = mutation
        self.subscription = subscription

        # item-b (B3): the SchemaRegistries pair this schema compiles against.
        # ``None`` -> the process-wide global default pair, so existing callers
        # are byte-identical. Threaded into every native compile entrypoint below
        # AND exposed on the built schema's extensions for query-time scoping.
        from django_graphex.native.base import default_schema_registries

        if registries is None:
            registries = default_schema_registries()
        self._registries = registries

        protected = (
            collect_field_names(private_query)
            | collect_field_names(private_mutation)
            | collect_field_names(private_subscription)
        )

        native_query = self._merge_root(
            "Query", query, private_query, registries=registries
        )
        native_mutation = self._merge_root(
            "Mutation", mutation, private_mutation, registries=registries
        )
        native_subscription = self._merge_root(
            "Subscription", subscription, private_subscription, registries=registries
        )
        native_schema = self._build_native_graphql_schema(
            native_query,
            native_mutation,
            native_subscription,
            protected_fields=frozenset(protected),
            registries=registries,
            **kwargs,
        )
        # Carry the protected-field marker onto the native schema too (legacy
        # reader compatibility) — the canonical native read location is
        # schema.extensions['gdx_protected_fields'] (set at build, C14).
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

    def __str__(self) -> str:
        """Render the schema's SDL.

        Mirrors ``graphene.Schema.__str__`` (which returned
        ``print_schema(self.graphql_schema)``) so SDL tooling that did
        ``str(schema)`` keeps working without the graphene base.
        """
        from graphql.utilities import print_schema

        return print_schema(self.graphql_schema)

    @staticmethod
    def _build_native_graphql_schema(
        query: Any,
        mutation: Any,
        subscription: Any,
        *,
        protected_fields: frozenset[str] | None = None,
        registries: Any = None,
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
            registries: The ``SchemaRegistries`` pair to compile each root against
                (item-b, B3); ``None`` -> the global default pair (byte-identical).
                Threaded into ``compile_native_root`` for the graphene-root
                short-circuit cases, and stowed on
                ``schema.extensions['gdx_registry']`` ALONGSIDE
                ``gdx_protected_fields`` so the polymorphic ``resolve_type`` can
                scope its registry read per-schema at query time (B4).
            **kwargs: Extra graphene.Schema kwargs. Two are consumed here and
                forwarded to ``GraphQLSchema`` EXACTLY as graphene does:

                * ``directives`` — forwarded as ``GraphQLSchema(..., directives=
                  <list>)``: a non-None list REPLACES the graphql-core spec
                  built-ins, so the native SDL's directive block matches
                  graphene's byte-for-byte (e.g. ``directives=all_directives``).
                  ``None`` keeps graphql-core's ``specified_directives`` default.
                * ``types`` — a list of graphene type CLASSES of types to FORCE
                  into the schema even when UNREFERENCED by any field. graphene's
                  ``graphene.Schema`` threads ``types=`` through its ``TypeMap``
                  into ``GraphQLSchema(..., types=<list>)``; native must do the
                  same or unreferenced types are SILENTLY dropped from the SDL (a
                  parity divergence). Each graphene class is mapped to its
                  CANONICAL native graphql-core type (see
                  ``_native_types_for_forwarding``) so the same type referenced by
                  a field AND listed in ``types=`` does not duplicate-name.
                  ``None`` / empty keeps graphql-core's defaults.

        Returns:
            A ``graphql.GraphQLSchema``.

        Raises:
            NotImplementedError: Propagated from the native root compiler for a
                field kind whose native builder does not exist yet, OR from
                ``types=`` forwarding for a graphene type kind with no clean
                native mapping. NEVER swallowed by a graphene fallback.
        """
        from graphql import GraphQLObjectType, GraphQLSchema

        from django_graphex.native.base import default_schema_registries
        from django_graphex.native.schema_compiler import compile_native_root

        # item-b (B3): resolve the pair this build compiles against. ``None`` ->
        # the global default pair, so the compile + the stowed extension are
        # byte-identical for the single/default-schema case.
        if registries is None:
            registries = default_schema_registries()

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
            return compile_native_root(
                root, name=_root_name(root, default), registries=registries
            )

        native_query = _native_root(query, "Query")
        native_mutation = _native_root(mutation, "Mutation")
        native_subscription = _native_root(subscription, "Subscription")

        extensions: dict[str, Any] = {}
        if protected_fields is not None:
            # C14: canonical native read location for protected top-level fields.
            extensions["gdx_protected_fields"] = protected_fields
        # item-b (B3): stow the schema's registry pair so the polymorphic
        # ``resolve_type`` can scope its registry read per-schema at query time
        # (B4), via ``info.schema.extensions['gdx_registry']`` — the SAME channel
        # ``gdx_protected_fields`` uses. With the default pair this is the global
        # pair, so the query-time read resolves the same registry as before.
        extensions["gdx_registry"] = registries

        # Forward ``directives`` exactly like graphene: a non-None custom list
        # REPLACES graphql-core's specified_directives (so SDL parity holds for
        # schemas built with ``directives=all_directives``); None keeps the
        # graphql-core default.
        directives = kwargs.get("directives")

        # Forward ``types`` exactly like graphene: each graphene type CLASS of an
        # (possibly UNREFERENCED) type is mapped to its CANONICAL native
        # graphql-core type and threaded into ``GraphQLSchema(..., types=<list>)``
        # so it is forced into the schema/SDL even when no field references it.
        # Without this, native silently DROPS unreferenced ``types=`` entries —
        # an SDL-parity break vs graphene. ``None`` / empty keeps graphql-core's
        # defaults; the canonical-instance mapping keeps a type referenced by a
        # field AND listed in ``types=`` from duplicate-naming.
        native_types = DjangoGraphQLSchema._native_types_for_forwarding(
            kwargs.get("types")
        )

        return GraphQLSchema(
            query=native_query,
            mutation=native_mutation,
            subscription=native_subscription,
            directives=directives,
            types=native_types,
            extensions=extensions,
        )

    @staticmethod
    def _native_types_for_forwarding(
        types: Any,
    ) -> list[Any] | None:
        """Map graphene ``types=`` entries to their canonical native types.

        graphene's ``types=`` is a list of graphene type CLASSES of types to
        FORCE into the schema even when unreferenced. graphql-core's ``types=``
        expects ``GraphQLNamedType`` INSTANCES, so each entry is mapped to its
        canonical native graphql-core equivalent — the SAME instance the rest of
        the schema uses, so a type both referenced by a field AND listed here
        does not duplicate-name:

        * an entry already a graphql-core ``GraphQLNamedType`` (object type,
          scalar, enum, …) → passed through unchanged;
        * a ``DjangoObjectType`` / ``DjangoListObjectType`` (carries the canonical
          ``_meta.graphql_output_type``) → that canonical instance (identity-
          stable; NOT recompiled);
        * a plain ``graphene.ObjectType`` (not a django-graphex output type) →
          compiled via the memoized ``_compile_plain_object_type`` (the SAME
          instance the dispatch path uses, so no duplicate-name);
        * a graphene scalar / enum class (its ``_meta.name`` resolves in
          ``GDX_SCALAR_MAP``) → the canonical native scalar singleton;
        * any other kind (input / interface / union / unmapped scalar) → a clear
          ``NotImplementedError`` naming the type and its kind. NO silent drop:
          dropping a forwarded type is exactly the SDL divergence this method
          fixes, so an unhandled kind fails loudly rather than diverging.

        Args:
            types: The raw ``types=`` value from ``graphene.Schema`` kwargs
                (a list of graphene type classes, or ``None``).

        Returns:
            A list of native ``GraphQLNamedType`` instances, or ``None`` when
            ``types`` is empty/``None`` (so graphql-core keeps its defaults).

        Raises:
            NotImplementedError: For a graphene type kind with no clean native
                mapping. NEVER swallowed by a graphene fallback.
        """
        if not types:
            return None

        import inspect

        from graphql import GraphQLNamedType

        from django_graphex.native.scalars import GDX_SCALAR_MAP
        from django_graphex.native.schema_compiler import (
            _compile_plain_object_type,
            _is_plain_object_type,
            _plain_django_output_type,
        )

        native: list[Any] = []
        for entry in types:
            # 1) Already a graphql-core named type → pass through.
            if isinstance(entry, GraphQLNamedType):
                native.append(entry)
                continue

            # 2) DjangoObjectType / DjangoListObjectType → canonical instance.
            canonical = _plain_django_output_type(entry)
            if canonical is not None:
                native.append(canonical)
                continue

            # 3) Plain graphene.ObjectType → memoized on-the-fly native type
            #    (the SAME instance the dispatch path compiles, so no dup-name).
            if _is_plain_object_type(entry):
                native.append(_compile_plain_object_type(entry))
                continue

            # 4) graphene scalar / enum class whose name resolves in the scalar
            #    map → the canonical native scalar singleton.
            meta_name = getattr(getattr(entry, "_meta", None), "name", None)
            if meta_name is not None and meta_name in GDX_SCALAR_MAP:
                native.append(GDX_SCALAR_MAP[meta_name])
                continue

            # 5) Unsupported kind (input / interface / union / unmapped scalar):
            #    raise loudly — silently dropping it is the exact SDL divergence
            #    this forwarding fixes.
            kind = (
                getattr(entry, "__name__", None)
                if inspect.isclass(entry)
                else type(entry).__name__
            )
            raise NotImplementedError(
                f"DjangoGraphQLSchema cannot forward types= entry {entry!r} "
                f"(name={meta_name!r}, kind={kind!r}) to the native schema: no "
                "native mapping exists for this graphene type kind. Supported "
                "kinds: graphql-core GraphQLNamedType instances, DjangoObjectType "
                "/ DjangoListObjectType, plain graphene.ObjectType, and graphene "
                "scalar/enum classes mapped in GDX_SCALAR_MAP. Map this kind to a "
                "native type or remove it from types= (it must NOT be silently "
                "dropped — that would diverge the native SDL from graphene)."
            )

        return native or None

    @staticmethod
    def _merge_root(
        name: str,
        public: Any,
        private: Any,
        *,
        registries: Any = None,
    ) -> Any:
        """Union a public root with its private counterpart.

        Native field-union (C12): performs the union DIRECTLY on the compiled
        native roots and RAISES ``ValueError`` on a field-name collision between
        public and private — the inverse-MRO security hazard graphene silently
        shadowed (one root quietly overriding the other). The (still-graphene)
        root CLASSES are accepted as input and compiled here; the graphene
        schema-build path is gone (S6f).

        The short-circuits are preserved:
        - no private root -> public unchanged
        - no public root -> private
        - public is private -> public
        - private fields are a SUBSET of public (the "full root + marker subset"
          idiom) -> public unchanged (only protection is recorded)

        Args:
            name: The GraphQL name for the merged root ("Query" / "Mutation" /
                "Subscription").
            public: The public root ObjectType class (or ``None``).
            private: The private root ObjectType class (or ``None``).
            registries: The ``SchemaRegistries`` pair to compile both sides of a
                genuine union against (item-b, B3); ``None`` -> the global default
                pair (byte-identical). Short-circuit cases return the graphene
                root class unchanged (compiled later by
                ``_build_native_graphql_schema`` with the same pair).

        Returns:
            A native ``GraphQLObjectType`` for the genuine union, or the graphene
            root class for short-circuit cases (compiled later by
            ``_build_native_graphql_schema``), or ``None``.

        Raises:
            ValueError: When public and private declare a field with the same
                name (collision).
        """
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
            public,
            name=DjangoGraphQLSchema._root_type_name(public, name),
            registries=registries,
        )
        private_native = compile_native_root(
            private,
            name=DjangoGraphQLSchema._root_type_name(private, name),
            registries=registries,
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
