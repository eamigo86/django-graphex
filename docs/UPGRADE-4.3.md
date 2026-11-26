# Upgrading to django-graphex 4.3

This guide covers the move from 4.2 to 4.3. If you are still on 4.1, follow
the [4.2 upgrade guide](UPGRADE-4.2.md) first.

```bash
uv add "django-graphex==4.3.0"
# or
pip install "django-graphex==4.3.0"
```

4.3 keeps the `graphql-core>=3.3.1,<3.4` requirement of 4.2.

## Upgrading to 4.3.0

4.3.0 is a minor release. Schemas and settings behave as in 4.2.0; these are
the differences you can notice.

- **Wire change on the SSE transport.** A query or mutation sent to the SSE
  subscription transport still answers HTTP 400 with the same message. The body
  is now `application/json` instead of `text/plain`:

  ```json
  {"errors": [{"message": "The SSE transport only serves subscription operations.", "extensions": {"code": "OPERATION_NOT_SUPPORTED"}}]}
  ```

  The WebSocket error frame for the same case now carries `extensions.code`
  `OPERATION_NOT_SUPPORTED`. Clients that read that 400 body as text, or that
  match on its content type, should read `errors[0].message` or the code. See
  [Subscriptions](usage/subscriptions.md#operation_not_supported).
- **Out-of-range subscription filters fail early.** A subscription filter value
  outside the database integer range now fails at subscribe time with a
  validation error. Before, the stream opened and later ended with
  `INTERNAL_SERVER_ERROR`.
- **Legacy cursors keep trailing NULL rows.** A legacy value-only (pk-less)
  cursor on ascending order over a nullable field now returns the trailing
  `NULL` rows, which were skipped before.
- **Client page.** The `/graphql/client/` page gained a Stop control and
  context-aware completion. No action is needed.
