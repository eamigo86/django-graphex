"""Nested INPUT fields must be pruned by the child's write permissions.

With "PERMISSION_SCOPED_SCHEMA" the pruner removes a child's own mutation root
when the caller may not write it, but it cloned every input object type
verbatim -- so the parent's "entries: [...]" nested input field survived and the
same write was still reachable through the parent's payload. The security
feature closed the front door and left the back door open.

Invariants asserted here:

* a caller lacking the child's write permission no longer sees the parent's
  nested input field,
* a caller HOLDING it still does -- which only works if the child's write label
  is part of the schema label-set, because the pruner's caller intersects the
  caller's permissions with that set before pruning,
* a child reachable ONLY through a nested input contributes its write label to
  that set (the roots alone never mention it),
* the FULL schema is unchanged on the wire: labeling is invisible in the SDL.
"""

from __future__ import annotations

from typing import Any, ClassVar

from graphql import get_named_type, print_schema

from django_graphex.core import ObjectType
from django_graphex.core.registry_compiler import compile_all_outputs
from django_graphex.core.schema_pruner import prune_schema
from django_graphex.permissions import DjangoModelPermissions
from django_graphex.schema import DjangoGraphQLSchema
from django_graphex.types import DjangoModelType
from tests.models import NestedPermBlog, NestedPermEntry

_VIEW_BLOG = "tests.view_nestedpermblog"
_ADD_BLOG = "tests.add_nestedpermblog"
_VIEW_ENTRY = "tests.view_nestedpermentry"
_ADD_ENTRY = "tests.add_nestedpermentry"


class _EntryType(DjangoModelType):
    """The child's own type: gated, and never mounted on a root.

    Its only reachable surface is the parent's nested input field, which is
    exactly the configuration the pruner used to leave unguarded.
    """

    permission_classes: ClassVar[tuple[Any, ...]] = (DjangoModelPermissions,)

    class Meta:
        """Bind the type to "NestedPermEntry"."""

        model = NestedPermEntry


class _BlogType(DjangoModelType):
    """The nesting parent, gated by the same model-permission stack."""

    permission_classes: ClassVar[tuple[Any, ...]] = (DjangoModelPermissions,)

    class Meta:
        """Bind the type to "NestedPermBlog" with "entries" nested."""

        model = NestedPermBlog
        nested_fields = {"entries": NestedPermEntry}


class _Query(ObjectType):
    """Root exposing only the parent's retrieve field."""

    blog_retrieve = _BlogType.RetrieveField()


class _Mutation(ObjectType):
    """Root exposing only the parent's create field."""

    blog_create = _BlogType.CreateField()


compile_all_outputs()
_schema = DjangoGraphQLSchema(query=_Query, mutation=_Mutation).graphql_schema


def _label_set() -> frozenset[str]:
    """Return the built schema's projection target for the pruner.

    Returns:
        The "gdx_label_set" the view intersects a caller's permissions with.
    """
    return frozenset((_schema.extensions or {}).get("gdx_label_set") or ())


def _nested_field_names(*granted: str) -> set[str]:
    """Return the parent's create-input field names as the caller would see them.

    Mirrors "PrunedSchemaCache.get" exactly: the granted set is intersected
    with the schema label-set BEFORE pruning, so a label missing from the set
    is stripped and its field disappears for everyone.

    Args:
        *granted: The permission codenames the caller holds.

    Returns:
        The field names of the pruned parent create input type.
    """
    pruned = prune_schema(_schema, frozenset(granted) & _label_set())
    create_field = pruned.mutation_type.fields["blogCreate"]
    (argument,) = create_field.args.values()
    return set(get_named_type(argument.type).fields)


class TestPermissionScopedNestedInput:
    """The nested input field is gated by the CHILD's write permission.

    Both directions are asserted on purpose: a pruner that simply deletes the
    nested field for everybody would satisfy the denial case alone.
    """

    def test_nested_input_pruned_without_the_childs_write_perm(self) -> None:
        """A caller who may not create the child must not see the nested field.

        This test breaks if input object types are cloned verbatim: the child's
        own root is pruned away while the parent's nested payload still reaches
        the same write.
        """
        fields = _nested_field_names(_VIEW_BLOG, _ADD_BLOG, _VIEW_ENTRY)
        assert "title" in fields
        assert "entries" not in fields

    def test_nested_input_kept_with_the_childs_write_perm(self) -> None:
        """A caller who holds the child's write permission still sees the field.

        This test breaks if the child's write label never enters the schema
        label-set: it is stripped from the granted set before the pruner runs,
        so the field vanishes for holders too -- a self-inflicted outage.
        """
        fields = _nested_field_names(_VIEW_BLOG, _ADD_BLOG, _VIEW_ENTRY, _ADD_ENTRY)
        assert "entries" in fields

    def test_label_set_covers_a_nesting_only_child(self) -> None:
        """The child's write label reaches the label-set with no root of its own.

        This test breaks if the label-set is computed from root fields and
        output types only, which never mention a nesting-only child's writes.
        """
        assert _ADD_ENTRY in _label_set()

    def test_full_schema_sdl_is_unchanged(self) -> None:
        """Labeling an input field must be invisible on the wire.

        This test breaks if the stamp alters the printed schema for a project
        that never turns the feature on.
        """
        sdl = print_schema(_schema)
        assert "entries: [" in sdl
