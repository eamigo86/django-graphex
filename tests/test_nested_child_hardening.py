"""Hardening of the nested-write gate: the ways it still failed OPEN.

The nested-write lot derived the child's input from the child's DECLARED hosts
and stamped the nested input field with the child's write permissions. Three
adversarial reviews found the seams where that still widened a surface instead
of narrowing it, and this module pins each one:

* two hosts declaring different "only_fields" annihilated each other, which
  every consumer reads as "no projection" -- the widest possible surface. Round
  6 settled that axis as an ALLOWANCE the serving hosts UNION, so what this
  module now pins is that the union is still a projection,
* the nested input field was stamped with the PARENT's operation only, while
  the nested payload's optional "id" makes it a create surface too, so a caller
  holding "change" but not "add" kept a pruned-away create through the parent,
* the stamp CONSULTED the child host's "required_perms", which labels the fields
  that host generates and says nothing about who may write the child through
  someone else's payload,
* an input object left with zero permitted fields fell back to its UNFILTERED
  field map, disabling the gate for the whole type,
* a host declared AFTER its nested input was materialized was silently ignored,
  baking the unprojected surface in for the process lifetime,
* the child's permission checks received a new "nested_parent" keyword argument
  that a permission class with a closed signature cannot absorb.
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any, ClassVar

import pytest
from django.core.exceptions import ImproperlyConfigured
from graphql import get_named_type, validate_schema

from django_graphex.core import ObjectType
from django_graphex.core.registry_compiler import compile_all_outputs
from django_graphex.core.schema_pruner import prune_schema
from django_graphex.mutation import DjangoModelMutation, nested_child_input
from django_graphex.permissions import BasePermission, DjangoModelPermissions
from django_graphex.registry import get_global_registry
from django_graphex.schema import DjangoGraphQLSchema
from django_graphex.types import DjangoModelType
from tests.models import (
    NestedHardDisjointKid,
    NestedHardDisjointOwner,
    NestedHardKeeperBatch,
    NestedHardLateKid,
    NestedHardLateOwner,
    NestedHardLatePlainKid,
    NestedHardLatePlainOwner,
    NestedHardNameKid,
    NestedHardNameOwner,
    NestedHardOnlyBatch,
    NestedHardOnlyRow,
    NestedHardOptOutBlog,
    NestedHardOptOutEntry,
    NestedHardOverlapKid,
    NestedHardOverlapOwner,
    NestedHardQsKid,
    NestedHardQsOwner,
    NestedHardSigKid,
    NestedHardSigOwner,
    NestedHardVerbBlog,
    NestedHardVerbEntry,
)


# --------------------------------------------------------------------------- #
# Split projections: two hosts, different non-empty "only_fields".             #
# --------------------------------------------------------------------------- #
class NestedHardDisjointKidType(DjangoModelType):
    """One host, exposing only "headline".

    Half of a read/write split that shares no column with its sibling; intersecting the
    two allowances left nothing at all and took the whole schema down at import.
    """

    class Meta:
        """Bind the type to "NestedHardDisjointKid".

        The allowance is declared on a type host rather than a mutation, so the two
        contributors differ in kind as well as in columns.
        """

        model = NestedHardDisjointKid
        only_fields = ("headline",)


class NestedHardDisjointKidMutation(DjangoModelMutation):
    """The other host, exposing only "tagline" -- no field in common.

    Create-only, so it genuinely serves the operation the merge is inspected on and
    cannot be filtered out before the union runs.
    """

    class Meta:
        """Bind the mutation to "NestedHardDisjointKid".

        The same model as the type host above: two declarations for one model are what
        make a projection merge happen at all.
        """

        model = NestedHardDisjointKid
        model_operations = ("create",)
        only_fields = ("tagline",)


class NestedHardDisjointOwnerMutation(DjangoModelMutation):
    """The parent nesting the contradictorily projected child.

    Supplies the nesting scope the child input is keyed by, which the assertions then
    build directly rather than through a schema.
    """

    class Meta:
        """Bind the mutation to "NestedHardDisjointOwner" with "kids" nested.

        Create-only, matching the one operation both of the child's hosts serve.
        """

        model = NestedHardDisjointOwner
        model_operations = ("create",)
        nested_fields = {"kids": NestedHardDisjointKid}


class NestedHardOverlapKidTypeA(DjangoModelType):
    """One host of the overlapping fixture: "headline" and "tagline".

    Overlap is interesting for the opposite reason to the disjoint case: an intersection
    survives here, and quietly drops the columns only one host allows.
    """

    class Meta:
        """Bind the type to "NestedHardOverlapKid".

        Allows one shared column and one of its own, so the union is strictly wider than
        either host's declaration on its own.
        """

        model = NestedHardOverlapKid
        only_fields = ("headline", "tagline")


class NestedHardOverlapKidMutationB(DjangoModelMutation):
    """The other host: "tagline" and "extra" -- "tagline" is the overlap.

    "extra" is allowed by this host alone, and it is the column the assertion on the
    merged surface actually pins.
    """

    class Meta:
        """Bind the mutation to "NestedHardOverlapKid".

        Create-only, so the merge under test has exactly two contributors and no third
        surface to blame a surprise on.
        """

        model = NestedHardOverlapKid
        model_operations = ("create",)
        only_fields = ("tagline", "extra")


class NestedHardOverlapOwnerMutation(DjangoModelMutation):
    """The parent nesting the overlapping-projection child.

    A separate parent from the disjoint fixture: the nested input is memoized per
    parent, so sharing one would blur the two cases together.
    """

    class Meta:
        """Bind the mutation to "NestedHardOverlapOwner" with "kids" nested.

        Create-only, matching the operation the union is asserted on.
        """

        model = NestedHardOverlapOwner
        model_operations = ("create",)
        nested_fields = {"kids": NestedHardOverlapKid}


class TestChildProjectionAllowancesUnion:
    """An "only_fields" is an ALLOWANCE, so the serving hosts union theirs.

    The disjoint and overlapping cases fail differently under an intersection: the first
    kills the schema outright at import, the second silently deletes writable columns.
    """

    def test_disjoint_only_fields_union(self) -> None:
        """Two hosts that agree on nothing are an ordinary split surface.

        A read card and a write mutation naming different columns escalate
        nothing, and intersecting them killed the whole schema at import. This
        test breaks if the allowance axis goes back to an intersection.
        """
        built = nested_child_input(
            NestedHardDisjointKid,
            "create",
            get_global_registry(),
            NestedHardDisjointOwner,
        )
        assert set(built._meta.graphql_input_type.fields) == {"headline", "tagline"}

    def test_overlapping_only_fields_union(self) -> None:
        """A shared column is not a ceiling either.

        The union is still a projection: what no host allows stays out. This
        test breaks if a failed merge falls back to "no projection declared",
        which mints an input carrying every writable column.
        """
        built = nested_child_input(
            NestedHardOverlapKid,
            "create",
            get_global_registry(),
            NestedHardOverlapOwner,
        )
        assert set(built._meta.graphql_input_type.fields) == {
            "headline",
            "tagline",
            "extra",
        }


# --------------------------------------------------------------------------- #
# Generated type name: the parent's capitals must survive.                     #
# --------------------------------------------------------------------------- #
class NestedHardNameKidType(DjangoModelType):
    """The child host of the naming fixture.

    Its own name is unremarkable on purpose -- the generated input name is assembled
    from the PARENT's name, which is where the capitals were lost.
    """

    class Meta:
        """Bind the type to "NestedHardNameKid".

        Declares nothing beyond the binding, so the generated type name is the only
        observable output of the fixture.
        """

        model = NestedHardNameKid


class NestedHardNameOwnerMutation(DjangoModelMutation):
    """The multi-word parent whose name the generated type must preserve.

    The generated input name is wire-visible, so flattening the parent's internal
    capitals renames a published type no documentation mentions.
    """

    class Meta:
        """Bind the mutation to "NestedHardNameOwner" with "kids" nested.

        Create-only, so exactly one nested input name exists for the test to assert on.
        """

        model = NestedHardNameOwner
        model_operations = ("create",)
        nested_fields = {"kids": NestedHardNameKid}


class TestNestedChildInputName:
    """The per-parent child input is named "<Child><Op>In<Parent>Type".

    That name is part of the published schema, so changing it is a breaking change for
    every client that references the input type by name.
    """

    def test_multi_word_parent_name_is_not_flattened(self) -> None:
        """A CamelCase parent model must not be capitalize()-d to one word.

        This test breaks if the name is assembled by camel-casing an
        underscore-joined string: every component after the first is
        "str.capitalize()"-d, which lower-cases the parent's internal capitals
        and produces a wire-visible name no documentation mentions.
        """
        built = nested_child_input(
            NestedHardNameKid,
            "create",
            get_global_registry(),
            NestedHardNameOwner,
        )
        assert (
            built._meta.graphql_input_type.name
            == "NestedHardNameKidCreateInNestedHardNameOwnerType"
        )


# --------------------------------------------------------------------------- #
# The permission stamp on the nested input field.                             #
# --------------------------------------------------------------------------- #
class NestedHardVerbEntryType(DjangoModelType):
    """The child of the create-through-update fixture, model-permission gated.

    Its "add" permission is the one a caller may lack while still holding "change" --
    exactly the split the parent's update payload can otherwise route around.
    """

    permission_classes: ClassVar[tuple[Any, ...]] = (DjangoModelPermissions,)

    class Meta:
        """Bind the type to "NestedHardVerbEntry".

        No projection, so the nested element keeps its optional "id" and the payload
        really can create as well as update.
        """

        model = NestedHardVerbEntry


class NestedHardVerbBlogType(DjangoModelType):
    """The parent whose UPDATE payload can also CREATE entries.

    One root field spanning two operations is what makes stamping it with the parent's
    verb alone insufficient.
    """

    permission_classes: ClassVar[tuple[Any, ...]] = (DjangoModelPermissions,)

    class Meta:
        """Bind the type to "NestedHardVerbBlog" with "entries" nested.

        Only the update root is mounted below, so the create reachable through this
        parent has no front door of its own for a caller to be refused at.
        """

        model = NestedHardVerbBlog
        nested_fields = {"entries": NestedHardVerbEntry}


class NestedHardOptOutEntryType(DjangoModelType):
    """A child trying to unlabel its nested surface through "required_perms".

    An empty override is a legitimate way to publish a host's OWN roots; the danger is
    the same declaration reading as publishing someone else's nested write.
    """

    permission_classes: ClassVar[tuple[Any, ...]] = (DjangoModelPermissions,)
    #: What the host's OWN root fields are labelled with. An empty override
    #: makes those public to the pruner; it must not make the PARENT's nested
    #: write surface public too.
    required_perms: ClassVar[tuple[str, ...]] = ()

    class Meta:
        """Bind the type to "NestedHardOptOutEntry".

        The override above is the whole fixture -- the binding adds nothing else the
        stamp could consult.
        """

        model = NestedHardOptOutEntry


class NestedHardOptOutBlogType(DjangoModelType):
    """The parent of the "required_perms" override fixture.

    Gated by the same stack, so a caller can be granted the parent's writes exactly and
    then measured on the child's stamp alone.
    """

    permission_classes: ClassVar[tuple[Any, ...]] = (DjangoModelPermissions,)

    class Meta:
        """Bind the type to "NestedHardOptOutBlog" with "entries" nested.

        The nested entry the override tried to make public; the composite default has to
        hold it shut regardless of what the child host declares.
        """

        model = NestedHardOptOutBlog
        nested_fields = {"entries": NestedHardOptOutEntry}


class NestedHardOnlyRowType(DjangoModelType):
    """The child that is its parent's ONLY writable input field.

    Denying a caller the child's write empties the parent's entire input object, which
    is the state the pruner used to answer with an unfiltered field map.
    """

    permission_classes: ClassVar[tuple[Any, ...]] = (DjangoModelPermissions,)

    class Meta:
        """Bind the type to "NestedHardOnlyRow".

        Gated but unprojected, so nothing except the permission stamp decides whether
        the parent's input survives.
        """

        model = NestedHardOnlyRow


class NestedHardOnlyBatchType(DjangoModelType):
    """A parent whose "Meta.only_fields" names nothing but the nested relation.

    One ordinary Meta option is all it takes to produce an input object whose
    every field carries the child's write stamp.
    """

    permission_classes: ClassVar[tuple[Any, ...]] = (DjangoModelPermissions,)

    class Meta:
        """Bind the type to "NestedHardOnlyBatch", exposing only "rows".

        An "only_fields" naming a single nested relation is an ordinary declaration, and
        it is all it takes to reach the empty-input state.
        """

        model = NestedHardOnlyBatch
        only_fields = ("rows",)
        nested_fields = {"rows": NestedHardOnlyRow}


class NestedHardKeeperBatchType(DjangoModelType):
    """An unrelated sibling root that must SURVIVE the empty-input cascade.

    Without it, a cascade that deleted the whole mutation type would look like a
    perfectly correct fix.
    """

    permission_classes: ClassVar[tuple[Any, ...]] = (DjangoModelPermissions,)

    class Meta:
        """Bind the type to "NestedHardKeeperBatch".

        Deliberately unrelated to the emptied parent: it shares only the mutation root,
        which is precisely the blast radius under test.
        """

        model = NestedHardKeeperBatch


class _Query(ObjectType):
    """Root exposing the sibling's retrieve field."""

    keeper_retrieve = NestedHardKeeperBatchType.RetrieveField()


class _Mutation(ObjectType):
    """Root exposing every parent whose input the pruner is asked about."""

    verb_blog_update = NestedHardVerbBlogType.UpdateField()
    opt_out_blog_create = NestedHardOptOutBlogType.CreateField()
    only_batch_create = NestedHardOnlyBatchType.CreateField()
    keeper_create = NestedHardKeeperBatchType.CreateField()


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


def _prune(granted: set[str]) -> Any:
    """Return the pruned schema a caller holding *granted* would be served.

    Mirrors "PrunedSchemaCache.get": the granted set is intersected with the
    schema label-set BEFORE pruning, so a label the schema never mentions is
    stripped rather than treated as held.

    Args:
        granted: The permission codenames the caller holds.

    Returns:
        The pruned "GraphQLSchema".
    """
    label_set = frozenset((_schema.extensions or {}).get("gdx_label_set") or ())
    return prune_schema(_schema, frozenset(granted) & label_set)


def _input_fields(granted: set[str], root: str) -> set[str]:
    """Return the field names of a pruned mutation root's input argument.

    Args:
        granted: The permission codenames the caller holds.
        root: The mutation field name to inspect.

    Returns:
        The input object type's field names.
    """
    (argument,) = _prune(granted).mutation_type.fields[root].args.values()
    return set(get_named_type(argument.type).fields)


class TestNestedInputStampVerb:
    """A nested input field is a create surface as well as an update one.

    Stamping it with the parent's verb alone leaves a caller holding "change" but not
    "add" with a working create through the parent, while the child's own create root is
    pruned away.
    """

    def test_update_input_requires_the_childs_create_permission(self) -> None:
        """The child's "id" is OPTIONAL on the parent's update payload.

        Omitting it CREATES a child row, so a caller holding "change" but not
        "add" must not keep the field. This test breaks if the stamp uses the
        PARENT's operation alone: the child's own create root is pruned away
        while the identical create stays reachable through the parent.
        """
        granted = _perms(NestedHardVerbBlog, "view", "change") | _perms(
            NestedHardVerbEntry, "view", "change"
        )
        assert "entries" not in _input_fields(granted, "verbBlogUpdate")

    def test_update_input_keeps_the_field_for_a_full_writer(self) -> None:
        """A caller holding both child write verbs still sees the field.

        This test breaks if the stamp is widened into something no caller can
        satisfy -- a self-inflicted outage rather than a fix.
        """
        granted = _perms(NestedHardVerbBlog, "view", "change") | _perms(
            NestedHardVerbEntry, "view", "change", "add"
        )
        assert "entries" in _input_fields(granted, "verbBlogUpdate")

    def test_an_empty_required_perms_override_does_not_unlabel_the_field(
        self,
    ) -> None:
        """ "required_perms" labels the fields a host GENERATES, not this one.

        An empty override makes the host's own roots public to the pruner. This
        test breaks if the nested stamp consults it: the parent's nested write
        surface would then be public too, so a caller holding no permission on
        the child at all would keep a working write of it through the parent.
        """
        granted = _perms(NestedHardOptOutBlog, "view", "add")
        assert "entries" not in _input_fields(granted, "optOutBlogCreate")

    def test_the_child_writer_still_sees_the_overridden_field(self) -> None:
        """The composite default is what governs, and it is satisfiable.

        The "writable only through its parent" pattern needs no override at all:
        the caller doing that write holds the child's write label, and what the
        project withholds is the child's own root -- which, never mounted, gives
        the pruner nothing to prune.
        """
        granted = _perms(NestedHardOptOutBlog, "view", "add") | _perms(
            NestedHardOptOutEntry, "view", "add"
        )
        assert "entries" in _input_fields(granted, "optOutBlogCreate")


class TestEmptyInputCascade:
    """An input object with no permitted field must prune its REFERENCING field.

    Falling back to the unfiltered field map disables the gate for the whole type;
    pruning too eagerly takes unrelated sibling roots down with it. Both the cascade and
    its blast radius are asserted.
    """

    def test_root_disappears_when_its_whole_input_is_denied(self) -> None:
        """Every field of the parent's input carries the child's write stamp.

        This test breaks if the pruner answers an empty field map by returning
        the UNFILTERED one: the nested write survives for a caller who may not
        write the child, which is the exact hole the stamp was added to close.
        """
        granted = (
            _perms(NestedHardOnlyBatch, "view", "add")
            | _perms(NestedHardOnlyRow, "view")
            | _perms(NestedHardKeeperBatch, "view", "add")
        )
        pruned = _prune(granted)
        assert "onlyBatchCreate" not in pruned.mutation_type.fields
        # The cascade must stop at the dead root: an unrelated sibling sharing
        # the mutation type is not collateral.
        assert "keeperCreate" in pruned.mutation_type.fields
        assert validate_schema(pruned) == []

    def test_root_survives_for_a_caller_who_may_write_the_child(self) -> None:
        """The same root is intact once the child's write permission is held.

        This test breaks if the cascade drops the field unconditionally instead
        of only when the input really has nothing left.
        """
        granted = (
            _perms(NestedHardOnlyBatch, "view", "add")
            | _perms(NestedHardOnlyRow, "view", "add")
            | _perms(NestedHardKeeperBatch, "view", "add")
        )
        pruned = _prune(granted)
        assert "onlyBatchCreate" in pruned.mutation_type.fields
        assert _input_fields(granted, "onlyBatchCreate") == {"rows"}


# --------------------------------------------------------------------------- #
# A host declared after its nested input was already materialized.            #
# --------------------------------------------------------------------------- #
class TestLateDeclaredHost:
    """A host that can no longer reach the nested surface must be LOUD.

    graphql-core caches the parent input's field map for good, so a late narrowing can
    never land. Silence bakes the wider surface in, and refusing every late host would
    turn an ordinary declaration into an import crash.
    """

    def test_host_declared_after_materialization_raises(self) -> None:
        """graphql-core caches the parent input's field map for good.

        Once the nested child input has been built, a host declared afterwards
        can never contribute its projection or its permissions -- not through a
        schema rebuild, not through clearing the memo. This test breaks if the
        late host is silently ignored, which leaves the unprojected surface
        baked in for the process lifetime.
        """
        nested_child_input(
            NestedHardLateKid,
            "create",
            get_global_registry(),
            NestedHardLateOwner,
        )

        with pytest.raises(ImproperlyConfigured) as excinfo:

            class NestedHardLateKidType(DjangoModelType):
                """A host arriving too late to matter."""

                class Meta:
                    """Bind the type to "NestedHardLateKid", hiding "secret"."""

                    model = NestedHardLateKid
                    exclude_fields = ("secret",)

        message = str(excinfo.value)
        assert "NestedHardLateKidType" in message
        assert "NestedHardLateOwner" in message

    def test_late_host_without_a_projection_is_accepted(self) -> None:
        """Only the FROZEN half of a host's declaration is fatal.

        A host declaring no projection and no label override contributes
        nothing the built input could have honoured, and its
        "permission_classes" are read from the host registry at write time, so
        they still gate nested writes. This test breaks if the guard refuses
        every late host: declaring a plain mutation for an already-nested model
        is ordinary, and turning it into an import-time crash is worse than the
        defect.
        """
        nested_child_input(
            NestedHardLatePlainKid,
            "create",
            get_global_registry(),
            NestedHardLatePlainOwner,
        )

        class NestedHardLatePlainKidType(DjangoModelType):
            """A late host that bakes nothing into the nested input."""

            class Meta:
                """Bind the type to "NestedHardLatePlainKid"."""

                model = NestedHardLatePlainKid

        assert NestedHardLatePlainKidType._meta.model is NestedHardLatePlainKid


# --------------------------------------------------------------------------- #
# The child's own gate, called with the new "nested_parent" keyword.          #
# --------------------------------------------------------------------------- #
class _ClosedSignature(BasePermission):
    """A policy that spells its arguments out instead of taking "**kwargs".

    Valid against the contract before the nested gate existed -- "data=" was the
    only extra ever forwarded -- and it GRANTS the write, so any failure here is
    a crash, not a denial.
    """

    def has_create_permission(self, info: Any, model: Any, data: Any = None) -> bool:
        """Allow every create.

        Args:
            info: GraphQL resolve info for the current request.
            model: The Django model the action targets.
            data: The payload under validation.

        Returns:
            Always True.
        """
        return True


class NestedHardSigKidType(DjangoModelType):
    """The child whose permission class cannot absorb an unknown keyword.

    Its policy grants the write, so this fixture can only fail by crashing -- and only
    through a parent, since the child's own root never forwards the extra.
    """

    permission_classes: ClassVar[tuple[Any, ...]] = (_ClosedSignature,)

    class Meta:
        """Bind the type to "NestedHardSigKid".

        Nothing but the binding: the closed-signature policy above is what the nested
        writer has to manage to call correctly.
        """

        model = NestedHardSigKid


class NestedHardSigOwnerType(DjangoModelType):
    """The parent driving the closed-signature child.

    Ungated itself, so the only permission code a nested create runs is the child's.
    """

    class Meta:
        """Bind the type to "NestedHardSigOwner" with "kids" nested.

        The nested entry through which the writer reaches the closed policy.
        """

        model = NestedHardSigOwner
        nested_fields = {"kids": NestedHardSigKid}


class NestedHardQsKidType(DjangoModelType):
    """A child narrowing its base queryset through "Meta.queryset" alone.

    Declarative scoping is easy to miss when the nested lookup only reproduces
    "filter_queryset", and that split is what this fixture forbids.
    """

    class Meta:
        """Bind the type to "NestedHardQsKid" with a narrowed base queryset.

        The queryset hides every row whose headline does not start with "ok" -- exactly
        the rows the child's own update already refuses to touch.
        """

        model = NestedHardQsKid
        queryset = NestedHardQsKid.objects.filter(headline__startswith="ok")


class NestedHardQsOwnerType(DjangoModelType):
    """The parent driving the "Meta.queryset" scoping fixture.

    Its nested update payload is the only route to the hidden row, so a passing test
    means the two scopes genuinely agree.
    """

    class Meta:
        """Bind the type to "NestedHardQsOwner" with "kids" nested.

        The nested entry a foreign primary key travels through on its way to the child's
        scope check.
        """

        model = NestedHardQsOwner
        nested_fields = {"kids": NestedHardQsKid}


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


def _update(host: Any, data: dict[str, Any]) -> Any:
    """Invoke the generated "update" resolver of a type host.

    Args:
        host: The "DjangoModelType" class to call.
        data: The input payload, keyed by the host's input field name.

    Returns:
        The mutation result object (exposes "ok" and, on failure, "errors").
    """
    return host.update(None, _info(), **{host._meta.input_field_name: data})


@pytest.mark.django_db()
class TestNestedGateCallingConvention:
    """The gate must not break a permission class that grants the write.

    The fixture permits everything, so a failure is an uncaught "TypeError" and an HTTP
    500 -- visible only through a parent, because the child's own root never forwards
    the new keyword.
    """

    def test_closed_signature_permission_class_still_grants(self) -> None:
        """A policy without "**kwargs" must not turn a grant into a crash.

        This test breaks if "nested_parent" is forwarded blindly: the nested
        path raises an uncaught "TypeError" -- a 500, not a GraphQL error --
        while the child's own root mutation keeps working, so the failure shows
        up only through a parent.
        """
        result = _create(
            NestedHardSigOwnerType, {"name": "o", "kids": [{"headline": "h"}]}
        )
        assert result.ok, getattr(result, "errors", None)
        assert NestedHardSigKid.objects.get().headline == "h"


@pytest.mark.django_db()
class TestNestedScopeIncludesMetaQueryset:
    """The nested pk lookup mirrors the child's own top-level scope exactly.

    This pins a decision rather than a fix: honouring "filter_queryset" but not
    "Meta.queryset" would let a nested payload rewrite a row the child's own update
    refuses to touch.
    """

    def test_meta_queryset_gates_a_nested_update(self) -> None:
        """A row outside "Meta.queryset" is not found, as it is for "kidUpdate".

        Pins a deliberate decision rather than a fix: splitting the scope --
        honouring "filter_queryset" but not "Meta.queryset" -- would let a
        nested payload rewrite a row the child's OWN update refuses to touch,
        which is the defect the scoping was added to close.
        """
        owner = NestedHardQsOwner.objects.create(name="o")
        hidden = NestedHardQsKid.objects.create(owner=owner, headline="hidden")

        result = _update(
            NestedHardQsOwnerType,
            {"id": owner.pk, "kids": [{"id": hidden.pk, "headline": "PWNED"}]},
        )

        assert not result.ok
        hidden.refresh_from_db()
        assert hidden.headline == "hidden"
