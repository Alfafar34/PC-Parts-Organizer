"""T17.9 SATA connectivity + declared M.2/SATA topology rules.

Descriptive dimensions only: no assignment, solver, RAID/controller modeling,
lane/lane-performance validation, or electrical claims.
"""
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
    analyze_build_compatibility,
)
from pc_parts_organizer.models import Build, Component
from pc_parts_organizer.technical_profiles import M2SlotSpec, TechnicalAttribute, TechnicalProfile


def comp(cat, manufacturer="M", model="X"):
    return Component(category=cat, manufacturer=manufacturer, model=model, specifications="", notes="")


def va(key, value, unit=None):
    return TechnicalAttribute(key=key, value=value, unit=unit, source="official_vendor_doc", confidence="high",
                              verification_status="verified", evidence_ref="https://vendor/doc", verified_at="2026-01-01")


def ua(key, value, unit=None):
    return TechnicalAttribute(key=key, value=value, unit=unit, source="unknown", confidence="low", verification_status="unverified")


def m2_slot(slot_id, keyings=("M",), lengths=("2280",), modes=("pcie_nvme",), disables=(), shared=None, routed="unknown", evidence="https://vendor/slot"):
    return M2SlotSpec(slot_id=slot_id, accepted_module_keyings=keyings, supported_lengths=lengths,
                      supported_modes=modes, disables_sata_port_ids=disables,
                      shared_resource_group_id=shared, routed_to=routed, evidence_ref=evidence)


def storage(ff, iface, cmd, key=None, length=None):
    attrs = [va("storage_form_factor", ff), va("storage_interface", iface), va("storage_command_set", cmd)]
    if key is not None:
        attrs.append(va("m2_keying", key))
    if length is not None:
        attrs.append(va("m2_length_code", length))
    return attrs


def mb_profile(count=None, ids=None, slots=None):
    attrs = []
    if count is not None:
        attrs.append(va("sata_port_count", count))
    if ids is not None:
        attrs.append(va("sata_port_identifiers", ids))
    if slots is not None:
        attrs.append(va("m2_slots", slots))
    return attrs


def find(rep, rule_id):
    return [f for f in rep.findings if f.rule_id == rule_id]


class T179Base(unittest.TestCase):
    def analyze(self, comps, profiles):
        b = Build(name="t179", component_ids=[c.id for c in comps])
        return analyze_build_compatibility(b, comps, profiles)


class TestSataPortAvailability(T179Base):
    def test_25_inch_sata_with_available_port(self):
        mb, st = comp("Motherboard"), comp("Storage")
        r = self.analyze([mb, st], [TechnicalProfile(component_id=mb.id, attributes=mb_profile(count=2)),
                                     TechnicalProfile(component_id=st.id, attributes=storage("2_5_in", "sata", "ata"))])
        f = find(r, "storage_sata.port_availability")
        self.assertEqual([x.result for x in f], [RESULT_COMPATIBLE])
        self.assertIn("sata_port_assignment_not_evaluated", r.analysis_limitations)

    def test_35_inch_sata_with_available_port(self):
        mb, st = comp("Motherboard"), comp("Storage")
        r = self.analyze([mb, st], [TechnicalProfile(component_id=mb.id, attributes=mb_profile(count=1)),
                                     TechnicalProfile(component_id=st.id, attributes=storage("3_5_in", "sata", "ata"))])
        self.assertEqual(find(r, "storage_sata.port_availability")[0].result, RESULT_COMPATIBLE)

    def test_multiple_sata_units_within_declared_count(self):
        mb, a, b = comp("Motherboard"), comp("Storage"), comp("Storage")
        r = self.analyze([mb, a, b], [TechnicalProfile(component_id=mb.id, attributes=mb_profile(count=3)),
                                      TechnicalProfile(component_id=a.id, attributes=storage("2_5_in", "sata", "ata")),
                                      TechnicalProfile(component_id=b.id, attributes=storage("3_5_in", "sata", "ata"))])
        f = find(r, "storage_sata.port_availability")[0]
        self.assertEqual(f.result, RESULT_COMPATIBLE)
        self.assertEqual(f.message_params["required_ports"], 2)
        self.assertEqual(f.message_params["declared_ports"], 3)

    def test_m2_and_pcie_units_do_not_consume_sata_data_ports(self):
        mb, m2s, m2n = comp("Motherboard"), comp("Storage"), comp("Storage")
        slots = [m2_slot("M2_1", modes=("sata_ata", "pcie_nvme")), m2_slot("M2_2", modes=("pcie_nvme",))]
        r = self.analyze([mb, m2s, m2n], [
            TechnicalProfile(component_id=mb.id, attributes=mb_profile(count=0, slots=slots)),
            TechnicalProfile(component_id=m2s.id, attributes=storage("m2", "sata", "ata", "M", "2280")),
            TechnicalProfile(component_id=m2n.id, attributes=storage("m2", "pcie", "nvme", "M", "2280")),
        ])
        self.assertEqual(find(r, "storage_sata.port_availability"), [])
        self.assertNotEqual(r.overall_result, RESULT_INCOMPATIBLE)

    def test_missing_sata_port_count_insufficient_data(self):
        mb, st = comp("Motherboard"), comp("Storage")
        r = self.analyze([mb, st], [TechnicalProfile(component_id=mb.id, attributes=[]),
                                     TechnicalProfile(component_id=st.id, attributes=storage("2_5_in", "sata", "ata"))])
        f = find(r, "storage_sata.port_availability")[0]
        self.assertEqual(f.result, RESULT_INSUFFICIENT_DATA)
        self.assertIn("motherboard.sata_port_count", f.missing_information)

    def test_declared_count_below_demand_requires_verification_never_incompatible(self):
        mb, a, b = comp("Motherboard"), comp("Storage"), comp("Storage")
        r = self.analyze([mb, a, b], [TechnicalProfile(component_id=mb.id, attributes=mb_profile(count=1)),
                                      TechnicalProfile(component_id=a.id, attributes=storage("2_5_in", "sata", "ata")),
                                      TechnicalProfile(component_id=b.id, attributes=storage("3_5_in", "sata", "ata"))])
        f = find(r, "storage_sata.port_availability")[0]
        self.assertEqual(f.result, RESULT_REQUIRES_VERIFICATION)
        self.assertEqual(f.message_params["reason"], "additional_sata_controllers_or_ports_not_excluded")
        self.assertEqual(f.recommended_action, "verify_additional_sata_controllers_and_ports")
        self.assertFalse(any(x.result == RESULT_INCOMPATIBLE for x in find(r, "storage_sata.port_availability")))

    def test_zero_declared_ports_requires_verification_not_incompatible(self):
        mb, st = comp("Motherboard"), comp("Storage")
        r = self.analyze([mb, st], [TechnicalProfile(component_id=mb.id, attributes=mb_profile(count=0)),
                                     TechnicalProfile(component_id=st.id, attributes=storage("2_5_in", "sata", "ata"))])
        f = find(r, "storage_sata.port_availability")[0]
        self.assertEqual(f.result, RESULT_REQUIRES_VERIFICATION)
        self.assertNotEqual(f.result, RESULT_INCOMPATIBLE)

    def test_unverified_port_count_requires_verification(self):
        mb, st = comp("Motherboard"), comp("Storage")
        r = self.analyze([mb, st], [TechnicalProfile(component_id=mb.id, attributes=[ua("sata_port_count", 2)]),
                                     TechnicalProfile(component_id=st.id, attributes=storage("2_5_in", "sata", "ata"))])
        f = find(r, "storage_sata.port_availability")[0]
        self.assertEqual(f.result, RESULT_REQUIRES_VERIFICATION)
        self.assertEqual(f.message_params["reason"], "sata_port_data_not_verified")

    def test_unverified_storage_unit_data_requires_verification(self):
        mb, st = comp("Motherboard"), comp("Storage")
        attrs = [ua("storage_form_factor", "2_5_in"), va("storage_interface", "sata"), va("storage_command_set", "ata")]
        r = self.analyze([mb, st], [TechnicalProfile(component_id=mb.id, attributes=mb_profile(count=2)),
                                     TechnicalProfile(component_id=st.id, attributes=attrs)])
        f = find(r, "storage_sata.port_availability")[0]
        self.assertEqual(f.result, RESULT_REQUIRES_VERIFICATION)
        self.assertEqual(f.message_params["reason"], "storage_units_undetermined")

    def test_undetermined_storage_unit_degrades_count(self):
        mb, st = comp("Motherboard"), comp("Storage")
        r = self.analyze([mb, st], [TechnicalProfile(component_id=mb.id, attributes=mb_profile(count=2)),
                                     TechnicalProfile(component_id=st.id, attributes=[va("storage_form_factor", "2_5_in")])])
        f = find(r, "storage_sata.port_availability")[0]
        self.assertEqual(f.result, RESULT_REQUIRES_VERIFICATION)
        self.assertEqual(f.message_params["reason"], "storage_units_undetermined")

    def test_sata_identifiers_are_declared_evidence_not_assignment(self):
        mb, st = comp("Motherboard"), comp("Storage")
        r = self.analyze([mb, st], [TechnicalProfile(component_id=mb.id, attributes=mb_profile(count=2, ids=["SATA1", "SATA2"])),
                                     TechnicalProfile(component_id=st.id, attributes=storage("2_5_in", "sata", "ata"))])
        f = find(r, "storage_sata.port_availability")[0]
        self.assertEqual(f.result, RESULT_COMPATIBLE)
        self.assertEqual(list(f.evidence["declared_ids"]), ["SATA1", "SATA2"])
        self.assertNotIn("assigned", f.evidence)

    def test_identifiers_without_count_are_not_inferred_as_total(self):
        mb, st = comp("Motherboard"), comp("Storage")
        r = self.analyze([mb, st], [TechnicalProfile(component_id=mb.id, attributes=mb_profile(ids=["SATA1", "SATA2"])),
                                     TechnicalProfile(component_id=st.id, attributes=storage("2_5_in", "sata", "ata"))])
        f = find(r, "storage_sata.port_availability")[0]
        self.assertEqual(f.result, RESULT_INSUFFICIENT_DATA)
        self.assertIn("motherboard.sata_port_count", f.missing_information)

    def test_missing_motherboard(self):
        st = comp("Storage")
        r = self.analyze([st], [TechnicalProfile(component_id=st.id, attributes=storage("2_5_in", "sata", "ata"))])
        f = find(r, "storage_sata.motherboard_missing")
        self.assertEqual([x.result for x in f], [RESULT_INSUFFICIENT_DATA])

    def test_multiple_motherboards_ambiguous(self):
        mb1, mb2, st = comp("Motherboard"), comp("Motherboard"), comp("Storage")
        r = self.analyze([mb1, mb2, st], [
            TechnicalProfile(component_id=mb1.id, attributes=mb_profile(count=2)),
            TechnicalProfile(component_id=mb2.id, attributes=mb_profile(count=2)),
            TechnicalProfile(component_id=st.id, attributes=storage("2_5_in", "sata", "ata")),
        ])
        f = find(r, "storage_sata.ambiguous_motherboard")
        self.assertEqual([x.result for x in f], [RESULT_INSUFFICIENT_DATA])

    def test_participants_are_exact_units_and_motherboard(self):
        mb, st, m2 = comp("Motherboard"), comp("Storage"), comp("Storage")
        r = self.analyze([mb, st, m2], [
            TechnicalProfile(component_id=mb.id, attributes=mb_profile(count=2, slots=[m2_slot("M2_1")])),
            TechnicalProfile(component_id=st.id, attributes=storage("2_5_in", "sata", "ata")),
            TechnicalProfile(component_id=m2.id, attributes=storage("m2", "pcie", "nvme", "M", "2280")),
        ])
        f = find(r, "storage_sata.port_availability")[0]
        self.assertEqual(set(f.component_ids), {st.id, mb.id})
        self.assertNotIn(m2.id, f.component_ids)


class TestM2SataTopology(T179Base):
    def _base(self, slots, count=2, ids=("SATA1", "SATA2"), m2_mode=("pcie", "nvme"), m2_key="M", sata_units=1):
        mb = comp("Motherboard")
        m2 = comp("Storage")
        comps = [mb, m2]
        profs = [TechnicalProfile(component_id=mb.id, attributes=mb_profile(count=count, ids=list(ids) if ids else None, slots=slots)),
                 TechnicalProfile(component_id=m2.id, attributes=storage("m2", m2_mode[0], m2_mode[1], m2_key, "2280"))]
        for _ in range(sata_units):
            st = comp("Storage")
            comps.append(st)
            profs.append(TechnicalProfile(component_id=st.id, attributes=storage("2_5_in", "sata", "ata")))
        return comps, profs

    def test_potential_m2_sata_conflict_requires_verification(self):
        comps, profs = self._base([m2_slot("M2_1", disables=("SATA1",))])
        r = self.analyze(comps, profs)
        f = find(r, "storage_sata.m2_topology")[0]
        self.assertEqual(f.result, RESULT_REQUIRES_VERIFICATION)
        self.assertEqual(f.message_params["reason"], "m2_slot_may_disable_sata_ports")
        self.assertEqual(list(f.message_params["affected_sata_port_ids"]), ["SATA1"])
        self.assertFalse(any(x.result == RESULT_INCOMPATIBLE for x in find(r, "storage_sata.m2_topology")))
        # M.2 fit and SATA port availability remain separate dimensions.
        self.assertEqual(find(r, "storage_m2.fit")[0].result, RESULT_COMPATIBLE)
        self.assertEqual(find(r, "storage_sata.port_availability")[0].result, RESULT_COMPATIBLE)

    def test_m2_sata_unit_and_sata_units_potential_conflict(self):
        comps, profs = self._base([m2_slot("M2_1", keyings=("B_M",), modes=("sata_ata",), disables=("SATA2",))], m2_mode=("sata", "ata"), m2_key="B_M")
        r = self.analyze(comps, profs)
        f = find(r, "storage_sata.m2_topology")[0]
        self.assertEqual(f.result, RESULT_REQUIRES_VERIFICATION)
        self.assertEqual(f.message_params["reason"], "m2_slot_may_disable_sata_ports")
        self.assertEqual(list(f.message_params["affected_sata_port_ids"]), ["SATA2"])
        self.assertEqual(find(r, "storage_m2.fit")[0].result, RESULT_COMPATIBLE)

    def test_multiple_candidate_slots_with_different_restrictions_no_assignment(self):
        comps, profs = self._base([
            m2_slot("M2_1", disables=("SATA1",)),
            m2_slot("M2_2"),
        ])
        r = self.analyze(comps, profs)
        f = find(r, "storage_sata.m2_topology")[0]
        self.assertEqual(f.result, RESULT_REQUIRES_VERIFICATION)
        self.assertEqual(f.message_params["candidate_units"], 1)
        self.assertEqual(f.message_params["restricting_slots"], 1)
        unit = f.evidence["m2_units"][0]
        self.assertEqual(list(unit["candidate_slots"]), ["M2_1", "M2_2"])
        self.assertEqual(list(unit["restricting_slots"]), ["M2_1"])
        self.assertNotIn("assigned_slot", unit)
        self.assertNotIn("slot_assignment", f.evidence)

    def test_shared_resource_group_does_not_become_exclusion_rule(self):
        comps, profs = self._base([m2_slot("M2_1", shared="G1")])
        r = self.analyze(comps, profs)
        f = find(r, "storage_sata.m2_topology")[0]
        self.assertEqual(f.result, RESULT_REQUIRES_VERIFICATION)
        self.assertEqual(f.message_params["reason"], "shared_resource_group_semantics_not_evaluated")
        self.assertTrue(f.evidence["shared_resource_groups"])
        self.assertIn("m2_shared_resource_group_semantics_not_evaluated", r.analysis_limitations)

    def test_routed_to_does_not_prove_lane_availability(self):
        comps, profs = self._base([m2_slot("M2_1", routed="cpu")])
        r = self.analyze(comps, profs)
        f = find(r, "storage_sata.m2_topology")[0]
        self.assertEqual(f.result, RESULT_REQUIRES_VERIFICATION)
        self.assertEqual(f.message_params["reason"], "m2_slot_inventory_exhaustiveness_not_demonstrated")
        self.assertEqual(f.evidence["m2_slots"]["slots"][0]["routed_to"], "cpu")
        self.assertNotEqual(f.result, RESULT_COMPATIBLE)

    def test_absence_of_declared_restriction_is_not_compatibility(self):
        comps, profs = self._base([m2_slot("M2_1")])
        r = self.analyze(comps, profs)
        f = find(r, "storage_sata.m2_topology")[0]
        self.assertEqual(f.result, RESULT_REQUIRES_VERIFICATION)
        self.assertEqual(f.message_params["reason"], "m2_slot_inventory_exhaustiveness_not_demonstrated")
        self.assertNotEqual(f.result, RESULT_COMPATIBLE)

    def test_topology_slots_missing_insufficient_data(self):
        mb, m2, st = comp("Motherboard"), comp("Storage"), comp("Storage")
        r = self.analyze([mb, m2, st], [
            TechnicalProfile(component_id=mb.id, attributes=mb_profile(count=2, ids=["SATA1", "SATA2"])),
            TechnicalProfile(component_id=m2.id, attributes=storage("m2", "pcie", "nvme", "M", "2280")),
            TechnicalProfile(component_id=st.id, attributes=storage("2_5_in", "sata", "ata")),
        ])
        f = find(r, "storage_sata.m2_topology")[0]
        self.assertEqual(f.result, RESULT_INSUFFICIENT_DATA)
        self.assertIn("motherboard.m2_slots", f.missing_information)

    def test_unverified_slots_degrade_topology(self):
        comps, profs = self._base([m2_slot("M2_1", evidence="https://vendor/slot")])
        # replace slots collection attribute with unverified copy
        p = profs[0]
        profs[0] = TechnicalProfile(component_id=p.component_id, attributes=[ua("m2_slots", list(get_attr_value(p, "m2_slots")))])
        r = self.analyze(comps, profs)
        f = find(r, "storage_sata.m2_topology")[0]
        self.assertEqual(f.result, RESULT_REQUIRES_VERIFICATION)
        self.assertEqual(f.message_params["reason"], "m2_slot_data_not_verified")

    def test_topology_rule_absent_without_sata_or_m2_units(self):
        mb, m2 = comp("Motherboard"), comp("Storage")
        r = self.analyze([mb, m2], [
            TechnicalProfile(component_id=mb.id, attributes=mb_profile(count=0, slots=[m2_slot("M2_1")])),
            TechnicalProfile(component_id=m2.id, attributes=storage("m2", "pcie", "nvme", "M", "2280")),
        ])
        self.assertEqual(find(r, "storage_sata.m2_topology"), [])


class TestStorageDimensionsAndIntegration(T179Base):
    def test_bay_capacity_and_sata_ports_are_distinct_dimensions(self):
        mb, case, a, b = comp("Motherboard"), comp("Case"), comp("Storage"), comp("Storage")
        r = self.analyze([mb, case, a, b], [
            TechnicalProfile(component_id=mb.id, attributes=mb_profile(count=2)),
            TechnicalProfile(component_id=case.id, attributes=[va("bay_2_5_total", 1)]),
            TechnicalProfile(component_id=a.id, attributes=storage("2_5_in", "sata", "ata")),
            TechnicalProfile(component_id=b.id, attributes=storage("2_5_in", "sata", "ata")),
        ])
        bay = find(r, "storage_case.bay_2_5_capacity")[0]
        sata = find(r, "storage_sata.port_availability")[0]
        self.assertEqual(bay.result, RESULT_INCOMPATIBLE)
        self.assertEqual(sata.result, RESULT_COMPATIBLE)
        self.assertNotEqual(bay.rule_id, sata.rule_id)

    def test_m2_fit_positive_does_not_hide_topology(self):
        mb, m2, st = comp("Motherboard"), comp("Storage"), comp("Storage")
        r = self.analyze([mb, m2, st], [
            TechnicalProfile(component_id=mb.id, attributes=mb_profile(count=2, ids=["SATA1", "SATA2"], slots=[m2_slot("M2_1", disables=("SATA1",))])),
            TechnicalProfile(component_id=m2.id, attributes=storage("m2", "pcie", "nvme", "M", "2280")),
            TechnicalProfile(component_id=st.id, attributes=storage("2_5_in", "sata", "ata")),
        ])
        self.assertEqual(find(r, "storage_m2.fit")[0].result, RESULT_COMPATIBLE)
        self.assertEqual(find(r, "storage_sata.m2_topology")[0].result, RESULT_REQUIRES_VERIFICATION)

    def test_old_profiles_without_new_attributes_remain_valid(self):
        mb, st = comp("Motherboard"), comp("Storage")
        r = self.analyze([mb, st], [TechnicalProfile(component_id=mb.id, attributes=[va("form_factor", "ATX")]),
                                     TechnicalProfile(component_id=st.id, attributes=storage("2_5_in", "sata", "ata"))])
        f = find(r, "storage_sata.port_availability")[0]
        self.assertEqual(f.result, RESULT_INSUFFICIENT_DATA)

    def test_engine_version(self):
        self.assertEqual(ENGINE_RULESET_VERSION, "t17.12-v1")

    def test_global_result_not_compatible_from_sata_dimension_alone(self):
        mb, st = comp("Motherboard"), comp("Storage")
        r = self.analyze([mb, st], [TechnicalProfile(component_id=mb.id, attributes=mb_profile(count=2)),
                                     TechnicalProfile(component_id=st.id, attributes=storage("2_5_in", "sata", "ata"))])
        self.assertNotEqual(r.overall_result, RESULT_COMPATIBLE)
        self.assertIn("sata_port_assignment_not_evaluated", r.analysis_limitations)
        self.assertIn("additional_storage_controllers_not_evaluated", r.analysis_limitations)

    def test_purity_determinism_no_mutation(self):
        mb, st = comp("Motherboard"), comp("Storage")
        b = Build(name="t179", component_ids=[mb.id, st.id])
        comps = [mb, st]
        profs = [TechnicalProfile(component_id=mb.id, attributes=mb_profile(count=2)),
                 TechnicalProfile(component_id=st.id, attributes=storage("2_5_in", "sata", "ata"))]
        before = [p.to_dict() for p in profs]
        b_before = copy.deepcopy(b.__dict__)
        r1 = analyze_build_compatibility(b, comps, profs)
        r2 = analyze_build_compatibility(b, comps, profs)
        self.assertEqual([p.to_dict() for p in profs], before)
        self.assertEqual(b.__dict__, b_before)
        self.assertEqual([(f.rule_id, f.result) for f in r1.findings], [(f.rule_id, f.result) for f in r2.findings])

    def test_service_integration_no_compatibility_persistence(self):
        from pc_parts_organizer.service import InventoryService
        from pc_parts_organizer.storage import load_project_state
        svc = InventoryService()
        mb = svc.add_component("Motherboard", "M", "T179 MB", "", "")
        st = svc.add_component("Storage", "M", "T179 SSD", "", "")
        svc.set_technical_profile(TechnicalProfile(component_id=mb.id, attributes=mb_profile(count=2)))
        svc.set_technical_profile(TechnicalProfile(component_id=st.id, attributes=storage("2_5_in", "sata", "ata")))
        b = svc.add_build("T179 service")
        svc.add_component_to_build(b.id, mb.id)
        svc.add_component_to_build(b.id, st.id)
        before = load_project_state()
        rep = svc.analyze_build_compatibility(b.id)
        after = load_project_state()
        self.assertEqual(find(rep, "storage_sata.port_availability")[0].result, RESULT_COMPATIBLE)
        self.assertEqual(len(before.components), len(after.components))
        self.assertEqual(len(before.builds), len(after.builds))
        self.assertEqual(len(before.technical_profiles), len(after.technical_profiles))


def get_attr_value(profile, key):
    for a in profile.attributes:
        if a.key == key:
            return a.value
    return None


if __name__ == "__main__":
    unittest.main()
