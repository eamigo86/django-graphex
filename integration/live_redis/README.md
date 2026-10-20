# Verify SSE leases against Redis

This explicit integration suite executes the account-cap Lua scripts on a
**test-owned Redis process**. It checks cross-process admission, renewal,
expiry, cancellation, and public SSE responses. The default suite does not
start or require Redis: `pyproject.toml` discovers `tests/`, while this file
lives under `integration/live_redis/`.

## Run the suite

Use a disposable local Redis 8.10.2 build and a separately extracted
`redis` Python 8.1.0 wheel. Do not install either into the project environment.
The sample artifacts used for this test matrix are:

| Artifact | Official source | SHA-256 |
| --- | --- | --- |
| Redis source | [redis-stable.tar.gz](https://download.redis.io/redis-stable.tar.gz), [published checksum](https://download.redis.io/redis-stable.tar.gz.SHA256SUM) | `430eb3e07c77678b6d6907593474fd3d2b2de524e51a2f84cbe5afda86f81a0f` |
| `redis` wheel | [redis 8.1.0 on PyPI](https://pypi.org/project/redis/8.1.0/) | `a4fe1aac3d3b3cc791d4b3d5931c5a956045dc951ee74d1c913ee3ac4d2ee9fb` |

Verify each download against its published hash before extraction. Extract
only archive paths contained within a fresh disposable directory; verify the
wheel's `RECORD` hashes. From the verified Redis source, `make -j2 build redis`
builds only the core server and does not install it globally. Avoid `make
bootstrap`, which can alter the host toolchain.

From the repository root, with a compatible `graphql-core` 3.3 environment:

```bash
export DJANGO_GRAPHEX_LIVE_REDIS_SERVER=/absolute/disposable/path/redis-server
export DJANGO_GRAPHEX_LIVE_REDIS_CLIENT_DIR=/absolute/disposable/path/redis-wheel-extract
export PYTHONPATH="$PWD:$DJANGO_GRAPHEX_LIVE_REDIS_CLIENT_DIR${CORE33_DIR:+:$CORE33_DIR}"
export PYTHONDONTWRITEBYTECODE=1
.venv/bin/python -B -m pytest -p tests.conftest -q --no-cov \
  --randomly-seed=21002 integration/live_redis/test_sse_live_redis.py
```

The optional `CORE33_DIR` suffix is only for an isolated supported
`graphql-core` 3.3 overlay when the local environment lacks it. A clean
installation satisfying this project's dependency constraint needs no overlay.
The suite fails, rather than skips, when the server/client inputs are missing
or their versions/origin differ from this pinned matrix. It imports the
existing test settings plugin explicitly because its location is outside
`tests/`; `--no-cov` disables only coverage collection for this separate
integration command, not the repository's ordinary coverage gate.

The fixture creates a mode-0700 private Unix socket and a fresh loopback TCP
port for the **same owned process**. Direct Lua and child-process checks use
the socket; public SSE uses TCP because the documented setting intentionally
accepts only `redis://` and `rediss://`. No ambient Redis service, credentials,
Docker daemon, or existing database is used. Persistence is off. The fixture
terminates only its own child and verifies its exit after the suite. This
single-instance proof does not establish Redis failover or partition safety.
