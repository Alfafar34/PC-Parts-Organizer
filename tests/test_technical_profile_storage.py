"""Storage tests for technical profiles v4 (T17.1)."""

from __future__ import annotations

try:
    import tests._pcpo_test_isolation_bootstrap  # noqa: F401
except Exception:
    import _pcpo_test_isolation_bootstrap  # type: ignore  # noqa: F401

import json
import os
import tempfile
import unittest
import uuid
from pathlib import Path
from unittest.mock import patch

from pc_parts_organizer.models import Build, Component
from pc_parts_organizer.storage import (
    StorageError,
    export_inventory,
    load_project_state,
    parse_project_state_text,
    read_inventory_file,
    save_project_state,
)
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


class TestTechnicalProfileStorage(unittest.TestCase):
    def _env(self, base):
        return patch.dict(os.environ, {"LOCALAPPDATA": str(base)})

    def test_v4_round_trip_and_deterministic_profiles(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
            c = _comp()
            p = _ram_profile(c.id)
            with self._env(base):
                save_project_state([c], [], [p])
                raw = (base / "PCPartsOrganizer" / "components.json").read_text(encoding="utf-8")
                doc = json.loads(raw)
                self.assertEqual(doc["schema_version"], 4)
                self.assertEqual(set(doc.keys()), {"schema_version", "components", "builds", "technical_profiles"})
                self.assertEqual(doc["technical_profiles"][0]["component_id"], c.id)
                state = load_project_state()
                self.assertEqual(len(state.technical_profiles), 1)
                self.assertEqual(state.technical_profiles[0].component_id, c.id)
                self.assertEqual([a.key for a in state.technical_profiles[0].attributes], ["memory_generation", "module_count", "module_form_factor", "total_capacity_gb"])

    def test_v1_v2_v3_read_no_rewrite_and_empty_profiles(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
            inv = base / "PCPartsOrganizer" / "components.json"
            inv.parent.mkdir(parents=True)
            cid = str(uuid.uuid4())
            for sv, doc in [
                (1, {"schema_version": 1, "components": [{"id": cid, "category": "RAM", "manufacturer": "A", "model": "M", "specifications": "", "notes": ""}]}),
                (2, {"schema_version": 2, "components": [{"id": cid, "category": "RAM", "manufacturer": "A", "model": "M", "specifications": "", "notes": "", "status": "unspecified", "location": "", "purchase_date": "", "warranty_end_date": "", "purchase_price": "", "purchase_currency": ""}]}),
                (3, {"schema_version": 3, "components": [{"id": cid, "category": "RAM", "manufacturer": "A", "model": "M", "specifications": "", "notes": "", "status": "unspecified", "location": "", "purchase_date": "", "warranty_end_date": "", "purchase_price": "", "purchase_currency": ""}], "builds": []}),
            ]:
                inv.write_text(json.dumps(doc), encoding="utf-8")
                before = inv.read_bytes()
                with self._env(base):
                    state = load_project_state()
                self.assertEqual(state.schema_version, sv)
                self.assertEqual(state.technical_profiles, [])
                self.assertEqual(inv.read_bytes(), before)

    def test_rejects_unknown_component_duplicate_key_not_allowed_and_corrupt(self) -> None:
        c = _comp()
        good = {"id": c.id, "category": c.category, "manufacturer": c.manufacturer, "model": c.model, "specifications": "", "notes": "", "status": "unspecified", "location": "", "purchase_date": "", "warranty_end_date": "", "purchase_price": "", "purchase_currency": ""}
        bad_ref = {"schema_version": 4, "components": [good], "builds": [], "technical_profiles": [{"component_id": str(uuid.uuid4()), "attributes": [{"key": "memory_generation", "value": "DDR4"}]}]}
        with self.assertRaises(StorageError):
            parse_project_state_text(json.dumps(bad_ref))
        dup = {"schema_version": 4, "components": [good], "builds": [], "technical_profiles": [{"component_id": c.id, "attributes": []}, {"component_id": c.id, "attributes": []}]}
        with self.assertRaises(StorageError):
            parse_project_state_text(json.dumps(dup))
        bad_key = {"schema_version": 4, "components": [good], "builds": [], "technical_profiles": [{"component_id": c.id, "attributes": [{"key": "form_factor", "value": "ATX"}]}]}
        with self.assertRaises(StorageError):
            parse_project_state_text(json.dumps(bad_key))
        with self.assertRaises(StorageError):
            parse_project_state_text("{bad")
        extra = {"schema_version": 4, "components": [good], "builds": [], "technical_profiles": [], "extra": 1}
        with self.assertRaises(StorageError):
            parse_project_state_text(json.dumps(extra))

    def test_atomic_write_preserves_previous(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
            c = _comp()
            with self._env(base):
                save_project_state([c], [], [_ram_profile(c.id)])
                p = base / "PCPartsOrganizer" / "components.json"
                before = p.read_bytes()
                with patch("os.replace", side_effect=OSError("boom")):
                    with self.assertRaises(StorageError):
                        save_project_state([c], [], [])
                self.assertEqual(p.read_bytes(), before)

    def test_export_and_prebackup_include_profiles(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
            c = _comp()
            prof = _ram_profile(c.id)
            dest = base / "b.json"
            info = export_inventory([c], dest, builds=[], technical_profiles=[prof])
            self.assertEqual(len(info.technical_profiles), 1)
            loaded = read_inventory_file(dest)
            self.assertEqual(loaded.technical_profiles[0].component_id, c.id)
            from pc_parts_organizer.storage import create_pre_restore_backup
            pre = create_pre_restore_backup([c], builds=[], technical_profiles=[prof], directory=base / "pre")
            self.assertEqual(len(read_inventory_file(pre.path).technical_profiles), 1)

    def test_save_components_preserves_profiles_when_omitted(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
            c = _comp()
            with self._env(base):
                save_project_state([c], [], [_ram_profile(c.id)])
                from pc_parts_organizer.storage import save_components
                save_components([Component(id=c.id, category=c.category, manufacturer="New", model=c.model, specifications="", notes="")])
                state = load_project_state()
                self.assertEqual(state.components[0].manufacturer, "New")
                self.assertEqual(len(state.technical_profiles), 1)
                self.assertEqual(state.technical_profiles[0].component_id, c.id)


if __name__ == "__main__":
    unittest.main()
