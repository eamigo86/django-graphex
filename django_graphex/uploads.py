"""Base64 file upload support for django-graphex.

Opt-in: import "Base64FileInput" (and optionally "decode_base64_file")
explicitly — nothing is imported by default.

Usage
-----

"Base64FileInput" is a native "InputType" (a Pydantic model). Use it as an
argument type on a mutation; the validated value that arrives in the resolver
exposes "filename" / "data" / "content_type" and a "to_uploaded_file()"
helper:

    from graphql import GraphQLArgument, GraphQLNonNull
    from django_graphex.core import Mutation, field
    from django_graphex.uploads import Base64FileInput, decode_base64_file

    class MyMutation(Mutation):
        class Arguments:
            # A native Mutation arg is a graphql-core "GraphQLArgument". The
            # compiled input type lives on "Base64FileInput._meta.graphql_input_type"
            # but is "None" until "compile_all_inputs()" runs (AppConfig.ready),
            # so reference it via a zero-arg "lambda" thunk that resolves at
            # "Field()" build time.
            avatar = lambda: GraphQLArgument(  # noqa: E731
                GraphQLNonNull(Base64FileInput._meta.graphql_input_type)
            )

        ok = field(GraphQLBoolean)

        @classmethod
        def mutate(cls, root, info, **kwargs):
            # Input-object args arrive as a plain dict (snake-case out_name keys);
            # rehydrate it into a Base64FileInput before calling to_uploaded_file().
            avatar = Base64FileInput(**kwargs["avatar"])
            uploaded = avatar.to_uploaded_file(max_size=2 * 1024 * 1024)
            profile.avatar.save(uploaded.name, uploaded)
            return cls(ok=True)

Settings
--------

"MAX_UPLOAD_SIZE" (int, bytes)
    Required when "Base64FileInput" is used. Raises "ImproperlyConfigured"
    if absent and no per-call "max_size" override is given.

"MAX_REQUEST_BODY_SIZE" (int, bytes, or None)
    Optional. When set, "BaseGraphQLView.dispatch" / "parse_body" rejects
    any request whose body length exceeds this limit with HTTP 413 — BEFORE
    JSON parsing. This is the primary memory-safety cap: the base64 payload
    is already in RAM once the JSON body is parsed, so a per-field decoded-
    size pre-check only saves the *decode* allocation. The body-size guard
    prevents the full body from ever being loaded above the threshold.

Memory model
------------

For batch requests both guards compose:

* "MAX_REQUEST_BODY_SIZE" bounds the total wire bytes of the entire batch.
* For each upload field in each batch operation, the per-field decoded-size
  pre-check ("len(b64_data) * 3 // 4" estimate vs effective cap) fires
  before the actual "base64.b64decode" call, bounding the decode allocation.

Peak memory ≈ body_size + MAX_UPLOAD_SIZE (one file decoded at a time because
batch operations execute sequentially in "views.py").

Content validation
------------------

Magic-byte / MIME-type validation is intentionally out of scope. Use Django's
"FileField" validators (e.g. "FileExtensionValidator") or a custom
validator on the model field — that is the correct layer.

Query cost
----------

Input payload size is not accounted for in query-cost analysis. The body-
size guard ("MAX_REQUEST_BODY_SIZE") is the canonical byte-level cap.

Cache
-----

Upload mutations bypass the response cache (they are "mutation" operations;
the cache layer already skips mutations). No special handling needed.

REST side-channel alternative
------------------------------

For gateway-constrained clients that cannot send large JSON bodies (e.g. an
API gateway with a 10 MB payload limit), the recommended alternative is a
REST side-channel: upload the file directly to a presigned URL (S3, GCS,
Azure Blob) or a separate "/upload/" endpoint, obtain a file key or URL,
and pass that reference as a plain string field in the GraphQL mutation.
This avoids base64 overhead entirely and scales naturally with file size.
"""

from __future__ import annotations

import base64
import binascii
from typing import Any, Optional

from django.core.exceptions import ImproperlyConfigured
from django.core.files.uploadedfile import SimpleUploadedFile
from graphql import GraphQLError

from .core.base import InputType
from .settings import graphql_api_settings

__all__ = ["Base64FileInput", "decode_base64_file", "merge_uploaded_files"]

_DEFAULT_CONTENT_TYPE = "application/octet-stream"


def _estimate_decoded_size(b64_data: str) -> int:
    """Estimate the decoded byte length of a base64 string without decoding it.

    Formula: len(stripped) * 3 // 4 (strips whitespace first to be robust
    against line-wrapped base64). The result may be 1–2 bytes over the true
    decoded length due to padding characters, which is intentionally
    conservative (safe to reject at the boundary).

    Args:
        b64_data: The raw base64 string (may contain whitespace/newlines).
            Coerced to str so non-str callers also work.

    Returns:
        Estimated decoded byte count.
    """
    b64_str = str(b64_data) if not isinstance(b64_data, str) else b64_data
    stripped = b64_str.replace(" ", "").replace("\n", "").replace("\r", "")
    return len(stripped) * 3 // 4


def _effective_max_size(max_size: int | None) -> int | None:
    """Return the effective upload size cap.

    Priority: explicit max_size argument > MAX_UPLOAD_SIZE setting.

    Args:
        max_size: The per-call override (bytes), or None to use the global
            setting.

    Returns:
        The effective cap in bytes, or None if no cap applies.

    Raises:
        ImproperlyConfigured: When max_size is None **and**
            MAX_UPLOAD_SIZE has not been configured. This prevents silent
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
    """Decode a base64 file payload dict into a Django "SimpleUploadedFile".

    This is the core decode function used internally by
    "Base64FileInput.to_uploaded_file()". You can call it directly when you
    hold the raw dict (e.g. from a custom resolver).

    The function performs a **decoded-size pre-check** *before* the actual
    "base64.b64decode" call: it estimates "len(b64_data) * 3 // 4" and
    rejects payloads that would exceed the effective cap without ever
    allocating the decoded bytes. This saves the decode-allocation overhead
    for oversized uploads.

    Args:
        value: A dict with keys:
            * "filename" (str, required) — the original filename.
            * "data" (str, required) — the base64-encoded file content.
            * "content_type" (str, optional) — MIME type; defaults to
              "application/octet-stream".
        max_size: Per-call size cap in bytes. Overrides the global
            "MAX_UPLOAD_SIZE" setting. Pass "None" to use the global
            setting (which must be set, or "ImproperlyConfigured" is raised).

    Returns:
        A "SimpleUploadedFile" with "name", "content_type", and the
        decoded binary content ready for "FileField.save()".

    Raises:
        ImproperlyConfigured: When no cap is configured (neither "max_size"
            nor "MAX_UPLOAD_SIZE").
        GraphQLError: When the estimated decoded size exceeds the effective cap,
            or when the "data" field is not valid base64.
    """
    # Coerce to plain str — callers may pass non-str values (e.g. a Pydantic
    # field that has not been narrowed, or a raw resolver dict) rather than str.
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
    except UnicodeDecodeError as exc:  # pragma: no cover
        # base64.b64decode(str, validate=True) cannot raise UnicodeDecodeError:
        # it only raises binascii.Error or ValueError for str inputs. This guard
        # is retained as a defensive catch for future callers passing bytes.
        raise GraphQLError(
            f"Upload '{filename}' contains non-UTF-8 data in the base64 string: {exc}."
        ) from exc

    return SimpleUploadedFile(
        name=filename,
        content=content,
        content_type=content_type,
    )


class Base64FileInput(InputType):
    """GraphQL input type for base64-encoded file uploads (opt-in).

    A native "InputType" (a Pydantic model). Use it as an argument type on a
    "django_graphex.Mutation"; the VALIDATED value that arrives in the resolver
    is an instance of this class. Call ".to_uploaded_file()" on it to obtain a
    Django "SimpleUploadedFile" suitable for assigning to a model "FileField".

    For example:

        from graphql import GraphQLArgument, GraphQLNonNull
        from django_graphex.core import Mutation, field
        from django_graphex.uploads import Base64FileInput

        class UploadAvatarMutation(Mutation):
            class Arguments:
                # A native Mutation argument is a graphql-core "GraphQLArgument".
                # "Base64FileInput" is a Pydantic "InputType" whose compiled
                # "GraphQLInputObjectType" lives on "_meta.graphql_input_type"
                # — but that attribute is "None" until "compile_all_inputs()"
                # runs (the package AppConfig.ready() does this at startup when
                # "django_graphex" is in "INSTALLED_APPS"). Reference it via a
                # zero-arg "lambda" thunk so it resolves at "Field()" build
                # time, NOT at class-definition time.
                avatar = lambda: GraphQLArgument(  # noqa: E731
                    GraphQLNonNull(Base64FileInput._meta.graphql_input_type)
                )

            ok = field(GraphQLBoolean)

            @classmethod
            def mutate(cls, root, info, **kwargs):
                # Input-object arguments arrive as a plain "dict" (snake-case
                # "out_name" keys), so rehydrate it into a "Base64FileInput"
                # instance before calling ".to_uploaded_file()".
                avatar = Base64FileInput(**kwargs["avatar"])
                file = avatar.to_uploaded_file(max_size=2 * 1024 * 1024)
                # file is a SimpleUploadedFile — assign to a FileField:
                profile.avatar.save(file.name, file, save=True)
                return cls(ok=True)

    Fields
    ------

    * "filename" (String!, required) — the original filename (used as the
      storage key; Django's "FileField" may rename it).
    * "data" (String!, required) — the file content, base64-encoded.
    * "content_type" / wire "contentType" (String) — MIME type; defaults to
      "application/octet-stream" when absent.

    Size limits
    -----------

    "to_uploaded_file()" accepts an optional "max_size" (bytes) that
    overrides the global "MAX_UPLOAD_SIZE" setting for this specific field.
    Use this to enforce tighter limits on avatar fields while allowing larger
    documents elsewhere:

        avatar.to_uploaded_file(max_size=512 * 1024)    # 512 KB avatar
        document.to_uploaded_file(max_size=10 * 1024 * 1024)  # 10 MB document

    Memory-safety architecture
    --------------------------

    The primary memory guard is "MAX_REQUEST_BODY_SIZE" configured on the
    view — it rejects the HTTP request before the JSON body is parsed, so the
    entire base64 string never enters RAM. The per-field decoded-size pre-check
    (this class) is a secondary guard that saves the decode allocation for
    payloads that somehow slip past the body-size guard (e.g. when
    "MAX_REQUEST_BODY_SIZE" is unset).

    Implementation note
    -------------------

    Because this is a Pydantic "InputType", the value delivered to a native
    resolver is a validated instance of this class — "to_uploaded_file" is a
    plain method on that instance and reads the validated "filename" / "data"
    / "content_type" attributes directly. The camelCase "contentType" wire key
    is mapped to the snake "content_type" attribute by the input compiler's
    "alias_generator" (no "Meta.container" override needed).
    """

    filename: str
    data: str
    content_type: Optional[str] = None

    def to_uploaded_file(self, *, max_size: int | None = None) -> SimpleUploadedFile:
        """Decode this validated upload input into a Django "SimpleUploadedFile".

        Call this in your mutation resolver on the validated value:

            @staticmethod
            def mutate(root, info, avatar):
                file = avatar.to_uploaded_file(max_size=2 * 1024 * 1024)
                profile.avatar.save(file.name, file, save=True)

        Reads the validated Pydantic attributes ("self.filename" / "self.data"
        / "self.content_type") rather than a graphene input container.

        Args:
            max_size: Per-field size cap in bytes. Overrides the global
                "MAX_UPLOAD_SIZE" setting. "None" falls back to the global.

        Returns:
            A "SimpleUploadedFile" ready for "FileField.save()".

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


def _accepted_part_names(input_type: Any) -> dict[str, str]:
    """Map every part name a compiled input accepts to its model attribute.

    Both spellings of a field are accepted: the camelCase name it is published
    under -- the only one a client can read off the SDL -- and the snake_case
    "out_name" the model attribute carries. They are read off the SAME compiled
    field, so the pair cannot drift apart, and the merged value is always keyed
    under the "out_name" because that is what the validated payload uses.

    Args:
        input_type: The compiled "GraphQLInputObjectType", possibly wrapped in
            "GraphQLNonNull".

    Returns:
        Each accepted part name mapped to the payload key it merges under.
    """
    from graphql import get_named_type

    named = get_named_type(input_type)
    fields = getattr(named, "fields", None) or {}
    accepted: dict[str, str] = {}
    for name, field in fields.items():
        out_name = getattr(field, "out_name", None) or name
        accepted[name] = out_name
        accepted[out_name] = out_name
    return accepted


def merge_uploaded_files(data: dict[str, Any], info: Any, input_type: Any) -> None:
    """Fold a multipart request's files into a mutation payload, in place.

    Only a part named after a field the input actually EXPOSES is merged. The
    filter is the point of this helper: a file column a type projects away with
    "Meta.exclude_fields" (or leaves out of "Meta.only_fields") has no input
    field, and a raw merge wrote it to the row anyway -- the payload reached the
    ORM without ever passing the wire surface that was supposed to bound it. An
    unrecognised part is ignored rather than rejected, because projecting a
    column away means the server does not accept it, not that the request is
    malformed.

    The part may carry either spelling of the field: the camelCase alias it is
    published under or the model's snake_case attribute. Whichever arrives, the
    value is merged under the snake_case key the validated payload uses.

    Args:
        data: The mutation input payload, mutated in place.
        info: GraphQL resolve info for the current request.
        input_type: The compiled input object the payload was validated against.
    """
    if "multipart/form-data" not in info.context.META.get("CONTENT_TYPE", ""):
        return
    files = getattr(info.context, "FILES", None)
    if not files:
        return
    accepted = _accepted_part_names(input_type)
    # A request naming ONE field under BOTH spellings contradicts itself, and
    # only one file can land. Apply the published alias first and the model
    # attribute second, so the attribute always wins: which file survives is a
    # property of the request, not of the order the parts happen to arrive in.
    for pass_over_attname in (False, True):
        data.update(
            {
                accepted[name]: value
                for name, value in files.items()
                if name in accepted and (name == accepted[name]) is pass_over_attname
            }
        )
