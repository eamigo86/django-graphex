# SPEC — Effective max page size across paginators

**Status:** IMPLEMENTED in `pre-v2` (`BaseDjangoGraphqlPagination._resolve_page_size`;
tests in `tests/test_pagination_limits.py`). Decisions: (1) keep `MAX_PAGE_SIZE=None`
default (unbounded out of the box, fully back-compat); (2) keep the cursor `20`
floor, extracted to a module constant `DEFAULT_CURSOR_PAGE_SIZE`.
**Area:** 4 of 4 (order: 2 → 4 → 1 → 3).
**Scope (planned):** `paginations/pagination.py` (the three paginators +
`BaseDjangoGraphqlPagination`); tests; docs; changelog.
**Date:** 2026-06-08

---

## 1. Problem

`MAX_PAGE_SIZE` already exists and is wired as the default cap of
`LimitOffsetGraphqlPagination.max_limit` and
`PageGraphqlPagination.max_page_size` (configurable per-type via the paginator
constructor). But it is **not an effective ceiling**:

| # | Severity | Defect |
|---|----------|--------|
| 4.1 | 🔴 | **The max only clamps an explicitly-provided value.** When the client omits `limit`/`page_size` and there is no default, the full queryset is returned — `max` is never applied. In `LimitOffset`: `if limit is None: return qs`. |
| 4.2 | 🔴 | **Unbounded out of the box.** `DEFAULT_PAGE_SIZE` and `MAX_PAGE_SIZE` default to `None`, so an unpaginated list query returns the whole table — the DoS surface cost analysis only *estimates*. |
| 4.3 | 🟡 | **Inconsistent across paginators.** `CursorGraphqlPagination` has **no** per-instance max (reads global `MAX_PAGE_SIZE` directly, hard-codes a `20` fallback); `LimitOffset`/`Page` have one. |

---

## 2. Goals / Non-Goals

**Goals**
- **G1** — `max` (per-type `max_limit`/`max_page_size`, default `MAX_PAGE_SIZE`)
  becomes a **hard ceiling always applied**: the effective page size is
  `min(requested_or_default_or_max, max)`. In particular, when the client omits
  the page-size arg and no default is set, the effective size **falls back to
  `max`** instead of "unbounded".
- **G2** — One shared resolver on `BaseDjangoGraphqlPagination`
  (`_resolve_page_size`) used by all three paginators; identical semantics.
- **G3** — `CursorGraphqlPagination` gets a per-instance `max_page_size`
  (default `MAX_PAGE_SIZE`) like the others (4.3).
- **G4** — Preserve the strict positive-int validation already in place
  (`_nonzero_int`/`_positive_int`): `0`/negative limits still error.

**Non-Goals**
- Changing the default of `MAX_PAGE_SIZE`/`DEFAULT_PAGE_SIZE` (stays `None`).
- Cursor keyset internals (only its page-size resolution changes).

---

## 3. Design

### 3.1 Shared resolver
```python
# BaseDjangoGraphqlPagination
def _resolve_page_size(self, requested, default, maximum):
    """Effective page size: requested -> default -> maximum, clamped at maximum.

    Returns None only when requested, default AND maximum are all None
    (unbounded; back-compat for "no pagination configured").
    """
    value = requested if requested is not None else default
    if value is None:
        value = maximum                 # max is the fallback ceiling
    if value is None:
        return None                     # truly unbounded
    value = _positive_int(value, strict=True)   # validate (0/neg -> ValueError)
    return min(value, maximum) if maximum is not None else value
```

### 3.2 Per-paginator wiring
- **LimitOffset** — `limit = self._resolve_page_size(kwargs.get(limit_param),
  self.default_limit, self.max_limit)`; `if limit is None: return qs`
  (unbounded only when default *and* max are unset). Removes the
  `if limit is None: return qs` shortcut that bypassed the cap.
- **Page** — `requested = kwargs.get(page_size_param)` when
  `page_size_query_param` is set else `None`; `page_size =
  self._resolve_page_size(requested, self.page_size, self.max_page_size)`;
  `if page_size is None: return None` (unchanged sentinel).
- **Cursor** — add `max_page_size=MAX_PAGE_SIZE` to `__init__`; `size =
  self._resolve_page_size(kwargs.get(first_param), self.page_size,
  self.max_page_size)`; keep the final `or DEFAULT_PAGE_SIZE or 20` floor
  (cursor keyset always needs a concrete size).

### 3.3 Behavior matrix (LimitOffset/Page)
| `default` | `max` | client sends | effective |
|---|---|---|---|
| None | None | — | unbounded (back-compat, **unchanged**) |
| None | 100 | — | **100** (was: unbounded) ← the fix |
| 25 | 100 | — | 25 |
| 25 | 100 | 500 | 100 (capped) |
| None | 100 | 500 | 100 (capped, unchanged) |

Only rows where `max` is set change, and only to *enforce the max the user
already configured*. Nothing changes when no pagination is configured.

---

## 4. Acceptance Criteria
- **AC1** — With `max` set and no default, omitting the page-size arg returns at
  most `max` rows (not the full set).
- **AC2** — An explicit page size above `max` is clamped to `max` (all three
  paginators).
- **AC3** — With neither default nor max set, behavior is unchanged (unbounded).
- **AC4** — `0`/negative page sizes still raise (strict validation preserved).
- **AC5** — `CursorGraphqlPagination(max_page_size=…)` clamps `first` per
  instance; default remains `MAX_PAGE_SIZE`.

---

## 5. Open questions (please confirm)
1. **Hard safety default?** Keep `MAX_PAGE_SIZE=None` ⇒ unbounded by default
   (fully back-compat, recommended), or ship a non-None default (e.g. `100`) so
   the library is bounded out of the box? The latter is safer but a
   **behavior change** for every existing project on upgrade. **Recommend: keep
   `None`**, document strongly (already cross-linked from cost analysis).
2. **Cursor `20` floor**: keep the existing `… or 20` final fallback (cursor
   needs a concrete size to build the keyset) — OK, or make that floor a named
   constant / setting? **Recommend: keep, extract to a module constant** for
   clarity.
