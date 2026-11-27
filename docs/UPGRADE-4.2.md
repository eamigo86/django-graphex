# Upgrading to django-graphex 4.2

This guide covers the move from 4.1 to 4.2. If you are still on 4.0, follow
the [4.1 upgrade guide](UPGRADE-4.1.md) first.

```bash
uv add "django-graphex==4.2.0"
# or
pip install "django-graphex==4.2.0"
```

4.2 keeps the `graphql-core>=3.3.1,<3.4` requirement of 4.1.1.

## Upgrading to 4.2.0

4.2.0 is a minor release with no breaking or behavior change for existing
applications: queries, mutations, schemas and settings behave as in 4.1.1. The
only visible difference is in the built-in GraphiQL page, which now runs
subscriptions ([#258](https://github.com/eamigo86/django-graphex/pull/258)).

- **One more pinned CDN asset.** The page loads the SRI-protected
  `graphql-ws@5.16.2` script from unpkg, next to the assets it already loaded.
- **A WebSocket when a subscription runs.** GraphiQL opens a same-origin
  WebSocket to `SUBSCRIPTION_PATH` (default `/ws/graphql/`) only when you run a
  subscription; queries and mutations keep using HTTP.
- **Strict CSP.** If you serve GraphiQL under a strict Content-Security-Policy,
  allow the extra unpkg script and a same-origin WebSocket connection
  (`connect-src` for the `ws:`/`wss:` origin of the page).
- **Offline or locked-down setups.** Point `graphiql_template` at your own
  template to serve the assets yourself; see
  [GraphiQL](usage/views.md#graphiql).

After upgrading to 4.2, continue with the [4.3 upgrade guide](UPGRADE-4.3.md).
