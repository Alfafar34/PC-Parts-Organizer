"""Idempotent, fail-closed test isolation bootstrap (T16.3-R2).

Must run BEFORE importing pc_parts_organizer or resolving app data paths.
Safe for: `python -m unittest tests.test_x`, `discover -v` (root),
`discover -v -s tests` (top-level module loading), and individual module runs
from the project root.

Does not import pc_parts_organizer. Does not import unrelated `tests` packages
(loaded as `tests._pcpo_test_isolation_bootstrap` or `_pcpo_test_isolation_bootstrap`).
"""

from __future__ import annotations

import atexit
import os
import shutil
import sys
import tempfile
from pathlib import Path

_MARKER = "PCPO_TEST_ISOLATION_ACTIVE"
_ROOT_MARKER = "PCPO_TEST_ISOLATION_LOCALAPPDATA"
_REAL_MARKER = "PCPO_TEST_ISOLATION_REAL_LOCALAPPDATA"
_APP_DIR_NAME = "PCPartsOrganizer"

_REAL_LOCALAPPDATA: str | None = None
_ISOLATED_LOCALAPPDATA: Path | None = None


def _resolve_real_guard() -> Path | None:
    raw = os.environ.get(_REAL_MARKER) or _REAL_LOCALAPPDATA
    if not raw or not raw.strip():
        return None
    try:
        p = Path(raw)
        if not p.is_absolute():
            return None
        return (p / _APP_DIR_NAME).resolve(strict=False)
    except Exception:
        return None


def get_data_path_guard() -> Path | None:
    """Return the real PCPartsOrganizer data dir, if resolvable (safety checks only)."""
    return _resolve_real_guard()


def assert_not_real_data_path(path: os.PathLike[str] | str) -> None:
    real = get_data_path_guard()
    if real is None:
        return
    try:
        resolved = Path(path).resolve(strict=False)
        real_resolved = real
    except Exception:
        return
    if resolved == real_resolved or real_resolved in resolved.parents:
        raise AssertionError(
            f"Test isolation violation: attempted to use real data path: {resolved}"
        )


def _is_under(path: Path, root: Path) -> bool:
    try:
        rp = path.resolve(strict=False)
        rr = root.resolve(strict=False)
        return rp == rr or rr in rp.parents
    except Exception:
        return False


def _fail(msg: str) -> None:
    raise RuntimeError(f"PC Parts Organizer test isolation failed: {msg}")


def _cleanup(path: Path) -> None:
    shutil.rmtree(path, ignore_errors=True)


def activate() -> None:
    global _REAL_LOCALAPPDATA, _ISOLATED_LOCALAPPDATA
    if os.environ.get(_MARKER) == "1":
        # verify still safe (idempotent / subprocess sanity)
        root = os.environ.get(_ROOT_MARKER)
        if not root:
            _fail("isolation marked active but root is missing")
        root_path = Path(root)
        cur = os.environ.get("LOCALAPPDATA")
        if not cur:
            _fail("LOCALAPPDATA missing while isolation is active")
        cur_path = Path(cur)
        if cur_path.resolve(strict=False) != root_path.resolve(strict=False):
            _fail("LOCALAPPDATA diverged from isolated test root")
        real_guard = _resolve_real_guard()
        if real_guard is not None and _is_under(cur_path / _APP_DIR_NAME, real_guard):
            _fail("isolated LOCALAPPDATA resolves under real app data path")
        _REAL_LOCALAPPDATA = os.environ.get(_REAL_MARKER)
        _ISOLATED_LOCALAPPDATA = root_path
        return

    original = os.environ.get("LOCALAPPDATA")
    if original is None or not str(original).strip():
        _fail("LOCALAPPDATA is not set; refusing to run persistent-capable tests")
    original_path = Path(original)
    # capture real guard before redirection
    os.environ[_REAL_MARKER] = str(original_path)
    _REAL_LOCALAPPDATA = str(original_path)

    isolated = Path(tempfile.mkdtemp(prefix="pcpo-tests-localappdata-"))
    os.environ["LOCALAPPDATA"] = str(isolated)
    os.environ[_ROOT_MARKER] = str(isolated)
    os.environ[_MARKER] = "1"
    _ISOLATED_LOCALAPPDATA = isolated

    # fail-closed verification
    real_guard = _resolve_real_guard()
    candidate_data = (isolated / _APP_DIR_NAME).resolve(strict=False)
    if real_guard is not None and _is_under(candidate_data, real_guard):
        _fail(f"isolated data path {candidate_data} falls under real {real_guard}")
    if real_guard is not None and candidate_data == real_guard:
        _fail("isolated data path equals real data path")

    atexit.register(_cleanup, isolated)


# Activate on import (must be first side effect in test modules).
activate()

# Re-export for compatibility.
TESTS_REAL_LOCALAPPDATA = os.environ.get(_REAL_MARKER)
TESTS_ISOLATED_LOCALAPPDATA = os.environ.get(_ROOT_MARKER)
