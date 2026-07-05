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
suite currently sits at **3,200+ tests** with a hard **≥95% coverage floor**
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
  ariadne 1.1.0 (+ ariadne-django 0.3.0), and django-graphex 2.0.0.
- **Identical data.** The same Django models and the same seeded dataset for
  everyone: **2,000 authors, 20,000 posts, 60,000 comments, 60,000 tag
  relations**, generated from a deterministic seed.
- **Five semantically-equivalent operations**, each written in the *idiomatic
  syntax of the library under test*: a flat list (50 rows), a nested query
  (20 authors → 10 posts → 5 comments — the N+1 stressor), a single object, a
  filtered list (`icontains`), and a create mutation.
- **Each library in its recommended production setup.** strawberry runs **with
  its `DjangoOptimizerExtension` enabled**; graphene-django runs stock (its
  optimizer is a separate, unmaintained package); ariadne uses hand-written
  idiomatic resolvers; graphex runs on defaults.
- **A strict harness.** Django test client, **15 warmup + 100 measured
  iterations** per operation, sequential single-session run, **response-shape
  validation before timing** (a benchmark that returns the wrong data is
  invalid), and SQL counts captured via `CaptureQueriesContext`. macOS arm64,
  16 cores, SQLite.

### The results

Per-request **p50 latency (ms)** and **SQL queries** for each operation. Lower is
better on both.

| Operation | django-graphex | graphene-django | strawberry | ariadne |
| :-------- | :------------- | :-------------- | :--------- | :------ |
| **flat_list** (50 rows) | **0.81 ms** · 1 SQL 🏆 | 1.72 ms · 2 SQL | 1.96 ms · 1 SQL | 1.17 ms · 1 SQL |
| **nested** (20→10→5) | **15.97 ms** · **3 SQL** 🏆 | 61.25 ms · <span style="color: #e53935;">**442 SQL**</span> | 26.86 ms · 3 SQL | 40.62 ms · 221 SQL |
| **single** object | **0.38 ms** · 1 SQL 🏆 | 1.08 ms · 2 SQL | 1.20 ms · 1 SQL | 0.90 ms · 2 SQL |
| **filtered** (`icontains`) | **1.18 ms** · 1 SQL 🏆 | 6.71 ms · 2 SQL | 2.15 ms · 1 SQL | 1.58 ms · 1 SQL |
| **create_comment** mutation | **0.62 ms** · 1 SQL 🏆 | 1.70 ms · 1 SQL | 2.20 ms · 8 SQL | 1.07 ms · 1 SQL |

| Metric | django-graphex | graphene-django | strawberry | ariadne |
| :----- | :------------- | :-------------- | :--------- | :------ |
| **Schema build (import)** | **9.7 ms** 🏆 | 13.7 ms | 179.7 ms | 75.9 ms |

### What the numbers actually mean

The **nested** row is the one that matters at scale. For the *same response*,
graphene-django fires **442 SQL queries** where graphex fires **3** — a textbook
N+1 explosion that graphex avoids by prefetching the relation tree. And here's
the part that's easy to miss: this ran on **local SQLite**, which *understates*
the gap. In production, against Postgres over a network, every one of those 442
round-trips pays real latency. The 15 ms vs 61 ms you see here becomes a far
wider chasm the moment there's a wire between your app and your database.

The **scaling story** is just as telling. When I doubled the dataset (from 1,000
to 2,000 authors), graphex's filtered operation stayed **flat at ~1.2 ms** — it's
`O(page)`: no unconditional `COUNT`, and a `LIKE` + `LIMIT` early exit. Over the
same doubling, graphene-django's filtered operation climbed from **3.55 ms to
6.71 ms** — it's `O(table)`, because its count scans the whole thing. The lead
doesn't just hold as your data grows; it *widens*.

!!! warning "Honest caveats — because you should trust numbers that admit their limits"
    - **Schema-import times are one-shot measurements.** They're noisy run to run,
      though the *ordering* is stable. Treat them as a rough magnitude, not a
      precise figure.
    - **graphex's parse + validate cache shines on repeated documents** — which is
      the real-world API pattern, where the same operations run over and over. A
      cold *first* parse pays roughly 0.4–0.75 ms once, then it's amortized away.
    - **ariadne's numbers are hand-written raw resolvers.** That's idiomatic for
      ariadne, and it's fast — but it carries *none* of the framework services the
      other three provide out of the box: validated filter inputs, pagination
      wrappers, error envelopes. It's a fair comparison of what each tool *is*, not
      a like-for-like feature comparison.

### Reproduce it yourself

I don't want you to take my word for any of this. The complete harness lives in
the repo under [`benchmarks/`](https://github.com/eamigo86/django-graphex/tree/main/benchmarks).
The README there documents the full operation contract and the fairness rules;
`./setup_envs.sh && ./run_all.sh` regenerates everything from scratch — venvs,
database, seed, and the raw per-library result JSONs under `benchmarks/results/`.

!!! note "One last, honest word"
    Every one of these libraries made different trade-offs, and every one serves
    its users well. graphene taught us GraphQL; strawberry brought a beautiful
    typed, modern API; ariadne gives you schema-first purity and total control.
    Performance is only *one* dimension — pick the tool that fits your project and
    your team. But if the question you're asking is *"how do I get performance
    **with** batteries included?"*, then this — right here — is the answer the data
    gives.
