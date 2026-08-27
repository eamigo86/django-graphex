# -*- coding: utf-8 -*-
"""Two pytest runs in one checkout must not share a coverage data file.

"pytest-cov" collects into a per-process suffixed file and then COMBINES every
sibling file next to the configured data file before it reports. With the data
file at the repo root, a second run in the same checkout is a sibling: each run
sweeps up -- and deletes -- the other's partial data, so a full suite that
passed 4120 tests reports another run's totals and then "Total coverage: 0.00%"
and exits 1.

The failure is silent about its cause and lands on whichever run loses the
race, which makes any concurrent verification of this repository unreliable and
reads exactly like a real coverage regression.

The fix is to give each process its own data-file DIRECTORY, so the combine
sweep can only find that process's own partials. It has to happen before
"pytest-cov" constructs its Coverage object, which it does from a "tryfirst"
"pytest_load_initial_conftests" hook -- earlier than any conftest -- so it lives
in a "-p" plugin module named in "addopts" instead.

Two rules are pinned here:

  - the data file this process writes is under a directory carrying this
    process's own id, and never the repo root;
  - a CHILD process does not inherit the parent's data file. Env vars cross
    "subprocess" boundaries, so an inherited value would put a nested pytest run
    right back in the parent's directory -- which is the very collision, one
    level down.
"""

from __future__ import annotations

import os
from pathlib import Path

from pytest_coverage_isolation import OWNER_ENV, isolate_coverage_data_file

_REPO_ROOT = Path(__file__).resolve().parent.parent


class TestTheRunningProcessOwnsItsCoverageDataFile:
    """The live environment, as the plugin left it at import time.

    Reading it back is the only way to tell that the wiring ran at all: the
    plugin defines no hooks, so nothing else observes it.
    """

    def test_the_data_file_is_not_at_the_repo_root(self) -> None:
        """A repo-root data file is what makes a sibling run a collision.

        Returns:
            None.
        """
        data_file = Path(os.environ["COVERAGE_FILE"])
        assert data_file.parent != _REPO_ROOT

    def test_the_directory_carries_this_process_id(self) -> None:
        """Two concurrent runs therefore sweep two different directories.

        Returns:
            None.
        """
        data_file = Path(os.environ["COVERAGE_FILE"])
        assert str(os.getpid()) in data_file.parent.name
        assert os.environ[OWNER_ENV] == str(os.getpid())


class TestOwnershipIsCheckedAgainstTheCurrentProcess:
    """The helper, asked the three questions an inherited env var poses.

    Ours, a parent's, or an operator's -- and only the middle one has to be
    replaced.
    """

    def test_an_inherited_value_is_replaced(self) -> None:
        """A child pytest must not write into its parent's directory.

        Returns:
            None.
        """
        other = os.getpid() + 1
        parent = f"/tmp/django-graphex-coverage-{other}/.coverage"  # noqa: S108
        environ = {"COVERAGE_FILE": parent, OWNER_ENV: str(other)}
        minted = isolate_coverage_data_file(environ, os.getpid())
        assert minted is not None
        assert minted != parent
        assert environ[OWNER_ENV] == str(os.getpid())

    def test_this_processs_own_value_is_kept(self) -> None:
        """Re-entering the helper must not mint a second directory.

        Returns:
            None.
        """
        environ = dict(os.environ)
        assert (
            isolate_coverage_data_file(environ, os.getpid())
            == os.environ["COVERAGE_FILE"]
        )

    def test_an_operator_set_value_is_left_alone(self) -> None:
        """A COVERAGE_FILE nobody here minted is a deliberate choice.

        It carries no owner stamp, which is what tells it apart from an
        inherited one.

        Returns:
            None.
        """
        environ = {"COVERAGE_FILE": "/tmp/operator-chose-this"}  # noqa: S108
        assert isolate_coverage_data_file(environ, os.getpid()) is None
        assert environ["COVERAGE_FILE"] == "/tmp/operator-chose-this"  # noqa: S108
