"""S5 RED — base_types.py repoints "to_camel_case" off graphene to "_strconv".

Phase 7 S5 narrows the graphene-symbol surface of "base_types.py". The
module-level "import graphene" (line 9) and "from graphene.types.datetime
import Date, DateTime, Time" (line 10) CANNOT be removed yet: "Binary",
"CustomDate" / "CustomDateTime" / "CustomTime" and "GenericForeignKeyType"
/ "GenericForeignKeyInputType" remain LIVE graphene field-descriptor surface
consumed by "converter.py" on the native path ("construct_fields" is called
unconditionally at "types.py:477" on both backends). Those are deferred to
S-ROOTS / S8.

What S5 DOES land here: the byte-safe "to_camel_case" import is repointed from
"graphene.utils.str_converters" to "django_graphex._strconv" (already pinned
byte-equivalent by "tests/core/test_strconv.py"). This removes ONE graphene
import line and proves "factory_type" naming is unchanged.

Run: .venv/bin/python -m pytest \
    tests/core/test_s5_base_types_strconv.py -q -o addopts=""
"""

from __future__ import annotations

import ast
import inspect


def _module_imports(module: object) -> list[ast.stmt]:
    """Parse a module's source and return its top-level import statements."""
    source = inspect.getsource(module)
    tree = ast.parse(source)
    return [
        node for node in tree.body if isinstance(node, (ast.Import, ast.ImportFrom))
    ]


def test_base_types_to_camel_case_imported_from_strconv() -> None:
    """Ships broken if "base_types" stops importing "to_camel_case" from
    "_strconv" and reverts to importing it from graphene.
    """
    from django_graphex import base_types

    imports = _module_imports(base_types)

    # The graphene str_converters import must be GONE.
    graphene_strconv = [
        node
        for node in imports
        if isinstance(node, ast.ImportFrom)
        and node.module == "graphene.utils.str_converters"
    ]
    assert not graphene_strconv, (
        "base_types.py must NOT import to_camel_case from "
        "graphene.utils.str_converters — repoint to django_graphex._strconv."
    )

    # And the _strconv import must be PRESENT, binding to_camel_case.
    strconv_imports = [
        node
        for node in imports
        if isinstance(node, ast.ImportFrom)
        and node.module is not None
        and node.module.endswith("_strconv")
        and any(alias.name == "to_camel_case" for alias in node.names)
    ]
    assert strconv_imports, (
        "base_types.py must import to_camel_case from django_graphex._strconv "
        "(byte-equivalent, graphene-free)."
    )


def test_base_types_to_camel_case_is_strconv_object() -> None:
    """Ships broken if the "to_camel_case" symbol bound in base_types stops
    being the exact _strconv object (e.g. a re-wrapped or re-imported copy).
    """
    from django_graphex import base_types
    from django_graphex._strconv import to_camel_case as strconv_to_camel

    assert base_types.to_camel_case is strconv_to_camel


def test_factory_type_output_name_unchanged_after_repoint() -> None:
    """Ships broken if "factory_type" auto-naming stops matching to_camel_case
    output (byte-safe repoint regression).

    The generated output type name for a model with NO explicit "Meta.name"
    is "to_camel_case("<Model>_Generic_Type")". This must be identical before
    and after the repoint (byte-equivalence guarantee).
    """
    from django_graphex._strconv import to_camel_case

    # The exact string factory_type builds for an unnamed output type. The FIRST
    # underscore-component is kept verbatim (graphene parity), so the leading
    # "Post" capital is preserved while later components are str.capitalize()-d.
    expected = to_camel_case("Post_Generic_Type")
    assert expected == "PostGenericType"
