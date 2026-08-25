# -*- coding: utf-8 -*-
"""Relation-traversal permission bypass regression ("PERMISSION_SCOPED_SCHEMA").

v2.0.0 stamped "extensions[gdx_required_perms]" on GENERATED CRUD ROOT fields
only. Relation / nested-list output fields (a to-ONE FK object field, a to-MANY
"<Model>ListType" container) carried NO label, and the pruner treats an untagged
field as PUBLIC — so a caller whose direct "commentRetrieve" / "commentList"
roots were pruned away could still read the very same rows through
"postRetrieve { comments { results { secretText } } }".

Invariants asserted here:

- A caller holding ONLY the parent's view permission cannot select the relation
  field at all (a "Cannot query field" validation error, no existence leak).
- A caller holding BOTH view permissions still traverses the relation and reads
  the data — including when the target model has NO root field of its own (so
  its permission label reaches the pruner through the schema label-set).
- The to-ONE arm ("commentRetrieve { post { title } }") is gated the same way.
- The pruned SDL simply does not contain the relation field.
- With the flag OFF (the default) traversal is byte-identical to today, and a
  project that declares no "permission_classes" is unaffected.
"""

from __future__ import annotations

import json
from typing import Any, ClassVar

from django.contrib.auth.models import Permission, User
from django.contrib.contenttypes.models import ContentType
from django.db.models import Model
from django.http import HttpRequest
from django.test import RequestFactory, TestCase, override_settings
from graphql import print_schema

from django_graphex.core import ObjectType
from django_graphex.core import permission_signature_cache as psc
from django_graphex.core.registry_compiler import compile_all_outputs
from django_graphex.permissions import DjangoModelPermissions
from django_graphex.schema import DjangoGraphQLSchema
from django_graphex.types import DjangoModelType
from django_graphex.views import AuthenticatedGraphQLView

from .models import (
    PermRelArticle,
    PermRelAuthor,
    PermRelComment,
    PermRelPost,
)

_ON = {"PERMISSION_SCOPED_SCHEMA": True}
_OFF = {"PERMISSION_SCOPED_SCHEMA": False}

_SECRET = "TOP SECRET COMMENT"


# --------------------------------------------------------------------------- #
# Perm-gated pair: both types opt into the model-permission stack.
# --------------------------------------------------------------------------- #
class _CommentType(DjangoModelType):
    """Model type for "PermRelComment", gated by "DjangoModelPermissions"."""

    permission_classes: ClassVar[tuple[Any, ...]] = (DjangoModelPermissions,)

    class Meta:
        """Bind the type to the "PermRelComment" model."""

        model = PermRelComment


class _PermRelPostType(DjangoModelType):
    """Model type for "PermRelPost", gated by "DjangoModelPermissions"."""

    permission_classes: ClassVar[tuple[Any, ...]] = (DjangoModelPermissions,)

    class Meta:
        """Bind the type to the "PermRelPost" model."""

        model = PermRelPost


class _Query(ObjectType):
    """Root exposing BOTH models directly — the exact reproduction schema."""

    post_retrieve = _PermRelPostType.RetrieveField()
    post_list = _PermRelPostType.ListField()
    comment_retrieve = _CommentType.RetrieveField()
    comment_list = _CommentType.ListField()


class _ParentOnlyQuery(ObjectType):
    """Root exposing ONLY the parent — the child is reachable via the relation.

    The child model has no root field, so its permission label can only reach
    the pruner if the schema label-set accounts for relation labels too.
    """

    post_retrieve = _PermRelPostType.RetrieveField()


# --------------------------------------------------------------------------- #
# Ungated pair: no "permission_classes" anywhere (the "unaffected" baseline).
# --------------------------------------------------------------------------- #
class _PermRelAuthorType(DjangoModelType):
    """Model type for "PermRelAuthor" declaring NO "permission_classes"."""

    class Meta:
        """Bind the type to the "PermRelAuthor" model."""

        model = PermRelAuthor


class _ArticleType(DjangoModelType):
    """Model type for "PermRelArticle" declaring NO "permission_classes"."""

    class Meta:
        """Bind the type to the "PermRelArticle" model."""

        model = PermRelArticle


class _OpenQuery(ObjectType):
    """Root for the permission-class-free project baseline."""

    article_retrieve = _ArticleType.RetrieveField()
    author_retrieve = _PermRelAuthorType.RetrieveField()


compile_all_outputs()
_schema = DjangoGraphQLSchema(query=_Query)
_parent_only_schema = DjangoGraphQLSchema(query=_ParentOnlyQuery)
_open_schema = DjangoGraphQLSchema(query=_OpenQuery)


def _post(query: str, user: Any) -> HttpRequest:
    """Build a POST request against the GraphQL endpoint for view tests.

    Args:
        query: The raw GraphQL query text.
        user: The user attached to the request as "request.user".

    Returns:
        A POST request carrying the given query.
    """
    request = RequestFactory().post(
        "/graphql/", {"query": query}, content_type="application/json"
    )
    request.user = user
    return request


def _view_perm(model: type[Model]) -> Permission:
    """Return the Django "view" permission object for a model.

    Args:
        model: The Django model whose view permission is looked up.

    Returns:
        The "view_<model>" permission row for the model's content type.
    """
    return Permission.objects.get(
        content_type=ContentType.objects.get_for_model(model),
        codename=f"view_{model._meta.model_name}",
    )


class RelationPermissionBypassTest(TestCase):
    """Relation traversal must obey the TARGET model's view permission.

    Exercises the nested-list arm, the to-ONE arm, a target reachable only
    through a relation, the pruned SDL, and the flag-off baseline.
    """

    def setUp(self) -> None:
        """Seed the fixtures and clear the pruned-schema LRU.

        Clearing the process-wide LRU stops a pruned schema built for another
        test's user from leaking into this one.
        """
        psc._CACHE.clear()
        self.post = PermRelPost.objects.create(title="public title")
        PermRelComment.objects.create(post=self.post, secret_text=_SECRET)
        self.author = PermRelAuthor.objects.create(secret_name="hidden author")
        PermRelArticle.objects.create(title="an article", author=self.author)

    def _user(self, name: str, *models: type[Model]) -> User:
        """Create a user granted the view permission of each given model.

        Args:
            name: The username to create.
            *models: The models whose view permission the user receives.

        Returns:
            The persisted user.
        """
        user = User.objects.create_user(username=name, password="x")
        for model in models:
            user.user_permissions.add(_view_perm(model))
        return user

    # 1. THE BYPASS: view_permrelpost only -> the relation must be unselectable.
    @override_settings(DJANGO_GRAPHEX=_ON)
    def test_relation_traversal_blocked_without_target_perm(self) -> None:
        """Ship-broken contract: a caller lacking the child's view permission
        must not be able to reach the child's rows through the parent's
        nested-list relation field.
        """
        ana = self._user("ana", PermRelPost)
        query = (
            "{ postRetrieve(id: %d) { title comments "
            "{ totalCount results { secretText } } } }" % self.post.pk
        )
        response = AuthenticatedGraphQLView.as_view(schema=_schema)(_post(query, ana))
        self.assertNotIn(_SECRET, response.content.decode())
        body = json.loads(response.content)
        self.assertEqual(response.status_code, 400)
        self.assertIn("Cannot query field", body["errors"][0]["message"])

    # 2. The to-ONE arm of the same bypass (Comment.post -> PostGenericType).
    @override_settings(DJANGO_GRAPHEX=_ON)
    def test_to_one_relation_blocked_without_target_perm(self) -> None:
        """Ship-broken contract: a to-ONE relation field must be gated by its
        TARGET model's view permission, not left untagged/public.
        """
        bob = self._user("bob", PermRelComment)
        query = "{ commentList { results { secretText post { title } } } }"
        response = AuthenticatedGraphQLView.as_view(schema=_schema)(_post(query, bob))
        body = json.loads(response.content)
        self.assertEqual(response.status_code, 400)
        self.assertIn("Cannot query field", body["errors"][0]["message"])

    # 3. Holding BOTH perms still reads the relation end to end.
    @override_settings(DJANGO_GRAPHEX=_ON)
    def test_relation_traversal_allowed_with_both_perms(self) -> None:
        """Ship-broken contract: pruning must remove only what the caller lacks
        — a caller holding both view permissions still traverses the relation.
        """
        eve = self._user("eve", PermRelPost, PermRelComment)
        query = (
            "{ postRetrieve(id: %d) { title comments "
            "{ totalCount results { secretText } } } }" % self.post.pk
        )
        response = AuthenticatedGraphQLView.as_view(schema=_schema)(_post(query, eve))
        self.assertEqual(response.status_code, 200)
        comments = json.loads(response.content)["data"]["postRetrieve"]["comments"]
        self.assertEqual(comments["totalCount"], 1)
        self.assertEqual(comments["results"][0]["secretText"], _SECRET)

    # 4. The child has NO root field: its label must still reach the pruner, or
    #    a fully-privileged caller would lose the relation entirely.
    @override_settings(DJANGO_GRAPHEX=_ON)
    def test_relation_only_target_still_readable_with_perm(self) -> None:
        """Ship-broken contract: when the target model is reachable ONLY through
        a relation, its permission label must still be part of the schema
        label-set so a caller holding it keeps the relation.
        """
        eve = self._user("eve2", PermRelPost, PermRelComment)
        query = (
            "{ postRetrieve(id: %d) { comments { results { secretText } } } }"
            % self.post.pk
        )
        view = AuthenticatedGraphQLView.as_view(schema=_parent_only_schema)
        response = view(_post(query, eve))
        self.assertEqual(response.status_code, 200)
        results = json.loads(response.content)["data"]["postRetrieve"]["comments"]
        self.assertEqual(results["results"][0]["secretText"], _SECRET)

    # 5. ... and the same relation-only schema still hides the child from a
    #    caller who holds only the parent perm.
    @override_settings(DJANGO_GRAPHEX=_ON)
    def test_relation_only_target_hidden_without_perm(self) -> None:
        """Ship-broken contract: a relation-only target model must be pruned for
        a caller lacking its view permission, even with no root field to prune.
        """
        ana = self._user("ana2", PermRelPost)
        query = (
            "{ postRetrieve(id: %d) { comments { results { secretText } } } }"
            % self.post.pk
        )
        view = AuthenticatedGraphQLView.as_view(schema=_parent_only_schema)
        response = view(_post(query, ana))
        self.assertEqual(response.status_code, 400)
        self.assertIn(
            "Cannot query field", json.loads(response.content)["errors"][0]["message"]
        )

    # 6. The pruned SDL must not even mention the relation field.
    @override_settings(DJANGO_GRAPHEX=_ON)
    def test_pruned_sdl_omits_relation_field(self) -> None:
        """Ship-broken contract: the relation field must be absent from the
        pruned SDL served to a caller lacking the target's view permission.
        """
        ana = self._user("ana3", PermRelPost)
        pruned = psc.pruned_schema_for(ana, _schema.graphql_schema)
        sdl = print_schema(pruned)
        self.assertIn("PermRelPostGenericType", sdl)
        self.assertNotIn("comments", sdl)
        self.assertNotIn("PermRelCommentGenericType", sdl)
        self.assertNotIn("secretText", sdl)

    # 7. Flag OFF (the default) + no permission_classes: byte-identical to today.
    @override_settings(DJANGO_GRAPHEX=_OFF)
    def test_project_without_permission_classes_unaffected(self) -> None:
        """Ship-broken contract: a project declaring no "permission_classes" and
        leaving the flag at its default must traverse relations exactly as
        before, with no permission required.
        """
        nobody = User.objects.create_user(username="nobody", password="x")
        query = "{ authorRetrieve(id: %d) { articles { results { title } } } }" % (
            self.author.pk
        )
        response = AuthenticatedGraphQLView.as_view(schema=_open_schema)(
            _post(query, nobody)
        )
        self.assertEqual(response.status_code, 200)
        articles = json.loads(response.content)["data"]["authorRetrieve"]["articles"]
        self.assertEqual(articles["results"][0]["title"], "an article")
