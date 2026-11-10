"""T17.8b PSU connector inventory rules: descriptive only, no electrical validation."""
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
    RESULT_INSUFFICIENT_DATA,
    RESULT_REQUIRES_VERIFICATION,
    analyze_build_compatibility,
)
from pc_parts_organizer.models import Build, Component
from pc_parts_organizer.technical_profiles import TechnicalAttribute, TechnicalProfile


def comp(cat, **kw):
    d = dict(category=cat, manufacturer="M", model="X", specifications="", notes="")
    d.update(kw); return Component(**d)
def va(key, value, unit=None):
    return TechnicalAttribute(key=key, value=value, unit=unit, source="official_vendor_doc", confidence="high",
                              verification_status="verified", evidence_ref="https://vendor/doc", verified_at="2026-01-01")
def ua(key, value, unit=None):
    return TechnicalAttribute(key=key, value=value, unit=unit, source="unknown", confidence="low", verification_status="unverified")
def req(kind, qty=1, required=True):
    return {"connector_kind": kind, "quantity": qty, "required": required}
def end(end_id, kind, split_group_id=None):
    d = {"end_id": end_id, "connector_kind": kind}
    if split_group_id is not None: d["split_group_id"] = split_group_id
    return d
def cable(cable_id, assembly_type, ends, psu_side=None, approved_psu_model=None, approval_reference=None):
    d = {"cable_id": cable_id, "assembly_type": assembly_type, "component_side_ends": ends}
    if psu_side is not None: d["psu_side_connector_id"] = psu_side
    if approved_psu_model is not None: d["approved_psu_model"] = approved_psu_model
    if approval_reference is not None: d["approval_reference"] = approval_reference
    return d
def fr(rule, rep): return [f for f in rep.findings if f.rule_id == rule]
def has_rule_prefix(prefix, rep): return [f for f in rep.findings if f.rule_id.startswith(prefix)]


class TestPsuConnectorInventory(unittest.TestCase):
    def _analyze(self, comps, profs):
        b = Build(name="b", component_ids=[c.id for c in comps])
        return analyze_build_compatibility(b, comps, profs)

    def test_atx24_required_and_available(self):
        mb=comp("Motherboard"); psu=comp("PSU")
        profs=[TechnicalProfile(component_id=mb.id, attributes=[va("motherboard_power_connectors_required",[req("ATX_24")])]),
               TechnicalProfile(component_id=psu.id, attributes=[va("power_cable_assemblies",[cable("C1","fixed_native",[end("E1","ATX_24")])])])]
        r=self._analyze([mb,psu],profs)
        self.assertTrue(any(f.rule_id=="psu_mb.connector_availability" and f.result==RESULT_COMPATIBLE for f in r.findings))
        self.assertIn("psu_electrical_capacity_not_evaluated", r.analysis_limitations)

    def test_eps8_required_and_available(self):
        mb=comp("Motherboard"); psu=comp("PSU")
        profs=[TechnicalProfile(component_id=mb.id, attributes=[va("motherboard_power_connectors_required",[req("EPS_8",2)])]),
               TechnicalProfile(component_id=psu.id, attributes=[va("power_cable_assemblies",[cable("C1","modular_native",[end("E1","EPS_8"),end("E2","EPS_8")],psu_side="CPU1")])])]
        r=self._analyze([mb,psu],profs)
        self.assertEqual([f.result for f in fr("psu_mb.connector_availability",r)], [RESULT_COMPATIBLE])

    def test_pcie8_required_and_available(self):
        gpu=comp("GPU"); psu=comp("PSU")
        profs=[TechnicalProfile(component_id=gpu.id, attributes=[va("gpu_power_connectors_required",[req("PCIE_8",2)])]),
               TechnicalProfile(component_id=psu.id, attributes=[va("power_cable_assemblies",[cable("C1","fixed_native",[end("E1","PCIE_8"),end("E2","PCIE_8")])])])]
        r=self._analyze([gpu,psu],profs)
        self.assertEqual([f.result for f in fr("psu_gpu.connector_availability",r)], [RESULT_COMPATIBLE])

    def test_12vhpwr_vs_12v2x6_not_equated(self):
        gpu=comp("GPU"); psu=comp("PSU")
        profs=[TechnicalProfile(component_id=gpu.id, attributes=[va("gpu_power_connectors_required",[req("12VHPWR",1)])]),
               TechnicalProfile(component_id=psu.id, attributes=[va("power_cable_assemblies",[cable("C1","fixed_native",[end("E1","12V_2x6")])])])]
        r=self._analyze([gpu,psu],profs)
        f=fr("psu_gpu.connector_availability",r)[0]
        self.assertEqual(f.result, RESULT_REQUIRES_VERIFICATION)
        self.assertNotEqual(f.result, RESULT_COMPATIBLE)

    def test_eps_vs_pcie_not_equated(self):
        gpu=comp("GPU"); psu=comp("PSU")
        profs=[TechnicalProfile(component_id=gpu.id, attributes=[va("gpu_power_connectors_required",[req("PCIE_8",1)])]),
               TechnicalProfile(component_id=psu.id, attributes=[va("power_cable_assemblies",[cable("C1","fixed_native",[end("E1","EPS_8")])])])]
        r=self._analyze([gpu,psu],profs)
        self.assertEqual(fr("psu_gpu.connector_availability",r)[0].result, RESULT_REQUIRES_VERIFICATION)

    def test_multiple_quantities_and_joint_aggregation(self):
        mb=comp("Motherboard"); gpu=comp("GPU"); psu=comp("PSU")
        profs=[TechnicalProfile(component_id=mb.id, attributes=[va("motherboard_power_connectors_required",[req("ATX_24"),req("EPS_8",1)])]),
               TechnicalProfile(component_id=gpu.id, attributes=[va("gpu_power_connectors_required",[req("PCIE_8",2)])]),
               TechnicalProfile(component_id=psu.id, attributes=[va("power_cable_assemblies",[
                   cable("C1","fixed_native",[end("E1","ATX_24")]),
                   cable("C2","modular_native",[end("E2","EPS_8")],psu_side="CPU"),
                   cable("C3","fixed_native",[end("E3","PCIE_8"),end("E4","PCIE_8")]),
               ])])]
        r=self._analyze([mb,gpu,psu],profs)
        self.assertEqual(fr("psu_mb.connector_availability",r)[0].result, RESULT_COMPATIBLE)
        self.assertEqual(fr("psu_gpu.connector_availability",r)[0].result, RESULT_COMPATIBLE)
        self.assertEqual(fr("psu_joint.connector_availability",r)[0].result, RESULT_COMPATIBLE)

    def test_joint_does_not_reuse_same_end(self):
        mb=comp("Motherboard"); gpu=comp("GPU"); psu=comp("PSU")
        profs=[TechnicalProfile(component_id=mb.id, attributes=[va("motherboard_power_connectors_required",[req("EPS_8",1)])]),
               TechnicalProfile(component_id=gpu.id, attributes=[va("gpu_power_connectors_required",[req("EPS_8",1)])]),
               TechnicalProfile(component_id=psu.id, attributes=[va("power_cable_assemblies",[cable("C1","fixed_native",[end("E1","EPS_8")])])])]
        r=self._analyze([mb,gpu,psu],profs)
        self.assertEqual(fr("psu_joint.connector_availability",r)[0].result, RESULT_REQUIRES_VERIFICATION)
        # EPS/PCIe still not equated; this test uses same kind to prove no reuse

    def test_optional_requirements_do_not_block(self):
        mb=comp("Motherboard"); psu=comp("PSU")
        profs=[TechnicalProfile(component_id=mb.id, attributes=[va("motherboard_power_connectors_required",[req("ATX_24"),req("EPS_4",1,required=False)])]),
               TechnicalProfile(component_id=psu.id, attributes=[va("power_cable_assemblies",[cable("C1","fixed_native",[end("E1","ATX_24")])])])]
        r=self._analyze([mb,psu],profs)
        self.assertEqual(fr("psu_mb.connector_availability",r)[0].result, RESULT_COMPATIBLE)

    def test_split_cable_ends_counted_descriptively_and_identity_preserved(self):
        gpu=comp("GPU"); psu=comp("PSU")
        profs=[TechnicalProfile(component_id=gpu.id, attributes=[va("gpu_power_connectors_required",[req("PCIE_8",2)])]),
               TechnicalProfile(component_id=psu.id, attributes=[va("power_cable_assemblies",[cable("C1","fixed_native",[end("E1","PCIE_8","SG1"),end("E2","PCIE_8","SG1")])])])]
        r=self._analyze([gpu,psu],profs)
        f=fr("psu_gpu.connector_availability",r)[0]
        self.assertEqual(f.result, RESULT_COMPATIBLE)
        ends=f.evidence["power_cable_assemblies"]["eligible_ends"]
        self.assertEqual({e["cable_id"] for e in ends}, {"C1"})
        self.assertTrue(all(e.get("split_group_id")=="SG1" for e in ends))

    def test_manufacturer_approved_adapter_not_auto_elevated(self):
        gpu=comp("GPU"); psu=comp("PSU")
        profs=[TechnicalProfile(component_id=gpu.id, attributes=[va("gpu_power_connectors_required",[req("12VHPWR",1)])]),
               TechnicalProfile(component_id=psu.id, attributes=[va("power_cable_assemblies",[cable("C1","manufacturer_approved_adapter",[end("E1","12VHPWR")],approved_psu_model="ModelX",approval_reference="https://vendor/approval")])])]
        r=self._analyze([gpu,psu],profs)
        f=fr("psu_gpu.connector_availability",r)[0]
        self.assertEqual(f.result, RESULT_REQUIRES_VERIFICATION)
        self.assertNotEqual(f.result, RESULT_COMPATIBLE)

    def test_third_party_and_unknown_not_counted_as_confirmed(self):
        for atype in ("third_party_adapter","unknown"):
            with self.subTest(atype=atype):
                gpu=comp("GPU"); psu=comp("PSU")
                kw={"approved_psu_model":"M","approval_reference":"R"} if False else {}
                profs=[TechnicalProfile(component_id=gpu.id, attributes=[va("gpu_power_connectors_required",[req("PCIE_8",1)])]),
                       TechnicalProfile(component_id=psu.id, attributes=[va("power_cable_assemblies",[cable("C1",atype,[end("E1","PCIE_8")])])])]
                r=self._analyze([gpu,psu],profs)
                self.assertEqual(fr("psu_gpu.connector_availability",r)[0].result, RESULT_REQUIRES_VERIFICATION)

    def test_insufficient_declared_inventory_not_incompatible_without_exhaustiveness(self):
        gpu=comp("GPU"); psu=comp("PSU")
        profs=[TechnicalProfile(component_id=gpu.id, attributes=[va("gpu_power_connectors_required",[req("PCIE_8",2)])]),
               TechnicalProfile(component_id=psu.id, attributes=[va("power_cable_assemblies",[cable("C1","fixed_native",[end("E1","PCIE_8")])])])]
        r=self._analyze([gpu,psu],profs)
        f=fr("psu_gpu.connector_availability",r)[0]
        self.assertEqual(f.result, RESULT_REQUIRES_VERIFICATION)
        self.assertNotIn(f.result, ("incompatible",))

    def test_verified_collection_does_not_imply_exhaustive_inventory(self):
        # same as insufficient case but explicitly verified/high-confidence collection
        gpu=comp("GPU"); psu=comp("PSU")
        profs=[TechnicalProfile(component_id=gpu.id, attributes=[va("gpu_power_connectors_required",[req("PCIE_8",3)])]),
               TechnicalProfile(component_id=psu.id, attributes=[va("power_cable_assemblies",[cable("C1","fixed_native",[end("E1","PCIE_8"),end("E2","PCIE_8")])])])]
        r=self._analyze([gpu,psu],profs)
        f=fr("psu_gpu.connector_availability",r)[0]
        self.assertEqual(f.result, RESULT_REQUIRES_VERIFICATION)
        self.assertEqual(f.message_params.get("reason"), "inventory_exhaustiveness_not_demonstrated")

    def test_unverified_inventory_degrades(self):
        mb=comp("Motherboard"); psu=comp("PSU")
        profs=[TechnicalProfile(component_id=mb.id, attributes=[va("motherboard_power_connectors_required",[req("ATX_24")])]),
               TechnicalProfile(component_id=psu.id, attributes=[ua("power_cable_assemblies",[cable("C1","fixed_native",[end("E1","ATX_24")])])])]
        r=self._analyze([mb,psu],profs)
        self.assertEqual(fr("psu_mb.connector_availability",r)[0].result, RESULT_REQUIRES_VERIFICATION)

    def test_missing_psu_profile_or_requirements(self):
        mb=comp("Motherboard"); psu=comp("PSU")
        r1=self._analyze([mb,psu],[TechnicalProfile(component_id=mb.id, attributes=[va("motherboard_power_connectors_required",[req("ATX_24")])])])
        self.assertEqual(fr("psu_mb.psu_inventory_missing",r1)[0].result, RESULT_INSUFFICIENT_DATA)
        r2=self._analyze([mb,psu],[TechnicalProfile(component_id=psu.id, attributes=[va("power_cable_assemblies",[cable("C1","fixed_native",[end("E1","ATX_24")])])])])
        self.assertEqual(fr("psu_mb.requirements_missing",r2)[0].result, RESULT_INSUFFICIENT_DATA)

    def test_absence_of_requirement_not_treated_as_empty_proof(self):
        mb=comp("Motherboard"); psu=comp("PSU")
        # no requirement attr at all -> insufficient_data, not compatible
        r=self._analyze([mb,psu],[TechnicalProfile(component_id=psu.id, attributes=[va("power_cable_assemblies",[cable("C1","fixed_native",[end("E1","ATX_24")])])])])
        self.assertEqual(fr("psu_mb.requirements_missing",r)[0].result, RESULT_INSUFFICIENT_DATA)
        self.assertFalse(any(f.result==RESULT_COMPATIBLE and f.rule_id.startswith("psu_mb") for f in r.findings))

    def test_purity_determinism_no_persistence(self):
        mb=comp("Motherboard"); psu=comp("PSU")
        profs=[TechnicalProfile(component_id=mb.id, attributes=[va("motherboard_power_connectors_required",[req("ATX_24")])]),
               TechnicalProfile(component_id=psu.id, attributes=[va("power_cable_assemblies",[cable("C1","fixed_native",[end("E1","ATX_24")])])])]
        b=Build(name="b", component_ids=[mb.id,psu.id]); comps=[mb,psu]
        before=[p.to_dict() for p in profs]; bb=copy.deepcopy(b.__dict__)
        r1=analyze_build_compatibility(b,comps,profs); r2=analyze_build_compatibility(b,comps,profs)
        self.assertEqual([p.to_dict() for p in profs], before); self.assertEqual(b.__dict__, bb)
        self.assertEqual([(f.rule_id,f.result) for f in r1.findings], [(f.rule_id,f.result) for f in r2.findings])

    def test_engine_version(self):
        self.assertEqual(ENGINE_RULESET_VERSION, "t17.12-v1")

    def test_global_not_compatible_from_connector_inventory_alone(self):
        mb=comp("Motherboard"); psu=comp("PSU")
        profs=[TechnicalProfile(component_id=mb.id, attributes=[va("motherboard_power_connectors_required",[req("ATX_24")])]),
               TechnicalProfile(component_id=psu.id, attributes=[va("power_cable_assemblies",[cable("C1","fixed_native",[end("E1","ATX_24")])])])]
        r=self._analyze([mb,psu],profs)
        self.assertNotEqual(r.overall_result, RESULT_COMPATIBLE)  # PSU electrical not evaluated / other OOS limits present
        self.assertIn("psu_electrical_capacity_not_evaluated", r.analysis_limitations)


if __name__ == "__main__":
    unittest.main()
