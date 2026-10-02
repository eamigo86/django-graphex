#!/usr/bin/env bash
# Bootstrap an observed comparison profile without touching historical venvs.
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
profile="${1:?Pass a named comparison profile}"
shift
if [[ "$#" -eq 0 ]]; then
  set -- graphex graphene strawberry ariadne
fi

# Validate every requested library before creating any environment.
validator="${BENCH_PYTHON:-python3}"
constraints=()
for lib in "$@"; do
  constraints+=("$("$validator" "$HERE/profile_bootstrap.py" "$profile" "$lib" "$HERE")")
done

python="${BENCH_PYTHON:?Set BENCH_PYTHON to an existing Python 3.12.11 executable}"
cache="${BENCH_UV_CACHE_DIR:?Set BENCH_UV_CACHE_DIR to an isolated absolute path}"
root="${BENCH_PROFILE_VENV_ROOT:-$HERE}"
[[ "$python" == /* && -x "$python" ]] || { echo "BENCH_PYTHON must be an absolute executable" >&2; exit 1; }
[[ "$cache" == /* && "$root" == /* ]] || { echo "cache and venv root must be absolute" >&2; exit 1; }
[[ "$("$python" -c 'import platform; print(platform.python_version())')" == "3.12.11" ]] || {
  echo "comparison profile requires Python 3.12.11" >&2; exit 1;
}
mkdir -p "$root"
for lib in "$@"; do
  [[ ! -e "$root/.venv-$profile-$lib" ]] || {
    echo "existing profile environment will not be replaced: $lib" >&2; exit 1;
  }
  if [[ "$lib" == graphene ]]; then
    [[ -f "${BENCH_WHEEL_DIR:-}/promise-2.3-py3-none-any.whl" ]] || {
      echo "Graphene requires a verified promise 2.3 wheel in BENCH_WHEEL_DIR" >&2; exit 1;
    }
  fi
done

export UV_PYTHON_DOWNLOADS=never
uv_flags=(--no-config --cache-dir "$cache")
if [[ "${BENCH_OFFLINE:-0}" == 1 ]]; then
  uv_flags+=(--offline)
fi
stage=""
cleanup() {
  if [[ -n "$stage" && -d "$stage" ]]; then
    rm -rf "$stage"
  fi
}
trap cleanup EXIT

index=0
for lib in "$@"; do
  freeze="${constraints[$index]}"
  index=$((index + 1))
  stage="$(mktemp -d "$root/.venv-$profile-$lib.staging.XXXXXX")"
  uv "${uv_flags[@]}" venv --no-managed-python -p "$python" "$stage"
  install_args=(--index-url https://pypi.org/simple -r "$freeze")
  if [[ "$lib" == graphene ]]; then
    install_args+=(--find-links "$BENCH_WHEEL_DIR")
  fi
  uv "${uv_flags[@]}" pip install --no-build --python "$stage/bin/python" \
    "${install_args[@]}" || {
      echo "profile install failed; destination remains untouched: $lib" >&2
      exit 1
    }
  "$stage/bin/python" "$HERE/verify_freeze.py" "$freeze" "$lib" > "$stage/.freeze.txt"
  cmp -s "$freeze" "$stage/.freeze.txt" || {
    echo "installed freeze differs from observed constraints: $lib" >&2
    exit 1
  }
  uv "${uv_flags[@]}" pip check --python "$stage/bin/python"
  target="$root/.venv-$profile-$lib"
  [[ ! -e "$target" ]] || { echo "profile destination appeared during install" >&2; exit 1; }
  mv -n "$stage" "$target"
  [[ ! -e "$stage" ]] || { echo "profile promotion did not complete: $lib" >&2; exit 1; }
  stage=""
  echo "Ready: $target"
done
