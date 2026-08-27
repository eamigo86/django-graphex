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

Talk is cheap, so here are the numbers. I built a fairness-first benchmark that
puts django-graphex head-to-head with the three other actively-used Django
GraphQL libraries, on the same database, the same models, and the same
operations. The full harness lives in the repository — you can run it yourself.

### The conditions

Credibility is in the conditions, so let me state all of them up front.

- **Identical runtime.** Same pinned **Python 3.12.11** and **Django 6.0.6**
  across all four virtual environments. Latest PyPI versions of every library:
  graphene-django 3.2.3 (+ graphene 3.4.3, django-filter 25.2),
  strawberry-graphql-django 0.86.4 (+ strawberry-graphql 0.320.1),
  ariadne 1.1.0 (+ ariadne-django 0.3.0). django-graphex is the one exception:
  it is installed **editable from this repository**, not from PyPI. The
  artifacts record `2.2.0` because that is the version string in
  `pyproject.toml`, but the projection boundary priced in the caveats below
  landed *after* the 2.2.0 release — so this run pays for a guard the published
  2.2.0 tarball does not even contain.
- **Identical data.** The same Django models and the same seeded dataset for
  everyone: **2,000 authors, 20,000 posts, 60,000 comments, 60,000 tag
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
  run is not a measurement. Three runs of the *same* code minutes apart drift by
  up to 8 % on this hardware, so a single sample cannot resolve a difference
  smaller than that — and every artifact records which statistic it is under
  `aggregation`. Nothing here is run on a busy machine: a run whose SQL counts
  or `surface` move, or whose latencies rise uniformly across all four
  libraries, is discarded rather than published, because a uniform rise across
  libraries nobody changed is the machine talking, not the code.

### The results

Per-request **p50 latency (ms)** and **SQL queries** for each operation. Lower is
better on both.

| Operation | django-graphex | graphene-django | strawberry | ariadne |
| :-------- | :------------- | :-------------- | :--------- | :------ |
| **flat_list** (50 rows) | **0.79 ms** · 1 SQL 🏆 | 1.73 ms · 2 SQL | 1.70 ms · 1 SQL | 1.24 ms · 1 SQL |
| **nested** (20→10→5) | **12.26 ms** · **3 SQL** 🏆 | 58.18 ms · <span style="color: #e53935;">**442 SQL**</span> | 24.62 ms · 3 SQL | 39.46 ms · 221 SQL |
| **single** object | **0.38 ms** · 1 SQL 🏆 | 0.95 ms · 2 SQL | 1.06 ms · 1 SQL | 0.91 ms · 2 SQL |
| **filtered** (`icontains`) | **1.16 ms** · 1 SQL 🏆 | 5.17 ms · 2 SQL | 2.25 ms · 1 SQL | 1.62 ms · 1 SQL |
| **create_comment** mutation | **0.58 ms** · 1 SQL 🏆 | 1.25 ms · 1 SQL | 2.00 ms · 8 SQL | 1.09 ms · 1 SQL |

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
| **Cold import**, 2,000-author run | 9.17 ms | 9.90 ms | 106.50 ms | 48.71 ms |
| *…at the 1,000-author seed* | *10.01 ms* | *10.70 ms* | *98.00 ms* | *43.97 ms* |

Read it as an **order of magnitude**: graphex and graphene-django
indistinguishable around 10 ms, ariadne roughly 5× them, strawberry roughly
10×. It still does **not** say which of the first two is faster, and it never
could — the two are one millisecond apart on a metric whose run-to-run spread
is 3–15 %. Earlier revisions of this page named opposite winners there, first
graphene by 0.05 ms and then graphex by 1 ms; **both were beneath the
instrument's resolution and neither should have been published.**

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
them. The spread on this row fell from 24–51 % to 3–15 % as a result. The
per-operation rows never had the problem: p50 over 100 iterations after 15
warmups is long past any import cost.

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
round-trips pays real latency. The 12 ms vs 58 ms you see here becomes a far
wider chasm the moment there's a wire between your app and your database.

The **scaling story** is just as telling. Doubling the dataset (from 1,000 to
2,000 authors) left graphex's filtered operation **flat: 1.19 ms → 1.16 ms** —
it's `O(page)`: no unconditional `COUNT`, and a `LIKE` + `LIMIT` early exit.
Over the same doubling, graphene-django's filtered operation climbed from
**3.23 ms to 5.17 ms** — it's `O(table)`, because its count scans the whole
thing. The lead doesn't just hold as your data grows; it *widens*.

Every number in that paragraph is the `filtered` operation's **p50**, read from
four tracked artifacts: `benchmarks/results/graphex.json` and
`benchmarks/results/graphene.json` for 1,000 authors, and the `2x_` files beside
them for 2,000 (`benchmarks/README.md` has the reseed recipe). graphex's pair
*fell* by 0.03 ms across a doubling — which is noise, not an improvement, and is
exactly why the claim here is **flat** rather than *faster*. graphene's rose by
1.94 ms — sixty times that — and is not noise at all.

!!! warning "Honest caveats — because you should trust numbers that admit their limits"
    - **The cold-import row is still the weakest number on this page**, even
      with its bias fixed. It is one sample per process; its spread across
      repetitions is 3–15 %, so an order of magnitude is a finding there and a
      millisecond is not, in *either* direction. The reasoning is stated in
      full beside the table rather than buried here, including what the row
      does not measure.
    - **The rebuild series is a diagnostic, not a ranking.** django-graphex's
      cost climbs across repeated in-process rebuilds where ariadne's is flat,
      and `gc.collect()` between rebuilds makes graphex's *worse* rather than
      better — something is retained. It has no effect on a deployment that
      builds its schema once, which is the normal case, and it is why that
      series ships as raw samples instead of a comparable figure.
    - **graphex's parse + validate cache shines on repeated documents** — which is
      the real-world API pattern, where the same operations run over and over. A
      cold *first* parse pays roughly 0.4–0.75 ms once, then it's amortized away.
    - **ariadne's numbers are hand-written raw resolvers.** That's idiomatic for
      ariadne, and it's fast — but it carries *none* of the framework services the
      other three provide out of the box: validated filter inputs, pagination
      wrappers, error envelopes. It's a fair comparison of what each tool *is*, not
      a like-for-like feature comparison.
    - **The security guards are in these numbers, and they are invisible.** The
      [projection boundary](usage/types.md#projection-security-boundary) runs one
      shared predicate on two paths: the filter guard consults it while the
      schema builds, and the ordering allowlist consults it per request on the
      nested window path. Counted and timed on the reference schema over three
      runs: **46 calls costing 0.69–0.71 ms of a 9–12 ms schema build**, and
      **17 calls costing about 0.015 ms per `nested` request — 0.13 % of that
      operation**, against a run-to-run stddev of roughly 2.7 ms. Reproduce it
      with `benchmarks/guard_cost.py` (same venv, same seeded database as the
      table); the figure it prints is an upper bound, because the timer sits
      inside the span it measures. There is no switch to turn the boundary off,
      so nothing here is a "guards off" number and no A/B against one exists.

### Reproduce it yourself

I don't want you to take my word for any of this. The complete harness lives in
the repo under [`benchmarks/`](https://github.com/eamigo86/django-graphex/tree/main/benchmarks),
and so do the eight result artifacts every number on this page was read from —
`results/<lib>.json` for the 1,000-author seed and `results/2x_<lib>.json` for
the doubled one, tracked rather than gitignored precisely so you can open them
before you run anything. The README there documents the full operation contract
and the fairness rules; `./setup_envs.sh && ./run_all.sh` regenerates everything
from scratch — venvs, database, seed, and the per-library result JSONs, which
means it **overwrites** the tracked 1,000-author four. That is the point: run
it, then `git diff benchmarks/results/` and see how far your machine lands from
mine (a 16-core arm64 macOS 26.5 laptop on SQLite).

`run_all.sh` seeds **1,000 authors**, half the dataset above. To reproduce the
table exactly, seed the doubled set against a **fresh** database — the seed
deletes rows but SQLite keeps counting primary keys, and the `single` operation
addresses a fixed mid-range pk:

```bash
cd benchmarks
rm -f db.sqlite3
BENCH_LIB=graphex DJANGO_SETTINGS_MODULE=config.settings \
  .venv-graphex/bin/python -m django migrate --run-syncdb
BENCH_LIB=graphex DJANGO_SETTINGS_MODULE=config.settings \
  .venv-graphex/bin/python -m django seed_bench --authors 2000
for lib in graphex graphene strawberry ariadne; do
  BENCH_PREFIX=2x_ BENCH_LIB=$lib DJANGO_SETTINGS_MODULE=config.settings \
    ".venv-$lib/bin/python" harness.py
done
```

`BENCH_PREFIX=2x_` is what writes `results/2x_<lib>.json` — the very files the
table above is read from. Without it the loop writes the 1,000-author names with
2,000-author numbers inside them, and nothing complains: both seeds are valid
runs, so only the caller knows which one this was.

!!! note "One last, honest word"
    Every one of these libraries made different trade-offs, and every one serves
    its users well. graphene taught us GraphQL; strawberry brought a beautiful
    typed, modern API; ariadne gives you schema-first purity and total control.
    Performance is only *one* dimension — pick the tool that fits your project and
    your team. But if the question you're asking is *"how do I get performance
    **with** batteries included?"*, then this — right here — is the answer the data
    gives.
