"""Regression tests for optimizer planning across merged root field nodes."""

from django.db import connection
from django.test import TestCase
from django.test.utils import CaptureQueriesContext
from graphql import graphql_sync

from .models import Author, Post, Tag
from .test_optimizer_phase_d import _promo_schema
from .test_query_optimization import schema


class MergedRootFieldNodesTest(TestCase):
    """A repeated root response key must share one complete query plan."""

    @classmethod
    def setUpTestData(cls) -> None:
        """Create five rows so per-row relation loads are observable."""
        author = Author.objects.create(name="Ada", bio="bio")
        tag = Tag.objects.create(label="shared")
        for index in range(5):
            post = Post.objects.create(
                title=f"Post {index}", body="body", author=author
            )
            post.tags.add(tag)

    def test_direct_and_fragment_root_fields_share_relation_and_column_plan(
        self,
    ) -> None:
        """The second root node supplies relations and columns absent from the first."""
        split_query = """
            {
              allPosts { results { title } }
              ...ExtraFields
            }
            fragment ExtraFields on Query {
              allPosts {
                results { body author { name } tags { results { label } } }
              }
            }
        """
        combined_query = """
            {
              allPosts {
                results {
                  title body author { name } tags { results { label } }
                }
              }
            }
        """

        with CaptureQueriesContext(connection) as split_queries:
            split = graphql_sync(schema.graphql_schema, split_query)
        with CaptureQueriesContext(connection) as combined_queries:
            combined = graphql_sync(schema.graphql_schema, combined_query)

        self.assertIsNone(split.errors)
        self.assertIsNone(combined.errors)
        self.assertEqual(split.data, combined.data)
        self.assertEqual(len(split.data["allPosts"]["results"]), 5)
        self.assertEqual(len(combined_queries), 2)
        self.assertEqual(len(split_queries), 2)

    def test_second_root_node_promotes_annotated_relation(self) -> None:
        """A later root fragment still supplies the related annotation plan."""
        root_type = _promo_schema.graphql_schema.query_type.name
        query = f"""
            {{
              allPosts {{ results {{ title }} }}
              ...ExtraFields
            }}
            fragment ExtraFields on {root_type} {{
              allPosts {{ results {{ author {{ name postCount }} }} }}
            }}
        """

        with CaptureQueriesContext(connection) as captured:
            result = graphql_sync(_promo_schema.graphql_schema, query)

        self.assertIsNone(result.errors)
        rows = result.data["allPosts"]["results"]
        self.assertEqual(len(rows), 5)
        self.assertEqual(rows[0]["author"], {"name": "Ada", "postCount": 5})
        self.assertEqual(len(captured), 2)
        self.assertTrue(
            any("_gqx_ann_post_count" in entry["sql"] for entry in captured)
        )
