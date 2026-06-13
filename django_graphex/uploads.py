"""Base64 file upload support for django-graphex.

Opt-in: import ``Base64FileInput`` (and optionally ``decode_base64_file``)
explicitly — nothing is imported by default.

Usage
-----

::

    from django_graphex.uploads import Base64FileInput, decode_base64_file

    class MyMutation(graphene.Mutation):
        class Arguments:
            avatar = Base64FileInput(required=True)

        ok = graphene.Boolean()

        def mutate(self, info, avatar):
            uploaded = avatar.to_uploaded_file(max_size=2 * 1024 * 1024)
            profile.avatar.save(uploaded.name, uploaded)
            return MyMutation(ok=True)

Settings
--------

``MAX_UPLOAD_SIZE`` (int, bytes)
    Required when ``Base64FileInput`` is used. Raises ``ImproperlyConfigured``
    if absent and no per-call ``max_size`` override is given.

``MAX_REQUEST_BODY_SIZE`` (int, bytes, or None)
    Optional. When set, ``BaseGraphQLView.dispatch`` / ``parse_body`` rejects
    any request whose body length exceeds this limit with HTTP 413 — BEFORE
    JSON parsing. This is the primary memory-safety cap: the base64 payload
    is already in RAM once the JSON body is parsed, so a per-field decoded-
    size pre-check only saves the *decode* allocation. The body-size guard
    prevents the full body from ever being loaded above the threshold.

Memory model
------------

For batch requests both guards compose:

* ``MAX_REQUEST_BODY_SIZE`` bounds the total wire bytes of the entire batch.
* For each upload field in each batch operation, the per-field decoded-size
  pre-check (``len(b64_data) * 3 // 4`` estimate vs effective cap) fires
  before the actual ``base64.b64decode`` call, bounding the decode allocation.

Peak memory ≈ body_size + MAX_UPLOAD_SIZE (one file decoded at a time because
batch operations execute sequentially in ``views.py``).

Content validation
------------------

Magic-byte / MIME-type validation is intentionally out of scope. Use Django's
``FileField`` validators (e.g. ``FileExtensionValidator``) or a custom
validator on the model field — that is the correct layer.

Query cost
----------

Input payload size is not accounted for in query-cost analysis. The body-
size guard (``MAX_REQUEST_BODY_SIZE``) is the canonical byte-level cap.

Cache
-----

Upload mutations bypass the response cache (they are ``mutation`` operations;
the cache layer already skips mutations). No special handling needed.

REST side-channel alternative
------------------------------

For gateway-constrained clients that cannot send large JSON bodies (e.g. an
API gateway with a 10 MB payload limit), the recommended alternative is a
REST side-channel: upload the file directly to a presigned URL (S3, GCS,
Azure Blob) or a separate ``/upload/`` endpoint, obtain a file key or URL,
and pass that reference as a plain string field in the GraphQL mutation.
This avoids base64 overhead entirely and scales naturally with file size.
"""

from __future__ import annotations

import base64
import binascii
from typing import Any

import graphene
from django.core.exceptions import ImproperlyConfigured
from django.core.files.uploadedfile import SimpleUploadedFile
from graphql import GraphQLError

from .settings import graphql_api_settings

__all__ = ["Base64FileInput", "decode_base64_file"]

_DEFAULT_CONTENT_TYPE = "application/octet-stream"


def _estimate_decoded_size(b64_data: str) -> int:
    """Estimate the decoded byte length of a base64 string without decoding it.

    Formula: ``len(stripped) * 3 // 4`` (strips whitespace first to be robust
    against line-wrapped base64). The result may be 1–2 bytes over the true
    decoded length due to padding characters, which is intentionally
    conservative (safe to reject at the boundary).

    Args:
        b64_data: The raw base64 string (may contain whitespace/newlines).
            Coerced to ``str`` so graphene ``String`` scalars also work.

    Returns:
        Estimated decoded byte count.
    """
    b64_str = str(b64_data) if not isinstance(b64_data, str) else b64_data
    stripped = b64_str.replace(" ", "").replace("\n", "").replace("\r", "")
    return len(stripped) * 3 // 4


def _effective_max_size(max_size: int | None) -> int | None:
    """Return the effective upload size cap.

    Priority: explicit ``max_size`` argument > ``MAX_UPLOAD_SIZE`` setting.

    Args:
        max_size: The per-call override (bytes), or ``None`` to use the global
            setting.

    Returns:
        The effective cap in bytes, or ``None`` if no cap applies.

    Raises:
        ImproperlyConfigured: When ``max_size`` is ``None`` **and**
            ``MAX_UPLOAD_SIZE`` has not been configured. This prevents silent
            unbounded uploads.
    """
    if max_size is not None:
        return max_size

    global_cap = graphql_api_settings.MAX_UPLOAD_SIZE
    if global_cap is None:
        raise ImproperlyConfigured(
            "django-graphex: Base64FileInput is in use but MAX_UPLOAD_SIZE is not "
            "configured. Set DJANGO_GRAPHEX['MAX_UPLOAD_SIZE'] to a byte limit "
            "(e.g. 5 * 1024 * 1024 for 5 MB) or pass a per-field max_size override "
            "to decode_base64_file() / Base64FileInput.to_uploaded_file()."
        )
    return global_cap


def decode_base64_file(
    value: dict[str, Any],
    *,
    max_size: int | None = None,
) -> SimpleUploadedFile:
    """Decode a base64 file payload dict into a Django ``SimpleUploadedFile``.

    This is the core decode function used internally by
    ``Base64FileInput.to_uploaded_file()``. You can call it directly when you
    hold the raw dict (e.g. from a custom resolver).

    The function performs a **decoded-size pre-check** *before* the actual
    ``base64.b64decode`` call: it estimates ``len(b64_data) * 3 // 4`` and
    rejects payloads that would exceed the effective cap without ever
    allocating the decoded bytes. This saves the decode-allocation overhead
    for oversized uploads.

    Args:
        value: A dict with keys:
            * ``"filename"`` (str, required) — the original filename.
            * ``"data"`` (str, required) — the base64-encoded file content.
            * ``"content_type"`` (str, optional) — MIME type; defaults to
              ``"application/octet-stream"``.
        max_size: Per-call size cap in bytes. Overrides the global
            ``MAX_UPLOAD_SIZE`` setting. Pass ``None`` to use the global
            setting (which must be set, or ``ImproperlyConfigured`` is raised).

    Returns:
        A ``SimpleUploadedFile`` with ``name``, ``content_type``, and the
        decoded binary content ready for ``FileField.save()``.

    Raises:
        ImproperlyConfigured: When no cap is configured (neither ``max_size``
            nor ``MAX_UPLOAD_SIZE``).
        GraphQLError: When the estimated decoded size exceeds the effective cap,
            or when the ``data`` field is not valid base64.
    """
    # Coerce to plain str — graphene InputObjectType field values may arrive
    # as graphene scalar wrappers (e.g. graphene.String) rather than str.
    filename: str = str(value.get("filename", "") or "")
    b64_data: str = str(value.get("data", "") or "")
    _ct_raw = value.get("content_type", None)
    content_type: str = str(_ct_raw) if _ct_raw else _DEFAULT_CONTENT_TYPE

    # Resolve the effective cap (may raise ImproperlyConfigured).
    cap = _effective_max_size(max_size)

    # Pre-check: estimate decoded size before allocating the decoded bytes.
    if cap is not None:
        estimated = _estimate_decoded_size(b64_data)
        if estimated > cap:
            raise GraphQLError(
                f"Upload '{filename}' exceeds the maximum allowed size of {cap} bytes "
                f"(estimated decoded size: {estimated} bytes). "
                "Reduce the file size or increase the per-field/global cap."
            )

    # Decode — wrap any base64 / encoding errors as GraphQLError (not 500).
    try:
        content = base64.b64decode(b64_data, validate=True)
    except (binascii.Error, ValueError) as exc:
        raise GraphQLError(
            f"Upload '{filename}' contains invalid base64 data: {exc}. "
            "Ensure the file is base64-encoded without extra whitespace or "
            "incorrect padding."
        ) from exc
    except UnicodeDecodeError as exc:
        raise GraphQLError(
            f"Upload '{filename}' contains non-UTF-8 data in the base64 string: {exc}."
        ) from exc

    return SimpleUploadedFile(
        name=filename,
        content=content,
        content_type=content_type,
    )


class Base64FileInput(graphene.InputObjectType):
    """GraphQL input type for base64-encoded file uploads (opt-in).

    Use this as a field type in any graphene ``Mutation.Arguments`` class.
    Call ``.to_uploaded_file()`` in the resolver to obtain a Django
    ``SimpleUploadedFile`` suitable for assigning to a model ``FileField``.

    Example::

        from django_graphex.uploads import Base64FileInput

        class UploadAvatarMutation(graphene.Mutation):
            class Arguments:
                avatar = Base64FileInput(required=True)

            ok = graphene.Boolean()

            def mutate(self, info, avatar):
                file = avatar.to_uploaded_file(max_size=2 * 1024 * 1024)
                # file is a SimpleUploadedFile — assign to a FileField:
                profile.avatar.save(file.name, file, save=True)
                return UploadAvatarMutation(ok=True)

    Fields
    ------

    * ``filename`` (String!, required) — the original filename (used as the
      storage key; Django's ``FileField`` may rename it).
    * ``data`` (String!, required) — the file content, base64-encoded.
    * ``content_type`` (String) — MIME type; defaults to
      ``"application/octet-stream"`` when absent.

    Size limits
    -----------

    ``to_uploaded_file()`` accepts an optional ``max_size`` (bytes) that
    overrides the global ``MAX_UPLOAD_SIZE`` setting for this specific field.
    Use this to enforce tighter limits on avatar fields while allowing larger
    documents elsewhere::

        avatar.to_uploaded_file(max_size=512 * 1024)    # 512 KB avatar
        document.to_uploaded_file(max_size=10 * 1024 * 1024)  # 10 MB document

    Memory-safety architecture
    --------------------------

    The primary memory guard is ``MAX_REQUEST_BODY_SIZE`` configured on the
    view — it rejects the HTTP request before the JSON body is parsed, so the
    entire base64 string never enters RAM. The per-field decoded-size pre-check
    (this class) is a secondary guard that saves the decode allocation for
    payloads that somehow slip past the body-size guard (e.g. when
    ``MAX_REQUEST_BODY_SIZE`` is unset).

    Implementation note
    -------------------

    graphene auto-generates a container class that inherits from both
    ``InputObjectTypeContainer`` and ``Base64FileInput``. This means methods
    defined here (like ``to_uploaded_file``) are available on the value that
    arrives in mutation resolvers — no ``Meta.container`` override needed.
    ``self`` in that context is a dict-like container with attribute access for
    field values.
    """

    filename = graphene.String(required=True, description="Original filename.")
    data = graphene.String(required=True, description="Base64-encoded file content.")
    content_type = graphene.String(
        description="MIME type (default: application/octet-stream)."
    )

    def to_uploaded_file(self, *, max_size: int | None = None) -> SimpleUploadedFile:
        """Decode this upload input into a Django ``SimpleUploadedFile``.

        Call this in your mutation resolver:

        .. code-block:: python

            def mutate(self, info, avatar):
                file = avatar.to_uploaded_file(max_size=2 * 1024 * 1024)
                profile.avatar.save(file.name, file, save=True)

        Args:
            max_size: Per-field size cap in bytes. Overrides the global
                ``MAX_UPLOAD_SIZE`` setting. ``None`` falls back to the global.

        Returns:
            A ``SimpleUploadedFile`` ready for ``FileField.save()``.

        Raises:
            ImproperlyConfigured: When no size cap is configured.
            GraphQLError: When the payload exceeds the cap or is not valid base64.
        """
        return decode_base64_file(
            {
                "filename": self.filename,
                "data": self.data,
                "content_type": self.content_type,
            },
            max_size=max_size,
        )
