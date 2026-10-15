"""The filter backend seam: model -> filter input type, value -> queryset.

Mirrors the "SerializerBackend" pattern ("backends.py") so the filtering
layer is swappable and isolated. The package ships a single
"NativeFilterBackend" built on Django's ORM lookups and "Q" objects;
"resolve_filter_backend" is the factory seam.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from django.db.models import Exists, OuterRef, Q
from graphql import Undefined

from .translate import to_q

if TYPE_CHECKING:
    from django.db.models import Model, QuerySet

    from django_graphex.registry import Registry

__all__ = ("FilterBackend", "NativeFilterBackend", "resolve_filter_backend")


def _has_independent_many_and(node: Any, model: type[Model]) -> bool:
    """Find an explicit AND branch that crosses a multi-valued relation.

    Relation objects are deliberately opaque here. Their criteria describe
    one related row, even when that object contains its own Boolean operators.

    Args:
        node: A generated filter input node.
        model: The root model being filtered.

    Returns:
        Whether a root-scope AND needs independently matched related rows.
    """
    if node is None or node is Undefined:
        return False
    for key, value in node.items():
        if value is None or value is Undefined:
            continue
        if key == "and":
            for child in value:
                child_q, child_many = to_q(child, model, _combinator="and")
                if child_q and child_many:
                    return True
        elif key == "or":
            if any(_has_independent_many_and(child, model) for child in value):
                return True
        elif key == "not" and _has_independent_many_and(value, model):
            return True
    return False


def _independent_many_q(
    node: Any, queryset: QuerySet, combinator: str | None = None
) -> Q:
    """Compile root-scope Boolean input with independent to-many AND branches.

    Each to-many branch is tested in one correlated SQL EXISTS against the
    incoming queryset. This retains its row scope, annotations and database
    alias without materializing primary keys or evaluating one query per row.
    A relation object remains one ordinary Q so all of its criteria bind the
    same related row, including nullable outer-join behavior.

    Args:
        node: A generated filter input node.
        queryset: The already-scoped root queryset.
        combinator: Enclosing Boolean operator for unknown-field validation.

    Returns:
        A SQL-composable condition for the node.
    """
    result = Q()
    if node is None or node is Undefined:
        return result

    for key, value in node.items():
        if value is None or value is Undefined:
            continue
        if key == "and":
            for child in value:
                child_q = _independent_many_q(child, queryset, "and")
                if not child_q:
                    continue
                _, child_many = to_q(child, queryset.model, _combinator="and")
                if child_many:
                    branch = queryset.filter(pk=OuterRef("pk")).filter(child_q)
                    result &= Q(Exists(branch))
                else:
                    result &= child_q
        elif key == "or":
            combined = Q()
            has_any = False
            for child in value:
                child_q = _independent_many_q(child, queryset, "or")
                combined = child_q if not has_any else (combined | child_q)
                has_any = True
            if has_any:
                result &= combined
        elif key == "not":
            result &= ~_independent_many_q(value, queryset, "not")
        else:
            leaf_q, _ = to_q({key: value}, queryset.model, _combinator=combinator)
            result &= leaf_q
    return result


class FilterBackend:
    """Seam that maps a model's filter declaration to schema and queryset effects.

    Concrete backends turn a "Meta.filter_fields" declaration into a GraphQL
    input type ("build_input_type") and apply a submitted filter value to a
    queryset ("apply"). Mirrors the "SerializerBackend" pattern so the filtering
    layer stays swappable; the package ships "NativeFilterBackend".
    """

    def build_input_type(
        self,
        model: type[Model],
        filter_fields: Any,
        registry: Registry | None = None,
        custom_filters: list | None = None,
        node_type: Any = None,
    ) -> Any:
        """Return the GraphQL input type for a model's filter declaration.

        Args:
            model: The Django model to build a filter input for.
            filter_fields: The "Meta.filter_fields" declaration.
            registry: The registry providing related types and choices enums.
            custom_filters: Optional list of "(arg_name, method, metadata)"
                triples from "@filter_field"-decorated methods.
            node_type: The COMPILED type that will serve this model's rows,
                which is what the projection boundary is measured against. Left
                "None" it is recovered from "registry" -- a model-keyed,
                last-wins index a type opts out of with "Meta.skip_registry",
                so a caller that KNOWS which type will serve the request has to
                say so or the guard answers about a different type.

        Returns:
            A "GraphQLInputObjectType" (or "None" when no filterable fields
            are declared).
        """
        raise NotImplementedError

    def apply(self, queryset: QuerySet, value: Any) -> QuerySet:
        """Apply a filter input value to a queryset.

        Args:
            queryset: The base queryset to filter.
            value: The filter input value (an "InputObjectTypeContainer"), or
                "None" / empty for a no-op.

        Returns:
            The filtered queryset.
        """
        raise NotImplementedError


class NativeFilterBackend(FilterBackend):
    """Filter backend built on Django's ORM lookups and "Q" objects.

    Builds the recursive "<Model>FilterInput" type from a declaration and
    applies a submitted value by translating it to a "Q" via "to_q", adding
    ".distinct()" when a to-many relation was traversed.
    """

    def build_input_type(
        self,
        model: type[Model],
        filter_fields: Any,
        registry: Registry | None = None,
        custom_filters: list | None = None,
        node_type: Any = None,
    ) -> Any:
        """Build the recursive "<Model>FilterInput" type (memoized).

        Args:
            model: The Django model to build a filter input for.
            filter_fields: The "Meta.filter_fields" declaration.
            registry: The registry providing related types and choices enums.
            custom_filters: Optional list of "(arg_name, method, metadata)"
                triples from "@filter_field"-decorated methods.
            node_type: The COMPILED type serving this model's rows, forwarded
                to the projection guard. Without it the guard falls back to the
                registry's last-wins entry, which is not necessarily the type
                about to serve the request.

        Returns:
            A "GraphQLInputObjectType" (or "None" when no filterable fields
            are declared).
        """
        # Native (graphql-core) ``<Model>FilterInput`` builder.
        from .native_schema import build_filter_input_type

        return build_filter_input_type(
            model,
            filter_fields,
            registry,
            custom_filters=custom_filters,
            node_type=node_type,
        )

    def apply(self, queryset: QuerySet, value: Any) -> QuerySet:
        """Filter "queryset" with the "Q" translated from "value".

        Applies ".distinct()" when a to-many relation was traversed (to
        de-duplicate join fan-out). An empty/absent value is a no-op.

        Args:
            queryset: The base queryset to filter.
            value: The filter input value, or "None" / empty for a no-op.

        Returns:
            The filtered (and possibly de-duplicated) queryset.
        """
        if not value:
            return queryset
        q, touched_to_many = to_q(value, queryset.model)
        if not q:
            return queryset
        if _has_independent_many_and(value, queryset.model):
            q = _independent_many_q(value, queryset)
        queryset = queryset.filter(q)
        if touched_to_many:
            queryset = queryset.distinct()
        return queryset


def resolve_filter_backend() -> FilterBackend:
    """Return the configured filter backend (the seam factory).

    Returns:
        A "FilterBackend" instance (the native backend).
    """
    return NativeFilterBackend()
