"""T17.17: revalidation governance, quality pagination/scale, consumer contract."""
from __future__ import annotations

try:
    import tests._pcpo_test_isolation_bootstrap  # noqa: F401
except Exception:
    import _pcpo_test_isolation_bootstrap  # type: ignore  # noqa: F401

import unittest
from pathlib import Path

from pc_parts_organizer import data_quality as dq
from pc_parts_organizer.models import Component
from pc_parts_organizer.technical_profiles import TechnicalAttribute, TechnicalProfile

REPO = Path(__file__).resolve().parents[1]


def comp(cat, model="X"):
    return Component(category=cat, manufacturer="M", model=model, specifications="", notes="")


def va(key, value, **kw):
    base = dict(source="official_vendor_doc", confidence="high",
                verification_status="verified", evidence_ref="https://vendor/doc",
                verified_at="2026-01-01")
    base.update(kw)
    return TechnicalAttribute(key=key, value=value, **base)


def needs_review(key, value, **kw):
    base = dict(source="official_vendor_doc", confidence="high",
                verification_status="needs_review", evidence_ref="https://vendor/doc",
                verified_at="2026-01-01")
    base.update(kw)
    return TechnicalAttribute(key=key, value=value, **base)


class TestRevalidationDialog(unittest.TestCase):
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

    def _set_row(self, f, key, value=None, verification=None):
        import uuid
        row = f._rows[key]
        row["enabled"].set(True)
        for k, r in f._rows.items():
            if k != key:
                r["enabled"].set(False)
        if value is not None:
            w = row["value"]
            if w[0] == "enum":
                w[1].set(value)
            elif w[0] in ("int", "int_non_negative"):
                w[1].delete(0, "end")
                w[1].insert(0, str(value))
            else:
                raise AssertionError(f"unsupported widget {w[0]}")
        if verification is not None:
            row["verification"].set(f.translator.t(f"technical_profile.status_{verification}"))
        return row

    def test_needs_review_to_verified_requires_confirm(self):
        import uuid
        from unittest.mock import patch
        from pc_parts_organizer.localization import Translator
        root = self._tk()
        try:
            tr = Translator()
            cid = str(uuid.uuid4())
            existing = TechnicalProfile(component_id=cid, attributes=[
                needs_review("memory_generation", "DDR4")])
            f = self._form(root, tr, cid, "RAM", existing)
            self._set_row(f, "memory_generation", verification="verified")
            with patch.object(f, "_confirm_revalidation", return_value=False) as m:
                f._on_save()
            self.assertTrue(m.called)
            self.assertIsNone(f.result)
        finally:
            root.destroy()

    def test_confirm_shows_old_new_and_evidence(self):
        import uuid
        from unittest.mock import patch
        from pc_parts_organizer.localization import Translator
        root = self._tk()
        try:
            tr = Translator()
            cid = str(uuid.uuid4())
            existing = TechnicalProfile(component_id=cid, attributes=[
                needs_review("memory_generation", "DDR4")])
            f = self._form(root, tr, cid, "RAM", existing)
            self._set_row(f, "memory_generation", value="DDR5", verification="verified")
            seen = {}
            def fake(**kw):
                seen.update(kw)
                return True
            with patch.object(f, "_confirm_revalidation", side_effect=fake):
                f._on_save()
            self.assertEqual(seen.get("old_value"), "DDR4")
            self.assertEqual(seen.get("new_value"), "DDR5")
            self.assertEqual(seen.get("old_evidence"), "https://vendor/doc")
            self.assertIsNotNone(f.result)
            got = [a for a in f.result.attributes if a.key == "memory_generation"][0]
            self.assertEqual(got.verification_status, "verified")
        finally:
            root.destroy()

    def test_first_verification_needs_no_dialog(self):
        import uuid
        from unittest.mock import patch
        from pc_parts_organizer.localization import Translator
        root = self._tk()
        try:
            tr = Translator()
            cid = str(uuid.uuid4())
            f = self._form(root, tr, cid, "RAM", None)
            row = self._set_row(f, "memory_generation", value="DDR4", verification="verified")
            row["evidence"].insert(0, "https://vendor/doc")
            row["verified_at"].insert(0, "2026-02-02")
            with patch.object(f, "_confirm_revalidation") as m:
                f._on_save()
            self.assertFalse(m.called)
            self.assertIsNotNone(f.result)
        finally:
            root.destroy()

    def test_confidence_and_source_preserved_on_reverify(self):
        import uuid
        from unittest.mock import patch
        from pc_parts_organizer.localization import Translator
        root = self._tk()
        try:
            tr = Translator()
            cid = str(uuid.uuid4())
            existing = TechnicalProfile(component_id=cid, attributes=[
                needs_review("memory_generation", "DDR4", confidence="medium",
                             source="catalog_import")])
            f = self._form(root, tr, cid, "RAM", existing)
            self._set_row(f, "memory_generation", verification="verified")
            with patch.object(f, "_confirm_revalidation", return_value=True):
                f._on_save()
            got = [a for a in f.result.attributes if a.key == "memory_generation"][0]
            self.assertEqual(got.verification_status, "verified")
            self.assertEqual(got.confidence, "medium")
            self.assertEqual(got.source, "catalog_import")
        finally:
            root.destroy()

    def test_value_change_verified_goes_through_dialog(self):
        import uuid
        from unittest.mock import patch
        from pc_parts_organizer.localization import Translator
        root = self._tk()
        try:
            tr = Translator()
            cid = str(uuid.uuid4())
            existing = TechnicalProfile(component_id=cid, attributes=[va("memory_generation", "DDR4")])
            f = self._form(root, tr, cid, "RAM", existing)
            self._set_row(f, "memory_generation", value="DDR5", verification="verified")
            with patch.object(f, "_confirm_revalidation", return_value=True) as m:
                f._on_save()
            # dialog confirms the changed value explicitly: verified is legitimate
            self.assertTrue(m.called)
            got = [a for a in f.result.attributes if a.key == "memory_generation"][0]
            self.assertEqual(got.value, "DDR5")
            self.assertEqual(got.verification_status, "verified")
        finally:
            root.destroy()


    def test_stepping_stone_unverified_becomes_needs_review(self):
        import uuid
        from unittest.mock import patch
        from pc_parts_organizer.localization import Translator
        root = self._tk()
        try:
            tr = Translator()
            cid = str(uuid.uuid4())
            existing = TechnicalProfile(component_id=cid, attributes=[va("memory_generation", "DDR4")])
            f = self._form(root, tr, cid, "RAM", existing)
            self._set_row(f, "memory_generation", value="DDR5", verification="unverified")
            with patch.object(f, "_confirm_revalidation") as m:
                f._on_save()
            self.assertFalse(m.called)
            self.assertIsNotNone(f.result)
            got = [a for a in f.result.attributes if a.key == "memory_generation"][0]
            self.assertEqual(got.value, "DDR5")
            self.assertEqual(got.verification_status, "needs_review")
        finally:
            root.destroy()

    def test_values_equal_is_multiset(self):
        from pc_parts_organizer.ui.technical_profile_form import _values_equal
        self.assertTrue(_values_equal(["A", "B"], None, ["B", "A"], None))
        self.assertFalse(_values_equal(["A", "A"], None, ["A", "B"], None))
        self.assertTrue(_values_equal("X", None, "X", None))
        self.assertFalse(_values_equal("X", "mm", "X", "cm"))


class TestConsumerContract(unittest.TestCase):
    def _rule_files(self):
        import ast
        out = {}
        for path in sorted((REPO / "pc_parts_organizer" / "compatibility").glob("rules_*.py")):
            tree = ast.parse(path.read_text(encoding="utf-8"))
            keys = set()
            for node in ast.walk(tree):
                if isinstance(node, ast.Constant) and isinstance(node.value, str):
                    keys.add(node.value)
            out[path.stem] = (tree, keys)
        return out

    def test_no_duplicate_rules_per_key(self):
        for k, v in dq.CONSUMERS.items():
            self.assertEqual(len(v), len(set(v)), k)

    def test_mapped_attribute_is_read_by_that_rule(self):
        import ast
        for (cat, key), rules in dq.CONSUMERS.items():
            for r in rules:
                module = "rules_" + r.split(".")[0].split("_")[0] + ("_" + r.split(".")[0].split("_")[1] if "_" in r.split(".")[0] and r.split(".")[0] not in ("ram", "psu", "cpu", "gpu", "mb") else "")
                # resolve rule prefix -> module file by longest match on rule namespace
                ns = r.split(".")[0]
                candidates = [p for p in (REPO / "pc_parts_organizer" / "compatibility").glob("rules_*.py")
                              if p.stem == f"rules_{ns}" or p.stem.startswith(f"rules_{ns}")]
                if not candidates:
                    # compound namespaces: ram_mb, mb_case, gpu_case, cpu_cooling, cooling_case,
                    # cpu_mb, storage_m2->storage, storage_case->storage, storage_sata, psu_*
                    base = ns.split("_")[0]
                    candidates = [p for p in (REPO / "pc_parts_organizer" / "compatibility").glob("rules_*.py")
                                  if base in p.stem]
                self.assertTrue(candidates, (cat, key, r))
                found = False
                for path in candidates:
                    src = path.read_text(encoding="utf-8")
                    tree = ast.parse(src)
                    for node in ast.walk(tree):
                        if not isinstance(node, ast.Call) or len(node.args) < 2:
                            continue
                        fn = node.func
                        is_get = ((isinstance(fn, ast.Name) and fn.id == "get_attr")
                                  or (isinstance(fn, ast.Attribute) and fn.attr == "get_attr"))
                        arg = node.args[1]
                        if is_get and isinstance(arg, ast.Constant) and arg.value == key:
                            found = True
                    # variable-held keys (loop vars, req_attr_key params): the
                    # literal must still flow through this rule module
                    if not found and f'"{key}"' in src:
                        found = True
                self.assertTrue(found, (cat, key, r))

    def test_every_engine_attribute_still_mapped(self):
        import ast
        used: set[str] = set()
        for path in sorted((REPO / "pc_parts_organizer" / "compatibility").glob("rules_*.py")):
            tree = ast.parse(path.read_text(encoding="utf-8"))
            for node in ast.walk(tree):
                if not isinstance(node, ast.Call) or len(node.args) < 2:
                    continue
                fn = node.func
                is_get = ((isinstance(fn, ast.Name) and fn.id == "get_attr")
                          or (isinstance(fn, ast.Attribute) and fn.attr == "get_attr"))
                if (is_get and isinstance(node.args[1], ast.Constant)
                        and isinstance(node.args[1].value, str)):
                    used.add(node.args[1].value)
        # loop-var / parameter-held keys flow through the same modules
        for path in sorted((REPO / "pc_parts_organizer" / "compatibility").glob("rules_*.py")):
            src = path.read_text(encoding="utf-8")
            for lit in ("bay_2_5_total", "bay_3_5_total",
                        "motherboard_power_connectors_required", "gpu_power_connectors_required"):
                if f'"{lit}"' in src:
                    used.add(lit)
        used.discard("cooler_type")  # inspected for candidacy, not compared
        mapped = {k for _, k in dq.CONSUMERS}
        self.assertFalse(used - mapped, used - mapped)
        self.assertGreater(len(used), 20, "engine read set suspiciously small")


class TestQualityPagination(unittest.TestCase):
    def _tk(self):
        import tkinter as tk
        try:
            root = tk.Tk()
            root.withdraw()
        except tk.TclError as exc:
            self.skipTest(f"Tk unavailable: {exc}")
        return root

    def _report(self, n):
        comps = [comp("RAM", f"R{i:03d}") for i in range(n)]
        return dq.audit_inventory(comps, {}), {c.id: c for c in comps}

    def _view(self, root, tr, rep, comps):
        from pc_parts_organizer.ui.quality_center_view import QualityCenterView
        from pc_parts_organizer.ui.theme import configure_theme
        configure_theme(root)
        v = QualityCenterView(root, tr)
        v.pack(fill="both", expand=True)
        v.set_data(rep, comps)
        root.update()
        return v

    def test_pages_cover_all_rows_exactly_once(self):
        from pc_parts_organizer.localization import Translator
        root = self._tk()
        try:
            tr = Translator()
            rep, comps = self._report(120)
            v = self._view(root, tr, rep, comps)
            seen = []
            v._page_size = 50
            v._table_page = 0
            v._render()
            pages = max(1, (120 + 49) // 50)
            for p in range(pages):
                v._table_page = p
                v._render()
                root.update()
                seen.extend([v.tree.item(i, "values")[0] for i in v.tree.get_children()])
            self.assertEqual(len(seen), 120)
            self.assertEqual(len(set(seen)), 120)
            v.destroy()
        finally:
            root.destroy()

    def test_filters_search_and_language_keep_page(self):
        from pc_parts_organizer.localization import Translator
        root = self._tk()
        try:
            tr = Translator()
            rep, comps = self._report(120)
            v = self._view(root, tr, rep, comps)
            v._page_size = 25
            v._search_text = "r0"
            v._table_page = 2
            v._render()
            root.update()
            n1 = len(v.tree.get_children())
            self.assertEqual(n1, 25)
            tr.set_language("en")
            v.set_translator(tr)
            root.update()
            self.assertEqual(v._table_page, 2)
            self.assertEqual(len(v.tree.get_children()), n1)
            self.assertEqual(v._page_size, 25)
            v.destroy()
        finally:
            root.destroy()

    def test_queue_pagination_and_counts(self):
        from pc_parts_organizer.localization import Translator
        root = self._tk()
        try:
            tr = Translator()
            rep, comps = self._report(120)
            v = self._view(root, tr, rep, comps)
            v._page_size = 25
            v._render()
            root.update()
            total = len(dq.review_queue(rep))
            shown = 0
            pages = max(1, (total + 24) // 25)
            for p in range(pages):
                v._queue_page = p
                v._render()
                root.update()
                shown += len(v.queue.get_children())
            self.assertEqual(shown, total)
            v.destroy()
        finally:
            root.destroy()

    def test_queue_selection_restored_across_pages(self):
        from pc_parts_organizer.localization import Translator
        from pc_parts_organizer.ui.quality_center_view import QualityCenterView
        root = self._tk()
        try:
            tr = Translator()
            rep, comps = self._report(60)
            v = QualityCenterView(root, tr)
            v.pack(fill="both", expand=True)
            v.set_data(rep, comps)
            v._page_size = 25
            v._render()
            root.update()
            first = v.queue.get_children()[0]
            v.queue.selection_set(first)
            tags = v.queue.item(first, "tags")
            v._table_page = 1
            v._render()
            root.update()
            sel = v.queue.selection()
            self.assertTrue(sel)
            self.assertEqual(tuple(v.queue.item(sel[0], "tags")), tuple(tags))
            v.destroy()
        finally:
            root.destroy()

    def test_perf_1000(self):
        import time
        rep, _ = self._report(1000)
        t0 = time.perf_counter()
        dq.review_queue(rep)
        self.assertLess(time.perf_counter() - t0, 5.0)


class TestCompatibilityIntegration(unittest.TestCase):
    def setUp(self):
        import os, shutil
        from pathlib import Path
        base = Path(os.environ["LOCALAPPDATA"]) / "PCPartsOrganizer"
        if base.exists():
            shutil.rmtree(base)
        from pc_parts_organizer.service import InventoryService
        self.svc = InventoryService()

    def _build_psu_case(self, psu_ff, case_list, verified=True):
        def A(key, value):
            kw = {} if verified else {"verification_status": "unverified", "confidence": "low", "source": "unknown"}
            base = dict(source="official_vendor_doc", confidence="high",
                        verification_status="verified", evidence_ref="https://vendor/doc",
                        verified_at="2026-01-01")
            base.update(kw)
            return TechnicalAttribute(key=key, value=value, **base)
        psu = self.svc.add_component("PSU", "M", "P", "", "")
        case = self.svc.add_component("Case", "M", "C", "", "")
        self.svc.set_technical_profile(TechnicalProfile(component_id=psu.id, attributes=[A("psu_form_factor", psu_ff)]))
        self.svc.set_technical_profile(TechnicalProfile(component_id=case.id, attributes=[A("supported_psu_form_factors", case_list)]))
        b = self.svc.add_build("B")
        self.svc.add_component_to_build(b.id, psu.id)
        self.svc.add_component_to_build(b.id, case.id)
        return b

    def test_verify_changes_result_only_when_justified(self):
        b = self._build_psu_case("ATX", ["ATX"], verified=False)
        r1 = self.svc.analyze_build_compatibility(b.id)
        f1 = [f for f in r1.findings if f.rule_id == "psu_case.form_factor"][0]
        self.assertEqual(f1.result, "requires_verification")
        # verify with same values -> compatible now
        for p in self.svc.get_technical_profiles():
            attrs = [TechnicalAttribute(key=a.key, value=a.value, unit=a.unit, source="official_vendor_doc",
                                        confidence="high", verification_status="verified",
                                        evidence_ref="https://vendor/doc", verified_at="2026-01-01",
                                        collection_completeness=a.collection_completeness,
                                        completeness_scope=a.completeness_scope) for a in p.attributes]
            self.svc.set_technical_profile(TechnicalProfile(component_id=p.component_id, attributes=attrs))
        r2 = self.svc.analyze_build_compatibility(b.id)
        f2 = [f for f in r2.findings if f.rule_id == "psu_case.form_factor"][0]
        self.assertEqual(f2.result, "compatible")

    def test_comparator_uses_fresh_reports(self):
        from pc_parts_organizer.build_compare import compare_hardware, compare_reports, correspondence_from_hardware
        b1 = self._build_psu_case("ATX", ["ATX"])
        # need distinct components per build
        psu2 = self.svc.add_component("PSU", "M", "P2", "", "")
        case2 = self.svc.add_component("Case", "M", "C2", "", "")
        self.svc.set_technical_profile(TechnicalProfile(component_id=psu2.id, attributes=[va2("psu_form_factor", "SFX")]))
        self.svc.set_technical_profile(TechnicalProfile(component_id=case2.id, attributes=[va2("supported_psu_form_factors", ["SFX"])]))
        b2 = self.svc.add_build("B2")
        self.svc.add_component_to_build(b2.id, psu2.id)
        self.svc.add_component_to_build(b2.id, case2.id)
        comps = {c.id: c for c in self.svc.get_components()}
        profs = {p.component_id: p for p in self.svc.get_technical_profiles()}
        hw = compare_hardware(self.svc.get_build(b1.id), self.svc.get_build(b2.id), comps, profs)
        ra = self.svc.analyze_build_compatibility(b1.id)
        rb = self.svc.analyze_build_compatibility(b2.id)
        cd = compare_reports(ra, rb, correspondence_from_hardware(hw))
        self.assertTrue(any(p.status == "same" for p in cd.pairs if p.key[0] == "psu_case.form_factor"))


def va2(key, value):
    return TechnicalAttribute(key=key, value=value, source="official_vendor_doc", confidence="high",
                              verification_status="verified", evidence_ref="https://vendor/doc",
                              verified_at="2026-01-01")


class TestLocalesContract(unittest.TestCase):
    def test_quality_keys_parity_and_placeholders(self):
        import json
        import string
        repo = Path(__file__).resolve().parents[1]
        en = json.load(open(repo / "pc_parts_organizer" / "locales" / "en.json", encoding="utf-8"))
        es = json.load(open(repo / "pc_parts_organizer" / "locales" / "es.json", encoding="utf-8"))
        self.assertEqual(sorted(en["quality"].keys()), sorted(es["quality"].keys()))
        for k, v in en["quality"].items():
            if not isinstance(v, str):
                continue
            pe = {f for _, f, _, _ in string.Formatter().parse(v) if f}
            qe = {f for _, f, _, _ in string.Formatter().parse(es["quality"][k]) if f}
            self.assertEqual(pe, qe, k)
        for k in ("revalidate_title", "revalidate_intro", "revalidate_old_value", "revalidate_new_value",
                  "revalidate_old_evidence", "revalidate_new_evidence", "revalidate_note_same_evidence",
                  "revalidate_note_new_evidence", "revalidate_confirm"):
            self.assertIn(k, en["technical_profile"])
            self.assertIn(k, es["technical_profile"])
        self.assertIn("compare_builds", en["builds"])


if __name__ == "__main__":
    unittest.main()
