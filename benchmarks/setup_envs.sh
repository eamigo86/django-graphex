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
if [[ "${1:-}" == "--profile" ]]; then
  shift
  exec bash "$HERE/setup_profile_envs.sh" "$@"
fi
CONSTRAINTS="$HERE/constraints.txt"
# shellcheck source=versions.env
source "$HERE/versions.env"

UV_FLAGS=(--no-config)
export UV_PYTHON_DOWNLOADS=never
if [[ "${BENCH_OFFLINE:-0}" == "1" ]]; then
  UV_FLAGS+=(--offline)
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
  local target="$3"
  "$python" "$HERE/verify_freeze.py" "$CONSTRAINTS" "$lib" \
    >"$target/.freeze.txt"
}

make_venv() {
  local lib="$1"
  local venv="$HERE/.venv-$lib"
  echo
  echo "=== Setting up $lib -> $venv ==="
  mkdir -- "$venv"
  owned_targets+=("$venv")
  uv venv -p "$PYTHON_VERSION" --allow-existing "$venv"

  case "$lib" in
    graphex)
      install_pinned "$venv/bin/python" "Django==$DJANGO_VERSION" \
        "channels==$CHANNELS_VERSION" "django-graphex==3.1.0"
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
  esac

  write_verified_freeze "$lib" "$venv/bin/python" "$venv"
}

if [[ "$#" -eq 0 ]]; then
  LIBS=(graphex graphene strawberry ariadne)
else
  LIBS=("$@")
fi

# Validate the whole request before reserving or installing any environment.
requested=("")
for lib in "${LIBS[@]}"; do
  case "$lib" in
    graphex|graphene|strawberry|ariadne) ;;
    *) echo "Unknown lib: $lib" >&2; exit 1 ;;
  esac
  for previous in "${requested[@]}"; do
    [[ "$previous" != "$lib" ]] || {
      echo "Duplicate library requested: $lib" >&2; exit 1;
    }
  done
  requested+=("$lib")
  target="$HERE/.venv-$lib"
  [[ ! -e "$target" && ! -L "$target" ]] || {
    echo "Existing legacy environment will not be replaced: $target" >&2; exit 1;
  }
done

owned_targets=("")
completed=0
cleanup() {
  if [[ "$completed" -eq 0 ]]; then
    for target in "${owned_targets[@]}"; do
      [[ -n "$target" ]] || continue
      [[ ! -L "$target" ]] && rm -rf -- "$target"
    done
  fi
}
trap cleanup EXIT

for lib in "${LIBS[@]}"; do
  make_venv "$lib"
done

# Do not alter previous freeze artifacts unless the whole request succeeded.
for lib in "${LIBS[@]}"; do
  cp -- "$HERE/.venv-$lib/.freeze.txt" "$HERE/.freeze-$lib.txt"
  echo "--- Installed versions in $lib venv ---"
  cat "$HERE/.freeze-$lib.txt"
done
completed=1

echo
echo ">> All requested environments ready."
