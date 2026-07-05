"""COND-B build-time flat-type guard for subscription output types.

Runs at SCHEMA BUILD, in the same pass as "assert_gdx_bridge"
("core/bridge.py"). For each subscription event (output) type:

1. Type-level escape hatch: if the type carries "_gdx_pure_projection = True"
   the guard is bypassed entirely. Advanced users may set this to accept the
   per-subscriber live-resolver cost.

2. Field-level sentinel check: for every field of the output type assert that
   "field.resolve" carries the sentinel:

       getattr(field.resolve, '_gdx_pure_projection', False) is True

   HARD-FAIL ("GraphQLError") on ANY field whose resolve:
     - is "None" (no resolver set — would fall through to
       "default_field_resolver" which uses camelCase keys, hence silent NULL)
     - is "default_field_resolver" (same silent-null problem)
     - is a hand-written / live / computed / FK / permission resolver that
       lacks the sentinel

CRITICAL (design section 5): the check is the SENTINEL PRESENCE, NOT identity
against "default_field_resolver". Identity-checking "default_field_resolver"
would re-admit the silent-null combo (a snake-shaped closure with a camelCase-
keying default resolver). A snake-closure-shaped fn that LACKS the sentinel is
ALSO rejected. This is the serialize-once safety net: a live-resolver field
would flip "execute()" to the awaitable branch = N executions = N DB queries.

No graphene or channels imports — this module is pure graphql-core + stdlib.
"""

from __future__ import annotations

from graphql import GraphQLError, GraphQLObjectType, GraphQLSchema

__all__ = ["check_subscription_output_type", "check_subscription_schema"]


def check_subscription_output_type(gql_type: GraphQLObjectType) -> None:
    """Assert every field in "gql_type" carries the "_gdx_pure_projection" sentinel.

    Type-level bypass: if "gql_type._gdx_pure_projection is True" the entire type
    is whitelisted — no field check is performed. Use this escape hatch only when
    you intentionally accept live-resolver cost per subscriber.

    Args:
        gql_type: The GraphQL output (event) type produced by a subscription.

    Raises:
        GraphQLError: If any field's resolver is missing the sentinel, is "None",
            or is the graphql-core "default_field_resolver".
    """
    # Type-level escape hatch — bypass field checks entirely
    if getattr(gql_type, "_gdx_pure_projection", False) is True:
        return

    # Walk every field and require the sentinel
    for field_name, field in gql_type.fields.items():
        resolver = field.resolve
        if getattr(resolver, "_gdx_pure_projection", False) is True:
            # Sentinel present — this is a make_snake_resolver closure; OK.
            continue

        # Sentinel absent — HARD-FAIL with a clear, actionable message
        if resolver is None:
            reason = "resolve is None (no resolver set)"
        else:
            from graphql import default_field_resolver as _dfr

            if resolver is _dfr:
                reason = (
                    "resolve is default_field_resolver (uses camelCase wire name "
                    "→ silent NULL for snake-keyed payloads)"
                )
            else:
                reason = (
                    f"resolve is {resolver!r} and lacks the "
                    f"_gdx_pure_projection sentinel (hand-written, live, computed, "
                    f"or unmarked closure)"
                )

        raise GraphQLError(
            f"Subscription output field '{gql_type.name}.{field_name}' has a live "
            f"or unmarked resolver and will not be guarded by the serialize-once "
            f"safety net.  {reason}.  "
            f"Attach a make_snake_resolver closure to fix this, or set "
            f"{gql_type.name}._gdx_pure_projection = True to bypass the guard "
            f"for the entire type."
        )


def check_subscription_schema(schema: GraphQLSchema) -> None:
    """Guard every subscription output type reachable from "schema".

    Walks all subscription output types in "schema" and calls
    "check_subscription_output_type" on each. This is the entry point for the
    build-time guard. Call it in the same pass as "assert_gdx_bridge" after
    schema assembly.

    Args:
        schema: The fully-assembled "GraphQLSchema".

    Raises:
        GraphQLError: From "check_subscription_output_type" on the first
            offending type.
    """
    if schema.subscription_type is None:
        return

    # Collect the concrete output types reachable from subscription fields.
    # A subscription field's return type (unwrapped from List/NonNull) is the
    # event type we need to guard.
    from graphql import GraphQLList, GraphQLNonNull
    from graphql import GraphQLObjectType as _ObjType

    def _unwrap(t):
        """Unwrap NonNull/List wrappers to reach the named type."""
        while isinstance(t, (GraphQLNonNull, GraphQLList)):
            t = t.of_type
        return t

    visited: set[str] = set()
    for _field_name, field in schema.subscription_type.fields.items():
        event_type = _unwrap(field.type)
        if not isinstance(event_type, _ObjType):
            continue
        if event_type.name in visited:
            continue
        visited.add(event_type.name)
        check_subscription_output_type(event_type)
