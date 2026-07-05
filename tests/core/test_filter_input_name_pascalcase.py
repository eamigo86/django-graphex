"""FIX 2 — native "<Model>FilterInput" type-name casing.

"filtering.native_schema.build_filter_input_type" assembled the input-type
NAME by round-tripping a PascalCase compound through the snake-to-camel
helper:

    name = to_camel_case(f"{model._meta.object_name}_FilterInput")

"to_camel_case" is defined for snake_case to camelCase: it keeps the first
component verbatim and "str.capitalize()"-s every later component (first char
upper, REST lower-cased). Feeding it "User_FilterInput" therefore yields
"UserFilterinput", the "I" in "Input" is silently lower-cased. That helper is
the WRONG tool for assembling a Pascal compound name.

The fix builds the name directly as "f'{object_name}FilterInput'" (no strconv
round-trip) producing "UserFilterInput" / "PostFilterInput" with the correct
PascalCase "FilterInput" suffix.
"""

from __future__ import annotations

import pytest


@pytest.mark.django_db
def test_native_filter_input_name_is_pascalcase_filterinput() -> None:
    """Assert that the compiled native filter input type name is PascalCase.

    If this fails, the filter input name would regress to the lower-cased
    "<Model>Filterinput" the old strconv round-trip produced, breaking any
    client code that references the exact "<Model>FilterInput" type name.
    """
    from django_graphex.filtering.native_schema import build_filter_input_type
    from django_graphex.registry import Registry
    from tests.models import OrderParent

    built = build_filter_input_type(
        OrderParent,
        {"title": ("icontains",)},
        Registry(),
    )

    assert built is not None, "filter input build must produce a type"
    assert built.name == "OrderParentFilterInput", (
        "the native filter input name must be PascalCase "
        f"'OrderParentFilterInput' (capital 'I'); got {built.name!r}"
    )
    assert "Filterinput" not in built.name, (
        "the lower-cased 'Filterinput' suffix (strconv round-trip artifact) must "
        f"be gone; got {built.name!r}"
    )


@pytest.mark.django_db
def test_filter_input_name_in_schema_type_map_is_pascalcase() -> None:
    """Assert that a filterable list field registers its input as PascalCase.

    Covers the end-to-end path: if this fails, the filter input type would be
    registered under the wrong-cased name in the schema's type map, so
    clients querying "<Model>FilterInput" would not find it.
    """
    from graphql import print_type

    from django_graphex.core import ObjectType
    from django_graphex.core.registry_compiler import compile_all_outputs
    from django_graphex.fields import DjangoListObjectField
    from django_graphex.schema import DjangoGraphQLSchema
    from django_graphex.types import DjangoListObjectType, DjangoObjectType
    from tests.models import OrderParent

    class _PascalParentType(DjangoObjectType):
        class Meta:
            model = OrderParent
            filter_fields = {"id": ("exact",), "title": ("icontains",)}

    class _PascalParentListType(DjangoListObjectType):
        class Meta:
            model = OrderParent

    compile_all_outputs()

    class _PascalQuery(ObjectType):
        parents = DjangoListObjectField(_PascalParentListType)

    schema = DjangoGraphQLSchema(query=_PascalQuery)
    type_map = schema.graphql_schema.type_map

    assert "OrderParentFilterInput" in type_map, (
        "the schema must register the filter input as 'OrderParentFilterInput' "
        f"(capital 'I'); got {[n for n in type_map if 'Filter' in n]!r}"
    )
    assert "OrderParentFilterinput" not in type_map, (
        "the lower-cased 'OrderParentFilterinput' must NOT be present"
    )
    sdl = print_type(type_map["OrderParentFilterInput"])
    assert sdl.startswith("input OrderParentFilterInput"), (
        f"filter input SDL header must use PascalCase; got {sdl.splitlines()[0]!r}"
    )
