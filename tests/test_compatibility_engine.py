"""Tests for compatibility engine global behavior, purity, determinism (T17.3)."""

from __future__ import annotations

try:
    import tests._pcpo_test_isolation_bootstrap  # noqa: F401
except Exception:
    import _pcpo_test_isolation_bootstrap  # type: ignore  # noqa: F401

import copy
import unittest
import uuid

from pc_parts_organizer.compatibility import (
    RESULT_COMPATIBLE,
    RESULT_INCOMPATIBLE,
    RESULT_INSUFFICIENT_DATA,
    RESULT_REQUIRES_VERIFICATION,
    CompatibilityValidationError,
    analyze_build_compatibility,
)
from pc_parts_organizer.models import Build, Component
from pc_parts_organizer.technical_profiles import TechnicalAttribute, TechnicalProfile


def cid():
    return str(uuid.uuid4())


def comp(category: str, component_id: str | None = None) -> Component:
    return Component(category=category, manufacturer="Mfg", model="Model", id=component_id or cid())


def vattr(key, value, unit=None):
    return TechnicalAttribute(key=key, value=value, unit=unit, source="official_vendor_doc", confidence="high",
                              verification_status="verified", evidence_ref="https://e", verified_at="2026-01-01")


def uattr(key, value, unit=None):
    return TechnicalAttribute(key=key, value=value, unit=unit)


class TestCompatibilityEngine(unittest.TestCase):
    def test_empty_build_insufficient_data(self):
        b = Build(name="empty")
        r = analyze_build_compatibility(b, [], [])
        self.assertEqual(r.overall_result, RESULT_INSUFFICIENT_DATA)
        self.assertEqual(r.build_id, b.id)
        self.assertFalse(r.rules_evaluated)

    def test_build_incomplete_no_false_compatible(self):
        ram = comp("RAM")
        b = Build(name="b", component_ids=[ram.id])
        r = analyze_build_compatibility(b, [ram], [])
        self.assertNotEqual(r.overall_result, RESULT_COMPATIBLE)

    def test_out_of_scope_present_blocks_global_compatible(self):
        # fully verified compatible RAM+MB+Case, but CPU present => not globally compatible
        ram = comp("RAM"); mb = comp("Motherboard"); case = comp("Case"); cpu = comp("CPU")
        b = Build(name="b", component_ids=[ram.id, mb.id, case.id, cpu.id])
        profiles = [
            TechnicalProfile(component_id=ram.id, attributes=[
                vattr("memory_generation", "DDR5"), vattr("module_form_factor", "DIMM"),
                vattr("total_capacity_gb", 32, "GB"), vattr("module_count", 2),
            ]),
            TechnicalProfile(component_id=mb.id, attributes=[
                vattr("supported_memory_generations", ["DDR5"]), vattr("supported_memory_module_form_factors", ["DIMM"]),
                vattr("max_memory_capacity_gb", 128, "GB"), vattr("memory_slot_count", 4),
                vattr("form_factor", "ATX"),
            ]),
            TechnicalProfile(component_id=case.id, attributes=[
                vattr("supported_motherboard_form_factors", ["ATX", "Micro-ATX"]),
            ]),
        ]
        r = analyze_build_compatibility(b, [ram, mb, case, cpu], profiles)
        self.assertEqual(r.overall_result, RESULT_REQUIRES_VERIFICATION)
        self.assertTrue(r.not_evaluated_relations)
        self.assertTrue(any(x.get("category") == "CPU" for x in r.not_evaluated_relations))
        self.assertGreater(r.rules_evaluated, 0)
        # in-scope rules should be compatible
        self.assertTrue(all(f.result == RESULT_COMPATIBLE for f in r.findings if f.rule_id.startswith(("ram_mb.", "mb_case."))))

    def test_critical_incompatibility_global(self):
        ram = comp("RAM"); mb = comp("Motherboard")
        b = Build(name="b", component_ids=[ram.id, mb.id])
        profiles = [
            TechnicalProfile(component_id=ram.id, attributes=[vattr("memory_generation", "DDR4")]),
            TechnicalProfile(component_id=mb.id, attributes=[vattr("supported_memory_generations", ["DDR5"])]),
        ]
        r = analyze_build_compatibility(b, [ram, mb], profiles)
        self.assertEqual(r.overall_result, RESULT_INCOMPATIBLE)

    def test_requires_verification_only(self):
        ram = comp("RAM"); mb = comp("Motherboard")
        b = Build(name="b", component_ids=[ram.id, mb.id])
        profiles = [
            TechnicalProfile(component_id=ram.id, attributes=[uattr("memory_generation", "DDR5")]),
            TechnicalProfile(component_id=mb.id, attributes=[vattr("supported_memory_generations", ["DDR5"])]),
        ]
        r = analyze_build_compatibility(b, [ram, mb], profiles)
        self.assertEqual(r.overall_result, RESULT_REQUIRES_VERIFICATION)

    def test_insufficient_data_when_no_applicable_scope(self):
        cpu = comp("CPU")
        b = Build(name="b", component_ids=[cpu.id])
        r = analyze_build_compatibility(b, [cpu], [])
        self.assertNotEqual(r.overall_result, RESULT_COMPATIBLE)
        self.assertIn(r.overall_result, (RESULT_INSUFFICIENT_DATA, RESULT_REQUIRES_VERIFICATION))

    def test_cpu_gpu_psu_present_no_false_compatible(self):
        cpu = comp("CPU"); gpu = comp("GPU"); psu = comp("PSU")
        b = Build(name="b", component_ids=[cpu.id, gpu.id, psu.id])
        r = analyze_build_compatibility(b, [cpu, gpu, psu], [])
        self.assertNotEqual(r.overall_result, RESULT_COMPATIBLE)
        cats = {x.get("category") for x in r.not_evaluated_relations}
        self.assertTrue({"CPU", "GPU", "PSU"}.issubset(cats))

    def test_no_storage_calls_and_no_mutation(self):
        ram = comp("RAM"); mb = comp("Motherboard")
        b = Build(name="b", component_ids=[ram.id, mb.id])
        profiles = [TechnicalProfile(component_id=ram.id, attributes=[uattr("memory_generation", "DDR5")])]
        components = [ram, mb]
        b_before = copy.deepcopy(b.__dict__)
        comps_before = [(c.id, c.category, c.manufacturer, c.model) for c in components]
        profs_before = [p.to_dict() for p in profiles]
        # monkeypatch storage module functions to fail if called? engine doesn't import storage.
        import pc_parts_organizer.storage as storage
        orig = (storage.save_project_state, storage.load_project_state)
        def boom(*a, **k): raise AssertionError("storage called")
        storage.save_project_state = boom  # type: ignore
        storage.load_project_state = boom  # type: ignore
        try:
            r = analyze_build_compatibility(b, components, profiles)
        finally:
            storage.save_project_state, storage.load_project_state = orig  # type: ignore
        self.assertIsNotNone(r)
        self.assertEqual(b.__dict__, b_before)
        self.assertEqual([(c.id, c.category, c.manufacturer, c.model) for c in components], comps_before)
        self.assertEqual([p.to_dict() for p in profiles], profs_before)

    def test_determinism_and_stable_order(self):
        ram = comp("RAM"); mb = comp("Motherboard"); case = comp("Case")
        b = Build(name="b", component_ids=[ram.id, mb.id, case.id])
        profiles = [
            TechnicalProfile(component_id=ram.id, attributes=[uattr("memory_generation", "DDR5"), uattr("module_form_factor", "DIMM"), uattr("total_capacity_gb", 32, "GB"), uattr("module_count", 2)]),
            TechnicalProfile(component_id=mb.id, attributes=[uattr("supported_memory_generations", ["DDR5"]), uattr("supported_memory_module_form_factors", ["DIMM"]), uattr("max_memory_capacity_gb", 128, "GB"), uattr("memory_slot_count", 4), uattr("form_factor", "ATX")]),
            TechnicalProfile(component_id=case.id, attributes=[uattr("supported_motherboard_form_factors", ["ATX"])]),
        ]
        r1 = analyze_build_compatibility(b, [ram, mb, case], profiles)
        r2 = analyze_build_compatibility(b, [ram, mb, case], profiles)
        k1 = [(f.rule_id, f.result, f.severity, f.component_ids, f.message_key) for f in r1.findings]
        k2 = [(f.rule_id, f.result, f.severity, f.component_ids, f.message_key) for f in r2.findings]
        self.assertEqual(k1, k2)
        self.assertEqual(r1.overall_result, r2.overall_result)
        self.assertEqual(r1.rules_evaluated, r2.rules_evaluated)
        self.assertEqual(sorted(k1), k1)

    def test_validation_rejects_unknown_component_reference(self):
        b = Build(name="b", component_ids=[str(uuid.uuid4())])
        with self.assertRaises(CompatibilityValidationError):
            analyze_build_compatibility(b, [], [])

    def test_validation_rejects_duplicate_profiles(self):
        ram = comp("RAM")
        b = Build(name="b", component_ids=[ram.id])
        p = TechnicalProfile(component_id=ram.id, attributes=[])
        with self.assertRaises(CompatibilityValidationError):
            analyze_build_compatibility(b, [ram], [p, p.copy()])

    def test_validation_rejects_profile_outside_input(self):
        ram = comp("RAM"); other = comp("RAM")
        b = Build(name="b", component_ids=[ram.id])
        p = TechnicalProfile(component_id=other.id, attributes=[])
        with self.assertRaises(CompatibilityValidationError):
            analyze_build_compatibility(b, [ram], [p])


if __name__ == "__main__":
    unittest.main()
