# Why django-graphex?

Every library carries the fingerprints of the person who built it. This page is
the honest story of where django-graphex comes from — and the benchmark that
tells you, in numbers, what those years of thinking bought you.

## The story

I come from a Django REST Framework background, and that DNA runs through every
line of this project. If you have ever written a DRF `ViewSet`, attached a
`permission_classes`, reached for a `pagination_class`, or leaned on a
serializer to validate an incoming payload, then django-graphex is going to feel
like home. That was deliberate. I did not want GraphQL in Django to feel like a
foreign framework bolted onto your models — I wanted it to feel like the Django
you already know, with the ergonomics you already trust.

Years ago I built [graphene-django-extras](https://github.com/eamigo86/graphene-django-extras)
as a hobby. It came together over a single weekend, born out of necessity: a
production project I was working on kept running into the real limitations of
graphene-django at the time, and I needed a way out. So I wrote one. It solved
concrete pain for concrete people, and to my surprise it found an audience. But
I'll be honest with you — I never gave it all the love it deserved. Life moved
on, the weekend project stayed a weekend project, and it quietly kept working
for people while I looked elsewhere.

Meanwhile, the ground it stood on shifted. Over the following years, the pace of
maintenance on graphene and graphene-django slowed considerably — releases
stretched further apart, issues sat longer without answers. I want to be very
clear about this: that is not a criticism of the people who built those
projects. Graphene taught an entire generation of Django developers what GraphQL
even *was*. It walked so the rest of us could run. I have nothing but gratitude
for the work — and for the maintainers who carried it as far as they did, on
their own time, for free.

django-graphex is me coming back to settle a pending debt. It is the same
initial idea behind graphene-django-extras — GraphQL for Django with DRF-style
ergonomics — but rebuilt the way it always deserved to be built. Modern
foundations: [graphql-core](https://github.com/graphql-python/graphql-core) and
[Pydantic](https://docs.pydantic.dev/) underneath, with **zero graphene** in the
stack. The best performance I could squeeze out of it, profiled and benchmarked
rather than assumed. Documentation treated as a first-class deliverable instead
of an afterthought. And test coverage pushed as high as I could take it — the
suite currently sits at **4,100+ tests** with a hard **≥95% coverage floor**
enforced in CI.

!!! quote "What this library wants to be"
    The most complete Django + GraphQL experience possible — queries, filtering,
    pagination, mutations with validation, permissions, and subscriptions.
    Batteries included, one install. No Relay tax you didn't ask for, no graphene
    to maintain underneath you.

## How it compares

The repository carries four distinct benchmark series. The current
`core33-4.0.0-bf6e1ed6ccb6d3940d253c9c83b19a436f01aa4e` results are
below. The earlier `core33-4.0.0-01f82ab94c86a5f35918dec4ba51deee02a58ac9`,
3.1.1-source core33 and original 3.1.0 comparisons remain historical evidence,
not current-package claims.

## Current core33 comparison

The current eight [portable result files](https://github.com/eamigo86/django-graphex/tree/826d5bae87ed7bbe705cf309d46a16d3ad3cdf33/benchmarks/results/core33-4.0.0-bf6e1ed6ccb6d3940d253c9c83b19a436f01aa4e/) measure the prepared 4.0.0 source, not a published wheel. The measured [source checkout](https://github.com/eamigo86/django-graphex/tree/bf6e1ed6ccb6d3940d253c9c83b19a436f01aa4e) is commit `bf6e1ed6ccb6d3940d253c9c83b19a436f01aa4e` (tree `619d81147c006c1eeb4a10eadc4867140649e4dc`). The artifact files were added later at publication commit `826d5bae87ed7bbe705cf309d46a16d3ad3cdf33`; that commit is not the measuring source. The prepared 4.0.0 release is not yet published.

Each dataset has 1,000 or 2,000 authors, ten posts per author and five comments per post (50,000 or 100,000 comments). Four pinned whole stacks ran the same five operations in three cyclically rotated repetitions, with 15 warmups and 100 timed requests per operation per run. Cells show each per-run p50 statistic's three-run median in milliseconds and request-only SQL statements. The companion artifacts contain p95 and other statistics; their p95 is the median of per-run p95 values, **not a pooled 300-sample percentile**. Five schema rebuild figures are per-position diagnostics, not request latencies.

All stacks use Python 3.12.11 and Django 6.0.8, but this is **not an equal-core competition**: GraphEx and Strawberry use graphql-core 3.3.0; Graphene and Ariadne use 3.2.13. Versions, distinct per-library manifest and constraints SHA-256 values, Raw SHA-256 triplets, response surface, fixed SQL counts and source/seed hashes are recorded in the artifacts. The fresh seed and measurement source are both `bf6e1ed6ccb6d3940d253c9c83b19a436f01aa4e`, unlike the earlier 3.1.1-source diagnostic batch. Digests corroborate retained local bytes; they are not signed attestation or a filesystem sandbox.

<!-- core33-stacks:start -->
| Library | Selected whole-stack versions |
| :-- | :-- |
| graphex | django 6.0.8, django-graphex 4.0.0, graphql-core 3.3.0 |
| graphene | django 6.0.8, django-filter 25.2, graphene 3.4.3, graphene-django 3.2.3, graphql-core 3.2.13 |
| strawberry | django 6.0.8, graphql-core 3.3.0, strawberry-graphql 0.328.0, strawberry-graphql-django 0.90.0 |
| ariadne | ariadne 1.1.0, ariadne-django 0.3.0, django 6.0.8, graphql-core 3.2.13 |
<!-- core33-stacks:end -->

<!-- core33-results:start -->
| Authors | Library | Flat list | Nested | Single | Filtered | Create comment |
| :-- | :-- | --: | --: | --: | --: | --: |
| 1,000 | graphex | 0.9191 ms / 1 SQL | 23.9056 ms / 3 SQL | 0.4728 ms / 1 SQL | 1.3569 ms / 1 SQL | 0.4912 ms / 4 SQL |
| 1,000 | graphene | 1.9709 ms / 2 SQL | 67.6724 ms / 442 SQL | 1.0555 ms / 2 SQL | 3.9441 ms / 2 SQL | 1.2085 ms / 1 SQL |
| 1,000 | strawberry | 2.0616 ms / 1 SQL | 31.9331 ms / 3 SQL | 1.2226 ms / 1 SQL | 2.6168 ms / 1 SQL | 1.7608 ms / 8 SQL |
| 1,000 | ariadne | 1.2869 ms / 1 SQL | 45.6589 ms / 221 SQL | 0.9386 ms / 2 SQL | 1.7158 ms / 1 SQL | 0.8636 ms / 1 SQL |
| 2,000 | graphex | 1.0153 ms / 1 SQL | 24.4239 ms / 3 SQL | 0.4539 ms / 1 SQL | 1.3764 ms / 1 SQL | 0.4700 ms / 4 SQL |
| 2,000 | graphene | 1.8954 ms / 2 SQL | 70.9776 ms / 442 SQL | 1.1866 ms / 2 SQL | 7.0437 ms / 2 SQL | 1.3248 ms / 1 SQL |
| 2,000 | strawberry | 2.1149 ms / 1 SQL | 35.9225 ms / 3 SQL | 1.1270 ms / 1 SQL | 2.6473 ms / 1 SQL | 1.8842 ms / 8 SQL |
| 2,000 | ariadne | 1.4982 ms / 1 SQL | 46.5779 ms / 221 SQL | 1.0243 ms / 2 SQL | 2.0179 ms / 1 SQL | 0.9234 ms / 1 SQL |
<!-- core33-results:end -->

For create_comment, GraphEx/Ariadne p50 is 0.57× at 50,000 comments (0.4912/0.8636 ms, about 43% lower) and 0.51× at 100,000 (0.4700/0.9234 ms, about 49% lower). GraphEx's direct-write integrity check uses 4 request-internal SQL statements against Ariadne's 1; the lower observed latency is not a promise of fewer statements. GraphEx had the lowest observed p50 in all five operations at both sizes **in this batch**, not universally. These are SQLite whole-stack timings, not PostgreSQL performance results. PostgreSQL 17 CI provides correctness validation only.

The user accepted existing background work. Pre/post aggregate CPU observations cannot prove constant load, thermal stability or an idle host during the batch. Rotation reduces fixed ordering bias but cannot remove every confounder. Do not compare these figures as a paired speedup against the older series from separate sessions. The successful runner validated first responses, SQL probes, warmups and timed requests with rollback isolation; individual successful child streams and HTTP bodies were not retained. The private 72-record journal was generated **after** batch completion from checked receipts, not timestamped live child events.

See the [benchmark guide](https://github.com/eamigo86/django-graphex/blob/bf6e1ed6ccb6d3940d253c9c83b19a436f01aa4e/benchmarks/README.md) and [named command](https://github.com/eamigo86/django-graphex/blob/bf6e1ed6ccb6d3940d253c9c83b19a436f01aa4e/benchmarks/run_publish_core33.py) for the `run` and `replay` modes. Replaying retained raws validates them but does not repeat measurement; `run` creates fresh private seeds and a costly new batch. Both require a trusted external results parent and a fresh immutable series.

### Historical core33 4.0.0 pre-fragment comparison

The previous [eight portable artifacts](https://github.com/eamigo86/django-graphex/tree/d4ef486af0e283c49a1c22a5c8fee92d51e8b42c/benchmarks/results/core33-4.0.0-01f82ab94c86a5f35918dec4ba51deee02a58ac9/) measured source `01f82ab94c86a5f35918dec4ba51deee02a58ac9` before the fragment-annotation correction. They remain available as historical evidence, not a paired baseline for the current timings.

### Historical core33 3.1.1-source comparison

The following original core33 table predates the scoped SQLite mutation checker. It remains the 3.1.1-metadata migration measurement and must not be rebranded as a 4.0.0 timing result.

The earlier eight committed [3.1.1-source core33 results](https://github.com/eamigo86/django-graphex/tree/integration/benchmarks/results/core33/) cover 1,000
and 2,000 authors, with ten posts per author and five comments per post. Each
library runs five equivalent operations for 100 timed requests in each of
three validated runs. Cells show the median of each run's p50 in milliseconds
and the request-only SQL count. They do **not** compare identical dependency
stacks: all use Python 3.12.11 and Django 6.0.8, but django-graphex and
Strawberry use graphql-core 3.3.0, whereas Graphene and Ariadne use
graphql-core 3.2.13. The artifacts record full selected dependency versions
and separate per-library constraints hashes.

<!-- historical-core33-stacks:start -->
| Library | Selected whole-stack versions |
| :-- | :-- |
| graphex | django 6.0.8, django-graphex 3.1.1, graphql-core 3.3.0 |
| graphene | django 6.0.8, django-filter 25.2, graphene 3.4.3, graphene-django 3.2.3, graphql-core 3.2.13 |
| strawberry | django 6.0.8, graphql-core 3.3.0, strawberry-graphql 0.328.0, strawberry-graphql-django 0.90.0 |
| ariadne | ariadne 1.1.0, ariadne-django 0.3.0, django 6.0.8, graphql-core 3.2.13 |
<!-- historical-core33-stacks:end -->

<!-- historical-core33-results:start -->
| Authors | Library | Flat list | Nested | Single | Filtered | Create comment |
| :-- | :-- | --: | --: | --: | --: | --: |
| 1,000 | graphex | 0.8301 ms / 1 SQL | 19.5582 ms / 3 SQL | 0.3832 ms / 1 SQL | 1.2067 ms / 1 SQL | 4.7725 ms / 4 SQL |
| 1,000 | graphene | 1.6373 ms / 2 SQL | 59.1942 ms / 442 SQL | 0.9216 ms / 2 SQL | 3.2392 ms / 2 SQL | 0.9701 ms / 1 SQL |
| 1,000 | strawberry | 1.7351 ms / 1 SQL | 29.2775 ms / 3 SQL | 0.9668 ms / 1 SQL | 2.0930 ms / 1 SQL | 1.2801 ms / 8 SQL |
| 1,000 | ariadne | 1.1141 ms / 1 SQL | 40.1715 ms / 221 SQL | 0.8606 ms / 2 SQL | 1.5429 ms / 1 SQL | 0.7818 ms / 1 SQL |
| 2,000 | graphex | 0.8335 ms / 1 SQL | 19.5867 ms / 3 SQL | 0.3834 ms / 1 SQL | 1.1910 ms / 1 SQL | 9.2149 ms / 4 SQL |
| 2,000 | graphene | 1.6338 ms / 2 SQL | 60.9607 ms / 442 SQL | 0.9403 ms / 2 SQL | 5.1500 ms / 2 SQL | 0.9816 ms / 1 SQL |
| 2,000 | strawberry | 1.7090 ms / 1 SQL | 27.8590 ms / 3 SQL | 0.9974 ms / 1 SQL | 2.0691 ms / 1 SQL | 1.2398 ms / 8 SQL |
| 2,000 | ariadne | 1.1210 ms / 1 SQL | 40.3793 ms / 221 SQL | 0.8419 ms / 2 SQL | 1.5311 ms / 1 SQL | 0.7766 ms / 1 SQL |
<!-- historical-core33-results:end -->

The Graphex create-comment figures above were measured before the prepared
4.0.0 SQLite mutation checker was narrowed to directly written rows. They
remain the original 3.1.1-source measurements, not post-optimization timings.

Every reported timing statistic is the median of that statistic across three
raw runs; the median of per-run p95 values is **not a pooled 300-sample
percentile**. The five schema rebuild values are per-position median
diagnostics, not a cross-library ranking. The machine's recorded platform and
CPU count describe the observed host, not guaranteed CPU quietness. Raw SHA-256
digests, shared response surface, fixed SQL counts, stack versions and source
hashes are in each artifact. These older local digests corroborate retained bytes;
they are not signed attestation of loaded source or a filesystem sandbox.

Measurement used the **unreleased migration checkout**
`350ae84256fdad1b1a98a6e0bef8d0f63609257f` (tree
`0afc136997b01b281c2a9f6c11cf062708b718ef`) whose django-graphex
metadata was 3.1.1; the separately prepared seed came from
`1b5b941e2555a5bffee8a109ee0a32fdef1258fd`. These are not measurements
of a published 3.1.1 wheel or of a 4.0.0 release. To reproduce a fresh
profile or validate retained evidence, follow the explicit `run` and `replay`
modes in [benchmarks/run_publish_core33.py](https://github.com/eamigo86/django-graphex/blob/integration/benchmarks/run_publish_core33.py)
and the [benchmark guide](https://github.com/eamigo86/django-graphex/blob/integration/benchmarks/README.md); `run` creates private
seeds and performs a costly new batch, whereas `replay` validates retained
raws without measuring. Both need a trusted external results parent.

### Historical 3.1.0 comparison

The original comparison below is frozen with its original versions and
measurements; it must not be relabeled as a core33 or 3.1.1 result.

### The conditions

Credibility is in the conditions, so let me state all of them up front.

- **Identical runtime.** Same pinned **Python 3.12.11** and **Django 6.0.6**
  across all four virtual environments. Canonical pinned library versions:
  graphene-django 3.2.3 (+ graphene 3.4.3, django-filter 25.2),
  strawberry-graphql-django 0.86.4 (+ strawberry-graphql 0.320.1),
  ariadne 1.1.0 (+ ariadne-django 0.3.0). django-graphex is the one exception:
  it is installed **editable from this repository**, not from PyPI. These
  artifacts measured django-graphex **3.1.0**, and record the exact source
  commit plus the SHA-256 of the shared dependency constraints.
- **Historical version boundary.** These are 3.1.0 measurements, not 3.1.1
  security-patch results. Their Django 6.0.6 and GraphQL-core 3.2.11 pins
  remain frozen for provenance even though current library and Playground
  dependencies use patched versions. A comparison for 3.1.1 would require new
  measurements rather than relabeling these artifacts.
- **Identical data.** The same Django models and the same seeded dataset for
  everyone: **2,000 authors, 20,000 posts, 100,000 comments, 60,000 tag
  relations**, generated from a deterministic seed. That is the `--authors 2000`
  seed; `run_all.sh` seeds **half** of it by default (see *Reproduce it
  yourself*).
- **Five semantically-equivalent operations**, each written in the *idiomatic
  syntax of the library under test*: a flat list (50 rows), a nested query
  (20 authors → 10 posts → 5 comments — the N+1 stressor), a single object, a
  filtered list (`icontains`), and a create mutation.
- **Identical schema surface.** All four declare the *same explicit field
  lists*, so nobody is charged for compiling fields nobody queries — and you do
  not have to take that on trust: the harness introspects the built schema back
  out and records the declared fields under `surface` in every result artifact,
  so the rule is a thing you can diff rather than a thing I assert. On graphex
  the option is `Meta.only_fields`, which is also a security boundary — a
  projected column is unreadable, unorderable and unfilterable — so the
  reference schema demonstrates the boundary while it is being measured.
- **Each library in its recommended production setup.** strawberry runs **with
  its `DjangoOptimizerExtension` enabled**; graphene-django runs stock (its
  optimizer is a separate, unmaintained package); ariadne uses hand-written
  idiomatic resolvers; graphex runs on defaults.
- **A strict harness.** Django test client, **15 warmup + 100 measured
  iterations** per operation, sequential single-session run, **response-shape
  validation before timing** (a benchmark that returns the wrong data is
  invalid), and SQL counts captured via `CaptureQueriesContext`.
  macOS 26.5 arm64, 16 cores, SQLite.
- **Three repetitions per library, per seed; every figure is the median.** One
  run is not a measurement. Raw timings vary, so every artifact records the
  source values and the reported statistic under `aggregation`. The publisher
  rejects version, dataset, response, SQL, schema-surface, iteration-count or
  provenance drift. It **does not reject a run because its timing is slower**:
  timings are observations, not a gate.
- **Mutations cannot contaminate the next sample.** Contract validation, SQL
  probes, warmups and timed requests each run in a transaction forced to
  rollback. Row counts and the database sequence are checked before and after
  every library. Timing and published SQL counts cover only the GraphQL request,
  not the harness's `BEGIN/ROLLBACK` boundary.
- **The nested response is exact, not merely non-empty.** Every implementation
  must return 20 authors, 10 posts per author and 5 comments per post, with the
  expected IDs, ordering and content, before timing begins.

### The results

Per-request **p50 latency (ms)** and **SQL queries** for each operation. Lower is
better on both.

| Operation | django-graphex | graphene-django | strawberry | ariadne |
| :-------- | :------------- | :-------------- | :--------- | :------ |
| **flat_list** (50 rows) | **0.82 ms** · 1 SQL 🏆 | 1.73 ms · 2 SQL | 1.64 ms · 1 SQL | 1.17 ms · 1 SQL |
| **nested** (20→10→5) | **16.28 ms** · **3 SQL** 🏆 | 60.04 ms · <span style="color: #e53935;">**442 SQL**</span> | 28.98 ms · 3 SQL | 42.73 ms · 221 SQL |
| **single** object | **0.41 ms** · 1 SQL 🏆 | 0.95 ms · 2 SQL | 0.96 ms · 1 SQL | 0.85 ms · 2 SQL |
| **filtered** (`icontains`) | **1.16 ms** · 1 SQL 🏆 | 4.91 ms · 2 SQL | 2.02 ms · 1 SQL | 1.57 ms · 1 SQL |
| **create_comment** mutation | 11.77 ms · 4 SQL | 0.98 ms · 1 SQL | 1.31 ms · 8 SQL | **0.83 ms** · 1 SQL 🏆 |

### Startup cost is a different question, so it gets a different row

The number this page used to call "schema build" was timing an
`import bench_schema`, which pays **two unrelated costs at once**: loading the
library and its whole dependency tree off disk, and compiling your declarations
into a schema. Those turn out to differ by two orders of magnitude, so their
sum answers neither question. They are now measured separately.

**Cold import** — library + dependencies + one schema build, which is what a
process actually pays at startup:

| Metric | django-graphex | graphene-django | strawberry | ariadne |
| :----- | :------------- | :-------------- | :--------- | :------ |
| **Cold import**, 2,000-author run | 10.21 ms | 10.45 ms | 93.24 ms | 47.88 ms |
| *…at the 1,000-author seed* | *9.30 ms* | *10.81 ms* | *98.70 ms* | *45.58 ms* |

Read it as an **order of magnitude**: graphex and graphene-django
indistinguishable around 10 ms, ariadne roughly 5× them, strawberry roughly
10×. It still does **not** say which of the first two is faster, and it never
could — the two are one millisecond apart while the eight canonical
cold-import sample sets span roughly **9–24 %** from minimum to maximum relative
to their median. Earlier revisions of this page named opposite winners there;
neither should have been published.

What that row does *not* measure is how fast each library compiles a schema.
With the dependency tree already imported, rebuilding the same schema costs
roughly **3 ms (graphex), 4 ms (graphene-django), 6 ms (strawberry), 2 ms
(ariadne)** — so strawberry's 106 ms is overwhelmingly the cost of *importing
strawberry*, not of building anything. Those figures are in the artifacts under
`schema_rebuild_samples_ms`, kept as a raw series rather than reduced to a
single number, because they are **a diagnostic and not a comparison**:
re-executing declarations perturbs each library's process state differently.
django-graphex's series climbs measurably across repeated rebuilds where
ariadne's is flat, which is a property of graphex worth knowing and not a
property you can rank libraries by. Read the series down one column, never
across.

**The bias this row used to carry is gone.** `run_all.sh` seeds the database
under the graphex interpreter, which left graphex's imports hot while the other
three were measured cold — a bias in graphex's favour on the one row where the
libraries are closest. It now warms **every** virtualenv before measuring any of
them. Each canonical artifact retains all three import samples so you can
inspect that spread directly. The per-operation rows never had the problem: p50
over 100 iterations after 15 warmups is long past any import cost.

Every operation cell above is the `p50_ms` / `sql_queries` pair sitting in
`benchmarks/results/2x_<lib>.json` — each the **median of three runs**, recorded
in the file under `aggregation` — and those four files are **tracked in the
repository** — a clone or a `git archive` export contains them, and you can read
them on GitHub without cloning anything. (The published sdist ships only the
library, its tests and the docs, so the benchmark tree is not in the tarball.)
Open them, diff them against your own run, and hold this table to what they say.

### What the numbers actually mean

The **nested** row is the one that matters at scale. For the *same response*,
graphene-django fires **442 SQL queries** where graphex fires **3** — a textbook
N+1 explosion that graphex avoids by prefetching the relation tree. And here's
the part that's easy to miss: this ran on **local SQLite**, which *understates*
the gap. In production, against Postgres over a network, every one of those 442
round-trips pays real latency. The 16.28 ms vs 60.04 ms measured here becomes a
far wider chasm the moment there's a wire between your app and your database.

The **scaling story** is just as telling. Doubling the dataset (from 1,000 to
2,000 authors) left graphex's filtered operation **flat: 1.13 ms → 1.16 ms** —
it's `O(page)`: no unconditional `COUNT`, and a `LIKE` + `LIMIT` early exit.
Over the same doubling, graphene-django's filtered operation climbed from
**3.25 ms → 4.91 ms** — it's `O(table)`, because its count scans the whole
thing. The lead doesn't just hold as your data grows; it *widens*.

Every number in that paragraph is the `filtered` operation's **p50**, read from
four tracked artifacts: `benchmarks/results/graphex.json` and
`benchmarks/results/graphene.json` for 1,000 authors, and the `2x_` files beside
them for 2,000 (`benchmarks/README.md` has the reseed recipe). graphex's pair
rose by 0.03 ms across a doubling — which is noise, and is exactly why the claim
here is **flat** rather than *slower*. graphene's rose by 1.66 ms, far beyond
that noise.

!!! warning "Honest caveats — because you should trust numbers that admit their limits"
    - **The cold-import row is still the weakest number on this page**, even
      with its bias fixed. It is one sample per process; the current artifacts'
      minimum-to-maximum spread is roughly 9–24 % relative to their medians, so
      an order of magnitude is a finding there and a millisecond is not, in
      *either* direction. The source samples are recorded under `aggregation`.
    - **The rebuild series is a diagnostic, not a ranking.** graphex climbs
      across repeated in-process rebuilds where ariadne is flatter, because an
      append-only registry of declared types makes every rebuild re-walk dead
      generations. A deployment pays none of that repeated-run effect: the walk
      happens once per process, at `AppConfig.ready()`. It is why the series
      ships as raw samples rather than a comparable figure.
    - **graphex's parse + validate cache shines on repeated documents** — which is
      the real-world API pattern, where the same operations run over and over.
    - **ariadne's numbers are hand-written raw resolvers.** That's idiomatic for
      ariadne, and it's fast — but it carries *none* of the framework services the
      other three provide out of the box: validated filter inputs, pagination
      wrappers, error envelopes. It's a fair comparison of what each tool *is*, not
      a like-for-like feature comparison.
    - **The security guards are in these numbers.** The
      [projection boundary](usage/types.md#projection-security-boundary) runs one
      shared predicate on two paths: the filter guard consults it while the
      schema builds, and the ordering allowlist consults it per request on the
      nested window path. `benchmarks/guard_cost.py` can profile that predicate
      locally, but its diagnostic is not published as a canonical timing. There
      is no switch to turn the boundary off, so nothing here is a "guards off"
      number and no A/B against one exists.

### Reproduce it yourself

I don't want you to take my word for any of this. The complete harness lives in
the repo under [`benchmarks/`](https://github.com/eamigo86/django-graphex/tree/main/benchmarks),
and so do the eight result artifacts every number on this page was read from —
`results/<lib>.json` for the 1,000-author seed and `results/2x_<lib>.json` for
the doubled one, tracked rather than gitignored precisely so you can open them
before you run anything. The README there documents the full operation contract
and the fairness rules. Recreate the exact pinned environments, then run the
validated median publisher from the repository root:

```bash
cd benchmarks && ./setup_envs.sh && cd ..
python benchmarks/run_publish.py --authors 1000 2000 --runs 3
```

It recreates each seed, rotates library order, validates the response contract,
versions, schema surface and SQL counts, then atomically publishes all eight
medians. A failed raw run leaves the existing canonical artifacts untouched.

The direct versions live in `benchmarks/versions.env`; the complete transitive
freeze lives in `benchmarks/constraints.txt`. Every result stores `commit` and
`measurement_tree` for the **actual local commit and tree that were measured**,
plus `constraints_sha256` for the dependency graph. `delivery_base_commit` is
only the public ancestor from which the JSON was delivered and validated; it is
not the measured state and does **not** claim byte, tree or semantic equivalence
with it. The benchmark README documents and CI validates that boundary without
trying to resolve the local measurement commit.

After priming uv's cache, replay without network access:

```bash
BENCH_OFFLINE=1 benchmarks/setup_envs.sh
python benchmarks/run_publish.py --authors 1000 2000 --runs 3
```

Offline mode fails clearly when the cache lacks a required distribution instead
of silently resolving a different environment.

!!! note "One last, honest word"
    Every one of these libraries made different trade-offs, and every one serves
    its users well. graphene taught us GraphQL; strawberry brought a beautiful
    typed, modern API; ariadne gives you schema-first purity and total control.
    Performance is only *one* dimension — pick the tool that fits your project and
    your team. But if the question you're asking is *"how do I get performance
    **with** batteries included?"*, then this — right here — is the answer the data
    gives.
