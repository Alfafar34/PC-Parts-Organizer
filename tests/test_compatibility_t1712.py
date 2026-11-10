"""T17.12: PSU <-> Case physical form factor (descriptive mounting check)."""
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
    SEVERITY_INFO,
    SEVERITY_WARNING,
    analyze_build_compatibility,
)
from pc_parts_organizer.models import Build, Component
from pc_parts_organizer.technical_profiles import (
    PROFILE_REGISTRY_VERSION,
    TechnicalAttribute,
    TechnicalProfile,
    TechnicalProfileValidationError,
)


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


def analyze_pair(psu_attrs, case_attrs):
    psu, case = comp("PSU"), comp("Case")
    b = Build(name="t1712", component_ids=[psu.id, case.id])
    return analyze_build_compatibility(b, [psu, case], [
        TechnicalProfile(component_id=psu.id, attributes=psu_attrs),
        TechnicalProfile(component_id=case.id, attributes=case_attrs),
    ]), psu, case


class TestPsuFormFactorModel(unittest.TestCase):
    def test_registry_keys(self):
        from pc_parts_organizer.technical_profiles import ATTRIBUTE_REGISTRY, PSU_FORM_FACTORS
        self.assertIn("psu_form_factor", ATTRIBUTE_REGISTRY["PSU"])
        self.assertIn("supported_psu_form_factors", ATTRIBUTE_REGISTRY["Case"])
        self.assertEqual(tuple(PSU_FORM_FACTORS),
                         ("ATX", "SFX", "SFX-L", "TFX", "FlexATX", "Proprietary", "Other"))
        self.assertFalse(ATTRIBUTE_REGISTRY["PSU"]["psu_form_factor"].allows_completeness)
        self.assertFalse(ATTRIBUTE_REGISTRY["Case"]["supported_psu_form_factors"].allows_completeness)

    def test_normalization(self):
        self.assertEqual(va("psu_form_factor", "atx").value, "ATX")
        self.assertEqual(va("psu_form_factor", " sfx-l ").value, "SFX-L")
        self.assertEqual(va("supported_psu_form_factors", ["SFX", "ATX"]).value, ["ATX", "SFX"])
        for bad in ["ATX12V", "SFX L", "", 12, None, ["ATX", "ATX"], []]:
            with self.subTest(bad=bad):
                key = "supported_psu_form_factors" if isinstance(bad, list) else "psu_form_factor"
                with self.assertRaises(TechnicalProfileValidationError):
                    TechnicalAttribute(key=key, value=bad)

    def test_no_aliases_or_equivalences(self):
        with self.assertRaises(TechnicalProfileValidationError):
            TechnicalAttribute(key="psu_form_factor", value="sfx l")
        with self.assertRaises(TechnicalProfileValidationError):
            TechnicalAttribute(key="psu_form_factor", value="SFXL")

    def test_completeness_rejected(self):
        with self.assertRaises(TechnicalProfileValidationError):
            TechnicalAttribute(key="psu_form_factor", value="ATX", collection_completeness="complete",
                               completeness_scope="all", source="official_vendor_doc",
                               confidence="high", verification_status="verified",
                               evidence_ref="https://vendor/doc", verified_at="2026-01-01")
        with self.assertRaises(TechnicalProfileValidationError):
            TechnicalAttribute(key="supported_psu_form_factors", value=["ATX"],
                               collection_completeness="partial", completeness_scope="x")

    def test_metadata_preserved(self):
        a = va("psu_form_factor", "TFX")
        self.assertEqual((a.source, a.confidence, a.verification_status), ("official_vendor_doc", "high", "verified"))
        self.assertEqual((a.evidence_ref, a.verified_at), ("https://vendor/doc", "2026-01-01"))

    def test_old_profiles_without_keys_still_valid(self):
        p = TechnicalProfile(component_id=comp("PSU").id,
                             attributes=[va("rated_continuous_power_w", 650)])
        self.assertEqual([a.key for a in p.attributes], ["rated_continuous_power_w"])
        c = TechnicalProfile(component_id=comp("Case").id,
                             attributes=[va("max_gpu_length_mm", 300)])
        self.assertEqual([a.key for a in c.attributes], ["max_gpu_length_mm"])

    def test_round_trip(self):
        from pc_parts_organizer.technical_profiles import validate_profile_for_category
        cid = comp("PSU").id
        p = TechnicalProfile(component_id=cid, attributes=[va("psu_form_factor", "SFX-L")])
        d = p.to_dict()
        back = TechnicalProfile(component_id=d["component_id"], profile_version=d["profile_version"],
                                attributes=[TechnicalAttribute(**a) for a in d["attributes"]])
        self.assertEqual(back.to_dict(), d)
        normed = validate_profile_for_category(p, "PSU")
        self.assertEqual(normed.attributes[0].value, "SFX-L")
        with self.assertRaises(TechnicalProfileValidationError):
            validate_profile_for_category(p, "Case")


class TestPsuCaseRule(unittest.TestCase):
    def test_exact_match_compatible(self):
        r, psu, case = analyze_pair([va("psu_form_factor", "ATX")],
                                    [va("supported_psu_form_factors", ["ATX"])])
        f = find(r, "psu_case.form_factor")
        self.assertEqual(len(f), 1)
        self.assertEqual(f[0].result, RESULT_COMPATIBLE)
        self.assertEqual(f[0].severity, SEVERITY_INFO)
        self.assertEqual(set(f[0].component_ids), {psu.id, case.id})
        self.assertEqual(r.rules_evaluated, 1)

    def test_all_recognized_formats(self):
        for ff in ["ATX", "SFX", "SFX-L", "TFX", "FlexATX"]:
            other = "TFX" if ff != "TFX" else "ATX"
            with self.subTest(ff=ff):
                r, _, _ = analyze_pair([va("psu_form_factor", ff)],
                                       [va("supported_psu_form_factors", [ff, other])])
                self.assertEqual(find(r, "psu_case.form_factor")[0].result, RESULT_COMPATIBLE)

    def test_recognized_mismatch_incompatible(self):
        r, _, _ = analyze_pair([va("psu_form_factor", "ATX")],
                               [va("supported_psu_form_factors", ["SFX"])])
        f = find(r, "psu_case.form_factor")
        self.assertEqual(f[0].result, RESULT_INCOMPATIBLE)
        self.assertEqual(f[0].severity, SEVERITY_CRITICAL)
        self.assertEqual(r.overall_result, RESULT_INCOMPATIBLE)

    def test_sfx_vs_sfxl_both_directions(self):
        for ff, supported in [("SFX", ["SFX-L"]), ("SFX-L", ["SFX"])]:
            with self.subTest(ff=ff, supported=supported):
                r, _, _ = analyze_pair([va("psu_form_factor", ff)],
                                       [va("supported_psu_form_factors", supported)])
                f = find(r, "psu_case.form_factor")[0]
                self.assertEqual(f.result, RESULT_REQUIRES_VERIFICATION)
                self.assertNotEqual(f.severity, SEVERITY_CRITICAL)
                self.assertEqual(f.message_params["reason"], "sfx_sfxl_requires_manual_check")

    def test_sfx_family_overlap_with_other_formats(self):
        r, _, _ = analyze_pair([va("psu_form_factor", "SFX")],
                               [va("supported_psu_form_factors", ["SFX-L", "ATX"])])
        f = find(r, "psu_case.form_factor")[0]
        self.assertEqual(f.result, RESULT_REQUIRES_VERIFICATION)
        self.assertEqual(f.message_params["reason"], "sfx_sfxl_requires_manual_check")

    def test_sfx_exact_match_stays_compatible(self):
        r, _, _ = analyze_pair([va("psu_form_factor", "SFX")],
                               [va("supported_psu_form_factors", ["SFX", "SFX-L"])])
        self.assertEqual(find(r, "psu_case.form_factor")[0].result, RESULT_COMPATIBLE)

    def test_other_psu(self):
        r, _, _ = analyze_pair([va("psu_form_factor", "Other")],
                               [va("supported_psu_form_factors", ["ATX", "Other"])])
        f = find(r, "psu_case.form_factor")[0]
        self.assertEqual(f.result, RESULT_REQUIRES_VERIFICATION)
        self.assertEqual(f.message_params["reason"], "other_not_confirmable")
        self.assertNotEqual(f.result, RESULT_COMPATIBLE)

    def test_other_in_case_list(self):
        r, _, _ = analyze_pair([va("psu_form_factor", "ATX")],
                               [va("supported_psu_form_factors", ["Other"])])
        f = find(r, "psu_case.form_factor")[0]
        self.assertEqual(f.result, RESULT_REQUIRES_VERIFICATION)
        self.assertEqual(f.message_params["reason"], "other_not_confirmable")
        self.assertNotEqual(r.overall_result, RESULT_INCOMPATIBLE)

    def test_proprietary_either_side(self):
        for ma, ca in [(["Proprietary"], ["ATX"]), (["ATX"], ["Proprietary"]),
                       (["Proprietary"], ["Proprietary"])]:
            with self.subTest(psu=ma, case=ca):
                r, _, _ = analyze_pair([va("psu_form_factor", ma[0])],
                                       [va("supported_psu_form_factors", ca)])
                f = find(r, "psu_case.form_factor")[0]
                self.assertEqual(f.result, RESULT_REQUIRES_VERIFICATION)
                self.assertEqual(f.message_params["reason"], "proprietary_requires_specific_documentation")
                self.assertNotEqual(f.severity, SEVERITY_CRITICAL)

    def test_mixed_list_with_match(self):
        r, _, _ = analyze_pair([va("psu_form_factor", "SFX")],
                               [va("supported_psu_form_factors", ["ATX", "SFX"])])
        self.assertEqual(find(r, "psu_case.form_factor")[0].result, RESULT_COMPATIBLE)

    def test_missing_unverified_low_confidence(self):
        r, _, _ = analyze_pair([], [va("supported_psu_form_factors", ["ATX"])])
        self.assertEqual(find(r, "psu_case.form_factor")[0].result, RESULT_INSUFFICIENT_DATA)
        r, _, _ = analyze_pair([ua("psu_form_factor", "ATX")],
                               [va("supported_psu_form_factors", ["SFX"])])
        self.assertEqual(find(r, "psu_case.form_factor")[0].result, RESULT_REQUIRES_VERIFICATION)
        r, _, _ = analyze_pair([low_verified("psu_form_factor", "ATX")],
                               [va("supported_psu_form_factors", ["SFX"])])
        self.assertEqual(find(r, "psu_case.form_factor")[0].result, RESULT_REQUIRES_VERIFICATION)

    def test_no_critical_from_unresolvable(self):
        cases = [
            ([va("psu_form_factor", "Other")], [va("supported_psu_form_factors", ["ATX"])]),
            ([va("psu_form_factor", "ATX")], [va("supported_psu_form_factors", ["Other"])]),
            ([va("psu_form_factor", "Proprietary")], [va("supported_psu_form_factors", ["ATX"])]),
            ([va("psu_form_factor", "SFX")], [va("supported_psu_form_factors", ["SFX-L"])]),
            ([ua("psu_form_factor", "SFX")], [ua("supported_psu_form_factors", ["SFX-L"])]),
        ]
        for i, (ma, ca) in enumerate(cases):
            with self.subTest(i=i):
                r, _, _ = analyze_pair(ma, ca)
                for f in find(r, "psu_case.form_factor"):
                    self.assertNotEqual(f.severity, SEVERITY_CRITICAL)
                    self.assertNotEqual(f.result, RESULT_INCOMPATIBLE)

    def test_participants_evidence(self):
        r, psu, case = analyze_pair([va("psu_form_factor", "ATX")],
                                    [va("supported_psu_form_factors", ["SFX"])])
        f = find(r, "psu_case.form_factor")[0]
        self.assertEqual(set(f.component_ids), {psu.id, case.id})
        self.assertEqual(list(f.attributes_compared), ["psu_form_factor", "supported_psu_form_factors"])
        self.assertEqual(f.evidence["psu"]["value"], "ATX")
        self.assertEqual(list(f.evidence["case"]["value"]), ["SFX"])

    def test_multiple_participants_not_compared(self):
        from pc_parts_organizer.compatibility.engine import build_context
        p1, p2, case = comp("PSU", "P1"), comp("PSU", "P2"), comp("Case", "C")
        b = Build(name="t1712", component_ids=[p1.id, p2.id, case.id])
        r = analyze_build_compatibility(b, [p1, p2, case], [
            TechnicalProfile(component_id=p1.id, attributes=[va("psu_form_factor", "ATX")]),
            TechnicalProfile(component_id=p2.id, attributes=[va("psu_form_factor", "ATX")]),
            TechnicalProfile(component_id=case.id, attributes=[va("supported_psu_form_factors", ["ATX"])]),
        ])
        self.assertEqual(find(r, "psu_case.form_factor"), [])
        p, c1, c2 = comp("PSU"), comp("Case", "C1"), comp("Case", "C2")
        b = Build(name="t1712", component_ids=[p.id, c1.id, c2.id])
        r = analyze_build_compatibility(b, [p, c1, c2], [
            TechnicalProfile(component_id=p.id, attributes=[va("psu_form_factor", "ATX")]),
            TechnicalProfile(component_id=c1.id, attributes=[va("supported_psu_form_factors", ["ATX"])]),
            TechnicalProfile(component_id=c2.id, attributes=[va("supported_psu_form_factors", ["ATX"])]),
        ])
        self.assertEqual(find(r, "psu_case.form_factor"), [])

    def test_psu_without_case(self):
        psu = comp("PSU")
        b = Build(name="t1712", component_ids=[psu.id])
        r = analyze_build_compatibility(b, [psu],
                                        [TechnicalProfile(component_id=psu.id, attributes=[va("psu_form_factor", "ATX")])])
        f = find(r, "psu_case.case_missing")
        self.assertEqual(len(f), 1)
        self.assertEqual(f[0].result, RESULT_INSUFFICIENT_DATA)

    def test_case_without_psu_no_finding(self):
        case = comp("Case")
        b = Build(name="t1712", component_ids=[case.id])
        r = analyze_build_compatibility(b, [case],
                                        [TechnicalProfile(component_id=case.id, attributes=[va("supported_psu_form_factors", ["ATX"])])])
        self.assertEqual([f for f in r.findings if f.rule_id.startswith("psu_case.")], [])

    def test_not_evaluated_and_limitations(self):
        r, _, _ = analyze_pair([va("psu_form_factor", "ATX")],
                               [va("supported_psu_form_factors", ["ATX"])])
        ne = {(n["category"], n["reason"]) for n in r.not_evaluated_relations}
        self.assertIn(("PSU", "case_psu_depth_not_evaluated"), ne)
        self.assertIn(("Case", "case_psu_depth_not_evaluated"), ne)
        self.assertIn(("PSU", "case_psu_cable_clearance_not_evaluated"), ne)
        self.assertIn(("Case", "case_psu_cable_clearance_not_evaluated"), ne)
        self.assertIn("psu_case_depth_not_evaluated", r.analysis_limitations)
        self.assertIn("psu_case_cable_clearance_not_evaluated", r.analysis_limitations)

    def test_no_ne_without_comparison(self):
        case = comp("Case")
        b = Build(name="t1712", component_ids=[case.id])
        r = analyze_build_compatibility(b, [case],
                                        [TechnicalProfile(component_id=case.id, attributes=[va("supported_psu_form_factors", ["ATX"])])])
        self.assertFalse(any("case_psu" in n["reason"] for n in r.not_evaluated_relations))
        self.assertFalse(any("psu_case" in lim for lim in r.analysis_limitations))

    def test_compatible_local_still_global_requires_verification(self):
        # Depth and cable clearance stay unevaluated, so global never claims full fit.
        r, _, _ = analyze_pair([va("psu_form_factor", "ATX")],
                               [va("supported_psu_form_factors", ["ATX"])])
        self.assertEqual(find(r, "psu_case.form_factor")[0].result, RESULT_COMPATIBLE)
        self.assertEqual(r.overall_result, RESULT_REQUIRES_VERIFICATION)

    def test_purity_determinism(self):
        import copy
        psu, case = comp("PSU"), comp("Case")
        comps = [psu, case]
        profs = [TechnicalProfile(component_id=psu.id, attributes=[va("psu_form_factor", "SFX")]),
                 TechnicalProfile(component_id=case.id, attributes=[va("supported_psu_form_factors", ["SFX-L"])])]
        b = Build(name="t1712", component_ids=[c.id for c in comps])
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
        psu = svc.add_component("PSU", "M", "PSU T17.12", "", "")
        case = svc.add_component("Case", "M", "Case T17.12", "", "")
        svc.set_technical_profile(TechnicalProfile(component_id=psu.id, attributes=[va("psu_form_factor", "SFX")]))
        svc.set_technical_profile(TechnicalProfile(component_id=case.id, attributes=[va("supported_psu_form_factors", ["SFX-L"])]))
        b = svc.add_build("T17.12 service")
        svc.add_component_to_build(b.id, psu.id)
        svc.add_component_to_build(b.id, case.id)
        before = load_project_state()
        rep = svc.analyze_build_compatibility(b.id)
        after = load_project_state()
        self.assertEqual(find(rep, "psu_case.form_factor")[0].result, RESULT_REQUIRES_VERIFICATION)
        self.assertEqual(len(before.components), len(after.components))
        self.assertEqual(len(before.builds), len(after.builds))
        self.assertEqual(len(before.technical_profiles), len(after.technical_profiles))

    def test_locales_resolve_both_languages(self):
        from pc_parts_organizer.localization import Translator
        for lang in ("es", "en"):
            tr = Translator()
            tr.set_language(lang)
            self.assertNotIn("psu_case", tr.t("compatibility.rule_labels.psu_case__form_factor"))
            self.assertNotIn("compatibility.reasons", tr.t("compatibility.reasons.sfx_sfxl_requires_manual_check"))
            tpl = tr.t("compatibility.messages.compat.psu_case.form_factor.requires_verification")
            reason = tr.t("compatibility.reasons.sfx_sfxl_requires_manual_check")
            out = tpl.format(form_factor="SFX", supported=["SFX-L"], reason=reason, apparent_conflict=True)
            self.assertIn("SFX", out)
            self.assertNotIn("{", out.replace("[", "").replace("]", ""))
            self.assertNotIn("compatibility.", tr.t("compatibility.recommended_actions.use_supported_psu_or_case"))
            self.assertNotIn("compatibility.", tr.t("compatibility.not_evaluated_reason.case_psu_depth_not_evaluated"))
            self.assertNotIn("compatibility.", tr.t("compatibility.not_evaluated_reason.case_psu_cable_clearance_not_evaluated"))
            self.assertNotIn("compatibility.", tr.t("compatibility.limitations_tokens.psu_case_depth_not_evaluated"))
            self.assertNotIn("compatibility.", tr.t("compatibility.limitations_tokens.psu_case_cable_clearance_not_evaluated"))

    def test_versions(self):
        self.assertEqual(ENGINE_RULESET_VERSION, "t17.12-v1")
        self.assertGreaterEqual(PROFILE_REGISTRY_VERSION, 7)


class TestPsuCaseIntegration(unittest.TestCase):
    def _full_build(self, psu_ff, case_list, extra=None):
        mb, case, psu = comp("Motherboard", "MB"), comp("Case", "C"), comp("PSU", "P")
        comps = [mb, case, psu]
        profs = [
            TechnicalProfile(component_id=mb.id, attributes=[va("form_factor", "ATX")]),
            TechnicalProfile(component_id=case.id, attributes=[
                va("supported_motherboard_form_factors", ["ATX"]),
                va("supported_psu_form_factors", case_list),
            ]),
            TechnicalProfile(component_id=psu.id, attributes=[va("psu_form_factor", psu_ff)]),
        ]
        if extra:
            comps.extend(extra[0])
            profs.extend(extra[1])
        b = Build(name="t1712-full", component_ids=[c.id for c in comps])
        return analyze_build_compatibility(b, comps, profs)

    def test_combined_physical_relations(self):
        r = self._full_build("ATX", ["ATX"])
        by_rule = {f.rule_id for f in r.findings}
        self.assertIn("mb_case.form_factor", by_rule)
        self.assertIn("psu_case.form_factor", by_rule)
        self.assertEqual(r.overall_result, RESULT_REQUIRES_VERIFICATION)

    def test_legit_critical_elsewhere_preserved(self):
        mb, case, psu = comp("Motherboard", "MB"), comp("Case", "C"), comp("PSU", "P")
        comps = [mb, case, psu]
        b = Build(name="t1712-full", component_ids=[c.id for c in comps])
        r = analyze_build_compatibility(b, comps, [
            TechnicalProfile(component_id=mb.id, attributes=[va("form_factor", "E-ATX")]),
            TechnicalProfile(component_id=case.id, attributes=[
                va("supported_motherboard_form_factors", ["ATX"]),
                va("supported_psu_form_factors", ["ATX"]),
            ]),
            TechnicalProfile(component_id=psu.id, attributes=[va("psu_form_factor", "ATX")]),
        ])
        self.assertEqual(r.overall_result, RESULT_INCOMPATIBLE)
        self.assertTrue(any(f.result == RESULT_INCOMPATIBLE and f.severity == SEVERITY_CRITICAL
                            for f in r.findings if f.rule_id == "mb_case.form_factor"))

    def test_no_false_positive_from_unresolvable(self):
        r = self._full_build("SFX", ["Other"])
        self.assertFalse(any(f.result == RESULT_INCOMPATIBLE for f in r.findings
                             if f.rule_id == "psu_case.form_factor"))
        self.assertNotEqual(r.overall_result, RESULT_INCOMPATIBLE)

    def test_gpu_and_cooling_relations_untouched(self):
        gpu, case = comp("GPU", "G"), comp("Case", "C")
        b = Build(name="t1712-g", component_ids=[gpu.id, case.id])
        r = analyze_build_compatibility(b, [gpu, case], [
            TechnicalProfile(component_id=gpu.id, attributes=[va("card_length_mm", 300)]),
            TechnicalProfile(component_id=case.id, attributes=[va("max_gpu_length_mm", 350)]),
        ])
        self.assertEqual(find(r, "gpu_case.max_length")[0].result, RESULT_COMPATIBLE)
        self.assertEqual(find(r, "psu_case.form_factor"), [])


class TestPsuCasePresentation(unittest.TestCase):
    def _tk(self):
        import tkinter as tk
        try:
            root = tk.Tk()
            root.withdraw()
        except tk.TclError as exc:
            self.skipTest(f"Tk unavailable: {exc}")
        return root

    def test_proprietary_renders_without_placeholders(self):
        from pc_parts_organizer.localization import Translator
        from pc_parts_organizer.ui.build_detail_view import BuildDetailView
        from pc_parts_organizer.ui.theme import configure_theme
        psu, case = comp("PSU"), comp("Case")
        b = Build(name="t1712", component_ids=[psu.id, case.id])
        rep = analyze_build_compatibility(b, [psu, case], [
            TechnicalProfile(component_id=psu.id, attributes=[va("psu_form_factor", "Proprietary")]),
            TechnicalProfile(component_id=case.id, attributes=[va("supported_psu_form_factors", ["ATX"])]),
        ])
        root = self._tk()
        try:
            configure_theme(root)
            for lang in ("es", "en"):
                tr = Translator()
                tr.set_language(lang)
                v = BuildDetailView(root, tr)
                v.set_build(b, {psu.id: psu, case.id: case})
                v.set_compatibility_report(rep)
                text = v._compat_text.get("1.0", "end")
                self.assertNotIn("{apparent_conflict}", text)
                self.assertNotIn("{apparent_match}", text)
                self.assertNotIn("{reason}", text)
                self.assertIn("Proprietary", text)
                v.destroy()
        finally:
            root.destroy()

    def test_sfx_finding_renders_without_placeholders(self):
        from pc_parts_organizer.localization import Translator
        from pc_parts_organizer.ui.build_detail_view import BuildDetailView
        from pc_parts_organizer.ui.theme import configure_theme
        psu, case = comp("PSU"), comp("Case")
        b = Build(name="t1712", component_ids=[psu.id, case.id])
        rep = analyze_build_compatibility(b, [psu, case], [
            TechnicalProfile(component_id=psu.id, attributes=[va("psu_form_factor", "SFX")]),
            TechnicalProfile(component_id=case.id, attributes=[va("supported_psu_form_factors", ["SFX-L"])]),
        ])
        root = self._tk()
        try:
            configure_theme(root)
            for lang in ("es", "en"):
                tr = Translator()
                tr.set_language(lang)
                v = BuildDetailView(root, tr)
                v.set_build(b, {psu.id: psu, case.id: case})
                v.set_compatibility_report(rep)
                text = v._compat_text.get("1.0", "end")
                self.assertIn("SFX", text)
                self.assertIn("SFX-L", text)
                self.assertNotIn("{apparent_conflict}", text)
                self.assertNotIn("{reason}", text)
                self.assertNotIn("{form_factor}", text)
                v.destroy()
        finally:
            root.destroy()

    def test_editor_psu_and_case_rows(self):
        import uuid
        import tkinter as tk
        from pc_parts_organizer.localization import Translator
        from pc_parts_organizer.ui.theme import configure_theme
        from pc_parts_organizer.ui.technical_profile_form import TechnicalProfileForm
        root = self._tk()
        try:
            configure_theme(root)
            tr = Translator()
            cid = str(uuid.uuid4())
            f = TechnicalProfileForm(root, tr, component_id=cid, category="PSU", profile=None)
            self.assertIn("psu_form_factor", f._rows)
            vals = f._rows["psu_form_factor"]["value"][3]
            self.assertIn("SFX-L", vals)
            f._rows["psu_form_factor"]["enabled"].set(True)
            f._rows["psu_form_factor"]["value"][1].set("SFX-L")
            for k, r_ in f._rows.items():
                if k != "psu_form_factor":
                    r_["enabled"].set(False)
            f._on_save()
            self.assertEqual(f.result.attributes[0].value, "SFX-L")
            cid2 = str(uuid.uuid4())
            g = TechnicalProfileForm(root, tr, component_id=cid2, category="Case", profile=None)
            self.assertIn("supported_psu_form_factors", g._rows)
            lb = g._rows["supported_psu_form_factors"]["value"][1]
            idx = [i for i, v in enumerate(lb.get(0, "end")) if v in ("ATX", "SFX-L")]
            for i in idx:
                lb.selection_set(i)
            g._rows["supported_psu_form_factors"]["enabled"].set(True)
            for k, r_ in g._rows.items():
                if k != "supported_psu_form_factors":
                    r_["enabled"].set(False)
            g._on_save()
            self.assertEqual(sorted(g.result.attributes[0].value), ["ATX", "SFX-L"])
        finally:
            root.destroy()


if __name__ == "__main__":
    unittest.main()
