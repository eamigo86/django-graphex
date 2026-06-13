import graphene
from django.test import TestCase
from graphql import (
    DirectiveLocation,
    GraphQLArgument,
    GraphQLDirective,
    GraphQLInt,
    GraphQLNonNull,
    GraphQLString,
)

from django_graphex import GraphQLDirectiveMiddleware, all_directives
from django_graphex.directives.base import BaseExtraGraphQLDirective
from tests.test_fields import ParentTest


class DateDirective_DateTime_Test(ParentTest, TestCase):
    query = """query { datetime @date(format:"HH:mm:ss YYYY.MM.DD") }"""
    expected_return_payload = {"data": {"datetime": "10:21:30 2020.12.31"}}


class DateDirective_Time_Test(ParentTest, TestCase):
    query = """query { time @date(format:"HH:mm:ss") }"""
    expected_return_payload = {"data": {"time": "10:21:30"}}


class DateDirective_Date_Test(ParentTest, TestCase):
    query = """query { date @date(format:"YYYY.MM.DD") }"""
    expected_return_payload = {"data": {"date": "2020.12.31"}}


# --------------------------------------------------------------------------- #
# Self-contained schema for the string / number / list directives             #
# --------------------------------------------------------------------------- #
class _DirectivesQuery(graphene.ObjectType):
    text = graphene.String()
    spaced = graphene.String()
    encoded = graphene.String()
    blank = graphene.String()
    num = graphene.Float()
    snum = graphene.String()
    items = graphene.List(graphene.String)

    def resolve_text(root, info):
        return "Hello World"

    def resolve_spaced(root, info):
        return "  hi \t\n "

    def resolve_encoded(root, info):
        return "SGVsbG8gV29ybGQ="

    def resolve_blank(root, info):
        return None

    def resolve_num(root, info):
        return -3.146

    def resolve_snum(root, info):
        return "5.7"

    def resolve_items(root, info):
        return ["b", "a", "b", "c"]


# A valid FIELD directive that is NOT registered in django-graphex, to
# exercise the middleware's "skip unknown directive" guard (B2).
_noop_directive = GraphQLDirective(name="noop", locations=[DirectiveLocation.FIELD])

_directives_schema = graphene.Schema(
    query=_DirectivesQuery, directives=list(all_directives) + [_noop_directive]
)
_middleware = [GraphQLDirectiveMiddleware()]


class DirectivesTest(TestCase):
    def _run(self, query, **variables):
        result = _directives_schema.execute(
            query, middleware=_middleware, variables=variables or None
        )
        self.assertIsNone(result.errors, result.errors)
        return result.data

    # -- bug fixes -------------------------------------------------------- #
    def test_base64_encode_with_op(self):  # B1
        self.assertEqual(
            self._run('{ text @base64(op:"encode") }')["text"], "SGVsbG8gV29ybGQ="
        )

    def test_base64_decode(self):  # B1
        self.assertEqual(
            self._run('{ encoded @base64(op:"decode") }')["encoded"], "Hello World"
        )

    def test_directive_argument_as_variable(self):  # B4
        data = self._run('query($w:Int!){ text @center(width:$w, fillchar:"*") }', w=15)
        self.assertEqual(data["text"], "**Hello World**")

    def test_unregistered_directive_is_ignored(self):  # B2
        self.assertEqual(self._run("{ text @noop }")["text"], "Hello World")

    def test_floor_none(self):  # B3
        self.assertIsNone(self._run("{ blank @floor }")["blank"])

    def test_floor_ceil(self):  # B3
        self.assertEqual(self._run("{ num @floor }")["num"], -4)
        self.assertEqual(self._run("{ num @ceil }")["num"], -3)

    def test_strip_default_whitespace(self):  # B5
        self.assertEqual(self._run("{ spaced @strip }")["spaced"], "hi")

    def test_shuffle_does_not_lose_items(self):  # B6
        data = self._run("{ items @shuffle }")["items"]
        self.assertEqual(sorted(data), ["a", "b", "b", "c"])

    def test_sample_clamps_k(self):  # B6
        data = self._run("{ items @sample(k:10) }")["items"]
        self.assertEqual(sorted(data), ["a", "b", "b", "c"])

    # -- new directives --------------------------------------------------- #
    def test_truncate(self):
        self.assertEqual(self._run("{ text @truncate(length:7) }")["text"], "Hello…")

    def test_truncate_killwords(self):
        self.assertEqual(
            self._run('{ text @truncate(length:7, killwords:true, end:"...") }')[
                "text"
            ],
            "Hello W...",
        )

    def test_slugify(self):
        self.assertEqual(self._run("{ text @slugify }")["text"], "hello-world")

    def test_round(self):
        self.assertEqual(self._run("{ num @round(precision:1) }")["num"], -3.1)
        self.assertEqual(self._run("{ num @round }")["num"], -3)

    def test_abs(self):
        self.assertEqual(self._run("{ num @abs }")["num"], 3.146)
        self.assertEqual(self._run("{ snum @abs }")["snum"], "5.7")

    def test_unique_preserves_order(self):
        self.assertEqual(self._run("{ items @unique }")["items"], ["b", "a", "c"])

    def test_default_on_blank(self):
        self.assertEqual(self._run('{ blank @default(to:"N/A") }')["blank"], "N/A")


# --------------------------------------------------------------------------- #
# Custom directive: mirrors the "Custom Directives" example in the docs so the #
# documented recipe stays verified end-to-end (define -> register -> execute). #
# --------------------------------------------------------------------------- #
class MaskGraphQLDirective(BaseExtraGraphQLDirective):
    """Keep the last `visible` characters, masking the rest."""

    @staticmethod
    def get_args():
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
    def resolve(value, args, directive, root, info, **kwargs):
        if not value:
            return value
        text = str(value)
        visible = args.get("visible") or 0
        char = args.get("char") or "*"
        if visible >= len(text):
            return text
        return char * (len(text) - visible) + text[len(text) - visible :]


class _CustomQuery(graphene.ObjectType):
    card = graphene.String()

    def resolve_card(root, info):
        return "4111111111111234"


# Register the custom directive by passing an instance alongside the built-ins.
_custom_schema = graphene.Schema(
    query=_CustomQuery, directives=[*all_directives, MaskGraphQLDirective()]
)


class CustomDirectiveTest(TestCase):
    def _run(self, query, **variables):
        result = _custom_schema.execute(
            query,
            middleware=[GraphQLDirectiveMiddleware()],
            variables=variables or None,
        )
        self.assertIsNone(result.errors, result.errors)
        return result.data

    def test_name_is_derived_from_class(self):
        # MaskGraphQLDirective -> "@mask"
        self.assertEqual(MaskGraphQLDirective.get_name(), "mask")

    def test_mask_keeps_last_n_visible(self):
        self.assertEqual(
            self._run("{ card @mask(visible: 4) }")["card"], "************1234"
        )

    def test_mask_custom_char(self):
        self.assertEqual(
            self._run('{ card @mask(visible: 4, char: "#") }')["card"],
            "############1234",
        )

    def test_mask_argument_as_variable(self):
        data = self._run("query($n: Int!){ card @mask(visible: $n) }", n=4)
        self.assertEqual(data["card"], "************1234")


# ---------------------------------------------------------------------------
# Issue #66 (a) — all_directives static-vs-runtime type consistency
# ---------------------------------------------------------------------------


class TestAllDirectivesTypeConsistency(TestCase):
    """#66(a): all_directives must be a list of GraphQLDirective *instances*,
    not classes, with a consistent static type that mypy can verify.

    Before the fix, ``all_directives`` was first bound to a tuple of directive
    CLASSES (24 items), then immediately rebound to a list of INSTANCES (30
    items). Mypy kept the first binding's inferred type, so callsites got
    incorrect type inference and the count discrepancy was hidden.

    After the fix, the class-tuple is stored under ``_DIRECTIVE_CLASSES``
    (or equivalent private name) and ``all_directives`` only ever holds the
    list of 30 instances.
    """

    def test_all_directives_is_a_list(self):
        """all_directives must be a list (not a tuple or other sequence)."""
        from django_graphex import all_directives

        self.assertIsInstance(
            all_directives,
            list,
            f"all_directives must be a list, got {type(all_directives).__name__}",
        )

    def test_all_directives_elements_are_instances_not_classes(self):
        """Every element of all_directives must be a directive *instance*, not a class."""
        from graphql import GraphQLDirective

        from django_graphex import all_directives

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

    def test_all_directives_count_includes_default_directives(self):
        """all_directives must include the default GraphQL built-in directives."""
        from graphql.type.directives import specified_directives

        from django_graphex import all_directives
        from django_graphex import directives as dir_module

        # Verify the total equals _DIRECTIVE_CLASSES count + default directives count.
        expected_total = len(dir_module._DIRECTIVE_CLASSES) + len(specified_directives)
        self.assertEqual(
            len(all_directives),
            expected_total,
            f"all_directives must contain {expected_total} items "
            f"({len(dir_module._DIRECTIVE_CLASSES)} custom + {len(specified_directives)} default), "
            f"got {len(all_directives)}",
        )

    def test_directive_classes_tuple_available_separately(self):
        """The private _DIRECTIVE_CLASSES tuple must exist and contain only class objects."""
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
