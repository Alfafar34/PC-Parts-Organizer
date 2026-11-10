"""Batch primitives, bulk conversion, and build sheets (T17.20).

Service tests run against isolated synthetic TEMP storage (fail-closed
bootstrap). No real data, no network, no commits.
"""

from __future__ import annotations

try:
    import tests._pcpo_test_isolation_bootstrap  # noqa: F401
except Exception:
    import _pcpo_test_isolation_bootstrap  # type: ignore  # noqa: F401

import json
import os
import string
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from pc_parts_organizer.build_audit import build_audit
from pc_parts_organizer.build_sheet import (
    export_build_sheet,
    render_build_sheet,
    sanitize_build_sheet_filename,
)
from pc_parts_organizer.catalog_models import CatalogEntry, catalog_duplicate_key
from pc_parts_organizer.models import Build, Component
from pc_parts_organizer.service import (
    BatchValidationError,
    InventoryService,
    StorageError,
)
from pc_parts_organizer.storage import save_project_state
from pc_parts_organizer.technical_profiles import TechnicalAttribute, TechnicalProfile


def _comp(**overrides):
    data = dict(
        category="CPU", manufacturer="AMD", model="Ryzen",
        specifications="", notes="",
    )
    data.update(overrides)
    return Component(**data)


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


class _ServiceCase(unittest.TestCase):
    def setUp(self):
        self._td = tempfile.TemporaryDirectory()
        self._base = Path(self._td.name)
        with patch.dict(os.environ, {"LOCALAPPDATA": str(self._base)}):
            save_project_state([], [], [])

    def tearDown(self):
        self._td.cleanup()

    def _service(self):
        with patch.dict(os.environ, {"LOCALAPPDATA": str(self._base)}):
            return InventoryService()

    def _patch_env(self):
        return patch.dict(os.environ, {"LOCALAPPDATA": str(self._base)})


class TestBatchAdd(_ServiceCase):
    def test_empty_batch_no_write(self):
        s = self._service()
        with patch("pc_parts_organizer.service.save_project_state") as sp:
            result = s.add_components([])
        self.assertEqual(result.created, [])
        self.assertEqual(result.duplicates, [])
        sp.assert_not_called()

    def test_single_valid_single_commit(self):
        s = self._service()
        with patch("pc_parts_organizer.service.save_project_state",
                   wraps=__import__("pc_parts_organizer.service", fromlist=["save_project_state"]).save_project_state) as sp:
            with self._patch_env():
                result = s.add_components([{"category": "GPU", "manufacturer": "N", "model": "X1"}])
        self.assertEqual(len(result.created), 1)
        self.assertEqual(sp.call_count, 1)

    def test_many_valid_single_commit_order_preserved(self):
        s = self._service()
        items = [{"category": "RAM", "manufacturer": "M", "model": f"S-{i}"} for i in range(5)]
        with patch("pc_parts_organizer.service.save_project_state",
                   wraps=__import__("pc_parts_organizer.service", fromlist=["save_project_state"]).save_project_state) as sp:
            with self._patch_env():
                result = s.add_components(items)
        self.assertEqual(sp.call_count, 1)
        self.assertEqual([c.model for c in result.created], [f"S-{i}" for i in range(5)])

    def test_duplicate_against_inventory_skipped_and_reported(self):
        c = _comp(manufacturer="Brand", model="X1", category="GPU")
        with self._patch_env():
            save_project_state([c], [], [])
        s = self._service()
        with self._patch_env():
            result = s.add_components([
                {"category": "GPU", "manufacturer": "brand", "model": "  X1 "},
                {"category": "GPU", "manufacturer": "Other", "model": "New"},
            ])
        self.assertEqual(len(result.created), 1)
        self.assertEqual(len(result.duplicates), 1)
        self.assertEqual(result.duplicates[0].index, 0)
        self.assertIn("Other", result.created[0].manufacturer)
        self.assertEqual(len(s.get_components()), 2)

    def test_internal_duplicates_keep_first_report_rest(self):
        s = self._service()
        with self._patch_env():
            result = s.add_components([
                {"category": "CPU", "manufacturer": "A  B", "model": "X1"},
                {"category": "CPU", "manufacturer": "a b", "model": "x1 "},
                {"category": "CPU", "manufacturer": "A  B", "model": "X1"},
            ])
        self.assertEqual(len(result.created), 1)
        self.assertEqual([d.index for d in result.duplicates], [1, 2])
        self.assertEqual(result.duplicates[0].matched_name, result.duplicates[1].matched_name)

    def test_same_maker_model_different_category_not_duplicate(self):
        s = self._service()
        with self._patch_env():
            result = s.add_components([
                {"category": "CPU", "manufacturer": "Acme", "model": "Z1"},
                {"category": "GPU", "manufacturer": "Acme", "model": "Z1"},
            ])
        self.assertEqual(len(result.created), 2)
        self.assertEqual(result.duplicates, [])

    def test_invalid_entry_aborts_whole_batch_zero_writes(self):
        for bad_pos in (0, 1, 2):
            s = self._service()
            items = [
                {"category": "CPU", "manufacturer": "A", "model": "M0"},
                {"category": "CPU", "manufacturer": "B", "model": "M1"},
                {"category": "CPU", "manufacturer": "C", "model": "M2"},
            ]
            items[bad_pos] = {"category": "Nope", "manufacturer": "", "model": ""}
            before = len(s.get_components())
            with patch("pc_parts_organizer.service.save_project_state") as sp:
                with self._patch_env():
                    with self.assertRaises(BatchValidationError) as ctx:
                        s.add_components(items)
            sp.assert_not_called()
            self.assertEqual(len(s.get_components()), before)
            self.assertTrue(ctx.exception.rejected)

    def test_non_mapping_item_rejected(self):
        s = self._service()
        with patch("pc_parts_organizer.service.save_project_state") as sp:
            with self._patch_env():
                with self.assertRaises(BatchValidationError):
                    s.add_components(["not-a-dict"])
        sp.assert_not_called()

    def test_persistence_failure_keeps_memory_unchanged(self):
        s = self._service()
        before = [c.model for c in s.get_components()]
        with patch("pc_parts_organizer.service.save_project_state", side_effect=StorageError("disk")):
            with self.assertRaises(StorageError):
                s.add_components([{"category": "CPU", "manufacturer": "A", "model": "M"}])
        self.assertEqual([c.model for c in s.get_components()], before)

    def test_profiles_preserved_on_add(self):
        c = _comp(category="RAM", manufacturer="M", model="Keep")
        with self._patch_env():
            save_project_state([c], [], [_ram_profile(c.id)])
        s = self._service()
        with self._patch_env():
            s.add_components([{"category": "CPU", "manufacturer": "A", "model": "New"}])
        self.assertEqual(len(s.get_technical_profiles()), 1)

    def test_duplicate_identity_matches_catalog_key(self):
        a = SimpleNamespace(category="CPU", manufacturer="A  B", model="X1")
        b = SimpleNamespace(category="CPU", manufacturer="a b", model="x1 ")
        self.assertEqual(catalog_duplicate_key(a), catalog_duplicate_key(b))
        e = CatalogEntry(category="CPU", manufacturer="A  B", model="X1")
        self.assertEqual(catalog_duplicate_key(e), catalog_duplicate_key(a))


class TestBatchDelete(_ServiceCase):
    def _seed(self, n_free=3, n_assigned=1):
        comps = [_comp(manufacturer="F", model=f"free-{i}") for i in range(n_free)]
        assigned = [_comp(manufacturer="A", model=f"asg-{i}") for i in range(n_assigned)]
        allc = comps + assigned
        builds = []
        if assigned:
            builds = [Build(name="Rig", component_ids=[c.id for c in assigned])]
        with self._patch_env():
            save_project_state(allc, builds, [])
        return comps, assigned

    def test_empty_selection_no_write(self):
        self._seed()
        s = self._service()
        with patch("pc_parts_organizer.service.save_project_state") as sp:
            result = s.delete_components([])
        self.assertEqual(result.deleted, [])
        sp.assert_not_called()

    def test_delete_free_single_commit(self):
        comps, _ = self._seed(n_free=2, n_assigned=0)
        s = self._service()
        with patch("pc_parts_organizer.service.save_project_state",
                   wraps=__import__("pc_parts_organizer.service", fromlist=["save_project_state"]).save_project_state) as sp:
            with self._patch_env():
                result = s.delete_components([c.id for c in comps])
        self.assertEqual(sp.call_count, 1)
        self.assertEqual(len(result.deleted), 2)
        self.assertEqual(s.get_components(), [])

    def test_assigned_kept_and_reported_with_build(self):
        comps, assigned = self._seed(n_free=1, n_assigned=1)
        s = self._service()
        with patch("pc_parts_organizer.service.save_project_state") as sp:
            with self._patch_env():
                result = s.delete_components([c.id for c in comps + assigned])
        sp.assert_called_once()
        self.assertEqual(len(result.deleted), 1)
        self.assertEqual(len(result.skipped_in_use), 1)
        self.assertEqual(result.skipped_in_use[0].build_name, "Rig")
        self.assertTrue(result.skipped_in_use[0].name)
        remaining = {c.id for c in s.get_components()}
        self.assertIn(assigned[0].id, remaining)

    def test_nothing_deletable_no_write(self):
        _, assigned = self._seed(n_free=0, n_assigned=1)
        s = self._service()
        with patch("pc_parts_organizer.service.save_project_state") as sp:
            with self._patch_env():
                result = s.delete_components([c.id for c in assigned])
        sp.assert_not_called()
        self.assertEqual(result.deleted, [])

    def test_unknown_and_repeated_ids_reported(self):
        comps, _ = self._seed(n_free=1, n_assigned=0)
        s = self._service()
        missing = "00000000-0000-4000-8000-000000000099"
        with self._patch_env():
            result = s.delete_components([comps[0].id, comps[0].id, missing])
        self.assertEqual(len(result.deleted), 1)
        self.assertEqual(result.not_found, [comps[0].id, missing])

    def test_assigned_across_builds_reported_per_build(self):
        a = _comp(manufacturer="A", model="one")
        b = _comp(manufacturer="B", model="two")
        builds = [Build(name="Alpha", component_ids=[a.id]), Build(name="Beta", component_ids=[b.id])]
        with self._patch_env():
            save_project_state([a, b], builds, [])
        s = self._service()
        with self._patch_env():
            result = s.delete_components([a.id, b.id])
        self.assertEqual(result.deleted, [])
        self.assertEqual({x.build_name for x in result.skipped_in_use}, {"Alpha", "Beta"})

    def test_profile_cleanup_on_delete(self):
        c = _comp(category="RAM", manufacturer="M", model="Gone")
        keep = _comp(category="RAM", manufacturer="M", model="Stay")
        with self._patch_env():
            save_project_state([c, keep], [], [_ram_profile(c.id), _ram_profile(keep.id)])
        s = self._service()
        with self._patch_env():
            s.delete_components([c.id])
        remaining = {p.component_id for p in s.get_technical_profiles()}
        self.assertEqual(remaining, {keep.id})

    def test_persistence_failure_keeps_memory(self):
        comps, _ = self._seed(n_free=2, n_assigned=0)
        s = self._service()
        before = {c.id for c in s.get_components()}
        with patch("pc_parts_organizer.service.save_project_state", side_effect=StorageError("disk")):
            with self.assertRaises(StorageError):
                s.delete_components([c.id for c in comps])
        self.assertEqual({c.id for c in s.get_components()}, before)


class TestCatalogBulkConversion(unittest.TestCase):
    def test_only_specs_and_notes_travel(self):
        from pc_parts_organizer.ui.main_window import MainWindow

        entry = CatalogEntry(
            category="GPU", manufacturer="N", model="X1",
            specifications="8GB", notes="shop note",
            source="Shop", source_url="https://example.com/x",
            source_license="MIT", attribution="shop",
            verified_at="2026-01-01",
        )
        item = MainWindow._catalog_entry_to_component_dict(entry)
        self.assertEqual(item, {
            "category": "GPU", "manufacturer": "N", "model": "X1",
            "specifications": "8GB", "notes": "shop note",
        })
        for forbidden in ("source", "source_url", "source_license", "attribution", "verified_at"):
            self.assertNotIn(forbidden, item)


class TestBuildSheet(unittest.TestCase):
    def _translator(self, language="es"):
        from pc_parts_organizer.localization import Translator

        with tempfile.TemporaryDirectory() as td:
            with patch.dict(os.environ, {"LOCALAPPDATA": td}):
                t = Translator()
                t.set_language(language)
                return t

    def _data(self):
        cpu = _comp(category="CPU", manufacturer="AMD", model="Ryzen ☃")
        gpu = _comp(category="GPU", manufacturer="N", model="X1",
                    specifications="8GB", notes="nota")
        build = Build(name="Mi Equipo / 01", component_ids=[cpu.id, gpu.id], notes="n")
        comps = {cpu.id: cpu, gpu.id: gpu}
        report = SimpleNamespace(
            overall_result="requires_verification", rules_evaluated=3,
            findings=[SimpleNamespace(
                rule_id="ram_mb.memory_generation", result="requires_verification",
                severity="warning", component_ids=[cpu.id],
                attributes_compared=["memory_generation"],
                message_key="x", message_params={"generation": "DDR4"},
                missing_information=["ram.memory_generation"],
                recommended_action="", evidence={"k": "v"})],
            not_evaluated_relations=[{"category": "Case", "reason": "no_applicable_rules"}],
            analysis_limitations=["empty_build"],
        )
        audit = SimpleNamespace(
            demonstrated=(), pending_verification=(), insufficient=(),
            not_evaluated=[{"category": "Case", "reason": "x"}],
            relevant_pending=[SimpleNamespace(component_id=cpu.id, key="memory_generation", status="unverified")],
            future_pending=(), inconsistent=(),
        )
        return build, comps, report, audit

    def test_markdown_and_text_render(self):
        t = self._translator("es")
        build, comps, report, audit = self._data()
        md = render_build_sheet(build, comps, report, audit, t, flavor="markdown")
        txt = render_build_sheet(build, comps, report, audit, t, flavor="text")
        for content in (md, txt):
            self.assertIn("Mi Equipo / 01", content)
            self.assertIn("Ryzen ☃", content)
            self.assertIn("8GB", content)
            self.assertNotIn("repr", content.lower())
        self.assertIn("#", md)
        self.assertNotIn("00000000", md)

    def test_empty_build(self):
        t = self._translator("en")
        build = Build(name="Empty")
        out = render_build_sheet(build, {}, SimpleNamespace(
            overall_result="insufficient_data", rules_evaluated=0, findings=[],
            not_evaluated_relations=[], analysis_limitations=[]),
            SimpleNamespace(demonstrated=(), pending_verification=(), insufficient=(),
                            not_evaluated=[], relevant_pending=(), future_pending=(),
                            inconsistent=()), t, flavor="text")
        self.assertIn("Empty", out)

    def test_export_atomic_and_refuses_active_path(self):
        t = self._translator("es")
        build, comps, report, audit = self._data()
        with tempfile.TemporaryDirectory() as td:
            dest = Path(td) / "sheet.md"
            out = export_build_sheet(build, comps, report, audit, t, dest, flavor="markdown")
            self.assertTrue(out.exists())
            self.assertIn("Mi Equipo", out.read_text(encoding="utf-8"))
            active = Path(td) / "components.json"
            active.write_text("{}", encoding="utf-8")
            with self.assertRaises(ValueError):
                export_build_sheet(build, comps, report, audit, t, active,
                                   flavor="markdown", active_inventory_path=active)

    def test_no_partial_file_on_encode_or_write_error(self):
        t = self._translator("es")
        build, comps, report, audit = self._data()
        with tempfile.TemporaryDirectory() as td:
            dest = Path(td) / "sub" / "sheet.md"
            with patch("pc_parts_organizer.build_sheet.render_build_sheet", side_effect=RuntimeError("boom")):
                with self.assertRaises(RuntimeError):
                    export_build_sheet(build, comps, report, audit, t, dest)
            self.assertFalse(dest.exists())

    def test_sanitize_filename(self):
        self.assertEqual(sanitize_build_sheet_filename('  Mi Equipo: 01/\\?* '), "Mi Equipo 01")
        self.assertEqual(sanitize_build_sheet_filename("   "), "build")
        self.assertTrue(len(sanitize_build_sheet_filename("x" * 200)) <= 80)

    def test_no_repr_or_uuid_leaks(self):
        import re
        import uuid

        from pc_parts_organizer.build_sheet import _render_evidence_lines

        t = self._translator("es")
        build, comps, report, audit = self._data()
        text = render_build_sheet(build, comps, report, audit, t, flavor="markdown")
        self.assertNotIn("object at 0x", text)
        self.assertNotIn("mappingproxy", text)
        for cid in comps:
            self.assertNotIn(cid, text)
        # evidence renderer maps component ids to labels, never raw UUIDs
        lines = _render_evidence_lines(
            {"ram_components": [{"id": next(iter(comps)), "attr": {"key": "x", "value": 1}}]},
            comps, t, "es", "  ")
        joined = "\n".join(lines)
        self.assertNotIn(next(iter(comps)), joined)
        self.assertNotIn("mappingproxy", joined)

    def test_build_audit_reuse(self):
        # build_sheet consumes precomputed report+audit; it must not run the
        # engine itself (no compatibility-engine imports).
        import inspect

        from pc_parts_organizer import build_sheet

        src = inspect.getsource(build_sheet)
        self.assertNotIn("from pc_parts_organizer.compatibility", src)
        self.assertNotIn("import pc_parts_organizer.compatibility", src)
        sig = inspect.signature(build_sheet.render_build_sheet)
        self.assertIn("report", sig.parameters)
        self.assertIn("audit", sig.parameters)


class TestInventoryBulkUI(unittest.TestCase):
    def setUp(self):
        import tkinter as tk

        from pc_parts_organizer.localization import Translator
        from pc_parts_organizer.ui.inventory_list_view import InventoryListView
        from pc_parts_organizer.ui.theme import configure_theme

        self.root = tk.Tk()
        self.root.withdraw()
        configure_theme(self.root)
        self.translator = Translator()
        self.view = InventoryListView(self.root, self.translator)
        self.view.grid(row=0, column=0)
        self.root.update_idletasks()

    def tearDown(self):
        try:
            self.root.update_idletasks()
        except Exception:
            pass
        try:
            self.root.destroy()
        except Exception:
            pass

    def _comps(self):
        return [SimpleNamespace(id=f"00000000-0000-4000-8000-00000000000{i}",
                                category="CPU", manufacturer="M", model=f"U{i}",
                                specifications="", notes="", location="",
                                status="unspecified", purchase_date="",
                                warranty_end_date="", purchase_price="",
                                purchase_currency="") for i in range(3)]

    def test_multi_selection_and_action_states(self):
        comps = self._comps()
        self.view.set_components(comps)
        self.root.update_idletasks()
        items = list(self.view.tree.get_children())
        self.assertEqual(len(items), 3)
        self.view.tree.selection_set(items[0])
        self.view._on_tree_select()
        self.assertEqual(self.view.get_selected_component_ids(), [comps[0].id])
        self.assertEqual(str(self.view.edit_button.cget("state")), "normal")
        self.view.tree.selection_set([items[0], items[2]])
        self.view._on_tree_select()
        self.assertEqual(set(self.view.get_selected_component_ids()), {comps[0].id, comps[2].id})
        self.assertEqual(str(self.view.edit_button.cget("state")), "disabled")
        self.assertEqual(str(self.view.bulk_delete_button.cget("state")), "normal")
        self.view.clear_selection()
        self.assertEqual(self.view.get_selected_component_ids(), [])
        self.assertEqual(str(self.view.bulk_delete_button.cget("state")), "disabled")

    def test_selection_preserved_across_filter_rerender(self):
        comps = self._comps()
        self.view.set_components(comps)
        self.root.update_idletasks()
        items = list(self.view.tree.get_children())
        self.view.tree.selection_set([items[0], items[1]])
        self.view._render_current_view(preserve_selection=True, preserve_scroll=False)
        self.assertEqual(set(self.view.get_selected_component_ids()), {comps[0].id, comps[1].id})


class TestCatalogSelectorMulti(unittest.TestCase):
    def setUp(self):
        import tkinter as tk

        from pc_parts_organizer.localization import Translator
        from pc_parts_organizer.ui.theme import configure_theme

        self.root = tk.Tk()
        self.root.withdraw()
        configure_theme(self.root)
        self.translator = Translator()

    def tearDown(self):
        try:
            self.root.update_idletasks()
        except Exception:
            pass
        try:
            self.root.destroy()
        except Exception:
            pass

    def _stub_service(self, entries):
        by_id = {e.id: e for e in entries}

        class Stub:
            def count_entries(self, query="", category=None):
                return len(entries)

            def search_entries(self, query="", category=None, limit=None, offset=0):
                return list(entries)

            def get_entry(self, entry_id):
                return by_id.get(entry_id)

        return Stub()

    def test_multi_keeps_selection_across_pages(self):
        from pc_parts_organizer.ui.catalog_selector import CatalogSelectorWindow

        entries = [CatalogEntry(category="CPU", manufacturer="M", model=f"U{i}") for i in range(3)]
        service = self._stub_service(entries)
        selector = CatalogSelectorWindow(self.root, service, self.translator, multi=True)
        try:
            self.assertEqual(str(selector.tree.cget("selectmode")), "extended")
            page_items = list(selector.tree.get_children())
            self.assertEqual(len(page_items), 3)
            selector.tree.selection_set([page_items[0], page_items[1]])
            selector._on_selection_changed()
            self.assertEqual(len(selector._selected_ids), 2)
            selector._begin_table_load([entries[2]], selector._load_token)
            selector._insert_entries([entries[2]], None)
            selector._finish_table_load(selector._load_token, None)
            self.assertEqual(len(selector._selected_ids), 2)
            page_items = list(selector.tree.get_children())
            selector.tree.selection_set(page_items)
            selector._on_selection_changed()
            self.assertEqual(len(selector._selected_ids), 3)
            selector._on_use_selected()
            self.assertEqual(len(selector.results), 3)
            self.assertEqual(len({e.id for e in selector.results}), 3)
        finally:
            try:
                selector.window.destroy()
            except Exception:
                pass

    def test_single_mode_unaffected(self):
        from pc_parts_organizer.ui.catalog_selector import CatalogSelectorWindow

        entries = [CatalogEntry(category="CPU", manufacturer="M", model="Solo")]
        selector = CatalogSelectorWindow(self.root, self._stub_service(entries), self.translator)
        try:
            self.assertEqual(str(selector.tree.cget("selectmode")), "browse")
            self.assertEqual(selector.results, [])
        finally:
            try:
                selector.window.destroy()
            except Exception:
                pass


class TestBulkResultDialog(unittest.TestCase):
    def setUp(self):
        import tkinter as tk

        from pc_parts_organizer.localization import Translator
        from pc_parts_organizer.ui.main_window import MainWindow
        from pc_parts_organizer.ui.theme import configure_theme

        self.root = tk.Tk()
        self.root.withdraw()
        configure_theme(self.root)
        self.mw = MainWindow.__new__(MainWindow)
        self.mw.root = self.root
        self.mw.translator = Translator()

    def tearDown(self):
        try:
            self.root.update_idletasks()
        except Exception:
            pass
        try:
            self.root.destroy()
        except Exception:
            pass

    def _add_result(self, n_created=15, n_dups=12):
        from pc_parts_organizer.service import BatchAddResult, BatchDuplicate

        created = [SimpleNamespace(manufacturer="M", model=f"New-{i}", id=f"id-{i}") for i in range(n_created)]
        dups = [BatchDuplicate(index=i, name=f"Dup-{i}", matched_name=f"Match-{i}") for i in range(n_dups)]
        return BatchAddResult(created=created, duplicates=dups)

    def test_catalog_lines_contain_everything_without_truncation(self):
        lines = self.mw._catalog_add_result_lines(self._add_result())
        self.assertEqual(len(lines), 1 + 15 + 12)
        self.assertNotIn("…", "\n".join(lines))
        for i in range(15):
            self.assertTrue(any(f"New-{i}" in line for line in lines), f"New-{i}")
        for i in range(12):
            self.assertTrue(any(f"Dup-{i}" in line and f"Match-{i}" in line for line in lines), f"Dup-{i}")

    def test_rejection_lines_cover_all_with_reasons(self):
        from pc_parts_organizer.service import BatchRejection

        rejected = [BatchRejection(index=i, name=f"Bad-{i}", reason=f"why-{i}") for i in range(14)]
        lines = self.mw._catalog_rejection_lines(rejected)
        self.assertEqual(len(lines), 14)
        for i in range(14):
            self.assertTrue(any(f"Bad-{i}" in line and f"why-{i}" in line for line in lines))

    def test_bulk_delete_lines_cover_all_with_builds(self):
        from pc_parts_organizer.service import BatchDeleteResult, BatchSkipped

        deleted = [SimpleNamespace(manufacturer="D", model=f"Gone-{i}", id=f"g-{i}") for i in range(11)]
        skipped = [BatchSkipped(component_id=f"s-{i}", name=f"Kept-{i}", build_name=f"Rig-{i % 2}")
                   for i in range(11)]
        result = BatchDeleteResult(deleted=deleted, skipped_in_use=skipped, not_found=["missing-1"])
        lines = self.mw._bulk_delete_result_lines(result)
        self.assertEqual(len(lines), 1 + 11 + 11 + 1)
        self.assertNotIn("…", "\n".join(lines))
        self.assertTrue(any("Kept-3" in line and "Rig-1" in line for line in lines))
        self.assertTrue(any("missing-1" in line for line in lines))

    def test_confirm_dialog_lists_all_protected(self):
        seen: dict = {}

        def driver(left: int = 5) -> None:
            seen["visits"] = seen.get("visits", 0) + 1
            confirm_btn = None
            for w in self.root.winfo_children():
                try:
                    if w.winfo_class() == "Toplevel":
                        stack = list(w.winfo_children())
                        while stack:
                            x = stack.pop(0)
                            try:
                                if x.winfo_class() == "Text":
                                    seen["body"] = x.get("1.0", "end")
                                if x.winfo_class() == "TButton" and "Eliminar" in str(x.cget("text")):
                                    confirm_btn = x
                            except Exception:
                                pass
                            try:
                                stack.extend(x.winfo_children())
                            except Exception:
                                pass
                except Exception:
                    pass
            if confirm_btn is not None:
                confirm_btn.invoke()
                return
            if left > 0:
                self.root.after(200, lambda: driver(left - 1))

        lines = [f"Protegido: N-{i} — Rig-{i}" for i in range(12)]
        self.root.after(300, driver)
        confirmed = self.mw._confirm_bulk_delete(14, 2, lines)
        self.assertTrue(confirmed)
        self.assertIn("body", seen)
        for i in range(12):
            self.assertIn(f"N-{i}", seen["body"])
        self.assertNotIn("…", seen["body"])

    def test_dialog_shows_full_scrollable_text(self):
        lines = self.mw._catalog_add_result_lines(self._add_result())
        dialog = self.mw._show_bulk_result("T", lines[0], lines, "Cerrar")
        try:
            texts = [w for w in dialog.winfo_children()[0].winfo_children()
                     if w.winfo_class() == "Text"]
            self.assertTrue(texts)
            content = texts[0].get("1.0", "end")
            for i in (0, 7, 14):
                self.assertIn(f"New-{i}", content)
            for i in (0, 11):
                self.assertIn(f"Dup-{i}", content)
        finally:
            dialog.destroy()


class TestBulkLocales(unittest.TestCase):
    def test_parity_and_placeholders(self):
        repo = Path(__file__).resolve().parents[1] / "pc_parts_organizer" / "locales"
        es = json.load(open(repo / "es.json", encoding="utf-8"))
        en = json.load(open(repo / "en.json", encoding="utf-8"))

        def collect(data, prefix=""):
            out = set()
            if isinstance(data, dict):
                for k, v in data.items():
                    full = f"{prefix}.{k}" if prefix else k
                    if isinstance(v, dict):
                        out.update(collect(v, full))
                    else:
                        out.add(full)
            return out

        self.assertEqual(collect(es), collect(en))
        for section in ("catalog_bulk", "bulk", "build_sheet"):
            self.assertIn(section, es)
            self.assertIn(section, en)
        for key in ("actions.add_from_catalog", "actions.delete_selected",
                    "catalog_selector.multi_title", "catalog_selector.selection_count",
                    "catalog_selector.use_selected_multi", "catalog_bulk.result",
                    "catalog_bulk.created_line", "catalog_bulk.rejected_line",
                    "catalog_bulk.duplicate_line", "catalog_bulk.close",
                    "bulk.delete_confirm", "bulk.result", "bulk.deleted_line",
                    "bulk.skipped_line", "bulk.not_found_line", "bulk.close",
                    "build_sheet.success"):
            cur_es, cur_en = es, en
            for part in key.split("."):
                cur_es, cur_en = cur_es[part], cur_en[part]
            pe = {f for _, f, _, _ in string.Formatter().parse(cur_en) if f}
            ps = {f for _, f, _, _ in string.Formatter().parse(cur_es) if f}
            self.assertEqual(pe, ps, key)


if __name__ == "__main__":
    unittest.main()
