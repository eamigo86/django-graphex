#!/usr/bin/env bash
# Create one isolated virtualenv per benchmarked library.
#
# Fairness rule enforced here: every direct and transitive package is pinned to
# the freeze that produced the canonical artifacts. BENCH_OFFLINE=1 forbids
# network access and succeeds only when uv's local cache is complete.
#
# Usage:
#   ./setup_envs.sh            # set up all four libraries
#   ./setup_envs.sh graphex    # set up only one
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$HERE/.." && pwd)"
CONSTRAINTS="$HERE/constraints.txt"
# shellcheck source=versions.env
source "$HERE/versions.env"

UV_FLAGS=()
if [[ "${BENCH_OFFLINE:-0}" == "1" ]]; then
  UV_FLAGS+=(--offline)
  export UV_PYTHON_DOWNLOADS=never
  echo ">> Offline replay: uv may use its local cache only"
fi

install_pinned() {
  local python="$1"
  shift
  if ! uv pip install "${UV_FLAGS[@]}" --python "$python" \
      --constraint "$CONSTRAINTS" "$@"; then
    if [[ "${BENCH_OFFLINE:-0}" == "1" ]]; then
      echo "ERROR: offline benchmark cache is incomplete; no network fallback allowed" >&2
    fi
    return 1
  fi
}

write_verified_freeze() {
  local lib="$1"
  local python="$2"
  "$python" "$HERE/verify_freeze.py" "$CONSTRAINTS" "$lib" \
    >"$HERE/.freeze-$lib.txt"
}

make_venv() {
  local lib="$1"
  local venv="$HERE/.venv-$lib"
  echo
  echo "=== Setting up $lib -> $venv ==="
  rm -rf "$venv"
  uv venv -p "$PYTHON_VERSION" "$venv"

  case "$lib" in
    graphex)
      install_pinned "$venv/bin/python" "Django==$DJANGO_VERSION" \
        "channels==$CHANNELS_VERSION" -e "$REPO_ROOT"
      ;;
    graphene)
      install_pinned "$venv/bin/python" "Django==$DJANGO_VERSION" \
        "graphene-django==$GRAPHENE_DJANGO_VERSION" \
        "django-filter==$DJANGO_FILTER_VERSION"
      ;;
    strawberry)
      install_pinned "$venv/bin/python" "Django==$DJANGO_VERSION" \
        "strawberry-graphql-django==$STRAWBERRY_DJANGO_VERSION" \
        "strawberry-graphql==$STRAWBERRY_VERSION"
      ;;
    ariadne)
      install_pinned "$venv/bin/python" "Django==$DJANGO_VERSION" \
        "ariadne==$ARIADNE_VERSION" \
        "ariadne-django==$ARIADNE_DJANGO_VERSION"
      ;;
    *)
      echo "Unknown lib: $lib" >&2
      exit 1
      ;;
  esac

  write_verified_freeze "$lib" "$venv/bin/python"
  echo "--- Installed versions in $lib venv ---"
  cat "$HERE/.freeze-$lib.txt"
}

LIBS=("${@:-graphex graphene strawberry ariadne}")
# shellcheck disable=SC2068
for lib in ${LIBS[@]}; do
  make_venv "$lib"
done

echo
echo ">> All requested environments ready."
