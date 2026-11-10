"""Test package bootstrap: isolate persistent storage from real LOCALAPPDATA."""

from __future__ import annotations

import sys as _sys

# Canonical bootstrap (idempotent, fail-closed). Keep both module-name aliases
# so package and top-level discovery modes share one activation state.
try:
    from . import _pcpo_test_isolation_bootstrap as _bootstrap
except Exception:  # pragma: no cover - fallback for unusual loaders
    import _pcpo_test_isolation_bootstrap as _bootstrap  # type: ignore

_sys.modules.setdefault("tests._pcpo_test_isolation_bootstrap", _bootstrap)
_sys.modules.setdefault("_pcpo_test_isolation_bootstrap", _bootstrap)

from ._pcpo_test_isolation_bootstrap import (  # noqa: E402
    TESTS_ISOLATED_LOCALAPPDATA,
    TESTS_REAL_LOCALAPPDATA,
    assert_not_real_data_path,
    get_data_path_guard,
)

__all__ = [
    "TESTS_REAL_LOCALAPPDATA",
    "TESTS_ISOLATED_LOCALAPPDATA",
    "get_data_path_guard",
    "assert_not_real_data_path",
]
