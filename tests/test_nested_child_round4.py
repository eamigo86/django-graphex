"""Round-4 hardening of the nested-write gate.

A third adversarial pass found that the previous round fixed some seams by
moving them:

* the nested input field's permission stamp CONSULTED the child host's
  "required_perms", which governs that host's OWN root fields. An ordinary read
  host labelled with a view permission therefore collapsed the nested WRITE
  stamp to a READ one -- strictly wider than before the round,
* the zero-field child input had two more roads to it (an overlap that is
  nothing but the primary key, and one host's "only_fields" annihilated by
  another's "exclude_fields"). Round 6 removed the first by unioning the
  allowance axis; the second is what a PROHIBITION beating an allowance means,
  and is pinned here as such,
* the projection merge was operation-blind, so a create-only host and an
  update-only host for one child poisoned each other's nested surface,
* the "supported_kwargs" narrowing was applied around
  "has_<action>_permission", which takes "**kwargs" -- so the extras still
  reached "has_permission", the DOCUMENTED primary override point, unfiltered,
* nothing pinned the "supported_kwargs" narrowing at the "authorize" seam.

It also pins one thing the pass found on the way past: "required_perms" cannot
be written on a "DjangoModelType" the way the guides spell it, because the base
never declared the "ClassVar" its Pydantic metaclass needs.
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any, ClassVar

import pytest
from graphql import get_named_type

from django_graphex.core import ObjectType
from django_graphex.core.registry_compiler import compile_all_outputs
from django_graphex.core.schema_pruner import prune_schema
from django_graphex.mutation import DjangoModelMutation, nested_child_input
from django_graphex.permissions import BasePermission, DjangoModelPermissions
from django_graphex.registry import get_global_registry
from django_graphex.schema import DjangoGraphQLSchema
from django_graphex.types import DjangoModelType
from tests.models import (
    NestedR4AuthKid,
    NestedR4AuthOwner,
    NestedR4BuildKid,
    NestedR4BuildOwner,
    NestedR4LabelHost,
    NestedR4OpKid,
    NestedR4OpOwner,
    NestedR4PkKid,
    NestedR4PkOwner,
    NestedR4PolicyKid,
    NestedR4PolicyOwner,
    NestedR4ReadKid,
    NestedR4ReadOwner,
    NestedR4XKid,
    NestedR4XOwner,
)


# --------------------------------------------------------------------------- #
# The nested stamp is a WRITE stamp, not the host's own root label.            #
# --------------------------------------------------------------------------- #
class NestedR4ReadKidType(DjangoModelType):
    """An ordinary read host for the child, labelled with a READ permission."""

    permission_classes: ClassVar[tuple[Any, ...]] = (DjangoModelPermissions,)
    #: What the child's own retrieve root requires. It says nothing about who
    #: may WRITE the child through a parent.
    required_perms: ClassVar[tuple[str, ...]] = ("tests.view_nestedr4readkid",)

    class Meta:
        """Bind the type to "NestedR4ReadKid"."""

        model = NestedR4ReadKid


class NestedR4ReadOwnerType(DjangoModelType):
    """The parent nesting the read-labelled child."""

    permission_classes: ClassVar[tuple[Any, ...]] = (DjangoModelPermissions,)

    class Meta:
        """Bind the type to "NestedR4ReadOwner" with "kids" nested."""

        model = NestedR4ReadOwner
        nested_fields = {"kids": NestedR4ReadKid}


class _Query(ObjectType):
    """Root exposing the child's own read field."""

    r4_read_kid_retrieve = NestedR4ReadKidType.RetrieveField()


class _Mutation(ObjectType):
    """Root exposing the parent whose input the pruner is asked about."""

    r4_read_owner_create = NestedR4ReadOwnerType.CreateField()


compile_all_outputs()
_schema = DjangoGraphQLSchema(query=_Query, mutation=_Mutation).graphql_schema


def _perms(model: Any, *verbs: str) -> set[str]:
    """Return the Django permission codenames for a model and verbs.

    Args:
        model: The Django model the codenames target.
        *verbs: The permission verbs ("view", "add", "change").

    Returns:
        The "{app_label}.{verb}_{model_name}" codenames.
    """
    opts = model._meta
    return {f"{opts.app_label}.{verb}_{opts.model_name}" for verb in verbs}


def _input_fields(granted: set[str], root: str) -> set[str]:
    """Return the field names of a pruned mutation root's input argument.

    Args:
        granted: The permission codenames the caller holds.
        root: The mutation field name to inspect.

    Returns:
        The input object type's field names.
    """
    label_set = frozenset((_schema.extensions or {}).get("gdx_label_set") or ())
    pruned = prune_schema(_schema, frozenset(granted) & label_set)
    (argument,) = pruned.mutation_type.fields[root].args.values()
    return set(get_named_type(argument.type).fields)


class TestNestedStampIsAWriteStamp:
    """The child host's "required_perms" must not reach the nested input."""

    def test_read_label_does_not_replace_the_childs_write_stamp(self) -> None:
        """A view-only host label must not open the nested WRITE surface.

        "required_perms" governs the host's OWN root fields. Honouring it on the
        nested input field lets the single most common shape -- a read host
        labelled with a view permission -- hand a caller holding nothing but
        that view permission a working write of the child through its parent.
        This test breaks if the stamp consults the host override again.
        """
        granted = _perms(NestedR4ReadOwner, "view", "add") | _perms(
            NestedR4ReadKid, "view"
        )
        assert "kids" not in _input_fields(granted, "r4ReadOwnerCreate")

    def test_the_field_survives_for_a_caller_who_may_write_the_child(self) -> None:
        """The composite default is still satisfiable.

        This test breaks if the stamp is widened into something no caller can
        hold -- a self-inflicted outage rather than a fix.
        """
        granted = _perms(NestedR4ReadOwner, "view", "add") | _perms(
            NestedR4ReadKid, "view", "add"
        )
        assert "kids" in _input_fields(granted, "r4ReadOwnerCreate")


# --------------------------------------------------------------------------- #
# The two projection axes meet on the RESULT, not on either axis alone.       #
# --------------------------------------------------------------------------- #
class NestedR4PkKidTypeA(DjangoModelType):
    """One host of the primary-key-only overlap fixture."""

    class Meta:
        """Bind the type to "NestedR4PkKid"."""

        model = NestedR4PkKid
        only_fields = ("id", "headline")


class NestedR4PkKidMutationB(DjangoModelMutation):
    """The other host: the overlap is the primary key and nothing else."""

    class Meta:
        """Bind the mutation to "NestedR4PkKid"."""

        model = NestedR4PkKid
        model_operations = ("create",)
        only_fields = ("id", "tagline")


class NestedR4PkOwnerMutation(DjangoModelMutation):
    """The parent nesting the primary-key-only overlap child."""

    class Meta:
        """Bind the mutation to "NestedR4PkOwner" with "kids" nested."""

        model = NestedR4PkOwner
        model_operations = ("create",)
        nested_fields = {"kids": NestedR4PkKid}


class NestedR4XKidType(DjangoModelType):
    """One host EXPOSING the field its sibling hides, plus one it does not."""

    class Meta:
        """Bind the type to "NestedR4XKid"."""

        model = NestedR4XKid
        only_fields = ("headline", "tagline")


class NestedR4XKidMutation(DjangoModelMutation):
    """The other host, HIDING the only field its sibling exposes."""

    class Meta:
        """Bind the mutation to "NestedR4XKid"."""

        model = NestedR4XKid
        model_operations = ("create",)
        exclude_fields = ("headline",)


class NestedR4XOwnerMutation(DjangoModelMutation):
    """The parent nesting the annihilated-projection child."""

    class Meta:
        """Bind the mutation to "NestedR4XOwner" with "kids" nested."""

        model = NestedR4XOwner
        model_operations = ("create",)
        nested_fields = {"kids": NestedR4XKid}


class TestTheTwoAxesMeetOnTheResult:
    """The allowance union and the prohibition union are merged, not checked."""

    def test_a_primary_key_only_overlap_is_no_longer_a_dead_end(self) -> None:
        """Unioning the allowance axis removes this road entirely.

        Each host allows the primary key plus one column of its own; the union
        keeps both columns, and the create input simply drops the "id" it never
        carries. This test breaks if the allowance axis goes back to an
        intersection, whose only shared name here is one the input cannot emit.
        """
        built = nested_child_input(
            NestedR4PkKid, "create", get_global_registry(), NestedR4PkOwner
        )
        assert set(built._meta.graphql_input_type.fields) == {"headline", "tagline"}

    def test_a_siblings_exclude_fields_still_beats_the_allowance_union(
        self,
    ) -> None:
        """A PROHIBITION subtracts from the union, and is applied LAST.

        One host allows two columns, one of which its sibling forbids for every
        operation. The prohibition wins -- that is the security property the
        union must not weaken -- and only the other column survives. This test
        breaks if an exclusion stops applying across hosts that do not declare
        it, or if the two axes are merged in the other order. (Emptying the
        result outright is refused at build time; see
        "tests/test_nested_child_round7.py".)
        """
        built = nested_child_input(
            NestedR4XKid, "create", get_global_registry(), NestedR4XOwner
        )
        assert set(built._meta.graphql_input_type.fields) == {"tagline"}


# --------------------------------------------------------------------------- #
# The projection merge respects each host's "model_operations".               #
# --------------------------------------------------------------------------- #
class NestedR4OpKidCreateMutation(DjangoModelMutation):
    """A create-only host for the child."""

    class Meta:
        """Bind the mutation to "NestedR4OpKid" for "create" only."""

        model = NestedR4OpKid
        model_operations = ("create",)
        only_fields = ("title", "body")


class NestedR4OpKidUpdateMutation(DjangoModelMutation):
    """An update-only host for the same child, projecting less."""

    class Meta:
        """Bind the mutation to "NestedR4OpKid" for "update" only."""

        model = NestedR4OpKid
        model_operations = ("update",)
        only_fields = ("body",)


class NestedR4OpOwnerMutation(DjangoModelMutation):
    """The parent nesting the split-surface child."""

    class Meta:
        """Bind the mutation to "NestedR4OpOwner" with "kids" nested."""

        model = NestedR4OpOwner
        nested_fields = {"kids": NestedR4OpKid}


class TestProjectionMergeIsOperationAware:
    """A host that does not serve an operation has no say over it."""

    def test_an_update_only_host_does_not_narrow_the_nested_create(self) -> None:
        """The child's own create accepts "title"; the nested one must too.

        This test breaks if the merge collects every host regardless of
        "Meta.model_operations": the update-only host's narrower projection then
        deletes a field the child's own create still accepts, so a client whose
        nested payload sends it gets a validation error the direct mutation
        never raises.
        """
        built = nested_child_input(
            NestedR4OpKid, "create", get_global_registry(), NestedR4OpOwner
        )
        assert "title" in built._meta.graphql_input_type.fields

    def test_a_create_only_host_does_not_widen_the_nested_update(self) -> None:
        """The other direction: the update host's projection still governs.

        This test breaks if the operation filter is applied so loosely that the
        create-only host's wider projection leaks into the update surface.
        """
        built = nested_child_input(
            NestedR4OpKid, "update", get_global_registry(), NestedR4OpOwner
        )
        assert "title" not in built._meta.graphql_input_type.fields


# --------------------------------------------------------------------------- #
# The projection merge must hold on a real schema build.                      #
# --------------------------------------------------------------------------- #
class NestedR4BuildKidTypeA(DjangoModelType):
    """One host of the build-path fixture."""

    class Meta:
        """Bind the type to "NestedR4BuildKid"."""

        model = NestedR4BuildKid
        only_fields = ("alpha",)


class NestedR4BuildKidMutationB(DjangoModelMutation):
    """The other host, agreeing with the first on nothing."""

    class Meta:
        """Bind the mutation to "NestedR4BuildKid"."""

        model = NestedR4BuildKid
        model_operations = ("create",)
        only_fields = ("beta",)


class NestedR4BuildOwnerType(DjangoModelType):
    """The parent nesting the contradictorily projected child."""

    class Meta:
        """Bind the type to "NestedR4BuildOwner" with "kids" nested."""

        model = NestedR4BuildOwner
        nested_fields = {"kids": NestedR4BuildKid}


class TestSplitProjectionsSurviveTheBuild:
    """The merge has to hold on the REAL build path, not just the direct call."""

    def test_schema_build_carries_the_union(self) -> None:
        """The nested child input is built inside a graphql-core fields thunk.

        The two hosts here agree on nothing, which used to abort the whole
        schema build. This test breaks if the allowance axis stops unioning, or
        if the thunk stops reaching the declared hosts at all.
        """

        class _BuildQuery(ObjectType):
            """Root exposing the parent's read field."""

            r4_build_owner_retrieve = NestedR4BuildOwnerType.RetrieveField()

        class _BuildMutation(ObjectType):
            """Root exposing the parent whose nested input the build resolves."""

            r4_build_owner_create = NestedR4BuildOwnerType.CreateField()

        compile_all_outputs()
        schema = DjangoGraphQLSchema(
            query=_BuildQuery, mutation=_BuildMutation
        ).graphql_schema

        child = schema.type_map["NestedR4BuildKidCreateInNestedR4BuildOwnerType"]
        assert set(child.fields) == {"alpha", "beta"}


# --------------------------------------------------------------------------- #
# The nested gate's calling convention, at BOTH seams.                        #
# --------------------------------------------------------------------------- #
class _ClosedHasPermission(BasePermission):
    """A policy overriding the DOCUMENTED primary hook with a closed signature.

    "has_permission" is what the guide tells a project to override to gate every
    action the same way, and "data=" was the only extra the contract ever
    forwarded. It GRANTS the write, so any failure here is a crash, not a
    denial.
    """

    def has_permission(
        self, info: Any, action: str, model: Any, data: Any = None
    ) -> bool:
        """Allow every action.

        Args:
            info: GraphQL resolve info for the current request.
            action: The CRUD action being checked.
            model: The Django model the action targets.
            data: The payload under validation.

        Returns:
            Always True.
        """
        return True


class NestedR4PolicyKidType(DjangoModelType):
    """The child whose policy cannot absorb an unknown keyword."""

    permission_classes: ClassVar[tuple[Any, ...]] = (_ClosedHasPermission,)

    class Meta:
        """Bind the type to "NestedR4PolicyKid"."""

        model = NestedR4PolicyKid


class NestedR4PolicyOwnerType(DjangoModelType):
    """The parent driving the closed-"has_permission" child."""

    class Meta:
        """Bind the type to "NestedR4PolicyOwner" with "kids" nested."""

        model = NestedR4PolicyOwner
        nested_fields = {"kids": NestedR4PolicyKid}


class NestedR4AuthKidType(DjangoModelType):
    """The child whose "authorize" override spells its arguments out."""

    class Meta:
        """Bind the type to "NestedR4AuthKid"."""

        model = NestedR4AuthKid

    @classmethod
    def authorize(cls, info: Any, action: str, data: Any = None) -> None:
        """Allow every action, the pre-"nested_parent" override shape.

        Args:
            info: GraphQL resolve info for the current request.
            action: The CRUD action being authorized.
            data: The payload under validation.
        """
        return


class NestedR4AuthOwnerType(DjangoModelType):
    """The parent driving the closed-"authorize" child."""

    class Meta:
        """Bind the type to "NestedR4AuthOwner" with "kids" nested."""

        model = NestedR4AuthOwner
        nested_fields = {"kids": NestedR4AuthKid}


def _info() -> SimpleNamespace:
    """Build a bare GraphQL resolve-info stand-in for direct resolver calls.

    Returns:
        An object shaped like a GraphQL resolve info, with a "context"
        carrying empty "META" and "FILES".
    """
    return SimpleNamespace(context=SimpleNamespace(META={}, FILES={}))


def _create(host: Any, data: dict[str, Any]) -> Any:
    """Invoke the generated "create" resolver of a type host.

    Args:
        host: The "DjangoModelType" class to call.
        data: The input payload, keyed by the host's input field name.

    Returns:
        The mutation result object (exposes "ok" and, on failure, "errors").
    """
    return host.create(None, _info(), **{host._meta.input_field_name: data})


@pytest.mark.django_db()
class TestNestedGateCallingConvention:
    """Neither seam may turn a GRANT into an uncaught "TypeError"."""

    def test_closed_has_permission_override_still_grants(self) -> None:
        """The extras must be narrowed where the call actually LANDS.

        "has_<action>_permission" declares "**kwargs", so narrowing against it
        forwards everything, and the base then splats it into "has_permission".
        This test breaks if the filtering is applied only at the outer call
        site: the nested path raises an uncaught "TypeError" -- an HTTP 500 --
        while the child's own root mutation keeps working.
        """
        result = _create(
            NestedR4PolicyOwnerType, {"name": "o", "kids": [{"headline": "h"}]}
        )
        assert result.ok, getattr(result, "errors", None)
        assert NestedR4PolicyKid.objects.get().headline == "h"

    def test_closed_authorize_override_still_grants(self) -> None:
        """The "authorize" seam of the same contract.

        This test breaks if the nested writer forwards "nested_parent" to an
        "authorize" override that spells its arguments out -- the shape the
        guides document and the changelog promises keeps working.
        """
        result = _create(
            NestedR4AuthOwnerType, {"name": "o", "kids": [{"headline": "h"}]}
        )
        assert result.ok, getattr(result, "errors", None)
        assert NestedR4AuthKid.objects.get().headline == "h"


# --------------------------------------------------------------------------- #
# "required_perms" must be declarable the way the guides spell it.            #
# --------------------------------------------------------------------------- #
class TestRequiredPermsOnAModelType:
    """The documented plain class attribute must survive class creation."""

    def test_a_plain_required_perms_class_attribute_is_accepted(self) -> None:
        """ "DjangoModelType" reads the attribute, so it must declare it.

        These classes are pydantic-backed, so an attribute the base never
        declares raises "PydanticUserError" at class-definition time -- the
        guides tell projects to write the plain form on the mutation fields a
        "DjangoModelType" generates, and only "DjangoModelMutation" declared it.
        This test breaks if the "ClassVar" is dropped again.
        """

        class NestedR4LabelHostType(DjangoModelType):
            """A host labelling its own generated fields."""

            required_perms = ("tests.publish_nestedr4labelhost",)

            class Meta:
                """Bind the type to "NestedR4LabelHost"."""

                model = NestedR4LabelHost

        field = NestedR4LabelHostType.CreateField()
        assert field.extensions["gdx_required_perms"] == frozenset(
            {"tests.publish_nestedr4labelhost"}
        )
