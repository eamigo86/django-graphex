"""The two permission demos this playground ships, exercised over the wire.

Both run under the PLAYGROUND's own "config.settings", against the real
"blog.schema" and the real views wired in "config/urls.py":

1. Nested writes run the CHILD's own permissions (2.2.0).
   "CommentModelType.permission_classes" gates "commentCreate"; the very same
   gate denies a comment written through "postWithCommentsCreate", and the
   parent Post rolls back with it.

2. "PERMISSION_SCOPED_SCHEMA" prunes the schema per caller on
   "/graphql/secure/": a user who does not hold "blog.add_note" has no
   "noteCreate" field to select at all, while the public fields still resolve —
   and a user who may write posts but not comments loses the nested "comments"
   input, since it is stamped with the child's permission.

Run from this directory:

    cd examples/playground
    DJANGO_SETTINGS_MODULE=config.settings python -m pytest -q --no-migrations
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any

import pytest

if TYPE_CHECKING:
    from blog.models import Author
    from django.contrib.auth.models import AbstractBaseUser
    from django.test import Client


def _graphql(
    client: Client, query: str, url: str = "/graphql/", status: int = 200
) -> dict[str, Any]:
    """POST a GraphQL document and return the decoded response body.

    Args:
        client: The Django test client issuing the request.
        query: The GraphQL document to execute.
        url: The endpoint to post to; defaults to the public "/graphql/".
        status: The HTTP status the request is expected to return. A document
            that does not validate against the caller's schema is a 400, which
            is what a pruned field produces.

    Returns:
        body: The decoded JSON response body.
    """
    resp = client.post(
        url, data=json.dumps({"query": query}), content_type="application/json"
    )
    assert resp.status_code == status, resp.status_code
    return resp.json()


def _nested_create(author_pk: int) -> str:
    """Build the nested-write document: a Post carrying one inline Comment.

    Args:
        author_pk: The primary key of the Author the post belongs to.

    Returns:
        document: The "postWithCommentsCreate" mutation document.
    """
    return f"""
        mutation {{
          postWithCommentsCreate(newPost: {{
            title: "Nested write"
            author: {author_pk}
            comments: [{{ authorName: "Ada", text: "Great post!" }}]
          }}) {{ ok errors {{ field messages }} post {{ id }} }}
        }}
    """


def _denied(body: dict[str, Any]) -> bool:
    """Report whether a response body is the library's permission denial.

    Args:
        body: The decoded GraphQL response body.

    Returns:
        denied: True when the body carries a PERMISSION_DENIED error.
    """
    return any(
        (error.get("extensions") or {}).get("code") == "PERMISSION_DENIED"
        for error in body.get("errors") or []
    )


@pytest.mark.django_db
def test_anonymous_is_denied_the_comments_own_mutation(client: Client) -> None:
    """Assert an anonymous caller may not run "commentCreate".

    Args:
        client: The Django test client issuing the unauthenticated POST.
    """
    from blog.models import Author, Comment, Post

    post = Post.objects.create(title="Host", author=Author.objects.create(name="A"))
    body = _graphql(
        client,
        f"""
        mutation {{
          commentCreate(newComment: {{
            post: {post.pk} authorName: "Ada" text: "Great post!"
          }}) {{ ok }}
        }}
        """,
    )
    assert _denied(body), body
    assert Comment.objects.count() == 0


@pytest.mark.django_db
def test_anonymous_nested_write_is_denied_through_the_parent(
    client: Client, author: Author
) -> None:
    """Assert the same denial reaches the caller through the nested field.

    The comment is written through "postWithCommentsCreate", which carries no
    permission of its own — the child's gate is what denies it, and the parent
    Post rolls back rather than landing without its comments.

    Args:
        client: The Django test client issuing the unauthenticated POST.
        author: The Author the attempted post would belong to.
    """
    from blog.models import Comment, Post

    body = _graphql(client, _nested_create(author.pk))

    assert _denied(body), body
    assert Post.objects.count() == 0
    assert Comment.objects.count() == 0


@pytest.mark.django_db
def test_authenticated_nested_write_creates_the_post_and_its_comments(
    client: Client, author: Author, django_user_model: type[AbstractBaseUser]
) -> None:
    """Assert the documented nested write still works for a permitted caller.

    Args:
        client: The Django test client used to log in and issue the mutation.
        author: The Author the created post belongs to.
        django_user_model: The active user model, used to create the caller.
    """
    from blog.models import Comment

    django_user_model.objects.create_user(username="ada", password="pw12345678")
    assert client.login(username="ada", password="pw12345678")

    body = _graphql(client, _nested_create(author.pk))

    assert not body.get("errors"), body
    assert body["data"]["postWithCommentsCreate"]["ok"] is True
    assert Comment.objects.count() == 1


@pytest.mark.django_db
def test_scoped_schema_prunes_note_create_for_a_caller_without_the_perm(
    client: Client, django_user_model: type[AbstractBaseUser]
) -> None:
    """Assert "/graphql/secure/" serves a schema pruned to the caller's perms.

    The user is authenticated (the endpoint's own gate passes) but holds no
    model permission, so the note CRUD fields do not exist for them — the error
    is graphql-core's own "Cannot query field", indistinguishable from a typo.

    Args:
        client: The Django test client used to log in and issue the requests.
        django_user_model: The active user model, used to create the caller.
    """
    django_user_model.objects.create_user(username="bob", password="pw12345678")
    assert client.login(username="bob", password="pw12345678")

    body = _graphql(
        client,
        'mutation { noteCreate(newNote: { title: "x" }) { ok } }',
        url="/graphql/secure/",
        status=400,
    )
    messages = " ".join(error.get("message", "") for error in body.get("errors") or [])
    assert "Cannot query field 'noteCreate'" in messages, body

    public = _graphql(client, "{ serverTime }", url="/graphql/secure/")
    assert not public.get("errors"), public


@pytest.mark.django_db
def test_scoped_schema_prunes_the_nested_comments_input(
    client: Client, author: Author, django_user_model: type[AbstractBaseUser]
) -> None:
    """Assert the nested input field carries the CHILD's permission label.

    The caller is the README's "editor": every blog permission except the Note
    and Comment ones. "postWithCommentsCreate" therefore survives the pruning
    while its "comments" input field does not — the parent is no longer a way to
    reach a child the caller's own schema refuses them.

    Args:
        client: The Django test client used to log in and issue the mutation.
        author: The Author the attempted post would belong to.
        django_user_model: The active user model, used to create the caller.
    """
    from django.contrib.auth.models import Permission

    user = django_user_model.objects.create_user(
        username="editor", password="pw12345678"
    )
    user.user_permissions.set(
        Permission.objects.filter(content_type__app_label="blog").exclude(
            content_type__model__in=["note", "comment"]
        )
    )
    assert client.login(username="editor", password="pw12345678")

    body = _graphql(
        client, _nested_create(author.pk), url="/graphql/secure/", status=400
    )

    messages = " ".join(error.get("message", "") for error in body.get("errors") or [])
    assert "Field 'comments' is not defined" in messages, body
    assert "postWithCommentsCreate" not in messages, body

    # The child's own root field is pruned for them as well — front door and
    # back door go together, which is the point of the 2.2.0 stamp.
    child = _graphql(
        client,
        'mutation { commentCreate(newComment: { post: 1, authorName: "A", '
        'text: "t" }) { ok } }',
        url="/graphql/secure/",
        status=400,
    )
    assert "Cannot query field 'commentCreate'" in str(child), child


@pytest.mark.django_db
def test_the_readme_validation_sample_is_refused_and_a_blank_title_is_not(
    client: Client, django_user_model: type[AbstractBaseUser]
) -> None:
    """Pin both halves of the README's validation section.

    Validation is PYDANTIC, derived from the column, so "max_length" fails and
    Django's form-level "blank" does not. The README used to claim the opposite
    with "title: ''", which returns "ok: true" and creates the row. Both the
    refusal and the non-refusal are asserted here so the section cannot rot
    back.

    Args:
        client: The Django test client issuing the requests.
        django_user_model: The active user model, used to log a caller in.
    """
    user = django_user_model.objects.create_user(username="writer", password="x")
    client.force_login(user)

    too_long = "x" * 250
    refused = _graphql(
        client,
        f'mutation {{ noteCreate(newNote: {{ title: "{too_long}" }}) '
        "{ ok errors { field messages } } }",
    )["data"]["noteCreate"]
    assert refused["ok"] is False
    assert refused["errors"] == [
        {"field": "title", "messages": ["String should have at most 200 characters"]}
    ]

    # The half the README got wrong: "blank" is a form concern Django never
    # enforces on save(), so an empty title is accepted.
    accepted = _graphql(
        client,
        'mutation { noteCreate(newNote: { title: "" }) { ok errors { field messages } } }',
    )["data"]["noteCreate"]
    assert accepted["ok"] is True
    assert accepted["errors"] is None
