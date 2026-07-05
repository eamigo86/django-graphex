"""A thin Django test client preconfigured for the "graphql" endpoint.

Kept small and dependency-free so any test module can import it without
pulling in the full fixture surface.
"""

from django.http import HttpResponse
from django.test import Client as BaseClient
from django.urls import reverse


class Client(BaseClient):
    """Test client that posts GraphQL query strings to the "graphql" URL.

    Resolves the "graphql" URL once at class-definition time and exposes a
    "query" helper so tests do not need to repeat the endpoint path.
    """

    url = reverse("graphql")

    def query(self, query: str) -> HttpResponse:
        """Send a GraphQL query string to the "graphql" endpoint as a GET request.

        Args:
            query: The raw GraphQL query document to send.

        Returns:
            The Django test client HTTP response for the request.
        """
        response = self.get(path=self.url, data={"query": query})
        return response
