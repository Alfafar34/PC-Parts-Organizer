"""T17.2 technical profile UI/contracts tests."""

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
from types import SimpleNamespace
from unittest.mock import patch

import tkinter as tk

from pc_parts_organizer.localization import Translator
from pc_parts_organizer.models import Component
from pc_parts_organizer.service import InventoryService, StorageError
from pc_parts_organizer.storage import (
    ProjectState,
    create_pre_restore_backup,
    export_inventory,
    export_project_state,
    read_inventory_file,
    save_project_state,
)
from pc_parts_organizer.technical_profiles import (
    TechnicalAttribute,
    TechnicalProfile,
    TechnicalProfileValidationError,
)
from pc_parts_organizer.ui.inventory_detail_view import InventoryDetailView
from pc_parts_organizer.ui.technical_profile_form import TechnicalProfileForm
from pc_parts_organizer.ui.theme import configure_theme


def _comp(category="RAM", **o):
    d = dict(category=category, manufacturer="M", model="X", specifications="", notes="")
    d.update(o)
    return Component(**d)


def _ram_profile(cid, status="unverified", evidence=None, verified_at=None):
    return TechnicalProfile(
        component_id=cid,
        attributes=[TechnicalAttribute(
            key="memory_generation", value="DDR4", source="user_input", confidence="medium",
            verification_status=status, evidence_ref=evidence, verified_at=verified_at,
        )],
    )


class TechnicalProfilePresentationTests(unittest.TestCase):
    def setUp(self):
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

    def _view(self, **cb):
        v = InventoryDetailView(self.root, self.translator, **cb)
        v.grid(row=0, column=0)
        self.root.update_idletasks()
        return v

    def test_no_profile_supported_category(self):
        v = self._view()
        c = _comp("RAM")
        v.set_component(c)
        v.set_technical_profile(None)
        self.assertIn(self.translator.t("technical_profile.empty"), v._tech_status_label.cget("text"))
        self.assertEqual(str(v._tech_add_btn.cget("state")), "normal")
        self.assertEqual(str(v._tech_edit_btn.cget("state")), "disabled")

    def test_profile_unverified_and_verified_states(self):
        c = _comp("RAM")
        v = self._view()
        v.set_component(c)
        v.set_technical_profile(_ram_profile(c.id, "unverified"))
        self.assertIn(self.translator.t("technical_profile.status_unverified"), v._tech_status_label.cget("text"))
        v.set_technical_profile(_ram_profile(c.id, "verified", "https://vendor.example/ds", "2026-01-02"))
        self.assertIn(self.translator.t("technical_profile.status_verified"), v._tech_status_label.cget("text"))
        txt = v._tech_text.get("1.0", "end-1c")
        self.assertIn("DDR4", txt)
        self.assertIn("https://vendor.example/ds", txt)

    def test_needs_review_and_empty_profile_attributes(self):
        c = _comp("RAM")
        v = self._view()
        v.set_component(c)
        p = TechnicalProfile(component_id=c.id, attributes=[TechnicalAttribute(key="memory_generation", value="DDR4", verification_status="needs_review")])
        v.set_technical_profile(p)
        self.assertIn(self.translator.t("technical_profile.status_needs_review"), v._tech_status_label.cget("text"))
        empty_p = TechnicalProfile(component_id=c.id, attributes=[])
        v.set_technical_profile(empty_p)
        self.assertIn(self.translator.t("technical_profile.no_attributes"), v._tech_status_label.cget("text"))

    def test_unsupported_category(self):
        c = _comp("Monitor")
        v = self._view()
        v.set_component(c)
        v.set_technical_profile(None)
        self.assertIn(self.translator.t("technical_profile.unsupported"), v._tech_status_label.cget("text"))
        self.assertEqual(str(v._tech_add_btn.cget("state")), "disabled")

    def test_cpu_category_now_supported(self):
        c = _comp("CPU")
        v = self._view()
        v.set_component(c)
        v.set_technical_profile(None)
        self.assertIn(self.translator.t("technical_profile.empty"), v._tech_status_label.cget("text"))
        self.assertEqual(str(v._tech_add_btn.cget("state")), "normal")


class TechnicalProfileFormTests(unittest.TestCase):
    def setUp(self):
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

    def test_cancel_makes_no_result(self):
        cid = str(uuid.uuid4())
        f = TechnicalProfileForm(self.root, self.translator, component_id=cid, category="RAM", profile=None)
        f._on_cancel()
        self.assertIsNone(f.result)

    def test_create_saves_selected_attribute_transactionally_as_result(self):
        cid = str(uuid.uuid4())
        f = TechnicalProfileForm(self.root, self.translator, component_id=cid, category="RAM", profile=None)
        row = f._rows["memory_generation"]
        row["enabled"].set(True)
        row["value"][1].set("DDR5")
        # disable others to keep form simple
        for k, r in f._rows.items():
            if k != "memory_generation":
                r["enabled"].set(False)
        f._on_save()
        self.assertIsNotNone(f.result)
        assert f.result is not None
        self.assertEqual(f.result.component_id, cid)
        self.assertEqual(len(f.result.attributes), 1)
        self.assertEqual(f.result.attributes[0].key, "memory_generation")
        self.assertEqual(f.result.attributes[0].value, "DDR5")
        self.assertEqual(f.result.attributes[0].verification_status, "unverified")

    def test_verified_requires_evidence_in_form(self):
        cid = str(uuid.uuid4())
        f = TechnicalProfileForm(self.root, self.translator, component_id=cid, category="RAM", profile=None)
        row = f._rows["memory_generation"]
        row["enabled"].set(True)
        row["value"][1].set("DDR4")
        for k, r in f._rows.items():
            if k != "memory_generation":
                r["enabled"].set(False)
        row["verification"].set(self.translator.t("technical_profile.status_verified"))
        with patch("pc_parts_organizer.ui.technical_profile_form.messagebox.showerror") as m:
            f._on_save()
        self.assertTrue(m.called)
        self.assertIsNone(f.result)

    def test_edit_preserves_existing_evidence_and_removes_attribute(self):
        cid = str(uuid.uuid4())
        existing = TechnicalProfile(component_id=cid, attributes=[
            TechnicalAttribute(key="memory_generation", value="DDR4", original_value="orig", evidence_ref="ref://x", source="catalog_import", confidence="high", verification_status="needs_review"),
            TechnicalAttribute(key="module_count", value=2),
        ])
        f = TechnicalProfileForm(self.root, self.translator, component_id=cid, category="RAM", profile=existing)
        self.assertTrue(f._rows["memory_generation"]["enabled"].get())
        self.assertEqual(f._rows["memory_generation"]["original"].get(), "orig")
        self.assertEqual(f._rows["memory_generation"]["evidence"].get(), "ref://x")
        # remove module_count, keep memory_generation
        f._rows["module_count"]["enabled"].set(False)
        for k, r in f._rows.items():
            if k not in ("memory_generation", "module_count"):
                r["enabled"].set(False)
        f._on_save()
        assert f.result is not None
        keys = [a.key for a in f.result.attributes]
        self.assertEqual(keys, ["memory_generation"])
        a = f.result.attributes[0]
        self.assertEqual(a.original_value, "orig")
        self.assertEqual(a.evidence_ref, "ref://x")
        self.assertEqual(a.source, "catalog_import")
        self.assertEqual(a.confidence, "high")

    def test_invalid_integer_rejected(self):
        cid = str(uuid.uuid4())
        f = TechnicalProfileForm(self.root, self.translator, component_id=cid, category="RAM", profile=None)
        row = f._rows["module_count"]
        row["enabled"].set(True)
        row["value"][1].delete(0, "end")
        row["value"][1].insert(0, "abc")
        for k, r in f._rows.items():
            if k != "module_count":
                r["enabled"].set(False)
        with patch("pc_parts_organizer.ui.technical_profile_form.messagebox.showerror") as m:
            f._on_save()
        self.assertTrue(m.called)
        self.assertIsNone(f.result)


class TechnicalProfileVerificationContractTests(unittest.TestCase):
    def test_new_data_defaults_unverified(self):
        a = TechnicalAttribute(key="memory_generation", value="DDR4")
        self.assertEqual(a.source, "user_input")
        self.assertEqual(a.confidence, "medium")
        self.assertEqual(a.verification_status, "unverified")

    def test_verified_requires_evidence_and_date(self):
        with self.assertRaises(TechnicalProfileValidationError):
            TechnicalAttribute(key="memory_generation", value="DDR4", verification_status="verified")
        with self.assertRaises(TechnicalProfileValidationError):
            TechnicalAttribute(key="memory_generation", value="DDR4", verification_status="verified", evidence_ref="ref", verified_at="bad")
        TechnicalAttribute(key="memory_generation", value="DDR4", verification_status="verified", evidence_ref="https://x", verified_at="2026-01-02")

    def test_confidence_not_verification(self):
        a = TechnicalAttribute(key="memory_generation", value="DDR4", confidence="high", verification_status="unverified")
        self.assertEqual(a.confidence, "high")
        self.assertEqual(a.verification_status, "unverified")


class TechnicalProfileTransactionAndExportTests(unittest.TestCase):
    def _env(self, base):
        return patch.dict(os.environ, {"LOCALAPPDATA": str(base)})

    def test_service_save_persists_profile_and_cancel_does_not(self):
        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
            c = _comp("RAM")
            with self._env(base):
                save_project_state([c], [], [])
                s = InventoryService()
                s.set_technical_profile(_ram_profile(c.id))
            with self._env(base):
                s2 = InventoryService()
                self.assertIsNotNone(s2.get_technical_profile(c.id))
        # cancel simulated by never calling service
        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
            c = _comp("RAM")
            with self._env(base):
                save_project_state([c], [], [])
            with self._env(base):
                s2 = InventoryService()
                self.assertIsNone(s2.get_technical_profile(c.id))

    def test_delete_profile_not_component(self):
        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
            c = _comp("RAM")
            with self._env(base):
                save_project_state([c], [], [_ram_profile(c.id)])
                s = InventoryService()
                s.delete_technical_profile(c.id)
                self.assertIsNone(s.get_technical_profile(c.id))
                self.assertIsNotNone(s.get_component(c.id))

    def test_persistence_error_leaves_memory_intact(self):
        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
            c = _comp("RAM")
            with self._env(base):
                save_project_state([c], [], [])
                s = InventoryService()
                with patch("pc_parts_organizer.service.save_project_state", side_effect=StorageError("boom")):
                    with self.assertRaises(StorageError):
                        s.set_technical_profile(_ram_profile(c.id))
                self.assertIsNone(s.get_technical_profile(c.id))

    def test_export_project_state_api_is_unambiguous_and_complete(self):
        c = _comp("RAM")
        state = ProjectState(components=[c], builds=[], technical_profiles=[_ram_profile(c.id)], schema_version=4)
        with tempfile.TemporaryDirectory() as td:
            dest = Path(td) / "b.json"
            info = export_project_state(state, dest)
            self.assertEqual(len(info.technical_profiles), 1)
            # legacy snapshot API still works
            dest2 = Path(td) / "c.json"
            info2 = export_inventory([c], dest2, builds=[], technical_profiles=[_ram_profile(c.id)])
            self.assertEqual(len(info2.technical_profiles), 1)

    def test_prebackup_accepts_project_state(self):
        c = _comp("RAM")
        state = ProjectState(components=[c], builds=[], technical_profiles=[_ram_profile(c.id)], schema_version=4)
        with tempfile.TemporaryDirectory() as td:
            info = create_pre_restore_backup(state, directory=td)
            loaded = read_inventory_file(info.path)
            self.assertEqual(len(loaded.technical_profiles), 1)


class TechnicalProfileCompletenessFormTests(unittest.TestCase):
    def setUp(self):
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

    def _form(self, category, profile=None):
        return TechnicalProfileForm(self.root, self.translator, component_id=str(uuid.uuid4()),
                                    category=category, profile=profile)

    def test_only_eligible_attrs_show_completeness(self):
        f = self._form("Motherboard")
        self.assertIsNotNone(f._rows["m2_slots"].get("completeness"))
        self.assertIsNotNone(f._rows["sata_port_identifiers"].get("completeness"))
        self.assertIsNone(f._rows["sata_port_count"].get("completeness"))
        f._on_cancel()
        g = self._form("PSU")
        self.assertIsNotNone(g._rows["power_cable_assemblies"].get("completeness"))
        g._on_cancel()

    def test_complete_requires_verified_high_evidence_scope(self):
        f = self._form("Motherboard")
        row = f._rows["m2_slots"]
        row["enabled"].set(True)
        for k, r in f._rows.items():
            if k != "m2_slots":
                r["enabled"].set(False)
        row["verification"].set(self.translator.t("technical_profile.status_verified"))
        row["confidence"].set(self.translator.t("technical_profile.confidence_levels.high"))
        row["evidence"].delete(0, "end")
        row["verified_at"].delete(0, "end")
        row["verified_at"].insert(0, "2026-01-01")
        row["completeness"].set(self.translator.t("technical_profile.completeness_complete"))
        row["scope"].delete(0, "end")
        row["scope"].insert(0, "All slots")
        with patch("pc_parts_organizer.ui.technical_profile_form.messagebox.showerror") as m:
            f._on_save()
        self.assertTrue(m.called)
        self.assertIsNone(f.result)

    def test_complete_save_persists_metadata(self):
        from pc_parts_organizer.technical_profiles import M2SlotSpec
        f = self._form("Motherboard")
        row = f._rows["m2_slots"]
        row["enabled"].set(True)
        for k, r in f._rows.items():
            if k != "m2_slots":
                r["enabled"].set(False)
        state = row["value"][2]
        state["items"].append(M2SlotSpec.from_dict({
            "slot_id": "M2_1", "accepted_module_keyings": ["M"],
            "supported_lengths": ["2280"], "supported_modes": ["pcie_nvme"],
            "evidence_ref": "https://vendor/slot"}))
        row["verification"].set(self.translator.t("technical_profile.status_verified"))
        row["confidence"].set(self.translator.t("technical_profile.confidence_levels.high"))
        row["evidence"].delete(0, "end")
        row["evidence"].insert(0, "https://vendor/doc")
        row["verified_at"].delete(0, "end")
        row["verified_at"].insert(0, "2026-01-01")
        row["completeness"].set(self.translator.t("technical_profile.completeness_complete"))
        row["scope"].delete(0, "end")
        row["scope"].insert(0, "All physical M.2 slots")
        with patch("pc_parts_organizer.ui.technical_profile_form.messagebox.showerror") as m:
            f._on_save()
        self.assertFalse(m.called)
        self.assertIsNotNone(f.result)
        assert f.result is not None
        attr = next(a for a in f.result.attributes if a.key == "m2_slots")
        self.assertEqual(attr.collection_completeness, "complete")
        self.assertEqual(attr.completeness_scope, "All physical M.2 slots")

    def test_partial_without_scope_rejected(self):
        from pc_parts_organizer.technical_profiles import M2SlotSpec
        f = self._form("Motherboard")
        row = f._rows["m2_slots"]
        row["enabled"].set(True)
        for k, r in f._rows.items():
            if k != "m2_slots":
                r["enabled"].set(False)
        state = row["value"][2]
        state["items"].append(M2SlotSpec.from_dict({
            "slot_id": "M2_1", "accepted_module_keyings": ["M"],
            "supported_lengths": ["2280"], "supported_modes": ["pcie_nvme"]}))
        row["completeness"].set(self.translator.t("technical_profile.completeness_partial"))
        row["scope"].delete(0, "end")
        with patch("pc_parts_organizer.ui.technical_profile_form.messagebox.showerror") as m:
            f._on_save()
        self.assertTrue(m.called)
        self.assertIsNone(f.result)

    def test_empty_complete_inventory_save(self):
        f = self._form("Motherboard")
        row = f._rows["m2_slots"]
        row["enabled"].set(True)
        for k, r in f._rows.items():
            if k != "m2_slots":
                r["enabled"].set(False)
        row["verification"].set(self.translator.t("technical_profile.status_verified"))
        row["confidence"].set(self.translator.t("technical_profile.confidence_levels.high"))
        row["evidence"].delete(0, "end")
        row["evidence"].insert(0, "https://vendor/doc")
        row["verified_at"].delete(0, "end")
        row["verified_at"].insert(0, "2026-01-01")
        row["completeness"].set(self.translator.t("technical_profile.completeness_complete"))
        row["scope"].delete(0, "end")
        row["scope"].insert(0, "All physical M.2 slots")
        with patch("pc_parts_organizer.ui.technical_profile_form.messagebox.showerror") as m:
            f._on_save()
        self.assertFalse(m.called)
        self.assertIsNotNone(f.result)
        assert f.result is not None
        attr = next(a for a in f.result.attributes if a.key == "m2_slots")
        self.assertEqual(attr.value, [])
        self.assertEqual(attr.collection_completeness, "complete")

    def test_cancel_does_not_modify(self):
        cid = str(uuid.uuid4())
        f = TechnicalProfileForm(self.root, self.translator, component_id=cid, category="Motherboard", profile=None)
        f._on_cancel()
        self.assertIsNone(f.result)


if __name__ == "__main__":
    unittest.main()
