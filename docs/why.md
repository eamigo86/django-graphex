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
  across all four virtual environments. Canonical pinned library versions:
  graphene-django 3.2.3 (+ graphene 3.4.3, django-filter 25.2),
  strawberry-graphql-django 0.86.4 (+ strawberry-graphql 0.320.1),
  ariadne 1.1.0 (+ ariadne-django 0.3.0). django-graphex is the one exception:
  it is installed **editable from this repository**, not from PyPI. These
  artifacts measured django-graphex **3.1.0**, and record the exact source
  commit plus the SHA-256 of the shared dependency constraints.
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
