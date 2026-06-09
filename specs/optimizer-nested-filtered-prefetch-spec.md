# SPEC — Optimizer: nest prefetches under a filtered nested list

**Status:** APPROVED — implementing in `pre-v2`.
**Scope:** `graphene_django_extras/utils.py`, tests, docs.
**Date:** 2026-06-07
**Origin:** edge case found in the playground.

---

## 1. Problem

When a nested list field is **filtered**, the optimizer fetches it with a single
filtered `Prefetch("posts", queryset=<filtered>)`. But a **deeper** nested list on
the same path (e.g. `posts → comments`) is still emitted as a sibling string
lookup `"posts__comments"` in `prefetch_related`. Django forbids the same lookup
(`posts`) appearing with two different querysets, so the query raises:

```
'posts' lookup was already seen with a different queryset.
You may need to adjust the ordering of your lookups.
```

i.e. `authors { results { posts(title_Icontains: "x") { results { comments {
results } } } } }` fails. (Filtered-only or unfiltered-deep queries work.)

## 2. Design

In `queryset_factory`, anything prefetched **under** a filtered `Prefetch` must be
**re-rooted into that Prefetch's own queryset** instead of being a sibling — which
both removes the conflict and optimizes the deeper level. Add a helper
`_merge_filtered_prefetches(prefetch_related, filtered_prefetches)` returning the
top-level `(plain, filtered)` lists:

- For each plain prefetch string `p`:
  - if `p` equals a filtered through → drop (the filtered Prefetch supersedes it);
  - elif `p` is under the nearest filtered through `t` → attach `strip(p, t)` to
    `t`'s queryset;
  - else → keep at top level.
- For each filtered Prefetch `pf`:
  - if `pf.prefetch_through` is under a nearest filtered through `t` → attach a
    re-rooted `Prefetch(strip(pf.through, t), queryset=pf.queryset)` to `t`;
  - else → keep at top level.
- **Materialize bottom-up** (deepest `prefetch_through` first) so each parent
  captures its already-finalized children's querysets via a single
  `queryset.prefetch_related(*children)` call.

`nearest(path)` is the deepest filtered through that is a strict prefix of `path`;
`strip(path, t) = path[len(t) + len(LOOKUP_SEP):]`. This handles arbitrary depth
and filtered-under-filtered.

`select_related` is unaffected (a reverse/list relation is never select_related).

## 3. Acceptance Criteria
- **AC1** `authors → posts(filtered) → <nested list>` no longer raises and returns
  the correct nested data. [fix]
- **AC2** It stays N+1-safe: the number of queries is bounded (independent of the
  number of parents) — the deeper list is prefetched via the filtered parent's
  queryset, not per-parent.
- **AC3** Existing nested-list behavior (unfiltered nested, filtered-only nested,
  per-model paginator reuse) is unchanged; full suite green; base channels-free;
  lint + `mkdocs --strict` green.

## 4. Test Plan (`tests/test_nested_lists.py`)
Using the existing isolated schema (Author → posts reverse FK, Post → coAuthors
M2M → Author list): create posts with co-authors, then run
`{ authors { results { posts(title_Icontains: "…") { results { coAuthors {
results { name } totalCount } } } } } }`:
- assert no error and the expected nested co-authors;
- wrap in `CaptureQueriesContext` and assert the query count is small and constant
  when the number of authors/posts grows (N+1-safe).
- A regression for the previously-failing query.

## 5. Documentation
`docs/usage/query-optimization.md` (or nested-lists): note that a filtered nested
list also optimizes its own deeper nested lists (they are prefetched through the
filtered parent), removing the previous limitation; update the playground README
tip.

## 6. Definition of Done
1. Fix per §2. 2. §3 ACs green via §4; full suite green; base channels-free;
lint + `mkdocs --strict` green. 3. Docs updated. 4. Committed and pushed to
`pre-v2`.
