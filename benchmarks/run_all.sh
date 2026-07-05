#!/usr/bin/env bash
# Full benchmark run: seed ONCE against a fresh DB, then run every library's
# harness sequentially in its own venv.
#
# The database is built + seeded using the graphex venv (any venv works — the
# models are library-agnostic — but graphex is guaranteed to exist first).
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$HERE"

GRAPHEX_PY="$HERE/.venv-graphex/bin/python"
LIBS=("${@:-graphex graphene strawberry ariadne}")

echo ">> Fresh database"
rm -f "$HERE/db.sqlite3"
rm -rf "$HERE/benchapp/migrations"

echo ">> makemigrations + migrate (graphex venv, BENCH_LIB=graphex)"
BENCH_LIB=graphex DJANGO_SETTINGS_MODULE=config.settings \
  "$GRAPHEX_PY" -m django makemigrations benchapp
BENCH_LIB=graphex DJANGO_SETTINGS_MODULE=config.settings \
  "$GRAPHEX_PY" -m django migrate --run-syncdb

echo ">> Seeding (this should take well under 2 minutes)"
time BENCH_LIB=graphex DJANGO_SETTINGS_MODULE=config.settings \
  "$GRAPHEX_PY" -m django seed_bench

mkdir -p "$HERE/results"

# shellcheck disable=SC2068
for lib in ${LIBS[@]}; do
  venv_py="$HERE/.venv-$lib/bin/python"
  if [[ ! -x "$venv_py" ]]; then
    echo ">> SKIP $lib (no venv at $venv_py — run ./setup_envs.sh $lib)"
    continue
  fi
  echo
  echo "=== Running harness for $lib ==="
  BENCH_LIB="$lib" DJANGO_SETTINGS_MODULE=config.settings "$venv_py" harness.py
done

echo
echo ">> Done. Results in $HERE/results/"
