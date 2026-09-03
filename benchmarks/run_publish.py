"""Publish validated median benchmark artifacts from isolated raw runs."""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
import os
import re
import shutil
import statistics
import subprocess
import tempfile
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
LIBRARIES = ("graphex", "graphene", "strawberry", "ariadne")
OPERATIONS = ("flat_list", "nested", "single", "filtered", "create_comment")
EXPECTED_SURFACE = {
    "Author": ["bio", "email", "id", "name", "posts"],
    "Post": ["author", "body", "comments", "createdAt", "id", "status", "title", "viewsCount"],
    "Comment": ["authorName", "createdAt", "id", "isApproved", "text"],
}
EXPECTED_VERSIONS = {
    "graphex": {"django-graphex": "3.1.0", "django": "6.0.6", "graphql-core": "3.2.11"},
    "graphene": {"graphene-django": "3.2.3", "graphene": "3.4.3", "django": "6.0.6", "graphql-core": "3.2.11", "django-filter": "25.2"},
    "strawberry": {"strawberry-graphql-django": "0.86.4", "django": "6.0.6", "strawberry-graphql": "0.320.1", "graphql-core": "3.2.11"},
    "ariadne": {"ariadne": "1.1.0", "ariadne-django": "0.3.0", "django": "6.0.6", "graphql-core": "3.2.11"},
}
# Query capture intentionally excludes the harness's outer BEGIN/ROLLBACK. The
# GraphEx mutation owns SAVEPOINT, INSERT, deferred-FK PRAGMA and RELEASE.
EXPECTED_SQL = {
    "graphex": dict(zip(OPERATIONS, (1, 3, 1, 1, 4), strict=True)),
    "graphene": dict(zip(OPERATIONS, (2, 442, 2, 2, 1), strict=True)),
    "strawberry": dict(zip(OPERATIONS, (1, 3, 1, 1, 8), strict=True)),
    "ariadne": dict(zip(OPERATIONS, (1, 221, 2, 1, 1), strict=True)),
}
METRICS = ("mean_ms", "p50_ms", "p95_ms", "min_ms", "stddev_ms")
DELIVERY_BASE_COMMIT = "4d595f1c4822d37a520a188892a943caa744f2ea"
CANONICAL_RESULTS = {
    f"{prefix}{lib}.json": (lib, authors)
    for prefix, authors in (("", 1000), ("2x_", 2000))
    for lib in LIBRARIES
}
PROVENANCE_FIELDS = {
    "commit": 40,
    "measurement_tree": 40,
    "delivery_base_commit": 40,
    "constraints_sha256": 64,
}


def _validate_runs(lib: str, runs: list[dict], authors: int) -> None:
    assert len(runs) >= 3 and len(runs) % 2 == 1, "publication needs an odd run count >= 3"
    stable = ("versions", "python", "django", "machine", "dataset", "provenance", "surface")
    for run in runs:
        assert run["lib"] == lib
        assert run["versions"] == EXPECTED_VERSIONS[lib], f"version contract drift: {lib}"
        assert run["surface"] == EXPECTED_SURFACE, f"surface contract drift: {lib}"
        assert run["dataset"] == {
            "authors": authors,
            "posts_per_author": 10,
            "comments_per_post": 5,
        }, f"dataset/cardinality contract drift: {lib}"
        assert set(run["ops"]) == set(OPERATIONS), f"operation contract drift: {lib}"
        for operation, expected in EXPECTED_SQL[lib].items():
            stats = run["ops"][operation]
            assert stats["sql_queries"] == expected, f"SQL contract drift: {lib}.{operation}"
            assert stats["iterations"] == 100
    for key in stable:
        assert all(run[key] == runs[0][key] for run in runs), f"unstable {key}: {lib}"


def validate_canonical_results(
    results_dir: Path = BASE_DIR / "results",
    *,
    constraints_path: Path = BASE_DIR / "constraints.txt",
    repo_root: Path = BASE_DIR.parent,
) -> None:
    """Validate tracked medians without resolving the local measurement commit.

    Args:
        results_dir: Directory containing the eight canonical JSON artifacts.
        constraints_path: Dependency freeze used by the recorded measurements.
        repo_root: Full-history Git checkout used for delivery ancestry checks.

    Raises:
        AssertionError: A result, provenance field, freeze, or ancestry check failed.
    """
    paths = {path.name: path for path in results_dir.glob("*.json")}
    assert set(paths) == set(CANONICAL_RESULTS), (
        "canonical results must contain exactly eight expected artifacts"
    )

    artifacts = []
    for name, (lib, authors) in CANONICAL_RESULTS.items():
        artifact = json.loads(paths[name].read_text())
        _validate_runs(lib, [artifact] * 3, authors)
        assert artifact.get("aggregation", {}).get("runs") == 3, (
            f"three-run aggregation contract drift: {name}"
        )
        artifacts.append(artifact)

    provenance = artifacts[0]["provenance"]
    assert all(item["provenance"] == provenance for item in artifacts), (
        "canonical artifacts must share one provenance"
    )
    assert set(provenance) == set(PROVENANCE_FIELDS), (
        "canonical provenance fields do not match the contract"
    )
    for field, length in PROVENANCE_FIELDS.items():
        assert re.fullmatch(rf"[0-9a-f]{{{length}}}", provenance[field]), (
            f"{field} must be a full lowercase hexadecimal SHA"
        )

    digest = hashlib.sha256(constraints_path.read_bytes()).hexdigest()
    assert provenance["constraints_sha256"] == digest, (
        "canonical constraints digest does not match constraints.txt"
    )
    delivery_base = provenance["delivery_base_commit"]
    assert delivery_base == DELIVERY_BASE_COMMIT, (
        "canonical artifacts do not name the approved public delivery base"
    )

    checks = (
        (["git", "cat-file", "-e", f"{delivery_base}^{{commit}}"], "does not exist"),
        (
            ["git", "merge-base", "--is-ancestor", delivery_base, "HEAD"],
            "is not an ancestor of HEAD",
        ),
    )
    for command, failure in checks:
        result = subprocess.run(
            command, cwd=repo_root, text=True, capture_output=True, check=False
        )
        assert result.returncode == 0, f"public delivery base {failure}"


def _aggregate_runs(lib: str, runs: list[dict], *, authors: int) -> dict:
    _validate_runs(lib, runs, authors)
    ordered = sorted(runs, key=lambda run: run["schema_import_ms"])
    result = copy.deepcopy(ordered[len(ordered) // 2])
    imports = [run["schema_import_ms"] for run in runs]
    result["schema_import_ms"] = round(statistics.median(imports), 4)
    for operation in OPERATIONS:
        for metric in METRICS:
            values = [run["ops"][operation][metric] for run in runs]
            result["ops"][operation][metric] = round(statistics.median(values), 4)
    result["aggregation"] = {"runs": len(runs), "ops": "median across runs of each timing statistic", "schema_import_ms": {"reported": "median", "samples": sorted(imports)}, "schema_rebuild_samples_ms": {"reported": "middle import run's raw series"}}
    return result


def _publish(datasets: dict[str, dict[str, list[dict]]], results_dir: Path) -> None:
    assert set(datasets) == {"", "2x_"}
    outputs = {}
    for prefix, authors in (("", 1000), ("2x_", 2000)):
        assert set(datasets[prefix]) == set(LIBRARIES)
        for lib in LIBRARIES:
            outputs[f"{prefix}{lib}.json"] = _aggregate_runs(
                lib, datasets[prefix][lib], authors=authors
            )
    provenance = {json.dumps(value["provenance"], sort_keys=True) for value in outputs.values()}
    assert len(provenance) == 1, "runs do not share one source/constraints provenance"

    results_dir.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=results_dir.parent) as staging:
        stage = Path(staging)
        for name, output in outputs.items():
            (stage / name).write_text(json.dumps(output, indent=2))
        for name in outputs:
            os.replace(stage / name, results_dir / name)


def _run(command: list[str], *, env: dict | None = None) -> None:
    subprocess.run(command, cwd=BASE_DIR, env=env, check=True)


def _prepare_database(authors: int) -> None:
    (BASE_DIR / "db.sqlite3").unlink(missing_ok=True)
    shutil.rmtree(BASE_DIR / "benchapp" / "migrations", ignore_errors=True)
    python = str(BASE_DIR / ".venv-graphex" / "bin" / "python")
    env = {**os.environ, "BENCH_LIB": "graphex", "DJANGO_SETTINGS_MODULE": "config.settings"}
    _run([python, "-m", "django", "makemigrations", "benchapp"], env=env)
    _run([python, "-m", "django", "migrate", "--run-syncdb"], env=env)
    _run([python, "-m", "django", "seed_bench", "--authors", str(authors)], env=env)


def _rotated_libraries(run_index: int) -> tuple[str, ...]:
    shift = run_index % len(LIBRARIES)
    return LIBRARIES[shift:] + LIBRARIES[:shift]


def _warm_environments() -> None:
    for lib in LIBRARIES:
        python = str(BASE_DIR / f".venv-{lib}" / "bin" / "python")
        env = {**os.environ, "BENCH_LIB": lib, "DJANGO_SETTINGS_MODULE": "config.settings"}
        code = (
            "import django, importlib; django.setup(); "
            f"importlib.import_module('libs.{lib}.bench_schema')"
        )
        _run([python, "-c", code], env=env)


def _measure(authors: int, runs: int, scratch: Path) -> dict[str, list[dict]]:
    _prepare_database(authors)
    _warm_environments()
    measured = {lib: [] for lib in LIBRARIES}
    for run_index in range(runs):
        for lib in _rotated_libraries(run_index):
            output_dir = scratch / str(authors) / f"run-{run_index + 1}"
            env = {
                **os.environ,
                "BENCH_LIB": lib,
                "BENCH_AUTHORS": str(authors),
                "BENCH_OUTPUT_DIR": str(output_dir),
                "DJANGO_SETTINGS_MODULE": "config.settings",
            }
            python = str(BASE_DIR / f".venv-{lib}" / "bin" / "python")
            _run([python, str(BASE_DIR / "harness.py")], env=env)
            measured[lib].append(json.loads((output_dir / f"{lib}.json").read_text()))
    return measured


def main() -> None:
    """Measure both canonical datasets and publish validated medians."""
    parser = argparse.ArgumentParser()
    parser.add_argument("--authors", type=int, nargs="+", default=[1000, 2000])
    parser.add_argument("--runs", type=int, default=3)
    parser.add_argument("--validate-existing", action="store_true")
    args = parser.parse_args()
    if args.validate_existing:
        validate_canonical_results()
        return
    if set(args.authors) != {1000, 2000} or args.runs < 3 or args.runs % 2 == 0:
        parser.error("canonical publication requires authors 1000 2000 and an odd runs >= 3")
    scratch = BASE_DIR / "scratch" / "publish"
    shutil.rmtree(scratch, ignore_errors=True)
    datasets = {("" if authors == 1000 else "2x_"): _measure(authors, args.runs, scratch) for authors in args.authors}
    _publish(datasets, BASE_DIR / "results")


if __name__ == "__main__":
    main()
