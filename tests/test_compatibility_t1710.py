"""T17.10 engine completeness tests: M.2/PSU negatives on complete inventories."""
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
    analyze_build_compatibility,
)
from pc_parts_organizer.models import Build, Component
from pc_parts_organizer.technical_profiles import M2SlotSpec, TechnicalAttribute, TechnicalProfile


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


SCOPE_M2 = "All physical M.2 slots of the board model/revision"
SCOPE_PSU = "All cable assemblies included with the PSU variant"
SCOPE_SATA = "All integrated SATA port identifiers of the board"


def slot(sid, keyings=("M",), modes=("pcie_nvme",), disables=(), evidence="https://vendor/slot"):
    return M2SlotSpec(slot_id=sid, accepted_module_keyings=keyings, supported_lengths=("2280",),
                      supported_modes=modes, disables_sata_port_ids=disables,
                      evidence_ref=evidence)


def find(rep, rule):
    return [f for f in rep.findings if f.rule_id == rule]


def analyze(comps, profs):
    b = Build(name="t1710", component_ids=[c.id for c in comps])
    return analyze_build_compatibility(b, comps, profs)


def m2_attrs(key="M", length="2280", iface="pcie", cmd="nvme"):
    return [va("storage_form_factor", "m2"), va("storage_interface", iface),
            va("storage_command_set", cmd), va("m2_keying", key), va("m2_length_code", length)]


class TestM2Complete(unittest.TestCase):
    def _mb(self, slots, completeness="complete", verified=True):
        fn = va if verified else ua
        kw = {} if completeness == "unknown" else {"collection_completeness": completeness, "completeness_scope": SCOPE_M2}
        return fn("m2_slots", slots, **kw)

    def test_complete_with_fit_compatible(self):
        mb, st = comp("Motherboard"), comp("Storage")
        r = analyze([mb, st], [
            TechnicalProfile(component_id=mb.id, attributes=[self._mb([slot("M2_1")])]),
            TechnicalProfile(component_id=st.id, attributes=m2_attrs()),
        ])
        self.assertEqual(find(r, "storage_m2.fit")[0].result, RESULT_COMPATIBLE)

    def test_complete_without_fit_incompatible(self):
        mb, st = comp("Motherboard"), comp("Storage")
        # slot only supports 2260, unit is 2280, both verified, complete collection
        sl = M2SlotSpec(slot_id="M2_1", accepted_module_keyings=("M",), supported_lengths=("2260",),
                        supported_modes=("pcie_nvme",), evidence_ref="https://vendor/slot")
        r = analyze([mb, st], [
            TechnicalProfile(component_id=mb.id, attributes=[self._mb([sl])]),
            TechnicalProfile(component_id=st.id, attributes=m2_attrs()),
        ])
        f = find(r, "storage_m2.fit")
        self.assertEqual(f[0].result, RESULT_INCOMPATIBLE)
        self.assertEqual(f[0].severity, "critical")

    def test_complete_empty_incompatible(self):
        mb, st = comp("Motherboard"), comp("Storage")
        r = analyze([mb, st], [
            TechnicalProfile(component_id=mb.id, attributes=[self._mb([])]),
            TechnicalProfile(component_id=st.id, attributes=m2_attrs()),
        ])
        f = find(r, "storage_m2.slots_absent")
        self.assertEqual(f[0].result, RESULT_INCOMPATIBLE)

    def test_partial_without_fit_requires_verification(self):
        mb, st = comp("Motherboard"), comp("Storage")
        sl = M2SlotSpec(slot_id="M2_1", accepted_module_keyings=("M",), supported_lengths=("2260",),
                        supported_modes=("pcie_nvme",), evidence_ref="https://vendor/slot")
        r = analyze([mb, st], [
            TechnicalProfile(component_id=mb.id, attributes=[self._mb([sl], completeness="partial")]),
            TechnicalProfile(component_id=st.id, attributes=m2_attrs()),
        ])
        self.assertEqual(find(r, "storage_m2.fit")[0].result, RESULT_REQUIRES_VERIFICATION)

    def test_unknown_without_fit_requires_verification(self):
        mb, st = comp("Motherboard"), comp("Storage")
        sl = M2SlotSpec(slot_id="M2_1", accepted_module_keyings=("M",), supported_lengths=("2260",),
                        supported_modes=("pcie_nvme",), evidence_ref="https://vendor/slot")
        r = analyze([mb, st], [
            TechnicalProfile(component_id=mb.id, attributes=[self._mb([sl], completeness="unknown")]),
            TechnicalProfile(component_id=st.id, attributes=m2_attrs()),
        ])
        self.assertEqual(find(r, "storage_m2.fit")[0].result, RESULT_REQUIRES_VERIFICATION)

    def test_complete_with_ambiguous_slot_requires_verification(self):
        mb, st = comp("Motherboard"), comp("Storage")
        # slot without per-slot evidence_ref -> ambiguous despite complete collection
        sl = M2SlotSpec(slot_id="M2_1", accepted_module_keyings=("M",), supported_lengths=("2260",),
                        supported_modes=("pcie_nvme",), evidence_ref=None)
        r = analyze([mb, st], [
            TechnicalProfile(component_id=mb.id, attributes=[self._mb([sl])]),
            TechnicalProfile(component_id=st.id, attributes=m2_attrs()),
        ])
        self.assertEqual(find(r, "storage_m2.fit")[0].result, RESULT_REQUIRES_VERIFICATION)

    def test_complete_unit_unverified_requires_verification(self):
        mb, st = comp("Motherboard"), comp("Storage")
        sl = M2SlotSpec(slot_id="M2_1", accepted_module_keyings=("M",), supported_lengths=("2260",),
                        supported_modes=("pcie_nvme",), evidence_ref="https://vendor/slot")
        r = analyze([mb, st], [
            TechnicalProfile(component_id=mb.id, attributes=[self._mb([sl])]),
            TechnicalProfile(component_id=st.id, attributes=[
                ua("storage_form_factor", "m2"), ua("storage_interface", "pcie"),
                ua("storage_command_set", "nvme"), ua("m2_keying", "M"), ua("m2_length_code", "2280")]),
        ])
        self.assertEqual(find(r, "storage_m2.fit")[0].result, RESULT_REQUIRES_VERIFICATION)

    def test_empty_unknown_requires_verification(self):
        mb, st = comp("Motherboard"), comp("Storage")
        r = analyze([mb, st], [
            TechnicalProfile(component_id=mb.id, attributes=[ua("m2_slots", [])]),
            TechnicalProfile(component_id=st.id, attributes=m2_attrs()),
        ])
        self.assertEqual(find(r, "storage_m2.slots_absent")[0].result, RESULT_INSUFFICIENT_DATA)

    def test_dimensional_incompatible_not_global_without_others(self):
        mb, st = comp("Motherboard"), comp("Storage")
        sl = M2SlotSpec(slot_id="M2_1", accepted_module_keyings=("M",), supported_lengths=("2260",),
                        supported_modes=("pcie_nvme",), evidence_ref="https://vendor/slot")
        r = analyze([mb, st], [
            TechnicalProfile(component_id=mb.id, attributes=[self._mb([sl]), va("sata_port_count", 0)]),
            TechnicalProfile(component_id=st.id, attributes=m2_attrs()),
        ])
        self.assertEqual(r.overall_result, RESULT_INCOMPATIBLE)


class TestPsuComplete(unittest.TestCase):
    def _cable(self, cid, atype, ends, psu_side=None):
        d = {"cable_id": cid, "assembly_type": atype, "component_side_ends": ends}
        if psu_side:
            d["psu_side_connector_id"] = psu_side
        return d

    def _end(self, eid, kind):
        return {"end_id": eid, "connector_kind": kind}

    def _psu_attr(self, cables, completeness="complete", verified=True):
        fn = va if verified else ua
        kw = {} if completeness == "unknown" else {"collection_completeness": completeness, "completeness_scope": SCOPE_PSU}
        return fn("power_cable_assemblies", cables, **kw)

    def test_complete_sufficient_compatible(self):
        mb, psu = comp("Motherboard"), comp("PSU")
        r = analyze([mb, psu], [
            TechnicalProfile(component_id=mb.id, attributes=[va("motherboard_power_connectors_required", [
                {"connector_kind": "ATX_24", "quantity": 1, "required": True}])]),
            TechnicalProfile(component_id=psu.id, attributes=[self._psu_attr(
                [self._cable("C1", "fixed_native", [self._end("E1", "ATX_24")])])]),
        ])
        self.assertEqual(find(r, "psu_mb.connector_availability")[0].result, RESULT_COMPATIBLE)

    def test_complete_resolved_insufficient_incompatible(self):
        gpu, psu = comp("GPU"), comp("PSU")
        r = analyze([gpu, psu], [
            TechnicalProfile(component_id=gpu.id, attributes=[va("gpu_power_connectors_required", [
                {"connector_kind": "PCIE_8", "quantity": 2, "required": True}])]),
            TechnicalProfile(component_id=psu.id, attributes=[self._psu_attr(
                [self._cable("C1", "fixed_native", [self._end("E1", "PCIE_8")])])]),
        ])
        f = find(r, "psu_gpu.connector_availability")
        self.assertEqual(f[0].result, RESULT_INCOMPATIBLE)
        self.assertEqual(f[0].severity, "critical")

    def test_partial_insufficient_requires_verification(self):
        gpu, psu = comp("GPU"), comp("PSU")
        r = analyze([gpu, psu], [
            TechnicalProfile(component_id=gpu.id, attributes=[va("gpu_power_connectors_required", [
                {"connector_kind": "PCIE_8", "quantity": 2, "required": True}])]),
            TechnicalProfile(component_id=psu.id, attributes=[self._psu_attr(
                [self._cable("C1", "fixed_native", [self._end("E1", "PCIE_8")])], completeness="partial")]),
        ])
        self.assertEqual(find(r, "psu_gpu.connector_availability")[0].result, RESULT_REQUIRES_VERIFICATION)

    def test_complete_with_third_party_requires_verification(self):
        gpu, psu = comp("GPU"), comp("PSU")
        r = analyze([gpu, psu], [
            TechnicalProfile(component_id=gpu.id, attributes=[va("gpu_power_connectors_required", [
                {"connector_kind": "PCIE_8", "quantity": 1, "required": True}])]),
            TechnicalProfile(component_id=psu.id, attributes=[self._psu_attr(
                [self._cable("T1", "third_party_adapter", [self._end("E1", "PCIE_8")])])]),
        ])
        f = find(r, "psu_gpu.connector_availability")[0]
        self.assertEqual(f.result, RESULT_REQUIRES_VERIFICATION)
        self.assertNotEqual(f.result, RESULT_INCOMPATIBLE)

    def test_complete_unapproved_adapter_requires_verification(self):
        gpu, psu = comp("GPU"), comp("PSU", model="Generic Model")
        r = analyze([gpu, psu], [
            TechnicalProfile(component_id=gpu.id, attributes=[va("gpu_power_connectors_required", [
                {"connector_kind": "12VHPWR", "quantity": 1, "required": True}])]),
            TechnicalProfile(component_id=psu.id, attributes=[self._psu_attr(
                [{"cable_id": "A1", "assembly_type": "manufacturer_approved_adapter",
                  "component_side_ends": [self._end("E1", "12VHPWR")],
                  "approved_psu_model": "Vendor Exact Model XYZ-999",
                  "approval_reference": "https://vendor.example/approval/xyz"}])]),
        ])
        self.assertEqual(find(r, "psu_gpu.connector_availability")[0].result, RESULT_REQUIRES_VERIFICATION)

    def test_complete_modular_no_pinout_claim(self):
        mb, psu = comp("Motherboard"), comp("PSU")
        r = analyze([mb, psu], [
            TechnicalProfile(component_id=mb.id, attributes=[va("motherboard_power_connectors_required", [
                {"connector_kind": "EPS_8", "quantity": 1, "required": True}])]),
            TechnicalProfile(component_id=psu.id, attributes=[self._psu_attr(
                [self._cable("C1", "modular_native", [self._end("E1", "EPS_8")], psu_side="CPU1")])]),
        ])
        f = find(r, "psu_mb.connector_availability")[0]
        self.assertEqual(f.result, RESULT_COMPATIBLE)
        self.assertIn("psu_pinout_assignment_not_evaluated", r.analysis_limitations)

    def test_complete_unverified_requirements_requires_verification(self):
        gpu, psu = comp("GPU"), comp("PSU")
        r = analyze([gpu, psu], [
            TechnicalProfile(component_id=gpu.id, attributes=[ua("gpu_power_connectors_required", [
                {"connector_kind": "PCIE_8", "quantity": 1, "required": True}])]),
            TechnicalProfile(component_id=psu.id, attributes=[self._psu_attr(
                [self._cable("C1", "fixed_native", [self._end("E1", "PCIE_8")])])]),
        ])
        self.assertEqual(find(r, "psu_gpu.connector_availability")[0].result, RESULT_REQUIRES_VERIFICATION)


class TestSataIdsComplete(unittest.TestCase):
    def test_complete_ids_include_affected(self):
        mb, m2, st = comp("Motherboard"), comp("Storage"), comp("Storage")
        sl = slot("M2_1", disables=("SATA1",))
        r = analyze([mb, m2, st], [
            TechnicalProfile(component_id=mb.id, attributes=[
                va("sata_port_count", 2),
                va("sata_port_identifiers", ["SATA1", "SATA2"], collection_completeness="complete", completeness_scope=SCOPE_SATA),
                va("m2_slots", [sl])]),
            TechnicalProfile(component_id=m2.id, attributes=m2_attrs()),
            TechnicalProfile(component_id=st.id, attributes=[
                va("storage_form_factor", "2_5_in"), va("storage_interface", "sata"), va("storage_command_set", "ata")]),
        ])
        f = find(r, "storage_sata.m2_topology")[0]
        self.assertEqual(f.result, RESULT_REQUIRES_VERIFICATION)
        self.assertIn("SATA1", list(f.message_params["affected_sata_port_ids"]))
        self.assertEqual(list(f.message_params.get("ids_nonexistent_within_scope", [])), [])

    def test_complete_ids_exclude_declared_rejected(self):
        # A complete identifier inventory contradicting a declared restriction is
        # incoherent data: fail closed at profile validation, never a silent engine claim.
        from pc_parts_organizer.technical_profiles import (
            TechnicalProfileValidationError, validate_profile_for_category)
        mb = comp("Motherboard")
        sl = slot("M2_1", disables=("SATA9",))
        p = TechnicalProfile(component_id=mb.id, attributes=[
            va("sata_port_count", 2),
            va("sata_port_identifiers", ["SATA1", "SATA2"], collection_completeness="complete", completeness_scope=SCOPE_SATA),
            va("m2_slots", [sl])])
        with self.assertRaises(TechnicalProfileValidationError):
            validate_profile_for_category(p, "Motherboard")

    def test_partial_ids_uncontrastable(self):
        mb, m2, st = comp("Motherboard"), comp("Storage"), comp("Storage")
        sl = slot("M2_1", disables=("SATA9",))
        r = analyze([mb, m2, st], [
            TechnicalProfile(component_id=mb.id, attributes=[
                va("sata_port_count", 2),
                va("sata_port_identifiers", ["SATA1", "SATA2"], collection_completeness="partial", completeness_scope="seen"),
                va("m2_slots", [sl])]),
            TechnicalProfile(component_id=m2.id, attributes=m2_attrs()),
            TechnicalProfile(component_id=st.id, attributes=[
                va("storage_form_factor", "2_5_in"), va("storage_interface", "sata"), va("storage_command_set", "ata")]),
        ])
        f = find(r, "storage_sata.m2_topology")[0]
        self.assertFalse(f.message_params["ids_contrastable"])

    def test_scalar_count_independent_of_completeness(self):
        mb, st = comp("Motherboard"), comp("Storage")
        r = analyze([mb, st], [
            TechnicalProfile(component_id=mb.id, attributes=[va("sata_port_count", 0)]),
            TechnicalProfile(component_id=st.id, attributes=[
                va("storage_form_factor", "2_5_in"), va("storage_interface", "sata"), va("storage_command_set", "ata")]),
        ])
        f = find(r, "storage_sata.port_availability")[0]
        self.assertEqual(f.result, RESULT_REQUIRES_VERIFICATION)
        self.assertNotEqual(f.result, RESULT_INCOMPATIBLE)


class TestEngineVersion(unittest.TestCase):
    def test_version(self):
        self.assertEqual(ENGINE_RULESET_VERSION, "t17.12-v1")


class TestAuditFixes(unittest.TestCase):
    def test_optional_only_unverified_requires_verification(self):
        mb, psu = comp("Motherboard"), comp("PSU")
        r = analyze([mb, psu], [
            TechnicalProfile(component_id=mb.id, attributes=[ua("motherboard_power_connectors_required", [
                {"connector_kind": "ATX_24", "quantity": 1, "required": False}])]),
            TechnicalProfile(component_id=psu.id, attributes=[ua("power_cable_assemblies",
                [self._cable("C1", "fixed_native", [self._end("E1", "ATX_24")])])]),
        ])
        f = find(r, "psu_mb.connector_availability")
        self.assertEqual(f[0].result, RESULT_REQUIRES_VERIFICATION)

    def _cable(self, cid, atype, ends, psu_side=None):
        d = {"cable_id": cid, "assembly_type": atype, "component_side_ends": ends}
        if psu_side:
            d["psu_side_connector_id"] = psu_side
        return d

    def _end(self, eid, kind):
        return {"end_id": eid, "connector_kind": kind}

    def test_split_group_shortage_covered_descriptively(self):
        # Descriptive inventory counts physical ends; electrical independence of
        # split-cable ends is explicitly not evaluated (limitation, not solver).
        gpu, psu = comp("GPU"), comp("PSU")
        r = analyze([gpu, psu], [
            TechnicalProfile(component_id=gpu.id, attributes=[va("gpu_power_connectors_required", [
                {"connector_kind": "PCIE_8", "quantity": 2, "required": True}])]),
            TechnicalProfile(component_id=psu.id, attributes=[va("power_cable_assemblies",
                [{"cable_id": "C1", "assembly_type": "fixed_native", "component_side_ends": [
                    {"end_id": "E1", "connector_kind": "PCIE_8", "split_group_id": "G"},
                    {"end_id": "E2", "connector_kind": "PCIE_8", "split_group_id": "G"}]}])]),
        ])
        f = find(r, "psu_gpu.connector_availability")
        self.assertEqual(f[0].result, RESULT_COMPATIBLE)
        self.assertIn("psu_pinout_assignment_not_evaluated", r.analysis_limitations)


if __name__ == "__main__":
    unittest.main()
