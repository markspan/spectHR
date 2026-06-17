# Copyright (C) 2025 Mark Span <m.m.span@rug.nl>
# SPDX-License-Identifier: GPL-3.0-or-later
"""
Headless-import guard.

``spectHR`` is the algorithm/computation library and must stay strictly
separated from ``spectUI`` (the PySide6 Qt UI). Importing any part of
``spectHR`` must therefore **not** drag in the GUI stack, both for clean
layering and because pulling PySide6 into a headless process is what
historically caused the test suite to abort (a Qt init-order segfault when
a "headless" test imported the UI indirectly).

Each check runs in a **fresh subprocess** so the result is independent of
whatever the surrounding pytest session has already imported (other test
files legitimately import Qt). The subprocess imports a single spectHR
module and inspects ``sys.modules`` for any forbidden GUI package.
"""
from __future__ import annotations

import os
import subprocess
import sys

import pytest


# Top-level package names that must never appear in sys.modules after a
# pure spectHR import.
FORBIDDEN_ROOTS = ("PySide6", "shiboken6", "spectUI", "qtawesome")

# The headless surface that must import Qt-free: the package root, the
# config bridge, the analysis layer, the dataset, and every loader.
HEADLESS_MODULES = [
    "spectHR",
    "spectHR.config",
    "spectHR.analysis",
    "spectHR.DataSet",
    "spectHR.DataSet.preprocessing",
    "spectHR.DataSet.loaders",
    "spectHR.DataSet.loaders.edf_loader",
    "spectHR.DataSet.loaders.evt_loader",
    "spectHR.DataSet.loaders.nff_loader",
    "spectHR.DataSet.loaders.xdf_loader",
]

_CHECK_SRC = """
import sys, importlib
importlib.import_module({mod!r})
forbidden = {forbidden!r}
leaked = sorted({{m for m in sys.modules if m.split('.')[0] in forbidden}})
if leaked:
    sys.stderr.write("LEAKED:" + ",".join(leaked))
    raise SystemExit(1)
raise SystemExit(0)
"""


def _run_import_check(mod: str) -> subprocess.CompletedProcess:
    env = dict(os.environ)
    # Hand the child exactly the import path the parent test process uses,
    # so the check works whether spectHR is installed or run from ``src``.
    env["PYTHONPATH"] = os.pathsep.join(p for p in sys.path if p)
    code = _CHECK_SRC.format(mod=mod, forbidden=FORBIDDEN_ROOTS)
    return subprocess.run(
        [sys.executable, "-c", code],
        capture_output=True,
        text=True,
        env=env,
    )


@pytest.mark.parametrize("mod", HEADLESS_MODULES)
def test_headless_import_pulls_no_gui(mod: str) -> None:
    """Importing *mod* must not load any GUI package into sys.modules."""
    proc = _run_import_check(mod)
    assert proc.returncode == 0, (
        f"Importing {mod!r} pulled GUI modules into sys.modules, spectHR "
        f"must stay headless and independent of spectUI/Qt.\n"
        f"{proc.stderr.strip()}"
    )
