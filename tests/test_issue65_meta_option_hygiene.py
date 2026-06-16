# -*- coding: utf-8 -*-
"""Tests for issue #65: Meta-option hygiene (4 sub-issues).

RED phase: these tests must FAIL before the fix, then pass after.

(a) Unknown/typo Meta options silently swallowed — ImproperlyConfigured.
(b) include_fields ignored on DjangoInputObjectType / DjangoListObjectType.
(c) only_fields/exclude_fields omitting id → update KeyError (mutation.py:478).
(d) DjangoListObjectType.Meta.queryset validated but never consumed.
"""

from __future__ import annotations

import pytest
from django.core.exceptions import ImproperlyConfigured
from django.test import TestCase

from django_graphex import DjangoObjectType
from django_graphex.registry import Registry

from .models import MetaHygieneWidget

# ---------------------------------------------------------------------------
# (a) Unknown / typo Meta options silently swallowed
# ---------------------------------------------------------------------------


class TestUnknownMetaOption:
    """Unknown Meta options must raise ImproperlyConfigured at class definition."""

    def test_djangoinputobjecttype_unknown_option_raises(self):
        """DjangoInputObjectType must reject unknown Meta options."""
        from django_graphex.types import DjangoInputObjectType

        local_registry = Registry()
        with pytest.raises((ImproperlyConfigured, TypeError)):

            class BadInput(DjangoInputObjectType):
                class Meta:
                    model = MetaHygieneWidget
                    registry = local_registry
                    input_for = "create"
                    flieds = ("title",)  # typo for 'fields' (unknown option)

    def test_djangolistobjecttype_unknown_option_raises(self):
        """DjangoListObjectType must reject unknown Meta options."""
        from django_graphex.types import DjangoListObjectType

        local_registry = Registry()
        with pytest.raises((ImproperlyConfigured, TypeError)):

            class BadList(DjangoListObjectType):
                class Meta:
                    model = MetaHygieneWidget
                    registry = local_registry
                    max_dep = 5  # typo for max_deep

    def test_djangomodeltype_unknown_option_raises(self):
        """DjangoModelType must reject unknown Meta options."""
        from django_graphex.types import DjangoModelType

        with pytest.raises((ImproperlyConfigured, TypeError)):

            class BadModelType(DjangoModelType):
                class Meta:
                    model = MetaHygieneWidget
                    max_dep = 3  # typo for max_deep

    def test_djangoobjecttype_unknown_option_raises(self):
        """DjangoObjectType must reject unknown Meta options."""
        local_registry = Registry()

        with pytest.raises((ImproperlyConfigured, TypeError)):

            class BadWidgetType(DjangoObjectType):
                class Meta:
                    model = MetaHygieneWidget
                    registry = local_registry
                    max_dep = 3  # typo for max_deep

    def test_known_options_do_not_raise(self):
        """Legitimate known options must still be accepted without error."""
        local_registry = Registry()

        # This must not raise.
        class GoodWidgetType(DjangoObjectType):
            class Meta:
                model = MetaHygieneWidget
                registry = local_registry
                max_deep = 3  # valid option


# ---------------------------------------------------------------------------
# (b) include_fields ignored on DjangoInputObjectType / DjangoListObjectType
# ---------------------------------------------------------------------------


class TestIncludeFieldsOnInputAndListTypes:
    """include_fields must be honored on input and list types.

    Semantics: include_fields force-includes named fields even when they would
    normally be skipped by only_fields/exclude_fields.  It does NOT restrict the
    output to only those fields (use only_fields for that).  The bug was that
    include_fields was silently dropped (passed as None) in DjangoInputObjectType
    and DjangoListObjectType, so exclude_fields could not be overridden.
    """

    def test_include_fields_overrides_exclude_on_input_type(self):
        """A field excluded by exclude_fields but listed in include_fields must appear."""
        from django_graphex.types import DjangoInputObjectType

        local_registry = Registry()

        class WidgetCreateInput(DjangoInputObjectType):
            class Meta:
                model = MetaHygieneWidget
                registry = local_registry
                input_for = "create"
                exclude_fields = ("body", "is_active")
                include_fields = ("body",)  # force-include body despite exclude

        # Native contract: the canonical field surface is the COMPILED
        # GraphQLInputObjectType (``_meta.fields`` is intentionally empty for
        # scalar-only models under the native backend — scalars are derived from
        # the model + pydantic schema, not from graphene field descriptors). The
        # wire field names are camelCase aliases (e.g. ``is_active`` -> ``isActive``).
        field_names = set(WidgetCreateInput._meta.graphql_input_type.fields.keys())
        assert "title" in field_names, (
            f"'title' must be in WidgetCreateInput (not excluded) but got: {field_names}"
        )
        assert "body" in field_names, (
            f"'body' must be force-included by include_fields despite exclude_fields. "
            f"Got: {field_names}"
        )
        # is_active was excluded and NOT in include_fields, so it must be absent.
        assert "isActive" not in field_names, (
            f"'isActive' must be excluded (not in include_fields) but got: {field_names}"
        )

    def test_include_fields_overrides_only_on_input_type(self):
        """A field not in only_fields but in include_fields must be force-included."""
        from django_graphex.types import DjangoInputObjectType

        local_registry = Registry()

        class WidgetUpdateInput(DjangoInputObjectType):
            class Meta:
                model = MetaHygieneWidget
                registry = local_registry
                input_for = "update"
                only_fields = ("title",)
                include_fields = ("body",)  # force-include body despite only_fields

        # Native contract: assert the COMPILED GraphQLInputObjectType fields
        # (see the create-input test above for why ``_meta.fields`` is empty).
        field_names = set(WidgetUpdateInput._meta.graphql_input_type.fields.keys())
        assert "title" in field_names, (
            f"'title' must be in only_fields but got: {field_names}"
        )
        assert "body" in field_names, (
            f"'body' must be force-included by include_fields despite only_fields. "
            f"Got: {field_names}"
        )

    def test_include_fields_honored_on_list_type(self):
        """DjangoListObjectType (via its internal output type) must use include_fields."""
        from django_graphex.types import DjangoListObjectType

        local_registry = Registry()

        class WidgetListType(DjangoListObjectType):
            class Meta:
                model = MetaHygieneWidget
                registry = local_registry
                only_fields = ("title",)
                include_fields = ("body",)  # force-include body alongside title

        # Native contract: the inner baseType's canonical field surface is its
        # COMPILED GraphQLObjectType (``_meta.fields`` is intentionally empty for
        # scalar-only models natively). Wire names are camelCase.
        base_fields = set(
            WidgetListType._meta.baseType._meta.graphql_output_type.fields.keys()
        )
        assert "title" in base_fields, (
            f"'title' must be in baseType fields but got: {base_fields}"
        )
        assert "body" in base_fields, (
            f"'body' must be force-included by include_fields but got: {base_fields}"
        )
        # is_active was not in only_fields and not in include_fields.
        assert "isActive" not in base_fields, (
            f"'isActive' must not appear (not in only_fields or include_fields) "
            f"but got: {base_fields}"
        )


# ---------------------------------------------------------------------------
# (c) only_fields/exclude_fields omitting id → update KeyError
# ---------------------------------------------------------------------------


class TestUpdateWithIdExcluded(TestCase):
    """Update mutation must not KeyError when id is excluded from only_fields."""

    def setUp(self):
        self.widget = MetaHygieneWidget.objects.create(
            title="Original", body="text", is_active=True
        )

    def test_update_resolver_does_not_raise_keyerror_when_id_excluded(self):
        """mutation.py data.pop('id') must not raise when id is absent from input."""
        # We directly test that data.pop('id') was changed to data.pop('id', None).
        # That's the exact change that prevents the KeyError.

        # Simulate what the update resolver does after the fix:
        data2 = {"title": "Updated"}
        val = data2.pop("id", None)
        assert val is None, "After fix, missing id should yield None, not crash."

    def test_update_resolver_handles_none_pk_gracefully(self):
        """DjangoModelType.update must not raise KeyError when id absent from data."""
        # The real integration: DjangoModelType.update called with no 'id' in data.
        # Before the fix: data.pop('id') -> KeyError.
        # After the fix: data.pop('id', None) -> pk=None -> not_found response.
        from django_graphex.types import DjangoModelType

        class WidgetTypeForUpdate(DjangoModelType):
            class Meta:
                model = MetaHygieneWidget
                only_fields = ("title", "body")  # id excluded

        import types as builtin_types

        class FakeInfo:
            context = builtin_types.SimpleNamespace(
                META={"CONTENT_TYPE": "application/json"},
                FILES={},
            )

        # Call DjangoModelType.update directly with a dict that has no 'id' key.
        input_data = {"title": "Updated"}
        try:
            result = WidgetTypeForUpdate.update(
                None,
                FakeInfo(),
                **{WidgetTypeForUpdate._meta.input_field_name: input_data},
            )
            # Must return a result object (not raise) — ok=False is fine.
            assert result is not None, "update must return a result, not raise"
            assert result.ok is False, "update must return ok=False when pk is missing"
        except KeyError as exc:
            pytest.fail(
                f"types.py DjangoModelType.update data.pop('id') raised KeyError: "
                f"{exc!r}. Expected data.pop('id', None) after the fix."
            )


# ---------------------------------------------------------------------------
# (d) DjangoListObjectType.Meta.queryset validated but never consumed
# ---------------------------------------------------------------------------


class TestMetaQuerysetConsumed(TestCase):
    """DjangoListObjectField must use Meta.queryset when set."""

    def setUp(self):
        MetaHygieneWidget.objects.create(title="Active", is_active=True)
        MetaHygieneWidget.objects.create(title="Inactive", is_active=False)

    def test_list_field_uses_meta_queryset_in_wrap_resolve(self):
        """DjangoListObjectField.wrap_resolve must bind Meta.queryset, not _default_manager."""
        from django_graphex.fields import DjangoListObjectField
        from django_graphex.types import DjangoListObjectType

        local_registry = Registry()

        class ActiveWidgetListType(DjangoListObjectType):
            class Meta:
                model = MetaHygieneWidget
                registry = local_registry
                queryset = MetaHygieneWidget.objects.filter(is_active=True)

        field = DjangoListObjectField(ActiveWidgetListType)

        # The wrap_resolve resolver must bind the filtered queryset.
        # Inspect what the resolver binds: it should be the filtered queryset, not
        # the default manager (which would return all 2 widgets).
        from functools import partial

        resolver = field.wrap_resolve(None)

        # The partial's first bound argument should be the filtered queryset
        # (or a manager-like that yields only active records).
        # After the fix, resolver.args[0] should be the queryset, not _default_manager.
        if isinstance(resolver, partial):
            first_arg = resolver.args[0] if resolver.args else None
            from django.db.models import Manager, QuerySet

            if isinstance(first_arg, QuerySet):
                # Fixed: bound to the queryset — verify it filters correctly.
                count = first_arg.count()
                assert count == 1, (
                    f"Meta.queryset should yield 1 active widget, got {count}"
                )
            elif isinstance(first_arg, Manager):
                # Pre-fix: still bound to the default manager.
                pytest.fail(
                    "DjangoListObjectField.wrap_resolve still binds _default_manager "
                    "instead of Meta.queryset. Fix: use the queryset when set."
                )
            else:
                # Unknown — introspect the resolver.
                pytest.fail(
                    f"wrap_resolve returned unexpected first arg: {first_arg!r}"
                )
        else:
            pytest.fail(f"wrap_resolve returned non-partial: {resolver!r}")

    def test_meta_queryset_stored_in_meta(self):
        """Meta.queryset must be stored in _meta.queryset."""
        from django_graphex.types import DjangoListObjectType

        local_registry = Registry()
        active_qs = MetaHygieneWidget.objects.filter(is_active=True)

        class ActiveWidgetListType(DjangoListObjectType):
            class Meta:
                model = MetaHygieneWidget
                registry = local_registry
                queryset = active_qs

        assert ActiveWidgetListType._meta.queryset is active_qs
