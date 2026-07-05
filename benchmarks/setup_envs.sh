#!/usr/bin/env bash
# Create one isolated virtualenv per benchmarked library.
#
# Fairness rule enforced here: EVERY venv pins the SAME Django version — read
# straight from the repo's own .venv so all four libraries run on identical
# Django. Python is pinned to 3.12 (uv venv -p 3.12) to match the repo venv.
#
# Usage:
#   ./setup_envs.sh            # set up all four libraries
#   ./setup_envs.sh graphex    # set up only one
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$HERE/.." && pwd)"
PYVER="3.12"

# The single Django version every venv pins, read from the repo's own venv.
DJANGO_VERSION="$("$REPO_ROOT/.venv/bin/python" -c 'import django; print(django.__version__)')"
echo ">> Pinning Django==$DJANGO_VERSION (from repo .venv) on Python $PYVER for every library"

make_venv() {
  local lib="$1"
  local venv="$HERE/.venv-$lib"
  echo
  echo "=== Setting up $lib -> $venv ==="
  uv venv -p "$PYVER" "$venv"
  # Common baseline: identical Django in every venv.
  uv pip install --python "$venv/bin/python" "Django==$DJANGO_VERSION"

  case "$lib" in
    graphex)
      # Local editable install of django-graphex v2. channels is added because
      # django_graphex.apps.ready() may touch the subscriptions package on
      # app load; installing it keeps the app import clean.
      uv pip install --python "$venv/bin/python" -e "$REPO_ROOT"
      uv pip install --python "$venv/bin/python" channels || true
      ;;
    graphene)
      uv pip install --python "$venv/bin/python" graphene-django
      ;;
    strawberry)
      uv pip install --python "$venv/bin/python" strawberry-graphql-django
      ;;
    ariadne)
      uv pip install --python "$venv/bin/python" ariadne
      # Optional Django integration package; skip silently if it fails to install.
      uv pip install --python "$venv/bin/python" ariadne-django \
        || echo "   (ariadne-django not installed; ariadne bench_schema will wire the view by hand)"
      ;;
    *)
      echo "Unknown lib: $lib" >&2
      exit 1
      ;;
  esac

  echo "--- Installed versions in $lib venv ---"
  "$venv/bin/python" -c 'import django; print("django", django.__version__)'
  case "$lib" in
    graphex)    "$venv/bin/python" -c 'from importlib.metadata import version; print("django-graphex", version("django-graphex"))' ;;
    graphene)   "$venv/bin/python" -c 'from importlib.metadata import version; print("graphene-django", version("graphene-django"))' ;;
    strawberry) "$venv/bin/python" -c 'from importlib.metadata import version; print("strawberry-graphql-django", version("strawberry-graphql-django"))' ;;
    ariadne)    "$venv/bin/python" -c 'from importlib.metadata import version; print("ariadne", version("ariadne"))' ;;
  esac
}

LIBS=("${@:-graphex graphene strawberry ariadne}")
# shellcheck disable=SC2068
for lib in ${LIBS[@]}; do
  make_venv "$lib"
done

echo
echo ">> All requested environments ready."
