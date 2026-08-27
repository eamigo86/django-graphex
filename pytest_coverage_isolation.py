# -*- coding: utf-8 -*-
"""Give each pytest process its own coverage data-file directory.

"pytest-cov" collects into a per-process suffixed file and then COMBINES every
sibling file sitting next to the configured data file before it reports. The
data file defaulted to ".coverage" in the repo root, which makes a second run in
the same checkout a sibling: each run sweeps up -- and deletes -- the other's
partials, so the loser of the race reports the winner's totals and then
"Total coverage: 0.00%" and exits 1, with 4120 tests passing above it. Any
concurrent verification of this repository was therefore unreliable, and the
failure reads exactly like a real coverage regression.

Moving the data file into a directory named after the process id shrinks the
combine sweep to that process's own partials. Only the DATA file moves:
"coverage.xml" stays at the repo root because CI uploads it from there.

This has to run before "pytest-cov" constructs its Coverage object, and it does
that from a "tryfirst" "pytest_load_initial_conftests" hook -- which fires
BEFORE any conftest is imported. A "-p" plugin named in
"[tool.pytest.ini_options] addopts" is loaded earlier still, during
"Config._preparse", so this module is wired that way rather than as a conftest.
It defines no hooks; importing it is the whole job.
"""

from __future__ import annotations

import atexit
import os
import shutil
import tempfile
from typing import MutableMapping

#: Env var stamping the process id that minted "COVERAGE_FILE". Env vars are
#: inherited across "subprocess", so a nested pytest run would otherwise write
#: into its parent's directory -- the very collision, one level down. The stamp
#: is what tells an INHERITED value (replace it) from an operator's own
#: deliberate "COVERAGE_FILE" (leave it alone).
OWNER_ENV = "GDX_COVERAGE_FILE_OWNER"


def isolate_coverage_data_file(
    environ: MutableMapping[str, str], pid: int
) -> str | None:
    """Point "COVERAGE_FILE" at a directory belonging to one process.

    Args:
        environ: The environment to read and rewrite, normally "os.environ".
        pid: The id of the process the data file should belong to.

    Returns:
        The data-file path this process owns, or "None" when an operator set
        "COVERAGE_FILE" themselves and it was left untouched.
    """
    if "COVERAGE_FILE" in environ and OWNER_ENV not in environ:
        return None
    if environ.get(OWNER_ENV) == str(pid):
        return environ["COVERAGE_FILE"]

    directory = os.path.join(tempfile.gettempdir(), f"django-graphex-coverage-{pid}")
    os.makedirs(directory, exist_ok=True)
    environ["COVERAGE_FILE"] = os.path.join(directory, ".coverage")
    environ[OWNER_ENV] = str(pid)
    # The report is written from the data file, so the directory has to outlive
    # the whole session -- atexit is the first point at which it is spent.
    atexit.register(shutil.rmtree, directory, True)
    return environ["COVERAGE_FILE"]


isolate_coverage_data_file(os.environ, os.getpid())
