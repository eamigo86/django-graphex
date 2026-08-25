"""A nested write must run the CHILD's own permissions and scoping.

"DjangoModelType.create" / "update" authorize the PARENT once and then hand the
whole payload -- children included -- to the nested writer, which had no
permission concept at all. A caller allowed to write the parent could therefore
create and update rows of a child whose own type denies it, and could reach a
row the child's "filter_queryset" hides.

Invariants asserted here:

* a nested create / update runs every declared host's "authorize" for the child
  model, with the same "PERMISSION_DENIED" / 403 the child's own mutation
  raises, and the whole write rolls back,
* the denial carries the action the nested writer is about to perform and the
  nesting parent model, so a policy can grant "only through this parent",
* a nested upsert naming a primary key the child's host does not expose is a
  clean not-found, never a create or an update at that key,
* the gate is INERT for a child whose host declares no "permission_classes",
* the LINK paths (forward FK / M2M by primary key) stay ungated by design: they
  attach an existing row exactly as the plain "category: ID" surface always did,
* the reverse ownership guard still fires for a row the scope does expose.
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any, ClassVar

import pytest
from graphql import GraphQLError

from django_graphex.permissions import BasePermission
from django_graphex.types import DjangoModelType
from tests.models import (
    NestedPermAuthor,
    NestedPermCategory,
    NestedPermHatchNote,
    NestedPermNote,
    NestedPermPost,
    NestedPermScopedNote,
    NestedPermTag,
)

#: Every "(action, nested_parent)" pair the recording policy was asked about.
#: Cleared per test; asserted on to pin WHICH action the nested writer reports.
_CALLS: list[tuple[str, Any]] = []

#: The nesting parent every "create" the escape-hatch policy was asked about
#: carried. Empty means the child's gate never ran at all.
_HATCH_CALLS: list[Any] = []


class _RecordingDeny(BasePermission):
    """Deny every action and record the action name and nesting parent.

    Stands in for a real policy: the test only needs to know that the child's
    own gate ran, for which action, and with which parent in scope.
    """

    def has_permission(self, info: Any, action: str, model: Any, **kwargs: Any) -> bool:
        """Record the call and deny it.

        Args:
            info: GraphQL resolve info for the current request.
            action: The action being checked.
            model: The Django model the action targets.
            **kwargs: Extras, including the nested "nested_parent" marker.

        Returns:
            Always False.
        """
        _CALLS.append((action, kwargs.get("nested_parent")))
        return False


class _OnlyViaParent(BasePermission):
    """Grant "create" only when the write comes through a nesting parent.

    The documented escape hatch: a child that must not be creatable on its own
    root but may be created inside its parent's payload.
    """

    def has_create_permission(self, info: Any, model: Any, **kwargs: Any) -> bool:
        """Allow the create only when the nested marker is present.

        Args:
            info: GraphQL resolve info for the current request.
            model: The Django model the action targets.
            **kwargs: Extras, including the nested "nested_parent" marker.

        Returns:
            True when the write is nested under a parent.
        """
        _HATCH_CALLS.append(kwargs.get("nested_parent"))
        return kwargs.get("nested_parent") is not None


class NestedPermPostType(DjangoModelType):
    """The post's own type, denying every write.

    Its permissions are the ones a nested write through the author must run.
    """

    permission_classes: ClassVar[tuple[Any, ...]] = (_RecordingDeny,)

    class Meta:
        """Bind the type to "NestedPermPost".

        The nested writer looks a child host up by MODEL, so this line is what makes
        the denying policy above apply to a write arriving through "author.posts".
        """

        model = NestedPermPost


class NestedPermCategoryType(DjangoModelType):
    """The forward-FK target's own type, denying every write.

    It exists to be ignored: the link path attaches an existing row, so a gate
    that started consulting the child here would break "category: ID".
    """

    permission_classes: ClassVar[tuple[Any, ...]] = (_RecordingDeny,)

    class Meta:
        """Bind the type to "NestedPermCategory".

        "NestedPermAuthor.category" resolves to this model, which is how the link
        path finds the host the test then proves is NOT asked.
        """

        model = NestedPermCategory


class NestedPermTagType(DjangoModelType):
    """The many-to-many target's own type, denying every write.

    The M2M twin of the category host: same denial, different relation kind, so a
    gate leaking onto link paths fails on both rather than only one.
    """

    permission_classes: ClassVar[tuple[Any, ...]] = (_RecordingDeny,)

    class Meta:
        """Bind the type to "NestedPermTag".

        Reached through "NestedPermAuthor.tags", whose rows are shared with every
        other parent -- writing them from a nested payload would be cross-tenant.
        """

        model = NestedPermTag


class NestedPermNoteType(DjangoModelType):
    """The note's own type, declaring NO permissions -- the inertness control.

    Without a host that consults nothing, a gate denying by default would still
    look correct on every other case in this module.
    """

    class Meta:
        """Bind the type to "NestedPermNote".

        The binding and nothing else: no "permission_classes" for the nested gate to
        find, which is the whole point of the fixture.
        """

        model = NestedPermNote


class NestedPermHatchNoteType(DjangoModelType):
    """The hatch note's own type: creatable only through its parent.

    Proves "nested_parent" reaches the child's policy as a usable SIGNAL, not
    merely as extra noise on a denial.
    """

    permission_classes: ClassVar[tuple[Any, ...]] = (_OnlyViaParent,)

    class Meta:
        """Bind the type to "NestedPermHatchNote".

        Bound on its own account too, so the same policy can be shown to keep
        refusing the direct create while the nested one succeeds.
        """

        model = NestedPermHatchNote


class NestedPermScopedNoteType(DjangoModelType):
    """The scoped note's own type, hiding every row of another tenant.

    Drives the upsert case: a nested pk must be resolved against this host's
    scope, never against the bare model manager.
    """

    class Meta:
        """Bind the type to "NestedPermScopedNote".

        The scoping lives in the "filter_queryset" override below, so the binding is
        deliberately the only declaration here.
        """

        model = NestedPermScopedNote

    @classmethod
    def filter_queryset(cls, qs: Any, info: Any, **kwargs: Any) -> Any:
        """Restrict every operation to the "mine" tenant.

        Args:
            qs: Queryset to scope.
            info: GraphQL resolve info for the current request.
            **kwargs: Extra arguments, unused here.

        Returns:
            The queryset narrowed to the caller's tenant.
        """
        return qs.filter(owner="mine")


class NestedPermAuthorType(DjangoModelType):
    """The nesting parent, permitting everything it is asked to write.

    Every child relation is declared nested so one host drives all the cases.
    """

    class Meta:
        """Bind the type to "NestedPermAuthor" with all relations nested.

        One host covers reverse FK, forward FK and many-to-many, so an implementation
        that only handled the reverse case cannot pass this module.
        """

        model = NestedPermAuthor
        nested_fields = {
            "posts": NestedPermPost,
            "notes": NestedPermNote,
            "hatch_notes": NestedPermHatchNote,
            "scoped_notes": NestedPermScopedNote,
            "category": NestedPermCategory,
            "tags": NestedPermTag,
        }


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
class TestNestedChildPermissions:
    """The child's own gate must run on every nested create and update.

    Authorizing the parent once and trusting the rest of the payload is the
    defect: it turns any writable parent into a bypass for every child model it
    nests.
    """

    def setup_method(self) -> None:
        """Reset the recorded permission calls before each case.

        The recorders are module-level lists, so an entry left by an earlier case
        would satisfy an assertion this one never earned.
        """
        _CALLS.clear()
        _HATCH_CALLS.clear()

    def test_nested_create_runs_the_childs_deny(self) -> None:
        """A nested create must raise the child's own denial and persist nothing.

        This test breaks if the nested writer reaches the child's backend
        without consulting the child's declared host: the row is created and
        the mutation answers "ok: true".
        """
        with pytest.raises(GraphQLError) as caught:
            _create(NestedPermAuthorType, {"name": "a", "posts": [{"title": "t"}]})

        # The SHAPE matters, not just the row count: a denial degraded into an
        # "ok: false" validation payload would still leave the count at zero.
        assert caught.value.extensions["code"] == "PERMISSION_DENIED"
        assert caught.value.extensions["status_code"] == 403
        assert _CALLS == [("create", NestedPermAuthor)]
        assert NestedPermPost.objects.count() == 0
        assert NestedPermAuthor.objects.count() == 0

    def test_nested_update_runs_the_childs_deny(self) -> None:
        """A nested payload carrying a child pk must be gated as an update.

        This test breaks if the child's gate is skipped, or if the nested
        writer reports the write as a create when it is about to update.
        """
        author = NestedPermAuthor.objects.create(name="a")
        post = NestedPermPost.objects.create(author=author, title="original")

        with pytest.raises(GraphQLError) as caught:
            _update(
                NestedPermAuthorType,
                {"id": author.pk, "posts": [{"id": post.pk, "title": "PWNED"}]},
            )

        assert caught.value.extensions["code"] == "PERMISSION_DENIED"
        assert _CALLS == [("update", NestedPermAuthor)]
        post.refresh_from_db()
        assert post.title == "original"

    def test_nested_parent_marker_is_the_escape_hatch(self) -> None:
        """A policy may grant a write only when it comes through a parent.

        This test breaks if the "nested_parent" kwarg is not forwarded to the
        child's permission checks.
        """
        result = _create(
            NestedPermAuthorType, {"name": "a", "hatch_notes": [{"body": "b"}]}
        )
        assert result.ok, getattr(result, "errors", None)
        assert _HATCH_CALLS == [NestedPermAuthor]
        assert NestedPermHatchNote.objects.count() == 1

    def test_direct_create_of_a_nested_only_child_is_still_denied(self) -> None:
        """The same policy still refuses the child's own root mutation.

        This test breaks if the nested marker leaks onto the direct path,
        which would make the hatch grant everything.
        """
        with pytest.raises(GraphQLError) as caught:
            _create(NestedPermHatchNoteType, {"body": "b"})
        assert caught.value.extensions["code"] == "PERMISSION_DENIED"
        assert NestedPermHatchNote.objects.count() == 0

    def test_gate_is_inert_for_a_child_without_permissions(self) -> None:
        """A child whose host declares no permissions behaves exactly as before.

        This test breaks if the gate denies (or errors on) a host that has no
        permission classes to consult.
        """
        result = _create(NestedPermAuthorType, {"name": "a", "notes": [{"body": "b"}]})
        assert result.ok, getattr(result, "errors", None)
        assert NestedPermNote.objects.get().body == "b"

    def test_nested_upsert_cannot_reach_a_row_the_scope_hides(self) -> None:
        """A pk outside the child's scope is not found -- not created, not updated.

        This test breaks if the nested writer resolves the target row on the
        bare model: Django's "save()" with a primary key issues an UPDATE, so
        the hidden row is silently rewritten.
        """
        author = NestedPermAuthor.objects.create(name="a")
        hidden = NestedPermScopedNote.objects.create(
            author=author, body="theirs", owner="theirs"
        )

        result = _update(
            NestedPermAuthorType,
            {
                "id": author.pk,
                "scoped_notes": [{"id": hidden.pk, "body": "PWNED"}],
            },
        )

        assert not result.ok
        hidden.refresh_from_db()
        assert hidden.body == "theirs"
        assert NestedPermScopedNote.objects.count() == 1

    def test_reverse_ownership_guard_still_fires(self) -> None:
        """A visible row owned by another parent is still refused by name.

        Guards the deny-only ownership check: scoping that branch would turn a
        hidden row into "no row" and skip the denial entirely.
        """
        owner = NestedPermAuthor.objects.create(name="owner")
        other = NestedPermAuthor.objects.create(name="other")
        note = NestedPermNote.objects.create(author=owner, body="b")

        result = _update(
            NestedPermAuthorType,
            {"id": other.pk, "notes": [{"id": note.pk, "body": "STOLEN"}]},
        )

        assert not result.ok
        messages = [message for error in result.errors for message in error.messages]
        assert any("does not belong to this NestedPermAuthor" in m for m in messages)

    def test_forward_link_path_is_not_gated(self) -> None:
        """Attaching an existing forward-FK row stays allowed.

        The link path writes nothing on the child; it is the same reachability
        the plain "category: ID" surface always offered.
        """
        category = NestedPermCategory.objects.create(name="c")
        result = _create(
            NestedPermAuthorType, {"name": "a", "category": {"id": category.pk}}
        )
        assert result.ok, getattr(result, "errors", None)
        assert NestedPermAuthor.objects.get().category_id == category.pk

    def test_m2m_link_path_is_not_gated(self) -> None:
        """Attaching an existing many-to-many row stays allowed.

        Same boundary as the forward link path, on the relation whose rows the
        parent shares with every other parent.
        """
        tag = NestedPermTag.objects.create(label="t")
        result = _create(NestedPermAuthorType, {"name": "a", "tags": [{"id": tag.pk}]})
        assert result.ok, getattr(result, "errors", None)
        assert list(NestedPermAuthor.objects.get().tags.all()) == [tag]
