"""T17.11 CPU/Motherboard socket visibility: descriptive only, never decisive."""
from __future__ import annotations

try:
    import tests._pcpo_test_isolation_bootstrap  # noqa: F401
except Exception:
    import _pcpo_test_isolation_bootstrap  # type: ignore  # noqa: F401

import copy
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
from pc_parts_organizer.compatibility.engine import IMPLEMENTED_RELATIONS
from pc_parts_organizer.models import Build, Component
from pc_parts_organizer.technical_profiles import (
    PROFILE_REGISTRY_VERSION,
    PROFILE_VERSION,
    TechnicalAttribute,
    TechnicalProfile,
    TechnicalProfileValidationError,
    allowed_keys_for_category,
    validate_profile_for_category,
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


def sock(v, verified=True):
    return va("socket_designation", v) if verified else ua("socket_designation", v)


def find(rep, rule):
    return [f for f in rep.findings if f.rule_id == rule]


def analyze(comps, profs):
    b = Build(name="t1711", component_ids=[c.id for c in comps])
    return analyze_build_compatibility(b, comps, profs)


class TestModelRegistry(unittest.TestCase):
    def test_motherboard_socket_registered(self):
        self.assertIn("socket_designation", allowed_keys_for_category("Motherboard"))
        self.assertIn("socket_designation", allowed_keys_for_category("CPU"))

    def test_socket_normalization_shared(self):
        a = va("socket_designation", "  am5 ")
        b = TechnicalAttribute(key="socket_designation", value="AM5")
        self.assertEqual(a.value, b.value)

    def test_socket_invalid_rejected(self):
        with self.assertRaises(TechnicalProfileValidationError):
            TechnicalAttribute(key="socket_designation", value="   ")
        with self.assertRaises(TechnicalProfileValidationError):
            TechnicalAttribute(key="socket_designation", value="")

    def test_socket_round_trip(self):
        p = TechnicalProfile(component_id=comp("Motherboard").id,
                             attributes=[va("socket_designation", "AM5")])
        d = p.to_dict()
        self.assertEqual(d["attributes"][0]["value"], "AM5")
        c = p.copy()
        self.assertEqual(c.attributes[0].value, "AM5")

    def test_socket_not_completeness_eligible(self):
        with self.assertRaises(TechnicalProfileValidationError):
            va("socket_designation", "AM5", collection_completeness="complete",
               completeness_scope="All sockets")
        with self.assertRaises(TechnicalProfileValidationError):
            va("socket_designation", "AM5", collection_completeness="partial",
               completeness_scope="Some sockets")

    def test_v1_profile_without_socket_still_valid(self):
        from pc_parts_organizer.technical_profiles import parse_profile_dict
        import uuid
        p = parse_profile_dict({"component_id": str(uuid.uuid4()), "profile_version": 1,
                                "attributes": [{"key": "form_factor", "value": "ATX"}]},
                               0, "Motherboard")
        self.assertEqual(p.profile_version, 1)
        validate_profile_for_category(p, "Motherboard")

    def test_versions(self):
        self.assertEqual(ENGINE_RULESET_VERSION, "t17.12-v1")
        self.assertEqual(PROFILE_VERSION, 2)
        self.assertGreaterEqual(PROFILE_REGISTRY_VERSION, 6)
        self.assertIn(("CPU", "Motherboard"), IMPLEMENTED_RELATIONS)


class TestSocketVisibility(unittest.TestCase):
    def _pair(self, cpu_sock, mb_sock):
        cpu, mb = comp("CPU"), comp("Motherboard")
        return analyze([cpu, mb], [
            TechnicalProfile(component_id=cpu.id, attributes=[cpu_sock]),
            TechnicalProfile(component_id=mb.id, attributes=[mb_sock]),
        ]), cpu, mb

    def test_match_verified_requires_verification(self):
        r, cpu, mb = self._pair(sock("AM5"), sock("AM5"))
        f = find(r, "cpu_mb.socket_visibility")
        self.assertEqual(len(f), 1)
        self.assertEqual(f[0].result, RESULT_REQUIRES_VERIFICATION)
        self.assertEqual(f[0].message_params["reason"], "socket_match_pending_platform")
        self.assertTrue(f[0].message_params["match"])
        self.assertEqual(set(f[0].component_ids), {cpu.id, mb.id})
        self.assertEqual(r.rules_evaluated, 1)

    def test_mismatch_verified_requires_verification_not_incompatible(self):
        r, _, _ = self._pair(sock("AM5"), sock("LGA1700"))
        f = find(r, "cpu_mb.socket_visibility")
        self.assertEqual(f[0].result, RESULT_REQUIRES_VERIFICATION)
        self.assertEqual(f[0].message_params["reason"], "socket_mismatch_unresolved")
        self.assertFalse(f[0].message_params["match"])
        self.assertNotEqual(r.overall_result, RESULT_INCOMPATIBLE)
        self.assertFalse(any(x.result == RESULT_INCOMPATIBLE for x in r.findings))

    def test_cpu_socket_missing(self):
        cpu, mb = comp("CPU"), comp("Motherboard")
        r = analyze([cpu, mb], [TechnicalProfile(component_id=mb.id, attributes=[sock("AM5")])])
        f = find(r, "cpu_mb.socket_visibility")
        self.assertEqual(f[0].result, RESULT_INSUFFICIENT_DATA)
        self.assertTrue(any("cpu[" in m for m in f[0].missing_information))
        self.assertEqual(r.rules_evaluated, 0)

    def test_mb_socket_missing(self):
        cpu, mb = comp("CPU"), comp("Motherboard")
        r = analyze([cpu, mb], [TechnicalProfile(component_id=cpu.id, attributes=[sock("AM5")])])
        f = find(r, "cpu_mb.socket_visibility")
        self.assertEqual(f[0].result, RESULT_INSUFFICIENT_DATA)
        self.assertTrue(any("motherboard[" in m for m in f[0].missing_information))

    def test_cpu_unverified(self):
        r, _, _ = self._pair(ua("socket_designation", "AM5"), sock("AM5"))
        f = find(r, "cpu_mb.socket_visibility")
        self.assertEqual(f[0].result, RESULT_REQUIRES_VERIFICATION)
        self.assertEqual(f[0].message_params["reason"], "socket_not_verified")

    def test_mb_low_confidence(self):
        cpu, mb = comp("CPU"), comp("Motherboard")
        low = TechnicalAttribute(key="socket_designation", value="AM5", source="official_vendor_doc",
                                 confidence="low", verification_status="verified",
                                 evidence_ref="https://vendor/doc", verified_at="2026-01-01")
        r = analyze([cpu, mb], [TechnicalProfile(component_id=cpu.id, attributes=[sock("AM5")]),
                                TechnicalProfile(component_id=mb.id, attributes=[low])])
        f = find(r, "cpu_mb.socket_visibility")
        self.assertEqual(f[0].result, RESULT_REQUIRES_VERIFICATION)
        self.assertEqual(f[0].message_params["reason"], "socket_low_confidence")

    def test_other_unresolvable(self):
        for other in ("Other", "Proprietary", "other"):
            with self.subTest(other=other):
                r, _, _ = self._pair(sock(other), sock("AM5"))
                f = find(r, "cpu_mb.socket_visibility")
                self.assertEqual(f[0].result, RESULT_REQUIRES_VERIFICATION)
                self.assertEqual(f[0].message_params["reason"], "socket_not_resolvable")

    def test_no_alias_equivalence(self):
        for a, b in (("LGA1700", "LGA 1700"), ("AM5", "AM4"), ("LGA1700", "LGA-1700"), ("AM5", "am5 ")):
            with self.subTest(a=a, b=b):
                if a.strip().upper().replace(" ", "") == b.strip().upper().replace(" ", "") and a != b:
                    pass  # normalization keeps spacing differences
                r, _, _ = self._pair(sock(a), sock(b))
                f = find(r, "cpu_mb.socket_visibility")
                self.assertNotEqual(f[0].result, RESULT_COMPATIBLE)
                self.assertNotEqual(f[0].result, RESULT_INCOMPATIBLE)

    def test_multiple_cpus_no_arbitrary_pairing(self):
        c1, c2, mb = comp("CPU", "A"), comp("CPU", "B"), comp("Motherboard")
        r = analyze([c1, c2, mb], [
            TechnicalProfile(component_id=c1.id, attributes=[sock("AM5")]),
            TechnicalProfile(component_id=c2.id, attributes=[sock("LGA1700")]),
            TechnicalProfile(component_id=mb.id, attributes=[sock("AM5")]),
        ])
        self.assertEqual(find(r, "cpu_mb.socket_visibility"), [])

    def test_multiple_motherboards_no_arbitrary_pairing(self):
        cpu, m1, m2 = comp("CPU"), comp("Motherboard", "A"), comp("Motherboard", "B")
        r = analyze([cpu, m1, m2], [
            TechnicalProfile(component_id=cpu.id, attributes=[sock("AM5")]),
            TechnicalProfile(component_id=m1.id, attributes=[sock("AM5")]),
            TechnicalProfile(component_id=m2.id, attributes=[sock("LGA1700")]),
        ])
        self.assertEqual(find(r, "cpu_mb.socket_visibility"), [])
        self.assertTrue(any(f.rule_id == "build.ambiguous_motherboard" for f in r.findings))

    def test_no_cpu_silent(self):
        mb = comp("Motherboard")
        r = analyze([mb], [TechnicalProfile(component_id=mb.id, attributes=[sock("AM5")])])
        self.assertEqual(find(r, "cpu_mb.socket_visibility"), [])

    def test_no_mb_silent(self):
        cpu = comp("CPU")
        r = analyze([cpu], [TechnicalProfile(component_id=cpu.id, attributes=[sock("AM5")])])
        self.assertEqual(find(r, "cpu_mb.socket_visibility"), [])

    def test_attributes_compared_and_evidence(self):
        r, cpu, mb = self._pair(sock("AM5"), sock("LGA1700"))
        f = find(r, "cpu_mb.socket_visibility")[0]
        self.assertEqual(list(f.attributes_compared), ["socket_designation"])
        self.assertEqual(f.evidence["cpu_socket"], "AM5")
        self.assertEqual(f.evidence["motherboard_socket"], "LGA1700")

    def test_never_compatible_incompatible_or_critical(self):
        cases = [
            ([sock("AM5")], [sock("AM5")]),
            ([sock("AM5")], [sock("LGA1700")]),
            ([ua("socket_designation", "AM5")], [sock("AM5")]),
            ([sock("Other")], [sock("AM5")]),
        ]
        for i, (cattrs, mattrs) in enumerate(cases):
            with self.subTest(i=i):
                cpu, mb = comp("CPU"), comp("Motherboard")
                r = analyze([cpu, mb], [TechnicalProfile(component_id=cpu.id, attributes=cattrs),
                                        TechnicalProfile(component_id=mb.id, attributes=mattrs)])
                for f in find(r, "cpu_mb.socket_visibility"):
                    self.assertNotEqual(f.result, RESULT_COMPATIBLE)
                    self.assertNotEqual(f.result, RESULT_INCOMPATIBLE)
                    self.assertNotEqual(f.severity, SEVERITY_CRITICAL)

    def test_not_evaluated_present_when_compared(self):
        r, _, _ = self._pair(sock("AM5"), sock("AM5"))
        reasons = [n["reason"] for n in r.not_evaluated_relations if n["category"] == "Motherboard"]
        self.assertIn("chipset_platform_not_evaluated", reasons)
        self.assertIn("firmware_bios_not_evaluated", reasons)
        self.assertIn("power_delivery_not_evaluated", reasons)
        self.assertIn("platform_chipset_not_evaluated", r.analysis_limitations)
        self.assertIn("firmware_bios_not_evaluated", r.analysis_limitations)
        self.assertIn("power_delivery_not_evaluated", r.analysis_limitations)

    def test_no_ne_when_socket_missing(self):
        cpu, mb = comp("CPU"), comp("Motherboard")
        r = analyze([cpu, mb], [TechnicalProfile(component_id=mb.id, attributes=[sock("AM5")])])
        reasons = [n["reason"] for n in r.not_evaluated_relations if n["category"] == "Motherboard"]
        self.assertNotIn("chipset_platform_not_evaluated", reasons)

    def test_independent_incompatible_preserved(self):
        cpu, mb, case = comp("CPU"), comp("Motherboard"), comp("Case")
        r = analyze([cpu, mb, case], [
            TechnicalProfile(component_id=cpu.id, attributes=[sock("AM5")]),
            TechnicalProfile(component_id=mb.id, attributes=[
                va("socket_designation", "AM5"),
                va("form_factor", "ATX")]),
            TechnicalProfile(component_id=case.id, attributes=[
                va("supported_motherboard_form_factors", ["Micro-ATX"])]),
        ])
        self.assertEqual(r.overall_result, RESULT_INCOMPATIBLE)
        f = find(r, "cpu_mb.socket_visibility")
        self.assertEqual(f[0].result, RESULT_REQUIRES_VERIFICATION)

    def test_match_does_not_force_compatible(self):
        cpu, mb = comp("CPU"), comp("Motherboard")
        r = analyze([cpu, mb], [TechnicalProfile(component_id=cpu.id, attributes=[sock("AM5")]),
                                TechnicalProfile(component_id=mb.id, attributes=[sock("AM5")])])
        self.assertNotEqual(r.overall_result, RESULT_COMPATIBLE)

    def test_purity_determinism(self):
        cpu, mb = comp("CPU"), comp("Motherboard")
        comps = [cpu, mb]
        profs = [TechnicalProfile(component_id=cpu.id, attributes=[sock("AM5")]),
                 TechnicalProfile(component_id=mb.id, attributes=[sock("AM5")])]
        b = Build(name="t1711", component_ids=[c.id for c in comps])
        before = [p.to_dict() for p in profs]
        r1 = analyze_build_compatibility(b, comps, profs)
        r2 = analyze_build_compatibility(b, comps, profs)
        self.assertEqual([p.to_dict() for p in profs], before)
        self.assertEqual([(f.rule_id, f.result) for f in r1.findings],
                         [(f.rule_id, f.result) for f in r2.findings])

    def test_service_integration(self):
        from pc_parts_organizer.service import InventoryService
        from pc_parts_organizer.storage import load_project_state
        svc = InventoryService()
        cpu = svc.add_component("CPU", "M", "CPU T", "", "")
        mb = svc.add_component("Motherboard", "M", "MB T", "", "")
        svc.set_technical_profile(TechnicalProfile(component_id=cpu.id, attributes=[sock("AM5")]))
        svc.set_technical_profile(TechnicalProfile(component_id=mb.id, attributes=[sock("AM5")]))
        b = svc.add_build("T1711 service")
        svc.add_component_to_build(b.id, cpu.id)
        svc.add_component_to_build(b.id, mb.id)
        before = load_project_state()
        rep = svc.analyze_build_compatibility(b.id)
        after = load_project_state()
        self.assertEqual(find(rep, "cpu_mb.socket_visibility")[0].result, RESULT_REQUIRES_VERIFICATION)
        self.assertEqual(len(before.components), len(after.components))
        self.assertEqual(len(before.builds), len(after.builds))
        self.assertEqual(len(before.technical_profiles), len(after.technical_profiles))

    def test_locales_resolve(self):
        from pc_parts_organizer.localization import Translator
        for lang in ("es", "en"):
            tr = Translator()
            tr.set_language(lang)
            self.assertNotIn("cpu_mb", tr.t("compatibility.rule_labels.cpu_mb__socket_visibility"))
            for reason in ("socket_match_pending_platform", "socket_mismatch_unresolved",
                           "socket_not_verified", "socket_low_confidence", "socket_not_resolvable"):
                self.assertNotIn("compatibility.reasons", tr.t(f"compatibility.reasons.{reason}"))


if __name__ == "__main__":
    unittest.main()
