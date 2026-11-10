"""T17.13 stabilization: end-to-end regression tests (synthetic isolation only)."""
from __future__ import annotations

try:
    import tests._pcpo_test_isolation_bootstrap  # noqa: F401
except Exception:
    import _pcpo_test_isolation_bootstrap  # type: ignore  # noqa: F401

import unittest

from pc_parts_organizer.localization import Translator
from pc_parts_organizer.models import CATEGORIES, Component
from pc_parts_organizer.service import (
    BuildNameConflictError,
    ComponentAlreadyAssignedError,
    ComponentInUseError,
    ComponentNotFoundError,
    InventoryService,
    StorageError,
)
from pc_parts_organizer.storage import (
    export_project_state,
    read_inventory_file,
)
from pc_parts_organizer.technical_profiles import TechnicalAttribute, TechnicalProfile


def va(key, value, **kw):
    base = dict(source="official_vendor_doc", confidence="high",
                verification_status="verified", evidence_ref="https://vendor/doc",
                verified_at="2026-01-01")
    base.update(kw)
    return TechnicalAttribute(key=key, value=value, **base)


def _reset_isolated_state():
    """Wipe the isolated LOCALAPPDATA tree (test-only; bootstrap guarantees isolation)."""
    import os
    import shutil
    from pathlib import Path
    base = Path(os.environ["LOCALAPPDATA"]) / "PCPartsOrganizer"
    if base.exists():
        shutil.rmtree(base)


class TestInventoryFlows(unittest.TestCase):
    def setUp(self):
        _reset_isolated_state()
        self.svc = InventoryService()

    def test_all_categories_crud(self):
        ids = {}
        for cat in CATEGORIES:
            c = self.svc.add_component(cat, "M", f"M-{cat}", "s", "n")
            ids[cat] = c.id
        self.assertEqual(len(self.svc.get_components()), len(CATEGORIES))
        got = self.svc.get_component(ids["RAM"])
        self.assertEqual(got.model, "M-RAM")
        upd = self.svc.update_component(ids["RAM"], "RAM", "M2", "M-RAM", "s", "n")
        self.assertEqual(upd.manufacturer, "M2")
        self.svc.delete_component(ids["Monitor"])
        self.assertIsNone(self.svc.get_component(ids["Monitor"]))
        with self.assertRaises(ComponentNotFoundError):
            self.svc.delete_component(ids["Monitor"])

    def test_empty_profile_unsupported_category_contract(self):
        c = self.svc.add_component("Monitor", "M", "Mon", "", "")
        with self.assertRaises(StorageError):
            self.svc.set_technical_profile(TechnicalProfile(component_id=c.id, attributes=[]))

    def test_profile_lifecycle(self):
        c = self.svc.add_component("RAM", "M", "R", "", "")
        p = self.svc.set_technical_profile(TechnicalProfile(component_id=c.id, attributes=[
            va("memory_generation", "DDR5"), va("module_count", 2)]))
        self.assertEqual(len(p.attributes), 2)
        self.assertIsNotNone(self.svc.get_technical_profile(c.id))
        self.svc.delete_technical_profile(c.id)
        self.assertIsNone(self.svc.get_technical_profile(c.id))

    def test_build_lifecycle_and_guards(self):
        cpu = self.svc.add_component("CPU", "M", "C", "", "")
        mb = self.svc.add_component("Motherboard", "M", "B", "", "")
        b = self.svc.add_build("B1")
        self.svc.add_component_to_build(b.id, cpu.id)
        with self.assertRaises(ComponentAlreadyAssignedError):
            b2 = self.svc.add_build("B2")
            self.svc.add_component_to_build(b2.id, cpu.id)
        with self.assertRaises(ComponentInUseError):
            self.svc.delete_component(cpu.id)
        with self.assertRaises(BuildNameConflictError):
            self.svc.add_build("B1")
        self.svc.remove_component_from_build(b.id, cpu.id)
        self.svc.delete_component(cpu.id)
        self.assertIsNone(self.svc.get_component(cpu.id))
        self.svc.delete_build(b.id)
        self.assertIsNone(self.svc.get_build(b.id))
        void = self.svc.add_component("RAM", "M", "R", "", "")
        self.svc.delete_component(void.id)

    def test_compatibility_fresh_each_analysis(self):
        cpu = self.svc.add_component("CPU", "M", "C", "", "")
        mb = self.svc.add_component("Motherboard", "M", "B", "", "")
        self.svc.set_technical_profile(TechnicalProfile(component_id=cpu.id, attributes=[va("socket_designation", "AM5")]))
        self.svc.set_technical_profile(TechnicalProfile(component_id=mb.id, attributes=[va("socket_designation", "AM5")]))
        b = self.svc.add_build("CB")
        self.svc.add_component_to_build(b.id, cpu.id)
        self.svc.add_component_to_build(b.id, mb.id)
        r1 = self.svc.analyze_build_compatibility(b.id)
        self.assertEqual(len([f for f in r1.findings if f.rule_id == "cpu_mb.socket_visibility"]), 1)
        self.svc.set_technical_profile(TechnicalProfile(component_id=mb.id, attributes=[va("socket_designation", "LGA1700")]))
        r2 = self.svc.analyze_build_compatibility(b.id)
        f = [x for x in r2.findings if x.rule_id == "cpu_mb.socket_visibility"][0]
        self.assertEqual(f.message_params.get("reason"), "socket_mismatch_unresolved")


class TestExportRestoreFlows(unittest.TestCase):
    def setUp(self):
        _reset_isolated_state()
        self.svc = InventoryService()

    def test_export_reimport_restore_roundtrip(self):
        import tempfile
        from pathlib import Path
        c = self.svc.add_component("RAM", "M", "R", "", "")
        self.svc.set_technical_profile(TechnicalProfile(component_id=c.id, attributes=[va("memory_generation", "DDR4")]))
        b = self.svc.add_build("RB")
        self.svc.add_component_to_build(b.id, c.id)
        tmp = Path(tempfile.mkdtemp(prefix="PCPO-T1713-t-"))
        dest = tmp / "exp.json"
        info = export_project_state(self.svc.get_project_state(), str(dest))
        self.assertTrue(dest.exists())
        back = read_inventory_file(str(dest), expected_sha256=info.sha256)
        self.assertEqual(len(back.components), 1)
        res = self.svc.restore_inventory(back)
        self.assertEqual(res.restored_count, 1)
        self.assertTrue(Path(res.pre_restore_backup.path).exists())
        self.assertEqual(len(self.svc.get_components()), 1)

    def test_corrupt_and_empty_files_rejected(self):
        import tempfile
        from pathlib import Path
        tmp = Path(tempfile.mkdtemp(prefix="PCPO-T1713-t-"))
        bad = tmp / "bad.json"
        bad.write_text("{not json", encoding="utf-8")
        with self.assertRaises(StorageError):
            read_inventory_file(str(bad))
        empty = tmp / "empty.json"
        empty.write_text("", encoding="utf-8")
        with self.assertRaises(StorageError):
            read_inventory_file(str(empty))


class TestCatalogFlows(unittest.TestCase):
    def _svc(self):
        import tempfile
        from pathlib import Path
        from pc_parts_organizer.catalog_service import CatalogService
        from pc_parts_organizer.catalog_storage import CatalogStorage
        tmp = Path(tempfile.mkdtemp(prefix="PCPO-T1713-catdb-"))
        st = CatalogStorage(database_path=tmp / "catalog.sqlite3")
        st.initialize()
        return CatalogService(st)

    def test_crud_search_duplicates(self):
        from pc_parts_organizer.catalog_models import CatalogEntry
        from pc_parts_organizer.catalog_service import CatalogDuplicateError
        cs = self._svc()
        self.assertEqual(cs.count_entries(), 0)
        e = CatalogEntry(category="GPU", manufacturer="B", model="G1", specifications="s", notes="")
        cs.add_entry(e)
        self.assertEqual(cs.count_entries(), 1)
        self.assertEqual(cs.count_entries(query="G1"), 1)
        self.assertEqual(cs.count_entries(query="zzz-no-match"), 0)
        with self.assertRaises(CatalogDuplicateError):
            cs.add_entry(CatalogEntry(category="GPU", manufacturer="B", model="G1", specifications="s", notes=""))
        self.assertIsNotNone(cs.get_entry(e.id))
        cs.delete_entry(e.id)
        self.assertEqual(cs.count_entries(), 0)
        self.assertIsNone(cs.get_entry(e.id))

    def test_catalog_import_export_roundtrip(self):
        import tempfile
        from pathlib import Path
        from pc_parts_organizer.catalog_models import CatalogEntry
        cs = self._svc()
        cs.add_entry(CatalogEntry(category="RAM", manufacturer="B", model="D1", specifications="", notes=""))
        tmp = Path(tempfile.mkdtemp(prefix="PCPO-T1713-t-"))
        dest = tmp / "cat.json"
        self.assertEqual(cs.export_file(dest, "json"), 1)
        res = cs.import_file(dest, "json")
        self.assertEqual(res.total_entries, 1)
        self.assertEqual(res.duplicate_count, 1)
        bad = tmp / "bad.csv"
        bad.write_text("not;a;catalog", encoding="utf-8")
        from pc_parts_organizer.catalog_service import CatalogImportError
        with self.assertRaises(CatalogImportError):
            cs.import_file(bad, "csv")


class TestCatalogLanguageRefresh(unittest.TestCase):
    def test_rows_retranslated_on_language_switch(self):
        import tkinter as tk
        from pc_parts_organizer.catalog_models import CatalogEntry
        from pc_parts_organizer.catalog_service import CatalogService
        from pc_parts_organizer.catalog_storage import CatalogStorage
        from pc_parts_organizer.ui.catalog_manager import CatalogManagerView
        from pc_parts_organizer.ui.theme import configure_theme
        try:
            root = tk.Tk()
            root.withdraw()
        except tk.TclError as exc:
            self.skipTest(f"Tk unavailable: {exc}")
        try:
            configure_theme(root)
            tr = Translator()
            tr.set_language("es")
            st = CatalogStorage()
            st.initialize()
            for entry in st.search_entries(limit=None):
                st.delete_entry(entry.id)
            view = CatalogManagerView(root, CatalogService(st), tr)
            view.pack(fill="both", expand=True)
            root.update()
            entry = CatalogEntry(category="GPU", manufacturer="B", model="LG1", specifications="", notes="")
            view.catalog_service.add_entry(entry)
            view.refresh_results(reset_page=True)
            root.update()
            rows = view.tree.get_children()
            self.assertTrue(rows)
            es_cell = view.tree.item(rows[0], "values")[0]
            self.assertEqual(es_cell, tr.translate_category("GPU"))
            tr.set_language("en")
            view.set_translator(tr)
            root.update()
            rows = view.tree.get_children()
            self.assertTrue(rows)
            en_cell = view.tree.item(rows[0], "values")[0]
            self.assertEqual(en_cell, "Graphics card")
            self.assertNotEqual(es_cell, en_cell)
        finally:
            root.destroy()

    def test_static_contract_versions(self):
        from pc_parts_organizer.compatibility import ENGINE_RULESET_VERSION
        from pc_parts_organizer.technical_profiles import PROFILE_REGISTRY_VERSION, PROFILE_VERSION
        self.assertEqual(ENGINE_RULESET_VERSION, "t17.12-v1")
        self.assertEqual(PROFILE_VERSION, 2)
        self.assertEqual(PROFILE_REGISTRY_VERSION, 7)


if __name__ == "__main__":
    unittest.main()
