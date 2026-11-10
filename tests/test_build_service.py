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
from pc_parts_organizer.service import (
    BuildNameConflictError,
    BuildNotFoundError,
    ComponentAlreadyAssignedError,
    ComponentInUseError,
    ComponentNotFoundError,
    InventoryService,
    StorageError,
)
from pc_parts_organizer.storage import InventoryFileInfo, load_project_state, save_project_state


def _comp(**o):
    d = dict(
        category="CPU", manufacturer="AMD", model="Ryzen", specifications="", notes="",
        status="unspecified", location="", purchase_date="", warranty_end_date="",
        purchase_price="", purchase_currency="",
    )
    d.update(o)
    return Component(**d)


class BuildServiceTests(unittest.TestCase):
    def _env(self, base: Path):
        return patch.dict(os.environ, {"LOCALAPPDATA": str(base)}, clear=False)

    def _save(self, components=None, builds=None):
        with self._env(self._base):
            save_project_state(list(components or []), list(builds or []))

    def setUp(self):
        self._td = tempfile.TemporaryDirectory()
        self._base = Path(self._td.name)
        self._save([], [])

    def tearDown(self):
        self._td.cleanup()

    def test_loads_components_and_builds(self):
        c = _comp(); b = Build(name="Mi PC", component_ids=[c.id])
        self._save([c], [b])
        with self._env(self._base):
            s = InventoryService()
            self.assertEqual(len(s.get_components()), 1)
            self.assertEqual(len(s.get_builds()), 1)
            self.assertEqual(s.get_builds()[0].component_ids, [c.id])

    def test_defensive_copies(self):
        c = _comp(); b = Build(name="Mi PC", component_ids=[c.id])
        self._save([c], [b])
        with self._env(self._base):
            s = InventoryService()
            comps = s.get_components(); comps.clear()
            self.assertEqual(len(s.get_components()), 1)
            builds = s.get_builds(); builds[0].component_ids.append(str(uuid.uuid4()))
            self.assertEqual(s.get_builds()[0].component_ids, [c.id])

    def test_persistence_reconstructed_service(self):
        c = _comp()
        self._save([c], [])
        with self._env(self._base):
            s = InventoryService()
            b = s.add_build("Mi PC", notes="n", kind="planned", component_ids=[c.id])
        with self._env(self._base):
            s2 = InventoryService()
            self.assertEqual(s2.get_build(b.id).name, "Mi PC")
            self.assertEqual(s2.get_available_components(), [])
        p = self._base / "PCPartsOrganizer" / "components.json"
        doc = json.loads(p.read_text(encoding="utf-8"))
        self.assertEqual(doc["schema_version"], 4)
        self.assertEqual(len(doc["builds"]), 1)
        self.assertIn("technical_profiles", doc)

    def test_build_crud(self):
        c = _comp(); self._save([c], [])
        with self._env(self._base):
            s = InventoryService()
            b = s.add_build("Mi PC", notes="nota", kind="current")
            self.assertTrue(uuid.UUID(b.id, version=4))
            self.assertEqual(s.get_build(b.id).name, "Mi PC")
            s.update_build(b.id, name="Nuevo", kind="planned", notes="x")
            self.assertEqual(s.get_build(b.id).kind, "planned")
            s.delete_build(b.id)
            self.assertIsNone(s.get_build(b.id))
            self.assertEqual(len(s.get_components()), 1)

    def test_build_name_unique_casefold(self):
        c1, c2 = _comp(), _comp(category="GPU", manufacturer="N", model="X")
        self._save([c1, c2], [])
        with self._env(self._base):
            s = InventoryService()
            s.add_build("Mi PC")
            with self.assertRaises(BuildNameConflictError):
                s.add_build(" mi pc ")
            b2 = s.add_build("Otra")
            with self.assertRaises(BuildNameConflictError):
                s.update_build(b2.id, name="MI PC")
            b1 = s.get_builds()[0]
            s.update_build(b1.id, name="Mi PC", notes="ok")

    def test_build_empty_valid_and_uuid_validation(self):
        with self._env(self._base):
            s = InventoryService()
            b = s.add_build("Vacío")
            self.assertEqual(b.component_ids, [])
            self.assertIsNone(s.get_build(str(uuid.uuid4())))
            with self.assertRaises(BuildNotFoundError):
                s.update_build(str(uuid.uuid4()), name="x")
            with self.assertRaises(BuildNotFoundError):
                s.delete_build(str(uuid.uuid4()))

    def test_association_add_remove_and_availability(self):
        c1, c2 = _comp(model="A"), _comp(category="GPU", manufacturer="N", model="B")
        self._save([c1, c2], [])
        with self._env(self._base):
            s = InventoryService()
            b = s.add_build("PC")
            s.add_component_to_build(b.id, c1.id)
            self.assertEqual(s.get_build(b.id).component_ids, [c1.id])
            self.assertEqual([c.id for c in s.get_available_components()], [c2.id])
            s.remove_component_from_build(b.id, c1.id)
            self.assertEqual(s.get_build(b.id).component_ids, [])
            self.assertEqual(len(s.get_available_components()), 2)

    def test_association_rejects_nonexistent_duplicate_second_build(self):
        c1, c2 = _comp(model="A"), _comp(category="GPU", manufacturer="N", model="B")
        self._save([c1, c2], [])
        with self._env(self._base):
            s = InventoryService()
            b1 = s.add_build("A"); b2 = s.add_build("B")
            with self.assertRaises(ComponentNotFoundError):
                s.add_component_to_build(b1.id, str(uuid.uuid4()))
            s.add_component_to_build(b1.id, c1.id)
            with self.assertRaises(ComponentAlreadyAssignedError):
                s.add_component_to_build(b1.id, c1.id)
            with self.assertRaises(ComponentAlreadyAssignedError):
                s.add_component_to_build(b2.id, c1.id)
            with self.assertRaises(ComponentNotFoundError):
                s.remove_component_from_build(b1.id, c2.id)

    def test_update_component_preserves_association(self):
        c = _comp(); self._save([c], [])
        with self._env(self._base):
            s = InventoryService()
            b = s.add_build("PC", component_ids=[c.id])
            s.update_component(c.id, category="CPU", manufacturer="AMD", model="Ryzen 9", specifications="new")
            self.assertEqual(s.get_build(b.id).component_ids, [c.id])
            self.assertEqual(s.get_component(c.id).model, "Ryzen 9")

    def test_delete_component_not_associated_works(self):
        c = _comp(); self._save([c], [])
        with self._env(self._base):
            s = InventoryService()
            s.delete_component(c.id)
            self.assertEqual(s.get_components(), [])

    def test_delete_component_associated_blocked_no_state_change(self):
        c = _comp(); b = Build(name="PC", component_ids=[c.id]); self._save([c], [b])
        p = self._base / "PCPartsOrganizer" / "components.json"
        before = p.read_bytes()
        with self._env(self._base):
            s = InventoryService()
            with self.assertRaises(ComponentInUseError):
                s.delete_component(c.id)
            self.assertEqual(len(s.get_components()), 1)
            self.assertEqual(len(s.get_builds()[0].component_ids), 1)
        self.assertEqual(p.read_bytes(), before)

    def test_atomicity_on_save_failure(self):
        c = _comp(); self._save([c], [])
        with self._env(self._base):
            s = InventoryService()
            with patch("pc_parts_organizer.storage.os.replace", side_effect=OSError("disk")):
                with self.assertRaises(StorageError):
                    s.add_build("PC")
            self.assertEqual(s.get_builds(), [])
            b = s.add_build("PC")
            c2 = _comp(category="GPU", manufacturer="N", model="B")
            s.add_component(c2.category, c2.manufacturer, c2.model)
            c2id = [x.id for x in s.get_components() if x.model == "B"][0]
            with patch("pc_parts_organizer.storage.os.replace", side_effect=OSError("disk")):
                with self.assertRaises(StorageError):
                    s.add_component_to_build(b.id, c2id)
            self.assertEqual(s.get_build(b.id).component_ids, [])
            with patch("pc_parts_organizer.storage.os.replace", side_effect=OSError("disk")):
                with self.assertRaises(StorageError):
                    s.delete_build(b.id)
            self.assertIsNotNone(s.get_build(b.id))

    def test_restore_v3_complete_state(self):
        c = _comp(); b = Build(name="PC", component_ids=[c.id]); self._save([c], [b])
        c2 = _comp(model="New"); b2 = Build(name="NewPC", component_ids=[c2.id])
        with self._env(self._base):
            s = InventoryService()
            result = s.restore_inventory([c2], [b2])
            self.assertEqual((result.restored_count, result.restored_build_count), (1, 1))
            self.assertEqual(s.get_builds()[0].name, "NewPC")
        with self._env(self._base):
            s2 = InventoryService()
            self.assertEqual(len(s2.get_builds()), 1)

    def test_restore_v1v2_equivalent_gives_empty_builds(self):
        c = _comp(); b = Build(name="PC", component_ids=[c.id]); self._save([c], [b])
        c2 = _comp(model="New")
        with self._env(self._base):
            s = InventoryService()
            result = s.restore_inventory([c2])
            self.assertEqual(result.restored_build_count, 0)
            self.assertEqual(s.get_builds(), [])

    def test_restore_inventory_fileinfo_v3(self):
        c = _comp(); b = Build(name="PC", component_ids=[c.id])
        with self._env(self._base):
            s = InventoryService()
            info = InventoryFileInfo(components=[c], builds=[b], schema_version=3, sha256="x")
            result = s.restore_inventory(info)
            self.assertEqual((result.restored_count, result.restored_build_count), (1, 1))

    def test_restore_prebackup_contains_current_builds(self):
        c = _comp(); b = Build(name="PC", component_ids=[c.id]); self._save([c], [b])
        backup_dir = self._base / "pre"
        with self._env(self._base):
            s = InventoryService()
            result = s.restore_inventory([], [], pre_restore_backup_dir=backup_dir)
        loaded = json.loads(Path(result.pre_restore_backup.path).read_text(encoding="utf-8"))
        self.assertEqual(loaded["builds"][0]["name"], "PC")

    def test_restore_failure_preserves_state(self):
        c = _comp(); b = Build(name="PC", component_ids=[c.id]); self._save([c], [b])
        backup_dir = self._base / "pre"; backup_dir.mkdir(parents=True, exist_ok=True)
        with self._env(self._base):
            s = InventoryService()
            with patch("pc_parts_organizer.service.create_pre_restore_backup", side_effect=StorageError("no backup")):
                with self.assertRaises(StorageError):
                    s.restore_inventory([_comp(model="X")], [])
            self.assertEqual(s.get_builds()[0].name, "PC")
            with patch("pc_parts_organizer.service.save_project_state", side_effect=StorageError("disk")):
                with self.assertRaises(StorageError):
                    s.restore_inventory([_comp(model="X")], [], pre_restore_backup_dir=backup_dir)
            self.assertEqual(s.get_builds()[0].name, "PC")
        self.assertTrue(any(backup_dir.glob("*.json")))

    def test_restore_rejects_invalid_cross_references(self):
        c = _comp(); self._save([c], [])
        bad = Build(name="Bad", component_ids=[str(uuid.uuid4())])
        with self._env(self._base):
            s = InventoryService()
            with self.assertRaises(ComponentNotFoundError):
                s.restore_inventory([c], [bad])
            self.assertEqual(s.get_components()[0].id, c.id)


if __name__ == "__main__":
    unittest.main()
