"""Hardening of the public "registerUser" mutation.

Registration is a public, hand-written mutation, so it carries the checks a
generated write would not: Django's password validators run before the account
is created, and a duplicate username answers with the same generic refusal
instead of the raw database error (which leaked both the table and the fact
that the name exists).

Run from this directory:

    cd examples/playground
    DJANGO_SETTINGS_MODULE=config.settings python -m pytest -q --no-migrations
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any

import pytest

if TYPE_CHECKING:
    from django.contrib.auth.models import AbstractBaseUser
    from django.test import Client

pytestmark = pytest.mark.django_db

_REGISTER = (
    "mutation {{ registerUser(username: {username}, password: {password}) "
    "{{ ok error user {{ username }} }} }}"
)


def _register(client: Client, username: str, password: str) -> dict[str, Any]:
    """Run "registerUser" and return its payload.

    Args:
        client: The Django test client issuing the request.
        username: The requested username.
        password: The requested password.

    Returns:
        payload: The decoded "registerUser" payload.
    """
    query = _REGISTER.format(
        username=json.dumps(username), password=json.dumps(password)
    )
    response = client.post(
        "/graphql/", data=json.dumps({"query": query}), content_type="application/json"
    )
    body = response.json()
    assert not body.get("errors"), body
    return body["data"]["registerUser"]


def test_a_weak_password_is_refused_and_no_account_is_created(
    client: Client, django_user_model: type[AbstractBaseUser]
) -> None:
    """Assert the password validators run: "x" is refused and nothing is saved.

    Args:
        client: The Django test client issuing the request.
        django_user_model: The active user model, used to check nothing was created.
    """
    payload = _register(client, "weak-reader", "x")

    assert payload["ok"] is False
    assert payload["user"] is None
    assert "too short" in payload["error"]
    assert not django_user_model.objects.filter(username="weak-reader").exists()


def test_a_password_similar_to_the_username_is_refused(client: Client) -> None:
    """Assert the validators see the requested username, not only the password.

    Args:
        client: The Django test client issuing the request.
    """
    payload = _register(client, "reader-account", "reader-account")

    assert payload["ok"] is False
    assert "similar" in payload["error"] or "common" in payload["error"]


def test_a_duplicate_username_gets_a_generic_refusal(
    client: Client, django_user_model: type[AbstractBaseUser]
) -> None:
    """Assert a taken username returns a generic error, never the database text.

    Args:
        client: The Django test client issuing the requests.
        django_user_model: The active user model, used to seed the taken name.
    """
    django_user_model.objects.create_user("taken", password="correct-horse-battery")

    payload = _register(client, "taken", "another-correct-horse")

    assert payload["ok"] is False
    assert payload["user"] is None
    for leak in ("UNIQUE", "auth_user", "already", "exists", "taken"):
        assert leak not in payload["error"], payload
    assert payload["error"] == "Registration failed. Try different details."
    assert django_user_model.objects.filter(username="taken").count() == 1


def test_a_valid_registration_still_succeeds(
    client: Client, django_user_model: type[AbstractBaseUser]
) -> None:
    """Assert the hardening did not break the happy path.

    Args:
        client: The Django test client issuing the request.
        django_user_model: The active user model, used to check the stored hash.
    """
    payload = _register(client, "good-reader", "correct-horse-battery-staple")

    assert payload["ok"] is True
    assert payload["error"] is None
    assert payload["user"] == {"username": "good-reader"}
    user = django_user_model.objects.get(username="good-reader")
    assert user.check_password("correct-horse-battery-staple")
