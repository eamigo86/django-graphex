# django-graphex GraphQL performance benchmark

A **fairness-first** benchmark comparing four Django GraphQL libraries on the
same database, same models, same operations:

| Library                     | App entry needed  | Idiom used here                              |
| --------------------------- | ----------------- | -------------------------------------------- |
| django-graphex (local v2)   | `django_graphex`  | `DjangoObjectType` + `DjangoListObjectType`  |
| graphene-django (latest)    | `graphene_django` | `DjangoObjectType` + Relay / list resolvers  |
| strawberry-graphql-django   | none              | `@strawberry_django.type` + fields           |
| ariadne (latest)            | none              | SDL-first + resolvers                         |

The benchmark measures **schema build time**, **per-operation latency**
(mean / p50 / p95 / min / stddev over 100 timed iterations), and **SQL query
count** per operation. It is fully deterministic and offline.

## The fairness rule (read this first)

The four libraries do **not** share a schema. Each has its own
`libs/<lib>/bench_schema.py` written in **that library's idiomatic style**
(its own pagination, filtering, and mutation syntax). What they DO share:

1. **The same models** (`benchapp/models.py`) and the **same seeded database**
   (`seed_bench`, deterministic `random.Random(42)`).
2. **The same Django version** — pinned identically in every venv, read from the
   repo's own `.venv` (see `setup_envs.sh`). Same Python (3.12).
3. **The same five logical operations**, defined by the operation contract below.

Per-library query documents may differ in **SHAPE** (e.g. graphex uses a
`results {} / totalCount` wrapper with `results(limit:, offset:)`; graphene uses
Relay connections; strawberry uses `OffsetPaginationInput`; ariadne uses whatever
its SDL defines). They **MUST be semantically equivalent**: the same rows are
touched, the same fields are returned. No library is allowed to short-cut an
operation (e.g. skip the nested comments, or over-fetch a smaller set). Each
operation ships a `validate()` callable that asserts the response shape; the
harness aborts loudly if validation fails, because **a benchmark that returns the
wrong data is invalid**.

Django itself is tuned identically for all libraries (`config/settings.py`,
`DEBUG=False`). Each library's own performance knobs (query optimizer,
dataloaders) live in its `bench_schema.py`, never in shared settings — that is
the library's job to get right, and measuring it is the point.

## The operation contract

Each `libs/<lib>/bench_schema.py` MUST export exactly three symbols:

```python
graphql_view    # a ready Django view callable, mounted at path("graphql/", ...)
OPERATIONS      # dict: 5 fixed keys (below)
LIB_VERSIONS    # dict: installed package name -> version string
```

`OPERATIONS` has **exactly these five keys**, each a dict:

```python
{
    "query":     str,             # the GraphQL document (library-idiomatic shape)
    "variables": dict | None,     # variables, or None
    "validate":  callable,        # (response_json) -> None; raises AssertionError on wrong shape
}
```

| Key              | What it exercises            | Semantic definition (same for all libs)                                                              | validate() asserts                                        |
| ---------------- | ---------------------------- | ---------------------------------------------------------------------------------------------------- | --------------------------------------------------------- |
| `flat_list`      | Scalar list, no relations    | First **50** posts, scalar fields only: `id, title, status, viewsCount`                               | exactly **50** items, those four fields present            |
| `nested`         | The **N+1 stressor**         | **20** authors, each with **10** posts, each with **5** comments (`text`)                              | 20 authors; nested posts arrive; nested comments arrive    |
| `single`         | One object by id + relation  | One post by a **fixed mid-range pk** (`5000`), with `title` + `author.name`                            | title non-empty; author name non-empty                    |
| `filtered`       | Filtered list                | Posts whose title contains **`post 42`** (seed guarantees **111** matches: >5, <200), limit **50**    | at least **1** item                                        |
| `create_comment` | Mutation                     | Create a `Comment` on post pk `5000`, returning its `id`                                               | returned `id` present / mutation ok                        |

The seed produces posts titled `Post 0` .. `Post 9999`, so `icontains "post 42"`
matches `Post 42`, `Post 420..429`, `Post 4200..4299`, and `Post 1420..9942…`
= **111** rows — comfortably inside the `>5, <200` window.

`create_comment` always runs **last** (it mutates the DB).

## What the harness records

`harness.py` runs inside a library's venv (`BENCH_LIB` selects it) and writes
`results/<lib>.json`:

```jsonc
{
  "lib": "graphex",
  "versions": { "...": "..." },
  "python": "3.12.11",
  "django": "6.0.6",
  "machine": { "platform": "...", "cpu_count": 16 },
  "schema_import_ms": 12.27,           // time to build the schema (import bench_schema)
  "ops": {
    "flat_list": {
      "mean_ms": 1.71, "p50_ms": 1.56, "p95_ms": 2.00,
      "min_ms": 1.37, "stddev_ms": 1.03,
      "sql_queries": 2,                 // from ONE extra instrumented iteration (not timed)
      "iterations": 100
    }
    // ... nested, single, filtered, create_comment
  }
}
```

Method per operation: **15 warmup** iterations (untimed) + **100 timed**
iterations (`time.perf_counter`, ms). SQL count comes from one extra iteration
wrapped in `CaptureQueriesContext`, excluded from timings. `validate()` runs on
the first response.

## Running it

```bash
# 1. Build one isolated venv per library (same Django, Python 3.12).
./setup_envs.sh                 # or: ./setup_envs.sh graphex

# 2. Fresh DB + seed once, then run every available library's harness.
./run_all.sh                    # or: ./run_all.sh graphex

# Results land in results/<lib>.json
```

Run a single library manually:

```bash
BENCH_LIB=graphex DJANGO_SETTINGS_MODULE=config.settings .venv-graphex/bin/python harness.py
```

## Layout

```
benchmarks/
├── .gitignore
├── README.md                         # this file (contract + fairness rules)
├── setup_envs.sh                     # per-lib venvs, identical Django pin
├── run_all.sh                        # fresh DB, seed once, run all harnesses
├── harness.py                        # the measurement loop (runs in a lib venv)
├── config/
│   ├── settings.py                   # single shared settings; LIB_APPS per lib
│   └── urls.py                       # mounts libs/<BENCH_LIB>/bench_schema.graphql_view
├── benchapp/
│   ├── models.py                     # library-agnostic blog domain
│   └── management/commands/seed_bench.py
├── libs/
│   ├── graphex/bench_schema.py       # reference implementation (django-graphex v2)
│   ├── graphene/bench_schema.py      # (to be implemented)
│   ├── strawberry/bench_schema.py    # (to be implemented)
│   └── ariadne/bench_schema.py       # (to be implemented)
└── results/                          # <lib>.json output (gitignored)
```

## Seeded dataset

| Entity     | Count  | Notes                                            |
| ---------- | ------ | ------------------------------------------------ |
| Authors    | 1,000  |                                                  |
| Categories | 20     |                                                  |
| Tags       | 100    |                                                  |
| Posts      | 10,000 | 10/author, ~80% published, `views_count` random |
| Comments   | 30,000 | 3/post                                           |
| Post↔Tag   | 30,000 | ~3 tags/post (M2M through table)                 |

Deterministic (`random.Random(42)`), pks contiguous `1..N` on a fresh DB, so the
fixed mid-range post pk `5000` is stable across every run.
