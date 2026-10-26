# -*- coding: utf-8 -*-
"""The schema-suggestion strip runs in linear time and matches its old regex.

"format_graphql_error" used a lazy regex whose cost grew with the square of the
message length: a 224 KB message took seconds. The strip is now a linear scan.
The reference pattern below is the previous regex, kept here as the oracle the
scan must agree with.
"""

from __future__ import annotations

import random
import re
import time

from django.test import SimpleTestCase, override_settings
from graphql import GraphQLError

from django_graphex.security import (
    DisableIntrospectionMiddleware,
    format_graphql_error,
)

_PREFIXES = (
    r"Cannot query field '[^']*' on type '[^']*'\.",
    r"Unknown type '[^']*'\.",
    r"Unknown argument '[^']*' on (?:field|directive) '[^']*'\.",
    r"Field '[^']*' is not defined by type '[^']*'\.",
    r"Value '[^']*' does not exist in '[^']*' enum\.",
    r"Enum '[^']*' cannot represent non-(?:string|enum) value: .*?",
)
_REFERENCE = re.compile(
    "^((?:Variable '\\$[^']*' got invalid value .*?; )?(?:"
    + "|".join(_PREFIXES)
    + r"))\s+Did you mean .*\?$"
)

_SAMPLES = (
    "Cannot query field 'nam' on type 'User'. Did you mean 'name'?",
    "Unknown type 'Usr'. Did you mean 'User'?",
    "Unknown argument 'x' on field 'Query.a'. Did you mean 'y'?",
    "Unknown argument 'x' on directive '@d'. Did you mean 'y'?",
    "Variable '$i' got invalid value {'nam': 1}; Field 'nam' is not defined by "
    "type 'In'. Did you mean 'name'?",
    "Value 'A' does not exist in 'E' enum. Did you mean the enum value 'B'?",
    "Enum 'E' cannot represent non-enum value: \"A\". Did you mean the enum value 'B'?",
    "Variable '$s' got invalid value 42; Enum 'E' cannot represent non-string "
    "value: 42. Did you mean the enum value 'B'?",
    "Variable '$x' got invalid value 1; Did you mean to call this?",
    "Did you mean to call this from a staff account?",
    "Field 'a' of type 'T' must have a selection of subfields. Did you mean 'a { ... }'?",
    "Unknown type 'Usr'. Did you mean 'User'?\n",
    "Unknown type 'Usr'.\n  Did you mean 'User'?",
    "Unknown type 'Usr'.\nDid you mean 'User'?\n\n",
    "Unknown type 'Usr'. Did you mean 'User'",
    "Enum 'E' cannot represent non-string value: x Did you mean a? Did you mean b?",
    "Enum 'E' cannot represent non-string value:  Did you mean b?",
    "Enum 'E' cannot represent non-string value: x\ny Did you mean b?",
    "Variable '$a' got invalid value 1; 2; Unknown type 'U'. Did you mean 'V'?",
    "Variable '$a' got invalid value 1\n; Unknown type 'U'. Did you mean 'V'?",
    "",
    "?",
)


class SuggestionStripTests(SimpleTestCase):
    """Behavior and speed of the suggestion strip.

    Equivalence is checked against the previous regex; speed on hostile input.
    """

    def test_samples_match_the_reference_regex(self) -> None:
        """Every representative message strips exactly as the old regex did.

        Covers each rule, the coercion wrapper, trailing newlines, odd
        whitespace and several suggestions in one message.
        """
        from django_graphex.security import _strip_suggestion

        for message in _SAMPLES:
            with self.subTest(message=message):
                self.assertEqual(
                    _strip_suggestion(message), _REFERENCE.sub(r"\1", message)
                )

    def test_random_messages_match_the_reference_regex(self) -> None:
        """Randomly assembled messages strip exactly as the old regex did.

        Fragments are drawn from the rule prefixes, the wrapper and noise that
        includes newlines, quotes, semicolons and Unicode spaces.
        """
        from django_graphex.security import _strip_suggestion

        pieces = (
            "Variable '$v' got invalid value ",
            "; ",
            "Unknown type 'U'.",
            "Cannot query field 'f' on type 'T'.",
            "Enum 'E' cannot represent non-string value: ",
            "Value 'A' does not exist in 'E' enum.",
            " Did you mean ",
            "Did you mean ",
            "'x'?",
            "?",
            "\n",
            " ",
            " ",
            "x",
            "'",
        )
        rng = random.Random(1234)
        for _ in range(4000):
            message = "".join(rng.choice(pieces) for _ in range(rng.randint(1, 12)))
            with self.subTest(message=message):
                self.assertEqual(
                    _strip_suggestion(message), _REFERENCE.sub(r"\1", message)
                )

    def test_adversarial_message_is_linear(self) -> None:
        """A 224 KB hostile message finishes quickly through the public formatter.

        The old regex took more than two seconds here.
        """
        message = (
            "Enum 'E' cannot represent non-string value: " + " Did you mean " * 16000
        )
        with override_settings(
            DJANGO_GRAPHEX={"ALLOW_INTROSPECTION": False},
        ):
            started = time.perf_counter()
            formatted = format_graphql_error(
                GraphQLError(message), [DisableIntrospectionMiddleware()]
            )
            elapsed = time.perf_counter() - started
        self.assertEqual(formatted["message"], message)
        self.assertLess(elapsed, 0.5)

    def test_adversarial_matching_message_is_linear(self) -> None:
        """Hostile messages that do end in a suggestion are also linear and stripped.

        Wrapper separators, repeated rule heads and repeated suggestions all
        appear, and the message ends the way a real suggestion does.
        """
        message = (
            "Variable '$a' got invalid value "
            + "; Enum 'E' cannot represent non-string value: x" * 4000
            + " Did you mean " * 4000
            + "?"
        )
        with override_settings(DJANGO_GRAPHEX={"ALLOW_INTROSPECTION": False}):
            started = time.perf_counter()
            formatted = format_graphql_error(
                GraphQLError(message), [DisableIntrospectionMiddleware()]
            )
            elapsed = time.perf_counter() - started
        self.assertNotIn("Did you mean", formatted["message"])
        self.assertLess(elapsed, 0.5)
