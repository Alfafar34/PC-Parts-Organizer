"""T17.8a storage rules: M.2 slot fit + bay capacity, conservative, no assignment."""

from __future__ import annotations

try:
    import tests._pcpo_test_isolation_bootstrap  # noqa: F401
except Exception:
    import _pcpo_test_isolation_bootstrap  # type: ignore  # noqa: F401

import copy
import unittest
import uuid

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


def cid(): return str(uuid.uuid4())
def comp(cat, **kw):
    d = dict(category=cat, manufacturer="M", model="X", specifications="", notes="")
    d.update(kw); return Component(**d)
def va(key, value, unit=None):
    return TechnicalAttribute(key=key, value=value, unit=unit, source="official_vendor_doc", confidence="high", verification_status="verified", evidence_ref="https://vendor/doc", verified_at="2026-01-01")
def ua(key, value, unit=None): return TechnicalAttribute(key=key, value=value, unit=unit)
def slot(slot_id, modes=("pcie_nvme",), keyings=("M",), lengths=("2280",), evidence="https://mb/slot", **o):
    d = {"slot_id":slot_id, "accepted_module_keyings":list(keyings), "supported_lengths":list(lengths), "supported_modes":list(modes), "evidence_ref":evidence}
    d.update(o)
    return d
def fr(rule, rep): return [f for f in rep.findings if f.rule_id == rule]


class TestM2(unittest.TestCase):
    def _build(self, storage_attrs, slots_attr, case_attrs=None, extra_storages=None):
        st = comp("Storage"); mb = comp("Motherboard"); case = comp("Case") if case_attrs is not None else None
        storages = [st] + (extra_storages or [])
        comps = storages + [mb] + ([case] if case else [])
        profs = [TechnicalProfile(component_id=st.id, attributes=list(storage_attrs)),
                 TechnicalProfile(component_id=mb.id, attributes=[slots_attr])]
        if case: profs.append(TechnicalProfile(component_id=case.id, attributes=list(case_attrs)))
        b = Build(name="b", component_ids=[c.id for c in comps])
        return analyze_build_compatibility(b, comps, profs), st, mb, case

    def test_sata_ata_supported_slot_verified_compatible_dimension(self):
        r,st,mb,_ = self._build([va("storage_form_factor","m2"),va("storage_interface","sata"),va("storage_command_set","ata"),va("m2_keying","B_M"),va("m2_length_code","2280")],
            va("m2_slots",[slot("M2_1",modes=("sata_ata",),keyings=("B_M",),lengths=("2280",))]))
        f = fr("storage_m2.fit", r)[0]
        self.assertEqual(f.result, RESULT_COMPATIBLE)
        self.assertEqual(r.overall_result, RESULT_REQUIRES_VERIFICATION)  # topology/perf not evaluated
        self.assertTrue(r.not_evaluated_relations)
        self.assertIn("m2_topology_not_fully_evaluated", r.analysis_limitations)

    def test_pcie_nvme_supported_slot_verified_compatible_dimension(self):
        r,st,mb,_ = self._build([va("storage_form_factor","m2"),va("storage_interface","pcie"),va("storage_command_set","nvme"),va("m2_keying","M"),va("m2_length_code","2280")],
            va("m2_slots",[slot("M2_1",modes=("pcie_nvme",),keyings=("M",),lengths=("2280",))]))
        self.assertEqual(fr("storage_m2.fit", r)[0].result, RESULT_COMPATIBLE)

    def test_protocol_contradiction_requires_not_incompatible_without_proof(self):
        r,st,mb,_ = self._build([va("storage_form_factor","m2"),va("storage_interface","sata"),va("storage_command_set","ata"),va("m2_keying","B_M"),va("m2_length_code","2280")],
            va("m2_slots",[slot("M2_1",modes=("pcie_nvme",),keyings=("M",),lengths=("2280",))]))
        f = fr("storage_m2.fit", r)[0]
        # R1: collection exhaustiveness not formally guaranteed -> no negative inference from absence-in-list
        self.assertEqual(f.result, RESULT_REQUIRES_VERIFICATION)

    def test_keying_not_demonstrated_degrades(self):
        r,st,mb,_ = self._build([va("storage_form_factor","m2"),va("storage_interface","pcie"),va("storage_command_set","nvme"),va("m2_keying","B_M"),va("m2_length_code","2280")],
            va("m2_slots",[slot("M2_1",modes=("pcie_nvme",),keyings=("M",),lengths=("2280",))]))
        self.assertEqual(fr("storage_m2.fit", r)[0].result, RESULT_REQUIRES_VERIFICATION)

    def test_length_admitted_not_admitted_other_and_missing(self):
        ok = self._build([va("storage_form_factor","m2"),va("storage_interface","pcie"),va("storage_command_set","nvme"),va("m2_keying","M"),va("m2_length_code","2280")],
            va("m2_slots",[slot("M2_1",lengths=("2280",))]))
        self.assertEqual(fr("storage_m2.fit", ok[0])[0].result, RESULT_COMPATIBLE)
        no = self._build([va("storage_form_factor","m2"),va("storage_interface","pcie"),va("storage_command_set","nvme"),va("m2_keying","M"),va("m2_length_code","22110")],
            va("m2_slots",[slot("M2_1",lengths=("2280",))]))
        # R1: even with verified/granular declared slots, exhaustiveness not formally guaranteed
        self.assertEqual(fr("storage_m2.fit", no[0])[0].result, RESULT_REQUIRES_VERIFICATION)
        other = self._build([va("storage_form_factor","m2"),va("storage_interface","pcie"),va("storage_command_set","nvme"),va("m2_keying","M"),va("m2_length_code","other")],
            va("m2_slots",[slot("M2_1",modes=("pcie_nvme",),lengths=("2280",))]))
        # 'other' length cannot be confirmed and is not a demonstrated contradiction
        self.assertEqual(fr("storage_m2.fit", other[0])[0].result, RESULT_REQUIRES_VERIFICATION)
        missing = self._build([va("storage_form_factor","m2"),va("m2_keying","M")],
            va("m2_slots",[slot("M2_1")]))
        self.assertEqual(fr("storage_m2.fit", missing[0])[0].result, RESULT_INSUFFICIENT_DATA)

    def test_no_slots_and_unverified_collection(self):
        r,_,_,_ = self._build([va("storage_form_factor","m2"),va("m2_keying","M"),va("m2_length_code","2280"),va("storage_interface","pcie"),va("storage_command_set","nvme")], ua("m2_slots",[slot("M2_1")]))
        # unverified slots -> not compatible; no negative conclusion from unverified collection
        self.assertEqual(fr("storage_m2.fit", r)[0].result, RESULT_REQUIRES_VERIFICATION)

    def test_multiple_units_no_joint_fit_and_no_assignment(self):
        from pc_parts_organizer.technical_profiles import TechnicalProfile
        s2 = comp("Storage")
        r,st,mb,_ = self._build([va("storage_form_factor","m2"),va("storage_interface","pcie"),va("storage_command_set","nvme"),va("m2_keying","M"),va("m2_length_code","2280")],
            va("m2_slots",[slot("M2_1"), slot("M2_2")]), extra_storages=[s2])
        # second M.2 unit declared but unverified -> still two declared M.2 units
        # attach a declared (unverified) M.2 profile to the extra storage
        profs_extra = TechnicalProfile(component_id=s2.id, attributes=[
            ua("storage_form_factor","m2"),ua("storage_interface","pcie"),ua("storage_command_set","nvme"),ua("m2_keying","M"),ua("m2_length_code","2280")])
        from pc_parts_organizer.compatibility import analyze_build_compatibility
        from pc_parts_organizer.models import Build
        # rebuild with both profiles to assert joint-fit limitation for two declared M.2
        comps = [st, s2, mb]
        profs = [TechnicalProfile(component_id=st.id, attributes=[va("storage_form_factor","m2"),va("storage_interface","pcie"),va("storage_command_set","nvme"),va("m2_keying","M"),va("m2_length_code","2280")]),
                 profs_extra,
                 TechnicalProfile(component_id=mb.id, attributes=[va("m2_slots",[slot("M2_1"), slot("M2_2")])])]
        b = Build(name="b", component_ids=[c.id for c in comps])
        r2 = analyze_build_compatibility(b, comps, profs)
        fs = fr("storage_m2.fit", r2)
        self.assertGreaterEqual(len(fs), 1)
        self.assertEqual(r2.overall_result, RESULT_REQUIRES_VERIFICATION)
        self.assertIn("multi_m2_joint_fit_not_evaluated", r2.analysis_limitations)

    def test_pcie_gen_lanes_different_not_incompatibility(self):
        r,st,mb,_ = self._build([va("storage_form_factor","m2"),va("storage_interface","pcie"),va("storage_command_set","nvme"),va("m2_keying","M"),va("m2_length_code","2280")],
            va("m2_slots",[slot("M2_1",pcie_generation_max=3,pcie_lanes_max="x4")]))
        self.assertEqual(fr("storage_m2.fit", r)[0].result, RESULT_COMPATIBLE)
        self.assertIn("m2_topology_not_fully_evaluated", r.analysis_limitations)

    def test_incomplete_essential_data(self):
        r,_,_,_ = self._build([va("storage_form_factor","m2"),va("storage_interface","pcie")], va("m2_slots",[slot("M2_1")]))
        self.assertEqual(fr("storage_m2.fit", r)[0].result, RESULT_INSUFFICIENT_DATA)

    def test_absent_m2_slots_not_proven_empty(self):
        st = comp("Storage"); mb = comp("Motherboard")
        b = Build(name="b", component_ids=[st.id,mb.id])
        profs = [TechnicalProfile(component_id=st.id, attributes=[va("storage_form_factor","m2"),va("storage_interface","pcie"),va("storage_command_set","nvme"),va("m2_keying","M"),va("m2_length_code","2280")]),
                 TechnicalProfile(component_id=mb.id, attributes=[])]
        r = analyze_build_compatibility(b,[st,mb],profs)
        f = fr("storage_m2.slots_absent", r)[0]
        self.assertEqual(f.result, RESULT_INSUFFICIENT_DATA)
        self.assertNotEqual(f.severity, SEVERITY_CRITICAL)
        self.assertIn("m2_topology_not_fully_evaluated", r.analysis_limitations)

    def test_shared_resource_group_not_treated_as_availability(self):
        r,st,mb,_ = self._build([va("storage_form_factor","m2"),va("storage_interface","pcie"),va("storage_command_set","nvme"),va("m2_keying","M"),va("m2_length_code","2280")],
            va("m2_slots",[slot("M2_1", shared_resource_group_id="G1"), slot("M2_2", shared_resource_group_id="G1")]))
        f = fr("storage_m2.fit", r)[0]
        # may find a candidate slot, but joint/shared topology not modeled; global not compatible
        self.assertIn(f.result, (RESULT_COMPATIBLE, RESULT_REQUIRES_VERIFICATION))
        self.assertEqual(r.overall_result, RESULT_REQUIRES_VERIFICATION)
        self.assertIn("m2_topology_not_fully_evaluated", r.analysis_limitations)

    def test_r1_no_incompatible_without_formal_exhaustiveness_even_if_verified_granular(self):
        # R1 audit: verified+high-confidence collection and every declared slot has evidence_ref
        # still does NOT prove no omitted physical slots exist; absence-in-list => requires_verification.
        r,_,_,_ = self._build([va("storage_form_factor","m2"),va("storage_interface","pcie"),va("storage_command_set","nvme"),va("m2_keying","M"),va("m2_length_code","22110")],
            va("m2_slots",[slot("M2_1", lengths=("2280",), evidence="https://mb/all?not-exhaustiveness-proof")]))
        f = fr("storage_m2.fit", r)[0]
        self.assertEqual(f.result, RESULT_REQUIRES_VERIFICATION)
        self.assertNotIn(f.result, (RESULT_INCOMPATIBLE,))

    def test_r1_positive_fit_still_possible_without_claiming_exhaustiveness(self):
        r,_,_,_ = self._build([va("storage_form_factor","m2"),va("storage_interface","pcie"),va("storage_command_set","nvme"),va("m2_keying","M"),va("m2_length_code","2280")],
            va("m2_slots",[slot("M2_1", evidence="https://mb/slot")]))
        f = fr("storage_m2.fit", r)[0]
        self.assertEqual(f.result, RESULT_COMPATIBLE)  # dimensional positive; not a slot assignment
        self.assertEqual(r.overall_result, RESULT_REQUIRES_VERIFICATION)


class TestBays(unittest.TestCase):
    def _build(self, units_25=0, units_35=0, bay25=None, bay35=None, bay_verified=True, ff_verified=True):
        storages = []
        for i in range(units_25): storages.append(comp("Storage"))
        for i in range(units_35): storages.append(comp("Storage"))
        case = comp("Case")
        comps = storages + [case]
        profs = []
        for i, s in enumerate(storages):
            ff = va("storage_form_factor", "2_5_in" if i < units_25 else "3_5_in") if ff_verified else ua("storage_form_factor", "2_5_in" if i < units_25 else "3_5_in")
            profs.append(TechnicalProfile(component_id=s.id, attributes=[ff]))
        attrs = []
        if bay25 is not None: attrs.append((va if bay_verified else ua)("bay_2_5_total", bay25))
        if bay35 is not None: attrs.append((va if bay_verified else ua)("bay_3_5_total", bay35))
        profs.append(TechnicalProfile(component_id=case.id, attributes=attrs))
        b = Build(name="b", component_ids=[c.id for c in comps])
        return analyze_build_compatibility(b, comps, profs)

    def test_25_fits_one_bay_verified(self):
        r = self._build(units_25=1, bay25=1)
        f = fr("storage_case.bay_2_5_capacity", r)[0]
        self.assertEqual(f.result, RESULT_COMPATIBLE)
        self.assertEqual(r.overall_result, RESULT_REQUIRES_VERIFICATION)  # bay free-space not evaluated
        self.assertIn("bay_free_space_not_evaluated", r.analysis_limitations)

    def test_35_fits_one_bay_verified(self):
        r = self._build(units_35=1, bay35=1)
        self.assertEqual(fr("storage_case.bay_3_5_capacity", r)[0].result, RESULT_COMPATIBLE)

    def test_exceeds_25_capacity_incompatible(self):
        r = self._build(units_25=3, bay25=2)
        f = fr("storage_case.bay_2_5_capacity", r)[0]
        self.assertEqual(f.result, RESULT_INCOMPATIBLE)
        self.assertEqual(f.severity, SEVERITY_CRITICAL)
        self.assertEqual(r.overall_result, RESULT_INCOMPATIBLE)

    def test_no_cross_size_installation_inference(self):
        r = self._build(units_25=2, bay25=0, bay35=4)
        self.assertEqual(fr("storage_case.bay_2_5_capacity", r)[0].result, RESULT_INCOMPATIBLE)

    def test_capacity_missing_and_unverified(self):
        r = self._build(units_25=1, bay25=None)
        self.assertEqual(fr("storage_case.bay_2_5_capacity", r)[0].result, RESULT_INSUFFICIENT_DATA)
        r2 = self._build(units_25=3, bay25=2, bay_verified=False)
        self.assertEqual(fr("storage_case.bay_2_5_capacity", r2)[0].result, RESULT_REQUIRES_VERIFICATION)
        r3 = self._build(units_25=1, bay25=1, ff_verified=False)
        self.assertEqual(fr("storage_case.bay_2_5_capacity", r3)[0].result, RESULT_REQUIRES_VERIFICATION)

    def test_multiple_units_exceed(self):
        r = self._build(units_35=4, bay35=2)
        self.assertEqual(fr("storage_case.bay_3_5_capacity", r)[0].result, RESULT_INCOMPATIBLE)

    def test_case_missing(self):
        st = comp("Storage")
        b = Build(name="b", component_ids=[st.id])
        profs = [TechnicalProfile(component_id=st.id, attributes=[va("storage_form_factor","2_5_in")])]
        r = analyze_build_compatibility(b,[st],profs)
        self.assertTrue(any(f.rule_id == "storage_case.case_missing" for f in r.findings))
        # global may be requires_verification due to not-evaluated relations/limitations
        self.assertIn(r.overall_result, (RESULT_INSUFFICIENT_DATA, RESULT_REQUIRES_VERIFICATION))


class TestR3ApplicabilityAndParticipants(unittest.TestCase):
    def test_bay_only_without_motherboard_no_m2_motherboard_missing(self):
        case = comp("Case"); s25 = comp("Storage"); s35 = comp("Storage")
        b = Build(name="b", component_ids=[case.id,s25.id,s35.id])
        profs = [TechnicalProfile(component_id=case.id, attributes=[va("supported_motherboard_form_factors",["ATX"]), va("bay_2_5_total",1), va("bay_3_5_total",1)]),
                 TechnicalProfile(component_id=s25.id, attributes=[va("storage_form_factor","2_5_in")]),
                 TechnicalProfile(component_id=s35.id, attributes=[va("storage_form_factor","3_5_in")])]
        r = analyze_build_compatibility(b,[case,s25,s35],profs)
        self.assertFalse(any(f.rule_id == "storage_m2.motherboard_missing" for f in r.findings))
        self.assertTrue(any(f.rule_id.startswith("storage_case.bay_") for f in r.findings))

    def test_m2_without_motherboard_generates_missing_with_m2_only_participants(self):
        m2 = comp("Storage"); s25 = comp("Storage")
        b = Build(name="b", component_ids=[m2.id,s25.id])
        profs = [TechnicalProfile(component_id=m2.id, attributes=[va("storage_form_factor","m2"), va("storage_interface","pcie"), va("storage_command_set","nvme"), va("m2_keying","M"), va("m2_length_code","2280")]),
                 TechnicalProfile(component_id=s25.id, attributes=[va("storage_form_factor","2_5_in")])]
        r = analyze_build_compatibility(b,[m2,s25],profs)
        miss = [f for f in r.findings if f.rule_id == "storage_m2.motherboard_missing"]
        self.assertEqual(len(miss), 1)
        self.assertEqual(list(miss[0].component_ids), [m2.id])

    def test_with_motherboard_no_false_motherboard_missing(self):
        mb = comp("Motherboard"); m2 = comp("Storage")
        b = Build(name="b", component_ids=[mb.id,m2.id])
        profs = [TechnicalProfile(component_id=mb.id, attributes=[va("m2_slots",[slot("M2_1")])]),
                 TechnicalProfile(component_id=m2.id, attributes=[va("storage_form_factor","m2"), va("storage_interface","pcie"), va("storage_command_set","nvme"), va("m2_keying","M"), va("m2_length_code","2280")])]
        r = analyze_build_compatibility(b,[mb,m2],profs)
        self.assertFalse(any(f.rule_id == "storage_m2.motherboard_missing" for f in r.findings))

    def test_bay_participants_exact_per_form_factor(self):
        case = comp("Case"); s25 = comp("Storage"); s35 = comp("Storage")
        b = Build(name="b", component_ids=[case.id,s25.id,s35.id])
        profs = [TechnicalProfile(component_id=case.id, attributes=[va("supported_motherboard_form_factors",["ATX"]), va("bay_2_5_total",1), va("bay_3_5_total",1)]),
                 TechnicalProfile(component_id=s25.id, attributes=[va("storage_form_factor","2_5_in")]),
                 TechnicalProfile(component_id=s35.id, attributes=[va("storage_form_factor","3_5_in")])]
        r = analyze_build_compatibility(b,[case,s25,s35],profs)
        b25 = fr("storage_case.bay_2_5_capacity", r)[0]
        b35 = fr("storage_case.bay_3_5_capacity", r)[0]
        self.assertEqual(set(b25.component_ids), {s25.id, case.id})
        self.assertEqual(set(b35.component_ids), {s35.id, case.id})


class TestIntegrationT178a(unittest.TestCase):
    def test_purity_no_mutation_and_determinism(self):
        st = comp("Storage"); mb = comp("Motherboard"); case = comp("Case")
        b = Build(name="b", component_ids=[st.id,mb.id,case.id])
        profs = [TechnicalProfile(component_id=st.id, attributes=[va("storage_form_factor","2_5_in")]),
                 TechnicalProfile(component_id=mb.id, attributes=[va("m2_slots",[slot("M2_1")])]),
                 TechnicalProfile(component_id=case.id, attributes=[va("bay_2_5_total",1)])]
        before_b = copy.deepcopy(b.__dict__); before_p = [p.to_dict() for p in profs]
        r1 = analyze_build_compatibility(b,[st,mb,case],profs)
        r2 = analyze_build_compatibility(b,[st,mb,case],profs)
        self.assertEqual(b.__dict__, before_b); self.assertEqual([p.to_dict() for p in profs], before_p)
        self.assertEqual(r1.to_dict() if hasattr(r1,'to_dict') else (r1.overall_result, list(r1.findings)), r2.to_dict() if hasattr(r2,'to_dict') else (r2.overall_result, list(r2.findings)))

    def test_engine_ruleset_version(self):
        self.assertEqual(ENGINE_RULESET_VERSION, "t17.12-v1")

    def test_old_profiles_without_new_attrs_still_valid(self):
        # T17.3 scenario with no storage attrs; engine still works
        from pc_parts_organizer.technical_profiles import parse_profile_dict
        ram = comp("RAM"); mb = comp("Motherboard")
        b = Build(name="b", component_ids=[ram.id,mb.id])
        profs = [parse_profile_dict({"component_id":ram.id,"attributes":[{"key":"memory_generation","value":"DDR5"},{"key":"module_form_factor","value":"DIMM"},{"key":"total_capacity_gb","value":32,"unit":"GB"},{"key":"module_count","value":2}]},0,"RAM"),
                 parse_profile_dict({"component_id":mb.id,"attributes":[{"key":"supported_memory_generations","value":["DDR5"]},{"key":"supported_memory_module_form_factors","value":["DIMM"]},{"key":"max_memory_capacity_gb","value":128,"unit":"GB"},{"key":"memory_slot_count","value":4},{"key":"form_factor","value":"ATX"}]},0,"Motherboard")]
        r = analyze_build_compatibility(b,[ram,mb],profs)
        # No storage present: legacy RAM/MB findings remain; no storage OOS mark
        self.assertFalse(any(f.rule_id.startswith("storage_") for f in r.findings))
        self.assertFalse(any(n.get("category") == "Storage" for n in r.not_evaluated_relations))


if __name__ == "__main__":
    unittest.main()
