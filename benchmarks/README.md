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

## What the published artifacts are

Every figure in `results/` and on
[Why django-graphex](https://eamigo86.github.io/django-graphex/why/) is the
**median of three runs** per library per seed. Each file records that under an
`aggregation` key — if that key is **absent**, the file is a single run, which
is what `run_all.sh` writes by default.

Three runs is not ceremony. Repeating the same code minutes apart on the same
machine drifts by up to **8 %** here, so one sample cannot resolve any
difference smaller than that. A run is discarded rather than published when a
SQL count or a `surface` list moves, or when latencies rise **uniformly across
all four libraries** — three of them are code nobody in this repo touched, so
they are the control: if they move together, the machine moved, not the code.

### Cold import and schema build are two different numbers

`schema_import_ms` used to be labelled "schema build", and it was timing
`import bench_schema` — which pays the library's **whole dependency tree** and
the **schema construction** in one measurement. Those differ by two orders of
magnitude, so their sum answers neither question:

| | cold import | rebuild (declarations only) |
| :--- | ---: | ---: |
| graphex | ~9–10 ms | ~3 ms |
| graphene-django | ~10 ms | ~4 ms |
| strawberry | ~98–107 ms | ~6 ms |
| ariadne | ~44–49 ms | ~2 ms |

strawberry's hundred milliseconds is **importing strawberry**, not building
anything. Both figures now ship in every artifact:

- **`schema_import_ms`** — the cold first import. What a process actually pays
  at startup, and the only one of the two comparable across libraries.
- **`schema_rebuild_samples_ms`** — the schema built again with the dependency
  tree already imported, five times, kept as a **raw series in order**.

The rebuild series is a **diagnostic, not a comparison, and it is deliberately
not reduced to a median.** Re-executing declarations perturbs each library's
process state differently: django-graphex's series climbs measurably
(`[2.99, 3.38, 3.70, 3.89, 4.34]` is typical) while ariadne's is flat
(`[2.74, 2.16, 1.96, 1.97, 2.02]` — one warm-up sample, then level).
**Read the series down one column; never across.** It is not a cache hit: in
all four libraries the rebuilt schema object, its `GraphQLSchema`, its Author
type and that type's fields are all new objects.

django-graphex's climb has a known cause, so the series **understates it** by
roughly 45 %: `_gdx_output_registry` (`django_graphex/core/base.py`) is an
append-only list of every declared type, and `compile_all_outputs()` walks the
whole thing, calling `recompile_fields()` on each dead generation as well as
the live one. Truncating that list between rebuilds flattens the series to
~2.6 ms. The first sample of each series is therefore the uncontaminated
figure. This costs a real deployment nothing — `compile_all_outputs()` runs
once per process from `AppConfig.ready()` — and the permission-scoped schema
path does not touch it at all (`prune_schema` is a graphql-core clone-on-write
transform that declares no types; 500 distinct permission signatures leave the
list at 6).

### The cold-import bias, and its fix

`run_all.sh` seeds the database under `.venv-graphex/bin/python`, which left
graphex's imports and file cache hot while the other three were measured cold —
a bias **in graphex's favour**, on the one row where the libraries are closest.
It now warms **every** virtualenv with a throwaway import before the measured
loop. The spread on that row fell from **24–51 % to 3–15 %**.

Even fixed, do not read a winner out of it between graphex and graphene-django:
one millisecond apart, on a metric that wanders 3–15 %, is not a result. An
order of magnitude is — ariadne roughly 5×, strawberry roughly 10×.

## The fairness rule (read this first)

The four libraries do **not** share a schema. Each has its own
`libs/<lib>/bench_schema.py` written in **that library's idiomatic style**
(its own pagination, filtering, and mutation syntax). What they DO share:

1. **The same models** (`benchapp/models.py`) and the **same seeded database**
   (`seed_bench`, deterministic `random.Random(42)`).
2. **The same Django version** — pinned identically in every venv, read from the
   repo's own `.venv` (see `setup_envs.sh`). Same Python (3.12).
3. **The same five logical operations**, defined by the operation contract below.

4. **The same schema surface.** Every library declares the same explicit field
   lists — `fields` on graphene-django, `strawberry.auto` annotations on
   strawberry, the SDL on ariadne, `Meta.only_fields` on graphex — so no library
   is charged for compiling a different amount of surface. **Seven** of the
   **eighteen** declared fields are in no operation's selection set at all —
   `Author.bio`, `Author.email`, `Post.body`, `Post.createdAt`,
   `Comment.authorName`, `Comment.createdAt`, `Comment.isApproved` — and that is
   deliberate: the schema-build number compares how much surface each library
   compiles, so the surface has to be the same one whether a query reaches it or
   not. **This rule is checked, not asserted**: the harness introspects the
   built schema and writes the declared field lists into `results/<lib>.json`
   under `surface`, so
   `diff <(jq .surface results/graphex.json) <(jq .surface results/ariadne.json)`
   settles it.

   On graphex that option is also a **security boundary**: a projected column is
   unreadable, unorderable and unfilterable through the type, so
   `PostType.filter_fields` naming the `author` relation is admitted only
   because `AuthorType` publishes the author's key. Counted and timed over three
   runs by `guard_cost.py`, the shared predicate costs **46 calls / 0.69–0.71 ms
   of a 9–12 ms schema build** and **17 calls / about 0.015 ms per `nested`
   request** (0.13 % of it). Both are inside the numbers, and neither is
   switchable off.

Per-library query documents may differ in **SHAPE** (e.g. graphex uses a
`results {} / totalCount` wrapper and asks it for `results(limit:, ordering:)`;
graphene uses Relay connections; strawberry uses `OffsetPaginationInput`; ariadne
uses whatever its SDL defines). They **MUST be semantically equivalent**: the
same rows are touched, the same fields are returned. No library is allowed to
short-cut an operation (e.g. skip the nested comments, or over-fetch a smaller
set). Each operation ships a `validate()` callable that asserts the response
shape; the harness aborts loudly if validation fails, because **a benchmark that
returns the wrong data is invalid**.

**No operation on any library selects `totalCount`** — the five documents ask for
rows, never for a count — and that is the whole story behind the SQL counts on
the two list rows. graphex issues no `COUNT` at all, because its count is
deferred to the selection that asks for it; graphene's Relay connection issues
one regardless, and that unasked-for `SELECT COUNT(*)` is the second query in
its `flat_list` and its `filtered` row. Neither is a short-cut: both return the
same rows to the same document, and what differs is what each library does with
a count nobody requested.

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
| `nested`         | The **N+1 stressor**         | **20** authors, each with **10** posts, each with **5** comments (`text`)                              | exact IDs, order, content and 20×10×5 cardinality          |
| `single`         | One object by id + relation  | One post by a **fixed mid-range pk** (`5000`), with `title` + `author.name`                            | title non-empty; author name non-empty                    |
| `filtered`       | Filtered list                | Posts whose title contains **`post 42`** (seed guarantees **111** matches: >5, <200), limit **50**    | exact first **50** matching IDs and titles                 |
| `create_comment` | Mutation                     | Create a `Comment` on post pk `5000`, returning its `id`                                               | returned `id` present / mutation ok                        |

The seed produces posts titled `Post 0` .. `Post 9999`, so `icontains "post 42"`
matches `Post 42`, `Post 420..429`, `Post 4200..4299`, and `Post 1420..9942…`
= **111** rows — comfortably inside the `>5, <200` window.

`create_comment` runs last, but like every request it is enclosed in a
rollback-only transaction. Validation, SQL probes, warmups and samples leave
both row counts and the SQLite sequence unchanged. BEGIN/ROLLBACK sit outside
the timer and SQL capture, so isolation does not become part of the result.

## What the harness records

`harness.py` runs inside a library's venv (`BENCH_LIB` selects it) and writes
`scratch/<lib>.json` unless the publisher assigns a raw-run directory:

```jsonc
{
  "lib": "graphex",
  "versions": { "...": "..." },
  "python": "3.12.11",
  "django": "6.0.6",
  "machine": { "platform": "...", "cpu_count": 16 },
  "schema_import_ms": 12.27,           // time to build the schema (import bench_schema)
  "surface": {                          // declared field lists, read back by introspection
    "Author": ["bio", "email", "id", "name", "posts"],
    "Post": ["author", "body", "comments", "createdAt", "id", "status", "title", "viewsCount"],
    "Comment": ["authorName", "createdAt", "id", "isApproved", "text"]
  },
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
the first response. Every one of those requests is rolled back independently.

## Running it

```bash
# 1. Recreate the four environments from the exact constraints.
./setup_envs.sh                 # or: ./setup_envs.sh graphex

# Strict offline replay (fails if uv's local cache/runtime is incomplete).
BENCH_OFFLINE=1 ./setup_envs.sh

# 2. Diagnostic single run (ignored scratch output; never canonical).
./run_all.sh                    # or: ./run_all.sh graphex

# 3. Publish from the repository root after every invariant passes.
(cd .. && python benchmarks/run_publish.py --authors 1000 2000 --runs 3)

# Diagnostic results land in scratch/run_all/<lib>.json.
```

Run a single library manually:

```bash
BENCH_LIB=graphex DJANGO_SETTINGS_MODULE=config.settings .venv-graphex/bin/python harness.py
```

The publisher recreates the database for each seed, warms every environment,
runs three repetitions with a rotating library order, and verifies versions,
dataset identity, the complete response contract, surface, SQL counts and
provenance. Only after all 24 raw runs pass does it median the timing statistics
and replace the eight canonical JSON files. Raw runs stay under ignored
`scratch/publish/`; a failure leaves every existing canonical file untouched.

Python is fixed to the canonical `3.12.11` patch release. Each artifact records
the measured Git commit and the SHA-256 of
`constraints.txt`. `versions.env` pins direct inputs; `constraints.txt` is the
union of the four complete environment freezes. `setup_envs.sh` rejects any
installed transitive version not present in that freeze. This makes a second
recreation byte-identical at the package/version level.

### Provenance: measured state versus delivery state

The coordinates in each canonical JSON answer different questions:

- `commit` and `measurement_tree` identify the **actual local commit and tree
  that were measured**. The commit is intentionally not required to resolve
  from GitHub; the full tree SHA preserves the measured source identity.
- `constraints_sha256` identifies the dependency freeze used by that run and
  must equal the digest of the tracked `constraints.txt`.
- `delivery_base_commit` is only the public ancestor from which the generated
  JSON files were delivered and validated. It does **not** say that commit was
  measured, nor claim byte, tree or semantic equivalence with the measured
  state.

The current delivery base
(`4d595f1c4822d37a520a188892a943caa744f2ea`) contains post-measurement
hardening in `contract.py`, `harness.py`, `setup_envs.sh`, `versions.env`, and
the new `verify_freeze.py`. Those changes strengthen response validation,
transaction isolation and offline replay; they do not retroactively move the
measurements.

CI checks this boundary, all eight result contracts, and Git ancestry from a
full-history checkout without trying to resolve the local measurement commit:

```bash
python benchmarks/run_publish.py --validate-existing
```

## Layout

```
benchmarks/
├── .gitignore
├── README.md                         # this file (contract + fairness rules)
├── setup_envs.sh                     # per-lib venvs, identical Django pin
├── constraints.txt                   # exact union freeze for all four venvs
├── run_all.sh                        # diagnostic single run -> scratch/
├── run_publish.py                    # validated median publisher -> results/
├── harness.py                        # the measurement loop (runs in a lib venv)
├── guard_cost.py                     # what the projection boundary costs (docs/why.md cites it)
├── config/
│   ├── settings.py                   # single shared settings; LIB_APPS per lib
│   └── urls.py                       # mounts libs/<BENCH_LIB>/bench_schema.graphql_view
├── benchapp/
│   ├── models.py                     # library-agnostic blog domain
│   └── management/commands/seed_bench.py
├── libs/
│   ├── graphex/bench_schema.py       # reference implementation (django-graphex v2)
│   ├── graphene/bench_schema.py      # Relay nodes + DjangoFilterConnectionField
│   ├── strawberry/bench_schema.py    # strawberry.auto + DjangoOptimizerExtension
│   └── ariadne/bench_schema.py       # SDL-first + hand-written resolvers
└── results/                          # <lib>.json + 2x_<lib>.json — TRACKED (see below)
```

## The results are tracked on purpose

`docs/why.md` cites eight artifacts by path, so eight artifacts are in the
repository: `results/<lib>.json` (1,000-author seed) and `results/2x_<lib>.json`
(the doubled seed the published table uses). A citation a reader cannot open is
not a citation, and these files are 1.7 kB each — cheap honesty.

`.gitignore` therefore ignores `results/*` and re-includes exactly those eight.
Anything else you leave in there (summaries, ad-hoc reruns) stays ignored.
`run_all.sh` can never overwrite these files. Only `run_publish.py`, after both
datasets and every invariant pass, replaces the canonical set.

## Seeded dataset

| Entity     | Count  | Notes                                            |
| ---------- | ------ | ------------------------------------------------ |
| Authors    | 1,000  |                                                  |
| Categories | 20     |                                                  |
| Tags       | 100    |                                                  |
| Posts      | 10,000 | 10/author, ~80% published, `views_count` random |
| Comments   | 50,000 | 5/post                                           |
| Post↔Tag   | 30,000 | ~3 tags/post (M2M through table)                 |

Deterministic (`random.Random(42)`), pks contiguous `1..N` on a fresh DB, so the
fixed mid-range post pk `5000` is stable across every run.
