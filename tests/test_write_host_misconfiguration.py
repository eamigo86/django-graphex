# -*- coding: utf-8 -*-
"""A misconfigured write host must fail at class definition, not in silence.

RED phase: every test here fails before the fix.

Three ways a "DjangoModelMutation" accepted a configuration it then ignored:
an unknown "Meta" option (so an "exclude_field" typo left the column writable
and a "Meta.queryset" scoped nothing), a "permission_classes" declaration the
class reads nowhere, and a "nested_fields" key naming no relation on the model.
The last one is shared with "DjangoModelType", which skipped it just as quietly.
"""

from __future__ import annotations

import pytest
from django.core.exceptions import ImproperlyConfigured

from django_graphex.mutation import DjangoModelMutation
from django_graphex.registry import Registry
from django_graphex.types import DjangoModelType

from .models import Author, MetaHygieneWidget, Post


class _Deny:
    """A permission class that refuses every action.

    Used only to give a "permission_classes" declaration something to hold; the
    guard fires at class definition, so it is never called.
    """

    def has_permission(self, info: object, action: str, **kwargs: object) -> bool:
        """Refuse the action.

        Args:
            info: The GraphQL resolve info for the current request.
            action: The CRUD action being checked.
            **kwargs: Extra arguments the caller passes through.

        Returns:
            Always False.
        """
        return False


class TestUnknownMetaOptionOnMutation:
    """A "DjangoModelMutation" must reject unknown "Meta" options.

    "DjangoModelType" has rejected them since 2.0; the mutation host never ran
    the same check, so both a typo and a real-but-unsupported option were taken
    and then dropped.
    """

    def test_exclude_field_typo_raises(self) -> None:
        """An "exclude_field" typo must not leave the column writable.

        Before the fix the class built and "is_active" stayed on the create
        input -- the exact column the declaration meant to hide.
        """
        with pytest.raises(ImproperlyConfigured) as excinfo:

            class TypoMutation(DjangoModelMutation):
                class Meta:
                    model = MetaHygieneWidget
                    registry = Registry()
                    exclude_field = ("is_active",)

        assert "exclude_field" in str(excinfo.value)

    def test_meta_queryset_raises(self) -> None:
        """A "Meta.queryset" on a mutation host must be refused, not dropped.

        This host resolves its target row through "get_queryset", which starts
        from the manager it is handed; the option scoped nothing.
        """
        with pytest.raises(ImproperlyConfigured) as excinfo:

            class QuerysetMutation(DjangoModelMutation):
                class Meta:
                    model = MetaHygieneWidget
                    registry = Registry()
                    queryset = MetaHygieneWidget.objects.filter(is_active=True)

        assert "queryset" in str(excinfo.value)

    def test_supported_options_still_build(self) -> None:
        """Every option the signature names must still be accepted.

        Guards the check against being over-broad: it must read the host's own
        signature rather than a hand-kept list.
        """

        class GoodMutation(DjangoModelMutation):
            class Meta:
                model = MetaHygieneWidget
                registry = Registry()
                exclude_fields = ("is_active",)
                description = "A well-formed host."
                model_operations = ("create",)

        create_input = GoodMutation._meta.arguments["create"]["new_metahygienewidget"]
        assert "isActive" not in create_input.type.of_type.fields


class TestPermissionClassesOnMutation:
    """ "permission_classes" on a mutation host must raise, not no-op.

    Declaring it raised a raw "PydanticUserError" whose advice -- annotate it
    "ClassVar" -- produced a class that builds while the permission never fires.
    """

    def test_plain_declaration_raises_improperly_configured(self) -> None:
        """The plain assignment the guides spell out must reach our own error.

        Before the fix Pydantic's metaclass rejected it first, with a message
        about model fields that says nothing about this library.
        """
        with pytest.raises(ImproperlyConfigured) as excinfo:

            class PermMutation(DjangoModelMutation):
                permission_classes = (_Deny,)

                class Meta:
                    model = MetaHygieneWidget
                    registry = Registry()

        message = str(excinfo.value)
        assert "PermMutation" in message
        assert "DjangoModelType" in message

    def test_classvar_declaration_raises_too(self) -> None:
        """Taking the "ClassVar" advice must not buy a silent no-op.

        This is the shape a user lands on after following the Pydantic error,
        and it is the one that shipped a permission that never fired.
        """
        from typing import Any, ClassVar

        with pytest.raises(ImproperlyConfigured):

            class ClassVarPermMutation(DjangoModelMutation):
                permission_classes: ClassVar[tuple[Any, ...]] = (_Deny,)

                class Meta:
                    model = MetaHygieneWidget
                    registry = Registry()

    def test_empty_default_still_builds(self) -> None:
        """A host that declares nothing must be unaffected.

        The base now carries the attribute, so its empty default must not read
        as a declaration.
        """

        class QuietMutation(DjangoModelMutation):
            class Meta:
                model = MetaHygieneWidget
                registry = Registry()

        assert QuietMutation.permission_classes == ()


class TestNestedFieldsUnknownKey:
    """A "nested_fields" key naming no relation must raise on both hosts.

    The key was skipped when the input surface was built and skipped again on
    the write path, while the generated input type was still NAMED after it --
    so a typo minted a type with no nested field in it.
    """

    def test_unknown_key_raises_on_mutation(self) -> None:
        """A misspelled accessor must be refused by "DjangoModelMutation".

        "bookz" is not an "Author" relation, so nothing would ever write it.
        """
        with pytest.raises(ImproperlyConfigured) as excinfo:

            class BogusNestedMutation(DjangoModelMutation):
                class Meta:
                    model = Author
                    registry = Registry()
                    nested_fields = {"bookz": Post}

        message = str(excinfo.value)
        assert "bookz" in message
        assert "Author" in message
        assert "posts" in message

    def test_unknown_key_raises_on_model_type(self) -> None:
        """The same key must be refused by "DjangoModelType".

        Both hosts take "nested_fields" and both skipped an unknown key, so the
        guard has to sit where both reach it.
        """
        with pytest.raises(ImproperlyConfigured) as excinfo:

            class BogusNestedType(DjangoModelType):
                class Meta:
                    model = Author
                    nested_fields = {"bookz": Post}

        assert "bookz" in str(excinfo.value)

    def test_non_relation_key_raises(self) -> None:
        """A key naming a real column that is not a relation must be refused.

        "name" exists on "Author" but is a scalar, so the nested surface left
        it out exactly as it left the misspelled key out.
        """
        with pytest.raises(ImproperlyConfigured) as excinfo:

            class ScalarNestedMutation(DjangoModelMutation):
                class Meta:
                    model = Author
                    registry = Registry()
                    nested_fields = {"name": Post}

        assert "name" in str(excinfo.value)

    def test_message_names_the_accessors_that_would_have_worked(self) -> None:
        """The error must list the model's relation accessors.

        A typo is only cheap to fix when the message says what to type instead.
        """
        with pytest.raises(ImproperlyConfigured) as excinfo:

            class ListedNestedMutation(DjangoModelMutation):
                class Meta:
                    model = Author
                    registry = Registry()
                    nested_fields = {"bookz": Post}

        message = str(excinfo.value)
        for accessor in ("author_profile", "coauthored_posts", "posts"):
            assert accessor in message

    def test_model_without_relations_still_reports(self) -> None:
        """A model with no relations at all must still produce a usable message.

        "MetaHygieneWidget" is scalar-only, so there is no accessor to suggest.
        """
        with pytest.raises(ImproperlyConfigured) as excinfo:

            class NoRelationsMutation(DjangoModelMutation):
                class Meta:
                    model = MetaHygieneWidget
                    registry = Registry()
                    nested_fields = {"whatever": Post}

        assert "whatever" in str(excinfo.value)

    def test_real_accessor_still_builds(self) -> None:
        """A correctly spelled accessor must keep building as before.

        Guards the guard: it must not reject the working configuration the
        nested-write guides teach.
        """

        class GoodNestedMutation(DjangoModelMutation):
            class Meta:
                model = Author
                registry = Registry()
                nested_fields = {"posts": Post}

        create_input = GoodNestedMutation._meta.arguments["create"]["new_author"]
        assert "posts" in create_input.type.of_type.fields


class TestUnknownOptionMessage:
    """An option that is real elsewhere must not be reported as a typo.

    "registry" is a supported "Meta" option on "DjangoModelMutation"; on
    "DjangoModelType" it was reported with a bare "Check for typos" hint.
    """

    def test_message_names_where_the_option_is_valid(self) -> None:
        """The error must say which host accepts "registry".

        Before the fix it only offered the "max_dep"/"max_depth" example, which
        reads as "you misspelled something" for an option spelled correctly.
        """
        with pytest.raises(ImproperlyConfigured) as excinfo:

            class RegistryOnModelType(DjangoModelType):
                class Meta:
                    model = MetaHygieneWidget
                    registry = Registry()

        message = str(excinfo.value)
        assert "registry" in message
        assert "DjangoModelMutation" in message

    def test_a_correctly_spelled_option_is_not_called_a_typo(self) -> None:
        """The typo hint must be dropped once the option is placed elsewhere.

        Emitting both sentences sends a user who spelled the option correctly
        hunting for a mistake they did not make.
        """
        with pytest.raises(ImproperlyConfigured) as excinfo:

            class RegistryOnModelTypeAgain(DjangoModelType):
                class Meta:
                    model = MetaHygieneWidget
                    registry = Registry()

        assert "typo" not in str(excinfo.value).lower(), str(excinfo.value)

    def test_a_true_typo_still_reads_as_one(self) -> None:
        """An option no host accepts must keep the typo hint.

        The added sentence is for the valid-elsewhere case only.
        """
        with pytest.raises(ImproperlyConfigured) as excinfo:

            class TypoOnModelType(DjangoModelType):
                class Meta:
                    model = MetaHygieneWidget
                    max_dep = 3

        assert "typo" in str(excinfo.value).lower()
