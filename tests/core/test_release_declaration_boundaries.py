"""Exercise supported declaration and native-container boundary behavior."""

from __future__ import annotations

import warnings
from typing import Any, ClassVar

import pytest
from django.core.exceptions import ImproperlyConfigured
from django.db.models import QuerySet
from django.test import override_settings
from graphql import GraphQLInputObjectType, GraphQLString, graphql_sync
from pydantic import BaseModel

from django_graphex.core import ObjectType
from django_graphex.core.base import NativeObjectTypeOptions
from django_graphex.core.input_compiler import NestedInputField, compile_input_type
from django_graphex.fields import DjangoListObjectField
from django_graphex.registry import Registry
from django_graphex.schema import DjangoGraphQLSchema
from django_graphex.types import DjangoListObjectType, DjangoModelType
from tests._schema_isolation import isolated_pair
from tests.models import BasicModel


@pytest.mark.django_db
def test_explicit_unpaginated_list_container_has_plain_results() -> None:
    """Keep list results and count plain without a default paginator.

    The compiled schema must expose neither pagination arguments nor pageInfo.
    """
    local_registry = Registry()
    with override_settings(DJANGO_GRAPHEX={"DEFAULT_PAGINATION_CLASS": None}):

        class PlainList(DjangoListObjectType):
            """Declare a real model list with no pagination."""

            class Meta:
                """Bind the list to a model and isolated registry."""

                model = BasicModel
                registry = local_registry
                pagination = None

        class Query(ObjectType):
            """Expose the unpaginated list for schema execution."""

            entries = DjangoListObjectField(PlainList)

        schema = DjangoGraphQLSchema(
            query=Query, registries=isolated_pair(local_registry)
        )
        container = schema.graphql_schema.query_type.fields["entries"].type
        assert set(container.fields) >= {"results", "totalCount"}
        assert "pageInfo" not in container.fields
        assert container.fields["results"].args == {}
        result = graphql_sync(
            schema.graphql_schema, "{ entries { totalCount results { id } } }"
        )
        assert result.errors is None
        assert result.data == {"entries": {"totalCount": 0, "results": []}}


def test_model_type_rejects_legacy_serialization_option() -> None:
    """Report the supported replacement for a removed model option.

    Misconfiguration must fail before a mutation field can be mounted.
    """
    with pytest.raises(ImproperlyConfigured, match=r"serialize_data.*payload_mode"):

        class LegacySerialization(DjangoModelType):
            """Declare the removed model option."""

            class Meta:
                """Bind the declaration to a real model."""

                model = BasicModel
                serialize_data = True


def test_model_type_rejects_unknown_payload_mode() -> None:
    """Reject unsupported subscription payload modes at declaration time.

    The error names both supported modes instead of silently choosing one.
    """
    with pytest.raises(ImproperlyConfigured, match=r'payload_mode.*"full".*"id_only"'):

        class InvalidPayloadMode(DjangoModelType):
            """Declare an unsupported mode."""

            class Meta:
                """Bind the mode to a real model."""

                model = BasicModel
                payload_mode = "everything"


def test_model_type_arguments_precede_legacy_input() -> None:
    """Compile declared Arguments without a compatibility warning.

    The caller-provided argument remains visible on the mutation field.
    """
    from graphql import GraphQLArgument

    class CurrentArguments(DjangoModelType):
        """Declare an argument through the current API."""

        class Meta:
            """Bind the mutation to a real model."""

            model = BasicModel

        class Arguments:
            """Expose a caller-provided note."""

            note = GraphQLArgument(GraphQLString)

    with warnings.catch_warnings(record=True) as seen:
        warnings.simplefilter("always", DeprecationWarning)
        field = CurrentArguments.CreateField()
    assert "note" in field.args
    assert not any(issubclass(item.category, DeprecationWarning) for item in seen)


def test_model_type_legacy_input_emits_migration_warning() -> None:
    """Preserve the legacy Input argument while warning about migration.

    Existing callers retain the field until they adopt Arguments.
    """
    from graphql import GraphQLArgument

    with pytest.warns(DeprecationWarning, match="Arguments instead"):

        class LegacyArguments(DjangoModelType):
            """Declare an argument through the compatibility API."""

            class Meta:
                """Bind the mutation to a real model."""

                model = BasicModel

            class Input:
                """Expose a legacy caller-provided note."""

                note = GraphQLArgument(GraphQLString)

    assert "note" in LegacyArguments.CreateField().args


def test_model_type_collects_nonreserved_custom_filter() -> None:
    """Keep a nonreserved custom filter on the query input surface.

    The declared scalar is reflected by the actual input compiler.
    """
    from django_graphex.filtering import filter_field

    class Searchable(DjangoModelType):
        """Expose a nonreserved model search argument."""

        class Meta:
            """Bind custom filtering to a real model."""

            model = BasicModel

        @filter_field(GraphQLString)
        def matches(
            cls: type[Searchable],
            queryset: QuerySet[BasicModel],
            info: Any,
            value: str,
        ) -> QuerySet[BasicModel]:
            """Return records whose text contains the supplied term.

            Args:
                cls: The declaring type.
                queryset: The queryset to filter.
                info: The GraphQL execution context.
                value: The requested search text.

            Returns:
                The filtered queryset.
            """
            return queryset.filter(text__icontains=value)

    assert [item[0] for item in Searchable._dgx_custom_filters] == ["matches"]
    from django_graphex.filtering.native_schema import build_filter_input_type

    filter_input = build_filter_input_type(
        BasicModel, {}, custom_filters=Searchable._dgx_custom_filters
    )
    assert filter_input.fields["matches"].type is GraphQLString


def test_subscription_type_without_stream_rejects_declaration() -> None:
    """Refuse to expose a subscription without its stream.

    This catches a declaration error before transport setup begins.
    """

    class NoStream(DjangoModelType):
        """Declare a model without a subscription stream."""

        class Meta:
            """Bind the type to a real model."""

            model = BasicModel

    with pytest.raises(ImproperlyConfigured, match=r"Meta.stream must be set"):
        NoStream.subscription_type()


def test_native_options_overrides_are_preserved() -> None:
    """Apply explicit native option values without freezing the object.

    A concrete driver may still update the resulting option values.
    """
    options = NativeObjectTypeOptions(
        ObjectType, interfaces=("interface",), name="Custom"
    )
    assert options.class_type is ObjectType
    assert options.interfaces == ("interface",)
    assert options.name == "Custom"
    options.name = "Changed"
    assert options.name == "Changed"


def test_native_driver_rejects_invalid_meta_object() -> None:
    """Reject an invalid Meta value with a precise type error.

    The annotated value reaches the driver rather than Pydantic field inference.
    """
    with pytest.raises(TypeError, match=r"Meta has to be either a class or a dict"):

        class InvalidMeta(ObjectType):
            """Present a Pydantic-safe but invalid Meta value."""

            Meta: ClassVar[int] = 42


def test_native_driver_preserves_prebuilt_options_and_interfaces() -> None:
    """Retain prebuilt options and interfaces supplied by a concrete driver.

    The terminal driver must not replace the prepared option object.
    """

    class PrebuiltBase(ObjectType):
        """Build options for a subsequently declared concrete type."""

        class Meta:
            """Keep the driver base abstract."""

            abstract = True

        @classmethod
        def __init_subclass_with_meta__(
            cls: type[PrebuiltBase], **options: Any
        ) -> None:
            """Forward a prebuilt option object to the terminal driver.

            Args:
                **options: Options declared by the class metadata.
            """
            built = NativeObjectTypeOptions(cls, interfaces=("declared",))
            super().__init_subclass_with_meta__(_meta=built, **options)

    class Prebuilt(PrebuiltBase):
        """Materialize the prebuilt driver options."""

        class Meta:
            """Give the subclass an explicit GraphQL type name."""

            name = "PrebuiltOutput"

    assert Prebuilt._meta.class_type is Prebuilt
    assert Prebuilt._meta.interfaces == ("declared",)
    assert Prebuilt._meta.name == "PrebuiltOutput"


def test_auto_list_type_uses_limit_offset_when_default_disabled() -> None:
    """Give an unregistered list type the documented fallback paginator.

    A repeated lookup returns the same registered type.
    """
    from django_graphex.paginations import LimitOffsetGraphqlPagination
    from django_graphex.types import get_or_create_list_object_type

    registry = Registry()
    with override_settings(DJANGO_GRAPHEX={"DEFAULT_PAGINATION_CLASS": None}):
        generated = get_or_create_list_object_type(BasicModel, registry)
        assert isinstance(generated._meta.paginator, LimitOffsetGraphqlPagination)
        assert get_or_create_list_object_type(BasicModel, registry) is generated


def test_native_driver_inherited_descriptor_uses_subclass_override() -> None:
    """Let a subclass descriptor replace an inherited field of the same name.

    The native driver preserves the most-derived field description.
    """
    from django_graphex.core import field

    class Parent(ObjectType):
        """Provide a parent descriptor."""

        value = field(GraphQLString)

    class Child(Parent):
        """Replace the inherited descriptor."""

        value = field(GraphQLString, description="child field")

    assert Child._meta.fields["value"] is Child.__dict__["value"]
    assert Child._meta.fields["value"].description == "child field"


@pytest.mark.parametrize("permissions", [None, ("tests.change_basicmodel",)])
def test_nested_input_concrete_permissions_are_stamped(
    permissions: tuple[str, ...] | None,
) -> None:
    """Nested input fields preserve declared permission labels and aliases.

    Args:
        permissions: A concrete permission tuple or no label.
    """
    child = GraphQLInputObjectType("DeclaredChildInput", {"name": GraphQLString})

    class ParentInput(BaseModel):
        """Provide a parent Pydantic input shape."""

        title: str

    nested = NestedInputField(
        out_name="child_record",
        alias="childRecord",
        child_input_type=child,
        is_list=False,
        required_perms=permissions,
    )
    compiled = compile_input_type(
        ParentInput, name="DeclaredParentInput", nested_fields=(nested,)
    )
    field = compiled.fields["childRecord"]
    assert field.type is child
    assert field.out_name == "child_record"
    assert field.extensions == (
        {"gdx_required_perms": permissions} if permissions is not None else {}
    )
