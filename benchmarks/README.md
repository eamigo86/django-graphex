# django-graphex GraphQL performance benchmark

A **fairness-first** benchmark comparing four Django GraphQL libraries on the
same database, same models, same operations:

| Library                     | App entry needed  | Idiom used here                              |
| --------------------------- | ----------------- | -------------------------------------------- |
| django-graphex (local)      | `django_graphex`  | `DjangoObjectType` + `DjangoListObjectType`  |
| graphene-django (pinned)    | `graphene_django` | `DjangoObjectType` + Relay / list resolvers  |
| strawberry-graphql-django   | none              | `@strawberry_django.type` + fields           |
| ariadne (pinned)            | none              | SDL-first + resolvers                         |

The benchmark measures **schema build time**, **per-operation latency**
(mean / p50 / p95 / min / stddev over 100 timed iterations), and **SQL query
count** per operation. It is deterministic and supports strict offline replay.

## What the published artifacts are

These are **3.1.0 measurements**, not results for the 3.1.1 security patch.
Their frozen environments use Django 6.0.6 and GraphQL-core 3.2.11 as recorded
in `versions.env`, `constraints.txt`, and the eight tracked canonical JSON
artifacts. The current library and Playground locks use patched versions, but
changing historical pins or relabeling old timings would destroy provenance.
New version claims require a new controlled measurement run and new artifacts.

### Named GraphQL-core 3.3 comparison environment

The separate `core33` profile records **whole-stack** inputs and has its own
eight portable results under `results/core33/`. Its four exact freezes live
under `comparison_profiles/core33/`:
django-graphex source and Strawberry use core 3.3.0; Graphene and Ariadne use
their compatible core 3.2.13. All use Python 3.12.11 and Django 6.0.8.
Strawberry's pinned 0.328.0/0.90.0 pair passed the shared seeded nested
response contract with its optimizer enabled. The profile does not modify the
historical constraints, result files, or publisher.

`setup_envs.sh --profile core33` validates every requested manifest/freeze
before installation, builds only fresh `.venv-core33-<library>` environments,
and refuses to overwrite an existing one. Set `BENCH_PYTHON` to an absolute
Python 3.12.11 executable, `BENCH_UV_CACHE_DIR` to an isolated absolute cache,
and optionally `BENCH_PROFILE_VENV_ROOT` to an isolated absolute directory.
Set `BENCH_OFFLINE=1` for cache-only replay. Graphene additionally requires
`BENCH_WHEEL_DIR` containing a verified upstream `promise-2.3-py3-none-any.whl`;
the bootstrap never builds django-graphex or another upstream dependency.
The current source is not installed into the new Graphex venv. The separate
comparison preflight supplies it explicitly and records its commit/version.

When the existing harness receives `BENCH_PROFILE=core33`, its measuring
process also records a `profile_witness`: the loaded backend and schema paths,
actual Python/Django/GraphQL-core versions, source commit and tree, source
version read from the measured checkout, and selected manifest/freeze hashes.
The historical harness without that variable keeps its original output
contract. For a named profile, an optional BENCH_OUTPUT_FD must name the same
directory as BENCH_OUTPUT_DIR; the harness then writes through that held
directory descriptor with an empty filename prefix and exclusive creation.
This is a write boundary, not a new runner or a sandbox for arbitrary callers.
The named runner's read-only `validate_result(plan, result)` checks
this witness against preflight, plus the selected stack, shared schema surface,
five-operation SQL counts, iteration counts, and five schema rebuild samples.
Timings must be finite, nonnegative numbers rather than JSON booleans; SQL
counts must not be booleans either.
It does not create an output or dispatch a measurement; validation does not
turn an unmeasured profile into a published comparison.

Before running a comparison, use run_comparison.py to preflight one named
profile stack. Pass --profile core33, one --library, the absolute
--venv-root containing its profile environment, an existing seeded SQLite
--database, a fresh external --output-root, and --authors 1000 (or the
matching seed size). By default the command prints source commit/tree, source
version, and manifest and freeze digests without creating output. Add --execute
for one diagnostic run through the selected interpreter and existing harness.
It validates the measured result and refuses source, profile, runtime, seed,
or output drift. On execution failure, it retains the output directory and any
unvalidated partial result for inspection; the caller must remove known
disposable output manually. Automatic cleanup cannot prove directory creation
ownership from a later pathname lookup, so it must not delete a foreign regular
result or empty replacement directory. An observed directory change is rejected
before a successful result is returned, but this is not a filesystem sandbox. A
single run is not a published comparison or a three-run median.

`comparison_statistics.aggregate_three` is a pure helper for exactly three
raw results from one already-prepared named-profile plan. It applies the same
single-run validation to each result and returns detached per-statistic
medians; callers retain the raw results separately. The five rebuild values
are per-position diagnostic medians, not one raw rebuild series, and the p95
value is the median of three per-run p95 values, not a pooled percentile over
300 samples. This helper neither runs the harness nor writes or publishes a
comparison. The core 3.3.0 and 3.2.13 stacks remain whole-stack diagnostics,
not an equal-core competition.

`comparison_seed.prepare_seed_plan` checks a proposed fresh, absolute,
external private-seed destination for 1,000 or 2,000 authors using the named
Graphex interpreter. It returns immutable source, profile, freeze, runtime,
and intended database-path observations. This is read-only: it creates no
directory or database and runs no migration or seed command. A later creator
must recheck the destination and source before reserving them; the plan is
neither proof of creator ownership nor a filesystem sandbox. It is not a
measurement or permission to execute a changed or foreign plan.

```python
from pathlib import Path
from benchmarks.comparison_seed import prepare_seed_plan

plan = prepare_seed_plan(
    "core33", Path("/absolute/external/envs"), Path("/absolute/external/seed-1000"), 1000
)
assert not plan.output_root.exists()
```

`comparison_seed_execution.create_private_seed(plan, envs_root)` is the
separate write step. It rechecks every plan field, requires the destination's
existing parent to be owner-only, and uses the selected Graphex interpreter
with an explicit private database path. It runs committed migrations, then
`seed_bench`, and checks the shared cardinalities and fixed post 5000 before
installing the database without replacing an occupied destination. Migration
and seed stdout/stderr files and failed attempt files remain for inspection;
there is no automatic deletion. The returned `PreparedSeed` identifies the
validated database, source plan, digest, and stream paths, not a benchmark
measurement. A fresh checkout needs no historical `benchmarks/db.sqlite3`:
its absence is observed and must remain absent; when that file exists, its
regular-file type and bytes must remain unchanged. Symlinks and other
nonregular historical paths fail closed. A FIFO substituted during acquisition
is opened nonblocking and rejected by the regular-file/inode checks rather
than waiting for a writer. Path and descriptor checks bound
ordinary substitutions, but
opening the random staging directory after creation does not attest creator
ownership. They do not protect against a same-user actor changing every
filesystem operation; the later runner must still preflight the returned
database.

`comparison_batch.run_batch` is the next, unpublished orchestration helper.
It accepts exactly the existing 1,000- and 2,000-author `PreparedSeed` records,
the named environment root, and an already existing owner-only external output
parent. It does not create or reseed a database. For each seed, it dispatches
three cyclic rotations of Graphex, Graphene, Strawberry, and Ariadne through
the checked single-run runner: 24 fresh, distinct raw output directories in
all. Only after every raw JSON passes the existing validator does it return
eight detached three-run medians with their three retained raw paths and both
the original seed and current measurement source witnesses. The older seed
commit is accepted only when its Git source/tree and seed-generating files
match the current data contract; it is never relabeled as the measuring commit.
The parent must be prepared separately, for example as a fresh mode-0700
directory outside the checkout, environments, and private seed directory.

This helper has no CLI, publisher, cleanup, or canonical-result writer. A
failed or incomplete batch raises and leaves every raw or partial output for
inspection; no median is returned as a complete comparison. Source, selected
freezes, seed bytes and SQLite sequences, raw files, and output-parent identity
are rechecked around dispatch. These are bounded ordinary drift checks, not
proof against an actor that can replace every filesystem operation. The
four libraries use disclosed compatible whole stacks, not a common
GraphQL-core version. No new performance figures are published by this helper.

`comparison_publish.publish_core33` is the separate receipt-aware writer for
an already completed batch. Its caller supplies the detached `BatchResult`,
24 numbered `DispatchReceipt` records containing each exact RunPlan, raw path,
SHA-256, and checked measuring-checkout schema context, and an existing
absolute results directory. It rereads every raw
file, applies the shared profile validator, recomputes all eight three-run
medians, then projects only portable versions, dataset, machine platform/CPU,
surface, SQL/timing statistics, aggregation meaning, source and seed digests,
and three raw digests. Private database, backend, schema, output and environment
paths are excluded. The measured source version remains its original value;
the writer's later checkout is not substituted into provenance.

The writer stages all eight JSON files in a private sibling and installs the
entire `results/core33/` directory with one atomic no-clobber rename. An
occupied target is never replaced; failed or uncertain staging residue is
retained for inspection, not deleted automatically. These checks are bounded
integrity and no-clobber controls, not a same-user filesystem sandbox or a
signed provenance receipt. This helper does not seed, measure, invoke the
historical publisher, or update the eight old tracked result files. The
`results/core33/` bundle was generated once by replaying the retained 24
measured raw results. Its eight artifacts record five operations over 100
timed requests in each of three runs for both 1,000- and 2,000-author seeds.
Every timing statistic is the median of that statistic across the three
validated runs; a median of per-run p95 values is not a pooled 300-request
p95. The measured django-graphex source remains 3.1.1 in provenance. These
files now supply the website's separate current core33 comparison; they do
not replace the historical `results/` comparison and are not a 4.0.0
measurement.

Use a trusted results parent without concurrent pathname substitution. A
foreign directory moved into the stage name after creation but before the first
staging descriptor is acquired may be adopted. A foreign directory can receive
all eight exclusive files; if it was empty, that foreign inode can then be
installed as the complete bundle. An inherited filename colliding with one of
the eight causes exclusive creation to fail rather than overwriting it. An
extra, noncolliding inherited file causes validation to reject the bundle,
but the eight added files remain as recoverable foreign-directory residue.
Descriptor checks establish continuity from first acquisition, not creator
ownership or immutable foreign state.

Use `run_publish_core33.py` only with an explicit mode. The expensive `run`
mode requires `--profile core33 --authors 1000 2000 --runs 3`, an existing
named `--venv-root`, existing owner-only external `--seed-parent` with absent
`seed-1000` and `seed-2000` children, empty owner-only external
`--output-parent`, and trusted existing `--results-root` with no `core33`
child. All paths must be absolute. For example:

```sh
.venv/bin/python -m benchmarks.run_publish_core33 run \
  --profile core33 --authors 1000 2000 --runs 3 \
  --venv-root /absolute/named-envs --seed-parent /absolute/private-seeds \
  --output-parent /absolute/private-raws \
  --results-root /absolute/checkout/benchmarks/results
```

It creates two private seeds, performs 24 rotated single-run
measurements, retains their complete receipts as private `events.jsonl`,
`raw-manifest.json`, and `batch-result.json`, then calls the eight-file
publisher. These private records are written after a complete batch and are
not timestamped live child events. Failures preserve private seeds, raw files,
records, and staging residue for inspection; no reset or automatic deletion
occurs. The publisher still refuses an occupied public target.

The [current comparison](../docs/why.md#current-core33-comparison) renders
all five request p50/SQL cells for both seed sizes directly from the eight
committed core33 artifacts. Its historical 3.1.0 section remains separate;
these new results still describe the measured 3.1.1-metadata migration
checkout, not a published 4.0.0 build.

The `replay` mode instead requires `--profile core33 --events`,
`--raw-manifest`, `--batch-result`, and `--results-root`. It reconstructs the
24 typed dispatch receipts from explicit retained files, compares their
cross-file identities, and delegates raw-byte, result, and median validation
to the same publisher. New complete-batch records carry one explicit schema
context per dispatch. Older accepted journals recover that context only from
each corroborating measuring-child cwd, harness argv, selected environment,
and one matching preflight source witness. The explicit new format binds each
dispatch directly and does not require that older preflight record. Missing,
mixed, or contradictory contexts fail before installation; replay does not
replace the measured checkout with the current command checkout. These are
local corroborating records, not signed attestations of loaded source bytes.
It never probes the current named environments, creates seeds, or reruns
measurements. Both modes require a trusted results parent without concurrent
pathname substitution; neither is a same-user
filesystem sandbox. The legacy `run_publish.py` command and its historical
eight artifacts remain separate and unchanged.
The installed `results/core33/` target is intentionally no-clobber; to repeat
the replay, select a fresh series or a separate trusted results parent rather
than deleting or overwriting these artifacts.

For a new comparison, select a fresh immutable child with `--series` in either
mode. The default remains `core33` for existing callers. A series must be one
portable `core33`-prefixed directory name; unsafe names and occupied children
(including links) are refused before seed planning or replay reads. The
prepared 4.0.0 comparison should use
`core33-4.0.0-<full-measurement-commit>` after the measuring source is frozen,
not a mutable `latest` pointer. For example, append
`--series core33-4.0.0-<full-measurement-commit>` to either command above.
The older `results/core33/` bundle stays intact. Selecting a fresh name does
not strengthen the existing trusted-parent or pathname-substitution limits.

```sh
.venv/bin/python -m benchmarks.run_publish_core33 replay \
  --profile core33 --events /absolute/private-raws/events.jsonl \
  --raw-manifest /absolute/private-raws/raw-manifest.json \
  --batch-result /absolute/private-raws/batch-result.json \
  --results-root /absolute/checkout/benchmarks/results
```

The no-argument historical `setup_envs.sh` instead installs published
django-graphex 3.1.0, not this checkout. Run historical tools without a
`PYTHONPATH` that points at newer source so the published wheel is imported.
It checks every requested historical destination before installation and
refuses existing directories, files, and symlinks. If an install fails, it
removes only environments created by that attempt; earlier freeze files and
existing environments remain untouched. Choose an empty, disposable benchmark
checkout for replay rather than deleting a historical environment in place.
For offline Graphene replay, point `UV_FIND_LINKS` at an isolated directory
containing the verified upstream promise 2.3 wheel when it is absent from uv's
cache. The bootstrap still enforces the historical constraints and never
builds django-graphex from this checkout.

Every timing figure in the eight tracked canonical files under `results/` and on
[Why django-graphex](https://eamigo86.github.io/django-graphex/why/) is the
**median of three runs** per library per seed. Each file records that under an
`aggregation` key — if that key is **absent**, the file is a single run, which
is what `run_all.sh` writes by default.

Three runs reduce the influence of a single noisy sample without hiding the
raw measurement contract. The publisher rejects version, dataset, response,
SQL, schema-surface, iteration-count or provenance drift. It **does not reject
a run because its timing is slower**: timings are observations, not a gate, and
their per-statistic medians are published exactly as measured.

### Cold import and schema build are two different numbers

`schema_import_ms` used to be labelled "schema build", and it was timing
`import bench_schema` — which pays the library's **whole dependency tree** and
the **schema construction** in one measurement. Those differ by two orders of
magnitude, so their sum answers neither question:

The canonical cold-import medians are shown below. These values are copied from
the tracked JSON artifacts; the executable documentation contract fails if the
table and artifacts diverge.

| Library | 1,000-author seed | 2,000-author seed |
| :--- | ---: | ---: |
| django-graphex | 9.30 ms | 10.21 ms |
| graphene-django | 10.81 ms | 10.45 ms |
| strawberry | 98.70 ms | 93.24 ms |
| ariadne | 45.58 ms | 47.88 ms |

strawberry's hundred milliseconds is **importing strawberry**, not building
anything. Both figures now ship in every artifact:

- **`schema_import_ms`** — the cold first import. What a process actually pays
  at startup, and the only one of the two comparable across libraries.
- **`schema_rebuild_samples_ms`** — the schema built again with the dependency
  tree already imported, five times, kept as a **raw series in order**.

The rebuild series is a **diagnostic, not a comparison, and it is deliberately
not reduced to a median.** Re-executing declarations perturbs each library's
process state differently. **Read the series down one artifact; never across
libraries.** It is not a cache hit: in all four libraries the rebuilt schema
object, its `GraphQLSchema`, its Author type and that type's fields are all new
objects.

django-graphex's climb has a known cause that is not a canonical timing of its
own: `_gdx_output_registry` (`django_graphex/core/base.py`) is an append-only
list of every declared type, and `compile_all_outputs()` walks the whole thing,
calling `recompile_fields()` on each dead generation as well as the live one.
The first sample of each series is therefore the least perturbed figure. This
costs a real deployment nothing — `compile_all_outputs()` runs once per process
from `AppConfig.ready()` — and the permission-scoped schema path does not touch
it at all (`prune_schema` is a graphql-core clone-on-write transform that
declares no types).

### The cold-import bias, and its fix

`run_all.sh` seeds the database under `.venv-graphex/bin/python`, which left
graphex's imports and file cache hot while the other three were measured cold —
a bias **in graphex's favour**, on the one row where the libraries are closest.
It now warms **every** virtualenv with a throwaway import before the measured
loop. Use the exact artifact-derived columns above rather than inferring a
winner from rounded or historical ranges.

## The fairness rule (read this first)

The four libraries do **not** share a schema. Each has its own
`libs/<lib>/bench_schema.py` written in **that library's idiomatic style**
(its own pagination, filtering, and mutation syntax). What they DO share:

1. **The same models** (`benchapp/models.py`) and the **same seeded database**
   (`seed_bench`, deterministic `random.Random(42)`).
2. **The same Django version** — pinned identically in every venv from
   `versions.env` (see `setup_envs.sh`). Same Python (3.12).
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
   because `AuthorType` publishes the author's key. `guard_cost.py` can profile
   that shared predicate locally; the guard remains inside every canonical
   measurement, but its diagnostic is not published as a timing of its own and
   is not switchable off.

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
the timer and SQL capture, so isolation does not become part of the result. The
graphex mutation itself records **4 request-internal SQL statements** on SQLite:
`SAVEPOINT`, `INSERT`, deferred-FK `PRAGMA foreign_key_check`, and `RELEASE`.
Those recorded core33 results measured the earlier 3.1.1 checkout. The prepared
4.0.0 source now uses a scoped post-write SQLite FK lookup instead of the
table-wide PRAGMA inside an outer transaction. Its new request timing is only
diagnostic until a separate controlled comparison is measured and published;
the eight existing core33 JSON files remain unchanged.

## What the harness records

`harness.py` runs inside a library's venv (`BENCH_LIB` selects it) and writes
`scratch/<lib>.json` by default. The publisher assigns a separate raw-run
directory under `scratch/publish/`:

```jsonc
{
  "lib": "graphex",
  "versions": { "...": "..." },
  "python": "3.12.11",
  "django": "6.0.6",
  "machine": { "platform": "...", "cpu_count": 16 },
  "schema_import_ms": 9.2961,          // cold import: dependencies + schema construction
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
# Run these commands from the repository root.

# 1. Recreate the four environments from the exact constraints.
benchmarks/setup_envs.sh        # or: benchmarks/setup_envs.sh graphex

# Strict offline replay (fails if uv's local cache is incomplete).
BENCH_OFFLINE=1 benchmarks/setup_envs.sh

# 2. Diagnostic single run (ignored scratch output; never canonical).
benchmarks/run_all.sh           # or: benchmarks/run_all.sh graphex

# 3. From the repository root, publish only after every invariant passes.
python benchmarks/run_publish.py --authors 1000 2000 --runs 3

# Diagnostic results land in scratch/run_all/<lib>.json.
```

Run a single library manually:

```bash
cd benchmarks
BENCH_LIB=graphex DJANGO_SETTINGS_MODULE=config.settings .venv-graphex/bin/python harness.py
```

The publisher recreates the database for each seed, warms every environment,
runs three repetitions with a rotating library order, and verifies versions,
dataset identity, the complete response contract, surface, SQL counts and
provenance. Only after all 24 raw runs pass does it median the timing statistics
and replace the eight canonical JSON files. Raw runs stay under ignored
`scratch/publish/`; a failure leaves every existing canonical file untouched.

Each artifact records the measured Git commit and the SHA-256 of
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
│   ├── graphex/bench_schema.py       # reference implementation (django-graphex 3.1)
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
fixed mid-range post pk `5000` is stable across every run. The published doubled
seed contains 2,000 authors, 20,000 posts and **100,000 comments**, preserving
the same 10-posts-per-author and 5-comments-per-post contract.
