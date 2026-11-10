"""T17.5 compatibility rules: GPU↔Case, CPU↔Cooling, Cooling↔Case + regression."""

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


def cid(): return str(uuid.uuid4())
def comp(category, i=None): return Component(category=category, manufacturer="M", model="X", id=i or cid())
def vattr(key,value,unit=None):
    return TechnicalAttribute(key=key,value=value,unit=unit,source="official_vendor_doc",confidence="high",verification_status="verified",evidence_ref="https://e",verified_at="2026-01-01")
def uattr(key,value,unit=None): return TechnicalAttribute(key=key,value=value,unit=unit)
def lattr(key,value,unit=None): return TechnicalAttribute(key=key,value=value,unit=unit,confidence="low")
def fr(rule, report): return [f for f in report.findings if f.rule_id==rule]


class TestGPUCase(unittest.TestCase):
    def _run(self, gpu_attrs, case_attrs, extra_gpus=None, extra_cases=None):
        gpu=comp("GPU"); case=comp("Case")
        gpus=[gpu]+(extra_gpus or []); cases=[case]+(extra_cases or [])
        b=Build(name="b", component_ids=[c.id for c in gpus+cases])
        profs=[TechnicalProfile(component_id=gpu.id,attributes=list(gpu_attrs)), TechnicalProfile(component_id=case.id,attributes=list(case_attrs))]
        return analyze_build_compatibility(b,gpus+cases,profs), gpu, case

    def test_length_verified_compatible_with_partial_limitations(self):
        r,gpu,case=self._run([vattr("card_length_mm",300,"mm")],[vattr("max_gpu_length_mm",360,"mm")])
        f=fr("gpu_case.max_length",r)[0]
        self.assertEqual(f.result, RESULT_COMPATIBLE)
        self.assertEqual(f.component_ids, (gpu.id,case.id))
        self.assertEqual(r.overall_result, RESULT_REQUIRES_VERIFICATION)  # partial geometry not fully evaluated
        self.assertTrue(r.not_evaluated_relations)
        self.assertIn("gpu_geometry_not_fully_evaluated", r.analysis_limitations)

    def test_exact_limit(self):
        r,_,_=self._run([vattr("card_length_mm",360,"mm")],[vattr("max_gpu_length_mm",360,"mm")])
        self.assertEqual(fr("gpu_case.max_length",r)[0].result, RESULT_COMPATIBLE)

    def test_exceeds_verified_incompatible(self):
        r,_,_=self._run([vattr("card_length_mm",400,"mm")],[vattr("max_gpu_length_mm",360,"mm")])
        self.assertEqual(fr("gpu_case.max_length",r)[0].result, RESULT_INCOMPATIBLE)
        self.assertEqual(fr("gpu_case.max_length",r)[0].severity, SEVERITY_CRITICAL)
        self.assertEqual(r.overall_result, RESULT_INCOMPATIBLE)

    def test_exceeds_unverified_requires(self):
        r,_,_=self._run([uattr("card_length_mm",400,"mm")],[vattr("max_gpu_length_mm",360,"mm")])
        self.assertEqual(fr("gpu_case.max_length",r)[0].result, RESULT_REQUIRES_VERIFICATION)

    def test_missing_data(self):
        r,_,_=self._run([],[vattr("max_gpu_length_mm",360,"mm")])
        self.assertEqual(fr("gpu_case.max_length",r)[0].result, RESULT_INSUFFICIENT_DATA)

    def test_low_confidence_not_confirmed(self):
        r,_,_=self._run([lattr("card_length_mm",300,"mm")],[vattr("max_gpu_length_mm",360,"mm")])
        self.assertEqual(fr("gpu_case.max_length",r)[0].result, RESULT_REQUIRES_VERIFICATION)

    def test_multiple_gpus_single_case(self):
        g1=comp("GPU"); g2=comp("GPU"); case=comp("Case")
        b=Build(name="b",component_ids=[g1.id,g2.id,case.id])
        profs=[TechnicalProfile(component_id=g1.id,attributes=[vattr("card_length_mm",300,"mm")]),
               TechnicalProfile(component_id=g2.id,attributes=[vattr("card_length_mm",400,"mm")]),
               TechnicalProfile(component_id=case.id,attributes=[vattr("max_gpu_length_mm",360,"mm")])]
        r=analyze_build_compatibility(b,[g1,g2,case],profs)
        fs=fr("gpu_case.max_length",r)
        self.assertEqual(len(fs),2)
        self.assertEqual({f.result for f in fs}, {RESULT_COMPATIBLE, RESULT_INCOMPATIBLE})

    def test_multiple_cases_ambiguous(self):
        gpu=comp("GPU"); c1=comp("Case"); c2=comp("Case")
        b=Build(name="b",component_ids=[gpu.id,c1.id,c2.id])
        r=analyze_build_compatibility(b,[gpu,c1,c2],[TechnicalProfile(component_id=gpu.id,attributes=[vattr("card_length_mm",300,"mm")])])
        self.assertTrue(fr("build.ambiguous_case",r))
        self.assertFalse(fr("gpu_case.max_length",r))
        self.assertIn("gpu_geometry_not_fully_evaluated", r.analysis_limitations)


class TestCPUCooling(unittest.TestCase):
    def test_socket_verified_compatible_with_thermal_limitations(self):
        cpu=comp("CPU"); cool=comp("Cooling")
        b=Build(name="b",component_ids=[cpu.id,cool.id])
        profs=[TechnicalProfile(component_id=cpu.id,attributes=[vattr("socket_designation","AM5")]),
               TechnicalProfile(component_id=cool.id,attributes=[vattr("cooler_type","air_cpu_cooler"), vattr("supported_cpu_sockets",["AM4","AM5"])])]
        r=analyze_build_compatibility(b,[cpu,cool],profs)
        self.assertEqual(fr("cpu_cooling.socket_support",r)[0].result, RESULT_COMPATIBLE)
        self.assertEqual(r.overall_result, RESULT_REQUIRES_VERIFICATION)  # thermal not evaluated
        self.assertIn("thermal_performance_not_evaluated", r.analysis_limitations)

    def test_socket_verified_incompatible(self):
        cpu=comp("CPU"); cool=comp("Cooling")
        b=Build(name="b",component_ids=[cpu.id,cool.id])
        profs=[TechnicalProfile(component_id=cpu.id,attributes=[vattr("socket_designation","LGA1700")]),
               TechnicalProfile(component_id=cool.id,attributes=[vattr("cooler_type","air_cpu_cooler"), vattr("supported_cpu_sockets",["AM5"])])]
        r=analyze_build_compatibility(b,[cpu,cool],profs)
        self.assertEqual(fr("cpu_cooling.socket_support",r)[0].result, RESULT_INCOMPATIBLE)
        self.assertEqual(r.overall_result, RESULT_INCOMPATIBLE)

    def test_socket_unverified_requires(self):
        cpu=comp("CPU"); cool=comp("Cooling")
        b=Build(name="b",component_ids=[cpu.id,cool.id])
        profs=[TechnicalProfile(component_id=cpu.id,attributes=[uattr("socket_designation","AM5")]),
               TechnicalProfile(component_id=cool.id,attributes=[vattr("cooler_type","aio_cpu_cooler"), vattr("supported_cpu_sockets",["AM5"])])]
        r=analyze_build_compatibility(b,[cpu,cool],profs)
        self.assertEqual(fr("cpu_cooling.socket_support",r)[0].result, RESULT_REQUIRES_VERIFICATION)

    def test_no_alias_equivalence(self):
        cpu=comp("CPU"); cool=comp("Cooling")
        b=Build(name="b",component_ids=[cpu.id,cool.id])
        profs=[TechnicalProfile(component_id=cpu.id,attributes=[vattr("socket_designation","LGA1700")]),
               TechnicalProfile(component_id=cool.id,attributes=[vattr("cooler_type","air_cpu_cooler"), vattr("supported_cpu_sockets",["LGA 1700"])])]
        r=analyze_build_compatibility(b,[cpu,cool],profs)
        self.assertEqual(fr("cpu_cooling.socket_support",r)[0].result, RESULT_INCOMPATIBLE)

    def test_missing_identifier(self):
        cpu=comp("CPU"); cool=comp("Cooling")
        b=Build(name="b",component_ids=[cpu.id,cool.id])
        profs=[TechnicalProfile(component_id=cool.id,attributes=[vattr("cooler_type","air_cpu_cooler"), vattr("supported_cpu_sockets",["AM5"])])]
        r=analyze_build_compatibility(b,[cpu,cool],profs)
        self.assertEqual(fr("cpu_cooling.socket_support",r)[0].result, RESULT_INSUFFICIENT_DATA)

    def test_multiple_sockets_supported(self):
        cpu=comp("CPU"); cool=comp("Cooling")
        b=Build(name="b",component_ids=[cpu.id,cool.id])
        profs=[TechnicalProfile(component_id=cpu.id,attributes=[vattr("socket_designation","AM4")]),
               TechnicalProfile(component_id=cool.id,attributes=[vattr("cooler_type","air_cpu_cooler"), vattr("supported_cpu_sockets",["AM4","AM5","LGA1700"])])]
        r=analyze_build_compatibility(b,[cpu,cool],profs)
        self.assertEqual(fr("cpu_cooling.socket_support",r)[0].result, RESULT_COMPATIBLE)

    def test_multiple_cpu_coolers_ambiguous(self):
        cpu=comp("CPU"); c1=comp("Cooling"); c2=comp("Cooling")
        b=Build(name="b",component_ids=[cpu.id,c1.id,c2.id])
        profs=[TechnicalProfile(component_id=cpu.id,attributes=[vattr("socket_designation","AM5")]),
               TechnicalProfile(component_id=c1.id,attributes=[vattr("cooler_type","air_cpu_cooler"), vattr("supported_cpu_sockets",["AM5"])]),
               TechnicalProfile(component_id=c2.id,attributes=[vattr("cooler_type","aio_cpu_cooler"), vattr("supported_cpu_sockets",["AM5"])])]
        r=analyze_build_compatibility(b,[cpu,c1,c2],profs)
        self.assertTrue(fr("build.ambiguous_cpu_cooler",r))
        self.assertFalse(fr("cpu_cooling.socket_support",r))

    def test_case_fan_not_cpu_cooler(self):
        cpu=comp("CPU"); fan=comp("Cooling")
        b=Build(name="b",component_ids=[cpu.id,fan.id])
        profs=[TechnicalProfile(component_id=cpu.id,attributes=[vattr("socket_designation","AM5")]),
               TechnicalProfile(component_id=fan.id,attributes=[vattr("cooler_type","case_fan")])]
        r=analyze_build_compatibility(b,[cpu,fan],profs)
        self.assertFalse(fr("cpu_cooling.socket_support",r))
        self.assertTrue(fr("cpu_cooling.cpu_cooler_missing",r))

    def test_multiple_cpus_ambiguous(self):
        c1=comp("CPU"); c2=comp("CPU"); cool=comp("Cooling")
        b=Build(name="b",component_ids=[c1.id,c2.id,cool.id])
        profs=[TechnicalProfile(component_id=c1.id,attributes=[vattr("socket_designation","AM5")]),
               TechnicalProfile(component_id=c2.id,attributes=[vattr("socket_designation","AM5")]),
               TechnicalProfile(component_id=cool.id,attributes=[vattr("cooler_type","air_cpu_cooler"), vattr("supported_cpu_sockets",["AM5"])])]
        r=analyze_build_compatibility(b,[c1,c2,cool],profs)
        self.assertTrue(fr("build.ambiguous_cpu",r))
        self.assertFalse(fr("cpu_cooling.socket_support",r))


class TestCoolingCase(unittest.TestCase):
    def test_air_height_verified_compatible_with_limitations(self):
        cool=comp("Cooling"); case=comp("Case")
        b=Build(name="b",component_ids=[cool.id,case.id])
        profs=[TechnicalProfile(component_id=cool.id,attributes=[vattr("cooler_type","air_cpu_cooler"), vattr("cooler_height_mm",155,"mm")]),
               TechnicalProfile(component_id=case.id,attributes=[vattr("max_cpu_cooler_height_mm",170,"mm")])]
        r=analyze_build_compatibility(b,[cool,case],profs)
        self.assertEqual(fr("cooling_case.air_cooler_height",r)[0].result, RESULT_COMPATIBLE)
        self.assertEqual(r.overall_result, RESULT_REQUIRES_VERIFICATION)

    def test_air_exact_limit(self):
        cool=comp("Cooling"); case=comp("Case")
        b=Build(name="b",component_ids=[cool.id,case.id])
        profs=[TechnicalProfile(component_id=cool.id,attributes=[vattr("cooler_type","air_cpu_cooler"), vattr("cooler_height_mm",170,"mm")]),
               TechnicalProfile(component_id=case.id,attributes=[vattr("max_cpu_cooler_height_mm",170,"mm")])]
        r=analyze_build_compatibility(b,[cool,case],profs)
        self.assertEqual(fr("cooling_case.air_cooler_height",r)[0].result, RESULT_COMPATIBLE)

    def test_air_too_high_incompatible(self):
        cool=comp("Cooling"); case=comp("Case")
        b=Build(name="b",component_ids=[cool.id,case.id])
        profs=[TechnicalProfile(component_id=cool.id,attributes=[vattr("cooler_type","air_cpu_cooler"), vattr("cooler_height_mm",180,"mm")]),
               TechnicalProfile(component_id=case.id,attributes=[vattr("max_cpu_cooler_height_mm",170,"mm")])]
        r=analyze_build_compatibility(b,[cool,case],profs)
        self.assertEqual(fr("cooling_case.air_cooler_height",r)[0].result, RESULT_INCOMPATIBLE)
        self.assertEqual(r.overall_result, RESULT_INCOMPATIBLE)

    def test_air_unverified_and_insufficient(self):
        cool=comp("Cooling"); case=comp("Case")
        b=Build(name="b",component_ids=[cool.id,case.id])
        profs=[TechnicalProfile(component_id=cool.id,attributes=[vattr("cooler_type","air_cpu_cooler"), uattr("cooler_height_mm",180,"mm")]),
               TechnicalProfile(component_id=case.id,attributes=[vattr("max_cpu_cooler_height_mm",170,"mm")])]
        r=analyze_build_compatibility(b,[cool,case],profs)
        self.assertEqual(fr("cooling_case.air_cooler_height",r)[0].result, RESULT_REQUIRES_VERIFICATION)
        r2=analyze_build_compatibility(b,[cool,case],[TechnicalProfile(component_id=cool.id,attributes=[vattr("cooler_type","air_cpu_cooler")])])
        self.assertEqual(fr("cooling_case.air_cooler_height",r2)[0].result, RESULT_INSUFFICIENT_DATA)

    def test_aio_custom_loop_out_of_scope_not_compatible(self):
        for ctype in ("aio_cpu_cooler","custom_loop_cpu_cooler"):
            cool=comp("Cooling"); case=comp("Case")
            b=Build(name="b",component_ids=[cool.id,case.id])
            profs=[TechnicalProfile(component_id=cool.id,attributes=[vattr("cooler_type",ctype)]),
                   TechnicalProfile(component_id=case.id,attributes=[vattr("max_cpu_cooler_height_mm",170,"mm")])]
            r=analyze_build_compatibility(b,[cool,case],profs)
            self.assertFalse(fr("cooling_case.air_cooler_height",r))
            self.assertTrue(fr("cooling_case.liquid_mounting_scope",r))
            self.assertNotEqual(r.overall_result, RESULT_COMPATIBLE)

    def test_case_fan_no_cpu_height_rule(self):
        cool=comp("Cooling"); case=comp("Case")
        b=Build(name="b",component_ids=[cool.id,case.id])
        profs=[TechnicalProfile(component_id=cool.id,attributes=[vattr("cooler_type","case_fan")]),
               TechnicalProfile(component_id=case.id,attributes=[vattr("max_cpu_cooler_height_mm",170,"mm")])]
        r=analyze_build_compatibility(b,[cool,case],profs)
        self.assertFalse(fr("cooling_case.air_cooler_height",r))
        self.assertFalse(fr("cooling_case.liquid_mounting_scope",r))
        self.assertFalse(fr("cpu_cooling.socket_support",r))


class TestT175Regression(unittest.TestCase):
    def test_ram_mb_mb_case_still_work(self):
        ram=comp("RAM"); mb=comp("Motherboard"); case=comp("Case")
        b=Build(name="b",component_ids=[ram.id,mb.id,case.id])
        profs=[
            TechnicalProfile(component_id=ram.id,attributes=[vattr("memory_generation","DDR5"),vattr("module_form_factor","DIMM"),vattr("total_capacity_gb",32,"GB"),vattr("module_count",2)]),
            TechnicalProfile(component_id=mb.id,attributes=[vattr("supported_memory_generations",["DDR5"]),vattr("supported_memory_module_form_factors",["DIMM"]),vattr("max_memory_capacity_gb",128,"GB"),vattr("memory_slot_count",4),vattr("form_factor","ATX")]),
            TechnicalProfile(component_id=case.id,attributes=[vattr("supported_motherboard_form_factors",["ATX"])]),
        ]
        r=analyze_build_compatibility(b,[ram,mb,case],profs)
        self.assertEqual(r.overall_result, RESULT_COMPATIBLE)
        self.assertTrue(fr("ram_mb.memory_generation",r))
        self.assertTrue(fr("mb_case.form_factor",r))

    def test_t174_scenarios_results_preserved(self):
        # compatible (RAM+MB+Case verified, no OOS)
        ram=comp("RAM"); mb=comp("Motherboard"); case=comp("Case")
        b=Build(name="b",component_ids=[ram.id,mb.id,case.id])
        profs=[TechnicalProfile(component_id=ram.id,attributes=[vattr("memory_generation","DDR5"),vattr("module_form_factor","DIMM"),vattr("total_capacity_gb",32,"GB"),vattr("module_count",2)]),
               TechnicalProfile(component_id=mb.id,attributes=[vattr("supported_memory_generations",["DDR5"]),vattr("supported_memory_module_form_factors",["DIMM"]),vattr("max_memory_capacity_gb",128,"GB"),vattr("memory_slot_count",4),vattr("form_factor","ATX")]),
               TechnicalProfile(component_id=case.id,attributes=[vattr("supported_motherboard_form_factors",["ATX"])])]
        self.assertEqual(analyze_build_compatibility(b,[ram,mb,case],profs).overall_result, RESULT_COMPATIBLE)
        # incompatible
        ram=comp("RAM"); mb=comp("Motherboard")
        b=Build(name="b",component_ids=[ram.id,mb.id])
        profs=[TechnicalProfile(component_id=ram.id,attributes=[vattr("memory_generation","DDR4"),vattr("module_form_factor","DIMM"),vattr("total_capacity_gb",32,"GB"),vattr("module_count",2)]),
               TechnicalProfile(component_id=mb.id,attributes=[vattr("supported_memory_generations",["DDR5"]),vattr("supported_memory_module_form_factors",["DIMM"]),vattr("max_memory_capacity_gb",128,"GB"),vattr("memory_slot_count",4),vattr("form_factor","ATX")])]
        self.assertEqual(analyze_build_compatibility(b,[ram,mb],profs).overall_result, RESULT_INCOMPATIBLE)
        # insufficient data
        ram=comp("RAM"); mb=comp("Motherboard"); b=Build(name="b",component_ids=[ram.id,mb.id])
        self.assertEqual(analyze_build_compatibility(b,[ram,mb],[]).overall_result, RESULT_INSUFFICIENT_DATA)
        # requires verification by OOS (CPU+GPU only)
        cpu=comp("CPU"); gpu=comp("GPU"); b=Build(name="b",component_ids=[cpu.id,gpu.id])
        r=analyze_build_compatibility(b,[cpu,gpu],[])
        self.assertEqual(r.overall_result, RESULT_REQUIRES_VERIFICATION)
        self.assertTrue(r.not_evaluated_relations)

    def test_critical_incompatibility_preserves_oos_visibility(self):
        cpu=comp("CPU"); cool=comp("Cooling")
        b=Build(name="b",component_ids=[cpu.id,cool.id])
        profs=[TechnicalProfile(component_id=cpu.id,attributes=[vattr("socket_designation","LGA1700")]),
               TechnicalProfile(component_id=cool.id,attributes=[vattr("cooler_type","air_cpu_cooler"), vattr("supported_cpu_sockets",["AM5"])])]
        r=analyze_build_compatibility(b,[cpu,cool],profs)
        self.assertEqual(r.overall_result, RESULT_INCOMPATIBLE)
        self.assertTrue(r.analysis_limitations)  # thermal limits still visible

    def test_purity_no_mutation(self):
        import copy
        gpu=comp("GPU"); case=comp("Case"); b=Build(name="b",component_ids=[gpu.id,case.id])
        profs=[TechnicalProfile(component_id=gpu.id,attributes=[uattr("card_length_mm",300,"mm")])]
        before_b=copy.deepcopy(b.__dict__); before_p=[p.to_dict() for p in profs]
        analyze_build_compatibility(b,[gpu,case],profs)
        self.assertEqual(b.__dict__, before_b); self.assertEqual([p.to_dict() for p in profs], before_p)


if __name__ == "__main__":
    unittest.main()
