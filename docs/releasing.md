# Release process

django-graphex publishes from GitHub Actions. Maintainers do not build or
upload distributions from a local checkout.

## Immutable Python distribution

The `release-artifact` job is the only release job allowed to build the
package. It produces exactly one wheel and one source distribution, then:

1. smoke-tests the installed wheel outside the source checkout;
2. audits that same prebuilt wheel's dependency closure;
3. records both files in `SHA256SUMS`; and
4. uploads the files and checksums together as `python-dist`.

The PyPI publisher and GitHub Release jobs download `python-dist`, verify
`SHA256SUMS`, and must not rebuild either distribution. The GitHub Release
attaches the wheel, source distribution, and checksum manifest that passed the
release checks.

This build-once flow means the bytes that were tested are the bytes that get
published. If a consumer job fails, rerun the workflow for the same immutable
tag; never replace an already published tag or artifact.

## Cumulative release-branch diff check

Every release run finds the shared merge base of `origin/main` and `HEAD`, then
runs `git diff --check` across that complete range. This catches whitespace
errors inherited from an earlier child PR instead of checking only the latest
slice. The gate blocks publication alongside tests, security and coverage.
