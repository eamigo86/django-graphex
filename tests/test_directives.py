"""Behavioral coverage of the built-in and custom GraphQL directives.

Covers the date directive family, the bug-fix regression suite (base64,
center, floor/ceil, strip, shuffle/sample), the newer directives
(truncate, slugify, round, abs, unique, default), a custom "@mask"
directive mirroring the documented extension recipe, and the
"all_directives" static-vs-runtime type-consistency contract (issue #66a).
"""

from typing import Any

from django.test import TestCase
from graphql import (
    DirectiveLocation,
    GraphQLArgument,
    GraphQLDirective,
    GraphQLFloat,
    GraphQLInt,
    GraphQLList,
    GraphQLNonNull,
    GraphQLResolveInfo,
    GraphQLString,
    graphql_sync,
)
from graphql.execution import MiddlewareManager

from django_graphex.core import ObjectType, field
from django_graphex.directives import all_directives
from django_graphex.directives.base import BaseExtraGraphQLDirective
from django_graphex.middleware import GraphQLDirectiveMiddleware
from django_graphex.schema import DjangoGraphQLSchema
from tests.test_fields import ParentTest


class DateDirective_DateTime_Test(ParentTest, TestCase):
    """ "@date" formatting of a combined date-and-time field.

    Runs the standard "ParentTest" contract against a fixed datetime value.
    """

    query = """query { datetime @date(format:"HH:mm:ss YYYY.MM.DD") }"""
    expected_return_payload = {"data": {"datetime": "10:21:30 2020.12.31"}}


class DateDirective_Time_Test(ParentTest, TestCase):
    """ "@date" formatting of a time-only field.

    Runs the standard "ParentTest" contract against a fixed time value.
    """

    query = """query { time @date(format:"HH:mm:ss") }"""
    expected_return_payload = {"data": {"time": "10:21:30"}}


class DateDirective_Date_Test(ParentTest, TestCase):
    """ "@date" formatting of a date-only field.

    Runs the standard "ParentTest" contract against a fixed date value.
    """

    query = """query { date @date(format:"YYYY.MM.DD") }"""
    expected_return_payload = {"data": {"date": "2020.12.31"}}


# --------------------------------------------------------------------------- #
# Self-contained schema for the string / number / list directives             #
# --------------------------------------------------------------------------- #
class _DirectivesQuery(ObjectType):
    """Query root exposing fixed-value fields for exercising each directive."""

    text = field(GraphQLString)
    spaced = field(GraphQLString)
    encoded = field(GraphQLString)
    blank = field(GraphQLString)
    num = field(GraphQLFloat)
    snum = field(GraphQLString)
    items = field(GraphQLList(GraphQLString))

    def resolve_text(root: Any, info: Any) -> str:
        """Resolve "text" to a constant sample sentence.

        Args:
            root: The unused root value passed by the executor.
            info: The unused GraphQL resolve info passed by the executor.

        Returns:
            text: The literal string "Hello World".
        """
        return "Hello World"

    def resolve_spaced(root: Any, info: Any) -> str:
        """Resolve "spaced" to a string padded with whitespace for "@strip" tests.

        Args:
            root: The unused root value passed by the executor.
            info: The unused GraphQL resolve info passed by the executor.

        Returns:
            text: A string with leading/trailing whitespace around "hi".
        """
        return "  hi \t\n "

    def resolve_encoded(root: Any, info: Any) -> str:
        """Resolve "encoded" to a base64-encoded sample string.

        Args:
            root: The unused root value passed by the executor.
            info: The unused GraphQL resolve info passed by the executor.

        Returns:
            text: The base64 encoding of "Hello World".
        """
        return "SGVsbG8gV29ybGQ="

    def resolve_blank(root: Any, info: Any) -> None:
        """Resolve "blank" to None, for exercising null-handling directives.

        Args:
            root: The unused root value passed by the executor.
            info: The unused GraphQL resolve info passed by the executor.
        """
        return None

    def resolve_num(root: Any, info: Any) -> float:
        """Resolve "num" to a fixed negative float for math directive tests.

        Args:
            root: The unused root value passed by the executor.
            info: The unused GraphQL resolve info passed by the executor.

        Returns:
            value: The literal float -3.146.
        """
        return -3.146

    def resolve_snum(root: Any, info: Any) -> str:
        """Resolve "snum" to a numeric string for the "@abs" string-input test.

        Args:
            root: The unused root value passed by the executor.
            info: The unused GraphQL resolve info passed by the executor.

        Returns:
            value: The literal string "5.7".
        """
        return "5.7"

    def resolve_items(root: Any, info: Any) -> list[str]:
        """Resolve "items" to a list with a duplicate, for "@unique"/"@shuffle"/"@sample" tests.

        Args:
            root: The unused root value passed by the executor.
            info: The unused GraphQL resolve info passed by the executor.

        Returns:
            items: The literal list ["b", "a", "b", "c"].
        """
        return ["b", "a", "b", "c"]


# A valid FIELD directive that is NOT registered in django-graphex, to
# exercise the middleware's "skip unknown directive" guard (B2).
_noop_directive = GraphQLDirective(name="noop", locations=[DirectiveLocation.FIELD])

_directives_schema = DjangoGraphQLSchema(
    query=_DirectivesQuery, directives=list(all_directives) + [_noop_directive]
)
_middleware = MiddlewareManager(GraphQLDirectiveMiddleware())


class DirectivesTest(TestCase):
    """Behavioral coverage of the built-in field directives against "_directives_schema".

    Covers both the bug-fix regression suite and the newer directive set.
    """

    def _run(self, query: str, **variables: Any) -> Any:
        result = graphql_sync(
            _directives_schema.graphql_schema,
            query,
            middleware=_middleware,
            variable_values=variables or None,
        )
        self.assertIsNone(result.errors, result.errors)
        return result.data

    # -- bug fixes -------------------------------------------------------- #
    def test_base64_encode_with_op(self) -> None:  # B1
        """ "@base64(op:"encode")" must base64-encode the field value.

        Regression guard for bug B1: the "op" argument must be honored
        instead of always decoding.
        """
        self.assertEqual(
            self._run('{ text @base64(op:"encode") }')["text"], "SGVsbG8gV29ybGQ="
        )

    def test_base64_decode(self) -> None:  # B1
        """ "@base64(op:"decode")" must base64-decode the field value.

        Regression guard for bug B1: decoding must still work alongside the
        newly supported "encode" operation.
        """
        self.assertEqual(
            self._run('{ encoded @base64(op:"decode") }')["encoded"], "Hello World"
        )

    def test_directive_argument_as_variable(self) -> None:  # B4
        """A directive argument bound to a GraphQL variable must resolve to its runtime value.

        Regression guard for bug B4: "@center(width:$w, ...)" must read the
        variable value, not treat it as a literal or crash.
        """
        data = self._run('query($w:Int!){ text @center(width:$w, fillchar:"*") }', w=15)
        self.assertEqual(data["text"], "**Hello World**")

    def test_unregistered_directive_is_ignored(self) -> None:  # B2
        """A schema directive not known to the middleware must be ignored, leaving the value untouched.

        Regression guard for bug B2: unknown directives must be skipped
        instead of raising inside the middleware.
        """
        self.assertEqual(self._run("{ text @noop }")["text"], "Hello World")

    def test_floor_none(self) -> None:  # B3
        """ "@floor" applied to a None value must stay None instead of raising.

        Regression guard for bug B3: math directives must tolerate a null
        field value.
        """
        self.assertIsNone(self._run("{ blank @floor }")["blank"])

    def test_floor_ceil(self) -> None:  # B3
        """ "@floor" and "@ceil" must round a float down and up respectively.

        Regression guard for bug B3.
        """
        self.assertEqual(self._run("{ num @floor }")["num"], -4)
        self.assertEqual(self._run("{ num @ceil }")["num"], -3)

    def test_strip_default_whitespace(self) -> None:  # B5
        """ "@strip" with no arguments must trim surrounding whitespace by default.

        Regression guard for bug B5: the default character set must be
        whitespace, not an empty no-op.
        """
        self.assertEqual(self._run("{ spaced @strip }")["spaced"], "hi")

    def test_shuffle_does_not_lose_items(self) -> None:  # B6
        """ "@shuffle" must reorder a list without dropping or adding elements.

        Regression guard for bug B6.
        """
        data = self._run("{ items @shuffle }")["items"]
        self.assertEqual(sorted(data), ["a", "b", "b", "c"])

    def test_sample_clamps_k(self) -> None:  # B6
        """ "@sample(k:...)" must clamp "k" to the list length instead of erroring when "k" exceeds it.

        Regression guard for bug B6.
        """
        data = self._run("{ items @sample(k:10) }")["items"]
        self.assertEqual(sorted(data), ["a", "b", "b", "c"])

    # -- new directives --------------------------------------------------- #
    def test_truncate(self) -> None:
        """ "@truncate(length:...)" must shorten text to the given length with an ellipsis.

        If this breaks, truncated output could exceed the requested length
        or drop the ellipsis marker.
        """
        self.assertEqual(self._run("{ text @truncate(length:7) }")["text"], "Hello…")

    def test_truncate_killwords(self) -> None:
        """ "@truncate" with "killwords:true" must cut mid-word instead of at a word boundary.

        If this breaks, "killwords" would be ignored and truncation would
        always snap to the nearest word boundary.
        """
        self.assertEqual(
            self._run('{ text @truncate(length:7, killwords:true, end:"...") }')[
                "text"
            ],
            "Hello W...",
        )

    def test_slugify(self) -> None:
        """ "@slugify" must convert text to a lowercase, hyphenated slug.

        If this breaks, slugified output could retain spaces, casing, or
        punctuation instead of producing a URL-safe slug.
        """
        self.assertEqual(self._run("{ text @slugify }")["text"], "hello-world")

    def test_round(self) -> None:
        """ "@round" must round to the given precision, defaulting to zero decimal places.

        If this breaks, rounding could ignore the "precision" argument or
        produce the wrong default rounding behavior.
        """
        self.assertEqual(self._run("{ num @round(precision:1) }")["num"], -3.1)
        self.assertEqual(self._run("{ num @round }")["num"], -3)

    def test_abs(self) -> None:
        """ "@abs" must return the absolute value for both numeric and numeric-string fields.

        If this breaks, "@abs" could fail on string-typed numeric fields
        instead of coercing them before taking the absolute value.
        """
        self.assertEqual(self._run("{ num @abs }")["num"], 3.146)
        self.assertEqual(self._run("{ snum @abs }")["snum"], "5.7")

    def test_unique_preserves_order(self) -> None:
        """ "@unique" must drop duplicates while preserving first-seen order.

        If this breaks, deduplication could reorder elements or fail to
        remove a genuine duplicate.
        """
        self.assertEqual(self._run("{ items @unique }")["items"], ["b", "a", "c"])

    def test_default_on_blank(self) -> None:
        """ "@default(to:...)" must substitute the given value when the field resolves to None.

        If this breaks, a null field value could be returned as-is instead
        of falling back to the directive's default.
        """
        self.assertEqual(self._run('{ blank @default(to:"N/A") }')["blank"], "N/A")


# --------------------------------------------------------------------------- #
# Custom directive: mirrors the "Custom Directives" example in the docs so the #
# documented recipe stays verified end-to-end (define -> register -> execute). #
# --------------------------------------------------------------------------- #
class MaskGraphQLDirective(BaseExtraGraphQLDirective):
    """Keep the last "visible" characters, masking the rest.

    Mirrors the "Custom Directives" recipe from the documentation so the
    documented extension pattern stays verified end-to-end.
    """

    @staticmethod
    def get_args() -> dict[str, GraphQLArgument]:
        """Declare the "visible" and "char" arguments accepted by "@mask".

        Returns:
            args: A mapping of argument names to their GraphQL definitions.
        """
        return {
            "visible": GraphQLArgument(
                GraphQLNonNull(GraphQLInt),
                description="Number of trailing characters to leave visible",
            ),
            "char": GraphQLArgument(
                GraphQLString, description="Masking character (default: '*')"
            ),
        }

    @staticmethod
    def resolve(
        value: Any,
        args: dict[str, Any],
        directive: Any,
        root: Any,
        info: GraphQLResolveInfo,
        **kwargs: Any,
    ) -> Any:
        """Mask all but the trailing "visible" characters of the field value.

        Args:
            value: The field value to mask.
            args: The directive arguments, containing "visible" and
                optionally "char".
            directive: The directive AST/definition, unused here.
            root: The unused root value passed by the executor.
            info: The unused GraphQL resolve info passed by the executor.
            **kwargs: Additional executor-supplied keyword arguments, unused.

        Returns:
            masked: The value unchanged if falsy or shorter than "visible",
                otherwise the masked string.
        """
        if not value:
            return value
        text = str(value)
        visible = args.get("visible") or 0
        char = args.get("char") or "*"
        if visible >= len(text):
            return text
        return char * (len(text) - visible) + text[len(text) - visible :]


class _CustomQuery(ObjectType):
    """Query root exposing a card-number field for the "@mask" directive demo."""

    card = field(GraphQLString)

    def resolve_card(root: Any, info: Any) -> str:
        """Resolve "card" to a fixed sample card number.

        Args:
            root: The unused root value passed by the executor.
            info: The unused GraphQL resolve info passed by the executor.

        Returns:
            card: The literal string "4111111111111234".
        """
        return "4111111111111234"


# Register the custom directive by passing an instance alongside the built-ins.
_custom_schema = DjangoGraphQLSchema(
    query=_CustomQuery, directives=[*all_directives, MaskGraphQLDirective()]
)


class CustomDirectiveTest(TestCase):
    """End-to-end coverage of the custom "@mask" directive: define, register, execute.

    Mirrors the "Custom Directives" documentation recipe against a live
    schema.
    """

    def _run(self, query: str, **variables: Any) -> Any:
        result = graphql_sync(
            _custom_schema.graphql_schema,
            query,
            middleware=MiddlewareManager(GraphQLDirectiveMiddleware()),
            variable_values=variables or None,
        )
        self.assertIsNone(result.errors, result.errors)
        return result.data

    def test_name_is_derived_from_class(self) -> None:
        """The directive name must be derived from the class name, minus the "GraphQLDirective" suffix.

        If this breaks, "MaskGraphQLDirective" could register under the
        wrong GraphQL name and never match "@mask" in a query.
        """
        # MaskGraphQLDirective -> "@mask"
        self.assertEqual(MaskGraphQLDirective.get_name(), "mask")

    def test_mask_keeps_last_n_visible(self) -> None:
        """ "@mask(visible: 4)" must mask all but the last four characters with the default character.

        If this breaks, the masking directive could reveal more of the
        value than intended (a sensitive-data leak in this recipe).
        """
        self.assertEqual(
            self._run("{ card @mask(visible: 4) }")["card"], "************1234"
        )

    def test_mask_custom_char(self) -> None:
        """ "@mask(visible:, char:)" must use the given character instead of the default asterisk.

        If this breaks, the "char" argument would be ignored in favor of a
        hardcoded mask character.
        """
        self.assertEqual(
            self._run('{ card @mask(visible: 4, char: "#") }')["card"],
            "############1234",
        )

    def test_mask_argument_as_variable(self) -> None:
        """A "@mask" argument bound to a GraphQL variable must resolve to its runtime value.

        If this breaks, custom directives could fail to support
        variable-bound arguments even though built-in directives do.
        """
        data = self._run("query($n: Int!){ card @mask(visible: $n) }", n=4)
        self.assertEqual(data["card"], "************1234")


# ---------------------------------------------------------------------------
# Issue #66 (a) — all_directives static-vs-runtime type consistency
# ---------------------------------------------------------------------------


class TestAllDirectivesTypeConsistency(TestCase):
    """Issue #66(a): "all_directives" must be a list of GraphQLDirective instances, not classes.

    Before the fix, "all_directives" was first bound to a tuple of directive
    classes (24 items), then immediately rebound to a list of instances (30
    items). Mypy kept the first binding's inferred type, so callsites got
    incorrect type inference and the count discrepancy was hidden.

    After the fix, the class tuple is stored under "_DIRECTIVE_CLASSES" (or
    an equivalent private name) and "all_directives" only ever holds the list
    of 30 instances, giving mypy a single consistent static type.
    """

    def test_all_directives_is_a_list(self) -> None:
        """ ""all_directives" must be a list, not a tuple or other sequence type.

        If this breaks, mypy would infer an inconsistent static type across
        the two bindings the regression previously left behind.
        """
        from django_graphex.directives import all_directives

        self.assertIsInstance(
            all_directives,
            list,
            f"all_directives must be a list, got {type(all_directives).__name__}",
        )

    def test_all_directives_elements_are_instances_not_classes(self) -> None:
        """Every element of "all_directives" must be a directive instance, not a class.

        If this breaks, schemas built from "all_directives" would receive
        uninstantiated directive classes instead of usable directives.
        """
        from graphql import GraphQLDirective

        from django_graphex.directives import all_directives

        for i, d in enumerate(all_directives):
            self.assertIsInstance(
                d,
                GraphQLDirective,
                f"all_directives[{i}] is {d!r} — expected a GraphQLDirective instance, got {type(d).__name__}",
            )
            self.assertFalse(
                isinstance(d, type),
                f"all_directives[{i}] is a CLASS ({d!r}), not an instance",
            )

    def test_all_directives_count_includes_default_directives(self) -> None:
        """ ""all_directives" must include the default GraphQL built-in directives.

        If this breaks, the custom-plus-default directive count could drift
        silently, e.g. after adding a custom directive without updating the
        splice with graphql-core's default bundle.
        """
        from graphql.type.directives import specified_directives

        from django_graphex import directives as dir_module
        from django_graphex.directives import all_directives

        # Verify the total equals _DIRECTIVE_CLASSES count + default directives count.
        expected_total = len(dir_module._DIRECTIVE_CLASSES) + len(specified_directives)
        self.assertEqual(
            len(all_directives),
            expected_total,
            f"all_directives must contain {expected_total} items "
            f"({len(dir_module._DIRECTIVE_CLASSES)} custom + {len(specified_directives)} default), "
            f"got {len(all_directives)}",
        )

    def test_all_directives_includes_the_five_spec_directive_names(self) -> None:
        """ ""all_directives" must expose the five graphql-core spec directives by name.

        The spec directives ship inside graphql-core's "specified_directives"
        bundle: "skip", "include", "deprecated", "specifiedBy" and "oneOf".
        "all_directives" splices them in via "[*default_directives]", so
        their presence is a bundle contract — a regression that dropped a
        spec directive (or swapped the graphql-core bundle) would silently
        strip "@skip" / "@deprecated" support from every schema built with
        "all_directives". Asserting the names guards that contract (it does
        NOT add custom support for "@specifiedBy" / "@oneOf" — those come
        from graphql-core itself).
        """
        from django_graphex.directives import all_directives

        names = {d.name for d in all_directives}
        for spec_name in ("skip", "include", "deprecated", "specifiedBy", "oneOf"):
            self.assertIn(
                spec_name,
                names,
                f"spec directive {spec_name!r} missing from all_directives — the "
                f"graphql-core specified_directives bundle contract is broken",
            )

    def test_directive_classes_tuple_available_separately(self) -> None:
        """The private "_DIRECTIVE_CLASSES" tuple must exist and contain only class objects.

        If this breaks, the class-vs-instance separation this issue fixed
        could regress, since callers rely on "_DIRECTIVE_CLASSES" holding
        classes exclusively.
        """
        from django_graphex import directives as dir_module

        self.assertTrue(
            hasattr(dir_module, "_DIRECTIVE_CLASSES"),
            "directives module must export _DIRECTIVE_CLASSES (the tuple of directive classes)",
        )
        classes = dir_module._DIRECTIVE_CLASSES
        self.assertIsInstance(classes, tuple, "_DIRECTIVE_CLASSES must be a tuple")
        self.assertGreater(
            len(classes),
            0,
            "_DIRECTIVE_CLASSES must be non-empty",
        )
        for cls in classes:
            self.assertTrue(
                isinstance(cls, type),
                f"_DIRECTIVE_CLASSES element {cls!r} must be a class",
            )
