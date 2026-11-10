"""Tests for compatibility rules RAM<->MB and MB<->Case (T17.3)."""

from __future__ import annotations

try:
    import tests._pcpo_test_isolation_bootstrap  # noqa: F401
except Exception:
    import _pcpo_test_isolation_bootstrap  # type: ignore  # noqa: F401

import unittest
import uuid

from pc_parts_organizer.compatibility import (
    RESULT_COMPATIBLE,
    RESULT_INCOMPATIBLE,
    RESULT_INSUFFICIENT_DATA,
    RESULT_REQUIRES_VERIFICATION,
    SEVERITY_CRITICAL,
    analyze_build_compatibility,
)
from pc_parts_organizer.models import Build, Component
from pc_parts_organizer.technical_profiles import TechnicalAttribute, TechnicalProfile


def cid():
    return str(uuid.uuid4())


def comp(category: str, component_id: str | None = None) -> Component:
    return Component(category=category, manufacturer="Mfg", model="Model", id=component_id or cid())


def attr(key, value, *, verified=False, confidence="high" if False else "medium", source="user_input", unit=None, low=False):
    # verified requires evidence_ref + verified_at
    if verified:
        return TechnicalAttribute(
            key=key,
            value=value,
            unit=unit,
            source=source if source != "user_input" else "official_vendor_doc",
            confidence="high",
            verification_status="verified",
            evidence_ref="https://example.invalid/doc",
            verified_at="2026-01-01",
        )
    if low:
        return TechnicalAttribute(key=key, value=value, unit=unit, source=source, confidence="low", verification_status="unverified")
    return TechnicalAttribute(key=key, value=value, unit=unit, source=source, confidence=confidence, verification_status="unverified")


def profile(component_id: str, attrs) -> TechnicalProfile:
    return TechnicalProfile(component_id=component_id, attributes=list(attrs))


def findings_by_rule(report, rule_id: str):
    return [f for f in report.findings if f.rule_id == rule_id]


class TestRamMotherboardRules(unittest.TestCase):
    def _mk(self, ram_attrs, mb_attrs, *, extra_rams=None):
        ram = comp("RAM")
        mb = comp("Motherboard")
        rams = [ram] + list(extra_rams or [])
        b = Build(name="b", component_ids=[c.id for c in rams] + [mb.id])
        profiles = [profile(ram.id, ram_attrs), profile(mb.id, mb_attrs)]
        return b, rams + [mb], profiles, ram, mb

    def test_generation_verified_match(self):
        b, comps, profs, ram, mb = self._mk(
            [attr("memory_generation", "DDR5", verified=True)],
            [attr("supported_memory_generations", ["DDR5"], verified=True)],
        )
        # need full RAM attrs? generation rule alone - others missing => requires_verification/insufficient; test specific rule
        report = analyze_build_compatibility(b, comps, profs)
        fs = findings_by_rule(report, "ram_mb.memory_generation")
        self.assertEqual(len(fs), 1)
        self.assertEqual(fs[0].result, RESULT_COMPATIBLE)
        self.assertEqual(tuple(fs[0].component_ids), (ram.id, mb.id))

    def test_generation_verified_contradiction(self):
        b, comps, profs, ram, mb = self._mk(
            [attr("memory_generation", "DDR4", verified=True)],
            [attr("supported_memory_generations", ["DDR5"], verified=True)],
        )
        report = analyze_build_compatibility(b, comps, profs)
        fs = findings_by_rule(report, "ram_mb.memory_generation")
        self.assertEqual(fs[0].result, RESULT_INCOMPATIBLE)
        self.assertEqual(fs[0].severity, SEVERITY_CRITICAL)
        self.assertEqual(report.overall_result, RESULT_INCOMPATIBLE)

    def test_generation_unverified_contradiction_requires_verification(self):
        b, comps, profs, *_ = self._mk(
            [attr("memory_generation", "DDR4")],
            [attr("supported_memory_generations", ["DDR5"], verified=True)],
        )
        report = analyze_build_compatibility(b, comps, profs)
        fs = findings_by_rule(report, "ram_mb.memory_generation")
        self.assertEqual(fs[0].result, RESULT_REQUIRES_VERIFICATION)

    def test_generation_missing(self):
        b, comps, profs, *_ = self._mk([], [attr("supported_memory_generations", ["DDR5"], verified=True)])
        report = analyze_build_compatibility(b, comps, profs)
        fs = findings_by_rule(report, "ram_mb.memory_generation")
        self.assertEqual(fs[0].result, RESULT_INSUFFICIENT_DATA)
        self.assertIn("ram.memory_generation", tuple(fs[0].missing_information))

    def test_form_factor_verified_contradiction(self):
        b, comps, profs, *_ = self._mk(
            [attr("module_form_factor", "SO-DIMM", verified=True)],
            [attr("supported_memory_module_form_factors", ["DIMM"], verified=True)],
        )
        report = analyze_build_compatibility(b, comps, profs)
        fs = findings_by_rule(report, "ram_mb.module_form_factor")
        self.assertEqual(fs[0].result, RESULT_INCOMPATIBLE)

    def test_form_factor_unverified_match_not_confirmed(self):
        b, comps, profs, *_ = self._mk(
            [attr("module_form_factor", "DIMM")],
            [attr("supported_memory_module_form_factors", ["DIMM"], verified=True)],
        )
        report = analyze_build_compatibility(b, comps, profs)
        fs = findings_by_rule(report, "ram_mb.module_form_factor")
        self.assertEqual(fs[0].result, RESULT_REQUIRES_VERIFICATION)

    def test_capacity_exact_limit_verified(self):
        b, comps, profs, *_ = self._mk(
            [attr("total_capacity_gb", 128, unit="GB", verified=True), attr("module_count", 4, verified=True)],
            [attr("max_memory_capacity_gb", 128, unit="GB", verified=True), attr("memory_slot_count", 4, verified=True)],
        )
        report = analyze_build_compatibility(b, comps, profs)
        cap = findings_by_rule(report, "ram_mb.max_capacity")[0]
        self.assertEqual(cap.result, RESULT_COMPATIBLE)
        slots = findings_by_rule(report, "ram_mb.module_slots")[0]
        self.assertEqual(slots.result, RESULT_COMPATIBLE)

    def test_capacity_exceeds_verified_incompatible(self):
        b, comps, profs, *_ = self._mk(
            [attr("total_capacity_gb", 192, unit="GB", verified=True)],
            [attr("max_memory_capacity_gb", 128, unit="GB", verified=True)],
        )
        report = analyze_build_compatibility(b, comps, profs)
        cap = findings_by_rule(report, "ram_mb.max_capacity")[0]
        self.assertEqual(cap.result, RESULT_INCOMPATIBLE)

    def test_capacity_exceeds_unverified_requires(self):
        b, comps, profs, *_ = self._mk(
            [attr("total_capacity_gb", 192, unit="GB")],
            [attr("max_memory_capacity_gb", 128, unit="GB", verified=True)],
        )
        report = analyze_build_compatibility(b, comps, profs)
        cap = findings_by_rule(report, "ram_mb.max_capacity")[0]
        self.assertEqual(cap.result, RESULT_REQUIRES_VERIFICATION)

    def test_multi_ram_aggregation_all_complete(self):
        ram1 = comp("RAM")
        ram2 = comp("RAM")
        mb = comp("Motherboard")
        b = Build(name="b", component_ids=[ram1.id, ram2.id, mb.id])
        profiles = [
            profile(ram1.id, [attr("total_capacity_gb", 16, unit="GB", verified=True), attr("module_count", 2, verified=True)]),
            profile(ram2.id, [attr("total_capacity_gb", 32, unit="GB", verified=True), attr("module_count", 2, verified=True)]),
            profile(mb.id, [attr("max_memory_capacity_gb", 64, unit="GB", verified=True), attr("memory_slot_count", 4, verified=True)]),
        ]
        report = analyze_build_compatibility(b, [ram1, ram2, mb], profiles)
        cap = findings_by_rule(report, "ram_mb.max_capacity")[0]
        self.assertEqual(cap.result, RESULT_COMPATIBLE)  # 16+32=48 <= 64
        self.assertEqual(cap.message_params["total_capacity_gb"], 48)
        self.assertCountEqual(cap.component_ids, (ram1.id, ram2.id, mb.id))
        slots = findings_by_rule(report, "ram_mb.module_slots")[0]
        self.assertEqual(slots.result, RESULT_COMPATIBLE)  # 2+2=4 <= 4
        self.assertEqual(slots.message_params["total_module_count"], 4)
        self.assertCountEqual(slots.component_ids, (ram1.id, ram2.id, mb.id))

    def test_multi_ram_any_missing_blocks_aggregated_capacity(self):
        ram1 = comp("RAM")
        ram2 = comp("RAM")
        mb = comp("Motherboard")
        b = Build(name="b", component_ids=[ram1.id, ram2.id, mb.id])
        profiles = [
            profile(ram1.id, [attr("total_capacity_gb", 16, unit="GB", verified=True)]),
            profile(ram2.id, []),  # missing
            profile(mb.id, [attr("max_memory_capacity_gb", 128, unit="GB", verified=True)]),
        ]
        report = analyze_build_compatibility(b, [ram1, ram2, mb], profiles)
        cap = findings_by_rule(report, "ram_mb.max_capacity")[0]
        self.assertEqual(cap.result, RESULT_INSUFFICIENT_DATA)
        self.assertIn(ram2.id, cap.message_params["missing_ram_components"])

    def test_multi_ram_any_missing_blocks_aggregated_modules(self):
        ram1 = comp("RAM")
        ram2 = comp("RAM")
        mb = comp("Motherboard")
        b = Build(name="b", component_ids=[ram1.id, ram2.id, mb.id])
        profiles = [
            profile(ram1.id, [attr("module_count", 2, verified=True)]),
            profile(ram2.id, [attr("total_capacity_gb", 16, unit="GB", verified=True)]),  # has cap but missing module_count
            profile(mb.id, [attr("memory_slot_count", 4, verified=True)]),
        ]
        report = analyze_build_compatibility(b, [ram1, ram2, mb], profiles)
        slots = findings_by_rule(report, "ram_mb.module_slots")[0]
        self.assertEqual(slots.result, RESULT_INSUFFICIENT_DATA)
        self.assertIn(ram2.id, slots.message_params["missing_ram_components"])

    def test_low_confidence_not_confirmed(self):
        b, comps, profs, *_ = self._mk(
            [attr("memory_generation", "DDR5", low=True)],
            [attr("supported_memory_generations", ["DDR5"], verified=True)],
        )
        report = analyze_build_compatibility(b, comps, profs)
        fs = findings_by_rule(report, "ram_mb.memory_generation")
        self.assertEqual(fs[0].result, RESULT_REQUIRES_VERIFICATION)


class TestMotherboardCaseRules(unittest.TestCase):
    def _mk(self, mb_attrs, case_attrs, *, extra_mb=None, extra_case=None):
        mb = comp("Motherboard")
        case = comp("Case")
        mbs = [mb] + ([extra_mb] if extra_mb else [])
        cases = [case] + ([extra_case] if extra_case else [])
        b = Build(name="b", component_ids=[c.id for c in mbs + cases])
        profiles = [profile(mb.id, mb_attrs), profile(case.id, case_attrs)]
        return b, mbs + cases, profiles, mb, case

    def test_form_factor_verified_admitted(self):
        b, comps, profs, *_ = self._mk(
            [attr("form_factor", "ATX", verified=True)],
            [attr("supported_motherboard_form_factors", ["ATX", "Micro-ATX"], verified=True)],
        )
        report = analyze_build_compatibility(b, comps, profs)
        fs = findings_by_rule(report, "mb_case.form_factor")
        self.assertEqual(fs[0].result, RESULT_COMPATIBLE)

    def test_form_factor_verified_not_admitted(self):
        b, comps, profs, *_ = self._mk(
            [attr("form_factor", "E-ATX", verified=True)],
            [attr("supported_motherboard_form_factors", ["ATX"], verified=True)],
        )
        report = analyze_build_compatibility(b, comps, profs)
        fs = findings_by_rule(report, "mb_case.form_factor")
        self.assertEqual(fs[0].result, RESULT_INCOMPATIBLE)

    def test_form_factor_unverified_contradiction(self):
        b, comps, profs, *_ = self._mk(
            [attr("form_factor", "E-ATX")],
            [attr("supported_motherboard_form_factors", ["ATX"], verified=True)],
        )
        report = analyze_build_compatibility(b, comps, profs)
        fs = findings_by_rule(report, "mb_case.form_factor")
        self.assertEqual(fs[0].result, RESULT_REQUIRES_VERIFICATION)

    def test_form_factor_missing(self):
        b, comps, profs, *_ = self._mk([], [attr("supported_motherboard_form_factors", ["ATX"], verified=True)])
        report = analyze_build_compatibility(b, comps, profs)
        fs = findings_by_rule(report, "mb_case.form_factor")
        self.assertEqual(fs[0].result, RESULT_INSUFFICIENT_DATA)

    def test_other_never_confirmed(self):
        b, comps, profs, *_ = self._mk(
            [attr("form_factor", "Other", verified=True)],
            [attr("supported_motherboard_form_factors", ["ATX", "Other"], verified=True)],
        )
        report = analyze_build_compatibility(b, comps, profs)
        fs = findings_by_rule(report, "mb_case.form_factor")
        self.assertEqual(fs[0].result, RESULT_REQUIRES_VERIFICATION)
        self.assertNotEqual(fs[0].result, RESULT_COMPATIBLE)

    def test_proprietary_requires_verification(self):
        b, comps, profs, *_ = self._mk(
            [attr("form_factor", "Proprietary", verified=True)],
            [attr("supported_motherboard_form_factors", ["Proprietary"], verified=True)],
        )
        report = analyze_build_compatibility(b, comps, profs)
        fs = findings_by_rule(report, "mb_case.form_factor")
        self.assertEqual(fs[0].result, RESULT_REQUIRES_VERIFICATION)

    def test_multi_case_ambiguity(self):
        mb = comp("Motherboard")
        c1 = comp("Case")
        c2 = comp("Case")
        b = Build(name="b", component_ids=[mb.id, c1.id, c2.id])
        profiles = [
            profile(mb.id, [attr("form_factor", "ATX", verified=True)]),
            profile(c1.id, [attr("supported_motherboard_form_factors", ["ATX"], verified=True)]),
            profile(c2.id, [attr("supported_motherboard_form_factors", ["ATX"], verified=True)]),
        ]
        report = analyze_build_compatibility(b, [mb, c1, c2], profiles)
        amb = findings_by_rule(report, "build.ambiguous_case")
        self.assertTrue(amb)
        self.assertEqual(amb[0].result, RESULT_INSUFFICIENT_DATA)
        self.assertFalse(findings_by_rule(report, "mb_case.form_factor"))

    def test_multi_motherboard_ambiguity(self):
        m1 = comp("Motherboard")
        m2 = comp("Motherboard")
        case = comp("Case")
        b = Build(name="b", component_ids=[m1.id, m2.id, case.id])
        report = analyze_build_compatibility(b, [m1, m2, case], [])
        amb = findings_by_rule(report, "build.ambiguous_motherboard")
        self.assertTrue(amb)
        self.assertFalse(findings_by_rule(report, "mb_case.form_factor"))


if __name__ == "__main__":
    unittest.main()
