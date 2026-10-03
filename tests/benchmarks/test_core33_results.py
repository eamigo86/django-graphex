"""Frozen contracts for the published core33 comparison artifacts."""

from __future__ import annotations

import hashlib
import json
import math
import re
from pathlib import Path

import pytest

RESULTS = Path(__file__).resolve().parents[2] / "benchmarks/results/core33"
LIBRARIES = ("graphex", "graphene", "strawberry", "ariadne")
FILENAMES = {
    (authors, library): f"{'2x_' if authors == 2000 else ''}{library}.json"
    for authors in (1000, 2000)
    for library in LIBRARIES
}
SOURCE = {
    "commit": "350ae84256fdad1b1a98a6e0bef8d0f63609257f",
    "tree": "0afc136997b01b281c2a9f6c11cf062708b718ef",
    "version": "3.1.1",
    "manifest_sha256": "0cbad15a165506a61cb18c1a5da44750accbfe8a23e3aa99070145b33d5c3957",
}
SEED_SHA256 = {
    1000: "a09f140458ef6a53b39f2bf5ab2ba4027962b5257a24b6d19aee44f97d3bc4d7",
    2000: "3d68cdc6a18a3f20e998e37a73584558d85379eb004d09caba37e73c4634b0d1",
}
SEED_SOURCE = {
    "commit": "1b5b941e2555a5bffee8a109ee0a32fdef1258fd",
    "tree": "ebc8872c6660c355c460238be37c2047a922f28d",
}
VERSIONS = {
    "graphex": {"django-graphex": "3.1.1", "django": "6.0.8", "graphql-core": "3.3.0"},
    "graphene": {
        "graphene-django": "3.2.3",
        "graphene": "3.4.3",
        "django": "6.0.8",
        "graphql-core": "3.2.13",
        "django-filter": "25.2",
    },
    "strawberry": {
        "strawberry-graphql-django": "0.90.0",
        "django": "6.0.8",
        "strawberry-graphql": "0.328.0",
        "graphql-core": "3.3.0",
    },
    "ariadne": {
        "ariadne": "1.1.0",
        "ariadne-django": "0.3.0",
        "django": "6.0.8",
        "graphql-core": "3.2.13",
    },
}
SQL_QUERIES = {
    "graphex": (1, 3, 1, 1, 4),
    "graphene": (2, 442, 2, 2, 1),
    "strawberry": (1, 3, 1, 1, 8),
    "ariadne": (1, 221, 2, 1, 1),
}
OPERATIONS = ("flat_list", "nested", "single", "filtered", "create_comment")
TIMING_STATS = ("mean_ms", "p50_ms", "p95_ms", "min_ms", "stddev_ms")
SURFACE = {
    "Author": ["bio", "email", "id", "name", "posts"],
    "Post": [
        "author",
        "body",
        "comments",
        "createdAt",
        "id",
        "status",
        "title",
        "viewsCount",
    ],
    "Comment": ["authorName", "createdAt", "id", "isApproved", "text"],
}
AGGREGATION = {
    "runs": 3,
    "method": "per-statistic median of three validated raw runs",
    "ops": "median of each per-run statistic; per-run p95 is not pooled p95",
    "schema_rebuild_samples_ms": (
        "per-position median of five diagnostic rebuild samples; not a raw run series"
    ),
}
PUBLIC_KEYS = {
    "schema",
    "profile",
    "library",
    "dataset",
    "whole_stack",
    "machine",
    "surface",
    "operations",
    "schema_import_ms",
    "schema_rebuild_diagnostic_ms",
    "aggregation",
    "measurement_source",
    "seed_source",
    "raw_sha256",
}

# Frozen before publication from the accepted batch-result and raw manifest.
# Each numeric digest covers all 31 per-file medians plus SQL and iteration fields.
CONSTRAINTS_SHA256 = {
    "ariadne": "3d35ad223f318ea66cff2f5a274c49cea06a0d04fa60b0e8b8847f69919f85ab",
    "graphene": "007523a3e7b626a3480f9b31a8dc88e77e3a163b924cdfbf7f49bb00266335d6",
    "graphex": "031a6c39d018bc60814d178adf42e7d81e2d1f78c20571916395901ca251a177",
    "strawberry": "be829227a4f47c2b822c1160b32147e9c611a68870bfc62e7a20fc8ee36a0947",
}
NUMERIC_SHA256 = {
    "2x_ariadne.json": "bc3d1fa9455c4108567e6eba6dfb538ca33499d5e2ff34d86f21aadb321dd9b8",
    "2x_graphene.json": "e40a06236d45bc3bf6d09998247978c37f25dcf3cc7a5a0129281cfc4fce84fe",
    "2x_graphex.json": "998cf98ad234b1d90141b70f0c765bfc08f4e9df31131ee2175859adda4e014f",
    "2x_strawberry.json": "13fd09470736c384d59496db3521a54fb298bb1613bdad75f27c768dc5afa47f",
    "ariadne.json": "6476e3cd84314872136176d2f78bf91b27fc48f9a6f0a56762a476b05eeac483",
    "graphene.json": "3ce87856fbdad2d94392be9497c6f27f86b83a803f8aa9fc727159ef4f23979c",
    "graphex.json": "665a2a9243dddfc5d8dd8f80350be4f58e98e04eb2481837f4c8503fd8d1e892",
    "strawberry.json": "bb298e798dc685c5914937fa8f979d99f7999f2283ff57a7c40763996172e42c",
}
RAW_SHA256 = {
    "2x_ariadne.json": (
        "44fc4266ab0fae37bbd0415f04dbcd9ee5601b7cf1e849c658b2b7a57a3969fe",
        "01a46c48739b251179f4ec700c5305fa3642f12711ec3613f5285a45f9781079",
        "133f1954c7f250e12cb246ebe50dd327a133ca5899b2d8d0992cf98c0cd6f4b4",
    ),
    "2x_graphene.json": (
        "28031273c0469752dbf409fd7fc0713da71da52e8954bb95c684e96cb1831b9f",
        "b89ef0d234a31a8b8baa7fa16d09c32344ca799b6dcb9a371da32eef5fa62d79",
        "d50e9ef392b5ed3fe75761b4bed5938d44846793d10de6a48680f29c80dd2a87",
    ),
    "2x_graphex.json": (
        "bbdb8252530b5c2509fef0084cc641cfb0d6409736a31acbd3429cc8286f1c7d",
        "6a134a86a6b8aeb461003077e845a94bf3316ae2abeac3a32b221257ff0fe3f6",
        "d70bdfbf60d308a4dfb20c6d849e40b79fd41677f10aaa9cfa9247a80b92cdd9",
    ),
    "2x_strawberry.json": (
        "33267856e02cefacc6a8862fc778c4d463797e07948e9d25f96b236be87eb0e2",
        "f7e2fe3c1ac84ccd48d86a3596bc4ed778dc08d7ad089491d5ba9c2c70399b6c",
        "779840214d612b2af73e350574f41eb73e8b9eada61e241d75fffe4833b16271",
    ),
    "ariadne.json": (
        "b5986b66c635d961d7e8023962211069cb58c2a89dcb5c7b775cd2f62c3ba6d9",
        "88ee26b1b7d13e6b1d77d75ab6df492c52d6fd65f8d8e3566c8932930e8e03dd",
        "3f39c748d42b52be19feb356130e9dc1cec8b05b6a12a06981ef35bacb192065",
    ),
    "graphene.json": (
        "3b0b447cc4151ec48889508eb195704a8205b5a4919f3563274f6a91ae2296b3",
        "4595e3054df59ad6e0835ef24cdcd64b0f7a05a9a8fe53639b4116351412f42d",
        "7d30494b7b71dc732338a9756017e502fde07b168a21deecde7cebf74c6796ee",
    ),
    "graphex.json": (
        "98f54623633f5aa1d9a6c32bdd942dc980bfe8a6071565bd606af8284ab5b88a",
        "46b1b503fa3f4d9c3698c22dc26067cb3a9633669b4c7d94fdd734514e893004",
        "0ca1ab1b79e4eeaa4431078a4a3adc40c62d51a878dde2dec7f2a99cc6bd4da2",
    ),
    "strawberry.json": (
        "2003bc643ed120163df4c4016b54789c1bcd5d785cacb6a7c6c8d452f156a4fd",
        "0c6b797688363d82287165f274f0f3eb5ffc21af6c48559d48ad9cce9a0b8f78",
        "41060bd175adbdd27b90e6f0a11c636bf6bc3f6c4687b5544991616cd069d863",
    ),
}


def test_core33_bundle_has_exactly_eight_portable_artifacts() -> None:
    """Require one complete bundle and 24 distinct raw-result digests.

    Raises:
        AssertionError: If the bundle is absent, incomplete, or duplicates raw runs.
    """
    assert RESULTS.is_dir()
    assert {path.name for path in RESULTS.iterdir()} == set(FILENAMES.values())
    assert all(path.is_file() and not path.is_symlink() for path in RESULTS.iterdir())
    raw_digests = [
        digest
        for path in RESULTS.iterdir()
        for digest in json.loads(path.read_bytes())["raw_sha256"]
    ]
    assert len(raw_digests) == len(set(raw_digests)) == 24


@pytest.mark.parametrize(("authors", "library"), FILENAMES)
def test_core33_artifact_matches_accepted_portable_contract(
    authors: int, library: str
) -> None:
    """Bind every public field and 31 medians to the accepted measured batch.

    Args:
        authors: Published author cardinality.
        library: Named whole-stack backend.

    Raises:
        AssertionError: If content or provenance drifts from the accepted batch.
    """
    name = FILENAMES[(authors, library)]
    data = (RESULTS / name).read_bytes()
    assert data.endswith(b"\n")
    artifact = json.loads(data)
    assert set(artifact) == PUBLIC_KEYS
    assert artifact["schema"] == "django-graphex.core33.comparison.v1"
    assert artifact["profile"] == "core33"
    assert artifact["library"] == library
    assert artifact["dataset"] == {
        "authors": authors,
        "posts_per_author": 10,
        "comments_per_post": 5,
    }
    assert artifact["whole_stack"] == {
        "versions": VERSIONS[library],
        "python": "3.12.11",
        "django": "6.0.8",
    }
    assert artifact["machine"] == {
        "platform": "macOS-27.0.1-arm64-arm-64bit",
        "cpu_count": 16,
    }
    assert artifact["surface"] == SURFACE
    assert artifact["aggregation"] == AGGREGATION
    assert artifact["measurement_source"] == {
        **SOURCE,
        "constraints_sha256": CONSTRAINTS_SHA256[library],
    }
    assert artifact["seed_source"] == {
        **SEED_SOURCE,
        "sha256": SEED_SHA256[authors],
    }
    assert tuple(artifact["raw_sha256"]) == RAW_SHA256[name]
    assert all(re.fullmatch(r"[0-9a-f]{64}", digest) for digest in RAW_SHA256[name])

    operations = artifact["operations"]
    assert set(operations) == set(OPERATIONS)
    for operation, sql in zip(OPERATIONS, SQL_QUERIES[library], strict=True):
        result = operations[operation]
        assert set(result) == {*TIMING_STATS, "iterations", "sql_queries"}
        assert result["iterations"] == 100
        assert result["sql_queries"] == sql
        assert all(
            type(result[stat]) in (int, float)
            and math.isfinite(result[stat])
            and result[stat] >= 0
            for stat in TIMING_STATS
        )
    assert len(artifact["schema_rebuild_diagnostic_ms"]) == 5
    assert all(
        type(value) in (int, float) and math.isfinite(value) and value >= 0
        for value in artifact["schema_rebuild_diagnostic_ms"]
    )
    assert type(artifact["schema_import_ms"]) in (int, float)
    assert math.isfinite(artifact["schema_import_ms"])
    assert artifact["schema_import_ms"] >= 0

    numeric_projection = {
        "operations": operations,
        "schema_import_ms": artifact["schema_import_ms"],
        "schema_rebuild_diagnostic_ms": artifact["schema_rebuild_diagnostic_ms"],
    }
    numeric_bytes = json.dumps(
        numeric_projection, sort_keys=True, separators=(",", ":")
    ).encode()
    assert hashlib.sha256(numeric_bytes).hexdigest() == NUMERIC_SHA256[name]

    rendered = data.decode()
    for private_marker in (
        "/Users/",
        "/home/",
        ".codex",
        ".venv",
        "site-packages",
        "db.sqlite3",
        "output_root",
        "backend_path",
        "schema_path",
        "hostname",
        "raw_path",
    ):
        assert private_marker not in rendered
    assert not any(value.startswith(("/", "\\")) for value in _all_strings(artifact))


def _all_strings(value: object) -> list[str]:
    """Collect nested text for portable-path checks.

    Args:
        value: Nested JSON value.

    Returns:
        All string values, including dictionary keys.
    """
    if isinstance(value, str):
        return [value]
    if isinstance(value, list):
        return [text for item in value for text in _all_strings(item)]
    if isinstance(value, dict):
        return [
            text
            for key, item in value.items()
            for text in [*_all_strings(key), *_all_strings(item)]
        ]
    return []
