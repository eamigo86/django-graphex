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

# Warm EVERY virtualenv equally before measuring any of them. The seeding above
# runs under the graphex interpreter, which leaves graphex's imports and file
# cache hot while the others are still cold -- and ``schema_import_ms`` is a
# cold-import measurement, so that alone put a bias in graphex's favour on the
# one row where the libraries are closest. One throwaway import each removes it.
echo ">> Warming every virtualenv (removes the cold-import bias)"
# shellcheck disable=SC2068
for lib in ${LIBS[@]}; do
  venv_py="$HERE/.venv-$lib/bin/python"
  [[ -x "$venv_py" ]] || continue
  BENCH_LIB="$lib" DJANGO_SETTINGS_MODULE=config.settings "$venv_py" -c "
import django, sys
sys.path.insert(0, '$HERE')
django.setup()
import importlib
importlib.import_module('libs.$lib.bench_schema')
" >/dev/null 2>&1 || echo "   (warmup for $lib failed; it will be measured cold)"
done

# shellcheck disable=SC2068
for lib in ${LIBS[@]}; do
  venv_py="$HERE/.venv-$lib/bin/python"
  if [[ ! -x "$venv_py" ]]; then
    echo ">> SKIP $lib (no venv at $venv_py — run ./setup_envs.sh $lib)"
    continue
  fi
  echo
  echo "=== Running harness for $lib ==="
  BENCH_LIB="$lib" BENCH_AUTHORS=1000 \
    BENCH_OUTPUT_DIR="$HERE/scratch/run_all" \
    DJANGO_SETTINGS_MODULE=config.settings "$venv_py" harness.py
done

echo
echo ">> Done. Diagnostic results in $HERE/scratch/run_all/"
