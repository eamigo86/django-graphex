import uuid

from django.test import TestCase

from tests import factories, queries
from tests.client import Client


class ParentTest:
    expected_status_code = 200
    expected_return_payload = {}

    @property
    def query(self):
        raise NotImplementedError()

    def setUp(self):
        self.user = factories.UserFactory()
        self.client = Client()
        self.response = self.client.query(self.query)
        self.data = self.response.json()

    def test_should_return_expected_status_code(self):
        self.assertEqual(self.response.status_code, self.expected_status_code)

    def test_should_return_expected_payload(self):
        self.assertEqual(
            self.response.json(), self.expected_return_payload, self.response.content
        )


class DjangoListObjectFieldTest(ParentTest, TestCase):
    query = queries.ALL_USERS

    @property
    def expected_return_payload(self):
        return {"data": {"allUsers": {"results": [{"id": str(self.user.id)}]}}}

    def test_field(self):
        self.assertEqual(
            self.data["data"]["allUsers"]["results"][0]["id"], str(self.user.id)
        )


class DjangoFilterPaginateListFieldTest(ParentTest, TestCase):
    query = queries.ALL_USERS1

    @property
    def expected_return_payload(self):
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
    query = queries.ALL_USERS2

    @property
    def expected_return_payload(self):
        return {"data": {"allUsers2": [{"username": self.user.username}]}}


class DjangoListObjectFieldWithFilterSetTest(ParentTest, TestCase):
    @property
    def expected_return_payload(self):
        return {"data": {"allUsers3": {"results": [{"username": self.user.username}]}}}

    @property
    def query(self):
        return queries.ALL_USERS3_WITH_FILTER % {
            "filter": "id: { exact: %s }" % self.user.id,
            "fields": "username",
        }

    def test_filter_charfield_icontains(self):
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

    def test_filter_charfield_iexact(self):
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
    @property
    def expected_return_payload(self):
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
    def query(self):
        return queries.USERS % {
            "filter": 'firstName: {{ icontains: "{}" }}'.format(
                self.user.first_name[:5]
            ),
            "pagination": "limit: 1",
            "fields": "id, username, email",
        }

    def test_filter_single_object(self):
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
    query = queries.ALL_USERS4

    def setUp(self):
        self.staff_user = factories.UserFactory(
            username=uuid.uuid4().hex, is_staff=True
        )
        super().setUp()

    @property
    def expected_return_payload(self):
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
