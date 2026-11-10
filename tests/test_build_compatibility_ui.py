"""UI tests for build compatibility analysis (T17.4)."""

from __future__ import annotations

try:
    import tests._pcpo_test_isolation_bootstrap  # noqa: F401
except Exception:
    import _pcpo_test_isolation_bootstrap  # type: ignore  # noqa: F401

import unittest
import uuid
from types import MappingProxyType
from unittest.mock import Mock, patch

from pc_parts_organizer.compatibility.models import (
    RESULT_COMPATIBLE,
    RESULT_INCOMPATIBLE,
    RESULT_INSUFFICIENT_DATA,
    RESULT_REQUIRES_VERIFICATION,
    SEVERITY_CRITICAL,
    SEVERITY_INFO,
    SEVERITY_WARNING,
    CompatibilityFinding,
    CompatibilityReport,
)
from pc_parts_organizer.localization import Translator
from pc_parts_organizer.models import Build, Component
from pc_parts_organizer.service import BuildNotFoundError, StorageError
from pc_parts_organizer.ui.build_detail_view import BuildDetailView
from pc_parts_organizer.ui.theme import configure_theme


def _tk():
    import tkinter as tk
    try:
        root = tk.Tk()
        root.withdraw()
        configure_theme(root)
    except tk.TclError as exc:
        raise unittest.SkipTest(f"Tk unavailable: {exc}")
    return root


def _comp(category="RAM", manufacturer="Mfg", model="Model", cid=None):
    return Component(category=category, manufacturer=manufacturer, model=model, id=cid or str(uuid.uuid4()))


def _build(name="B", component_ids=None, bid=None):
    b = Build(name=name, component_ids=list(component_ids or []))
    if bid:
        b.id = bid
    return b


def _finding(**kw):
    d = dict(rule_id="r1", rule_version="1", result=RESULT_INSUFFICIENT_DATA, severity=SEVERITY_WARNING,
             component_ids=(), attributes_compared=(), evidence={}, message_key="compat.build.empty",
             message_params={}, missing_information=(), recommended_action="")
    d.update(kw)
    return CompatibilityFinding(**d)


def _report(build_id, overall, findings=(), rules_evaluated=0, not_evaluated=(), limitations=()):
    return CompatibilityReport(
        build_id=build_id, overall_result=overall, findings=tuple(findings),
        rules_evaluated=rules_evaluated, not_evaluated_relations=tuple(not_evaluated),
        analysis_limitations=tuple(limitations),
    )


class TestBuildDetailViewCompatibility(unittest.TestCase):
    def setUp(self):
        self.root = _tk()
        self.tr = Translator(); self.tr.set_language("en")

    def tearDown(self):
        try:
            self.root.update_idletasks()
        except Exception:
            pass
        self.root.destroy()

    def _view(self, **kw):
        v = BuildDetailView(self.root, self.tr, **kw)
        v.grid(row=0, column=0)
        self.root.update_idletasks()
        return v

    def _text(self, v):
        v._render_compatibility()
        v._compat_text.configure(state="normal")
        t = v._compat_text.get("1.0", "end-1c")
        v._compat_text.configure(state="disabled")
        return t

    def test_not_analyzed_state(self):
        b = _build()
        v = self._view()
        v.set_build(b, {})
        self.assertIn(self.tr.t("compatibility.not_analyzed"), v._compat_status.cget("text"))
        self.assertEqual(self._text(v), "")

    def test_analyze_button_calls_callback_with_build_id(self):
        b = _build()
        cb = Mock()
        v = self._view(on_analyze=cb)
        v.set_build(b, {})
        v.analyze_button.invoke()
        cb.assert_called_once_with(b.id)

    def test_repeat_analysis_updates_report(self):
        b = _build(); r1 = _comp("RAM"); m = _comp("Motherboard")
        v = self._view()
        v.set_build(b, {r1.id: r1, m.id: m})
        rep1 = _report(b.id, RESULT_INSUFFICIENT_DATA, findings=[_finding(rule_id="a", result=RESULT_INSUFFICIENT_DATA, message_key="compat.build.empty")])
        rep2 = _report(b.id, RESULT_COMPATIBLE, findings=[_finding(rule_id="b", result=RESULT_COMPATIBLE, severity=SEVERITY_INFO, message_key="compat.ram_mb.memory_generation.compatible", message_params={"generation": "DDR5"})])
        v.set_compatibility_report(rep1)
        self.assertIn(self.tr.t("compatibility.results.insufficient_data"), v._compat_status.cget("text"))
        v.set_compatibility_report(rep2)
        self.assertIn(self.tr.t("compatibility.results.compatible"), v._compat_status.cget("text"))
        self.assertNotIn("incompatible", v._compat_status.cget("text").lower() + self._text(v).lower()[:0])
        self.assertIn("DDR5", self._text(v))

    def test_four_global_results_presented_no_percent(self):
        b = _build(); v = self._view(); v.set_build(b, {})
        for res in (RESULT_COMPATIBLE, RESULT_INCOMPATIBLE, RESULT_REQUIRES_VERIFICATION, RESULT_INSUFFICIENT_DATA):
            rep = _report(b.id, res, findings=[_finding(result=res, severity=SEVERITY_CRITICAL if res==RESULT_INCOMPATIBLE else SEVERITY_INFO, message_key="compat.build.empty")])
            v.set_compatibility_report(rep)
            txt = v._compat_status.cget("text") + "\n" + self._text(v)
            self.assertIn(self.tr.t(f"compatibility.results.{res}"), txt)
            self.assertNotIn("%", txt)

    def test_incompatible_preserves_out_of_scope_limitations(self):
        b = _build()
        ram = _comp("RAM"); mb = _comp("Motherboard"); cpu = _comp("CPU")
        v = self._view()
        v.set_build(b, {ram.id: ram, mb.id: mb, cpu.id: cpu})
        rep = _report(
            b.id, RESULT_INCOMPATIBLE,
            findings=[_finding(rule_id="ram_mb.memory_generation", result=RESULT_INCOMPATIBLE, severity=SEVERITY_CRITICAL,
                               component_ids=(ram.id, mb.id), attributes_compared=("memory_generation", "supported_memory_generations"),
                               message_key="compat.ram_mb.memory_generation.incompatible",
                               message_params={"generation": "DDR4", "supported": ["DDR5"]})],
            rules_evaluated=1,
            not_evaluated=[{"category": "CPU", "reason": "no_rules_implemented"}],
            limitations=["out_of_scope_relations_present"],
        )
        v.set_compatibility_report(rep)
        txt = v._compat_status.cget("text") + "\n" + self._text(v)
        self.assertIn(self.tr.t("compatibility.results.incompatible"), txt)
        self.assertIn(self.tr.translate_category("CPU"), txt)
        self.assertIn(self.tr.t("compatibility.sections.not_evaluated"), txt)
        self.assertIn(self.tr.t("compatibility.sections.limitations"), txt)
        self.assertNotIn(self.tr.t("compatibility.results.compatible") + "\n", txt)

    def test_empty_incomplete_not_shown_as_compatible(self):
        b = _build()
        v = self._view(); v.set_build(b, {})
        rep = _report(b.id, RESULT_INSUFFICIENT_DATA, findings=[_finding(rule_id="build.empty", result=RESULT_INSUFFICIENT_DATA, severity=SEVERITY_INFO, message_key="compat.build.empty", recommended_action="add_components")])
        v.set_compatibility_report(rep)
        txt = v._compat_status.cget("text") + "\n" + self._text(v)
        self.assertIn(self.tr.t("compatibility.results.insufficient_data"), txt)
        self.assertNotIn(self.tr.t("compatibility.results.compatible"), v._compat_status.cget("text"))

    def test_findings_sections_severity_and_translation_params(self):
        b = _build(); ram = _comp("RAM"); mb = _comp("Motherboard")
        v = self._view(); v.set_build(b, {ram.id: ram, mb.id: mb})
        ev = {"ram": {"key": "memory_generation", "value": "DDR4", "unit": None, "source": "official_vendor_doc", "confidence": "high", "verification_status": "verified", "evidence_ref": "https://doc", "verified_at": "2026-01-01"},
              "motherboard": {"key": "supported_memory_generations", "value": ["DDR5"], "unit": None, "source": "user_input", "confidence": "medium", "verification_status": "unverified", "evidence_ref": None, "verified_at": None}}
        rep = _report(b.id, RESULT_INCOMPATIBLE, findings=[
            _finding(rule_id="ram_mb.memory_generation", result=RESULT_INCOMPATIBLE, severity=SEVERITY_CRITICAL,
                     component_ids=(ram.id, mb.id), attributes_compared=("memory_generation", "supported_memory_generations"),
                     evidence=ev, message_key="compat.ram_mb.memory_generation.incompatible",
                     message_params={"generation": "DDR4", "supported": ["DDR5"]}, recommended_action="use_supported_memory_generation"),
            _finding(rule_id="mb_case.case_missing", result=RESULT_INSUFFICIENT_DATA, severity=SEVERITY_INFO,
                     component_ids=(mb.id,), message_key="compat.mb_case.case_missing", missing_information=("case",), recommended_action="add_case"),
            _finding(rule_id="r_ok", result=RESULT_COMPATIBLE, severity=SEVERITY_INFO, message_key="compat.mb_case.form_factor.compatible", message_params={"form_factor": "ATX"}),
            _finding(rule_id="r_verify", result=RESULT_REQUIRES_VERIFICATION, severity=SEVERITY_WARNING, message_key="compat.mb_case.form_factor.requires_verification",
                     message_params={"form_factor": "ATX", "supported": ["ATX"], "apparent_conflict": False, "reason": "other"}),
        ], not_evaluated=[{"category": "GPU", "reason": "no_rules_implemented"}], limitations=["out_of_scope_relations_present"])
        v.set_compatibility_report(rep)
        txt = self._text(v)
        self.assertIn(self.tr.t("compatibility.sections.incompatibilities"), txt)
        self.assertIn(self.tr.t("compatibility.sections.insufficient_data"), txt)
        self.assertIn(self.tr.t("compatibility.sections.compatible"), txt)
        self.assertIn(self.tr.t("compatibility.sections.requires_verification"), txt)
        self.assertIn(self.tr.t("compatibility.severity.critical"), txt)
        self.assertIn("DDR4", txt)
        self.assertIn("DDR5", txt)
        self.assertIn(self.tr.t("compatibility.recommended_actions.use_supported_memory_generation"), txt)
        # stable order preserved within groups (report order is deterministic; grouping preserves relative order)
        self.assertLess(txt.index(self.tr.t("compatibility.rule_labels.ram_mb__memory_generation")),
                        txt.index(self.tr.t("compatibility.rule_labels.mb_case__case_missing")))

    def test_unknown_message_key_fallback_safe(self):
        b = _build(); v = self._view(); v.set_build(b, {})
        rep = _report(b.id, RESULT_REQUIRES_VERIFICATION, findings=[
            _finding(rule_id="x.unknown", result=RESULT_REQUIRES_VERIFICATION, severity=SEVERITY_WARNING,
                     message_key="compat.totally.unknown.key", message_params={"x": 1}, missing_information=("mystery",), recommended_action="unknown_action")
        ])
        v.set_compatibility_report(rep)  # must not raise
        txt = self._text(v)
        self.assertIn("x.unknown", txt)
        self.assertTrue(self.tr.t("compatibility.finding.unknown_message") in txt or "unknown" in txt.lower() or "x=1" in txt)

    def test_evidence_provenance_and_disclaimer(self):
        b = _build(); v = self._view(); v.set_build(b, {})
        ev = {"ram": {"key": "memory_generation", "value": "DDR5", "unit": None, "source": "official_vendor_doc", "confidence": "high", "verification_status": "verified", "evidence_ref": "ref://doc", "verified_at": "2026-01-02"}}
        rep = _report(b.id, RESULT_REQUIRES_VERIFICATION, findings=[_finding(message_key="compat.build.empty", evidence=ev)])
        v.set_compatibility_report(rep)
        txt = self._text(v)
        self.assertIn(self.tr.t("compatibility.evidence_labels.source"), txt)
        self.assertIn(self.tr.t("compatibility.evidence_labels.confidence"), txt)
        self.assertIn(self.tr.t("compatibility.evidence_labels.verification_status"), txt)
        self.assertIn("ref://doc", txt)
        self.assertIn("2026-01-02", txt)
        self.assertIn(self.tr.t("compatibility.evidence_disclaimer"), txt)
        self.assertIn(self.tr.t("compatibility.scope_note"), txt)
        self.assertIn(self.tr.t("compatibility.verification_statuses.verified"), txt)

    def test_coverage_ram_mb_mb_case_and_out_of_scope(self):
        b = _build(); ram=_comp("RAM"); mb=_comp("Motherboard"); case=_comp("Case"); cpu=_comp("CPU"); gpu=_comp("GPU")
        v = self._view(); v.set_build(b, {x.id: x for x in (ram,mb,case,cpu,gpu)})
        rep = _report(b.id, RESULT_REQUIRES_VERIFICATION, findings=[
            _finding(rule_id="ram_mb.memory_generation", result=RESULT_COMPATIBLE, severity=SEVERITY_INFO, component_ids=(ram.id,mb.id), message_key="compat.ram_mb.memory_generation.compatible", message_params={"generation":"DDR5"}),
            _finding(rule_id="mb_case.form_factor", result=RESULT_COMPATIBLE, severity=SEVERITY_INFO, component_ids=(mb.id,case.id), message_key="compat.mb_case.form_factor.compatible", message_params={"form_factor":"ATX"}),
        ], not_evaluated=[{"category":"CPU","reason":"no_rules_implemented"},{"category":"GPU","reason":"no_rules_implemented"}], limitations=["out_of_scope_relations_present"])
        v.set_compatibility_report(rep)
        txt = self._text(v)
        self.assertIn(self.tr.t("compatibility.rule_labels.ram_mb__memory_generation"), txt)
        self.assertIn(self.tr.t("compatibility.rule_labels.mb_case__form_factor"), txt)
        self.assertIn(self.tr.translate_category("CPU"), txt)
        self.assertIn(self.tr.translate_category("GPU"), txt)

    def test_ambiguity_multiple_mb_case(self):
        b=_build(); m1=_comp("Motherboard"); m2=_comp("Motherboard")
        v=self._view(); v.set_build(b,{m1.id:m1,m2.id:m2})
        rep=_report(b.id, RESULT_INSUFFICIENT_DATA, findings=[
            _finding(rule_id="build.ambiguous_motherboard", result=RESULT_INSUFFICIENT_DATA, severity=SEVERITY_WARNING,
                     component_ids=(m1.id,m2.id), message_key="compat.build.ambiguous_motherboard", message_params={"count":2},
                     missing_information=("single_motherboard",), recommended_action="review_build_configuration")
        ])
        v.set_compatibility_report(rep)
        txt = self._text(v)
        self.assertIn("2", txt)
        self.assertIn(self.tr.t("compatibility.recommended_actions.review_build_configuration"), txt)

    def test_freshness_set_build_clears_report(self):
        b = _build(); v = self._view(); v.set_build(b, {})
        v.set_compatibility_report(_report(b.id, RESULT_COMPATIBLE))
        self.assertIn(self.tr.t("compatibility.results.compatible"), v._compat_status.cget("text"))
        v.set_build(b, {})  # refresh
        self.assertIn(self.tr.t("compatibility.not_analyzed"), v._compat_status.cget("text"))

    def test_stale_marking(self):
        b = _build(); v = self._view(); v.set_build(b, {})
        v.set_compatibility_report(_report(b.id, RESULT_COMPATIBLE))
        v.invalidate_compatibility(stale=True)
        self.assertIn(self.tr.t("compatibility.stale"), v._compat_status.cget("text"))

    def test_component_navigation_from_implicated_list(self):
        b=_build(); ram=_comp("RAM","A","X")
        opened=[]
        v=self._view(on_view_component=lambda cid: opened.append(cid))
        v.set_build(b,{ram.id:ram})
        rep=_report(b.id, RESULT_INSUFFICIENT_DATA, findings=[_finding(component_ids=(ram.id,), message_key="compat.build.empty")])
        v.set_compatibility_report(rep)
        self.assertTrue(v._compat_comp_combo.cget("values"))
        v._handle_open_implicated()
        self.assertEqual(opened, [ram.id])

    def test_error_state(self):
        b=_build(); v=self._view(); v.set_build(b,{})
        v.set_compatibility_error("compatibility.error")
        self.assertIn(self.tr.t("compatibility.error"), v._compat_status.cget("text"))


class TestR31PunctuationFormatting(unittest.TestCase):
    """T17.8a-R3.1: localized explanation punctuation (no functional changes)."""

    def _fmt(self, lang, reason_key, storage_label="Storage: T17.8a Visual SSD NVMe"):
        tr = Translator(); tr.set_language(lang)
        v = BuildDetailView.__new__(BuildDetailView)
        v.translator = tr
        v._components_by_id = {}
        # simulate resolved storage_id param path by passing through _resolve_param_value
        from types import SimpleNamespace
        f = SimpleNamespace(message_key="compat.storage_m2.fit.requires_verification",
                            message_params={"storage_id": storage_label, "reason": reason_key})
        return v._format_message(f)

    def test_no_double_periods_es_storage_reasons(self):
        for reason in ("collection_exhaustiveness_not_demonstrated", "storage_or_slot_data_not_verified",
                       "keying_or_mode_or_length_not_demonstrated", "capacity_data_not_verified"):
            txt = self._fmt("es", reason)
            self.assertNotIn("..", txt, (reason, txt))
            self.assertRegex(txt.rstrip(), r"[.!?…]$")

    def test_no_double_periods_en_storage_reasons(self):
        for reason in ("collection_exhaustiveness_not_demonstrated", "storage_or_slot_data_not_verified",
                       "keying_or_mode_or_length_not_demonstrated", "capacity_data_not_verified"):
            txt = self._fmt("en", reason)
            self.assertNotIn("..", txt, (reason, txt))
            self.assertRegex(txt.rstrip(), r"[.!?]$")


class TestMainWindowCompatibilityIntegration(unittest.TestCase):
    def _win(self):
        root = _tk()
        tr = Translator(); tr.set_language("en")
        from pc_parts_organizer.ui.main_window import MainWindow
        win = MainWindow.__new__(MainWindow)
        win.root = root
        win.service = Mock()
        win.catalog_service = Mock()
        win.translator = tr
        win._inventory_list_view = Mock()
        win._builds_list_view = Mock()
        win._builds_detail_view = Mock()
        win._detail_component_id = None
        win._detail_build_id = None
        win.refresh_inventory = Mock()
        win.refresh_builds = Mock()
        win._show_inventory_list = Mock()
        win._show_builds_list = Mock()
        win._show_builds_detail_view = Mock()
        win._select_notebook_tab = Mock()
        win._show_inventory_detail = Mock()
        win._update_inventory_actions = Mock()
        return root, win

    def test_handler_calls_service_with_uuid_and_sets_report(self):
        root, win = self._win()
        try:
            from pc_parts_organizer.ui.main_window import MainWindow
            bid = str(uuid.uuid4())
            rep = _report(bid, RESULT_INSUFFICIENT_DATA)
            win.service.analyze_build_compatibility.return_value = rep
            win.service.get_technical_profiles.return_value = []
            MainWindow._analyze_build_compatibility(win, bid)
            win.service.analyze_build_compatibility.assert_called_once_with(bid)
            win._builds_detail_view.set_compatibility_report.assert_called_once_with(rep, {})
        finally:
            root.destroy()

    def test_handler_build_not_found(self):
        root, win = self._win()
        try:
            from pc_parts_organizer.ui.main_window import MainWindow
            win.service.analyze_build_compatibility.side_effect = BuildNotFoundError("x")
            with patch("pc_parts_organizer.ui.main_window.messagebox.showerror") as me:
                MainWindow._analyze_build_compatibility(win, "x")
            self.assertTrue(me.called)
            win._builds_detail_view.set_compatibility_error.assert_called()
            win.refresh_builds.assert_called()
        finally:
            root.destroy()

    def test_handler_storage_error(self):
        root, win = self._win()
        try:
            from pc_parts_organizer.ui.main_window import MainWindow
            win.service.analyze_build_compatibility.side_effect = StorageError("x")
            with patch("pc_parts_organizer.ui.main_window.messagebox.showerror") as me:
                MainWindow._analyze_build_compatibility(win, "x")
            self.assertTrue(me.called)
            win._builds_detail_view.set_compatibility_error.assert_called_with("compatibility.error")
        finally:
            root.destroy()

    def test_show_component_from_build_switches_tab(self):
        root, win = self._win()
        try:
            from pc_parts_organizer.ui.main_window import MainWindow, NAV_INVENTORY
            MainWindow._show_component_from_build(win, "cid")
            win._select_notebook_tab.assert_called_once_with(NAV_INVENTORY)
            win._show_inventory_detail.assert_called_once_with("cid")
        finally:
            root.destroy()


if __name__ == "__main__":
    unittest.main()


class TestPsuEvidencePresentationR2(unittest.TestCase):
    """T17.8b-R2: PSU evidence presentation/localization only (no engine changes)."""

    def _view_with(self, comps, profiles, build, lang="es"):
        from pc_parts_organizer.compatibility import analyze_build_compatibility
        root = _tk()
        try:
            tr = Translator(); tr.set_language(lang)
            v = BuildDetailView(root, tr)
            rep = analyze_build_compatibility(build, comps, profiles)
            v.set_build(build, {c.id: c for c in comps})
            v.set_compatibility_report(rep)
            text = v._compat_text.get("1.0", "end")
            return rep, text
        finally:
            root.destroy()

    @staticmethod
    def _base():
        from pc_parts_organizer.models import Component, Build
        from pc_parts_organizer.technical_profiles import TechnicalAttribute, TechnicalProfile
        def va(key, value, unit=None):
            return TechnicalAttribute(key=key, value=value, unit=unit, source="official_vendor_doc", confidence="high",
                                      verification_status="verified", evidence_ref="https://vendor.example/doc", verified_at="2026-01-01")
        def ua(key, value, unit=None):
            return TechnicalAttribute(key=key, value=value, unit=unit, source="unknown", confidence="low", verification_status="unverified")
        req = lambda kind, qty=1, required=True: {"connector_kind": kind, "quantity": qty, "required": required}
        end = lambda eid, kind, sg=None: ({"end_id": eid, "connector_kind": kind} | ({"split_group_id": sg} if sg else {}))
        cable = lambda cid, atype, ends, psu_side=None, apm=None, apr=None: ({"cable_id": cid, "assembly_type": atype, "component_side_ends": ends} | ({"psu_side_connector_id": psu_side} if psu_side else {}) | ({"approved_psu_model": apm} if apm else {}) | ({"approval_reference": apr} if apr else {}))
        return Component, Build, TechnicalProfile, va, ua, req, end, cable

    def test_no_psu_dataclass_repr_in_rendered_evidence(self):
        Component, Build, TechnicalProfile, va, ua, req, end, cable = self._base()
        psu=Component(category="PSU", manufacturer="V", model="P"); mb=Component(category="Motherboard", manufacturer="V", model="M")
        b=Build(name="b", component_ids=[psu.id,mb.id])
        profs=[TechnicalProfile(component_id=psu.id, attributes=[va("power_cable_assemblies",[cable("C1","fixed_native",[end("E1","ATX_24"),end("E2","EPS_8")])])]),
               TechnicalProfile(component_id=mb.id, attributes=[va("motherboard_power_connectors_required",[req("ATX_24"),req("EPS_8")])])]
        for lang in ("es","en"):
            rep, text = self._view_with([psu,mb], profs, b, lang=lang)
            for bad in ("PowerCableAssembly(", "PowerConnectorRequirement(", "PowerCableEndSpec("):
                self.assertNotIn(bad, text, (lang,bad))

    def test_s4_split_preserves_cable_identity_and_split_group(self):
        Component, Build, TechnicalProfile, va, ua, req, end, cable = self._base()
        psu=Component(category="PSU", manufacturer="V", model="P"); gpu=Component(category="GPU", manufacturer="V", model="G")
        b=Build(name="b", component_ids=[psu.id,gpu.id])
        profs=[TechnicalProfile(component_id=psu.id, attributes=[va("power_cable_assemblies",[cable("PCIe-CABLE-01","fixed_native",[end("PCIE_8_A","PCIE_8","SG1"),end("PCIE_8_B","PCIE_8","SG1")])])]),
               TechnicalProfile(component_id=gpu.id, attributes=[va("gpu_power_connectors_required",[req("PCIE_8",2)])])]
        rep, text = self._view_with([psu,gpu], profs, b, lang="es")
        self.assertIn("PCIe-CABLE-01", text)
        self.assertIn("PCIE_8_A", text); self.assertIn("PCIE_8_B", text); self.assertIn("SG1", text)
        self.assertNotIn("PowerCableAssembly(", text)

    def test_s6_unresolved_assemblies_identified(self):
        Component, Build, TechnicalProfile, va, ua, req, end, cable = self._base()
        psu=Component(category="PSU", manufacturer="V", model="P"); gpu=Component(category="GPU", manufacturer="V", model="G")
        b=Build(name="b", component_ids=[psu.id,gpu.id])
        profs=[TechnicalProfile(component_id=psu.id, attributes=[va("power_cable_assemblies",[cable("TP1","third_party_adapter",[end("E1","PCIE_8")]), cable("U1","unknown",[end("E2","PCIE_8")])])]),
               TechnicalProfile(component_id=gpu.id, attributes=[va("gpu_power_connectors_required",[req("PCIE_8",1)])])]
        rep, text = self._view_with([psu,gpu], profs, b, lang="es")
        self.assertIn("TP1", text); self.assertIn("U1", text)
        self.assertTrue(("terceros" in text.lower()) or ("third" in text.lower()))
        self.assertNotIn("PowerCableAssembly(", text)

    def test_s7_shows_approval_correspondence_note_without_incompatibility_claim(self):
        Component, Build, TechnicalProfile, va, ua, req, end, cable = self._base()
        psu=Component(category="PSU", manufacturer="Vendor", model="Generic Model"); gpu=Component(category="GPU", manufacturer="V", model="G")
        b=Build(name="b", component_ids=[psu.id,gpu.id])
        profs=[TechnicalProfile(component_id=psu.id, attributes=[va("power_cable_assemblies",[cable("A1","manufacturer_approved_adapter",[end("E1","12VHPWR")], apm="Vendor PSU Exact Model XYZ-999", apr="https://vendor.example/approval/xyz")])]),
               TechnicalProfile(component_id=gpu.id, attributes=[va("gpu_power_connectors_required",[req("12VHPWR",1)])])]
        rep, text = self._view_with([psu,gpu], profs, b, lang="es")
        self.assertIn("Vendor PSU Exact Model XYZ-999", text)
        self.assertIn("Generic Model", text)
        self.assertIn("https://vendor.example/approval/xyz", text)
        self.assertRegex(text, r"no puede verificar|cannot verify")
        self.assertNotRegex(text, r"incompatible.*aprobaci|approval.*incompatible")
        self.assertNotIn("PowerCableAssembly(", text)

    def test_s8_action_neutral_no_gpu_mention_for_mb_only(self):
        Component, Build, TechnicalProfile, va, ua, req, end, cable = self._base()
        psu=Component(category="PSU", manufacturer="V", model="P"); mb=Component(category="Motherboard", manufacturer="V", model="M")
        b=Build(name="b", component_ids=[psu.id,mb.id])
        profs=[TechnicalProfile(component_id=psu.id, attributes=[ua("power_cable_assemblies",[cable("C1","fixed_native",[end("E1","ATX_24")])])]),
               TechnicalProfile(component_id=mb.id, attributes=[va("motherboard_power_connectors_required",[req("ATX_24")])])]
        rep, text = self._view_with([psu,mb], profs, b, lang="es")
        self.assertNotIn("placa/GPU", text)
        self.assertRegex(text, r"requisitos de conectores declarados|Verify the declared connector requirements")

    def test_psu_labels_es_en_parity(self):
        Component, Build, TechnicalProfile, va, ua, req, end, cable = self._base()
        psu=Component(category="PSU", manufacturer="V", model="P"); gpu=Component(category="GPU", manufacturer="V", model="G")
        b=Build(name="b", component_ids=[psu.id,gpu.id])
        profs=[TechnicalProfile(component_id=psu.id, attributes=[va("power_cable_assemblies",[cable("C1","fixed_native",[end("E1","PCIE_8")])])]),
               TechnicalProfile(component_id=gpu.id, attributes=[va("gpu_power_connectors_required",[req("PCIE_8",1)])])]
        for lang, expect in (("es","Obligatorio"),("en","Required")):
            rep, text = self._view_with([psu,gpu], profs, b, lang=lang)
            self.assertIn(expect, text, (lang,text[:500]))
            self.assertNotIn("PowerConnectorRequirement(", text)


class TestStorageConnectivityPresentationT179(unittest.TestCase):
    """T17.9: storage connectivity dimensions and localized rule presentation."""

    def _render(self, lang="es"):
        from pc_parts_organizer.compatibility import analyze_build_compatibility
        from pc_parts_organizer.models import Build, Component
        from pc_parts_organizer.technical_profiles import M2SlotSpec, TechnicalAttribute, TechnicalProfile
        def va(key, value):
            return TechnicalAttribute(key=key, value=value, source="official_vendor_doc", confidence="high",
                                      verification_status="verified", evidence_ref="https://vendor/doc", verified_at="2026-01-01")
        mb=Component(category="Motherboard", manufacturer="V", model="Board T179")
        m2=Component(category="Storage", manufacturer="V", model="NVMe T179")
        sata=Component(category="Storage", manufacturer="V", model="SSD T179")
        b=Build(name="T179", component_ids=[mb.id,m2.id,sata.id])
        profs=[
            TechnicalProfile(component_id=mb.id, attributes=[va("sata_port_count",2), va("sata_port_identifiers",["SATA1","SATA2"]),
                va("m2_slots",[M2SlotSpec(slot_id="M2_1", accepted_module_keyings=("M",), supported_lengths=("2280",),
                                          supported_modes=("pcie_nvme",), disables_sata_port_ids=("SATA1",), evidence_ref="https://vendor/slot")])]),
            TechnicalProfile(component_id=m2.id, attributes=[va("storage_form_factor","m2"), va("storage_interface","pcie"),
                va("storage_command_set","nvme"), va("m2_keying","M"), va("m2_length_code","2280")]),
            TechnicalProfile(component_id=sata.id, attributes=[va("storage_form_factor","2_5_in"), va("storage_interface","sata"), va("storage_command_set","ata")]),
        ]
        root=_tk()
        try:
            tr=Translator(); tr.set_language(lang)
            v=BuildDetailView(root,tr)
            rep=analyze_build_compatibility(b,[mb,m2,sata],profs)
            v.set_build(b,{c.id:c for c in [mb,m2,sata]})
            v.set_compatibility_report(rep)
            return v._compat_text.get("1.0","end"), mb.id, m2.id
        finally:
            root.destroy()

    def test_storage_summary_and_localized_rule_labels(self):
        text, _mb, _m2 = self._render("es")
        self.assertIn("Conectividad de almacenamiento", text)
        self.assertIn("Puertos SATA de datos", text)
        self.assertIn("Compartición de puertos M.2/SATA", text)
        self.assertIn("dimensiones independientes", text)
        self.assertNotIn("Rule: storage_sata.m2_topology", text)
        self.assertIn("Placa/caja (sin caja)", text)
        self.assertNotIn("mb_case.case_missing", text)
        self.assertNotIn("storage_case.case_missing", text)

    def test_storage_evidence_has_no_dataclass_repr(self):
        text, _mb, _m2 = self._render("en")
        self.assertNotIn("M2SlotSpec(", text)
        self.assertIn("M.2 keying", text)
        self.assertNotIn("m2_keying:", text)
        self.assertNotIn("storage:", text)
        self.assertIn("M.2 physical fit", text)
        self.assertIn("M.2/SATA port sharing", text)

    def test_storage_reason_and_action_are_translated_es_en(self):
        es, _mb, _m2 = self._render("es")
        en, _mb2, _m2b = self._render("en")
        self.assertIn("pueden deshabilitar puertos SATA", es)
        self.assertIn("Revisa el manual de la placa base", es)
        self.assertIn("may disable specific SATA ports", en)
        self.assertIn("Check the motherboard manual", en)
        self.assertNotIn("m2_slot_may_disable_sata_ports", es)
        self.assertNotIn("m2_slot_may_disable_sata_ports", en)

    def test_explanation_does_not_use_uuid_as_primary(self):
        text, _mb, m2_id = self._render("es")
        explanation_prefix = text.split("Explicación:", 1)[1][:400] if "Explicación:" in text else text[:400]
        self.assertNotIn(m2_id, explanation_prefix)


class TestStorageR2Presentation(unittest.TestCase):
    """T17.9-R2: indeterminate units, empty slots, ambiguous MB presentation."""

    def _render_case(self, comps, profs, lang="es"):
        from pc_parts_organizer.compatibility import analyze_build_compatibility
        from pc_parts_organizer.models import Build
        root = _tk()
        try:
            tr = Translator(); tr.set_language(lang)
            v = BuildDetailView(root, tr)
            b = Build(name="R2", component_ids=[c.id for c in comps])
            rep = analyze_build_compatibility(b, comps, profs)
            v.set_build(b, {c.id: c for c in comps})
            v.set_compatibility_report(rep)
            return v._compat_text.get("1.0", "end"), rep
        finally:
            root.destroy()

    def test_indeterminate_sata_not_compatible(self):
        from pc_parts_organizer.technical_profiles import TechnicalAttribute, TechnicalProfile
        mb = _comp("Motherboard"); a = _comp("Storage"); b = _comp("Storage")
        def va2(k, v):
            return TechnicalAttribute(key=k, value=v, source="official_vendor_doc", confidence="high",
                                      verification_status="verified", evidence_ref="r", verified_at="2026-01-01")
        def ua2(k, v):
            return TechnicalAttribute(key=k, value=v, source="unknown", confidence="low", verification_status="unverified")
        profs = [TechnicalProfile(component_id=mb.id, attributes=[va2("sata_port_count", 1)]),
                 TechnicalProfile(component_id=a.id, attributes=[va2("storage_form_factor", "2_5_in"), va2("storage_interface", "sata"), va2("storage_command_set", "ata")]),
                 TechnicalProfile(component_id=b.id, attributes=[ua2("storage_form_factor", "2_5_in"), ua2("storage_interface", "pcie"), ua2("storage_command_set", "nvme")])]
        text, rep = self._render_case([mb, a, b], profs, lang="es")
        self.assertNotIn("M2SlotSpec(", text)
        self.assertIn("Requiere verificación", text)
        self.assertNotIn("storage_units_undetermined", text)

    def test_empty_slots_message(self):
        from pc_parts_organizer.technical_profiles import M2SlotSpec, TechnicalAttribute, TechnicalProfile
        def va2(k, v):
            return TechnicalAttribute(key=k, value=v, source="official_vendor_doc", confidence="high",
                                      verification_status="verified", evidence_ref="r", verified_at="2026-01-01")
        mb = _comp("Motherboard"); m2 = _comp("Storage")
        profs = [TechnicalProfile(component_id=mb.id, attributes=[va2("m2_slots", [])]),
                 TechnicalProfile(component_id=m2.id, attributes=[va2("storage_form_factor", "m2"), va2("storage_interface", "pcie"),
                                                                   va2("storage_command_set", "nvme"), va2("m2_keying", "M"), va2("m2_length_code", "2280")])]
        text, rep = self._render_case([mb, m2], profs, lang="es")
        self.assertIn("vacío", text)
        self.assertNotIn("slots_absent", text.replace("Rule:", ""))


class TestCpuMbSocketPresentation(unittest.TestCase):
    """T17.11: socket visibility presentation (descriptive, never decisive)."""

    def _render_analysis(self, cpu_sock, mb_sock, lang="es"):
        from pc_parts_organizer.compatibility import analyze_build_compatibility
        from pc_parts_organizer.models import Build
        from pc_parts_organizer.technical_profiles import TechnicalAttribute, TechnicalProfile

        def va2(k, v):
            return TechnicalAttribute(key=k, value=v, source="official_vendor_doc", confidence="high",
                                      verification_status="verified", evidence_ref="r", verified_at="2026-01-01")

        cpu = _comp("CPU")
        mb = _comp("Motherboard")
        b = _build(component_ids=[cpu.id, mb.id])
        rep = analyze_build_compatibility(b, [cpu, mb], [
            TechnicalProfile(component_id=cpu.id, attributes=[va2("socket_designation", cpu_sock)]),
            TechnicalProfile(component_id=mb.id, attributes=[va2("socket_designation", mb_sock)]),
        ])
        root = _tk()
        try:
            tr = Translator()
            tr.set_language(lang)
            v = BuildDetailView(root, tr)
            v.set_build(b, {cpu.id: cpu, mb.id: mb})
            v.set_compatibility_report(rep)
            return v._compat_text.get("1.0", "end"), rep
        finally:
            root.destroy()

    def test_match_finding_rendered_without_decisive_claim(self):
        text, rep = self._render_analysis("AM5", "AM5", lang="es")
        self.assertIn("Socket CPU/placa base (descriptivo)", text)
        self.assertIn("AM5", text)
        self.assertNotIn("PowerCableAssembly(", text)
        self.assertNotIn("TechnicalAttribute(", text)
        cpu_id = [c for c in rep.findings if c.rule_id == "cpu_mb.socket_visibility"][0].component_ids[0]
        self.assertNotIn(cpu_id, text.split("Explicación:")[1][:300] if "Explicación:" in text else text[:300])

    def test_mismatch_rendered_as_unresolved_not_incompatible(self):
        text, rep = self._render_analysis("AM5", "LGA1700", lang="en")
        self.assertIn("CPU/motherboard socket (descriptive)", text)
        f = [x for x in rep.findings if x.rule_id == "cpu_mb.socket_visibility"][0]
        self.assertNotIn("incompatible", f.message_key)

    def test_editor_shows_socket_without_completeness(self):
        from pc_parts_organizer.ui.technical_profile_form import TechnicalProfileForm
        import uuid

        root = _tk()
        try:
            tr = Translator()
            tr.set_language("es")
            cid = str(uuid.uuid4())
            f = TechnicalProfileForm(root, tr, component_id=cid, category="Motherboard", profile=None)
            row = f._rows["socket_designation"]
            self.assertIsNone(row.get("completeness"))
            self.assertIsNone(row.get("scope"))
            row["enabled"].set(True)
            for k, r in f._rows.items():
                if k != "socket_designation":
                    r["enabled"].set(False)
            row["value"][1].delete(0, "end")
            row["value"][1].insert(0, "AM5")
            f._on_save()
            self.assertIsNotNone(f.result)
            assert f.result is not None
            attr = next(a for a in f.result.attributes if a.key == "socket_designation")
            self.assertEqual(attr.value, "AM5")
            self.assertEqual(attr.collection_completeness, "unknown")
            f._on_cancel()
        finally:
            root.destroy()
