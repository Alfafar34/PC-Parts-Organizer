"""Service tests for technical profiles (T17.1)."""

from __future__ import annotations

try:
    import tests._pcpo_test_isolation_bootstrap  # noqa: F401
except Exception:
    import _pcpo_test_isolation_bootstrap  # type: ignore  # noqa: F401

import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from pc_parts_organizer.models import Component
from pc_parts_organizer.service import (
    ComponentInUseError,
    ComponentNotFoundError,
    InventoryService,
    StorageError,
    TechnicalProfileCategoryConflictError,
)
from pc_parts_organizer.storage import InventoryFileInfo, read_inventory_file
from pc_parts_organizer.technical_profiles import TechnicalAttribute, TechnicalProfile


def _comp(category="RAM", **o):
    d = dict(category=category, manufacturer="M", model="X", specifications="", notes="")
    d.update(o)
    return Component(**d)


def _ram_profile(cid):
    return TechnicalProfile(
        component_id=cid,
        attributes=[
            TechnicalAttribute(key="memory_generation", value="DDR4"),
            TechnicalAttribute(key="module_form_factor", value="DIMM"),
            TechnicalAttribute(key="total_capacity_gb", value=16, unit="GB"),
            TechnicalAttribute(key="module_count", value=2),
        ],
    )


class TestTechnicalProfileService(unittest.TestCase):
    def _env(self, base):
        return patch.dict(os.environ, {"LOCALAPPDATA": str(base)})

    def _save_state(self, base, comps, builds=None, profiles=None):
        from pc_parts_organizer.storage import save_project_state
        with self._env(base):
            save_project_state(comps, builds or [], profiles or [])

    def test_set_get_delete_profile_and_reconstruction(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
            c = _comp()
            self._save_state(base, [c], [], [])
            with self._env(base):
                s = InventoryService()
                p = s.set_technical_profile(_ram_profile(c.id))
                self.assertEqual(p.component_id, c.id)
                self.assertIsNotNone(s.get_technical_profile(c.id))
                self.assertEqual(len(s.get_technical_profiles()), 1)
            with self._env(base):
                s2 = InventoryService()
                self.assertEqual(len(s2.get_technical_profiles()), 1)
                s2.delete_technical_profile(c.id)
                self.assertIsNone(s2.get_technical_profile(c.id))
            with self._env(base):
                s3 = InventoryService()
                self.assertEqual(s3.get_technical_profiles(), [])

    def test_rejects_orphan_profile_and_missing_component(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
            self._save_state(base, [], [], [])
            with self._env(base):
                s = InventoryService()
                with self.assertRaises((ComponentNotFoundError, StorageError)):
                    s.set_technical_profile(_ram_profile("00000000-0000-4000-8000-000000000099"))

    def test_profiles_preserved_across_component_and_build_mutations(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
            c = _comp()
            self._save_state(base, [c], [], [_ram_profile(c.id)])
            with self._env(base):
                s = InventoryService()
                s.update_component(c.id, c.category, "NewMaker", c.model, "", "")
                self.assertEqual(len(s.get_technical_profiles()), 1)
                b = s.add_build("B1")
                self.assertEqual(len(s.get_technical_profiles()), 1)
                s.update_build(b.id, notes="x")
                self.assertEqual(len(s.get_technical_profiles()), 1)

    def test_category_change_incompatible_blocked_no_auto_discard(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
            c = _comp(category="RAM")
            self._save_state(base, [c], [], [_ram_profile(c.id)])
            with self._env(base):
                s = InventoryService()
                with self.assertRaises(TechnicalProfileCategoryConflictError):
                    s.update_component(c.id, "GPU", c.manufacturer, c.model, "", "")
                self.assertEqual(s.get_component(c.id).category, "RAM")
                self.assertEqual(len(s.get_technical_profiles()), 1)

    def test_delete_component_removes_profile_atomically_and_respects_build_lock(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
            c = _comp()
            self._save_state(base, [c], [], [_ram_profile(c.id)])
            with self._env(base):
                s = InventoryService()
                b = s.add_build("B", component_ids=[c.id])
                with self.assertRaises(ComponentInUseError):
                    s.delete_component(c.id)
                self.assertEqual(len(s.get_technical_profiles()), 1)
                s.delete_build(b.id)
                s.delete_component(c.id)
                self.assertEqual(s.get_technical_profiles(), [])
                self.assertIsNone(s.get_component(c.id))

    def test_persistence_failure_leaves_memory_intact(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
            c = _comp()
            self._save_state(base, [c], [], [_ram_profile(c.id)])
            with self._env(base):
                s = InventoryService()
                with patch("pc_parts_organizer.service.save_project_state", side_effect=StorageError("boom")):
                    with self.assertRaises(StorageError):
                        s.set_technical_profile(_ram_profile(c.id))
                self.assertEqual(len(s.get_technical_profiles()), 1)

    def test_restore_v4_and_legacy_clears_profiles(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
            c = _comp()
            self._save_state(base, [c], [], [_ram_profile(c.id)])
            # v4 backup
            with self._env(base):
                s = InventoryService()
                from pc_parts_organizer.storage import export_inventory, get_components_file_path
                state = s.get_project_state()
                dest = base / "v4.json"
                info = export_inventory(state.components, dest, active_path=get_components_file_path(), builds=state.builds, technical_profiles=state.technical_profiles)
            # wipe profiles then restore v4
            with self._env(base):
                s = InventoryService()
                s.delete_technical_profile(c.id)
                res = s.restore_inventory(info)
                self.assertEqual(res.restored_technical_profile_count, 1)
                self.assertEqual(len(s.get_technical_profiles()), 1)
            # legacy v3 restore clears profiles
            v3 = base / "v3.json"
            v3.write_text(json.dumps({
                "schema_version": 3,
                "components": [{"id": c.id, "category": c.category, "manufacturer": c.manufacturer, "model": c.model, "specifications": "", "notes": "", "status": "unspecified", "location": "", "purchase_date": "", "warranty_end_date": "", "purchase_price": "", "purchase_currency": ""}],
                "builds": [],
            }), encoding="utf-8")
            with self._env(base):
                s = InventoryService()
                # ensure has profile
                s.set_technical_profile(_ram_profile(c.id))
                self.assertEqual(len(s.get_technical_profiles()), 1)
                v3info = read_inventory_file(v3)
                s.restore_inventory(v3info)
                self.assertEqual(s.get_technical_profiles(), [])


if __name__ == "__main__":
    unittest.main()
