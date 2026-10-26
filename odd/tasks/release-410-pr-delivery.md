# Deliver the prepared 4.1.0 integration for review

Status: IN PROGRESS. Repository locator: odd/tasks/release-410-pr-delivery.md.

## Objective and authority

Create one reviewable integration pull request for the locally prepared
4.1.0 work and observe its hosted checks. This task is remote delivery for
review, **not** a release or merge.

- The human explicitly authorized one integration PR with a size exception,
  creation and maintainer approval of a tracking issue, one push, and waiting
  for all applicable checks, using account eamigo86 in
  eamigo86/django-graphex. The parent executes and records remote operations.
- Destination: the existing codex/audit-400-remediation branch targeting main
  in eamigo86/django-graphex. Keep this branch; no renaming for a generic
  branch-naming example. Starting local HEAD:
  ede8f93bcf67d66e8bcc63945b117f017d084381. Main reference:
  5a155a059a4d3995ead1b639f08136e5d7619aec.
- The parent-verified integration range contains 400 files, 90,181 additions,
  2,698 deletions and 588 commits. These are full-range review counts, **not**
  an authored-only line count or a claim about generated-file proportions.
  The human explicitly accepted size:exception for this single integrated PR;
  the earlier local-only exception did not grant this remote authority.
- Create the issue from the repository's feature-request fields, confirm the
  status:approved label before PR creation, link it in the PR body, and apply
  exactly one PR type label: type:breaking-change. Record size:exception on
  the PR. The actual issue form labels a new request enhancement and triage;
  it does not grant status:approved automatically. Parent-verified duplicate
  and label checks are preparation evidence, not proof that a new issue or PR
  already exists.
- Explicitly forbidden: merge, tag, PyPI/TestPyPI publication,
  workflow_dispatch, benchmark timing, local release-artifact build, new
  dependency installation, and any automatic release action. Do not edit the
  completed odd/tasks/release-410-preparation.md history or the frozen
  benchmark worktree.

## Workflow and verification policy

- ODD delegated direct, not SDD. Parent owns the issue, approval, commits,
  exact-head push, PR creation/attachment, mirror and tracker updates. RDD is
  globally OFF; do not start review or change its mode.
- Delivery strategy: exception-ok from the human's explicit single-PR remote
  consent. Do not split this approved integration into a chain or infer that
  size approval grants merge or publication.
- Strict TDD remains enabled by the user and AGENTS instructions if any
  implementation change is later authorized: observe RED, then GREEN and
  REFACTOR with the supported interpreter at
  /private/tmp/claude-501/-Users-eamigo-Documents-Work-django-graphex/beff4e6e-3a6e-47db-be34-debf3cc0d12e/scratchpad/venv-head/bin/python.
  This delivery-metadata unit changes no executable behavior, so RED is N/A.
  Its runtime harness is N/A; structural readback and whitespace checks are
  the applicable local checks. No shell script changed, so Shellcheck is N/A.
- Prior local evidence: 7,788 root tests passed, six known skips and 4,064
  subtests; pure branch coverage 95.54846% and combined 97.58617%; Playground
  98 passed; strict docs built 44 pages with valid anchors. Offline Ruff,
  mypy, docstring and Bandit checks passed. These are local checks, not hosted
  status for the pending PR. Keep 4.1.0 changelogs Unreleased.
- The selected f9f4eae benchmark is a local SQLite batch with changing host
  load and mixed graphql-core stacks; it is not a paired historical or
  PostgreSQL performance comparison. Historical evidence remains qualified.

## Tasks

- [x] RD-1 — Establish the approved issue and local delivery record. Create
  the issue using the actual feature-request headings, verify its identity and
  status:approved, then commit this task record as a Conventional Commit work
  unit. Record issue URL/number, approval evidence, commit and exact HEAD.
  Do not mark complete from a drafted body or from human approval alone.
  Issue: https://github.com/eamigo86/django-graphex/issues/253, author eamigo86;
  status:approved confirmed before PR creation, needs-review removed.
  Initial tracking commit: 414df951840f74cb0e475769c3e86f50683284e6.
  Structural readback and diff check passed; no executable change (RED N/A).
- [x] RD-2 — Push and open the linked, typed integration PR. Confirm the local
  candidate and push only its explicit HEAD to the retained branch under the
  authorized account/destination. Create one PR to main with a real approved
  issue reference replacing the draft placeholder; apply exactly one
  type:breaking-change label and size:exception; attach its URL to the task.
  Record pushed SHA, PR URL/number and label/readback evidence. No merge.
  Explicit-head push of 414df951840f74cb0e475769c3e86f50683284e6 succeeded
  through the authorized gh credential helper with push.followTags=false.
  PR: https://github.com/eamigo86/django-graphex/pull/254, open, non-draft,
  author eamigo86, target main, retained codex head. Closing issue #253 and
  exactly type:breaking-change plus size:exception verified on readback.
  PR attachment succeeded. This evidence is saved in the RD-2 metadata commit.
- [ ] RD-3 — Observe applicable hosted checks for that exact PR head until
  terminal. Inventory the matrix, base-install, quality/security, coverage,
  PostgreSQL, docs, Playground, artifact and PR-policy jobs that actually run.
  Record pass/fail/skip with links and collect diagnostics for failures. On a
  PR event, production publication jobs are expected to skip; a skipped
  release job is not a test pass. Do not infer CI-green from local proof or
  from incomplete checks, and do not dispatch a workflow.
- [ ] RD-4 — Close the delivery record without releasing. When checks are
  green, record the exact head, PR/issue identities, terminal check evidence,
  remaining release gates and a next-step boundary for maintainer review.
  If a check fails or access blocks monitoring, record the blocker and leave
  closure pending. Parent updates the task file and Engram mirror together;
  no merge, tag or publication follows automatically.

## Progress and next step

Issue #253 was created under eamigo86 and its status:approved label was
confirmed before PR creation: https://github.com/eamigo86/django-graphex/issues/253.
The obsolete status:needs-review label was removed under the human's explicit
approval. RD-1 and RD-2 are complete; RD-3 and RD-4 remain pending.
The CLI rejected combining --template with --body-file before making a remote
change; the successful creation used the actual template headings in the body
and existing enhancement/status labels instead. No duplicate issue was created.
PR #254 is open and attached. Initial pull-request run:
https://github.com/eamigo86/django-graphex/actions/runs/40380622029,
head 414df951840f74cb0e475769c3e86f50683284e6. Its jobs have started, not passed.
The metadata evidence update will advance the PR head; only terminal checks
for the resulting exact head can establish completion. No merge or release.
Hosted CI, release artifacts, advisory results and remote publication remain
unknown until separately observed or authorized. Rollback for this metadata
unit is this task file and its external draft bodies; no package source or
measurement data is part of the unit.
