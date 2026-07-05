"""End-to-end coverage of the list/filter/pagination query fields via a live client.

Shares the "ParentTest" mixin contract (status code + full payload
assertions) across the "allUsers" field family, the filtered/paginated
"DjangoModelType" query, and the custom-resolver "allUsers4" field.
"""

import uuid

from django.test import TestCase

from tests import factories, queries
from tests.client import Client


class ParentTest:
    """Shared setUp + baseline assertions for a single fixed GraphQL query.

    Subclasses provide "query" (a class attribute or property) and
    "expected_return_payload"; this mixin then asserts both the HTTP status
    code and the full response payload against them.
    """

    expected_status_code = 200
    expected_return_payload = {}

    @property
    def query(self) -> str:
        """Get the GraphQL query string to execute for this test class.

        Returns:
            query: The raw GraphQL query text.

        Raises:
            NotImplementedError: Always, unless a subclass overrides this
                property (or sets a "query" class attribute instead).
        """
        raise NotImplementedError()

    def setUp(self) -> None:
        """Create a user, run "self.query" against the test client, and cache the parsed response.

        Runs before every test in a subclass per unittest convention.
        """
        self.user = factories.UserFactory()
        self.client = Client()
        self.response = self.client.query(self.query)
        self.data = self.response.json()

    def test_should_return_expected_status_code(self) -> None:
        """The response status code must match "expected_status_code".

        If this breaks, the query under test would fail at the transport
        level before its payload could even be checked.
        """
        self.assertEqual(self.response.status_code, self.expected_status_code)

    def test_should_return_expected_payload(self) -> None:
        """The full JSON response body must match "expected_return_payload" exactly.

        If this breaks, the query field under test would return the wrong
        shape or values for its result set.
        """
        self.assertEqual(
            self.response.json(), self.expected_return_payload, self.response.content
        )


class DjangoListObjectFieldTest(ParentTest, TestCase):
    """ "allUsers" (a DjangoListObjectField) must return the created user in "results".

    Runs the standard "ParentTest" status/payload contract plus a
    field-specific id assertion.
    """

    query = queries.ALL_USERS

    @property
    def expected_return_payload(self) -> dict:
        """Get the expected payload: one user's id nested under "results".

        Returns:
            payload: The expected JSON response body.
        """
        return {"data": {"allUsers": {"results": [{"id": str(self.user.id)}]}}}

    def test_field(self) -> None:
        """The first result's "id" must equal the created user's id as a string.

        If this breaks, the list-object field could return results in the
        wrong order or serialize the id incorrectly.
        """
        self.assertEqual(
            self.data["data"]["allUsers"]["results"][0]["id"], str(self.user.id)
        )


class DjangoFilterPaginateListFieldTest(ParentTest, TestCase):
    """ "allUsers1" (a filter+paginate list field) must return the full user record.

    Runs only the standard "ParentTest" status/payload contract.
    """

    query = queries.ALL_USERS1

    @property
    def expected_return_payload(self) -> dict:
        """Get the expected payload: the created user's core profile fields.

        Returns:
            payload: The expected JSON response body.
        """
        return {
            "data": {
                "allUsers1": [
                    {
                        "id": str(self.user.id),
                        "username": self.user.username,
                        "firstName": self.user.first_name,
                        "lastName": self.user.last_name,
                        "email": self.user.email,
                    }
                ]
            }
        }


class DjangoFilterListFieldTest(ParentTest, TestCase):
    """ "allUsers2" (a plain filter list field) must return the created user's username.

    Runs only the standard "ParentTest" status/payload contract.
    """

    query = queries.ALL_USERS2

    @property
    def expected_return_payload(self) -> dict:
        """Get the expected payload: the created user's username only.

        Returns:
            payload: The expected JSON response body.
        """
        return {"data": {"allUsers2": [{"username": self.user.username}]}}


class DjangoListObjectFieldWithFilterSetTest(ParentTest, TestCase):
    """ "allUsers3" (a list-object field bound to a FilterSet) must honor its runtime filter argument.

    Covers the base id-exact filter plus dedicated icontains/iexact
    lookup tests.
    """

    @property
    def expected_return_payload(self) -> dict:
        """Get the expected payload: the created user's username under "results".

        Returns:
            payload: The expected JSON response body.
        """
        return {"data": {"allUsers3": {"results": [{"username": self.user.username}]}}}

    @property
    def query(self) -> str:
        """Build the "allUsers3" query filtered by the created user's exact id.

        Returns:
            query: The formatted GraphQL query text.
        """
        return queries.ALL_USERS3_WITH_FILTER % {
            "filter": "id: { exact: %s }" % self.user.id,
            "fields": "username",
        }

    def test_filter_charfield_icontains(self) -> None:
        """The "icontains" lookup on "email" must match the created user by a partial local-part.

        If this breaks, the FilterSet-backed field could reject a valid
        substring filter or match the wrong records.
        """
        query = queries.ALL_USERS3_WITH_FILTER % {
            "filter": 'email: { icontains: "%s" }' % self.user.email.split("@")[0],
            "fields": "username",
        }
        response = self.client.query(query)
        self.assertEqual(response.status_code, 200, response.content)
        data = response.json()
        self.assertIn("allUsers3", data["data"])
        self.assertIn("results", data["data"]["allUsers3"])
        self.assertTrue(data["data"]["allUsers3"]["results"])
        self.assertEqual(
            data["data"]["allUsers3"]["results"][0]["username"], self.user.username
        )

    def test_filter_charfield_iexact(self) -> None:
        """The "iexact" lookup on "email" must match the created user by exact case-insensitive value.

        If this breaks, the FilterSet-backed field could reject a valid
        exact-match filter or apply case sensitivity incorrectly.
        """
        query = queries.ALL_USERS3_WITH_FILTER % {
            "filter": 'email: { iexact: "%s" }' % self.user.email,
            "fields": "username",
        }
        response = self.client.query(query)
        self.assertEqual(response.status_code, 200, response.content)
        data = response.json()
        self.assertIn("allUsers3", data["data"])
        self.assertIn("results", data["data"]["allUsers3"])
        self.assertTrue(data["data"]["allUsers3"]["results"])
        self.assertEqual(
            data["data"]["allUsers3"]["results"][0]["username"], self.user.username
        )


class DjangoModelTypeTest(ParentTest, TestCase):
    """ "users" (a DjangoModelType-backed paginated field) must honor filtering, pagination, and field selection.

    Also covers the separate "user2" single-object lookup field.
    """

    @property
    def expected_return_payload(self) -> dict:
        """Get the expected payload: one filtered user plus a totalCount of 1.

        Returns:
            payload: The expected JSON response body.
        """
        return {
            "data": {
                "users": {
                    "results": [
                        {
                            "id": str(self.user.id),
                            "username": self.user.username,
                            "email": self.user.email,
                        }
                    ],
                    "totalCount": 1,
                }
            }
        }

    @property
    def query(self) -> str:
        """Build the "users" query filtered by first name prefix, limited to 1 result.

        Returns:
            query: The formatted GraphQL query text.
        """
        return queries.USERS % {
            "filter": 'firstName: {{ icontains: "{}" }}'.format(
                self.user.first_name[:5]
            ),
            "pagination": "limit: 1",
            "fields": "id, username, email",
        }

    def test_filter_single_object(self) -> None:
        """The "user2" single-object field filtered by exact id must return the matching user's username.

        If this breaks, single-object lookup by id could return the wrong
        record or fail to resolve at all.
        """
        query = queries.USER % {
            "filter": "id: {}".format(self.user.id),
            "fields": "username",
        }
        response = self.client.query(query)
        self.assertEqual(response.status_code, 200, response.content)
        data = response.json()
        self.assertIn("user2", data["data"])
        self.assertTrue(data["data"]["user2"])
        self.assertEqual(data["data"]["user2"]["username"], self.user.username)


class DjangoCustomResolverTest(ParentTest, TestCase):
    """ "allUsers4" (backed by a custom resolver) must return only staff users.

    Runs only the standard "ParentTest" status/payload contract.
    """

    query = queries.ALL_USERS4

    def setUp(self) -> None:
        """Create an extra staff user (beyond the base "ParentTest" user) before running the query.

        Runs before every test in this class per unittest convention.
        """
        self.staff_user = factories.UserFactory(
            username=uuid.uuid4().hex, is_staff=True
        )
        super().setUp()

    @property
    def expected_return_payload(self) -> dict:
        """Get the expected payload: only the staff user, not the regular one from "setUp".

        Returns:
            payload: The expected JSON response body.
        """
        return {
            "data": {
                "allUsers4": [
                    {
                        "id": str(self.staff_user.id),
                        "username": self.staff_user.username,
                    }
                ]
            }
        }
