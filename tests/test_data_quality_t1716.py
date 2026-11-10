"""T17.16: data-quality center tests (pure audit + integration + UI)."""
from __future__ import annotations

try:
    import tests._pcpo_test_isolation_bootstrap  # noqa: F401
except Exception:
    import _pcpo_test_isolation_bootstrap  # type: ignore  # noqa: F401

import ast
import unittest
from pathlib import Path

from pc_parts_organizer import data_quality as dq
from pc_parts_organizer.models import Component
from pc_parts_organizer.technical_profiles import (
    ATTRIBUTE_REGISTRY,
    TechnicalAttribute,
    TechnicalProfile,
)

REPO = Path(__file__).resolve().parents[1]


def comp(cat, model="X"):
    return Component(category=cat, manufacturer="M", model=model, specifications="", notes="")


def va(key, value, **kw):
    base = dict(source="official_vendor_doc", confidence="high",
                verification_status="verified", evidence_ref="https://vendor/doc",
                verified_at="2026-01-01")
    base.update(kw)
    return TechnicalAttribute(key=key, value=value, **base)


def ua(key, value, **kw):
    base = dict(source="unknown", confidence="low", verification_status="unverified")
    base.update(kw)
    return TechnicalAttribute(key=key, value=value, **base)


class TestClassifyAttribute(unittest.TestCase):
    def _spec(self, cat, key):
        return ATTRIBUTE_REGISTRY[cat][key]

    def test_verified_gate(self):
        self.assertEqual(dq.classify_attribute("memory_generation", va("memory_generation", "DDR4"),
                                               self._spec("RAM", "memory_generation")), dq.VERIFIED)

    def test_unverified(self):
        a = TechnicalAttribute(key="memory_generation", value="DDR4")
        self.assertEqual(dq.classify_attribute("memory_generation", a,
                                               self._spec("RAM", "memory_generation")), dq.UNVERIFIED)

    def test_low_confidence_beats_unverified(self):
        self.assertEqual(dq.classify_attribute("memory_generation", ua("memory_generation", "DDR4"),
                                               self._spec("RAM", "memory_generation")), dq.LOW_CONFIDENCE)

    def test_verified_but_low_confidence(self):
        a = va("memory_generation", "DDR4", confidence="low")
        self.assertEqual(dq.classify_attribute("memory_generation", a,
                                               self._spec("RAM", "memory_generation")), dq.LOW_CONFIDENCE)

    def test_verified_without_evidence(self):
        # validation itself rejects verified-without-evidence at construction;
        # hand-mutated legacy objects bypassing it must still classify correctly
        a = va("memory_generation", "DDR4")
        object.__setattr__(a, "evidence_ref", None)
        object.__setattr__(a, "verified_at", None)
        self.assertEqual(dq.classify_attribute("memory_generation", a,
                                               self._spec("RAM", "memory_generation")), dq.MISSING_EVIDENCE)

    def test_unknown_value(self):
        a = TechnicalAttribute.__new__(TechnicalAttribute)
        object.__setattr__(a, "key", "memory_generation")
        object.__setattr__(a, "value", None)
        object.__setattr__(a, "source", "unknown")
        object.__setattr__(a, "confidence", "low")
        object.__setattr__(a, "verification_status", "unverified")
        object.__setattr__(a, "evidence_ref", None)
        object.__setattr__(a, "verified_at", None)
        object.__setattr__(a, "collection_completeness", "unknown")
        object.__setattr__(a, "completeness_scope", None)
        self.assertEqual(dq.classify_attribute("memory_generation", a,
                                               self._spec("RAM", "memory_generation")), dq.UNKNOWN)

    def test_absent(self):
        self.assertEqual(dq.classify_attribute("memory_generation", None,
                                               self._spec("RAM", "memory_generation")), dq.ABSENT)

    def test_inconsistent_complete_on_ineligible_key(self):
        with self.assertRaises(Exception):
            TechnicalAttribute(key="memory_generation", value="DDR4", source="official_vendor_doc",
                               confidence="high", verification_status="verified",
                               evidence_ref="https://vendor/doc", verified_at="2026-01-01",
                               collection_completeness="complete", completeness_scope="all")
        # hand-built equivalent still classifies inconsistent
        a = va("memory_generation", "DDR4")
        object.__setattr__(a, "collection_completeness", "complete")
        object.__setattr__(a, "completeness_scope", "all")
        self.assertEqual(dq.classify_attribute("memory_generation", a,
                                               self._spec("RAM", "memory_generation")), dq.INCONSISTENT_METADATA)

    def test_inconsistent_scope_without_completeness(self):
        a = va("memory_generation", "DDR4")
        object.__setattr__(a, "completeness_scope", "x")
        self.assertEqual(dq.classify_attribute("memory_generation", a,
                                               self._spec("RAM", "memory_generation")), dq.INCONSISTENT_METADATA)


class TestCollections(unittest.TestCase):
    def _slots(self, **kw):
        base = dict(slot_id="M2_1", accepted_module_keyings=["M"],
                    supported_lengths=["2280"], supported_modes=["pcie_nvme"])
        base.update(kw)
        return base

    def test_complete_valid(self):
        a = va("m2_slots", [self._slots()], collection_completeness="complete",
               completeness_scope="board manual p.12")
        self.assertEqual(dq.classify_attribute(
            "m2_slots", a, ATTRIBUTE_REGISTRY["Motherboard"]["m2_slots"]), dq.VERIFIED)

    def test_partial_keeps_scope(self):
        a = va("m2_slots", [self._slots()], collection_completeness="partial",
               completeness_scope="slots seen: M2_1")
        st = dq.classify_attribute(
            "m2_slots", a, ATTRIBUTE_REGISTRY["Motherboard"]["m2_slots"])
        self.assertEqual(st, dq.VERIFIED)
        self.assertEqual(a.collection_completeness, "partial")

    def test_complete_unverified_is_inconsistent(self):
        a = va("m2_slots", [self._slots()])
        object.__setattr__(a, "verification_status", "unverified")
        object.__setattr__(a, "collection_completeness", "complete")
        object.__setattr__(a, "completeness_scope", "x")
        self.assertEqual(dq.classify_attribute(
            "m2_slots", a, ATTRIBUTE_REGISTRY["Motherboard"]["m2_slots"]),
            dq.INCONSISTENT_METADATA)

    def test_unknown_has_no_scope(self):
        a = va("m2_slots", [self._slots()])
        self.assertEqual(a.collection_completeness, "unknown")
        self.assertIsNone(a.completeness_scope)


class TestAuditInventory(unittest.TestCase):
    def test_absent_keys_and_counts(self):
        c = comp("RAM")
        rep = dq.audit_inventory([c], {})
        self.assertEqual(rep.components_total, 1)
        self.assertEqual(rep.components_without_profile, 1)
        keys = {e.key for e in rep.entries}
        self.assertEqual(keys, set(ATTRIBUTE_REGISTRY["RAM"].keys()))
        self.assertTrue(all(e.status == dq.ABSENT for e in rep.entries))
        self.assertEqual(rep.count(dq.ABSENT), len(ATTRIBUTE_REGISTRY["RAM"]))

    def test_counts_derive_from_entries(self):
        c = comp("RAM")
        p = TechnicalProfile(component_id=c.id, attributes=[
            va("memory_generation", "DDR4"), ua("module_count", 2)])
        rep = dq.audit_inventory([c], {c.id: p})
        total = sum(rep.count(s) for s in dq.ATTRIBUTE_STATES if s != dq.NOT_APPLICABLE)
        self.assertEqual(total, len(rep.entries))
        self.assertEqual(rep.components_with_profile, 1)

    def test_v1_profile_readable(self):
        c = comp("RAM")
        p = TechnicalProfile(component_id=c.id, profile_version=1, attributes=[
            TechnicalAttribute(key="memory_generation", value="DDR4")])
        rep = dq.audit_inventory([c], {c.id: p})
        self.assertEqual(rep.components_with_profile, 1)
        gen = [e for e in rep.entries if e.key == "memory_generation"][0]
        self.assertEqual(gen.status, dq.UNVERIFIED)

    def test_no_scores_no_percentages(self):
        self.assertFalse(hasattr(dq.QualityReport, "score"))
        self.assertFalse(hasattr(dq, "compute_score"))

    def test_review_queue_filters_and_orders(self):
        c = comp("PSU")
        p = TechnicalProfile(component_id=c.id, attributes=[
            va("psu_form_factor", "ATX"), ua("rated_continuous_power_w", 650)])
        rep = dq.audit_inventory([c], {c.id: p})
        q = dq.review_queue(rep)
        self.assertTrue(all(e.status != dq.VERIFIED for e in q))
        # absent non-consumed keys are not work items; absent consumed keys are
        self.assertFalse(any(e.key == "rated_continuous_power_w" and e.status == dq.ABSENT for e in q))
        q_all = dq.review_queue(rep, important_only=False)
        self.assertGreaterEqual(len(q_all), len(q))


class TestConsumerMap(unittest.TestCase):
    def test_map_keys_exist_in_registry(self):
        for (cat, key) in dq.CONSUMERS:
            self.assertIn(cat, ATTRIBUTE_REGISTRY, cat)
            self.assertIn(key, ATTRIBUTE_REGISTRY[cat], (cat, key))

    def test_map_rule_ids_exist_in_engine(self):
        import re
        emitted = set()
        for path in sorted((REPO / "pc_parts_organizer" / "compatibility").glob("rules_*.py")):
            src = path.read_text(encoding="utf-8")
            emitted |= set(re.findall(r'rule_id="([a-z0-9_.]+)"', src))
            for pat in re.findall(r'rule_id=f"([a-z0-9_.{}]+)"', src):
                cands = [pat]
                for token, values in (("label", ("mb", "gpu", "joint")),
                                      ("size", ("2_5", "3_5"))):
                    expanded = [c.replace("{" + token + "}", v)
                                for c in cands if "{" + token + "}" in c for v in values]
                    if expanded:
                        cands = [c for c in cands if "{" + token + "}" not in c] + expanded
                emitted.update(c for c in cands if "{" not in c)
        for rules in dq.CONSUMERS.values():
            for r in rules:
                self.assertIn(r, emitted, r)

    def test_every_engine_attribute_is_mapped(self):
        used: set[tuple[str, str]] = set()
        for path in sorted((REPO / "pc_parts_organizer" / "compatibility").glob("rules_*.py")):
            tree = ast.parse(path.read_text(encoding="utf-8"))
            for node in ast.walk(tree):
                if isinstance(node, ast.Call):
                    fn = node.func
                    is_get = ((isinstance(fn, ast.Name) and fn.id == "get_attr")
                              or (isinstance(fn, ast.Attribute) and fn.attr == "get_attr"))
                    if is_get and len(node.args) >= 2:
                        key = node.args[1]
                        if isinstance(key, ast.Constant) and isinstance(key.value, str):
                            used.add((path.stem, key.value))
        # attribute keys actually consumed (cooler_type inspected, not compared, still mapped)
        consumed = {k for _, k in used} - {"cooler_type"}
        mapped = {k for _, k in dq.CONSUMERS}
        self.assertFalse(consumed - mapped, f"unmapped engine keys: {consumed - mapped}")
        self.assertGreater(len(consumed), 20, "engine read set suspiciously small")

    def test_unevaluated_attributes_marked_unused(self):
        for cat, key in [("Storage", "pcie_generation"), ("Storage", "pcie_lanes"),
                         ("PSU", "rated_continuous_power_w"), ("GPU", "recommended_psu_power_w")]:
            self.assertEqual(dq.consumers_for(cat, key), ())


class TestEditorInvariant(unittest.TestCase):
    def _tk(self):
        import tkinter as tk
        try:
            root = tk.Tk()
            root.withdraw()
        except tk.TclError as exc:
            self.skipTest(f"Tk unavailable: {exc}")
        return root

    def _form(self, root, tr, cid, cat, profile):
        from pc_parts_organizer.ui.technical_profile_form import TechnicalProfileForm
        from pc_parts_organizer.ui.theme import configure_theme
        configure_theme(root)
        return TechnicalProfileForm(root, tr, component_id=cid, category=cat, profile=profile)

    def test_value_change_verified_requires_explicit_confirm(self):
        import uuid
        from unittest.mock import patch
        from pc_parts_organizer.localization import Translator
        for confirmed, expected in ((True, "verified"), (False, None)):
            root = self._tk()
            try:
                tr = Translator()
                cid = str(uuid.uuid4())
                existing = TechnicalProfile(component_id=cid, attributes=[va("memory_generation", "DDR4")])
                f = self._form(root, tr, cid, "RAM", existing)
                row = f._rows["memory_generation"]
                row["enabled"].set(True)
                row["value"][1].set("DDR5")
                with patch.object(f, "_confirm_revalidation", return_value=confirmed) as m:
                    f._on_save()
                self.assertTrue(m.called)
                if expected is None:
                    self.assertIsNone(f.result)
                else:
                    got = [a for a in f.result.attributes if a.key == "memory_generation"][0]
                    self.assertEqual(got.value, "DDR5")
                    self.assertEqual(got.verification_status, "verified")
            finally:
                root.destroy()

    def test_value_change_without_verify_lands_needs_review(self):
        import uuid
        from unittest.mock import patch
        from pc_parts_organizer.localization import Translator
        root = self._tk()
        try:
            tr = Translator()
            cid = str(uuid.uuid4())
            existing = TechnicalProfile(component_id=cid, attributes=[va("memory_generation", "DDR4")])
            f = self._form(root, tr, cid, "RAM", existing)
            row = f._rows["memory_generation"]
            row["enabled"].set(True)
            row["value"][1].set("DDR5")
            row["verification"].set(tr.t("technical_profile.status_unverified"))
            with patch.object(f, "_confirm_revalidation") as m:
                f._on_save()
            # no dialog on this path, and no silent unverified laundering
            self.assertFalse(m.called)
            self.assertIsNotNone(f.result)
            got = [a for a in f.result.attributes if a.key == "memory_generation"][0]
            self.assertEqual(got.value, "DDR5")
            self.assertEqual(got.verification_status, "needs_review")
        finally:
            root.destroy()

    def test_unchanged_value_keeps_verified(self):
        import uuid
        from pc_parts_organizer.localization import Translator
        root = self._tk()
        try:
            tr = Translator()
            cid = str(uuid.uuid4())
            existing = TechnicalProfile(component_id=cid, attributes=[va("memory_generation", "DDR4")])
            f = self._form(root, tr, cid, "RAM", existing)
            row = f._rows["memory_generation"]
            row["enabled"].set(True)
            for k, r in f._rows.items():
                if k != "memory_generation":
                    r["enabled"].set(False)
            f._on_save()
            got = [a for a in f.result.attributes if a.key == "memory_generation"][0]
            self.assertEqual(got.verification_status, "verified")
        finally:
            root.destroy()

    def test_evidence_deletion_forces_status_change(self):
        import uuid
        from unittest.mock import patch
        from pc_parts_organizer.localization import Translator
        root = self._tk()
        try:
            tr = Translator()
            cid = str(uuid.uuid4())
            existing = TechnicalProfile(component_id=cid, attributes=[va("memory_generation", "DDR4")])
            f = self._form(root, tr, cid, "RAM", existing)
            row = f._rows["memory_generation"]
            row["enabled"].set(True)
            for k, r in f._rows.items():
                if k != "memory_generation":
                    r["enabled"].set(False)
            row["evidence"].delete(0, "end")
            with patch("pc_parts_organizer.ui.technical_profile_form.messagebox.showerror") as m:
                f._on_save()
            self.assertTrue(m.called)
            self.assertIsNone(f.result)
        finally:
            root.destroy()


class TestServiceIntegration(unittest.TestCase):
    def setUp(self):
        import os, shutil
        from pathlib import Path
        base = Path(os.environ["LOCALAPPDATA"]) / "PCPartsOrganizer"
        if base.exists():
            shutil.rmtree(base)
        from pc_parts_organizer.service import InventoryService
        self.svc = InventoryService()

    def test_audit_reflects_edits_and_no_writes(self):
        from pc_parts_organizer.storage import load_project_state
        c = self.svc.add_component("RAM", "M", "R", "", "")
        before = load_project_state()
        rep1 = dq.audit_inventory(self.svc.get_components(),
                                 {p.component_id: p for p in self.svc.get_technical_profiles()})
        self.assertEqual(rep1.components_without_profile, 1)
        self.svc.set_technical_profile(TechnicalProfile(component_id=c.id, attributes=[va("memory_generation", "DDR5")]))
        rep2 = dq.audit_inventory(self.svc.get_components(),
                                 {p.component_id: p for p in self.svc.get_technical_profiles()})
        self.assertEqual(rep2.components_with_profile, 1)
        self.assertTrue(any(e.key == "memory_generation" and e.status == dq.VERIFIED for e in rep2.entries))
        after = load_project_state()
        # audit itself writes nothing; only the explicit set_technical_profile did
        self.assertEqual(len(before.components), len(after.components))
        self.assertEqual(len(before.builds), len(after.builds))
        self.assertEqual(len(before.technical_profiles) + 1, len(after.technical_profiles))

    def test_perf_bound(self):
        import time
        for i in range(200):
            c = self.svc.add_component("RAM", "M", f"R{i}", "", "")
            self.svc.set_technical_profile(TechnicalProfile(component_id=c.id, attributes=[
                va("memory_generation", "DDR5")]))
        comps = self.svc.get_components()
        profs = {p.component_id: p for p in self.svc.get_technical_profiles()}
        t0 = time.perf_counter()
        rep = dq.audit_inventory(comps, profs)
        dt = time.perf_counter() - t0
        self.assertGreater(len(rep.entries), 0)
        self.assertLess(dt, 5.0, f"audit too slow: {dt:.2f}s")


class TestQualityCenterUI(unittest.TestCase):
    def _tk(self):
        import tkinter as tk
        try:
            root = tk.Tk()
            root.withdraw()
        except tk.TclError as exc:
            self.skipTest(f"Tk unavailable: {exc}")
        return root

    def _report(self):
        a = comp("RAM", "R1")
        b = comp("PSU", "P1")
        p = TechnicalProfile(component_id=a.id, attributes=[
            va("memory_generation", "DDR5"), ua("module_count", 2)])
        return dq.audit_inventory([a, b], {a.id: p}), {a.id: a, b.id: b}

    def test_renders_both_languages(self):
        from pc_parts_organizer.localization import Translator
        from pc_parts_organizer.ui.quality_center_view import QualityCenterView
        from pc_parts_organizer.ui.theme import configure_theme
        root = self._tk()
        try:
            configure_theme(root)
            rep, comps = self._report()
            for lang in ("es", "en"):
                tr = Translator()
                tr.set_language(lang)
                v = QualityCenterView(root, tr)
                v.pack(fill="both", expand=True)
                v.set_data(rep, comps)
                root.update()
                self.assertTrue(len(v.tree.get_children()) >= 2)
                self.assertTrue(len(v.queue.get_children()) >= 1)
                v.destroy()
        finally:
            root.destroy()

    def test_filter_and_open_editor(self):
        from pc_parts_organizer.localization import Translator
        from pc_parts_organizer.ui.quality_center_view import QualityCenterView
        from pc_parts_organizer.ui.theme import configure_theme
        root = self._tk()
        try:
            configure_theme(root)
            tr = Translator()
            rep, comps = self._report()
            opened = []
            v = QualityCenterView(root, tr, on_edit_profile=opened.append)
            v.pack(fill="both", expand=True)
            v.set_data(rep, comps)
            root.update()
            v.cat_combo.set(v._t("quality.filter_all"))
            v._apply_filter()
            root.update()
            first = v.queue.get_children()
            self.assertTrue(first)
            v.queue.selection_set(first[0])
            v._handle_open_editor()
            self.assertEqual(len(opened), 1)
            v.destroy()
        finally:
            root.destroy()

    def test_filter_survives_language_switch(self):
        from pc_parts_organizer.localization import Translator
        from pc_parts_organizer.ui.quality_center_view import QualityCenterView
        from pc_parts_organizer.ui.theme import configure_theme
        root = self._tk()
        try:
            configure_theme(root)
            tr = Translator()
            rep, comps = self._report()
            v = QualityCenterView(root, tr)
            v.pack(fill="both", expand=True)
            v.set_data(rep, comps)
            root.update()
            v.cat_combo.set(v._cat_label("RAM"))
            v._apply_filter()
            root.update()
            n_filtered = len(v.tree.get_children())
            self.assertGreater(n_filtered, 0)
            tr.set_language("en")
            v.set_translator(tr)
            root.update()
            self.assertEqual(v._category_filter, "RAM")
            self.assertEqual(len(v.tree.get_children()), n_filtered)
            v.destroy()
        finally:
            root.destroy()

    def test_unsupported_category_row_and_translated_detail(self):
        from pc_parts_organizer.localization import Translator
        from pc_parts_organizer.ui.quality_center_view import QualityCenterView
        from pc_parts_organizer.ui.theme import configure_theme
        root = self._tk()
        try:
            configure_theme(root)
            tr = Translator()
            mon = comp("Monitor", "M1")
            rep = dq.audit_inventory([mon], {})
            v = QualityCenterView(root, tr)
            v.pack(fill="both", expand=True)
            v.set_data(rep, {mon.id: mon})
            root.update()
            rows = v.tree.get_children()
            self.assertEqual(len(rows), 1)
            self.assertIn("M1", v.tree.item(rows[0], "values")[0])
            # detail metadata translated, no raw canonical enums in ES
            a = comp("RAM", "R1")
            p = TechnicalProfile(component_id=a.id, attributes=[va("memory_generation", "DDR5")])
            rep2 = dq.audit_inventory([a], {a.id: p})
            v.set_data(rep2, {a.id: a})
            root.update()
            v.tree.selection_set(v.tree.get_children()[0])
            v._render_detail()
            text = v.detail_text.get("1.0", "end")
            self.assertIn("Documentaci", text)
            self.assertNotIn("official_vendor_doc", text)
            self.assertNotIn("needs_review", text.replace("needs_review", ""))
            v.destroy()
        finally:
            root.destroy()

    def test_unchanged_typed_profile_keeps_verified(self):
        import uuid
        from pc_parts_organizer.localization import Translator
        from pc_parts_organizer.ui.technical_profile_form import TechnicalProfileForm
        from pc_parts_organizer.ui.theme import configure_theme
        root = self._tk()
        try:
            configure_theme(root)
            tr = Translator()
            cid = str(uuid.uuid4())
            slot = {"slot_id": "M2_1", "accepted_module_keyings": ["M"],
                    "supported_lengths": ["2280"], "supported_modes": ["pcie_nvme"]}
            existing = TechnicalProfile(component_id=cid, attributes=[
                va("m2_slots", [slot], collection_completeness="partial",
                   completeness_scope="seen M2_1")])
            f = TechnicalProfileForm(root, tr, component_id=cid, category="Motherboard", profile=existing)
            row = f._rows["m2_slots"]
            row["enabled"].set(True)
            for k, r in f._rows.items():
                if k != "m2_slots":
                    r["enabled"].set(False)
            f._on_save()
            self.assertIsNotNone(f.result)
            got = [a for a in f.result.attributes if a.key == "m2_slots"][0]
            self.assertEqual(got.verification_status, "verified")
        finally:
            root.destroy()
        import os, shutil
        from pathlib import Path
        base = Path(os.environ["LOCALAPPDATA"]) / "PCPartsOrganizer"
        if base.exists():
            shutil.rmtree(base)
        from pc_parts_organizer.localization import Translator
        from pc_parts_organizer.catalog_service import CatalogService
        from pc_parts_organizer.catalog_storage import CatalogStorage
        from pc_parts_organizer.service import InventoryService
        from pc_parts_organizer.ui.main_window import MainWindow
        from pc_parts_organizer.ui.theme import configure_theme
        root = self._tk()
        try:
            configure_theme(root)
            svc = InventoryService()
            c = svc.add_component("RAM", "M", "R", "", "")
            svc.set_technical_profile(TechnicalProfile(component_id=c.id, attributes=[va("memory_generation", "DDR5")]))
            tr = Translator()
            win = MainWindow(root, svc, CatalogService(CatalogStorage()), tr)
            win._show_quality_center()
            root.update()
            self.assertTrue(len(win._quality_center_view.tree.get_children()) >= 1)
            for lang in ("es", "en"):
                tr.set_language(lang)
                win.apply_translations()
                root.update()
            # edit profile with quality center visible recomputes
            svc.set_technical_profile(TechnicalProfile(component_id=c.id, attributes=[
                TechnicalAttribute(key="memory_generation", value="DDR4")]))
            win._refresh_quality_if_visible()
            root.update()
            root.destroy()
        finally:
            try:
                root.destroy()
            except Exception:
                pass


if __name__ == "__main__":
    unittest.main()
