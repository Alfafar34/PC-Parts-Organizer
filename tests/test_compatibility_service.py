"""Service query integration for compatibility analysis (T17.3). Isolated storage."""

from __future__ import annotations

try:
    import tests._pcpo_test_isolation_bootstrap  # noqa: F401
except Exception:
    import _pcpo_test_isolation_bootstrap  # type: ignore  # noqa: F401

import dataclasses
import os
import tempfile
import unittest
import uuid
from pathlib import Path
from unittest.mock import patch

from pc_parts_organizer.compatibility import RESULT_INSUFFICIENT_DATA, RESULT_REQUIRES_VERIFICATION
from pc_parts_organizer.service import BuildNotFoundError, InventoryService
from pc_parts_organizer.storage import save_project_state
from pc_parts_organizer.technical_profiles import TechnicalAttribute, TechnicalProfile


def vattr(key, value, unit=None):
    return TechnicalAttribute(key=key, value=value, unit=unit, source="official_vendor_doc", confidence="high",
                              verification_status="verified", evidence_ref="https://e", verified_at="2026-01-01")


class TestCompatibilityService(unittest.TestCase):
    def _env(self, base):
        return patch.dict(os.environ, {"LOCALAPPDATA": str(base)})

    @staticmethod
    def _state_dict(service: InventoryService):
        st = service.get_project_state()
        return dataclasses.asdict(st) if dataclasses.is_dataclass(st) else st.to_dict()

    def test_existing_build_returns_report_no_state_change(self):
        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
            with self._env(base):
                save_project_state([], [], [])
                s = InventoryService()
                before = self._state_dict(s)
                ram = s.add_component("RAM", "M", "R")
                mb = s.add_component("Motherboard", "M", "B")
                b = s.add_build("Build1", component_ids=[ram.id, mb.id])
                s.set_technical_profile(TechnicalProfile(component_id=ram.id, attributes=[vattr("memory_generation", "DDR5"), vattr("module_form_factor", "DIMM"), vattr("total_capacity_gb", 32, "GB"), vattr("module_count", 2)]))
                s.set_technical_profile(TechnicalProfile(component_id=mb.id, attributes=[vattr("supported_memory_generations", ["DDR5"]), vattr("supported_memory_module_form_factors", ["DIMM"]), vattr("max_memory_capacity_gb", 128, "GB"), vattr("memory_slot_count", 4)]))
                state_mid = self._state_dict(s)
                r = s.analyze_build_compatibility(b.id)
                state_after = self._state_dict(s)
                self.assertEqual(r.build_id, b.id)
                self.assertGreater(r.rules_evaluated, 0)
                self.assertEqual(r.overall_result, RESULT_INSUFFICIENT_DATA)
                self.assertNotEqual(state_mid, before)
                self.assertEqual(state_mid, state_after)

    def test_missing_build_raises(self):
        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
            with self._env(base):
                save_project_state([], [], [])
                s = InventoryService()
                with self.assertRaises(BuildNotFoundError):
                    s.analyze_build_compatibility(str(uuid.uuid4()))

    def test_snapshot_coherent_with_current_state(self):
        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
            with self._env(base):
                save_project_state([], [], [])
                s = InventoryService()
                ram = s.add_component("RAM", "M", "R")
                mb = s.add_component("Motherboard", "M", "B")
                b = s.add_build("B", component_ids=[ram.id, mb.id])
                r1 = s.analyze_build_compatibility(b.id)
                s.set_technical_profile(TechnicalProfile(component_id=ram.id, attributes=[TechnicalAttribute(key="memory_generation", value="DDR5")]))
                s.set_technical_profile(TechnicalProfile(component_id=mb.id, attributes=[vattr("supported_memory_generations", ["DDR5"])]))
                r2 = s.analyze_build_compatibility(b.id)
                self.assertNotEqual([(f.rule_id, f.result) for f in r1.findings], [(f.rule_id, f.result) for f in r2.findings])
                gen = [f for f in r2.findings if f.rule_id == "ram_mb.memory_generation"][0]
                self.assertEqual(gen.result, RESULT_REQUIRES_VERIFICATION)


if __name__ == "__main__":
    unittest.main()
