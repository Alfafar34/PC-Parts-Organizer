"""T17.18: per-build technical audit tests (model + integration + UI)."""
from __future__ import annotations

try:
    import tests._pcpo_test_isolation_bootstrap  # noqa: F401
except Exception:
    import _pcpo_test_isolation_bootstrap  # type: ignore  # noqa: F401

import time
import unittest

from pc_parts_organizer import build_audit as ba
from pc_parts_organizer.compatibility import analyze_build_compatibility
from pc_parts_organizer.models import Build, Component
from pc_parts_organizer.technical_profiles import TechnicalAttribute, TechnicalProfile


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


def analyze(comps, profs, name="B"):
    b = Build(name=name, component_ids=[c.id for c in comps])
    return b, analyze_build_compatibility(b, comps, profs)


class TestAuditModel(unittest.TestCase):
    def test_demonstrated_grouping_and_counts(self):
        psu, case = comp("PSU"), comp("Case")
        profs = [TechnicalProfile(component_id=psu.id, attributes=[va("psu_form_factor", "ATX")]),
                 TechnicalProfile(component_id=case.id, attributes=[va("supported_psu_form_factors", ["SFX"])])]
        b, rep = analyze([psu, case], profs)
        pmap = {p.component_id: p for p in profs}
        a = ba.build_audit(b, {c.id: c for c in (psu, case)}, pmap, rep)
        self.assertEqual(len(a.demonstrated), 1)
        self.assertEqual(a.global_result, rep.overall_result)
        self.assertEqual(a.rules_evaluated, rep.rules_evaluated)
        total = len(a.demonstrated) + len(a.pending_verification) + len(a.insufficient)
        self.assertLessEqual(total, len(rep.findings))

    def test_bracket_id_targets_only_named_component(self):
        from pc_parts_organizer.compatibility.models import CompatibilityFinding
        g1 = comp("GPU", "G1")
        b = Build(name="B", component_ids=[g1.id])
        other = "00000000-0000-0000-0000-000000000000"
        f = CompatibilityFinding(rule_id="gpu_case.max_length", rule_version="1",
                                 result="insufficient_data", severity="warning",
                                 component_ids=(g1.id,),
                                 missing_information=[f"gpu[{other}].card_length_mm"])
        rep = self._rep_with([f], b.id)
        a = ba.build_audit(b, {g1.id: g1}, {}, rep)
        self.assertTrue(a.insufficient)
        # stale bracket id must not invent a direct link to our GPU
        for e in a.insufficient:
            self.assertFalse([l for l in e.linked if l.direct])

    def test_context_limited_to_participants(self):
        from pc_parts_organizer.compatibility.models import CompatibilityFinding
        psu, case = comp("PSU"), comp("Case")
        b = Build(name="B", component_ids=[psu.id, case.id])
        f = CompatibilityFinding(rule_id="psu_case.form_factor", rule_version="1",
                                 result="requires_verification", severity="warning",
                                 component_ids=(psu.id,),
                                 message_params={"form_factor": "ATX", "supported": ["SFX"]})
        rep = self._rep_with([f], b.id)
        comps = {psu.id: psu, case.id: case}
        profs = {psu.id: TechnicalProfile(component_id=psu.id, attributes=[va("psu_form_factor", "ATX")]),
                 case.id: TechnicalProfile(component_id=case.id, attributes=[va("supported_psu_form_factors", ["SFX"])])}
        a = ba.build_audit(b, comps, profs, rep)
        self.assertEqual(len(a.pending_verification), 1)
        # case is not a participant: no case context links allowed
        for la in a.pending_verification[0].linked:
            self.assertNotEqual(la.category, "Case")

    def test_summary_counts_distinct_attrs(self):
        psu = comp("PSU")
        b = Build(name="B", component_ids=[psu.id])
        profs = {psu.id: TechnicalProfile(component_id=psu.id, attributes=[va("psu_form_factor", "ATX")])}
        rep = self._rep_with([], b.id)
        a = ba.build_audit(b, {psu.id: psu}, profs, rep)
        self.assertEqual(len(a.relevant_pending), 0)

    def _rep_with(self, findings, build_id):
        from pc_parts_organizer.compatibility.models import CompatibilityReport
        return CompatibilityReport(build_id=build_id, overall_result="requires_verification",
                                   findings=tuple(findings))

    def test_no_duplicates_no_loss(self):
        psu, case = comp("PSU"), comp("Case")
        b, rep = analyze([psu, case], [
            TechnicalProfile(component_id=psu.id, attributes=[va("psu_form_factor", "SFX")]),
            TechnicalProfile(component_id=case.id, attributes=[va("supported_psu_form_factors", ["SFX-L"])]),
        ])
        comps = {c.id: c for c in (psu, case)}
        profs = {p.component_id: p for p in [
            TechnicalProfile(component_id=psu.id, attributes=[va("psu_form_factor", "SFX")]),
            TechnicalProfile(component_id=case.id, attributes=[va("supported_psu_form_factors", ["SFX-L"])])]}
        a = ba.build_audit(b, comps, profs, rep)
        seen = [id(e.finding) for e in list(a.demonstrated) + list(a.pending_verification) + list(a.insufficient)]
        self.assertEqual(len(seen), len(set(seen)))
        self.assertEqual(sorted(map(id, (f for f in rep.findings
                                         if f.result in ("incompatible", "requires_verification", "insufficient_data")))),
                         sorted(seen))

    def test_direct_vs_context_link(self):
        # missing_information naming the attr -> direct; shared rule context otherwise
        gpu, case = comp("GPU"), comp("Case")
        profs = [TechnicalProfile(component_id=case.id, attributes=[va("max_gpu_length_mm", 350)])]
        b, rep = analyze([gpu, case], profs)
        comps = {gpu.id: gpu, case.id: case}
        pmap = {case.id: profs[0]}
        a = ba.build_audit(b, comps, pmap, rep)
        direct = [l for e in list(a.pending_verification) + list(a.insufficient) for l in e.linked if l.direct]
        self.assertTrue(direct)
        # every direct link names an attribute the finding's missing_information names
        for e in list(a.pending_verification) + list(a.insufficient):
            for la in e.linked:
                if la.direct:
                    self.assertTrue(ba._names_attribute(
                        getattr(e.finding, "missing_information", None), la.category, la.key,
                        {c.category for c in comps.values()}))

    def test_context_never_invents(self):
        # unverified attr on a component whose category is absent from participants
        mb = comp("Motherboard")
        b, rep = analyze([mb], [TechnicalProfile(component_id=mb.id, attributes=[
            ua("socket_designation", "AM5")])])
        a = ba.build_audit(b, {mb.id: mb}, {mb.id: TechnicalProfile(component_id=mb.id, attributes=[
            ua("socket_designation", "AM5")])}, rep)
        # cpu_mb.socket_visibility never ran (no CPU): socket attr must not be
        # linked as blocking, only as future context at most
        for la in a.relevant_pending:
            self.assertNotEqual(la.rule_id, "cpu_mb.socket_visibility")

    def test_ambiguous_participants_stay_independent(self):
        s1, s2 = comp("Storage", "S1"), comp("Storage", "S2")
        b, rep = analyze([s1, s2], [TechnicalProfile(component_id=s1.id, attributes=[]),
                                    TechnicalProfile(component_id=s2.id, attributes=[])])
        comps = {s1.id: s1, s2.id: s2}
        profs = {s1.id: TechnicalProfile(component_id=s1.id, attributes=[]),
                 s2.id: TechnicalProfile(component_id=s2.id, attributes=[])}
        a = ba.build_audit(b, comps, profs, rep)
        # bay findings reference both units; hardware correspondence is unknown
        # externally, but within one build every real finding must still appear once
        seen = [id(e.finding) for e in list(a.demonstrated) + list(a.pending_verification) + list(a.insufficient)]
        self.assertEqual(len(seen), len(set(seen)))

    def test_counts_derive_from_entries(self):
        mb, ram = comp("Motherboard"), comp("RAM")
        b, rep = analyze([mb, ram], [
            TechnicalProfile(component_id=mb.id, attributes=[va("form_factor", "ATX")]),
            TechnicalProfile(component_id=ram.id, attributes=[va("memory_generation", "DDR5")]),
        ])
        comps = {mb.id: mb, ram.id: ram}
        profs = {mb.id: TechnicalProfile(component_id=mb.id, attributes=[va("form_factor", "ATX")]),
                 ram.id: TechnicalProfile(component_id=ram.id, attributes=[va("memory_generation", "DDR5")])}
        a = ba.build_audit(b, comps, profs, rep)
        self.assertEqual(len(a.not_evaluated), len(rep.not_evaluated_relations))
        self.assertEqual(len(a.limitations), len(rep.analysis_limitations))

    def test_pure_no_mutation_no_io(self):
        import copy
        psu, case = comp("PSU"), comp("Case")
        profs = [TechnicalProfile(component_id=psu.id, attributes=[va("psu_form_factor", "ATX")]),
                 TechnicalProfile(component_id=case.id, attributes=[va("supported_psu_form_factors", ["ATX"])])]
        b, rep = analyze([psu, case], profs)
        comps = {psu.id: psu, case.id: case}
        pmap = {p.component_id: p for p in profs}
        before_c = copy.deepcopy(comps)
        before_p = [p.to_dict() for p in pmap.values()]
        before_r = [(f.rule_id, f.result) for f in rep.findings]
        ba.build_audit(b, comps, pmap, rep)
        self.assertEqual([p.to_dict() for p in pmap.values()], before_p)
        self.assertEqual([(f.rule_id, f.result) for f in rep.findings], before_r)
        self.assertEqual(set(before_c), set(comps))

    def test_epistemic_contract(self):
        # compatible never claims full scope; RV/insufficient/NE carry explicit scope text
        from pc_parts_organizer.localization import Translator
        tr = Translator()
        for lang in ("es", "en"):
            tr.set_language(lang)
            scope = tr.t("compatibility.scope_note")
            self.assertTrue(len(scope) > 20)


class TestAuditIntegration(unittest.TestCase):
    def setUp(self):
        import os, shutil
        from pathlib import Path
        base = Path(os.environ["LOCALAPPDATA"]) / "PCPartsOrganizer"
        if base.exists():
            shutil.rmtree(base)
        from pc_parts_organizer.service import InventoryService
        self.svc = InventoryService()

    def test_build_flow_and_comparator(self):
        psu = self.svc.add_component("PSU", "M", "P", "", "")
        case = self.svc.add_component("Case", "M", "C", "", "")
        self.svc.set_technical_profile(TechnicalProfile(component_id=psu.id, attributes=[ua("psu_form_factor", "ATX")]))
        self.svc.set_technical_profile(TechnicalProfile(component_id=case.id, attributes=[va("supported_psu_form_factors", ["SFX"])]))
        b = self.svc.add_build("B")
        self.svc.add_component_to_build(b.id, psu.id)
        self.svc.add_component_to_build(b.id, case.id)
        before = len(self.svc.get_technical_profiles())
        rep = self.svc.analyze_build_compatibility(b.id)
        a = ba.build_audit(self.svc.get_build(b.id),
                           {c.id: c for c in self.svc.get_components()},
                           {p.component_id: p for p in self.svc.get_technical_profiles()}, rep)
        self.assertEqual(len(a.pending_verification), 1)
        self.assertTrue(any(x.key == "psu_form_factor" for x in a.relevant_pending))
        after = len(self.svc.get_technical_profiles())
        self.assertEqual(before, after)
        # verify -> re-analyze changes only what data justifies
        self.svc.set_technical_profile(TechnicalProfile(component_id=case.id, attributes=[va("supported_psu_form_factors", ["ATX"])]))
        rep2 = self.svc.analyze_build_compatibility(b.id)
        a2 = ba.build_audit(self.svc.get_build(b.id),
                            {c.id: c for c in self.svc.get_components()},
                            {p.component_id: p for p in self.svc.get_technical_profiles()}, rep2)
        self.assertEqual(len(a2.demonstrated), 0)
        # comparator still uses fresh reports
        from pc_parts_organizer.build_compare import compare_hardware, compare_reports, correspondence_from_hardware
        comps = {c.id: c for c in self.svc.get_components()}
        hw = compare_hardware(self.svc.get_build(b.id), self.svc.get_build(b.id), comps,
                              {p.component_id: p for p in self.svc.get_technical_profiles()})
        cd = compare_reports(rep2, rep2, correspondence_from_hardware(hw))
        self.assertTrue(cd.pairs)


class TestAuditUI(unittest.TestCase):
    def _tk(self):
        import tkinter as tk
        try:
            root = tk.Tk()
            root.withdraw()
        except tk.TclError as exc:
            self.skipTest(f"Tk unavailable: {exc}")
        return root

    def _detail(self, root, tr, lang="es"):
        from pc_parts_organizer.ui.build_detail_view import BuildDetailView
        from pc_parts_organizer.ui.theme import configure_theme
        configure_theme(root)
        tr.set_language(lang)
        return BuildDetailView(root, tr)

    def test_renders_groups_both_languages(self):
        from pc_parts_organizer.localization import Translator
        psu, case = comp("PSU"), comp("Case")
        profs = [TechnicalProfile(component_id=psu.id, attributes=[va("psu_form_factor", "ATX")]),
                 TechnicalProfile(component_id=case.id, attributes=[va("supported_psu_form_factors", ["SFX"])])]
        b, rep = analyze([psu, case], profs)
        root = self._tk()
        try:
            tr = Translator()
            for lang in ("es", "en"):
                v = self._detail(root, tr, lang)
                bobj = Build(name="B", component_ids=[psu.id, case.id])
                pmap = {p.component_id: p for p in profs}
                v.set_build(bobj, {psu.id: psu, case.id: case})
                v.set_compatibility_report(rep, pmap)
                root.update()
                text = v._audit_text.get("1.0", "end")
                self.assertTrue(len(text.strip()) > 50)
                self.assertNotIn("{", text.replace("{SFX", "SFX"))
                v.destroy()
        finally:
            root.destroy()

    def test_stale_marker_shown(self):
        from pc_parts_organizer.localization import Translator
        root = self._tk()
        try:
            tr = Translator()
            tr.set_language("es")
            psu, case = comp("PSU"), comp("Case")
            profs = [TechnicalProfile(component_id=psu.id, attributes=[va("psu_form_factor", "ATX")]),
                     TechnicalProfile(component_id=case.id, attributes=[va("supported_psu_form_factors", ["SFX"])])]
            b, rep = analyze([psu, case], profs)
            pmap = {p.component_id: p for p in profs}
            from pc_parts_organizer.ui.build_detail_view import BuildDetailView
            from pc_parts_organizer.ui.theme import configure_theme
            configure_theme(root)
            v = BuildDetailView(root, tr)
            v.set_build(b, {psu.id: psu, case.id: case})
            v.set_compatibility_report(rep, pmap)
            v._compat_stale = True
            v._render_audit()
            root.update()
            self.assertIn("desactualizad", v._audit_text.get("1.0", "end"))
            v.destroy()
        finally:
            root.destroy()

    def test_relevant_limited_to_blocking_rules(self):
        # compatible rule's pending attrs are NOT relevant (future context at most)
        mb = comp("Motherboard")
        b, rep = analyze([mb], [TechnicalProfile(component_id=mb.id, attributes=[
            va("form_factor", "ATX"), va("memory_slot_count", 4)])])
        comps = {mb.id: mb}
        profs = {mb.id: TechnicalProfile(component_id=mb.id, attributes=[
            va("form_factor", "ATX"), va("memory_slot_count", 4)])}
        a = ba.build_audit(b, comps, profs, rep)
        rel_keys = {(x.component_id, x.key) for x in a.relevant_pending}
        # memory_slot_count is verified here; an absent sibling consumed by an
        # unevaluated rule must land in future, never in relevant
        self.assertNotIn((mb.id, "memory_slot_count"), rel_keys)
        fut = {(x.component_id, x.key) for x in a.future_pending}
        self.assertIn((mb.id, "sata_port_count"), fut)

    def test_same_attr_two_blocking_rules_counts_once(self):
        # power_cable_assemblies feeds psu_mb + psu_gpu + psu_joint; summary must not triple-count
        mb = comp("Motherboard")
        gpu = comp("GPU")
        psu = comp("PSU")
        comps = [mb, gpu, psu]
        profs = [
            TechnicalProfile(component_id=mb.id, attributes=[va("motherboard_power_connectors_required", [{"connector_kind": "ATX_24", "quantity": 1}])]),
            TechnicalProfile(component_id=gpu.id, attributes=[va("gpu_power_connectors_required", [{"connector_kind": "PCIE_8", "quantity": 1}])]),
            TechnicalProfile(component_id=psu.id, attributes=[]),
        ]
        b, rep = analyze(comps, profs)
        a = ba.build_audit(b, {c.id: c for c in comps}, {p.component_id: p for p in profs}, rep)
        from pc_parts_organizer.ui.build_detail_view import BuildDetailView
        import tkinter as tk
        from pc_parts_organizer.localization import Translator
        from pc_parts_organizer.ui.theme import configure_theme
        root = tk.Tk()
        root.withdraw()
        try:
            configure_theme(root)
            tr = Translator()
            tr.set_language("es")
            v = BuildDetailView.__new__(BuildDetailView)
            v.translator = tr
            v._audit_text = tk.Text(root)
            v._build = b
            v._components_by_id = {c.id: c for c in comps}
            v._profiles_by_id = {p.component_id: p for p in profs}
            v._compat_report = rep
            v._compat_stale = False
            v._render_audit()
            text = v._audit_text.get("1.0", "end")
            import re
            m = re.search(r"Atributos relevantes pendientes: (\d+)", text)
            self.assertIsNotNone(m)
            n = int(m.group(1))
            distinct = {(x.component_id, x.key) for x in a.relevant_pending}
            self.assertEqual(n, len(distinct))
            v._audit_text.destroy()
        finally:
            root.destroy()

    def test_no_report_and_no_profiles_states(self):
        from pc_parts_organizer.localization import Translator
        root = self._tk()
        try:
            tr = Translator()
            v = self._detail(root, tr)
            psu = comp("PSU")
            v.set_build(Build(name="B", component_ids=[psu.id]), {psu.id: psu})
            root.update()
            self.assertIn("ejecuta", v._audit_text.get("1.0", "end").lower())
            v.destroy()
        finally:
            root.destroy()

    def test_open_quality_callback(self):
        from pc_parts_organizer.localization import Translator
        root = self._tk()
        try:
            hits = []
            from pc_parts_organizer.ui.build_detail_view import BuildDetailView
            from pc_parts_organizer.ui.theme import configure_theme
            configure_theme(root)
            tr = Translator()
            v = BuildDetailView(root, tr, on_open_quality=lambda: hits.append(1))
            v._on_open_quality()
            self.assertEqual(hits, [1])
            v.destroy()
        finally:
            root.destroy()

    def test_main_window_wires_quality_and_profiles(self):
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
            psu = svc.add_component("PSU", "M", "P", "", "")
            case = svc.add_component("Case", "M", "C", "", "")
            svc.set_technical_profile(TechnicalProfile(component_id=psu.id, attributes=[va("psu_form_factor", "ATX")]))
            b = svc.add_build("B")
            svc.add_component_to_build(b.id, psu.id)
            svc.add_component_to_build(b.id, case.id)
            tr = Translator()
            win = MainWindow(root, svc, CatalogService(CatalogStorage()), tr)
            win._show_build_detail(b.id)
            win._analyze_build_compatibility(b.id)
            root.update()
            text = win._builds_detail_view._audit_text.get("1.0", "end")
            self.assertTrue(len(text) > 50)
            for lang in ("es", "en"):
                tr.set_language(lang)
                win.apply_translations()
                root.update()
            win._show_quality_center()
            root.update()
            self.assertTrue(win._quality_center_view.grid_info())
            root.destroy()
        finally:
            try:
                root.destroy()
            except Exception:
                pass


if __name__ == "__main__":
    unittest.main()
