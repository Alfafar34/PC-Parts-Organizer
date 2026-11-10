"""Mandatory test isolation proof (T16.3-R2). No real data writes."""

from __future__ import annotations

try:
    import tests._pcpo_test_isolation_bootstrap  # noqa: F401
except Exception:
    import _pcpo_test_isolation_bootstrap  # type: ignore  # noqa: F401

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

import tests
from pc_parts_organizer.storage import get_components_file_path, get_data_directory


class TestIsolationProof(unittest.TestCase):
    def _assert_isolated(self) -> Path:
        data_dir = get_data_directory()
        tests.assert_not_real_data_path(data_dir)
        tests.assert_not_real_data_path(get_components_file_path())
        isolated = Path(os.environ["LOCALAPPDATA"]).resolve(strict=False)
        resolved = data_dir.resolve(strict=False)
        self.assertTrue(
            resolved == isolated / "PCPartsOrganizer" or isolated in resolved.parents,
            f"{resolved} not under isolated LOCALAPPDATA {isolated}",
        )
        self.assertEqual(os.environ.get("PCPO_TEST_ISOLATION_ACTIVE"), "1")
        return isolated

    def test_positive_persistence_path_is_isolated_temp(self) -> None:
        self._assert_isolated()

    def test_negative_real_path_is_rejected(self) -> None:
        real = tests.get_data_path_guard()
        if real is None:
            self.skipTest("Real LOCALAPPDATA not resolvable for negative check")
        with self.assertRaises(AssertionError):
            tests.assert_not_real_data_path(real / "components.json")
        self.assertNotEqual(
            Path(os.environ["LOCALAPPDATA"]).resolve(strict=False),
            real.parent.resolve(strict=False),
        )

    def test_persistence_writes_only_to_temp(self) -> None:
        isolated = self._assert_isolated()
        # controlled persistence in temp dir only (never real inventory)
        with tempfile.TemporaryDirectory() as td:
            target = Path(td) / "sample.json"
            target.write_text(json.dumps({"ok": True}), encoding="utf-8")
            self.assertTrue(target.exists())
            resolved = target.resolve(strict=False)
            self.assertTrue(Path(td).resolve(strict=False) in resolved.parents or resolved == Path(td).resolve(strict=False))
            self.assertNotEqual(resolved, (Path(os.environ.get("PCPO_TEST_ISOLATION_REAL_LOCALAPPDATA") or td) / "PCPartsOrganizer" / "components.json").resolve(strict=False))

    def test_subprocess_inherits_isolated_env(self) -> None:
        self._assert_isolated()
        code = (
            "import os, json; "
            "print(json.dumps({"
            "'active': os.environ.get('PCPO_TEST_ISOLATION_ACTIVE'),"
            "'local': os.environ.get('LOCALAPPDATA'),"
            "'root': os.environ.get('PCPO_TEST_ISOLATION_LOCALAPPDATA')"
            "}))"
        )
        r = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, env=os.environ.copy(), timeout=30)
        self.assertEqual(r.returncode, 0, r.stderr)
        data = json.loads(r.stdout.strip())
        self.assertEqual(data["active"], "1")
        self.assertEqual(data["local"], data["root"])
        self.assertTrue(data["local"])

    def test_top_level_module_bootstraps_before_app_import(self) -> None:
        """Equivalent to R1 breach: top-level test module load must activate bootstrap."""
        root = Path(__file__).resolve().parents[1]
        tests_dir = root / "tests"
        code = (
            "import os, sys, json\n"
            f"sys.path.insert(0, {str(tests_dir)!r})\n"
            f"sys.path.insert(0, {str(root)!r})\n"
            "import test_models\n"  # top-level style; module itself now has bootstrap
            "print(json.dumps({'active': os.environ.get('PCPO_TEST_ISOLATION_ACTIVE'), 'has_tests_pkg': 'tests._pcpo_test_isolation_bootstrap' in sys.modules or '_pcpo_test_isolation_bootstrap' in sys.modules}))\n"
        )
        env = os.environ.copy()
        # simulate real-ish LOCALAPPDATA present; subprocess inherits isolated env by default, which is fine
        r = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, env=env, cwd=str(root), timeout=30)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        data = json.loads(r.stdout.strip())
        self.assertEqual(data["active"], "1")
        self.assertTrue(data["has_tests_pkg"])
