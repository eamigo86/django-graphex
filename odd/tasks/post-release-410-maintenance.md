# Post-release 4.1.0 maintenance

Status: LOCAL_FIX_VERIFIED_DELIVERY_AND_CLEANUP_PENDING. Repository locator: odd/tasks/post-release-410-maintenance.md.

## Objective and authority

The maintainer authorized uploading the final 4.1.0 tracking closure, fixing
publisher cache warnings, and cleaning temporary branches and environments.
Preserve the published tag and all release/benchmark evidence. Do not publish
again, move/create/delete tags, dispatch publishing workflows, rebuild release
packages locally, modify package behavior or change any coverage threshold.

Use account eamigo86 only for eamigo86/django-graphex. Parent owns GitHub
operations, commits, branch deletion, environment cleanup and Engram mirrors.
No new pull request is required by known repository policy for this explicitly
authorized maintenance; normal fast-forward pushes must reject divergence.
Never force a source-history rewrite. RDD remains globally OFF.

## Baseline and scope

- Development: /Users/eamigo/Documents/Work/django-graphex.
- Maintenance branch: codex/post-release-4.1.0-maintenance, starting at local
  06ece90d3e7a9067129ed4bfc45383aec4bc6dc4.
- Remote main and released commit:
  c576baa241b999693c9cf14d70d101751ed83fcd.
- Published annotated tag v4.1.0 object:
  eb2bef230c3e4987064faba5214f7f4c6461e78c. Never mutate it.
- Existing local-only closure commits cf44cfb and 06ece90 change only
  odd/tasks/release-410-pr-delivery.md and must travel with this maintenance.
- GitHub Release 424974975 and its wheel, sdist and SHA256SUMS are immutable.
  Wheel digest: f0485628b9ed4944ec4203c311ac52bc60603395a60015e1a36b5b54240cd740.
  Sdist digest: fcd104038024fd197e3b6af73eae767a92f050899b3db361a30877138a943efa.
  Manifest digest: 7d1fc45de69514b52a005d64d8f7e0517c7c9782e013c19fe1308824428d2d26.
- Preserve four untracked original audit documents, .codegraph, original
  project environments, the shared venv-head verification interpreter and
  every evidence/report/log/download/constraint/freeze file.
- Keep the clean frozen benchmark checkout at f9f4eae. It is an app-managed
  primary checkout with ignored measurement evidence; prior archive refusal
  must not be bypassed or retried as a manual removal.
- The local inventory found merged branch candidates but also many unique
  recovery/tracking tips. Delete only freshly verified, strictly merged
  temporary branches. Preserve all unique/unmerged work by default.
- Environment removal is restricted to exact, confirmed disposable venv/cache
  children of the recorded release/RDC proof roots. No broad glob deletion.

## Implementation and proof

Workflow: delegated direct, not SDD. Narrow cache mapping and cleanup
inventories were delegated because understanding spans more than three files.
One bounded writer owns the workflow, its contract tests and release guide;
parent owns this maintenance record and destructive/delivery operations.
Forecast under 400 authored lines for the warning fix and maintenance record;
the previously committed release tracking closure is separately preserved.
Delivery strategy: single-pr, via the authorized normal
fast-forward main update, without creating a tag or another publication.

Strict TDD is ON from the user's AGENTS instructions. Observe a focused RED
before changing workflow configuration, then minimum GREEN, normalization,
final focal tests and applicable checks. The verified interpreter is:
/private/tmp/claude-501/-Users-eamigo-Documents-Work-django-graphex/beff4e6e-3a6e-47db-be34-debf3cc0d12e/scratchpad/venv-head/bin/python.
Focused tests must use --no-cov, retain configured addopts, and may disable
cacheprovider without adding a cache_dir override. No original environment
mutation or local distribution build is allowed.

The exact pinned setup-uv source confirms two independent causes:
enable-cache=false prevents unused cache-key/glob work, while
ignore-empty-workdir=true is separately needed for the intentional no-checkout
publisher. Apply both only in publish; remove its unused cache suffix. Keep all
other caches, action pins, immutable download/checksum flow, event guards and
release gates unchanged. This changes CI housekeeping, not package behavior.
Do not run publish again merely to demonstrate the absence of these warnings.

## Tasks

- [x] M41-1 — Preserve baseline evidence before cleanup. Create a durable,
  ignored local archive under var/release-evidence/4.1.0 with a verified Git
  bundle, exact-ref manifests, release identities, copied proof/downloads and
  file checksums. Validate copies before removing any environment/cache.
  Preserve raw proof and original files even if cleanup eligibility is unclear.
  Verified archive: var/release-evidence/4.1.0/post-release-maintenance-verified-3/.
  Its Git bundle contains all 264 fully qualified refs, exact snapshot match;
  parent independently reran bundle verification: complete history, PASS.
  Source/worktree HEAD pseudo-entries are separately recorded. Copied 42,870
  regular files (762,428,102 bytes), 1,907 symlinks without following them and
  10 FIFO fixtures without reading them. All source/copy and independent
  archive-reread hashes match; four original audit files are also preserved.
  inventory.json and SHA256SUMS record the actual proof and 17 validated
  disposable children excluded from copying, not deleted (about 802 MB).
  Two earlier incomplete archive attempts are retained pending duplicate-only
  cleanup; neither is accepted as the verified backup. No optional input was
  missing. No ref, tag, source or environment deletion has happened yet.
- [x] M41-2 — Reproduce both warning contracts in RED, implement only the
  publisher setup-uv inputs, document the no-checkout/no-cache rationale, and
  verify focused GREEN plus formatting/type/structural checks. Keep no-publish
  gates intact. Record exact commands, results and coherent commit.
  RED: both new focused tests failed before the workflow edit for the two
  missing inputs. Raw commands, exit codes and RED/GREEN logs are retained
  at /private/tmp/maintenance410-cachefix-9KZlQ7/. GREEN: both new tests and
  all 16 release-workflow tests passed; Ruff lint/format, targeted mypy and
  diff check passed. Parent spot-check: 16 passed in 0.25s. Independent
  functional verifier: 16 passed in 0.18s, unchanged pins/gates/thresholds
  and immutable publisher contract; PASS_SCOPED. Its report is retained at
  /private/tmp/maintenance410-independent-wopwTx/preflight-final-results.json.
  Runtime warning absence cannot be observed without executing the publisher;
  no publisher execution is authorized. Pinned-source causality and executable
  structural tests are the verification boundary for these future runs.
- [ ] M41-3 — Upload the release closure and verified maintenance with a
  normal fast-forward main push using eamigo86 and push.followTags=false.
  Observe all applicable exact-head Actions and Codecov checks. Publication
  jobs must skip on this branch push; do not dispatch or create another tag.
- [ ] M41-4 — Clean only freshly verified merged temporary local/remote
  branches. Back up exact tips first, retain main/current/worktree branches,
  every tag and every unique/unmerged recovery or tracking branch. Check
  current remote PR/ref state and prevent deletion of a changed remote tip.
- [ ] M41-5 — Remove only exact owned disposable environment/cache directories
  after durable evidence verification. Preserve proof roots, reports, logs,
  artifacts, databases, constraints/freezes, shared/original environments and
  the frozen benchmark checkout. Record actual removals and freed space.
- [ ] M41-6 — Verify no republication or released-byte/tag changes, reconcile
  tracking and mirror, confirm evidence recoverability and report completed,
  retained or blocked cleanup items honestly.

## Current evidence and next step

Read-only mapping and inventory are complete; no cleanup has happened.
The pinned action source independently detects an empty directory before its
cache guard, so disabling caching alone is insufficient. References:
https://github.com/astral-sh/setup-uv/blob/fac544c07dec837d0ccb6301d7b5580bf5edae39/src/setup-uv.ts#L69-L119
https://github.com/astral-sh/setup-uv/blob/fac544c07dec837d0ccb6301d7b5580bf5edae39/src/cache/restore-cache.ts#L68-L97

Next: preserve exact baseline and implement the bounded TDD warning fix.
