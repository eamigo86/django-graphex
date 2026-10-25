"""The filter backend seam: model -> filter input type, value -> queryset.

Mirrors the "SerializerBackend" pattern ("backends.py") so the filtering
layer is swappable and isolated. The package ships a single
"NativeFilterBackend" built on Django's ORM lookups and "Q" objects;
"resolve_filter_backend" is the factory seam.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from django.db.models import (
    BooleanField,
    Case,
    Exists,
    ForeignKey,
    ManyToManyField,
    ManyToManyRel,
    ManyToOneRel,
    OuterRef,
    Q,
    Value,
    When,
)
from graphql import GraphQLError, Undefined, get_named_type

from .translate import _is_pk_lookups, _leaf_q, _relation_target, to_q

if TYPE_CHECKING:
    from django.db.models import Model, QuerySet

    from django_graphex.registry import Registry

__all__ = ("FilterBackend", "NativeFilterBackend", "resolve_filter_backend")


class _ForwardFkFilterScope:
    """Carry the active schema, request and database alias through filter branches."""

    def __init__(self, info: Any, alias: str, node_type: Any) -> None:
        """Bind one filter evaluation to its request and compiled output type.

        Args:
            info: Active GraphQL resolve information.
            alias: Database alias of the source queryset.
            node_type: Compiled output type serving the current model.
        """
        self.info = info
        self.alias = alias
        self.node_type = node_type

    @classmethod
    def for_queryset(cls, info: Any, queryset: QuerySet) -> _ForwardFkFilterScope:
        """Build the root scope from the actual request's compiled result type.

        Args:
            info: Active GraphQL resolve information.
            queryset: Source queryset being filtered.

        Returns:
            A request-bound scope for the list's item type.
        """
        from .native_schema import _node_of

        return cls(info, queryset.db, _node_of(get_named_type(info.return_type)))

    def for_relation(
        self, model: type[Model], name: str, prefix: str
    ) -> tuple[Q, _ForwardFkFilterScope]:
        """Scope a forward FK or OneToOne traversal with real-null matches.

        Args:
            model: Model owning the relation.
            name: Relation field name from the coerced filter input.
            prefix: Current ORM relation path.

        Returns:
            A relation condition and the scope for nested filter fields.

        Raises:
            GraphQLError: If the schema omits a traversed destination type or a hook
                switches the destination queryset to another database.
        """
        from django_graphex.core.compat import _gdx_graphene_type
        from django_graphex.utils import (
            apply_object_type_get_queryset,
            has_object_type_queryset_override,
        )

        from .native_schema import _traversed_type

        child_type = (
            _traversed_type(self.node_type, name)
            if self.node_type is not None
            else None
        )
        child_scope = type(self)(self.info, self.alias, child_type)
        field = model._meta.get_field(name)
        if not isinstance(field, ForeignKey):
            return Q(), child_scope
        if self.node_type is None:
            return Q(), child_scope
        if child_type is None:
            raise GraphQLError(
                f"The filter relation {model._meta.label}.{name} has no "
                "destination type in the active schema."
            )
        output_type = _gdx_graphene_type(child_type)
        if not has_object_type_queryset_override(output_type):
            return Q(), child_scope

        destination = field.related_model._default_manager.db_manager(self.alias).all()
        visible = apply_object_type_get_queryset(destination, output_type, self.info)
        if (
            visible.model._meta.concrete_model
            is not field.related_model._meta.concrete_model
            or visible.db != self.alias
        ):
            raise GraphQLError(
                f"{output_type.__name__}.get_queryset must retain the "
                "destination model and database alias for a relation filter."
            )

        path = f"{prefix}{name}"
        # The existing nullable-join predicate still decides whether a truly
        # absent FK matches. A hidden, non-null destination never matches.
        condition = Q(**{f"{path}__isnull": True}) | Q(
            **{f"{path}__pk__in": visible.values("pk")}
        )
        return condition, child_scope

    def reverse_is_scoped(self, model: type[Model], name: str) -> bool:
        """Identify a reverse-FK destination hook without evaluating it.

        Args:
            model: Model owning the reverse relation.
            name: Reverse relation's ORM query name.

        Returns:
            Whether the active schema's child type overrides its row scope.
        """
        from django_graphex.core.compat import _gdx_graphene_type

        from .native_schema import _traversed_type

        field = model._meta.get_field(name)
        if not isinstance(field, ManyToOneRel) or self.node_type is None:
            return False
        child_type = _traversed_type(self.node_type, field.get_accessor_name())
        if child_type is None:
            raise GraphQLError(
                f"The filter relation {model._meta.label}.{name} has no "
                "destination type in the active schema."
            )
        from django_graphex.utils import has_object_type_queryset_override

        return has_object_type_queryset_override(_gdx_graphene_type(child_type))

    def reverse_filter(
        self, model: type[Model], name: str, value: Any, prefix: str
    ) -> Q | None:
        """Filter a reverse-FK using one visible child as its SQL witness.

        A multi-valued join cannot combine visibility and a child predicate
        under negation: Django may compile them as separate existential tests.
        Correlating both against the same child preserves that row identity.

        Args:
            model: Model owning the reverse relation.
            name: Reverse relation's ORM query name.
            value: Nested child fields or direct child-ID lookups.
            prefix: ORM path from the root source to this model.

        Returns:
            A parent-row condition, or None when this relation has no hook.

        Raises:
            GraphQLError: If the hook changes the destination model or alias.
        """
        from django_graphex.core.compat import _gdx_graphene_type
        from django_graphex.utils import apply_object_type_get_queryset

        from .native_schema import _traversed_type

        if not self.reverse_is_scoped(model, name):
            return None
        field = model._meta.get_field(name)
        related = field.related_model
        child_type = _traversed_type(self.node_type, field.get_accessor_name())
        child_scope = type(self)(self.info, self.alias, child_type)
        if _is_pk_lookups(value):
            child_q = _leaf_q("", related._meta.pk.name, value)
        else:
            child_q, _ = to_q(value, related, _scope=child_scope)
        if not child_q:
            return Q()

        output_type = _gdx_graphene_type(child_type)
        destination = related._default_manager.db_manager(self.alias).all()
        visible = apply_object_type_get_queryset(destination, output_type, self.info)
        if (
            visible.model._meta.concrete_model is not related._meta.concrete_model
            or visible.db != self.alias
        ):
            raise GraphQLError(
                f"{output_type.__name__}.get_queryset must retain the "
                "destination model and database alias for a relation filter."
            )
        if not _is_pk_lookups(value) and _has_independent_many_and(value, related):
            child_q = _independent_many_q(value, visible, scope=child_scope)
        linked = visible.filter(**{field.field.attname: OuterRef(f"{prefix}pk")})
        matching = Q(Exists(linked.filter(child_q)))
        if _matches_missing_child(child_q):
            matching |= ~Q(Exists(linked))
        return matching

    def many_to_many_is_scoped(self, model: type[Model], name: str) -> bool:
        """Identify an M2M destination hook in the active compiled schema.

        Args:
            model: Model owning the relation lookup.
            name: Forward or reverse ORM relation name.

        Returns:
            Whether the published destination type scopes its rows.

        Raises:
            GraphQLError: If the active schema omits the destination type.
        """
        from django_graphex.core.compat import _gdx_graphene_type
        from django_graphex.utils import has_object_type_queryset_override

        from .native_schema import _traversed_type

        field = model._meta.get_field(name)
        if (
            not isinstance(field, (ManyToManyField, ManyToManyRel))
            or self.node_type is None
        ):
            return False
        child_type = _traversed_type(self.node_type, name)
        if child_type is None:
            raise GraphQLError(
                f"The filter relation {model._meta.label}.{name} has no "
                "destination type in the active schema."
            )
        return has_object_type_queryset_override(_gdx_graphene_type(child_type))

    def many_to_many_filter(
        self, model: type[Model], name: str, value: Any, prefix: str
    ) -> Q | None:
        """Filter an M2M through one request-visible destination witness.

        The ORM relation lookup supplies the through-table link, including
        custom through fields and reverse accessors. Visibility and the child
        predicate are evaluated on the same destination row before EXISTS is
        complemented by an enclosing NOT.

        Args:
            model: Model owning the M2M relation lookup.
            name: Forward or reverse ORM relation name.
            value: Nested destination fields or direct destination IDs.
            prefix: ORM path from the root source to this model.

        Returns:
            A source-row condition, or None when this relation has no hook.

        Raises:
            GraphQLError: If a destination hook changes model or database alias.
        """
        from django_graphex.core.compat import _gdx_graphene_type
        from django_graphex.utils import apply_object_type_get_queryset

        from .native_schema import _traversed_type

        if not self.many_to_many_is_scoped(model, name):
            return None
        field = model._meta.get_field(name)
        related = field.related_model
        child_type = _traversed_type(self.node_type, name)
        child_scope = type(self)(self.info, self.alias, child_type)
        if _is_pk_lookups(value):
            child_q = _leaf_q("", related._meta.pk.name, value)
        else:
            child_q, _ = to_q(value, related, _scope=child_scope)
        if not child_q:
            return Q()

        output_type = _gdx_graphene_type(child_type)
        destination = related._default_manager.db_manager(self.alias).all()
        visible = apply_object_type_get_queryset(destination, output_type, self.info)
        if (
            visible.model._meta.concrete_model is not related._meta.concrete_model
            or visible.db != self.alias
        ):
            raise GraphQLError(
                f"{output_type.__name__}.get_queryset must retain the "
                "destination model and database alias for a relation filter."
            )
        if not _is_pk_lookups(value) and _has_independent_many_and(value, related):
            child_q = _independent_many_q(value, visible, scope=child_scope)
        reverse_name = (
            field.related_query_name()
            if isinstance(field, ManyToManyField)
            else field.field.name
        )
        linked = visible.filter(**{f"{reverse_name}__pk": OuterRef(f"{prefix}pk")})
        matching = Q(Exists(linked.filter(child_q)))
        if _matches_missing_child(child_q):
            matching |= ~Q(Exists(linked))
        return matching

    def visible_rows(
        self, model: type[Model], name: str
    ) -> tuple[QuerySet, _ForwardFkFilterScope]:
        """Return the request-visible destination rows of a scoped to-many hop.

        Args:
            model: Model owning the reverse-FK or M2M relation.
            name: Forward or reverse ORM relation name.

        Returns:
            The destination rows after its hook, and the scope for its fields.

        Raises:
            GraphQLError: If the hook changes the destination model or alias.
        """
        from django_graphex.core.compat import _gdx_graphene_type
        from django_graphex.utils import apply_object_type_get_queryset

        from .native_schema import _traversed_type

        field = model._meta.get_field(name)
        related = field.related_model
        accessor = (
            field.get_accessor_name() if isinstance(field, ManyToOneRel) else name
        )
        child_type = _traversed_type(self.node_type, accessor)
        child_scope = type(self)(self.info, self.alias, child_type)
        output_type = _gdx_graphene_type(child_type)
        destination = related._default_manager.db_manager(self.alias).all()
        visible = apply_object_type_get_queryset(destination, output_type, self.info)
        if (
            visible.model._meta.concrete_model is not related._meta.concrete_model
            or visible.db != self.alias
        ):
            raise GraphQLError(
                f"{output_type.__name__}.get_queryset must retain the "
                "destination model and database alias for a relation filter."
            )
        return visible, child_scope


def _matches_missing_child(condition: Q) -> bool:
    """Evaluate a child condition against a missing reverse-join row.

    This reproduces the nullable-join branch without querying or materializing
    a child. Explicit SQL-null tests match absence; ordinary values do not.

    Args:
        condition: Predicate compiled for the child model.

    Returns:
        Whether the condition accepts an absent child row.
    """
    values = []
    for child in condition.children:
        if isinstance(child, Q):
            values.append(_matches_missing_child(child))
        elif isinstance(child, tuple):
            values.append(child[0].endswith("__isnull") and child[1] is True)
        elif isinstance(child, Case) and len(child.cases) == 1:
            branch = child.cases[0]
            values.append(
                isinstance(child.output_field, BooleanField)
                and isinstance(child.default, Value)
                and child.default.value is False
                and isinstance(branch, When)
                and isinstance(branch.condition, Q)
                and isinstance(branch.result, Value)
                and branch.result.value is True
                and _matches_missing_child(branch.condition)
            )
        else:
            values.append(False)
    answer = (
        (any(values) if condition.connector == Q.OR else all(values))
        if values
        else True
    )
    return not answer if condition.negated else answer


def apply_filter_backend(
    backend: FilterBackend, queryset: QuerySet, value: Any, info: Any
) -> QuerySet:
    """Pass request context only to the package's unmodified native backend.

    Args:
        backend: Selected filter backend instance.
        queryset: Source queryset to filter.
        value: Coerced GraphQL filter input.
        info: Active GraphQL resolve information.

    Returns:
        The filtered queryset.
    """
    if isinstance(backend, NativeFilterBackend) and (
        type(backend).apply is NativeFilterBackend.apply
    ):
        return backend.apply(queryset, value, info=info)
    return backend.apply(queryset, value)


def _has_independent_many_and(node: Any, model: type[Model]) -> bool:
    """Find an explicit to-many AND at any related-model scope.

    Args:
        node: A generated filter input node.
        model: The model at the current relation-object scope.

    Returns:
        Whether an AND needs independently matched related rows.
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
            # An "or" over a to-many relation shares one join with a sibling
            # relation key, or with a negated operand; each needs its own
            # witness, as an "and" operand has.
            if any(to_q(child, model, _combinator="or")[1] for child in value):
                siblings = {
                    k: v for k, v in node.items() if k not in ("and", "or", "not")
                }
                if to_q(siblings, model)[1] or any(
                    _has_inner_not(child, model, True) for child in value
                ):
                    return True
        elif key == "not" and (
            _has_independent_many_and(value, model)
            or to_q(value, model, _combinator="not")[1]
        ):
            # A not over a to-many relation is NOT EXISTS of its own row.
            return True
        else:
            related = _relation_target(model, key)
            if related is not None and not _is_pk_lookups(value):
                if _has_independent_many_and(value, related):
                    return True
    return False


def _flat_and(children: Any) -> list[Any]:
    """Flatten nested pure-AND nodes into one conjunct list.

    AND is associative, so an operand that is only an "and" list contributes
    its own operands directly. This keeps the compiled SQL depth bounded by
    real relation nesting rather than by "and" nesting, and avoids the
    quadratic re-translation of every enclosing level.

    Args:
        children: The operands of an "and" list.

    Returns:
        The operands with pure "and" wrappers expanded, in order.
    """
    flat: list[Any] = []
    pending = list(reversed(list(children)))
    while pending:
        child = pending.pop()
        if child is not None and child is not Undefined:
            keys = [k for k, v in child.items() if v is not None and v is not Undefined]
            if keys == ["and"]:
                pending.extend(reversed(list(child["and"])))
                continue
        flat.append(child)
    return flat


def _independent_many_q(
    node: Any,
    queryset: QuerySet,
    combinator: str | None = None,
    scope: _ForwardFkFilterScope | None = None,
) -> Q:
    """Compile Boolean input with independent to-many AND at each model scope.

    Each to-many branch is tested in one correlated SQL EXISTS against the
    incoming queryset. This retains its row scope, annotations and database
    alias without materializing primary keys or evaluating one query per row.
    A relation object with deeper independent branches selects one related
    witness satisfying all of its criteria. The ordinary Q still decides
    whether a missing related row satisfies nullable-join lookups.

    Args:
        node: A generated filter input node.
        queryset: The queryset at this model scope.
        combinator: Enclosing Boolean operator for unknown-field validation.
        scope: Request-bound forward-FK destination scope, when available.

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
            for child in _flat_and(value):
                child_q = _independent_many_q(child, queryset, "and", scope)
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
                child_q = _independent_many_q(child, queryset, "or", scope)
                # Like an "and" operand, an operand over a to-many relation
                # owns its related rows; sibling keys at this level never
                # share its join.
                if child_q and to_q(child, queryset.model, _combinator="or")[1]:
                    branch = queryset.filter(pk=OuterRef("pk")).filter(child_q)
                    child_q = Q(Exists(branch))
                combined = child_q if not has_any else (combined | child_q)
                has_any = True
            if has_any:
                result &= combined
        elif key == "not":
            inner = _independent_many_q(value, queryset, "not", scope)
            if inner and to_q(value, queryset.model, _combinator="not")[1]:
                # Exact complement: no row of its own satisfies every criterion
                # (the ORM's exclude() would test each criterion separately).
                branch = queryset.filter(pk=OuterRef("pk")).filter(inner)
                result &= ~Q(Exists(branch))
            else:
                result &= ~inner
        else:
            leaf_q, _ = to_q(
                {key: value}, queryset.model, _combinator=combinator, _scope=scope
            )
            related = _relation_target(queryset.model, key)
            if (
                related is not None
                and not (
                    scope is not None
                    and (
                        scope.reverse_is_scoped(queryset.model, key)
                        or scope.many_to_many_is_scoped(queryset.model, key)
                    )
                )
                and not _is_pk_lookups(value)
                and not _has_inner_not(value, related, True)
                and _has_independent_many_and(value, related)
            ):
                relation_scope, child_scope = (
                    scope.for_relation(queryset.model, key, "")
                    if scope is not None
                    else (Q(), None)
                )
                related_rows = related._base_manager.using(queryset.db).all()
                matching = related_rows.filter(
                    _independent_many_q(value, related_rows, scope=child_scope)
                ).values("pk")
                present = Q(**{f"{key}__in": matching})
                missing = Q(**{f"{key}__isnull": True}) & leaf_q
                result &= (present | missing) & relation_scope
            else:
                result &= leaf_q
    return result


def _negates_exists(condition: Q, negated: bool = False) -> bool:
    """Find an EXISTS under a NOT, which an absent row cannot satisfy.

    Args:
        condition: Predicate compiled for a related row.
        negated: Whether an enclosing Q negates this one.

    Returns:
        Whether a nested to-many test is negated within the condition.
    """
    negated = negated != condition.negated
    for child in condition.children:
        if isinstance(child, Q):
            if _negates_exists(child, negated):
                return True
        elif negated and isinstance(child, Exists):
            return True
    return False


def _has_inner_not(node: Any, model: type[Model], deep: bool) -> bool:
    """Find a "not" inside a relation object.

    Args:
        node: A generated filter input node.
        model: The model at the current relation-object scope.
        deep: Whether to also look through nested relation objects.

    Returns:
        Whether the node holds a "not" at its own scope or, when deep, below.
    """
    if node is None or node is Undefined:
        return False
    for key, value in node.items():
        if value is None or value is Undefined:
            continue
        if key == "not":
            return True
        if key in ("and", "or"):
            if any(_has_inner_not(child, model, deep) for child in value):
                return True
        elif deep and not _is_pk_lookups(value):
            related = _relation_target(model, key)
            if related is not None and _has_inner_not(value, related, True):
                return True
    return False


def _many_not_q(
    node: Any,
    related: type[Model],
    rows: QuerySet,
    linked: QuerySet,
    scope: _ForwardFkFilterScope | None,
    combinator: str | None = None,
) -> Q:
    """Compile a to-many relation object that holds a "not".

    The relation object is a parent-level condition. Criteria without a "not"
    share one related row (one correlated EXISTS); each "not" is the NOT of its
    operand evaluated the same way, so it is the complement of the parent set
    matching the operand, like the ORM's "~Q(rel__...)".

    Args:
        node: The relation object (or a Boolean operand of it).
        related: Related model of the relation.
        rows: Related rows, after any destination scope.
        linked: The rows linked to the outer parent row.
        scope: Request-bound destination scope for nested hops, when available.
        combinator: Enclosing Boolean operator for unknown-field validation.

    Returns:
        A SQL-composable parent-row condition.
    """
    terms: list[Q] = []
    row: dict[str, Any] = {}
    row_and: list[Any] = []
    for key, value in node.items():
        if value is None or value is Undefined:
            continue
        if key == "not":
            inner = _many_not_q(value, related, rows, linked, scope, "not")
            if inner:
                terms.append(~inner)
        elif key == "and":
            for child in _flat_and(value):
                if _has_inner_not(child, related, False):
                    inner = _many_not_q(child, related, rows, linked, scope, "and")
                    if inner:
                        terms.append(inner)
                else:
                    row_and.append(child)
        elif key == "or" and any(_has_inner_not(c, related, False) for c in value):
            combined = Q()
            has_any = False
            for child in value:
                inner = _many_not_q(child, related, rows, linked, scope, "or")
                combined = inner if not has_any else (combined | inner)
                has_any = True
            if has_any:
                terms.append(combined)
        else:
            row[key] = value
    if row_and:
        row["and"] = row_and
    if row:
        if _has_independent_many_and(row, related):
            row_q = _independent_many_q(row, rows, combinator, scope)
        else:
            row_q, _ = to_q(row, related, _combinator=combinator, _scope=scope)
        if row_q:
            witness = Q(Exists(linked.filter(row_q)))
            if not _negates_exists(row_q) and _matches_missing_child(row_q):
                witness |= ~Q(Exists(linked))
            terms.append(witness)
    result = Q()
    for term in terms:
        result &= term
    return result


def many_not_filter(
    model: type[Model], name: str, value: Any, prefix: str, scope: Any
) -> Q:
    """Filter a to-many relation object that holds a "not".

    Args:
        model: Model owning the reverse-FK or M2M relation.
        name: Forward or reverse ORM relation name.
        value: Nested related fields with Boolean operators.
        prefix: ORM path from the root source to this model.
        scope: Request-bound destination scope, or None.

    Returns:
        A parent-row condition, or an empty Q when the relation is not a
        plain reverse-FK or M2M one.
    """
    field = model._meta.get_field(name)
    if isinstance(field, (ManyToManyField, ManyToManyRel)):
        back = (
            field.related_query_name()
            if isinstance(field, ManyToManyField)
            else field.field.name
        )
        link = {f"{back}__pk": OuterRef(f"{prefix}pk")}
    elif isinstance(field, ManyToOneRel) and not hasattr(field.field, "ct_field"):
        link = {field.field.attname: OuterRef(f"{prefix}pk")}
    else:
        return Q()
    related = field.related_model
    if not to_q(value, related)[0]:
        return Q()
    child_scope = None
    if scope is None:
        rows = related._base_manager.all()
    elif scope.reverse_is_scoped(model, name) or scope.many_to_many_is_scoped(
        model, name
    ):
        rows, child_scope = scope.visible_rows(model, name)
    else:
        rows = related._base_manager.using(scope.alias).all()
        child_scope = scope.for_relation(model, name, prefix)[1]
    return _many_not_q(value, related, rows, rows.filter(**link), child_scope)


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

    def apply(self, queryset: QuerySet, value: Any, *, info: Any = None) -> QuerySet:
        """Filter "queryset" with the "Q" translated from "value".

        Applies ".distinct()" when a to-many relation was traversed (to
        de-duplicate join fan-out). An empty/absent value is a no-op.

        Args:
            queryset: The base queryset to filter.
            value: The filter input value, or "None" / empty for a no-op.
            info: Active GraphQL request, or None for direct backend callers.

        Returns:
            The filtered (and possibly de-duplicated) queryset.
        """
        if not value:
            return queryset
        scope = (
            _ForwardFkFilterScope.for_queryset(info, queryset)
            if info is not None and getattr(info, "return_type", None) is not None
            else None
        )
        q, touched_to_many = to_q(value, queryset.model, _scope=scope)
        if not q:
            return queryset
        if _has_independent_many_and(value, queryset.model):
            q = _independent_many_q(value, queryset, scope=scope)
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
