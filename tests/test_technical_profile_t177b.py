"""T17.7b typed object structures (M2 slots, power connectors/cables)."""

from __future__ import annotations

try:
    import tests._pcpo_test_isolation_bootstrap  # noqa: F401
except Exception:
    import _pcpo_test_isolation_bootstrap  # type: ignore  # noqa: F401

import json
import os
import tempfile
import unittest
import uuid
from pathlib import Path
from unittest.mock import patch

from pc_parts_organizer.models import Component
from pc_parts_organizer.service import InventoryService, StorageError
from pc_parts_organizer.storage import read_inventory_file, save_project_state
from pc_parts_organizer.technical_profiles import (
    ATTRIBUTE_REGISTRY,
    PROFILE_REGISTRY_VERSION,
    PROFILE_VERSION,
    M2SlotSpec,
    PowerCableAssembly,
    PowerCableEndSpec,
    PowerConnectorRequirement,
    TechnicalAttribute,
    TechnicalProfile,
    TechnicalProfileValidationError,
    parse_profile_dict,
    validate_profile_for_category,
)


def cid(): return str(uuid.uuid4())
def env(base): return patch.dict(os.environ, {"LOCALAPPDATA": str(base)})


class TestM2SlotSpec(unittest.TestCase):
    def valid(self, **o):
        d = {"slot_id":"M2_1","accepted_module_keyings":["M","B_M"],"supported_lengths":["2280","2242"],"supported_modes":["pcie_nvme"],"routed_to":"cpu"}
        d.update(o); return M2SlotSpec.from_dict(d)

    def test_valid_serialization_rebuild_defensive(self):
        s = self.valid(pcie_generation_max=4, pcie_lanes_max="x4", shared_resource_group_id="G1", disables_sata_port_ids=["SATA1"], notes="n", evidence_ref="ref")
        d = s.to_dict(); s2 = M2SlotSpec.from_dict(d)
        self.assertEqual(s, s2); self.assertEqual(d["schema_version"], 1)
        c = s.copy(); self.assertEqual(c.slot_id, s.slot_id)
        self.assertIsNot(s.accepted_module_keyings, c.accepted_module_keyings)

    def test_duplicate_id_in_list_rejected(self):
        with self.assertRaises(TechnicalProfileValidationError):
            TechnicalAttribute(key="m2_slots", value=[self.valid().to_dict(), self.valid().to_dict()])

    def test_invalid_keying_length_mode(self):
        with self.assertRaises(TechnicalProfileValidationError): self.valid(accepted_module_keyings=["X"])
        with self.assertRaises(TechnicalProfileValidationError): self.valid(supported_lengths=["9999"])
        with self.assertRaises(TechnicalProfileValidationError): self.valid(supported_modes=["nvme_only"])

    def test_sata_ata_and_pcie_nvme(self):
        self.assertEqual(self.valid(supported_modes=["sata_ata"]).supported_modes, ("sata_ata",))
        self.assertEqual(self.valid(supported_modes=["pcie_nvme","sata_ata"]).supported_modes, ("pcie_nvme","sata_ata"))

    def test_pcie_gen_lanes_optional(self):
        s = self.valid(pcie_generation_max=5, pcie_lanes_max="x2")
        self.assertEqual((s.pcie_generation_max, s.pcie_lanes_max), (5, "x2"))
        with self.assertRaises(TechnicalProfileValidationError): self.valid(pcie_generation_max=0)
        with self.assertRaises(TechnicalProfileValidationError): self.valid(pcie_lanes_max="x8")

    def test_sata_disable_ids_and_shared_group(self):
        s = self.valid(disables_sata_port_ids=["SATA_A1","SATA_A2"], shared_resource_group_id="R1")
        self.assertEqual(s.disables_sata_port_ids, ("SATA_A1","SATA_A2"))

    def test_unknown_fields_rejected(self):
        d = self.valid().to_dict(); d["hacker"] = 1
        with self.assertRaises(TechnicalProfileValidationError): M2SlotSpec.from_dict(d)


class TestPowerConnectorRequirement(unittest.TestCase):
    def test_kinds_and_validation(self):
        for k in ("ATX_20","ATX_24","EPS_4","EPS_8","PCIE_6","PCIE_8","12VHPWR","12V_2x6"):
            r = PowerConnectorRequirement.from_dict({"connector_kind":k,"quantity":1,"required":True})
            self.assertEqual(r.connector_kind, k)
        with self.assertRaises(TechnicalProfileValidationError):
            PowerConnectorRequirement.from_dict({"connector_kind":"ATX_24","quantity":0})
        with self.assertRaises(TechnicalProfileValidationError):
            PowerConnectorRequirement.from_dict({"connector_kind":"NOPE","quantity":1})
        r = PowerConnectorRequirement.from_dict({"connector_kind":"EPS_8","quantity":2,"required":False})
        self.assertFalse(r.required)

    def test_duplicate_kind_ambiguous_rejected_in_list(self):
        v = [{"connector_kind":"PCIE_8","quantity":1},{"connector_kind":"PCIE_8","quantity":1}]
        with self.assertRaises(TechnicalProfileValidationError):
            TechnicalAttribute(key="gpu_power_connectors_required", value=v)

    def test_differentiates_eps_pcie_and_12v(self):
        self.assertNotEqual(PowerConnectorRequirement.from_dict({"connector_kind":"EPS_8","quantity":1}).connector_kind,
                            PowerConnectorRequirement.from_dict({"connector_kind":"PCIE_8","quantity":1}).connector_kind)
        self.assertNotEqual(PowerConnectorRequirement.from_dict({"connector_kind":"12VHPWR","quantity":1}).connector_kind,
                            PowerConnectorRequirement.from_dict({"connector_kind":"12V_2x6","quantity":1}).connector_kind)


class TestPowerCableAssembly(unittest.TestCase):
    def end(self, eid="E1", kind="PCIE_8", grp=None):
        return {"end_id":eid, "connector_kind":kind, "split_group_id":grp}

    def test_fixed_native(self):
        c = PowerCableAssembly.from_dict({"cable_id":"C1","assembly_type":"fixed_native","component_side_ends":[self.end()]})
        self.assertEqual(c.assembly_type, "fixed_native")

    def test_modular_native_requires_psu_side(self):
        with self.assertRaises(TechnicalProfileValidationError):
            PowerCableAssembly.from_dict({"cable_id":"C1","assembly_type":"modular_native","component_side_ends":[self.end()]})
        PowerCableAssembly.from_dict({"cable_id":"C1","assembly_type":"modular_native","psu_side_connector_id":"PSU_CPU1","component_side_ends":[self.end("E1","EPS_8")]})

    def test_approved_adapter_requires_model_and_reference(self):
        with self.assertRaises(TechnicalProfileValidationError):
            PowerCableAssembly.from_dict({"cable_id":"C1","assembly_type":"manufacturer_approved_adapter","component_side_ends":[self.end("E1","12VHPWR")]})
        PowerCableAssembly.from_dict({"cable_id":"C1","assembly_type":"manufacturer_approved_adapter","approved_psu_model":"PSU-X","approval_reference":"https://vendor/doc","component_side_ends":[self.end("E1","12V_2x6")]})

    def test_third_party_and_unknown_preserved(self):
        self.assertEqual(PowerCableAssembly.from_dict({"cable_id":"C1","assembly_type":"third_party_adapter","component_side_ends":[self.end()]}).assembly_type, "third_party_adapter")
        self.assertEqual(PowerCableAssembly.from_dict({"cable_id":"C1","assembly_type":"unknown","component_side_ends":[self.end()]}).assembly_type, "unknown")

    def test_multiple_same_ends_same_cable_and_split(self):
        c = PowerCableAssembly.from_dict({"cable_id":"C1","assembly_type":"fixed_native","component_side_ends":[self.end("E1","PCIE_8","S1"), self.end("E2","PCIE_8","S1")]})
        self.assertEqual(len(c.component_side_ends), 2)
        self.assertEqual(c.component_side_ends[0].split_group_id, "S1")

    def test_duplicate_end_id_empty_cable_and_duplicate_cable_id(self):
        with self.assertRaises(TechnicalProfileValidationError):
            PowerCableAssembly.from_dict({"cable_id":"C1","assembly_type":"fixed_native","component_side_ends":[self.end("E1"), self.end("E1")]})
        with self.assertRaises(TechnicalProfileValidationError):
            PowerCableAssembly.from_dict({"cable_id":"C1","assembly_type":"fixed_native","component_side_ends":[]})
        with self.assertRaises(TechnicalProfileValidationError):
            TechnicalAttribute(key="power_cable_assemblies", value=[
                {"cable_id":"C1","assembly_type":"fixed_native","component_side_ends":[self.end()]},
                {"cable_id":"C1","assembly_type":"fixed_native","component_side_ends":[self.end("E2")]}])

    def test_unknown_fields_rejected(self):
        d = {"cable_id":"C1","assembly_type":"fixed_native","component_side_ends":[self.end()],"extra":1}
        with self.assertRaises(TechnicalProfileValidationError): PowerCableAssembly.from_dict(d)


class TestTypedStorageAndService(unittest.TestCase):
    def _env(self, base): return patch.dict(os.environ, {"LOCALAPPDATA": str(base)})

    def test_registry_and_versions(self):
        self.assertEqual(PROFILE_VERSION, 2)
        self.assertGreaterEqual(PROFILE_REGISTRY_VERSION, 5)
        self.assertIn("m2_slots", ATTRIBUTE_REGISTRY["Motherboard"])
        self.assertIn("motherboard_power_connectors_required", ATTRIBUTE_REGISTRY["Motherboard"])
        self.assertIn("sata_port_identifiers", ATTRIBUTE_REGISTRY["Motherboard"])
        self.assertIn("gpu_power_connectors_required", ATTRIBUTE_REGISTRY["GPU"])
        self.assertIn("power_cable_assemblies", ATTRIBUTE_REGISTRY["PSU"])

    def test_motherboard_sata_cross_validation(self):
        mb = Component(category="Motherboard", manufacturer="M", model="B")
        p = parse_profile_dict({"component_id": mb.id, "attributes":[
            {"key":"sata_port_count","value":2},
            {"key":"sata_port_identifiers","value":["SATA1","SATA2"]},
            {"key":"m2_slots","value":[{"slot_id":"M2_1","accepted_module_keyings":["M"],"supported_lengths":["2280"],"supported_modes":["pcie_nvme"],"disables_sata_port_ids":["SATA1"]}]}
        ]}, 0, "Motherboard")
        self.assertEqual(len([a for a in p.attributes if a.key=="m2_slots"][0].value), 1)
        with self.assertRaises(TechnicalProfileValidationError):
            parse_profile_dict({"component_id": mb.id, "attributes":[{"key":"sata_port_count","value":1},{"key":"sata_port_identifiers","value":["SATA1","SATA2"]}]}, 0, "Motherboard")
        # T17.10: a non-complete identifier list may omit ports a slot declares;
        # the engine reports them as uncontrastable instead of rejecting the profile.
        p2 = parse_profile_dict({"component_id": mb.id, "attributes":[{"key":"sata_port_identifiers","value":["SATA1"]},{"key":"m2_slots","value":[{"slot_id":"M2_1","accepted_module_keyings":["M"],"supported_lengths":["2280"],"supported_modes":["pcie_nvme"],"disables_sata_port_ids":["SATA9"]}]}]}, 0, "Motherboard")
        self.assertEqual(p2.attributes[0].collection_completeness, "unknown")
        # ...while a complete inventory contradicting a declared restriction stays incoherent.
        with self.assertRaises(TechnicalProfileValidationError):
            parse_profile_dict({"component_id": mb.id, "attributes":[
                {"key":"sata_port_identifiers","value":["SATA1"],"source":"official_vendor_doc","confidence":"high",
                 "verification_status":"verified","evidence_ref":"https://vendor/doc","verified_at":"2026-01-01",
                 "collection_completeness":"complete","completeness_scope":"All integrated SATA ports"},
                {"key":"m2_slots","value":[{"slot_id":"M2_1","accepted_module_keyings":["M"],"supported_lengths":["2280"],"supported_modes":["pcie_nvme"],"disables_sata_port_ids":["SATA9"]}]}]}, 0, "Motherboard")

    def test_round_trip_rebuild_old_profiles_valid(self):
        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
            mb = Component(category="Motherboard", manufacturer="M", model="B")
            gpu = Component(category="GPU", manufacturer="M", model="G")
            psu = Component(category="PSU", manufacturer="M", model="P")
            old = TechnicalProfile(component_id=gpu.id, attributes=[TechnicalAttribute(key="recommended_psu_power_w", value=650, unit="W")])
            mbp = parse_profile_dict({"component_id":mb.id,"attributes":[
                {"key":"sata_port_count","value":4},
                {"key":"m2_slots","value":[{"slot_id":"M2_A","accepted_module_keyings":["M"],"supported_lengths":["2280"],"supported_modes":["pcie_nvme"]}]},
                {"key":"motherboard_power_connectors_required","value":[{"connector_kind":"ATX_24","quantity":1},{"connector_kind":"EPS_8","quantity":1}]}
            ]},0,"Motherboard")
            psup = parse_profile_dict({"component_id":psu.id,"attributes":[{"key":"power_cable_assemblies","value":[{"cable_id":"PCIE1","assembly_type":"modular_native","psu_side_connector_id":"PSU_VGA1","component_side_ends":[{"end_id":"E1","connector_kind":"PCIE_8"},{"end_id":"E2","connector_kind":"PCIE_8","split_group_id":"DAISY1"}]}]}]},0,"PSU")
            with self._env(base):
                save_project_state([mb,gpu,psu], [], [mbp,old,psup])
                s = InventoryService()
                mbr = s.get_technical_profile(mb.id)
                self.assertTrue(any(a.key=="m2_slots" for a in mbr.attributes))
                self.assertIsNotNone(s.get_technical_profile(gpu.id))  # old-style scalar profile preserved
            # storage file reload
            with self._env(base):
                s2 = InventoryService()
                pa = next(a for a in s2.get_technical_profile(psu.id).attributes if a.key=="power_cable_assemblies")
                self.assertEqual(len(pa.value[0].component_side_ends), 2)

    def test_rejects_malformed_typed_structures(self):
        with self.assertRaises(TechnicalProfileValidationError):
            parse_profile_dict({"component_id":cid(),"attributes":[{"key":"m2_slots","value":[{"slot_id":"X"}]}]},0,"Motherboard")
        with self.assertRaises(TechnicalProfileValidationError):
            parse_profile_dict({"component_id":cid(),"attributes":[{"key":"gpu_power_connectors_required","value":[{"connector_kind":"ATX_24","quantity":1,"bad":1}]}]},0,"GPU")
        # unsupported schema version
        with self.assertRaises(TechnicalProfileValidationError):
            M2SlotSpec.from_dict({"schema_version":99,"slot_id":"M2","accepted_module_keyings":["M"],"supported_lengths":["2280"],"supported_modes":["pcie_nvme"]})

    def test_persistence_failure_no_memory_mutation_and_preserved(self):
        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
            mb = Component(category="Motherboard", manufacturer="M", model="B")
            p = parse_profile_dict({"component_id":mb.id,"attributes":[{"key":"m2_slots","value":[{"slot_id":"M2_A","accepted_module_keyings":["M"],"supported_lengths":["2280"],"supported_modes":["pcie_nvme"]}]}]},0,"Motherboard")
            with self._env(base):
                save_project_state([mb], [], [])
                s = InventoryService()
                with patch("pc_parts_organizer.service.save_project_state", side_effect=StorageError("boom")):
                    with self.assertRaises(StorageError): s.set_technical_profile(p)
                self.assertIsNone(s.get_technical_profile(mb.id))


if __name__ == "__main__":
    unittest.main()
