"""T17.11-R1: unresolvable form factors never decide Motherboard/Case fit."""
from __future__ import annotations

try:
    import tests._pcpo_test_isolation_bootstrap  # noqa: F401
except Exception:
    import _pcpo_test_isolation_bootstrap  # type: ignore  # noqa: F401

import unittest

from pc_parts_organizer.compatibility import (
    ENGINE_RULESET_VERSION,
    RESULT_COMPATIBLE,
    RESULT_INCOMPATIBLE,
    RESULT_INSUFFICIENT_DATA,
    RESULT_REQUIRES_VERIFICATION,
    SEVERITY_CRITICAL,
    analyze_build_compatibility,
)
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


def low_verified(key, value, **kw):
    base = dict(source="official_vendor_doc", confidence="low",
                verification_status="verified", evidence_ref="https://vendor/doc",
                verified_at="2026-01-01")
    base.update(kw)
    return TechnicalAttribute(key=key, value=value, **base)


def find(rep, rule):
    return [f for f in rep.findings if f.rule_id == rule]


def analyze_pair(mb_attrs, case_attrs):
    mb, case = comp("Motherboard"), comp("Case")
    b = Build(name="t1711r1", component_ids=[mb.id, case.id])
    return analyze_build_compatibility(b, [mb, case], [
        TechnicalProfile(component_id=mb.id, attributes=mb_attrs),
        TechnicalProfile(component_id=case.id, attributes=case_attrs),
    ]), mb, case


class TestUnresolvableListEntries(unittest.TestCase):
    def test_denounced_case_verified_atx_vs_other_only(self):
        r, mb, case = analyze_pair([va("form_factor", "ATX")],
                                   [va("supported_motherboard_form_factors", ["Other"])])
        f = find(r, "mb_case.form_factor")
        self.assertEqual(len(f), 1)
        self.assertEqual(f[0].result, RESULT_REQUIRES_VERIFICATION)
        self.assertNotEqual(f[0].result, RESULT_INCOMPATIBLE)
        self.assertNotEqual(f[0].severity, SEVERITY_CRITICAL)
        self.assertEqual(f[0].message_params["reason"], "other_not_confirmable")
        self.assertTrue(f[0].message_params["apparent_conflict"])
        self.assertEqual(set(f[0].component_ids), {mb.id, case.id})
        self.assertNotEqual(r.overall_result, RESULT_INCOMPATIBLE)

    def test_mixed_known_plus_other_mismatch_not_incompatible(self):
        r, _, _ = analyze_pair([va("form_factor", "ATX")],
                               [va("supported_motherboard_form_factors", ["Micro-ATX", "Other"])])
        f = find(r, "mb_case.form_factor")
        self.assertEqual(f[0].result, RESULT_REQUIRES_VERIFICATION)
        self.assertEqual(f[0].message_params["reason"], "other_not_confirmable")
        self.assertFalse(any(x.result == RESULT_INCOMPATIBLE and x.severity == SEVERITY_CRITICAL
                             for x in r.findings))

    def test_mixed_known_plus_other_match_stays_compatible(self):
        r, _, _ = analyze_pair([va("form_factor", "ATX")],
                               [va("supported_motherboard_form_factors", ["ATX", "Other"])])
        f = find(r, "mb_case.form_factor")
        self.assertEqual(f[0].result, RESULT_COMPATIBLE)

    def test_mb_other_stays_requires_verification(self):
        r, _, _ = analyze_pair([va("form_factor", "Other")],
                               [va("supported_motherboard_form_factors", ["ATX", "Other"])])
        f = find(r, "mb_case.form_factor")
        self.assertEqual(f[0].result, RESULT_REQUIRES_VERIFICATION)
        self.assertNotEqual(f[0].result, RESULT_COMPATIBLE)
        self.assertNotEqual(f[0].result, RESULT_INCOMPATIBLE)

    def test_mb_proprietary_unchanged(self):
        r, _, _ = analyze_pair([va("form_factor", "Proprietary")],
                               [va("supported_motherboard_form_factors", ["Proprietary"])])
        f = find(r, "mb_case.form_factor")
        self.assertEqual(f[0].result, RESULT_REQUIRES_VERIFICATION)
        self.assertEqual(f[0].message_params["reason"], "proprietary_requires_specific_documentation")

    def test_case_proprietary_only_unchanged(self):
        r, _, _ = analyze_pair([va("form_factor", "ATX")],
                               [va("supported_motherboard_form_factors", ["Proprietary"])])
        f = find(r, "mb_case.form_factor")
        self.assertEqual(f[0].result, RESULT_REQUIRES_VERIFICATION)

    def test_recognized_mismatch_still_incompatible(self):
        r, _, _ = analyze_pair([va("form_factor", "E-ATX")],
                               [va("supported_motherboard_form_factors", ["ATX"])])
        f = find(r, "mb_case.form_factor")
        self.assertEqual(f[0].result, RESULT_INCOMPATIBLE)
        self.assertEqual(f[0].severity, SEVERITY_CRITICAL)
        self.assertEqual(r.overall_result, RESULT_INCOMPATIBLE)

    def test_recognized_match_still_compatible_dimension(self):
        r, _, _ = analyze_pair([va("form_factor", "ATX")],
                               [va("supported_motherboard_form_factors", ["ATX", "Micro-ATX"])])
        f = find(r, "mb_case.form_factor")
        self.assertEqual(f[0].result, RESULT_COMPATIBLE)

    def test_missing_unverified_low_confidence_paths(self):
        # missing motherboard form factor
        r, _, _ = analyze_pair([],
                               [va("supported_motherboard_form_factors", ["ATX"])])
        self.assertEqual(find(r, "mb_case.form_factor")[0].result, RESULT_INSUFFICIENT_DATA)
        # unverified contradiction
        r, _, _ = analyze_pair([ua("form_factor", "E-ATX")],
                               [va("supported_motherboard_form_factors", ["ATX"])])
        self.assertEqual(find(r, "mb_case.form_factor")[0].result, RESULT_REQUIRES_VERIFICATION)
        # verified but low confidence contradiction
        r, _, _ = analyze_pair([low_verified("form_factor", "E-ATX")],
                               [va("supported_motherboard_form_factors", ["ATX"])])
        self.assertEqual(find(r, "mb_case.form_factor")[0].result, RESULT_REQUIRES_VERIFICATION)
        # unverified Other list still requires verification, never critical
        r, _, _ = analyze_pair([va("form_factor", "ATX")],
                               [ua("supported_motherboard_form_factors", ["Other"])])
        f = find(r, "mb_case.form_factor")[0]
        self.assertEqual(f.result, RESULT_REQUIRES_VERIFICATION)
        self.assertNotEqual(f.severity, SEVERITY_CRITICAL)

    def test_no_critical_from_unresolvable(self):
        cases = [
            ([va("form_factor", "ATX")], [va("supported_motherboard_form_factors", ["Other"])]),
            ([va("form_factor", "ATX")], [va("supported_motherboard_form_factors", ["Micro-ATX", "Other"])]),
            ([va("form_factor", "Other")], [va("supported_motherboard_form_factors", ["ATX"])]),
            ([va("form_factor", "Proprietary")], [va("supported_motherboard_form_factors", ["ATX"])]),
            ([ua("form_factor", "ATX")], [ua("supported_motherboard_form_factors", ["Other"])]),
        ]
        for i, (ma, ca) in enumerate(cases):
            with self.subTest(i=i):
                r, _, _ = analyze_pair(ma, ca)
                for f in find(r, "mb_case.form_factor"):
                    self.assertNotEqual(f.severity, SEVERITY_CRITICAL)
                    self.assertNotEqual(f.result, RESULT_INCOMPATIBLE)

    def test_global_not_degraded_by_unresolvable(self):
        r, _, _ = analyze_pair([va("form_factor", "ATX")],
                               [va("supported_motherboard_form_factors", ["Other"])])
        # requires_verification from the rule, never a critical incompatible
        self.assertEqual(r.overall_result, RESULT_REQUIRES_VERIFICATION)
        self.assertFalse(any(f.result == RESULT_INCOMPATIBLE and f.severity == SEVERITY_CRITICAL
                             for f in r.findings))

    def test_participants_evidence_and_count(self):
        r, mb, case = analyze_pair([va("form_factor", "ATX")],
                                   [va("supported_motherboard_form_factors", ["Other"])])
        f = find(r, "mb_case.form_factor")[0]
        self.assertEqual(set(f.component_ids), {mb.id, case.id})
        self.assertEqual(list(f.attributes_compared), ["form_factor", "supported_motherboard_form_factors"])
        self.assertEqual(f.evidence["motherboard"]["value"], "ATX")
        self.assertEqual(list(f.evidence["case"]["value"]), ["Other"])
        self.assertEqual(r.rules_evaluated, 1)

    def test_purity_determinism(self):
        import copy
        mb, case = comp("Motherboard"), comp("Case")
        comps = [mb, case]
        profs = [TechnicalProfile(component_id=mb.id, attributes=[va("form_factor", "ATX")]),
                 TechnicalProfile(component_id=case.id, attributes=[va("supported_motherboard_form_factors", ["Other"])])]
        b = Build(name="t1711r1", component_ids=[c.id for c in comps])
        before = [p.to_dict() for p in profs]
        b_before = copy.deepcopy(b.__dict__)
        r1 = analyze_build_compatibility(b, comps, profs)
        r2 = analyze_build_compatibility(b, comps, profs)
        self.assertEqual([p.to_dict() for p in profs], before)
        self.assertEqual(b.__dict__, b_before)
        self.assertEqual([(f.rule_id, f.result) for f in r1.findings], [(f.rule_id, f.result) for f in r2.findings])

    def test_service_integration_no_persistence(self):
        from pc_parts_organizer.service import InventoryService
        from pc_parts_organizer.storage import load_project_state
        svc = InventoryService()
        mb = svc.add_component("Motherboard", "M", "MB R1", "", "")
        case = svc.add_component("Case", "M", "Case R1", "", "")
        svc.set_technical_profile(TechnicalProfile(component_id=mb.id, attributes=[va("form_factor", "ATX")]))
        svc.set_technical_profile(TechnicalProfile(component_id=case.id, attributes=[va("supported_motherboard_form_factors", ["Other"])]))
        b = svc.add_build("T17.11-R1 service")
        svc.add_component_to_build(b.id, mb.id)
        svc.add_component_to_build(b.id, case.id)
        before = load_project_state()
        rep = svc.analyze_build_compatibility(b.id)
        after = load_project_state()
        self.assertEqual(find(rep, "mb_case.form_factor")[0].result, RESULT_REQUIRES_VERIFICATION)
        self.assertEqual(len(before.components), len(after.components))
        self.assertEqual(len(before.builds), len(after.builds))
        self.assertEqual(len(before.technical_profiles), len(after.technical_profiles))

    def test_locales_resolve_both_languages(self):
        from pc_parts_organizer.localization import Translator
        for lang in ("es", "en"):
            tr = Translator()
            tr.set_language(lang)
            reason = tr.t("compatibility.reasons.other_not_confirmable")
            self.assertNotIn("compatibility.reasons", reason)
            msg = tr.t("compatibility.messages.compat.mb_case.form_factor.requires_verification")
            self.assertIn("{reason}", msg)
            self.assertIn("{apparent_conflict}", msg)
            out = msg.format(form_factor="ATX", supported=["Other"], reason=reason, apparent_conflict=True)
            self.assertIn("ATX", out)
            action = tr.t("compatibility.recommended_actions.verify_physical_compatibility")
            self.assertNotIn("compatibility.recommended_actions", action)

    def test_engine_version(self):
        self.assertEqual(ENGINE_RULESET_VERSION, "t17.12-v1")

    def test_message_renders_without_placeholders(self):
        from pc_parts_organizer.localization import Translator
        for lang in ("es", "en"):
            tr = Translator()
            tr.set_language(lang)
            tpl = tr.t("compatibility.messages.compat.mb_case.form_factor.requires_verification")
            reason = tr.t("compatibility.reasons.attributes_not_verified")
            self.assertNotIn("compatibility.", reason)
            out = tpl.format(form_factor="ATX", supported=["ATX"], apparent_conflict=True, reason=reason)
            self.assertNotIn("{", out)
            self.assertNotIn("}", out)
            self.assertIn("ATX", out)


class TestMbCasePresentation(unittest.TestCase):
    def _tk(self):
        import tkinter as tk
        try:
            root = tk.Tk()
            root.withdraw()
        except tk.TclError as exc:
            self.skipTest(f"Tk unavailable: {exc}")
        return root

    def test_denounced_finding_renders_without_placeholders(self):
        from pc_parts_organizer.localization import Translator
        from pc_parts_organizer.ui.build_detail_view import BuildDetailView
        from pc_parts_organizer.ui.theme import configure_theme
        mb, case = comp("Motherboard"), comp("Case")
        b = Build(name="t1711r1", component_ids=[mb.id, case.id])
        rep = analyze_build_compatibility(b, [mb, case], [
            TechnicalProfile(component_id=mb.id, attributes=[va("form_factor", "ATX")]),
            TechnicalProfile(component_id=case.id, attributes=[va("supported_motherboard_form_factors", ["Other"])]),
        ])
        root = self._tk()
        try:
            configure_theme(root)
            for lang in ("es", "en"):
                tr = Translator()
                tr.set_language(lang)
                v = BuildDetailView(root, tr)
                v.set_build(b, {mb.id: mb, case.id: case})
                v.set_compatibility_report(rep)
                text = v._compat_text.get("1.0", "end")
                self.assertIn("ATX", text)
                self.assertIn("Other", text)
                self.assertNotIn("{apparent_conflict}", text)
                self.assertNotIn("{reason}", text)
                self.assertNotIn("PowerCableAssembly(", text)
                v.destroy()
        finally:
            root.destroy()


if __name__ == "__main__":
    unittest.main()
