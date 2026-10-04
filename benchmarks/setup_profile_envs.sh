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

uv_flags=(--no-config --cache-dir "$cache")
if [[ "${BENCH_OFFLINE:-0}" == 1 ]]; then
  uv_flags+=(--offline)
fi
run_uv() {
  env -i PATH="$PATH" HOME="$cache" UV_PYTHON_DOWNLOADS=never \
    uv "${uv_flags[@]}" "$@"
}
owned_target=""
cleanup() {
  if [[ -n "$owned_target" && -d "$owned_target" ]]; then
    rm -rf "$owned_target"
  fi
}
trap cleanup EXIT

index=0
for lib in "$@"; do
  freeze="${constraints[$index]}"
  index=$((index + 1))
  target="$root/.venv-$profile-$lib"
  mkdir "$target" || { echo "profile destination appeared during install: $lib" >&2; exit 1; }
  owned_target="$target"
  run_uv venv --allow-existing --no-managed-python -p "$python" "$target"
  install_args=(--index-url https://pypi.org/simple -r "$freeze")
  if [[ "$lib" == graphene ]]; then
    install_args+=(--find-links "$BENCH_WHEEL_DIR")
  fi
  run_uv pip install --no-build --python "$target/bin/python" \
    "${install_args[@]}" || {
      echo "profile install failed; destination remains untouched: $lib" >&2
      exit 1
    }
  "$target/bin/python" "$HERE/verify_freeze.py" "$freeze" "$lib" > "$target/.freeze.txt"
  cmp -s "$freeze" "$target/.freeze.txt" || {
    echo "installed freeze differs from observed constraints: $lib" >&2
    exit 1
  }
  run_uv pip check --python "$target/bin/python"
  owned_target=""
  echo "Ready: $target"
done
