# SPEC — Directives: bug fixes, optimization, and new directives

**Status:** APPROVED — implementing in `graphene-django-extras 1.2.0`.
**Scope:** `graphene_django_extras/directives/*`, `middleware.py`, tests, docs.
**Date:** 2026-06-07

---

## 1. Problem / Goals

The directive module has correctness bugs and a lot of duplicated, fragile AST
argument parsing. Goals:

- **G1 — Fix bugs:** B1 `@base64(op:…)` no-op; B2 middleware crash on unregistered
  directives; B3 `@floor`/`@ceil` on `None` + `NonNull` return type; B4 directive
  arguments via GraphQL **variables** crash; B5 `@strip` default whitespace; B6
  `@shuffle`/`@sample` on querysets / `k>len`; B7 `@date` relativedelta 3-tuple.
- **G2 — Optimize/DRY:** one coercion-correct, variable-aware argument helper used
  by every directive (built on `graphql.execution.values.get_directive_values`),
  removing all the manual `[... arg ...][0].value.value` parsing. Fixes B1+B4 at
  the root.
- **G3 — New directives** (useful, low-risk): `@truncate`, `@slugify`, `@round`,
  `@abs`, `@unique`. (`@first`/`@last`/`@join` were considered but **dropped**:
  they change a list field into a scalar, which the middleware cannot do — the
  field's declared GraphQL type still drives serialization, so a `List` field
  returning a scalar errors with "Expected Iterable".)
- **G4 — Tests + docs.**

### Non-Goals
- Apollo-style executable directive definitions on the schema; the runtime stays
  the existing `ExtraGraphQLDirectiveMiddleware`.

## 2. Design

### 2.1 Argument helper + middleware
`ExtraGraphQLDirectiveMiddleware.__process_value`:
- skip `@skip`/`@include`; **skip directives not in the registry** (B2);
- compute coerced args once with
  `get_directive_values(directive_def, field_node, info.variable_values)`
  (resolves variables, applies coercion + arg defaults);
- call `directive_class.resolve(value, args, directive_node, root, info)`.

Every directive's `resolve(value, directive, root, info, **kwargs)` becomes
`resolve(value, args, directive, root, info, **kwargs)` and reads `args.get(...)`
instead of parsing the AST. (`directive` node kept for back-compat / introspection.)

### 2.2 Bug fixes
- **B1** `@base64`: `op = args.get("op") or "encode"`; encode/decode by value.
- **B3** numbers: guard `value is None` (return `None`); type check via
  `get_named_type(info.return_type) is GraphQLString`.
- **B5** `@strip`: `chars = args.get("chars")` defaulting to `None` (all
  whitespace).
- **B6** list: `@shuffle` copies to a list first (`items = list(value)`), never
  mutating cached/queryset data; `@sample` clamps `k = min(k, len(items))`.
- **B7** `@date`: fix `_format_relativedelta` empty-result branch to always return
  a 2-tuple.

### 2.3 New directives
| Directive | Args | Behavior |
|-----------|------|----------|
| `@truncate` | `length: Int!`, `end: String = "…"`, `killwords: Boolean = false` | Shorten a string to `length`, appending `end`; break on word boundary unless `killwords`. |
| `@slugify` | — | Django `slugify` (URL-safe slug). |
| `@round` | `precision: Int = 0` | Round a number; returns String if the field is String. |
| `@abs` | — | Absolute value (String-aware like floor/ceil). |
| `@unique` | — | De-duplicate a list, preserving order. |

All registered in `all_directives` and exported.

## 3. Acceptance Criteria
- **AC1** `@base64(op:"encode")` / `@base64(op:"decode")` round-trip correctly. [B1]
- **AC2** A directive argument passed as a **variable** works (e.g.
  `@center(width:$w)`, `@truncate(length:$n)`). [B4]
- **AC3** An unregistered/standard directive on a field does not crash the
  middleware. [B2]
- **AC4** `@floor`/`@ceil`/`@round`/`@abs` return `None` for `None`, and a string
  for a `String`/`String!` field. [B3]
- **AC5** `@strip` with no `chars` removes all surrounding whitespace. [B5]
- **AC6** `@shuffle` on a queryset/list returns a permutation without mutating the
  source; `@sample(k)` with `k>len` returns all. [B6]
- **AC7** New directives behave per §2.3. [G3]
- **AC8** Existing date directive tests stay green; full suite green; base
  channels-free; lint + `mkdocs --strict` green.

## 4. Test Plan (`tests/test_directives.py`)
Extend with a small schema exposing `String`/`Float`/`List` fields and a
middleware, covering each fix (B1–B6) and each new directive, plus a variable-arg
case and the unregistered-directive guard.

## 5. Documentation
Update `docs/usage/` / `docs/api/directives.md` (and `docs/directives.md`) with the
new directives and a note that arguments may be variables.

## 6. Definition of Done
1. SPEC approved.
2. Fixes + helper/middleware refactor + new directives per §2.
3. §3 ACs green via §4 tests; full suite green; base channels-free; lint +
   `mkdocs --strict` green.
4. Docs updated.
5. Committed and pushed to `pre-v2`.
