"""Tests for v3 project storage (components + builds)."""

from __future__ import annotations
try:
    import tests._pcpo_test_isolation_bootstrap  # noqa: F401
except Exception:
    import _pcpo_test_isolation_bootstrap  # type: ignore  # noqa: F401

import hashlib
import json
import os
import tempfile
import unittest
import uuid
from pathlib import Path
from unittest.mock import patch

from pc_parts_organizer.models import Build, Component
from pc_parts_organizer.storage import (
    ProjectState,
    StorageError,
    create_pre_restore_backup,
    export_inventory,
    load_project_state,
    parse_inventory_text,
    read_inventory_file,
    save_project_state,
)


def _comp(**o):
    d = dict(
        category="CPU", manufacturer="AMD", model="Ryzen ñ", specifications="spec", notes="nota",
        status="stored", location="Escritorio", purchase_date="2024-01-01", warranty_end_date="2025-01-01",
        purchase_price="99.90", purchase_currency="EUR",
    )
    d.update(o)
    return Component(**d)


def _build(component_ids=None, **o):
    d = dict(name="Mi PC", notes="notas", kind="current", component_ids=component_ids or [])
    d.update(o)
    return Build(**d)


def _v1_doc(comp_dicts):
    return {"schema_version": 1, "components": comp_dicts}


def _v2_doc(comp_dicts):
    # v2 shape accepted by reader (full or partial optional fields); use full for clarity
    return {"schema_version": 2, "components": comp_dicts}


def _minimal_v1_comp(uid):
    return {"id": uid, "category": "CPU", "manufacturer": "A", "model": "M", "specifications": "", "notes": ""}


def _full_comp_dict(c: Component):
    return {
        "id": c.id, "category": c.category, "manufacturer": c.manufacturer, "model": c.model,
        "specifications": c.specifications, "notes": c.notes, "status": c.status, "location": c.location,
        "purchase_date": c.purchase_date, "warranty_end_date": c.warranty_end_date,
        "purchase_price": c.purchase_price, "purchase_currency": c.purchase_currency,
    }


class TestBuildStorageV3(unittest.TestCase):
    def _env(self, base: Path):
        return patch.dict(os.environ, {"LOCALAPPDATA": str(base)})

    def test_save_load_v3_preserves_all_fields_and_utf8(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
            c = _comp()
            b = _build(component_ids=[c.id], notes="configuración ñ")
            with self._env(base):
                save_project_state([c], [b])
                path = base / "PCPartsOrganizer" / "components.json"
                raw = path.read_bytes()
                self.assertFalse(raw.startswith(b"\xef\xbb\xbf"))
                doc = json.loads(raw.decode("utf-8"))
                self.assertEqual(doc["schema_version"], 4)
                self.assertEqual(set(doc.keys()), {"schema_version", "components", "builds", "technical_profiles"})
                self.assertEqual(doc["technical_profiles"], [])
                self.assertEqual(len(doc["components"][0].keys()), 12)
                self.assertEqual(set(doc["builds"][0].keys()), {"id", "name", "notes", "kind", "component_ids"})
                self.assertEqual(doc["builds"][0]["notes"], "configuración ñ")
                state = load_project_state()
        self.assertEqual(len(state.components), 1)
        self.assertEqual(state.components[0].id, c.id)
        self.assertEqual(state.components[0].location, "Escritorio")
        self.assertEqual(len(state.builds), 1)
        self.assertEqual(state.builds[0].id, b.id)
        self.assertEqual(state.builds[0].component_ids, [c.id])

    def test_v3_cross_reference_validations(self) -> None:
        c1, c2 = _comp(model="A"), _comp(category="GPU", manufacturer="N", model="B")
        # unknown component
        with self.assertRaises(StorageError):
            save_project_state([c1], [_build(component_ids=[str(uuid.uuid4())])])
        # duplicate in build (caught by Build model / parse validation)
        with self.assertRaises(StorageError):
            parse_inventory_text(json.dumps({"schema_version": 3, "components": [_full_comp_dict(c1)], "builds": [
                {"id": str(uuid.uuid4()), "name": "B", "notes": "", "kind": "current", "component_ids": [c1.id, c1.id]}
            ]}))
        # global duplicate across builds
        with self.assertRaises(StorageError):
            save_project_state([c1, c2], [_build(name="A", component_ids=[c1.id]), _build(name="B", component_ids=[c1.id])])
        # duplicate build name case-insensitive after strip
        with self.assertRaises(StorageError):
            save_project_state([c1, c2], [_build(name="Mi PC", component_ids=[c1.id]), _build(name=" mi pc ", component_ids=[c2.id])])
        # duplicate build id
        bid = str(uuid.uuid4())
        with self.assertRaises(StorageError):
            save_project_state([c1, c2], [_build(name="A", id=bid, component_ids=[c1.id]), _build(name="B", id=bid, component_ids=[c2.id])])

    def test_parse_accepts_v1_v2_with_empty_builds_and_no_rewrite(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
            uid = str(uuid.uuid4())
            for doc in [_v1_doc([_minimal_v1_comp(uid)]), _v2_doc([_full_comp_dict(_comp(id=uid))])]:
                p = base / "f.json"
                p.write_text(json.dumps(doc, ensure_ascii=False), encoding="utf-8")
                before = p.read_bytes()
                sv, comps, builds = parse_inventory_text(p.read_text(encoding="utf-8"))
                self.assertIn(sv, (1, 2))
                self.assertEqual(len(comps), 1)
                self.assertEqual(builds, [])
                self.assertEqual(p.read_bytes(), before)

    def test_load_v1_v2_does_not_write(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
            inv_dir = base / "PCPartsOrganizer"
            inv_dir.mkdir(parents=True)
            p = inv_dir / "components.json"
            uid = str(uuid.uuid4())
            p.write_text(json.dumps(_v1_doc([_minimal_v1_comp(uid)])), encoding="utf-8")
            before = p.read_bytes()
            with self._env(base):
                state = load_project_state()
            self.assertEqual(len(state.components), 1)
            self.assertEqual(state.builds, [])
            self.assertEqual(p.read_bytes(), before)

    def test_rejects_corrupt_unknown_version_unknown_keys(self) -> None:
        with self.assertRaises(StorageError):
            parse_inventory_text("{bad")
        with self.assertRaises(StorageError):
            parse_inventory_text(json.dumps({"schema_version": 9, "components": [], "builds": []}))
        with self.assertRaises(StorageError):
            parse_inventory_text(json.dumps({"schema_version": 3, "components": [], "builds": [], "extra": 1}))
        uid = str(uuid.uuid4())
        bad_build = {"id": str(uuid.uuid4()), "name": "B", "kind": "current", "component_ids": [], "extra": 1}
        with self.assertRaises(StorageError):
            parse_inventory_text(json.dumps({"schema_version": 3, "components": [_full_comp_dict(_comp(id=uid))], "builds": [bad_build]}))
        # v2 root must not accept builds key
        with self.assertRaises(StorageError):
            parse_inventory_text(json.dumps({"schema_version": 2, "components": [_full_comp_dict(_comp(id=uid))], "builds": []}))

    def test_atomic_write_preserves_previous_file_on_failure(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
            c1 = _comp(model="Original")
            with self._env(base):
                save_project_state([c1], [])
                p = base / "PCPartsOrganizer" / "components.json"
                before = p.read_bytes()
                c2 = _comp(model="New")
                with patch("os.replace", side_effect=OSError("boom")):
                    with self.assertRaises(StorageError):
                        save_project_state([c2], [])
                self.assertEqual(p.read_bytes(), before)

    def test_export_complete_and_read_verification(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
            c = _comp()
            b = _build(component_ids=[c.id])
            dest = base / "backup.json"
            info = export_inventory([c], dest, builds=[b])
            self.assertEqual(info.schema_version, 4)
            self.assertEqual(len(info.components), 1)
            self.assertEqual(len(info.builds), 1)
            self.assertEqual(getattr(info, "technical_profiles", []), [])
            loaded = read_inventory_file(dest)
            self.assertEqual(loaded.builds[0].name, "Mi PC")
            self.assertEqual(getattr(loaded, "technical_profiles", []), [])
            self.assertEqual(loaded.sha256, info.sha256)
            self.assertEqual(hashlib.sha256(dest.read_bytes()).hexdigest(), info.sha256)

    def test_pre_restore_backup_complete_no_overwrite_verifiable(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
            c = _comp()
            b = _build(component_ids=[c.id])
            bdir = base / "pre"
            info = create_pre_restore_backup([c], builds=[b], directory=bdir)
            self.assertTrue(info.path and info.path.exists())
            loaded = read_inventory_file(info.path)
            self.assertEqual(len(loaded.builds), 1)
            info2 = create_pre_restore_backup([c], builds=[b], directory=bdir)
            self.assertNotEqual(info.path, info2.path)
            self.assertTrue(info.path.exists() and info2.path.exists())

    def test_parse_rejects_unknown_component_reference(self) -> None:
        c = _comp()
        doc = {"schema_version": 3, "components": [_full_comp_dict(c)], "builds": [
            {"id": str(uuid.uuid4()), "name": "B", "notes": "", "kind": "current", "component_ids": [str(uuid.uuid4())]}
        ]}
        with self.assertRaises(StorageError):
            parse_inventory_text(json.dumps(doc))


if __name__ == "__main__":
    unittest.main()
