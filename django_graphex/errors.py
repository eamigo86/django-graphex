"""GraphQL error payload types."""

from __future__ import annotations

import graphene

__all__ = ("ErrorType",)


class ErrorType(graphene.ObjectType):
    """A field-scoped validation error: ``{field, messages}``.

    Mirrors ``graphene_django.types.ErrorType`` (the only part of it we use), so
    mutation error payloads are unchanged.
    """

    field = graphene.String(required=True)
    messages = graphene.List(graphene.NonNull(graphene.String), required=True)
