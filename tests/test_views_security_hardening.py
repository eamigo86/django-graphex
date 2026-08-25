# -*- coding: utf-8 -*-
"""Two view-layer leaks: cross-site simple POSTs, and schema suggestions.

The endpoint is "csrf_exempt" and "parse_body" accepts
"application/x-www-form-urlencoded" and "multipart/form-data". Both belong to
the CORS "simple request" set, so a cross-site form POST reaches the endpoint
with the victim's session cookie attached and no preflight to stop it. These
tests pin the header the endpoint now demands on that set, and pin that the
content types which already force a preflight are untouched.

The second half pins the "Did you mean" suggestion strip: graphql-core answers
a misspelled field with the correct spelling, so probing with invented names
rebuilds a schema the operator disabled introspection to hide. The suggestion
is only stripped when introspection is actually disabled -- with introspection
open the same names are public anyway and the hint is a development aid.
"""

from __future__ import annotations

import json
from types import SimpleNamespace
from typing import Any
from unittest.mock import patch

from django.contrib.auth.models import AnonymousUser
from django.core.cache import cache
from django.test import RequestFactory, TestCase, override_settings
from graphql import GraphQLArgument, GraphQLBoolean, GraphQLError, GraphQLString

from django_graphex.core import ObjectType, field
from django_graphex.schema import DjangoGraphQLSchema
from django_graphex.security import DisableIntrospectionMiddleware, format_graphql_error
from django_graphex.views import AuthenticatedGraphQLView, BaseGraphQLView, GraphQLView

_INTROSPECTION_MIDDLEWARE = (DisableIntrospectionMiddleware,)


class _Profile(ObjectType):
    """Nested type carrying one field for a misspelling to suggest.

    "email" is what graphql-core offers back when a client asks for "emial".
    """

    email = field(GraphQLString)


class _Query(ObjectType):
    """Root query exposing a scalar and a nested object.

    The scalar answers the transport tests; the nested object gives the
    suggestion tests a type name of their own to leak.
    """

    hello = field(GraphQLString)
    profile = field(_Profile)
    boom = field(GraphQLString)
    # "nickname" is the argument name KnownArgumentNamesRule offers back when a
    # client sends "nicknam" -- an argument name is schema-derived just like a
    # field or type name.
    greet = field(GraphQLString, args={"nickname": GraphQLArgument(GraphQLString)})

    def resolve_hello(root: Any, info: Any) -> str:
        """Resolve the "hello" field to a fixed greeting.

        Args:
            root: The resolver root value (unused).
            info: The GraphQL resolve info (unused).

        Returns:
            greeting: The fixed string "world".
        """
        return "world"

    def resolve_boom(root: Any, info: Any) -> str:
        """Raise an application error whose WHOLE text is a suggestion sentence.

        A resolver-raised error goes through the same formatter as a validation
        error, so a strip anchored only at the end would erase this message
        entirely.

        Args:
            root: The resolver root value (unused).
            info: The GraphQL resolve info (unused).

        Returns:
            Nothing -- the resolver always raises.

        Raises:
            GraphQLError: Always, carrying a message that is nothing but a
                "Did you mean ...?" sentence.
        """
        raise GraphQLError("Did you mean to call this from a staff account?")


class _Mutation(ObjectType):
    """Root mutation giving the cache-version tests a real mutation to send."""

    ping = field(GraphQLBoolean)

    def resolve_ping(root: Any, info: Any) -> bool:
        """Resolve the "ping" mutation to a constant.

        Args:
            root: The resolver root value (unused).
            info: The GraphQL resolve info (unused).

        Returns:
            ok: Always True.
        """
        return True


_schema = DjangoGraphQLSchema(query=_Query, mutation=_Mutation)

#: A form-urlencoded body carrying "{ hello }".
_FORM_QUERY = "query=%7B+hello+%7D"
#: A form-urlencoded body carrying "mutation { ping }".
_FORM_MUTATION = "query=mutation+%7B+ping+%7D"


class SimpleContentTypePostGuardTest(TestCase):
    """A POST a browser can send cross-site without a preflight needs a header.

    Covers the guarded set (form-encoded, multipart, text/plain, and a
    body-less POST carrying no content type at all), the content types that
    already force a preflight, GET, the GraphiQL render, and the opt-out.
    """

    def setUp(self) -> None:
        """Build a fresh request factory and view.

        Both are per-test so no request or view state leaks between cases.
        """
        self.factory = RequestFactory()
        self.view = BaseGraphQLView.as_view(schema=_schema)

    def test_form_urlencoded_post_without_the_header_is_forbidden(self) -> None:
        """Reject the cross-site form POST vector with a 403.

        This is the reproduced attack: a form on any origin posting a mutation
        with the victim's session cookie riding along.
        """
        request = self.factory.post(
            "/graphql/",
            "query=%7B+hello+%7D",
            content_type="application/x-www-form-urlencoded",
        )
        response = self.view(request)
        self.assertEqual(response.status_code, 403)
        payload = json.loads(response.content)
        self.assertIn("X-Requested-With", payload["errors"][0]["message"])
        self.assertNotIn("data", payload)

    def test_multipart_post_without_the_header_is_forbidden(self) -> None:
        """Reject a multipart POST that omits the header.

        Multipart is equally simple, so it is equally forgeable.
        """
        request = self.factory.post("/graphql/", data={"query": "{ hello }"})
        response = self.view(request)
        self.assertEqual(response.status_code, 403)

    def test_text_plain_post_without_the_header_is_forbidden(self) -> None:
        """Reject a text/plain POST that omits the header.

        The body parses to nothing, but the query rides the query string and
        would execute anyway.
        """
        request = self.factory.post(
            "/graphql/?query=%7B+hello+%7D", "ignored body", content_type="text/plain"
        )
        # RequestFactory only sets CONTENT_TYPE when the body is truthy, so an
        # empty body would silently make this a duplicate of the body-less test
        # and leave "text/plain" untested.
        self.assertEqual(request.META.get("CONTENT_TYPE"), "text/plain")
        response = self.view(request)
        self.assertEqual(response.status_code, 403)

    def test_body_less_post_without_a_content_type_is_forbidden(self) -> None:
        """Reject a POST that carries no content type at all.

        A body-less cross-site fetch() sends no Content-Type and needs no
        preflight, so the query string alone is enough to execute.
        """
        # "generic" with an empty body sets no CONTENT_TYPE at all, which is
        # exactly what a body-less cross-site fetch() POST looks like.
        request = self.factory.generic("POST", "/graphql/?query=%7B+hello+%7D", "")
        response = self.view(request)
        self.assertEqual(response.status_code, 403)

    def test_the_rejection_does_not_reveal_whether_the_query_was_valid(self) -> None:
        """Refuse a nonsense query and a valid one identically.

        A differing body would turn the guard into a schema oracle.
        """
        valid = self.factory.post(
            "/graphql/",
            "query=%7B+hello+%7D",
            content_type="application/x-www-form-urlencoded",
        )
        nonsense = self.factory.post(
            "/graphql/",
            "query=%7B+nosuchfield+%7D",
            content_type="application/x-www-form-urlencoded",
        )
        self.assertEqual(
            json.loads(self.view(valid).content),
            json.loads(self.view(nonsense).content),
        )

    def test_multipart_post_with_the_header_still_works(self) -> None:
        """Execute a multipart POST that sends the header.

        This is the whole reason the guard is a header check and not a blanket
        rejection: the upload path stays usable.
        """
        request = self.factory.post(
            "/graphql/",
            data={"query": "{ hello }"},
            HTTP_X_REQUESTED_WITH="XMLHttpRequest",
        )
        response = self.view(request)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(json.loads(response.content)["data"]["hello"], "world")

    def test_form_urlencoded_post_with_the_header_still_works(self) -> None:
        """Execute a form-encoded POST that sends the header.

        The one caller the guard disrupts only has to add a single header.
        """
        request = self.factory.post(
            "/graphql/",
            "query=%7B+hello+%7D",
            content_type="application/x-www-form-urlencoded",
            HTTP_X_REQUESTED_WITH="XMLHttpRequest",
        )
        self.assertEqual(self.view(request).status_code, 200)

    def test_application_json_post_is_untouched(self) -> None:
        """Serve a JSON POST that sends no header.

        JSON is not CORS-simple, so it already forces a preflight and no JSON
        client has to change.
        """
        request = self.factory.post(
            "/graphql/", json.dumps({"query": "{ hello }"}), "application/json"
        )
        response = self.view(request)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(json.loads(response.content)["data"]["hello"], "world")

    def test_application_graphql_post_is_untouched(self) -> None:
        """Serve a raw application/graphql POST that sends no header.

        It is not on the CORS-simple list either, so it keeps working.
        """
        request = self.factory.post(
            "/graphql/", "{ hello }", content_type="application/graphql"
        )
        response = self.view(request)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(json.loads(response.content)["data"]["hello"], "world")

    def test_get_requests_are_untouched(self) -> None:
        """Serve a GET that sends no header.

        The guard is POST-only: a GET carries no request body to forge.
        """
        response = self.view(self.factory.get("/graphql/", {"query": "{ hello }"}))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(json.loads(response.content)["data"]["hello"], "world")

    def test_the_graphiql_page_still_renders(self) -> None:
        """Render the GraphiQL page with no header.

        It is served from a plain GET, so the guard must never reach it.
        """
        view = BaseGraphQLView.as_view(schema=_schema, graphiql=True)
        request = self.factory.get("/graphql/", HTTP_ACCEPT="text/html")
        response = view(request)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["Content-Type"], "text/html")

    @override_settings(DJANGO_GRAPHEX={"REQUIRE_CSRF_HEADER": False})
    def test_the_setting_turns_the_guard_off(self) -> None:
        """Serve a header-less form POST once the setting is off.

        A project whose client cannot add the header keeps the old behavior.
        """
        request = self.factory.post(
            "/graphql/",
            "query=%7B+hello+%7D",
            content_type="application/x-www-form-urlencoded",
        )
        self.assertEqual(self.view(request).status_code, 200)

    def test_the_enhanced_view_is_guarded_too(self) -> None:
        """Reject a header-less multipart POST on the enhanced view.

        The guard runs ahead of every view's own dispatch, so every view
        inherits it rather than only the one the report named.
        """
        view = GraphQLView.as_view(schema=_schema)
        request = self.factory.post("/graphql/", data={"query": "{ hello }"})
        self.assertEqual(view(request).status_code, 403)

    def test_the_batch_endpoint_is_guarded_too(self) -> None:
        """Reject a header-less form POST on a batch endpoint.

        The batch path takes its own route through the view, so it needs its
        own pin.
        """
        view = GraphQLView.as_view(schema=_schema, batch=True)
        request = self.factory.post(
            "/graphql/",
            _FORM_QUERY,
            content_type="application/x-www-form-urlencoded",
        )
        response = view(request)
        self.assertEqual(response.status_code, 403)
        payload = json.loads(response.content)
        self.assertIn("X-Requested-With", payload["errors"][0]["message"])

    def test_the_authenticated_view_refuses_before_its_own_gate(self) -> None:
        """Refuse a header-less form POST with the CSRF message, not the 403 gate.

        "AuthenticatedGraphQLView" runs "permission_classes" in its own
        dispatch. The guard has to be ahead of that too, or the ordering is
        merely accidental on the one view the report exercised.
        """
        view = AuthenticatedGraphQLView.as_view(schema=_schema)
        request = self.factory.post(
            "/graphql/",
            _FORM_QUERY,
            content_type="application/x-www-form-urlencoded",
        )
        request.user = AnonymousUser()
        response = view(request)
        self.assertEqual(response.status_code, 403)
        payload = json.loads(response.content)
        self.assertIn("X-Requested-With", payload["errors"][0]["message"])

    def test_a_padded_content_type_is_still_guarded(self) -> None:
        """Reject a form POST whose content type carries surrounding whitespace.

        "get_content_type" is the guard's only look at the content type, so a
        value it fails to normalize walks straight past the guarded set.
        """
        request = self.factory.generic(
            "POST",
            "/graphql/",
            _FORM_QUERY,
            content_type=" application/x-www-form-urlencoded ",
        )
        self.assertEqual(self.view(request).status_code, 403)

    def test_get_content_type_normalizes_surrounding_whitespace(self) -> None:
        """Return the bare, trimmed, lower-cased content type.

        The header is compared against a frozenset, so an untrimmed value is a
        silent miss rather than a visible error.
        """
        request = SimpleNamespace(
            META={"CONTENT_TYPE": "  Application/JSON ; charset=utf-8 "}
        )
        self.assertEqual(BaseGraphQLView.get_content_type(request), "application/json")


class SimplePostGuardAndTheResponseCacheTest(TestCase):
    """The guard has to run ahead of every response-cache interaction.

    "GraphQLView.dispatch" owns the whole cache interaction and only reaches
    the shared dispatch through "super_call", at several different points. A
    guard placed behind it is bypassed by a warm entry, gets its own refusal
    stored, and still bumps the namespace version on a rejected mutation.
    """

    def setUp(self) -> None:
        """Build a request factory and empty the response cache.

        Both are per-test so no cached body or version counter leaks between
        cases.
        """
        self.factory = RequestFactory()
        self.view = GraphQLView.as_view(schema=_schema)
        cache.clear()

    def _post(self, body: str, *, header: bool) -> Any:
        """Send a form-encoded POST, with or without the guard header.

        Args:
            body: The urlencoded request body.
            header: Whether to send the "X-Requested-With" header.

        Returns:
            response: The view's HTTP response.
        """
        extra = {"HTTP_X_REQUESTED_WITH": "XMLHttpRequest"} if header else {}
        request = self.factory.post(
            "/graphql/",
            body,
            content_type="application/x-www-form-urlencoded",
            **extra,
        )
        request.user = AnonymousUser()
        return self.view(request)

    @override_settings(
        DJANGO_GRAPHEX={"REQUIRE_CSRF_HEADER": True, "CACHE_ACTIVE": True}
    )
    def test_a_warm_cache_entry_never_answers_a_header_less_post(self) -> None:
        """Refuse the forged POST even when its slot is already warm.

        This is the bypass: the cached body is returned before the guard ever
        runs, so the forged cross-site POST gets a 200 and executes.
        """
        self.assertEqual(self._post(_FORM_QUERY, header=True).status_code, 200)

        forged = self._post(_FORM_QUERY, header=False)

        self.assertEqual(forged.status_code, 403)
        self.assertIn(
            "X-Requested-With", json.loads(forged.content)["errors"][0]["message"]
        )

    @override_settings(
        DJANGO_GRAPHEX={"REQUIRE_CSRF_HEADER": True, "CACHE_ACTIVE": True}
    )
    def test_the_refusal_is_never_stored_in_the_cache(self) -> None:
        """Serve the legitimate POST after a forged one hit the same slot.

        A cached 403 poisons that query's slot for the whole CACHE_TIMEOUT: one
        forged request would deny every well-behaved client after it.
        """
        self.assertEqual(self._post(_FORM_QUERY, header=False).status_code, 403)

        legit = self._post(_FORM_QUERY, header=True)

        self.assertEqual(legit.status_code, 200)
        self.assertEqual(json.loads(legit.content)["data"]["hello"], "world")

    @override_settings(
        DJANGO_GRAPHEX={"REQUIRE_CSRF_HEADER": True, "CACHE_ACTIVE": True}
    )
    def test_a_refused_mutation_never_bumps_the_cache_version(self) -> None:
        """Leave the namespace version alone when the mutation is refused.

        The bump flushes that identity's whole cache namespace, so a rejected
        request that still reaches it hands the attacker a free cache-flush.
        """
        with patch.object(GraphQLView, "_bump_cache_version") as bump:
            response = self._post(_FORM_MUTATION, header=False)

        self.assertEqual(response.status_code, 403)
        bump.assert_not_called()


class SuggestionLeakTest(TestCase):
    """The "Did you mean" hint is stripped only when introspection is off.

    A stripped error keeps its own message, its locations and its path -- only
    the trailing suggestion sentence goes.
    """

    def setUp(self) -> None:
        """Build a fresh request factory.

        Per-test so no request state leaks between cases.
        """
        self.factory = RequestFactory()

    def _errors(self, view: Any, query: str) -> list:
        """Run a JSON query through a view and return its formatted errors.

        Args:
            view: The view callable to send the request to.
            query: The GraphQL document to send.

        Returns:
            errors: The "errors" list of the JSON response body.
        """
        request = self.factory.post(
            "/graphql/", json.dumps({"query": query}), "application/json"
        )
        return json.loads(view(request).content)["errors"]

    @override_settings(
        DJANGO_GRAPHEX={
            "ALLOW_INTROSPECTION": False,
            "MIDDLEWARE": _INTROSPECTION_MIDDLEWARE,
        }
    )
    def test_the_suggestion_is_stripped_when_introspection_is_disabled(self) -> None:
        """Answer a misspelled field without naming the real one.

        This is the leak: the suggestion hands back a field name the operator
        disabled introspection to withhold.
        """
        view = BaseGraphQLView.as_view(schema=_schema)
        errors = self._errors(view, "{ profile { emial } }")
        self.assertNotIn("Did you mean", errors[0]["message"])
        self.assertNotIn("email", errors[0]["message"])

    @override_settings(
        DJANGO_GRAPHEX={
            "ALLOW_INTROSPECTION": False,
            "MIDDLEWARE": _INTROSPECTION_MIDDLEWARE,
        }
    )
    def test_the_rest_of_the_stripped_error_survives(self) -> None:
        """Keep everything but the suggestion sentence.

        The message, the locations and the path all have to survive, or a
        client that reports validation errors breaks.
        """
        view = BaseGraphQLView.as_view(schema=_schema)
        errors = self._errors(view, "{ profile { emial } }")
        self.assertEqual(
            errors[0]["message"], "Cannot query field 'emial' on type '_Profile'."
        )
        self.assertEqual(errors[0]["locations"], [{"line": 1, "column": 13}])

    @override_settings(
        DJANGO_GRAPHEX={
            "ALLOW_INTROSPECTION": False,
            "MIDDLEWARE": _INTROSPECTION_MIDDLEWARE,
        }
    )
    def test_an_application_error_ending_in_a_question_is_left_alone(self) -> None:
        """Keep a resolver-raised error whose text merely ends in a suggestion.

        A resolver error goes through the same formatter as a validation error.
        It names nothing schema-derived, so a strip keyed on the SHAPE of the
        sentence rather than on the rules that leak would mangle (here: erase)
        an application message the library never wrote.
        """
        view = BaseGraphQLView.as_view(schema=_schema)
        errors = self._errors(view, "{ boom }")
        self.assertEqual(
            errors[0]["message"], "Did you mean to call this from a staff account?"
        )

    @override_settings(
        DJANGO_GRAPHEX={
            "ALLOW_INTROSPECTION": False,
            "MIDDLEWARE": _INTROSPECTION_MIDDLEWARE,
        }
    )
    def test_an_unknown_argument_loses_its_suggestion(self) -> None:
        """Strip the suggestion from an unknown argument name.

        KnownArgumentNamesRule builds its hint from the field's real argument
        names, so it is the same oracle as an unknown field or type.
        """
        view = BaseGraphQLView.as_view(schema=_schema)
        errors = self._errors(view, '{ greet(nicknam: "x") }')
        self.assertEqual(
            errors[0]["message"],
            "Unknown argument 'nicknam' on field '_Query.greet'.",
        )

    @override_settings(
        DJANGO_GRAPHEX={
            "ALLOW_INTROSPECTION": False,
            "MIDDLEWARE": _INTROSPECTION_MIDDLEWARE,
        }
    )
    def test_an_unknown_type_name_loses_its_suggestion_too(self) -> None:
        """Strip the suggestion from an unknown type name.

        KnownTypeNamesRule leaks type names by exactly the same route as
        FieldsOnCorrectTypeRule leaks field names.
        """
        view = BaseGraphQLView.as_view(schema=_schema)
        errors = self._errors(
            view, "fragment f on _Profil { email } { profile { email } }"
        )
        self.assertIn("Unknown type '_Profil'.", errors[0]["message"])
        self.assertNotIn("Did you mean", errors[0]["message"])

    @override_settings(
        DJANGO_GRAPHEX={
            "ALLOW_INTROSPECTION": False,
            "MIDDLEWARE": _INTROSPECTION_MIDDLEWARE,
        }
    )
    def test_an_error_with_no_suggestion_is_left_alone(self) -> None:
        """Leave a message that carries no hint untouched.

        Most validation errors have no suggestion at all, so the strip has to
        be a no-op on them. "hello" is a String, so asking it for subfields
        produces a ScalarLeafsRule message with no trailing hint of any kind.
        """
        view = BaseGraphQLView.as_view(schema=_schema)
        errors = self._errors(view, "{ hello { anything } }")
        self.assertEqual(
            errors[0]["message"],
            "Field 'hello' must not have a selection since type 'String' has "
            "no subfields.",
        )

    @override_settings(
        DJANGO_GRAPHEX={
            "ALLOW_INTROSPECTION": False,
            "MIDDLEWARE": _INTROSPECTION_MIDDLEWARE,
        }
    )
    def test_the_scalar_leafs_hint_survives(self) -> None:
        """Keep ScalarLeafsRule's guidance, suggestion sentence and all.

        Its hint is built from the field name the CLIENT already typed, not
        from the schema, so stripping it costs a real usability aid and hides
        nothing. It is the counter-example a shape-keyed strip destroys.
        """
        view = BaseGraphQLView.as_view(schema=_schema)
        errors = self._errors(view, "{ profile }")
        self.assertEqual(
            errors[0]["message"],
            "Field 'profile' of type '_Profile' must have a selection of "
            "subfields. Did you mean 'profile { ... }'?",
        )

    @override_settings(
        DJANGO_GRAPHEX={
            "ALLOW_INTROSPECTION": True,
            "MIDDLEWARE": _INTROSPECTION_MIDDLEWARE,
        }
    )
    def test_the_suggestion_survives_when_introspection_is_allowed(self) -> None:
        """Keep the suggestion when introspection is allowed.

        The schema is public anyway, so the hint costs nothing and is a
        genuine development aid.
        """
        view = BaseGraphQLView.as_view(schema=_schema)
        errors = self._errors(view, "{ profile { emial } }")
        self.assertIn("Did you mean 'email'?", errors[0]["message"])

    @override_settings(DJANGO_GRAPHEX={"ALLOW_INTROSPECTION": False})
    def test_the_suggestion_survives_without_the_introspection_middleware(self) -> None:
        """Keep the suggestion when only the setting is off.

        ALLOW_INTROSPECTION defaults to False and is inert on its own: without
        the middleware nothing blocks introspection, so a stock project must
        not silently lose its hints.
        """
        view = BaseGraphQLView.as_view(schema=_schema)
        errors = self._errors(view, "{ profile { emial } }")
        self.assertIn("Did you mean 'email'?", errors[0]["message"])


@override_settings(
    DJANGO_GRAPHEX={
        "ALLOW_INTROSPECTION": False,
        "MIDDLEWARE": _INTROSPECTION_MIDDLEWARE,
    }
)
class SuggestionStripBoundaryTest(TestCase):
    """The strip only ever removes the sentence graphql-core appended LAST.

    "did_you_mean" is concatenated onto the end of the message and nothing is
    ever written after it, so the pattern is anchored at the end. Without that
    anchor the strip would reach into the middle of a message and delete text
    the library never produced.
    """

    def test_a_suggestion_that_is_not_the_last_sentence_is_left_alone(self) -> None:
        """Leave a message whose suggestion is followed by more prose.

        graphql-core never writes anything after "did_you_mean", so such a
        message came from application code. Dropping the end anchor would cut
        the sentence out of its middle and silently rewrite that message.
        """
        message = (
            "Cannot query field 'emial' on type '_Profile'. Did you mean "
            "'email'? Contact an administrator."
        )
        formatted = format_graphql_error(
            GraphQLError(message), _INTROSPECTION_MIDDLEWARE
        )
        self.assertEqual(formatted["message"], message)


class FormatErrorMiddlewareHookTest(TestCase):
    """The formatter must read the chain that actually ran the request.

    Execution asks "get_middleware(request)"; a subclass that overrides that
    hook (per-request chains are its whole point) would otherwise get a
    formatter whose introspection verdict disagrees with the chain that ran.
    """

    @override_settings(DJANGO_GRAPHEX={"ALLOW_INTROSPECTION": False, "MIDDLEWARE": ()})
    def test_format_error_follows_the_per_request_middleware_hook(self) -> None:
        """Strip the suggestion when only "get_middleware" installs the guard.

        "self.middleware" is empty here, so a formatter reading it concludes
        introspection is open and leaks the field name the request's real
        chain was hiding.
        """

        class _PerRequestView(BaseGraphQLView):
            """A view whose introspection guard is chosen per request."""

            def get_middleware(self, request: Any) -> Any:
                """Return the introspection guard for every request.

                Args:
                    request: The incoming HTTP request (unused).

                Returns:
                    middleware: The introspection-blocking chain.
                """
                return _INTROSPECTION_MIDDLEWARE

        view = _PerRequestView.as_view(schema=_schema)
        request = RequestFactory().post(
            "/graphql/",
            json.dumps({"query": "{ profile { emial } }"}),
            "application/json",
        )
        errors = json.loads(view(request).content)["errors"]
        self.assertEqual(
            errors[0]["message"], "Cannot query field 'emial' on type '_Profile'."
        )


class SuggestionStripReachesTheVariablePathTest(TestCase):
    """A suggestion still leaks when the bad value arrived through a variable.

    "coerce_variable_values" wraps a rule's own message in
    "Variable '$x' got invalid value ...; " before it reaches the formatter.
    Anchoring the rule prefixes at the start of the string made the strip a
    no-op on that whole path -- and it is the path on which the input-field and
    enum-member rules are actually reached, so the two prefixes the docs claim
    to cover leaked every suggestion they produced.
    """

    def test_an_input_field_suggestion_is_stripped_behind_the_wrapper(self) -> None:
        """Strip the suggestion from a wrapped input-field coercion message.

        This is the shape a client actually produces: an input object sent as a
        variable, with one key misspelled. The rule that fires here is reached
        almost exclusively through the wrapper.
        """
        from django_graphex.security import _SUGGESTION_RE

        message = (
            "Variable '$input' got invalid value {'nam': 'x'}; "
            "Field 'nam' is not defined by type 'UserInput'. Did you mean 'name'?"
        )
        self.assertEqual(
            _SUGGESTION_RE.sub(r"\1", message),
            "Variable '$input' got invalid value {'nam': 'x'}; "
            "Field 'nam' is not defined by type 'UserInput'.",
        )

    def test_an_enum_suggestion_is_stripped_behind_the_wrapper(self) -> None:
        """Strip the suggestion from a wrapped enum coercion message.

        The enum rules are the second pair the wrapper hides, and their
        suggestion names a real member of the enum.
        """
        from django_graphex.security import _SUGGESTION_RE

        message = (
            "Variable '$status' got invalid value 'DRAFTT'; "
            "Value 'DRAFTT' does not exist in 'Status' enum. Did you mean 'DRAFT'?"
        )
        self.assertNotIn("Did you mean", _SUGGESTION_RE.sub(r"\1", message))

    def test_the_wrapper_does_not_widen_the_strip(self) -> None:
        """Keep a wrapped message whose rule is not one that leaks a schema name.

        The wrapper is optional and additive: it must let the listed rules
        through, not turn the pattern into a match on any message that happens
        to carry one.
        """
        from django_graphex.security import _SUGGESTION_RE

        message = (
            "Variable '$x' got invalid value 1; "
            "Did you mean to call this from a staff account?"
        )
        self.assertEqual(_SUGGESTION_RE.sub(r"\1", message), message)


class TheGuardHeaderValueIsNeverInspectedTest(TestCase):
    """A present-but-empty guard header is still a header.

    An empty value is as non-safelisted as a filled one, so it forces the same
    CORS preflight and the attack it exists to stop is already impossible.
    Refusing it bought nothing and contradicted the contract the docs state.
    """

    def test_an_empty_header_value_is_accepted(self) -> None:
        """Assert the guard reads presence, not truthiness.

        A client that sets the header from an empty variable still sent it, and
        the browser still had to preflight to do so.
        """
        from django_graphex.views import csrf_header_missing

        request = RequestFactory().post("/graphql/", data={"query": "{ __typename }"})
        request.META["HTTP_X_REQUESTED_WITH"] = ""
        self.assertFalse(
            csrf_header_missing(request, "application/x-www-form-urlencoded")
        )

    def test_an_absent_header_is_still_refused(self) -> None:
        """Assert removing the header entirely still trips the guard.

        The counterpart to the test above: relaxing truthiness to presence must
        not relax the guard itself.
        """
        from django_graphex.views import csrf_header_missing

        request = RequestFactory().post("/graphql/", data={"query": "{ __typename }"})
        request.META.pop("HTTP_X_REQUESTED_WITH", None)
        self.assertTrue(
            csrf_header_missing(request, "application/x-www-form-urlencoded")
        )
