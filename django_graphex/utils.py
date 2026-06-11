"""Utility functions for Django-GraphQL integration."""

from __future__ import annotations

import dataclasses
import inspect
import logging
import re
from collections import OrderedDict
from typing import TYPE_CHECKING, Any, Iterator

from django.apps import apps
from django.contrib.contenttypes.fields import (
    GenericForeignKey,
    GenericRel,
    GenericRelation,
)
from django.core.exceptions import ValidationError
from django.db.models import (
    NOT_PROVIDED,
    Manager,
    ManyToManyRel,
    ManyToOneRel,
    Model,
    Prefetch,
    QuerySet,
)
from django.db.models.base import ModelBase
from django.db.models.constants import LOOKUP_SEP
from graphene.utils.str_converters import to_snake_case
from graphql import GraphQLList, GraphQLNonNull, GraphQLObjectType, get_named_type
from graphql.execution.values import get_argument_values
from graphql.language.ast import FragmentSpreadNode, InlineFragmentNode
from text_unidecode import unidecode

from .errors import ErrorType
from .settings import graphql_api_settings

if TYPE_CHECKING:
    from django.db.models import Field
    from graphql import GraphQLResolveInfo, GraphQLType
    from graphql.language.ast import SelectionSetNode


@dataclasses.dataclass
class PrefetchPlan:
    """Column narrowing plan for a single direct prefetch branch.

    Attributes:
        only_cols: The list of attname/dotted paths to pass to ``.only()``.
        child_select: The list of forward-FK heads to pass to
            ``.select_related()`` on the child queryset (closes GAP-1 N+1).
    """

    only_cols: list[str]
    child_select: list[str]


def is_valid_django_model(model: Any) -> bool:
    """Return whether ``model`` is a Django model class.

    Args:
        model: The object to test.

    Returns:
        True if ``model`` is a subclass of ``django.db.models.Model``.
    """
    return inspect.isclass(model) and issubclass(model, Model)


def maybe_queryset(value: Any) -> Any:
    """Return a queryset for a manager, or the value unchanged.

    Args:
        value: A model manager or any other value.

    Returns:
        ``value.get_queryset()`` when ``value`` is a ``Manager``, else ``value``.
    """
    if isinstance(value, Manager):
        value = value.get_queryset()
    return value


def to_const(string: str) -> str:
    """Convert a label to an uppercase GraphQL enum constant name.

    Args:
        string: The human-readable label (e.g. a model choice display).

    Returns:
        An uppercase, underscore-separated constant safe for an enum name.
    """
    return re.sub(r"[\W|^]+", "_", unidecode(string)).upper()


def not_found_error(model: type[Model], pk: Any) -> list:
    """Return a one-entry ``ErrorType`` list for a missing object.

    Centralizes the "object not found" mutation error so its wording stays
    consistent across types and mutations.

    Args:
        model: The Django model that was looked up.
        pk: The primary key that did not match a row.

    Returns:
        A single-element list of "ErrorType" with the "id" field set.
    """
    return [
        ErrorType(
            field="id",
            messages=["{} with id {} does not exist.".format(model.__name__, pk)],
        )
    ]


def get_reverse_fields(model: type[Model]) -> Iterator[tuple[str, Any]]:
    """Yield the reverse relation fields of a Django model.

    Args:
        model: The Django model class to inspect.

    Yields:
        Pairs of the field name and its reverse relation descriptor.
    """
    reverse_fields = {
        f.name: f for f in model._meta.get_fields() if f.auto_created and not f.concrete
    }

    for name, field in reverse_fields.items():
        # Django =>1.9 uses 'rel', django <1.9 uses 'related'
        related = getattr(field, "rel", None) or getattr(field, "related", None)
        if isinstance(related, ManyToOneRel):
            yield (name, related)
        elif isinstance(related, ManyToManyRel) and not related.symmetrical:
            yield (name, related)


def to_kebab_case(name: str) -> str:
    """Convert a name to kebab-case format.

    Args:
        name: The name to convert.

    Returns:
        The kebab-cased name.
    """
    s1 = re.sub("(.)([A-Z][a-z]+)", r"\1-\2", name.title().replace(" ", ""))
    return re.sub("([a-z0-9])([A-Z])", r"\1-\2", s1).lower()


def get_related_model(field: Field) -> type[Model]:
    """Return the related model of a Django relation field.

    Args:
        field: The Django relation field to inspect.

    Returns:
        The related Django model class.
    """
    return field.remote_field.model


def get_model_fields(model: type[Model]) -> list[tuple[str, Any]]:
    """Return all fields of a Django model, including reverse fields.

    Args:
        model: The Django model class to inspect.

    Returns:
        A list of "(name, field)" pairs for every local and reverse field.
    """
    private_fields = model._meta.private_fields

    all_fields_list = (
        list(model._meta.fields)
        + list(model._meta.local_many_to_many)
        + list(private_fields)
        + list(model._meta.fields_map.values())
    )

    # Make sure we don't duplicate local fields with "reverse" version
    # and get the real reverse django related_name
    reverse_fields = list(get_reverse_fields(model))
    exclude_fields = [field[1] for field in reverse_fields]

    local_fields = [
        (field.name, field) for field in all_fields_list if field not in exclude_fields
    ]

    all_fields = local_fields + reverse_fields

    return all_fields


def get_obj(app_label: str, model_name: str, object_id: Any) -> Model | None:
    """Get a Django object by app label, model name, and object ID.

    Args:
        app_label: The Django app label.
        model_name: The model name.
        object_id: The primary key of the object.

    Returns:
        The model instance, or None if it does not exist.

    Raises:
        ValidationError: If the lookup fails validation.
        TypeError: If the lookup arguments have an invalid type.
        Exception: If any other error occurs during the lookup.
    """
    try:
        model = apps.get_model(f"{app_label}.{model_name}")
    except LookupError:
        # Unknown app label / model name -> no such object.
        return None

    if not is_valid_django_model(model):
        return None

    try:
        return get_Object_or_None(model, pk=object_id)
    except model.DoesNotExist:
        return None
    except ValidationError as e:
        raise ValidationError(str(e))
    except TypeError as e:
        raise TypeError(str(e))
    except Exception as e:
        raise Exception(str(e))


def create_obj(
    django_model: Any, new_obj_key: str | None = None, *args: Any, **kwargs: Any
) -> Any:
    """Create a Django model instance.

    Args:
        django_model: A Django model class or a "app_label.model_name" string.
        new_obj_key: The key in "kwargs" holding the data, if any.
        *args: Additional positional arguments.
        **kwargs: The model attribute values.

    Returns:
        The created model instance, or an error message string on failure.

    Raises:
        ValidationError: If the new object fails validation.
        TypeError: If the supplied data has an invalid type.
    """
    try:
        if isinstance(django_model, str):
            django_model = apps.get_model(django_model)
        assert is_valid_django_model(django_model), (
            "You need to pass a valid Django Model or a string with format: "
            '<app_label>.<model_name> to "create_obj"'
            ' function, received "{}".'
        ).format(django_model)

        data = kwargs.get(new_obj_key, None) if new_obj_key else kwargs
        new_obj = django_model(**data)
        new_obj.full_clean()
        new_obj.save()
        return new_obj
    except LookupError:
        pass
    except ValidationError as e:
        raise ValidationError(str(e))
    except TypeError as e:
        raise TypeError(str(e))
    except Exception as e:
        return str(e)


def clean_dict(d: Any) -> Any:
    """Remove all empty fields in a nested dict.

    Args:
        d: The value to clean, typically a dict or list.

    Returns:
        The value with empty entries removed at every nesting level.
    """
    if not isinstance(d, (dict, list)):
        return d
    if isinstance(d, list):
        return [v for v in (clean_dict(v) for v in d) if v]
    return OrderedDict(
        [(k, v) for k, v in ((k, clean_dict(v)) for k, v in list(d.items())) if v]
    )


def get_type(_type: GraphQLType) -> GraphQLType:
    """Return the base type from GraphQL list/non-null wrappers.

    Args:
        _type: The GraphQL type, possibly wrapped.

    Returns:
        The unwrapped underlying GraphQL type.
    """
    if isinstance(_type, (GraphQLList, GraphQLNonNull)):
        return get_type(_type.of_type)
    return _type


def get_fields(info: GraphQLResolveInfo) -> Iterator[str]:
    """Extract the requested field names from the GraphQL query info.

    Args:
        info: The GraphQL resolve info for the current field.

    Yields:
        The name of each selected field, expanding fragment spreads.
    """
    fragments = info.fragments
    field_nodes = info.field_nodes[0].selection_set.selections

    for field_ast in field_nodes:
        field_name = field_ast.name.value
        if isinstance(field_ast, FragmentSpreadNode):
            for field in fragments[field_name].selection_set.selections:
                yield field.name.value
            continue

        yield field_name


def is_required(field: Field) -> bool:
    """Check whether a Django field is required.

    Args:
        field: The Django field to inspect.

    Returns:
        True if the field is required, False otherwise.
    """
    try:
        blank = getattr(field, "blank", getattr(field, "field", None))
        default = getattr(field, "default", getattr(field, "field", None))

        if blank is None:
            blank = True
        elif not isinstance(blank, bool):
            blank = getattr(blank, "blank", True)

        if default is None:
            default = NOT_PROVIDED
        elif default != NOT_PROVIDED:
            default = getattr(default, "default", default)

    except AttributeError:
        return False

    return not blank and default == NOT_PROVIDED


def _get_queryset(klass: Any) -> QuerySet:
    """Return a QuerySet from a Model, Manager, or QuerySet.

    Args:
        klass: A Django model, manager, or queryset.

    Returns:
        A queryset derived from "klass".

    Raises:
        ValueError: If "klass" is not a valid type.
    """
    if isinstance(klass, QuerySet):
        return klass
    elif isinstance(klass, Manager):
        manager = klass
    elif isinstance(klass, ModelBase):
        manager = klass._default_manager
    else:
        if isinstance(klass, type):
            klass__name = klass.__name__
        else:
            klass__name = klass.__class__.__name__
        raise ValueError(
            "Object is of type '{}', but must be a Django Model, "
            "Manager, or QuerySet".format(klass__name)
        )
    return manager.all()


def _get_custom_resolver(info: GraphQLResolveInfo) -> Any | None:
    """Get the custom user-defined resolver for the query, if any.

    This resolver must return a QuerySet instance to be successfully resolved.

    Args:
        info: The GraphQL resolve info for the current field.

    Returns:
        The custom resolver callable, or None if none is defined.
    """
    parent = info.parent_type
    custom_resolver_name = f"resolve_{to_snake_case(info.field_name)}"
    if hasattr(parent.graphene_type, custom_resolver_name):
        return getattr(parent.graphene_type, custom_resolver_name)
    return None


def get_Object_or_None(klass: Any, *args: Any, **kwargs: Any) -> Model | None:
    """Use get() to return an object, or None if it does not exist.

    The "klass" may be a Model, Manager, or QuerySet object. All other passed
    arguments and keyword arguments are used in the get() query. Like with
    get(), a MultipleObjectsReturned error is raised if more than one object
    is found.

    Args:
        klass: A Django model, manager, or queryset.
        *args: When given, the first value selects the database alias.
        **kwargs: The lookup arguments for the get() query.

    Returns:
        The matched object, or None if it does not exist.
    """
    queryset = _get_queryset(klass)
    try:
        if args:
            return queryset.using(args[0]).get(**kwargs)
        else:
            return queryset.get(*args, **kwargs)
    except queryset.model.DoesNotExist:
        return None


def get_extra_filters(root: Model, model: type[Model]) -> dict[str, Any]:
    """Build extra filters tying a model to its parent "root" relations.

    Args:
        root: The parent model instance to filter against.
        model: The Django model class being filtered.

    Returns:
        A mapping of relation field names to the "root" instance.
    """
    extra_filters = {}
    for field in model._meta.get_fields():
        if field.is_relation and field.related_model == root._meta.model:
            extra_filters.update({field.name: root})

    return extra_filters


def get_related_fields(model: type[Model]) -> dict[str, Any]:
    """Return the relation fields of a Django model.

    Args:
        model: The Django model class to inspect.

    Returns:
        A mapping of field name to field for each non-generic relation.
    """
    return {
        field.name: field
        for field in model._meta.get_fields()
        if field.is_relation and not isinstance(field, (GenericForeignKey, GenericRel))
    }


def find_field(field: Any, fields_dict: dict[str, Any]) -> Any:
    """Find a field in a fields dictionary by its name or snake_case name.

    Args:
        field: The GraphQL field node whose name is looked up.
        fields_dict: The mapping of field names to fields.

    Returns:
        The matched field, or None if not found.
    """
    temp = fields_dict.get(
        field.name.value, fields_dict.get(to_snake_case(field.name.value), None)
    )

    return temp


# GraphQL/relay plumbing leaf names that never map to a model column and must not
# mark a model as "computed" when deciding `.only()` narrowing.
_PLUMBING_FIELDS = frozenset(
    {
        "__typename",
        "totalcount",
        "count",
        "pageinfo",
        "page_info",
        "cursor",
        "startcursor",
        "endcursor",
        "hasnextpage",
        "haspreviouspage",
        "edges",
        "node",
    }
)


def _relation_optimization(field: Any) -> tuple[str, str] | None:
    """Classify a Django relation field for queryset optimization.

    The "orm_name" is the path component to feed "select_related" /
    "prefetch_related" (the reverse accessor for reverse relations).

    Args:
        field: The Django field to classify.

    Returns:
        A "(select, orm_name)" pair for forward FK or one-to-one, a
        "(prefetch, orm_name)" pair for many-to-many or reverse FK, or None
        for non-relations and generic relations.
    """
    if isinstance(field, GenericForeignKey):
        return ("prefetch", field.name)
    if isinstance(field, GenericRel):
        return None
    if not getattr(field, "is_relation", False):
        return None

    is_reverse = getattr(field, "auto_created", False) and not getattr(
        field, "concrete", False
    )
    if is_reverse:
        get_accessor = getattr(field, "get_accessor_name", None)
        orm_name = get_accessor() if callable(get_accessor) else field.name
    else:
        orm_name = field.name

    if field.many_to_many or field.one_to_many:
        return ("prefetch", orm_name)
    if field.many_to_one or field.one_to_one:
        return ("select", orm_name)
    return None  # pragma: no cover


def _relation_field_map(model: type[Model]) -> dict[str, Any]:
    """Map relation names (with snake and accessor aliases) to their fields.

    Args:
        model: The Django model class to inspect.

    Returns:
        A mapping of every GraphQL-facing relation name and alias to its
        field.
    """
    result = {}
    for field in model._meta.get_fields():
        if _relation_optimization(field) is None:
            continue
        names = {field.name, to_snake_case(field.name)}
        get_accessor = getattr(field, "get_accessor_name", None)
        if callable(get_accessor):
            try:
                names.add(get_accessor())
            except Exception:  # nosec B110 - accessor may be unavailable ; pragma: no cover
                pass
        for name in names:
            result.setdefault(name, field)
    return result


def _concrete_field_map(model: type[Model]) -> dict[str, str]:
    """Map concrete non-relation field names and snake aliases to attnames.

    Args:
        model: The Django model class to inspect.

    Returns:
        A mapping of each concrete field name and snake alias to its attname.
    """
    result = {}
    for field in model._meta.get_fields():
        if getattr(field, "is_relation", False):
            continue
        if not getattr(field, "concrete", False):
            continue  # pragma: no cover
        result.setdefault(field.name, field.attname)
        result.setdefault(to_snake_case(field.name), field.attname)
    return result


def recursive_params(
    selection_set: SelectionSetNode,
    fragments: dict[str, Any],
    available_related_fields: dict[str, Any],
    select_related: list[str],
    prefetch_related: list[str],
    _prefix: str = "",
) -> tuple[list[str], list[str]]:
    """Walk a GraphQL selection set building nested select/prefetch paths.

    The "available_related_fields" argument is the relation map of the current
    model (name to field). Forward FK or one-to-one relations become dotted
    "select_related" paths; many-to-many or reverse relations become
    "prefetch_related" paths. The walk descends into related models (building
    "a__b" paths) and is transparent to wrapper fields (such as "results"),
    fragments and inline fragments.

    Args:
        selection_set: The GraphQL selection set to walk.
        fragments: The fragment definitions keyed by name.
        available_related_fields: The relation map of the current model.
        select_related: The accumulated select_related paths, mutated in place.
        prefetch_related: The accumulated prefetch_related paths, mutated in
            place.
        _prefix: The dotted ORM path prefix for the current model.

    Returns:
        The mutated "(select_related, prefetch_related)" pair.
    """
    for field in selection_set.selections:
        if isinstance(field, FragmentSpreadNode):
            fragment = fragments.get(field.name.value) if fragments else None
            if fragment is not None:
                recursive_params(
                    fragment.selection_set,
                    fragments,
                    available_related_fields,
                    select_related,
                    prefetch_related,
                    _prefix,
                )
            continue

        if isinstance(field, InlineFragmentNode):
            recursive_params(
                field.selection_set,
                fragments,
                available_related_fields,
                select_related,
                prefetch_related,
                _prefix,
            )
            continue

        name = field.name.value
        related_field = available_related_fields.get(
            name, available_related_fields.get(to_snake_case(name), None)
        )
        sub_selection = getattr(field, "selection_set", None)

        if related_field is not None:
            optimization = _relation_optimization(related_field)
            if optimization is None:
                continue  # pragma: no cover
            kind, orm_name = optimization
            path = _prefix + orm_name
            target = select_related if kind == "select" else prefetch_related
            if path not in target:
                target.append(path)
            if sub_selection is not None and not isinstance(
                related_field, GenericForeignKey
            ):
                related_model = get_related_model(related_field)
                recursive_params(
                    sub_selection,
                    fragments,
                    _relation_field_map(related_model),
                    select_related,
                    prefetch_related,
                    path + LOOKUP_SEP,
                )
        elif sub_selection is not None:
            # Wrapper field (e.g. `results`) or unknown object: stay on the same
            # model and prefix so nested relations are still discovered.
            recursive_params(
                sub_selection,
                fragments,
                available_related_fields,
                select_related,
                prefetch_related,
                _prefix,
            )

    return select_related, prefetch_related


def _collect_only_fields(
    model: type[Model],
    selection_set: SelectionSetNode,
    fragments: dict[str, Any],
    _prefix: str = "",
    _only: set[str] | None = None,
) -> list[str]:
    """Collect a safe ".only()" field set across the select_related span.

    Always keeps the pk (per model in the span), forward FK attnames and
    "Meta.ordering" columns. A model that selects a computed or unknown leaf
    is loaded in full (not narrowed) so properties keep working. Prefetched
    branches are not narrowed.

    Args:
        model: The Django model class at the current span position.
        selection_set: The GraphQL selection set to walk.
        fragments: The fragment definitions keyed by name.
        _prefix: The dotted ORM path prefix for the current model.
        _only: The accumulating set of dotted only paths.

    Returns:
        A sorted list of dotted "only" paths.
    """
    if _only is None:
        _only = set()

    rel_map = _relation_field_map(model)
    concrete_map = _concrete_field_map(model)
    concrete_attnames = {field.attname for field in model._meta.concrete_fields}

    # Always-on columns for this model so select_related joins/ordering survive.
    _only.add(_prefix + model._meta.pk.attname)
    for term in model._meta.ordering or []:
        if not isinstance(term, str):
            continue
        column = term.lstrip("-+").split(LOOKUP_SEP)[0]
        if column in concrete_attnames:
            _only.add(_prefix + column)

    model_full = False
    pending = []
    for field in selection_set.selections:
        if isinstance(field, FragmentSpreadNode):
            fragment = fragments.get(field.name.value) if fragments else None
            if fragment is not None:
                _collect_only_fields(
                    model, fragment.selection_set, fragments, _prefix, _only
                )
            continue
        if isinstance(field, InlineFragmentNode):
            _collect_only_fields(model, field.selection_set, fragments, _prefix, _only)
            continue

        name = field.name.value
        snake = to_snake_case(name)
        sub_selection = getattr(field, "selection_set", None)

        related_field = rel_map.get(name, rel_map.get(snake, None))
        if related_field is not None:
            optimization = _relation_optimization(related_field)
            if optimization is None:
                continue  # pragma: no cover
            kind, orm_name = optimization
            if isinstance(related_field, GenericForeignKey):
                # GFK needs the two concrete LOCAL columns on the parent row so
                # Django can run the prefetch_related second query without
                # re-loading: the content-type id and object id.  Resolve
                # attnames via model meta (ct_field stores the field NAME, e.g.
                # "content_type"; its attname is "content_type_id").
                _only.add(
                    _prefix + model._meta.get_field(related_field.ct_field).attname
                )
                _only.add(
                    _prefix + model._meta.get_field(related_field.fk_field).attname
                )
                continue
            if kind == "select":
                # Forward FK / O2O: keep the local join key on this model.
                if getattr(related_field, "concrete", False) and getattr(
                    related_field, "attname", None
                ):
                    _only.add(_prefix + related_field.attname)
                if sub_selection is not None:
                    _collect_only_fields(
                        get_related_model(related_field),
                        sub_selection,
                        fragments,
                        _prefix + orm_name + LOOKUP_SEP,
                        _only,
                    )
            # prefetch branches use separate querysets -> not narrowed here.
            continue

        concrete_attname = concrete_map.get(name, concrete_map.get(snake, None))
        if concrete_attname is not None:
            pending.append(_prefix + concrete_attname)
            continue

        if name.lower() in _PLUMBING_FIELDS or snake in _PLUMBING_FIELDS:
            continue

        if sub_selection is not None:
            # Wrapper field (e.g. `results`, or a renamed results field).
            _collect_only_fields(model, sub_selection, fragments, _prefix, _only)
            continue

        # Unknown leaf -> computed/property/custom-named field.
        model_full = True

    if model_full:
        for attname in concrete_attnames:
            _only.add(_prefix + attname)
    else:
        _only.update(pending)

    return sorted(_only)


def _collect_only_fields_is_full_load(
    model: type[Model],
    selection_set: Any,
    fragments: dict[str, Any],
) -> bool:
    """Return True when ``_collect_only_fields`` would trigger the full-load path.

    Detects the case where the selection contains an unknown/computed leaf that
    sets ``model_full=True`` in ``_collect_only_fields``.  Used by
    ``_compute_child_only`` to decide whether to skip ``.only()`` for a prefetch
    branch without needing to compare result sets.

    This is a private helper and MUST NOT be used outside this module.

    Args:
        model: The Django model class at the current span position.
        selection_set: The GraphQL selection set to walk.
        fragments: The fragment definitions keyed by name.

    Returns:
        True if any unknown leaf would trigger full-load for ``model``.
    """
    rel_map = _relation_field_map(model)
    concrete_map = _concrete_field_map(model)

    for field in selection_set.selections:
        if isinstance(field, FragmentSpreadNode):
            fragment = fragments.get(field.name.value) if fragments else None
            if fragment is not None:
                if _collect_only_fields_is_full_load(
                    model, fragment.selection_set, fragments
                ):
                    return True
            continue
        if isinstance(field, InlineFragmentNode):
            if _collect_only_fields_is_full_load(model, field.selection_set, fragments):
                return True
            continue

        name = field.name.value
        snake = to_snake_case(name)
        sub_selection = getattr(field, "selection_set", None)

        related_field = rel_map.get(name, rel_map.get(snake, None))
        if related_field is not None:
            continue  # relations don't trigger full-load

        if concrete_map.get(name, concrete_map.get(snake, None)) is not None:
            continue  # known concrete field

        if name.lower() in _PLUMBING_FIELDS or snake in _PLUMBING_FIELDS:
            continue

        if sub_selection is not None:
            # Wrapper field — recurse but it doesn't trigger full-load by itself.
            if _collect_only_fields_is_full_load(model, sub_selection, fragments):
                return True
            continue

        # Unknown leaf -> triggers model_full=True.
        return True

    return False


# --------------------------------------------------------------------------- #
# Phase B helpers — prefetch branch column narrowing                           #
# --------------------------------------------------------------------------- #


def _leaf_model(model: type[Model], lookup: str) -> type[Model]:
    """Walk a dotted ORM lookup through ALL relation kinds and return the leaf model.

    Unlike ``_collect_only_fields``, which only traverses select_related segments,
    this helper traverses PREFETCH relations too (reverse FK, M2M, GenericRelation)
    so that a dotted top_plain lookup like ``posts__tags`` resolves to ``Tag``.

    GFK-target fields are never passed here (they are skipped in
    ``_collect_prefetch_only_sets`` before any call to this function).

    Args:
        model: The root model class.
        lookup: A dotted ORM path, e.g. ``"posts"`` or ``"posts__tags"``.

    Returns:
        The Django model class at the end of the lookup chain.
    """
    current = model
    for segment in lookup.split(LOOKUP_SEP):
        rel_map = _relation_field_map(current)
        field = rel_map.get(segment) or rel_map.get(to_snake_case(segment))
        current = get_related_model(field)
    return current


def _compute_child_only(
    child: type[Model],
    related_field: Any,
    sub_selection: Any,
    fragments: dict[str, Any],
) -> PrefetchPlan | None:
    """Compute the `.only()` column plan for a single prefetch child queryset.

    Reuses ``_collect_only_fields`` as the single source of truth for requested
    and mandatory columns.  A full-load signal (unknown/computed leaf) is
    detected and returned as ``None`` — the caller leaves the lookup as a bare
    string (full load).

    The returned ``PrefetchPlan.child_select`` list contains the forward-FK head
    paths that MUST accompany the ``.only()`` call to avoid re-introducing N+1
    (GAP-1).

    Args:
        child: The child model class.
        related_field: The Django relation field object (ManyToOneRel,
            ManyToManyField, GenericRelation, etc.).
        sub_selection: The GraphQL SelectionSetNode for the child sub-selection.
        fragments: Fragment definitions keyed by name.

    Returns:
        A ``PrefetchPlan`` with the column and select_related lists, or ``None``
        to signal a full-load branch.
    """
    if sub_selection is None:
        return None

    # Full-load detection: if the sub-selection contains an unknown/computed
    # leaf (e.g. a @property), mirror the root model_full contract and return
    # None (caller leaves the lookup as a bare string -> full load; no FieldError).
    if _collect_only_fields_is_full_load(child, sub_selection, fragments):
        return None

    # Collect the raw only-set via the existing helper (handles ordering, pk,
    # fragment spreads, inline fragments transparently).
    raw_cols = _collect_only_fields(child, sub_selection, fragments)

    # Split raw_cols into dotted FK heads (-> child_select) and flat attnames
    # (-> only_cols).  _collect_only_fields emits dotted paths like
    # ``category__id`` for select_related descents; those heads become
    # child_select entries so the forward FK is select_related on the child
    # queryset (GAP-1 fix).
    only_cols: list[str] = list(raw_cols)  # keep dotted paths for .only()
    child_select: list[str] = []
    for col in raw_cols:
        if LOOKUP_SEP in col:
            # Extract the head up to the last separator.  e.g. "a__b__col" -> "a__b".
            head = LOOKUP_SEP.join(col.split(LOOKUP_SEP)[:-1])
            if head not in child_select:
                child_select.append(head)

    # Always-keep structural columns (§4.1) — these may already be present from
    # _collect_only_fields, but we guarantee them unconditionally.
    pk_attname = child._meta.pk.attname
    if pk_attname not in only_cols:
        only_cols.append(pk_attname)

    concrete_attnames = {f.attname for f in child._meta.concrete_fields}
    for term in child._meta.ordering or []:
        if not isinstance(term, str):
            continue
        column = term.lstrip("-+").split(LOOKUP_SEP)[0]
        if column in concrete_attnames and column not in only_cols:
            only_cols.append(column)

    # Per-relation-kind dispatch (GAP-2): add structural join columns.
    if isinstance(related_field, GenericRelation):
        # Discover the child GFK matching this GenericRelation's ct/fk fields.
        ct_field_name = related_field.content_type_field_name  # e.g. "content_type"
        fk_field_name = related_field.object_id_field_name  # e.g. "object_id"
        # Disambiguate among multiple GFKs on the child: pick the one whose
        # ct_field and fk_field match the GenericRelation's referenced fields.
        gfk = None
        for f in child._meta.get_fields():
            if isinstance(f, GenericForeignKey):
                if f.ct_field == ct_field_name and f.fk_field == fk_field_name:
                    gfk = f
                    break
        if gfk is None:
            # Fallback: try to find any GFK (single-GFK case).
            for f in child._meta.get_fields():
                if isinstance(f, GenericForeignKey):
                    gfk = f
                    break
        if gfk is None:
            # No GFK found -> full-load fallback.
            return None
        ct_attname = child._meta.get_field(gfk.ct_field).attname
        fk_attname = child._meta.get_field(gfk.fk_field).attname
        if ct_attname not in only_cols:
            only_cols.append(ct_attname)
        if fk_attname not in only_cols:
            only_cols.append(fk_attname)

    elif getattr(related_field, "many_to_many", False):
        # Forward ManyToManyField + reverse ManyToManyRel: Django handles the
        # through-table join; only pk + ordering are needed structurally.
        pass  # already added pk + ordering above

    elif getattr(related_field, "one_to_many", False):
        # Reverse FK (ManyToOneRel): add the FK-back attname on the child.
        fk_field = getattr(related_field, "field", None)
        if fk_field is None:
            return None
        fk_attname = fk_field.attname
        if fk_attname not in only_cols:
            only_cols.append(fk_attname)

    return PrefetchPlan(only_cols=only_cols, child_select=child_select)


def _collect_prefetch_only_sets(
    model: type[Model],
    selection_set: Any,
    fragments: dict[str, Any],
    _prefix: str = "",
    _out: dict[str, PrefetchPlan] | None = None,
) -> dict[str, PrefetchPlan]:
    """Map each direct prefetch lookup to its child column plan.

    Walks the GraphQL selection set mirroring ``recursive_params`` structure
    (handles fragments, inline fragments, wrapper fields).  For each field:

    - GFK-target (``isinstance(field, GenericForeignKey)``) → skip (stays full-load
      bare string).  **This check runs BEFORE** any ``get_related_model`` call
      (GAP-3 ordering invariant).
    - ``kind == "select"`` → recurse with dotted prefix (discover nested prefetches
      under a select_related path).
    - ``kind == "prefetch"`` → call ``_compute_child_only``; omit if ``None`` (full-load).

    Args:
        model: The Django model class at the current position.
        selection_set: The GraphQL SelectionSetNode to walk.
        fragments: Fragment definitions keyed by name.
        _prefix: Dotted ORM path prefix accumulated during descent.
        _out: The accumulating map mutated in place.

    Returns:
        The completed ``{dotted_lookup: PrefetchPlan}`` dict.
    """
    if _out is None:
        _out = {}

    rel_map = _relation_field_map(model)

    for field in selection_set.selections:
        if isinstance(field, FragmentSpreadNode):
            fragment = fragments.get(field.name.value) if fragments else None
            if fragment is not None:
                _collect_prefetch_only_sets(
                    model, fragment.selection_set, fragments, _prefix, _out
                )
            continue
        if isinstance(field, InlineFragmentNode):
            _collect_prefetch_only_sets(
                model, field.selection_set, fragments, _prefix, _out
            )
            continue

        name = field.name.value
        snake = to_snake_case(name)
        sub_selection = getattr(field, "selection_set", None)

        related_field = rel_map.get(name, rel_map.get(snake, None))
        if related_field is None:
            # Concrete leaf, plumbing field, or wrapper field.
            if sub_selection is not None and name.lower() not in _PLUMBING_FIELDS:
                # Transparent wrapper field (e.g. "results"): recurse same model.
                _collect_prefetch_only_sets(
                    model, sub_selection, fragments, _prefix, _out
                )
            continue

        # GAP-3 ordering invariant: GFK-target check MUST come FIRST, BEFORE any
        # get_related_model / _leaf_model call (GFK.remote_field is None ->
        # AttributeError if passed to get_related_model).
        if isinstance(related_field, GenericForeignKey):
            continue  # stays full-load bare string

        optimization = _relation_optimization(related_field)
        if optimization is None:
            continue
        kind, orm_name = optimization
        lookup = _prefix + orm_name

        if kind == "select":
            # Descend into the select_related span to discover any nested
            # prefetch lookups under it (their dotted lookup carries the prefix).
            if sub_selection is not None:
                child_model = get_related_model(related_field)
                _collect_prefetch_only_sets(
                    child_model, sub_selection, fragments, lookup + LOOKUP_SEP, _out
                )
            continue

        # kind == "prefetch": reverse FK / forward M2M / reverse M2M / GenericRelation
        child_model = get_related_model(related_field)
        plan = _compute_child_only(child_model, related_field, sub_selection, fragments)
        if plan is not None:
            _out[lookup] = plan

    return _out


def _narrow_plain_prefetch(
    model: type[Model],
    lookup: str,
    only_map: dict[str, PrefetchPlan],
) -> str | Prefetch:
    """Convert a plain-string prefetch lookup to a narrowed ``Prefetch`` if a plan exists.

    Args:
        model: The root model class (used to resolve the leaf model for dotted
            lookups via ``_leaf_model``).
        lookup: The plain-string prefetch lookup (may be dotted).
        only_map: The ``{lookup: PrefetchPlan}`` map from
            ``_collect_prefetch_only_sets``.

    Returns:
        The bare ``lookup`` string when no plan exists (full load), or a
        ``Prefetch(lookup, queryset=...)`` with ``.only()`` (and optionally
        ``.select_related()``) applied.
    """
    if lookup not in only_map:
        return lookup

    plan = only_map[lookup]
    child = _leaf_model(model, lookup)
    qs = child._default_manager.all()
    if plan.child_select:
        qs = qs.select_related(*plan.child_select)
    qs = qs.only(*plan.only_cols)
    return Prefetch(lookup, queryset=qs)


def _nested_list_field_instance(field_def: Any) -> Any | None:
    """Recover the DjangoNestedListObjectField behind a GraphQL field.

    Args:
        field_def: The GraphQL field definition to inspect.

    Returns:
        The DjangoNestedListObjectField instance, or None if the field is not
        backed by one.
    """
    resolve = getattr(field_def, "resolve", None)
    func = getattr(resolve, "func", None)  # functools.partial -> bound method
    inst = getattr(func, "__self__", None)
    from .fields import DjangoNestedListObjectField

    if isinstance(inst, DjangoNestedListObjectField):
        return inst
    return None


def _resolve_results_paginator(
    results_field_def: Any,
) -> Any | None:
    """Defensively resolve the paginator instance from a ``results`` field definition.

    Implements the G2 fail-loud guard (ADR-3 step 4): every attribute lookup is
    guarded so that a custom resolver (whose bound object is NOT a
    ``GenericPaginationField``) returns ``None`` instead of raising
    ``AttributeError``.  A bare attribute access would crash the whole query
    with a 500 when ``OPTIMIZER_SAFE_MODE`` is ``False`` (the default).

    Args:
        results_field_def: The GraphQL field definition for the ``results``
            sub-field of a ``DjangoNestedListObjectField``.

    Returns:
        The ``BaseDjangoGraphqlPagination`` instance, or ``None`` if the
        resolver is custom / not the default ``GenericPaginationField`` shape.
    """
    from .paginations.pagination import BaseDjangoGraphqlPagination

    resolve_fn = getattr(results_field_def, "resolve", None)
    func = getattr(resolve_fn, "func", None)  # functools.partial → bound method
    bound = getattr(func, "__self__", None)  # the GenericPaginationField, or None
    paginator = getattr(bound, "paginator_instance", None)
    if not isinstance(paginator, BaseDjangoGraphqlPagination):
        return None
    return paginator


def _walk_window_params(
    inst: Any,
    field: Any,
    sub_gql: GraphQLObjectType | None,
    info: GraphQLResolveInfo,
) -> tuple[Any, Any, Any, Any] | None:
    """Extract window-slice parameters from a ``DjangoNestedListObjectField`` AST node.

    Descends one level into the selection set to find the ``results`` sub-field,
    extracts pagination kwargs via ``get_argument_values``, resolves the paginator
    via the G2 fail-loud guard, and calls ``prefetch_window_slice``.

    Wired into the live ``_walk_filtered_prefetches`` path in C3.

    Args:
        inst: The ``DjangoNestedListObjectField`` instance.
        field: The ``FieldNode`` for the nested list field in the AST.
        sub_gql: The ``GraphQLObjectType`` for the nested list type, or ``None``.
        info: The GraphQL resolve info.

    Returns:
        ``(slice_tuple, related_field, results_field_node, paginator)`` when
        the window path is viable, or ``None`` to signal a fallback to
        ``build_prefetch``.
    """
    if sub_gql is None or field.selection_set is None:
        return None

    # Locate the ``results`` sub-field name on the nested list type.
    results_name = getattr(
        getattr(inst.type, "_meta", None), "results_field_name", None
    )
    if results_name is None:
        return None

    # Descend into the selection set to find the results FieldNode.
    results_field_node = None
    for sel in field.selection_set.selections:
        node_name = getattr(getattr(sel, "name", None), "value", None)
        if node_name is not None and (
            node_name == results_name or to_snake_case(node_name) == results_name
        ):
            results_field_node = sel
            break

    if results_field_node is None:
        # Client did not select the results sub-field → fall back.
        return None

    # Get the GraphQL field definition for the results sub-field.
    results_field_def = sub_gql.fields.get(results_name) or sub_gql.fields.get(
        results_field_node.name.value
    )
    if results_field_def is None:
        return None

    # G2 fail-loud guard: resolve paginator defensively.
    paginator = _resolve_results_paginator(results_field_def)
    if paginator is None:
        return None

    # Extract pagination kwargs from the results sub-field's arguments.
    page_args = get_argument_values(
        results_field_def, results_field_node, info.variable_values or {}
    )
    slice_tuple = paginator.prefetch_window_slice(**page_args)

    # Resolve the relation field on the parent model.
    # inst.accessor is the name used for the reverse FK.
    # We need the ManyToOneRel (or other relation) from the parent model.
    # The parent model is not available here; the caller provides it via
    # related_field when calling build_window_prefetch.
    return (slice_tuple, results_field_node, page_args, paginator)


def _walk_filtered_prefetches(
    gql_type: GraphQLObjectType | None,
    model: type[Model] | None,
    selection_set: SelectionSetNode,
    prefix: str,
    info: GraphQLResolveInfo,
    out: list[Any],
    seen: dict[str, int],
) -> None:
    """Collect filtered Prefetch objects for nested list fields with filters.

    Args:
        gql_type: The GraphQL object type at the current position.
        model: The Django model class at the current position, if known.
        selection_set: The GraphQL selection set to walk.
        prefix: The dotted ORM lookup prefix for the current position.
        info: The GraphQL resolve info for the current field.
        out: The accumulating list of Prefetch objects, mutated in place.
        seen: A counter of how often each lookup was produced, mutated in
            place.
    """
    relation_map = _relation_field_map(model) if model is not None else {}

    for field in selection_set.selections:
        if isinstance(field, FragmentSpreadNode):
            fragment = info.fragments.get(field.name.value) if info.fragments else None
            if fragment is not None:  # pragma: no branch
                _walk_filtered_prefetches(
                    gql_type, model, fragment.selection_set, prefix, info, out, seen
                )
            continue
        if isinstance(field, InlineFragmentNode):
            _walk_filtered_prefetches(
                gql_type, model, field.selection_set, prefix, info, out, seen
            )
            continue

        name = field.name.value
        field_def = gql_type.fields.get(name) if gql_type is not None else None
        if field_def is None:
            continue
        sub_gql = get_named_type(field_def.type)
        sub_gql = sub_gql if isinstance(sub_gql, GraphQLObjectType) else None

        inst = _nested_list_field_instance(field_def)
        if inst is not None:
            lookup = prefix + inst.accessor
            args = get_argument_values(field_def, field, info.variable_values or {})
            filter_value = args.get("filter")

            # C3: attempt window-slice path (fires for both filtered and unfiltered
            # nested lists when the paginator and relation support it).
            window_params = _walk_window_params(inst, field, sub_gql, info)
            if window_params is not None:
                slice_tuple, results_field_node, _page_args, _paginator = window_params
                # Resolve the related_field from the parent model's relation map.
                related_field = relation_map.get(
                    inst.accessor,
                    relation_map.get(to_snake_case(inst.accessor)),
                )
                sub_selection = getattr(results_field_node, "selection_set", None)
                pf = inst.build_window_prefetch(
                    lookup,
                    filter_value,
                    slice_tuple,
                    related_field,
                    sub_selection,
                    info.fragments or {},
                )
                if pf is not None:
                    # Tag the parent model+lookup so list_resolver can distinguish
                    # a window-sliced empty cache from a zero-child empty cache.
                    out.append(pf)
                    seen[lookup] = seen.get(lookup, 0) + 1
                    if field.selection_set and sub_gql is not None:  # pragma: no branch
                        _walk_filtered_prefetches(
                            sub_gql,
                            inst.type._meta.model,
                            field.selection_set,
                            lookup + LOOKUP_SEP,
                            info,
                            out,
                            seen,
                        )
                    continue
                # Window path declined (pre-checks failed) → fall through to plain path.

            # Plain path: build a filtered Prefetch only when a filter is applied.
            if filter_value:
                out.append(inst.build_prefetch(lookup, filter_value, info))
                seen[lookup] = seen.get(lookup, 0) + 1
            if field.selection_set and sub_gql is not None:  # pragma: no branch
                _walk_filtered_prefetches(
                    sub_gql,
                    inst.type._meta.model,
                    field.selection_set,
                    lookup + LOOKUP_SEP,
                    info,
                    out,
                    seen,
                )
            continue

        related_field = relation_map.get(name, relation_map.get(to_snake_case(name)))
        if related_field is not None and field.selection_set and sub_gql is not None:
            optimization = _relation_optimization(related_field)
            if optimization is not None and not isinstance(
                related_field, GenericForeignKey
            ):  # pragma: no branch
                _walk_filtered_prefetches(
                    sub_gql,
                    get_related_model(related_field),
                    field.selection_set,
                    prefix + optimization[1] + LOOKUP_SEP,
                    info,
                    out,
                    seen,
                )
            continue

        if field.selection_set and sub_gql is not None:
            # Wrapper field (results / pageInfo): same model and prefix.
            _walk_filtered_prefetches(
                sub_gql, model, field.selection_set, prefix, info, out, seen
            )


def build_filtered_prefetches(info: GraphQLResolveInfo) -> list[Any]:
    """Build filtered Prefetch objects for the nested list fields in the query.

    A nested list field carrying filter arguments is fetched in a single
    filtered Prefetch for all parents (instead of one query per parent). This
    walks the GraphQL return type and the selection AST together to map each
    filtered nested list to its dotted ORM lookup.

    Args:
        info: The GraphQL resolve info for the current field.

    Returns:
        The list of filtered Prefetch objects, one per uniquely filtered
        nested list lookup.
    """
    return_type = get_named_type(info.return_type)
    field_nodes = info.field_nodes
    if not field_nodes or not isinstance(return_type, GraphQLObjectType):
        return []
    field_node = field_nodes[0]
    if not field_node.selection_set:
        return []

    graphene_type = getattr(return_type, "graphene_type", None)
    model = getattr(getattr(graphene_type, "_meta", None), "model", None)

    out = []
    seen = {}
    _walk_filtered_prefetches(
        return_type, model, field_node.selection_set, "", info, out, seen
    )
    # Drop lookups that appeared more than once (aliased fields with different
    # filters): fall back to the per-parent path for those, for correctness.
    return [p for p in out if seen.get(p.prefetch_through, 0) == 1]


def _merge_filtered_prefetches(
    prefetch_related: list[str], filtered_prefetches: list[Any]
) -> tuple[list[str], list[Any]]:
    """Re-root prefetches under a filtered Prefetch into its own queryset.

    Django forbids the same lookup appearing with two different querysets, so a
    plain prefetch ("posts__comments") cannot sit beside a filtered
    Prefetch("posts", ...). Re-root every prefetch (plain string or filtered
    Prefetch) that lives under a filtered lookup into that filtered Prefetch's
    queryset, which also optimizes the deeper level.

    Args:
        prefetch_related: The accumulated plain prefetch lookup strings.
        filtered_prefetches: The filtered Prefetch objects for nested lists.

    Returns:
        The top-level (plain prefetch strings, filtered Prefetch objects) to
        apply directly; deeper ones are nested into their parent's queryset.
    """
    if not filtered_prefetches:
        return prefetch_related, filtered_prefetches

    throughs = [pf.prefetch_through for pf in filtered_prefetches]
    by_through = {pf.prefetch_through for pf in filtered_prefetches}

    def nearest(path: str) -> str | None:
        best = None
        for through in throughs:
            if path != through and path.startswith(through + LOOKUP_SEP):
                if best is None or len(through) > len(best):
                    best = through
        return best

    def strip(path: str, ancestor: str) -> str:
        return path[len(ancestor) + len(LOOKUP_SEP) :]

    plain_children: dict[str, list[str]] = {}
    top_plain: list[str] = []
    for path in prefetch_related:
        if path in by_through:
            continue  # the filtered Prefetch supersedes the plain lookup
        ancestor = nearest(path)
        if ancestor is None:
            top_plain.append(path)
        else:
            plain_children.setdefault(ancestor, []).append(strip(path, ancestor))

    filtered_children: dict[str, list[Any]] = {}
    top_filtered: list[Any] = []
    for pf in filtered_prefetches:
        ancestor = nearest(pf.prefetch_through)
        if ancestor is None:
            top_filtered.append(pf)
        else:
            filtered_children.setdefault(ancestor, []).append(pf)

    # Materialize bottom-up so a parent captures already-finalized children.
    for pf in sorted(
        filtered_prefetches,
        key=lambda p: p.prefetch_through.count(LOOKUP_SEP),
        reverse=True,
    ):
        children: list[Any] = list(plain_children.get(pf.prefetch_through, []))
        for child in filtered_children.get(pf.prefetch_through, []):
            children.append(
                Prefetch(
                    strip(child.prefetch_through, pf.prefetch_through),
                    queryset=child.queryset,
                )
            )
        if children:
            pf.queryset = pf.queryset.prefetch_related(*children)

    return top_plain, top_filtered


def _apply_optimizations(
    base: QuerySet,
    model: type[Model],
    info: GraphQLResolveInfo,
    kwargs: dict[str, Any],
    custom_used: bool,
) -> QuerySet:
    """Apply select_related, prefetch_related and .only() to *base*.

    This helper is extracted from ``queryset_factory`` so that the optional
    ``OPTIMIZER_SAFE_MODE`` try/except boundary can wrap the entire block in
    one place without duplication.

    Args:
        base: The starting queryset.
        model: The Django model class for ``base``.
        info: The GraphQL resolve info for the current field.
        kwargs: The resolver arguments, used to seed relation joins.
        custom_used: Whether a custom resolver already supplied ``base``.

    Returns:
        The optimized queryset (may be the same object or a new one).
    """
    relation_map = _relation_field_map(model)
    select_related: list[str] = []
    prefetch_related: list[str] = []

    # Filter kwargs that traverse relations (e.g. ``author__name``) also seed
    # the joins so filtering does not trigger extra queries.
    for key in kwargs.keys():
        head = key.split(LOOKUP_SEP, 1)[0]
        related_field = relation_map.get(
            head, relation_map.get(to_snake_case(head), None)
        )
        if related_field is not None:
            optimization = _relation_optimization(related_field)
            if optimization is not None:  # pragma: no branch
                kind, orm_name = optimization
                target = select_related if kind == "select" else prefetch_related
                if orm_name not in target:
                    target.append(orm_name)

    fields_asts = info.field_nodes
    if fields_asts:
        recursive_params(
            fields_asts[0].selection_set,
            info.fragments,
            relation_map,
            select_related,
            prefetch_related,
        )

    # Drop any select_related path that crosses a prefetch boundary.
    # recursive_params descends unconditionally into ALL sub-selections, so a
    # query like "allAuthors { posts { category { title } } }" produces BOTH
    # "posts" in prefetch_related AND "posts__category" in select_related.
    # Applying select_related("posts__category") to the Author queryset raises
    # "Invalid field name(s) given in select_related: 'posts'" because "posts"
    # is a reverse FK (prefetch-only).  Phase B handles these sub-select_related
    # paths at the child-queryset level via _compute_child_only's child_select
    # derivation.  Safe to drop them here.
    if prefetch_related and select_related:
        prefetch_prefixes = {p + LOOKUP_SEP for p in prefetch_related}
        select_related = [
            sr
            for sr in select_related
            if not any(sr.startswith(pfx) for pfx in prefetch_prefixes)
        ]

    # Filtered nested lists are fetched once for all parents via a filtered
    # Prefetch. Anything prefetched *under* a filtered lookup is re-rooted into
    # that Prefetch's own queryset (Django forbids the same lookup with two
    # different querysets), which also optimizes the deeper level.
    filtered_prefetches = build_filtered_prefetches(info) if fields_asts else []
    prefetch_related, filtered_prefetches = _merge_filtered_prefetches(
        prefetch_related, filtered_prefetches
    )

    # Phase B: narrow each top_plain prefetch string to a Prefetch(…).only(…).
    # STRICTLY AFTER _merge_filtered_prefetches (REQ-B5): the merge runs on
    # plain strings; conversion happens only on the returned top_plain list.
    # Gated identically to root .only() (OPTIMIZE_ONLY_FIELDS + not custom_used).
    if (
        graphql_api_settings.OPTIMIZE_ONLY_FIELDS
        and not custom_used
        and fields_asts
        and prefetch_related
    ):
        only_map = _collect_prefetch_only_sets(
            model, fields_asts[0].selection_set, info.fragments
        )
        if only_map:
            prefetch_related = [
                _narrow_plain_prefetch(model, lk, only_map) for lk in prefetch_related
            ]

    if select_related:
        base = base.select_related(*select_related)
    if prefetch_related:
        base = base.prefetch_related(*prefetch_related)
    if filtered_prefetches:
        base = base.prefetch_related(*filtered_prefetches)

    if graphql_api_settings.OPTIMIZE_ONLY_FIELDS and not custom_used and fields_asts:
        only_fields = _collect_only_fields(
            model, fields_asts[0].selection_set, info.fragments
        )
        if only_fields:  # pragma: no branch
            base = base.only(*only_fields)

    return base


def queryset_factory(
    manager: Any, root: Any, info: GraphQLResolveInfo, **kwargs: Any
) -> QuerySet:
    """Build a queryset optimized for the requested GraphQL selection.

    This applies nested "select_related" / "prefetch_related" (eliminating the
    N+1 problem for related objects) and, when "OPTIMIZE_ONLY_FIELDS" is on, a
    conservative ".only()" column projection. It honors a custom
    "resolve_<field>" that returns a QuerySet. Behavior is controlled by the
    "OPTIMIZE_QUERYSET" and "OPTIMIZE_ONLY_FIELDS" settings.

    Args:
        manager: A Django model, manager, or queryset to start from.
        root: The root value passed to the resolver.
        info: The GraphQL resolve info for the current field.
        **kwargs: The resolver arguments, used to seed relation joins.

    Returns:
        The optimized queryset.
    """
    base = _get_queryset(manager)
    model = base.model

    custom_used = False
    custom_resolver = _get_custom_resolver(info)
    if custom_resolver is not None:
        produced = custom_resolver(root, info, **kwargs)
        if isinstance(produced, QuerySet):
            base = produced
            model = base.model
            custom_used = True

    if not graphql_api_settings.OPTIMIZE_QUERYSET:
        return base

    if graphql_api_settings.OPTIMIZER_SAFE_MODE:
        try:
            base = _apply_optimizations(base, model, info, kwargs, custom_used)
        except Exception as exc:  # noqa: BLE001 - intentional broad degrade guard
            logging.getLogger("django_graphex.utils").warning(
                "Queryset optimization failed for %s; serving un-optimized "
                "queryset (OPTIMIZER_SAFE_MODE). %r",
                model.__name__,
                exc,
            )
            return base
    else:
        base = _apply_optimizations(base, model, info, kwargs, custom_used)

    return _get_queryset(base)


def parse_validation_exc(validation_exc: Any) -> list[dict[str, Any]]:
    """Parse a Django validation exception into a structured error list.

    Args:
        validation_exc: The Django validation exception to parse.

    Returns:
        A list of "{field, messages}" dictionaries, one per error.
    """
    errors_list = []
    for key, value in validation_exc.error_dict.items():
        for exc in value:
            errors_list.append({"field": key, "messages": exc.messages})

    return errors_list
