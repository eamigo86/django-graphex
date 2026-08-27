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
  ariadne 1.1.0 (+ ariadne-django 0.3.0), and django-graphex 2.2.0.
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

### The results

Per-request **p50 latency (ms)** and **SQL queries** for each operation. Lower is
better on both.

| Operation | django-graphex | graphene-django | strawberry | ariadne |
| :-------- | :------------- | :-------------- | :--------- | :------ |
| **flat_list** (50 rows) | **0.83 ms** · 1 SQL 🏆 | 1.80 ms · 2 SQL | 1.79 ms · 1 SQL | 1.21 ms · 1 SQL |
| **nested** (20→10→5) | **13.47 ms** · **3 SQL** 🏆 | 62.66 ms · <span style="color: #e53935;">**442 SQL**</span> | 26.54 ms · 3 SQL | 41.76 ms · 221 SQL |
| **single** object | **0.40 ms** · 1 SQL 🏆 | 1.03 ms · 2 SQL | 1.13 ms · 1 SQL | 0.93 ms · 2 SQL |
| **filtered** (`icontains`) | **1.24 ms** · 1 SQL 🏆 | 6.05 ms · 2 SQL | 2.25 ms · 1 SQL | 1.67 ms · 1 SQL |
| **create_comment** mutation | **0.60 ms** · 1 SQL 🏆 | 1.34 ms · 1 SQL | 1.68 ms · 8 SQL | 1.05 ms · 1 SQL |

| Metric | django-graphex | graphene-django | strawberry | ariadne |
| :----- | :------------- | :-------------- | :--------- | :------ |
| **Schema build (import)** | 11.74 ms | 13.72 ms | 153.62 ms | 72.79 ms |

There is no trophy on that last row on purpose: graphex and graphene-django are
two milliseconds apart, which is noise, not a win. See the caveats below.

Every cell above is the `p50_ms` / `sql_queries` pair sitting in
`benchmarks/results/2x_<lib>.json`, and those four files are **tracked in the
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
round-trips pays real latency. The 13 ms vs 62 ms you see here becomes a far
wider chasm the moment there's a wire between your app and your database.

The **scaling story** is just as telling. Doubling the dataset (from 1,000 to
2,000 authors) left graphex's filtered operation **flat: 1.21 ms → 1.24 ms** —
it's `O(page)`: no unconditional `COUNT`, and a `LIKE` + `LIMIT` early exit.
Over the same doubling, graphene-django's filtered operation climbed from
**3.63 ms to 6.05 ms** — it's `O(table)`, because its count scans the whole
thing. The lead doesn't just hold as your data grows; it *widens*.

Every number in that paragraph is the `filtered` operation's **p50**, read from
four tracked artifacts: `benchmarks/results/graphex.json` and
`benchmarks/results/graphene.json` for 1,000 authors, and the `2x_` files beside
them for 2,000 (`benchmarks/README.md` has the reseed recipe). graphex's pair
rose by 0.03 ms across a doubling — well inside the run-to-run noise of a
100-iteration sample, which is why the claim here is **flat** rather than
*faster*, while graphene's rose by 2.4 ms and is not noise at all.

!!! warning "Honest caveats — because you should trust numbers that admit their limits"
    - **Schema-import times are one-shot measurements, and the trophy on that row
      is not a real win.** They are noisy run to run: graphex and graphene-django
      are within two milliseconds of each other here, and in the 1,000-author
      artifacts beside these (`results/graphex.json` vs `results/graphene.json`)
      graphene comes out *ahead* by 0.05 ms. Read that row as **two libraries
      tied around 12 ms, with ariadne paying 6× and strawberry 13× that** — an
      order of magnitude is a finding, a millisecond is not.
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
      runs: **46 calls costing 0.73–1.04 ms of a 10–15 ms schema build**, and
      **17 calls costing about 0.02 ms per `nested` request — 0.15 % of that
      operation**, against a run-to-run stddev of roughly 4 ms. Reproduce it
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
