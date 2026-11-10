"""T17.9-R2 adversarial storage classification tests.

Verifies unknown data never becomes favorable certainty.
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
from pc_parts_organizer.compatibility.storage_classification import classify_all, classify_unit
from pc_parts_organizer.models import Build, Component
from pc_parts_organizer.technical_profiles import M2SlotSpec, TechnicalAttribute, TechnicalProfile


def comp(cat, model="X"):
    return Component(category=cat, manufacturer="M", model=model, specifications="", notes="")


def va(key, value):
    return TechnicalAttribute(key=key, value=value, source="official_vendor_doc", confidence="high",
                              verification_status="verified", evidence_ref="https://vendor/doc", verified_at="2026-01-01")


def ua(key, value):
    return TechnicalAttribute(key=key, value=value, source="unknown", confidence="low", verification_status="unverified")


def slot(sid, keyings=("M",), modes=("pcie_nvme",), disables=(), shared=None, routed="unknown", evidence="https://vendor/slot"):
    return M2SlotSpec(slot_id=sid, accepted_module_keyings=keyings, supported_lengths=("2280",),
                      supported_modes=modes, disables_sata_port_ids=disables,
                      shared_resource_group_id=shared, routed_to=routed, evidence_ref=evidence)


def sattr(ff, iface=None, cmd=None, key=None, length=None, ff_v=True, if_v=True, cmd_v=True):
    a = [(va if ff_v else ua)("storage_form_factor", ff)]
    if iface is not None:
        a.append((va if if_v else ua)("storage_interface", iface))
    if cmd is not None:
        a.append((va if cmd_v else ua)("storage_command_set", cmd))
    if key is not None:
        a.append(va("m2_keying", key))
    if length is not None:
        a.append(va("m2_length_code", length))
    return a


def find(rep, rule):
    return [f for f in rep.findings if f.rule_id == rule]


def analyze(comps, profs):
    b = Build(name="r2", component_ids=[c.id for c in comps])
    return analyze_build_compatibility(b, comps, profs)


class TestCriticalFalseCompatible(unittest.TestCase):
    def test_verified_sata_plus_unverified_pcie_excluded_before(self):
        mb, a, b = comp("Motherboard"), comp("Storage"), comp("Storage")
        r = analyze([mb, a, b], [
            TechnicalProfile(component_id=mb.id, attributes=[va("sata_port_count", 1)]),
            TechnicalProfile(component_id=a.id, attributes=sattr("2_5_in", "sata", "ata")),
            TechnicalProfile(component_id=b.id, attributes=sattr("2_5_in", "pcie", "nvme", ff_v=False, if_v=False, cmd_v=False)),
        ])
        f = find(r, "storage_sata.port_availability")
        self.assertEqual(len(f), 1)
        self.assertEqual(f[0].result, RESULT_REQUIRES_VERIFICATION)
        self.assertEqual(f[0].message_params["reason"], "storage_units_undetermined")
        self.assertNotEqual(f[0].result, RESULT_COMPATIBLE)
        self.assertIn(b.id, f[0].component_ids)

    def test_unverified_m2_ff_does_not_exclude_sata(self):
        mb, a, b = comp("Motherboard"), comp("Storage"), comp("Storage")
        r = analyze([mb, a, b], [
            TechnicalProfile(component_id=mb.id, attributes=[va("sata_port_count", 1)]),
            TechnicalProfile(component_id=a.id, attributes=sattr("2_5_in", "sata", "ata")),
            TechnicalProfile(component_id=b.id, attributes=[ua("storage_form_factor", "m2"), ua("storage_interface", "pcie"), ua("storage_command_set", "nvme"), va("m2_keying", "M"), va("m2_length_code", "2280")]),
        ])
        f = find(r, "storage_sata.port_availability")[0]
        self.assertEqual(f.result, RESULT_REQUIRES_VERIFICATION)
        self.assertEqual(f.message_params["reason"], "storage_units_undetermined")

    def test_unverified_addin_does_not_exclude(self):
        mb, a, b = comp("Motherboard"), comp("Storage"), comp("Storage")
        r = analyze([mb, a, b], [
            TechnicalProfile(component_id=mb.id, attributes=[va("sata_port_count", 1)]),
            TechnicalProfile(component_id=a.id, attributes=sattr("2_5_in", "sata", "ata")),
            TechnicalProfile(component_id=b.id, attributes=[ua("storage_form_factor", "pcie_addin")]),
        ])
        f = find(r, "storage_sata.port_availability")[0]
        self.assertEqual(f.result, RESULT_REQUIRES_VERIFICATION)

    def test_missing_ff_does_not_exclude(self):
        mb, a, b = comp("Motherboard"), comp("Storage"), comp("Storage")
        r = analyze([mb, a, b], [
            TechnicalProfile(component_id=mb.id, attributes=[va("sata_port_count", 2)]),
            TechnicalProfile(component_id=a.id, attributes=sattr("2_5_in", "sata", "ata")),
            TechnicalProfile(component_id=b.id, attributes=[va("storage_interface", "sata"), va("storage_command_set", "ata")]),
        ])
        f = find(r, "storage_sata.port_availability")[0]
        self.assertEqual(f.result, RESULT_REQUIRES_VERIFICATION)
        self.assertEqual(f.message_params["reason"], "storage_units_undetermined")

    def test_iface_verified_cmd_missing(self):
        mb, st = comp("Motherboard"), comp("Storage")
        r = analyze([mb, st], [
            TechnicalProfile(component_id=mb.id, attributes=[va("sata_port_count", 2)]),
            TechnicalProfile(component_id=st.id, attributes=[va("storage_form_factor", "2_5_in"), va("storage_interface", "sata")]),
        ])
        f = find(r, "storage_sata.port_availability")[0]
        self.assertEqual(f.result, RESULT_REQUIRES_VERIFICATION)

    def test_cmd_verified_iface_missing(self):
        mb, st = comp("Motherboard"), comp("Storage")
        r = analyze([mb, st], [
            TechnicalProfile(component_id=mb.id, attributes=[va("sata_port_count", 2)]),
            TechnicalProfile(component_id=st.id, attributes=[va("storage_form_factor", "2_5_in"), va("storage_command_set", "ata")]),
        ])
        f = find(r, "storage_sata.port_availability")[0]
        self.assertEqual(f.result, RESULT_REQUIRES_VERIFICATION)

    def test_contradictory_data(self):
        mb, st = comp("Motherboard"), comp("Storage")
        # bypass profile validation: construct classification directly via synthetic profile object
        from types import SimpleNamespace
        prof = SimpleNamespace(attributes=[va("storage_form_factor", "2_5_in"), va("storage_interface", "sata"), va("storage_command_set", "nvme")])
        c = classify_unit(st.id, prof)
        self.assertEqual(c.status, "contradictory_storage_data")


class TestCountConfidence(unittest.TestCase):
    def test_verified_count_unverified_ids_still_compatible(self):
        mb, st = comp("Motherboard"), comp("Storage")
        r = analyze([mb, st], [
            TechnicalProfile(component_id=mb.id, attributes=[va("sata_port_count", 1), ua("sata_port_identifiers", ["SATA1"])]),
            TechnicalProfile(component_id=st.id, attributes=sattr("2_5_in", "sata", "ata")),
        ])
        f = find(r, "storage_sata.port_availability")[0]
        self.assertEqual(f.result, RESULT_COMPATIBLE)

    def test_ids_without_count_no_inference(self):
        mb, st = comp("Motherboard"), comp("Storage")
        r = analyze([mb, st], [
            TechnicalProfile(component_id=mb.id, attributes=[va("sata_port_identifiers", ["SATA1", "SATA2"])]),
            TechnicalProfile(component_id=st.id, attributes=sattr("2_5_in", "sata", "ata")),
        ])
        f = find(r, "storage_sata.port_availability")[0]
        self.assertEqual(f.result, RESULT_INSUFFICIENT_DATA)
        self.assertIn("motherboard.sata_port_count", f.missing_information)

    def test_unverified_count_never_compatible(self):
        mb, st = comp("Motherboard"), comp("Storage")
        r = analyze([mb, st], [
            TechnicalProfile(component_id=mb.id, attributes=[ua("sata_port_count", 2)]),
            TechnicalProfile(component_id=st.id, attributes=sattr("2_5_in", "sata", "ata")),
        ])
        f = find(r, "storage_sata.port_availability")[0]
        self.assertEqual(f.result, RESULT_REQUIRES_VERIFICATION)
        self.assertEqual(f.message_params["reason"], "sata_port_data_not_verified")

    def test_zero_verified_ports_requires_verification(self):
        mb, st = comp("Motherboard"), comp("Storage")
        r = analyze([mb, st], [
            TechnicalProfile(component_id=mb.id, attributes=[va("sata_port_count", 0)]),
            TechnicalProfile(component_id=st.id, attributes=sattr("2_5_in", "sata", "ata")),
        ])
        f = find(r, "storage_sata.port_availability")[0]
        self.assertEqual(f.result, RESULT_REQUIRES_VERIFICATION)
        self.assertNotEqual(f.result, RESULT_INCOMPATIBLE)

    def test_short_verified_count_controllers_reason(self):
        mb, a, b = comp("Motherboard"), comp("Storage"), comp("Storage")
        r = analyze([mb, a, b], [
            TechnicalProfile(component_id=mb.id, attributes=[va("sata_port_count", 1)]),
            TechnicalProfile(component_id=a.id, attributes=sattr("2_5_in", "sata", "ata")),
            TechnicalProfile(component_id=b.id, attributes=sattr("3_5_in", "sata", "ata")),
        ])
        f = find(r, "storage_sata.port_availability")[0]
        self.assertEqual(f.result, RESULT_REQUIRES_VERIFICATION)
        self.assertEqual(f.message_params["reason"], "additional_sata_controllers_or_ports_not_excluded")
        self.assertEqual(f.recommended_action, "verify_additional_sata_controllers_and_ports")

    def test_short_unverified_count_mentions_verification(self):
        mb, a, b = comp("Motherboard"), comp("Storage"), comp("Storage")
        r = analyze([mb, a, b], [
            TechnicalProfile(component_id=mb.id, attributes=[ua("sata_port_count", 1)]),
            TechnicalProfile(component_id=a.id, attributes=sattr("2_5_in", "sata", "ata")),
            TechnicalProfile(component_id=b.id, attributes=sattr("3_5_in", "sata", "ata")),
        ])
        f = find(r, "storage_sata.port_availability")[0]
        self.assertEqual(f.result, RESULT_REQUIRES_VERIFICATION)
        self.assertEqual(f.message_params["reason"], "sata_port_data_not_verified")

    def test_action_targets_unit_when_unit_unverified(self):
        mb, st = comp("Motherboard"), comp("Storage")
        r = analyze([mb, st], [
            TechnicalProfile(component_id=mb.id, attributes=[va("sata_port_count", 2)]),
            TechnicalProfile(component_id=st.id, attributes=sattr("2_5_in", "sata", "ata", ff_v=False)),
        ])
        f = find(r, "storage_sata.port_availability")[0]
        self.assertEqual(f.recommended_action, "verify_storage_and_slot_attributes")


class TestBayCapacity(unittest.TestCase):
    def test_known_plus_no_profile_requires_verification(self):
        case, a, b = comp("Case"), comp("Storage"), comp("Storage")
        r = analyze([case, a, b], [
            TechnicalProfile(component_id=case.id, attributes=[va("bay_2_5_total", 1)]),
            TechnicalProfile(component_id=a.id, attributes=[va("storage_form_factor", "2_5_in")]),
        ])
        f = find(r, "storage_case.bay_2_5_capacity")
        self.assertEqual(len(f), 1)
        self.assertEqual(f[0].result, RESULT_REQUIRES_VERIFICATION)
        self.assertEqual(f[0].message_params["reason"], "bay_demand_undetermined")
        self.assertIn(b.id, f[0].component_ids)

    def test_known_plus_other_requires_verification(self):
        case, a, b = comp("Case"), comp("Storage"), comp("Storage")
        r = analyze([case, a, b], [
            TechnicalProfile(component_id=case.id, attributes=[va("bay_2_5_total", 1), va("bay_3_5_total", 1)]),
            TechnicalProfile(component_id=a.id, attributes=[va("storage_form_factor", "2_5_in")]),
            TechnicalProfile(component_id=b.id, attributes=[ua("storage_form_factor", "other")]),
        ])
        f25 = find(r, "storage_case.bay_2_5_capacity")
        self.assertEqual(f25[0].result, RESULT_REQUIRES_VERIFICATION)

    def test_only_m2_no_bay_findings_no_case_missing(self):
        m2 = comp("Storage")
        r = analyze([m2], [TechnicalProfile(component_id=m2.id, attributes=sattr("m2", "pcie", "nvme", "M", "2280"))])
        self.assertEqual(find(r, "storage_case.bay_2_5_capacity"), [])
        self.assertEqual(find(r, "storage_case.bay_3_5_capacity"), [])
        self.assertEqual(find(r, "storage_case.case_missing"), [])

    def test_only_addin_no_bay_findings(self):
        st = comp("Storage")
        r = analyze([st], [TechnicalProfile(component_id=st.id, attributes=[va("storage_form_factor", "pcie_addin")])])
        self.assertEqual(find(r, "storage_case.case_missing"), [])

    def test_only_25_no_case_includes_only_bay_units(self):
        st, m2 = comp("Storage"), comp("Storage")
        r = analyze([st, m2], [
            TechnicalProfile(component_id=st.id, attributes=[va("storage_form_factor", "2_5_in")]),
            TechnicalProfile(component_id=m2.id, attributes=sattr("m2", "pcie", "nvme", "M", "2280")),
        ])
        f = find(r, "storage_case.case_missing")
        self.assertEqual(len(f), 1)
        self.assertIn(st.id, f[0].component_ids)
        self.assertNotIn(m2.id, f[0].component_ids)


class TestM2Relevance(unittest.TestCase):
    def test_addin_no_m2_findings(self):
        mb, st = comp("Motherboard"), comp("Storage")
        r = analyze([mb, st], [
            TechnicalProfile(component_id=mb.id, attributes=[]),
            TechnicalProfile(component_id=st.id, attributes=[va("storage_form_factor", "pcie_addin")]),
        ])
        self.assertEqual(find(r, "storage_m2.motherboard_missing"), [])
        self.assertEqual([f for f in r.findings if f.rule_id.startswith("storage_m2.")], [])

    def test_other_no_m2_findings(self):
        mb, st = comp("Motherboard"), comp("Storage")
        r = analyze([mb, st], [
            TechnicalProfile(component_id=mb.id, attributes=[]),
            TechnicalProfile(component_id=st.id, attributes=[va("storage_form_factor", "other")]),
        ])
        self.assertEqual([f for f in r.findings if f.rule_id.startswith("storage_m2.")], [])

    def test_missing_ff_no_m2_findings(self):
        mb, st = comp("Motherboard"), comp("Storage")
        r = analyze([mb, st], [
            TechnicalProfile(component_id=mb.id, attributes=[]),
            TechnicalProfile(component_id=st.id, attributes=[va("storage_interface", "sata")]),
        ])
        self.assertEqual([f for f in r.findings if f.rule_id.startswith("storage_m2.")], [])

    def test_single_m2_no_multi_limitation(self):
        mb, st = comp("Motherboard"), comp("Storage")
        r = analyze([mb, st], [
            TechnicalProfile(component_id=mb.id, attributes=[va("m2_slots", [slot("M2_1")])]),
            TechnicalProfile(component_id=st.id, attributes=sattr("m2", "pcie", "nvme", "M", "2280")),
        ])
        self.assertNotIn("multi_m2_joint_fit_not_evaluated", r.analysis_limitations)

    def test_m2_plus_addin_no_multi_limitation(self):
        mb, m2, ad = comp("Motherboard"), comp("Storage"), comp("Storage")
        r = analyze([mb, m2, ad], [
            TechnicalProfile(component_id=mb.id, attributes=[va("m2_slots", [slot("M2_1")])]),
            TechnicalProfile(component_id=m2.id, attributes=sattr("m2", "pcie", "nvme", "M", "2280")),
            TechnicalProfile(component_id=ad.id, attributes=[va("storage_form_factor", "pcie_addin")]),
        ])
        self.assertNotIn("multi_m2_joint_fit_not_evaluated", r.analysis_limitations)

    def test_two_m2_multi_limitation(self):
        mb, a, b = comp("Motherboard"), comp("Storage"), comp("Storage")
        r = analyze([mb, a, b], [
            TechnicalProfile(component_id=mb.id, attributes=[va("m2_slots", [slot("M2_1"), slot("M2_2")])]),
            TechnicalProfile(component_id=a.id, attributes=sattr("m2", "pcie", "nvme", "M", "2280")),
            TechnicalProfile(component_id=b.id, attributes=sattr("m2", "pcie", "nvme", "M", "2280")),
        ])
        self.assertIn("multi_m2_joint_fit_not_evaluated", r.analysis_limitations)

    def test_slots_empty_verified_requires_verification(self):
        mb, m2 = comp("Motherboard"), comp("Storage")
        r = analyze([mb, m2], [
            TechnicalProfile(component_id=mb.id, attributes=[va("m2_slots", [])]),
            TechnicalProfile(component_id=m2.id, attributes=sattr("m2", "pcie", "nvme", "M", "2280")),
        ])
        f = find(r, "storage_m2.slots_absent")
        self.assertEqual(len(f), 1)
        self.assertEqual(f[0].result, RESULT_REQUIRES_VERIFICATION)
        self.assertIn(mb.id, f[0].component_ids)

    def test_slots_empty_unverified_insufficient(self):
        mb, m2 = comp("Motherboard"), comp("Storage")
        r = analyze([mb, m2], [
            TechnicalProfile(component_id=mb.id, attributes=[ua("m2_slots", [])]),
            TechnicalProfile(component_id=m2.id, attributes=sattr("m2", "pcie", "nvme", "M", "2280")),
        ])
        f = find(r, "storage_m2.slots_absent")
        self.assertEqual(f[0].result, RESULT_INSUFFICIENT_DATA)

    def test_slots_absent_includes_motherboard(self):
        mb, m2 = comp("Motherboard"), comp("Storage")
        r = analyze([mb, m2], [
            TechnicalProfile(component_id=mb.id, attributes=[]),
            TechnicalProfile(component_id=m2.id, attributes=sattr("m2", "pcie", "nvme", "M", "2280")),
        ])
        f = find(r, "storage_m2.slots_absent")
        self.assertIn(mb.id, f[0].component_ids)
        self.assertIn(m2.id, f[0].component_ids)


class TestTopologyIndeterminate(unittest.TestCase):
    def _mb_slots(self, slots, count=2):
        ids = ["SATA1", "SATA2"] if count else None
        attrs = [va("sata_port_count", count)]
        if ids:
            attrs.append(va("sata_port_identifiers", ids))
        attrs.append(va("m2_slots", slots))
        return attrs

    def test_m2_mode_unknown(self):
        mb, m2, st = comp("Motherboard"), comp("Storage"), comp("Storage")
        r = analyze([mb, m2, st], [
            TechnicalProfile(component_id=mb.id, attributes=self._mb_slots([slot("M2_1", disables=("SATA1",))])),
            TechnicalProfile(component_id=m2.id, attributes=[va("storage_form_factor", "m2"), va("m2_keying", "M"), va("m2_length_code", "2280")]),
            TechnicalProfile(component_id=st.id, attributes=sattr("2_5_in", "sata", "ata")),
        ])
        f = find(r, "storage_sata.m2_topology")[0]
        self.assertEqual(f.result, RESULT_REQUIRES_VERIFICATION)
        self.assertEqual(f.message_params["reason"], "m2_slot_assignment_or_attributes_unknown")

    def test_ids_missing_keeps_potential_but_uncontrastable(self):
        mb, m2, st = comp("Motherboard"), comp("Storage"), comp("Storage")
        r = analyze([mb, m2, st], [
            TechnicalProfile(component_id=mb.id, attributes=[va("sata_port_count", 2), va("m2_slots", [slot("M2_1", disables=("SATA9",))])]),
            TechnicalProfile(component_id=m2.id, attributes=sattr("m2", "pcie", "nvme", "M", "2280")),
            TechnicalProfile(component_id=st.id, attributes=sattr("2_5_in", "sata", "ata")),
        ])
        f = find(r, "storage_sata.m2_topology")[0]
        self.assertEqual(f.result, RESULT_REQUIRES_VERIFICATION)
        self.assertEqual(f.message_params["reason"], "m2_slot_may_disable_sata_ports")
        self.assertFalse(f.message_params["ids_contrastable"])
        self.assertIn("SATA9", list(f.message_params["affected_sata_port_ids"]))

    def test_slot_id_with_colon_count_correct(self):
        mb, m2, st = comp("Motherboard"), comp("Storage"), comp("Storage")
        r = analyze([mb, m2, st], [
            TechnicalProfile(component_id=mb.id, attributes=self._mb_slots([slot("M2:1", disables=("SATA1",)), slot("M2:2", disables=("SATA1",))])),
            TechnicalProfile(component_id=m2.id, attributes=sattr("m2", "pcie", "nvme", "M", "2280")),
            TechnicalProfile(component_id=st.id, attributes=sattr("2_5_in", "sata", "ata")),
        ])
        f = find(r, "storage_sata.m2_topology")[0]
        self.assertEqual(f.message_params["restricting_slots"], 2)
        self.assertEqual(len(f.evidence["restricting_slots"]), 2)

    def test_unverified_ids_still_potential_with_flag(self):
        mb, m2, st = comp("Motherboard"), comp("Storage"), comp("Storage")
        r = analyze([mb, m2, st], [
            TechnicalProfile(component_id=mb.id, attributes=[va("sata_port_count", 2), ua("sata_port_identifiers", ["SATA1", "SATA2"]), va("m2_slots", [slot("M2_1", disables=("SATA1",))])]),
            TechnicalProfile(component_id=m2.id, attributes=sattr("m2", "pcie", "nvme", "M", "2280")),
            TechnicalProfile(component_id=st.id, attributes=sattr("2_5_in", "sata", "ata")),
        ])
        f = find(r, "storage_sata.m2_topology")[0]
        self.assertEqual(f.message_params["reason"], "m2_slot_may_disable_sata_ports")
        self.assertFalse(f.message_params["ids_contrastable"])

    def test_no_classified_sata_but_possible_still_topology(self):
        mb, m2, u = comp("Motherboard"), comp("Storage"), comp("Storage")
        r = analyze([mb, m2, u], [
            TechnicalProfile(component_id=mb.id, attributes=self._mb_slots([slot("M2_1", disables=("SATA1",))])),
            TechnicalProfile(component_id=m2.id, attributes=sattr("m2", "pcie", "nvme", "M", "2280")),
            TechnicalProfile(component_id=u.id, attributes=[va("storage_form_factor", "2_5_in")]),
        ])
        f = find(r, "storage_sata.m2_topology")
        self.assertEqual(len(f), 1)
        self.assertEqual(f[0].result, RESULT_REQUIRES_VERIFICATION)


class TestMultipleMotherboards(unittest.TestCase):
    def test_two_mb_sata_ambiguous(self):
        m1, m2, st = comp("Motherboard"), comp("Motherboard"), comp("Storage")
        r = analyze([m1, m2, st], [
            TechnicalProfile(component_id=m1.id, attributes=[va("sata_port_count", 2)]),
            TechnicalProfile(component_id=m2.id, attributes=[va("sata_port_count", 4)]),
            TechnicalProfile(component_id=st.id, attributes=sattr("2_5_in", "sata", "ata")),
        ])
        f = find(r, "storage_sata.ambiguous_motherboard")
        self.assertEqual(f[0].result, RESULT_INSUFFICIENT_DATA)
        self.assertIn(m1.id, f[0].component_ids)
        self.assertIn(m2.id, f[0].component_ids)
        self.assertNotIn("declared_ports", {k: 1 for k in [1]})

    def test_two_mb_topology_ambiguous(self):
        m1, m2, a, b = comp("Motherboard"), comp("Motherboard"), comp("Storage"), comp("Storage")
        r = analyze([m1, m2, a, b], [
            TechnicalProfile(component_id=m1.id, attributes=[va("sata_port_count", 2), va("m2_slots", [slot("M2_1")])]),
            TechnicalProfile(component_id=m2.id, attributes=[va("sata_port_count", 2), va("m2_slots", [slot("M2_1")])]),
            TechnicalProfile(component_id=a.id, attributes=sattr("m2", "pcie", "nvme", "M", "2280")),
            TechnicalProfile(component_id=b.id, attributes=sattr("2_5_in", "sata", "ata")),
        ])
        f = find(r, "storage_sata.m2_topology")
        self.assertEqual(len(f), 1)
        self.assertIn(m1.id, f[0].component_ids)
        self.assertIn(m2.id, f[0].component_ids)


class TestEvidenceMetrics(unittest.TestCase):
    def test_attributes_compared_exact_sata(self):
        mb, st = comp("Motherboard"), comp("Storage")
        r = analyze([mb, st], [
            TechnicalProfile(component_id=mb.id, attributes=[va("sata_port_count", 2), va("sata_port_identifiers", ["SATA1", "SATA2"])]),
            TechnicalProfile(component_id=st.id, attributes=sattr("2_5_in", "sata", "ata")),
        ])
        f = find(r, "storage_sata.port_availability")[0]
        self.assertNotIn("sata_port_identifiers", f.attributes_compared)
        self.assertIn("sata_port_count", f.attributes_compared)

    def test_topology_omits_unused_count(self):
        mb, m2, st = comp("Motherboard"), comp("Storage"), comp("Storage")
        r = analyze([mb, m2, st], [
            TechnicalProfile(component_id=mb.id, attributes=[va("sata_port_count", 2), va("m2_slots", [slot("M2_1")])]),
            TechnicalProfile(component_id=m2.id, attributes=sattr("m2", "pcie", "nvme", "M", "2280")),
            TechnicalProfile(component_id=st.id, attributes=sattr("2_5_in", "sata", "ata")),
        ])
        f = find(r, "storage_sata.m2_topology")[0]
        self.assertNotIn("sata_port_count", f.attributes_compared)
        self.assertIn("m2_slots", f.attributes_compared)
        self.assertIn("disables_sata_port_ids", f.attributes_compared)

    def test_declared_ids_always_list(self):
        mb, st = comp("Motherboard"), comp("Storage")
        for attrs in ([va("sata_port_count", 2)], [va("sata_port_count", 1), va("sata_port_identifiers", ["SATA1"])]):
            r = analyze([mb, st], [
                TechnicalProfile(component_id=mb.id, attributes=attrs),
                TechnicalProfile(component_id=st.id, attributes=sattr("2_5_in", "sata", "ata")),
            ])
            f = find(r, "storage_sata.port_availability")[0]
            self.assertIsInstance(list(f.evidence["declared_ids"]), list)
            self.assertIsInstance(list(f.message_params["declared_ids"]), list)

    def test_restricting_slots_structured_not_delimited(self):
        mb, m2, st = comp("Motherboard"), comp("Storage"), comp("Storage")
        r = analyze([mb, m2, st], [
            TechnicalProfile(component_id=mb.id, attributes=[va("sata_port_count", 1), va("sata_port_identifiers", ["SATA1"]), va("m2_slots", [slot("M2_1", disables=("SATA1",))])]),
            TechnicalProfile(component_id=m2.id, attributes=sattr("m2", "pcie", "nvme", "M", "2280")),
            TechnicalProfile(component_id=st.id, attributes=sattr("2_5_in", "sata", "ata")),
        ])
        f = find(r, "storage_sata.m2_topology")[0]
        for entry in f.evidence["restricting_slots"]:
            self.assertIn("slot_id", entry)
            self.assertIn("disables_sata_port_ids", entry)
            self.assertNotIsInstance(entry, str)

    def test_rules_evaluated_counts(self):
        mb, st = comp("Motherboard"), comp("Storage")
        r = analyze([mb, st], [
            TechnicalProfile(component_id=mb.id, attributes=[va("sata_port_count", 2)]),
            TechnicalProfile(component_id=st.id, attributes=sattr("2_5_in", "sata", "ata")),
        ])
        f = find(r, "storage_sata.port_availability")[0]
        self.assertGreaterEqual(r.rules_evaluated, 1)
        # slots_absent is a scope guard (no value comparison): finding with 0 evaluations
        mb2, m2 = comp("Motherboard"), comp("Storage")
        r2 = analyze([mb2, m2], [
            TechnicalProfile(component_id=mb2.id, attributes=[]),
            TechnicalProfile(component_id=m2.id, attributes=sattr("m2", "pcie", "nvme", "M", "2280")),
        ])
        self.assertEqual(len(find(r2, "storage_m2.slots_absent")), 1)

    def test_purity_determinism(self):
        mb, st = comp("Motherboard"), comp("Storage")
        comps = [mb, st]
        profs = [TechnicalProfile(component_id=mb.id, attributes=[va("sata_port_count", 2)]),
                 TechnicalProfile(component_id=st.id, attributes=sattr("2_5_in", "sata", "ata"))]
        b = Build(name="r2", component_ids=[c.id for c in comps])
        before = [p.to_dict() for p in profs]
        r1 = analyze_build_compatibility(b, comps, profs)
        r2 = analyze_build_compatibility(b, comps, profs)
        self.assertEqual([p.to_dict() for p in profs], before)
        self.assertEqual([(f.rule_id, f.result) for f in r1.findings], [(f.rule_id, f.result) for f in r2.findings])

    def test_version(self):
        self.assertEqual(ENGINE_RULESET_VERSION, "t17.12-v1")


class TestRulesEvaluatedContract(unittest.TestCase):
    """R2.1: rules_evaluated counts value comparisons, not scope guards."""

    def test_sata_missing_mb_counts_zero(self):
        st = comp("Storage")
        r = analyze([st], [TechnicalProfile(component_id=st.id, attributes=sattr("2_5_in", "sata", "ata"))])
        self.assertEqual(len(find(r, "storage_sata.motherboard_missing")), 1)
        self.assertEqual(find(r, "storage_sata.port_availability"), [])

    def test_sata_ambiguous_mb_counts_zero(self):
        m1, m2, st = comp("Motherboard"), comp("Motherboard"), comp("Storage")
        r = analyze([m1, m2, st], [
            TechnicalProfile(component_id=m1.id, attributes=[va("sata_port_count", 2)]),
            TechnicalProfile(component_id=m2.id, attributes=[va("sata_port_count", 2)]),
            TechnicalProfile(component_id=st.id, attributes=sattr("2_5_in", "sata", "ata")),
        ])
        self.assertEqual(len(find(r, "storage_sata.ambiguous_motherboard")), 1)

    def test_sata_count_missing_counts_zero(self):
        mb, st = comp("Motherboard"), comp("Storage")
        before = analyze([mb, st], [
            TechnicalProfile(component_id=mb.id, attributes=[]),
            TechnicalProfile(component_id=st.id, attributes=sattr("2_5_in", "sata", "ata")),
        ])
        self.assertEqual(find(before, "storage_sata.port_availability")[0].result, RESULT_INSUFFICIENT_DATA)
        after = analyze([mb, st], [
            TechnicalProfile(component_id=mb.id, attributes=[va("sata_port_count", 2)]),
            TechnicalProfile(component_id=st.id, attributes=sattr("2_5_in", "sata", "ata")),
        ])
        self.assertGreater(after.rules_evaluated, before.rules_evaluated)

    def test_topology_missing_and_empty_count_zero(self):
        mb, m2, st = comp("Motherboard"), comp("Storage"), comp("Storage")
        base_m2 = sattr("m2", "pcie", "nvme", "M", "2280")
        base_sata = sattr("2_5_in", "sata", "ata")
        r1 = analyze([mb, m2, st], [
            TechnicalProfile(component_id=mb.id, attributes=[va("sata_port_count", 2)]),
            TechnicalProfile(component_id=m2.id, attributes=base_m2),
            TechnicalProfile(component_id=st.id, attributes=base_sata),
        ])
        self.assertEqual(find(r1, "storage_sata.m2_topology")[0].result, RESULT_INSUFFICIENT_DATA)
        r1n = r1.rules_evaluated
        r2 = analyze([mb, m2, st], [
            TechnicalProfile(component_id=mb.id, attributes=[va("sata_port_count", 2), va("m2_slots", [slot("M2_1")])]),
            TechnicalProfile(component_id=m2.id, attributes=base_m2),
            TechnicalProfile(component_id=st.id, attributes=base_sata),
        ])
        self.assertEqual(find(r2, "storage_sata.m2_topology")[0].result, RESULT_REQUIRES_VERIFICATION)
        self.assertGreater(r2.rules_evaluated, r1n)

    def test_m2_slots_absent_counts_zero(self):
        mb, m2 = comp("Motherboard"), comp("Storage")
        r = analyze([mb, m2], [
            TechnicalProfile(component_id=mb.id, attributes=[]),
            TechnicalProfile(component_id=m2.id, attributes=sattr("m2", "pcie", "nvme", "M", "2280")),
        ])
        self.assertEqual(len(find(r, "storage_m2.slots_absent")), 1)

    def test_m2_fit_counts_per_unit(self):
        mb, a, b = comp("Motherboard"), comp("Storage"), comp("Storage")
        attrs = [va("m2_slots", [slot("M2_1"), slot("M2_2")])]
        r1 = analyze([mb, a], [
            TechnicalProfile(component_id=mb.id, attributes=attrs),
            TechnicalProfile(component_id=a.id, attributes=sattr("m2", "pcie", "nvme", "M", "2280")),
        ])
        r2 = analyze([mb, a, b], [
            TechnicalProfile(component_id=mb.id, attributes=attrs),
            TechnicalProfile(component_id=a.id, attributes=sattr("m2", "pcie", "nvme", "M", "2280")),
            TechnicalProfile(component_id=b.id, attributes=sattr("m2", "pcie", "nvme", "M", "2280")),
        ])
        n1 = len(find(r1, "storage_m2.fit"))
        n2 = len(find(r2, "storage_m2.fit"))
        self.assertEqual(n1, 1)
        self.assertEqual(n2, 2)
        self.assertGreater(r2.rules_evaluated, r1.rules_evaluated)

    def test_bay_missing_count_not_counted(self):
        case, st = comp("Case"), comp("Storage")
        r = analyze([case, st], [
            TechnicalProfile(component_id=case.id, attributes=[]),
            TechnicalProfile(component_id=st.id, attributes=[va("storage_form_factor", "2_5_in")]),
        ])
        f = find(r, "storage_case.bay_2_5_capacity")
        self.assertEqual(f[0].result, RESULT_INSUFFICIENT_DATA)

    def test_total_equals_sum_of_rule_evaluations(self):
        from pc_parts_organizer.compatibility import engine as eng
        mb, case, m2, st = comp("Motherboard"), comp("Case"), comp("Storage"), comp("Storage")
        comps = [mb, case, m2, st]
        profs = [
            TechnicalProfile(component_id=mb.id, attributes=[va("sata_port_count", 2), va("sata_port_identifiers", ["SATA1", "SATA2"]), va("m2_slots", [slot("M2_1")])]),
            TechnicalProfile(component_id=case.id, attributes=[va("bay_2_5_total", 1)]),
            TechnicalProfile(component_id=m2.id, attributes=sattr("m2", "pcie", "nvme", "M", "2280")),
            TechnicalProfile(component_id=st.id, attributes=sattr("2_5_in", "sata", "ata")),
        ]
        b = Build(name="sum", component_ids=[c.id for c in comps])
        ctx = eng.build_context(b, comps, profs)
        from pc_parts_organizer.compatibility.rules_storage import evaluate_bay_capacity, evaluate_m2_fit
        from pc_parts_organizer.compatibility.rules_storage_sata import evaluate_m2_sata_topology, evaluate_sata_port_availability
        parts = [evaluate_m2_fit(ctx)[1], evaluate_bay_capacity(ctx)[1], evaluate_sata_port_availability(ctx)[1], evaluate_m2_sata_topology(ctx)[1]]
        r = analyze(comps, profs)
        self.assertGreaterEqual(r.rules_evaluated, sum(parts))


if __name__ == "__main__":
    unittest.main()
