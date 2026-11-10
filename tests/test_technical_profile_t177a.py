"""T17.7a: basic scalar technical profiles for Storage/Motherboard/Case/PSU/GPU."""

from __future__ import annotations

try:
    import tests._pcpo_test_isolation_bootstrap  # noqa: F401
except Exception:
    import _pcpo_test_isolation_bootstrap  # type: ignore  # noqa: F401

import os
import tempfile
import unittest
import uuid
from pathlib import Path
from unittest.mock import patch

from pc_parts_organizer.models import Build, Component
from pc_parts_organizer.service import InventoryService, StorageError
from pc_parts_organizer.storage import export_project_state, read_inventory_file, save_project_state
from pc_parts_organizer.technical_profiles import (
    ATTRIBUTE_REGISTRY,
    PROFILE_REGISTRY_VERSION,
    PROFILE_VERSION,
    TechnicalAttribute,
    TechnicalProfile,
    TechnicalProfileValidationError,
    parse_profile_dict,
    validate_profile_for_category,
)


def cid(): return str(uuid.uuid4())
def comp(category, **kw):
    d = dict(category=category, manufacturer="M", model="X", specifications="", notes="")
    d.update(kw)
    return Component(**d)
def env(base): return patch.dict(os.environ, {"LOCALAPPDATA": str(base)})


class TestT177aRegistry(unittest.TestCase):
    def test_version_and_supported_categories(self):
        self.assertEqual(PROFILE_VERSION, 2)
        self.assertGreaterEqual(PROFILE_REGISTRY_VERSION, 3)
        for cat in ("Storage","PSU"):
            self.assertIn(cat, ATTRIBUTE_REGISTRY)
        self.assertIn("sata_port_count", ATTRIBUTE_REGISTRY["Motherboard"])
        self.assertIn("bay_2_5_total", ATTRIBUTE_REGISTRY["Case"])
        self.assertIn("bay_3_5_total", ATTRIBUTE_REGISTRY["Case"])
        self.assertIn("rated_continuous_power_w", ATTRIBUTE_REGISTRY["PSU"])
        self.assertIn("recommended_psu_power_w", ATTRIBUTE_REGISTRY["GPU"])

    def test_storage_enums_and_units(self):
        p = parse_profile_dict({"component_id": cid(), "attributes": [
            {"key":"storage_form_factor","value":"m2"},
            {"key":"storage_interface","value":"pcie"},
            {"key":"storage_command_set","value":"nvme"},
            {"key":"m2_keying","value":"B+M"},
            {"key":"m2_length_code","value":"2280"},
            {"key":"pcie_generation","value":4},
            {"key":"pcie_lanes","value":"x4"},
        ]}, 0, "Storage")
        vals = {a.key:a.value for a in p.attributes}
        self.assertEqual(vals["m2_keying"], "B_M")
        self.assertEqual(vals["pcie_generation"], 4)

    def test_non_negative_ints_allow_zero(self):
        for cat,key in (("Motherboard","sata_port_count"),("Case","bay_2_5_total"),("Case","bay_3_5_total")):
            p = parse_profile_dict({"component_id": cid(), "attributes":[{"key":key,"value":0}]}, 0, cat)
            self.assertEqual(p.attributes[0].value, 0)
        for cat,key in (("Motherboard","sata_port_count"),("Case","bay_2_5_total")):
            with self.assertRaises(TechnicalProfileValidationError):
                parse_profile_dict({"component_id": cid(), "attributes":[{"key":key,"value":-1}]}, 0, cat)
            with self.assertRaises(TechnicalProfileValidationError):
                parse_profile_dict({"component_id": cid(), "attributes":[{"key":key,"value":True}]}, 0, cat)

    def test_positive_power_attrs(self):
        for cat,key in (("PSU","rated_continuous_power_w"),("GPU","recommended_psu_power_w")):
            p = parse_profile_dict({"component_id": cid(), "attributes":[{"key":key,"value":750,"unit":"W"}]}, 0, cat)
            self.assertEqual(p.attributes[0].value, 750)
            self.assertEqual(p.attributes[0].unit, "W")
            with self.assertRaises(TechnicalProfileValidationError):
                parse_profile_dict({"component_id": cid(), "attributes":[{"key":key,"value":0}]}, 0, cat)

    def test_interface_command_set_coherence(self):
        # supported coherent
        parse_profile_dict({"component_id": cid(), "attributes":[{"key":"storage_form_factor","value":"2_5_in"},{"key":"storage_interface","value":"sata"},{"key":"storage_command_set","value":"ata"}]}, 0, "Storage")
        parse_profile_dict({"component_id": cid(), "attributes":[{"key":"storage_form_factor","value":"m2"},{"key":"storage_interface","value":"pcie"},{"key":"storage_command_set","value":"nvme"}]}, 0, "Storage")
        # incoherent
        with self.assertRaises(TechnicalProfileValidationError):
            parse_profile_dict({"component_id": cid(), "attributes":[{"key":"storage_interface","value":"sata"},{"key":"storage_command_set","value":"nvme"}]}, 0, "Storage")
        with self.assertRaises(TechnicalProfileValidationError):
            parse_profile_dict({"component_id": cid(), "attributes":[{"key":"storage_interface","value":"pcie"},{"key":"storage_command_set","value":"ata"}]}, 0, "Storage")
        # other does not hard-fail coherence
        parse_profile_dict({"component_id": cid(), "attributes":[{"key":"storage_interface","value":"other"},{"key":"storage_command_set","value":"nvme"}]}, 0, "Storage")

    def test_m2_attrs_conditional(self):
        # allowed when m2
        parse_profile_dict({"component_id": cid(), "attributes":[{"key":"storage_form_factor","value":"m2"},{"key":"m2_keying","value":"M"},{"key":"m2_length_code","value":"2280"}]}, 0, "Storage")
        # rejected when other known format
        for ff in ("2_5_in","3_5_in","pcie_addin"):
            with self.assertRaises(TechnicalProfileValidationError):
                parse_profile_dict({"component_id": cid(), "attributes":[{"key":"storage_form_factor","value":ff},{"key":"m2_keying","value":"M"}]}, 0, "Storage")
        # unknown/other form factor does not force rejection
        parse_profile_dict({"component_id": cid(), "attributes":[{"key":"storage_form_factor","value":"other"},{"key":"m2_keying","value":"M"}]}, 0, "Storage")
        # pcie attrs rejected when interface sata
        with self.assertRaises(TechnicalProfileValidationError):
            parse_profile_dict({"component_id": cid(), "attributes":[{"key":"storage_interface","value":"sata"},{"key":"pcie_generation","value":4}]}, 0, "Storage")

    def test_old_profiles_still_valid(self):
        ram = parse_profile_dict({"component_id": cid(), "profile_version": 1, "attributes": [
            {"key":"memory_generation","value":"DDR4"},{"key":"module_form_factor","value":"DIMM"},
            {"key":"total_capacity_gb","value":16,"unit":"GB"},{"key":"module_count","value":2}
        ]}, 0, "RAM")
        self.assertEqual(ram.profile_version, 1)
        validate_profile_for_category(ram, "RAM")


class TestT177aServiceAndPersistence(unittest.TestCase):
    def _env(self, base): return patch.dict(os.environ, {"LOCALAPPDATA": str(base)})

    def test_save_and_rebuild_new_categories(self):
        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
            st = comp("Storage"); ps = comp("PSU"); gpu = comp("GPU"); mb = comp("Motherboard"); case = comp("Case")
            sp = TechnicalProfile(component_id=st.id, attributes=[TechnicalAttribute(key="storage_form_factor",value="m2"), TechnicalAttribute(key="storage_interface",value="pcie"), TechnicalAttribute(key="storage_command_set",value="nvme")])
            pp = TechnicalProfile(component_id=ps.id, attributes=[TechnicalAttribute(key="rated_continuous_power_w",value=750,unit="W",source="official_vendor_doc",confidence="high",verification_status="verified",evidence_ref="https://e",verified_at="2026-01-01")])
            gp = TechnicalProfile(component_id=gpu.id, attributes=[TechnicalAttribute(key="recommended_psu_power_w",value=850,unit="W")])
            mp = TechnicalProfile(component_id=mb.id, attributes=[TechnicalAttribute(key="sata_port_count",value=0)])
            cp = TechnicalProfile(component_id=case.id, attributes=[TechnicalAttribute(key="bay_2_5_total",value=2), TechnicalAttribute(key="bay_3_5_total",value=0)])
            with self._env(base):
                save_project_state([st,ps,gpu,mb,case], [], [sp,pp,gp,mp,cp])
                s = InventoryService()
                self.assertEqual(s.get_technical_profile(ps.id).attributes[0].verification_status, "verified")
                self.assertEqual(s.get_technical_profile(mb.id).attributes[0].value, 0)
            with self._env(base):
                s2 = InventoryService()
                self.assertIsNotNone(s2.get_technical_profile(st.id))

    def test_preserved_during_component_and_build_mutations(self):
        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
            st = comp("Storage"); other = comp("RAM")
            sp = TechnicalProfile(component_id=st.id, attributes=[TechnicalAttribute(key="storage_form_factor",value="2_5_in")])
            b = Build(name="B", component_ids=[other.id])
            with self._env(base):
                save_project_state([st,other], [b], [sp])
                s = InventoryService()
                s.update_component(st.id, st.category, st.manufacturer, st.model + "2", st.specifications, st.notes,
                                  st.status, st.location, st.purchase_date, st.warranty_end_date, st.purchase_price, st.purchase_currency)
                self.assertIsNotNone(s.get_technical_profile(st.id))
                s.update_build(b.id, component_ids=[other.id])
                self.assertIsNotNone(s.get_technical_profile(st.id))

    def test_export_restore_complete_with_new_profiles(self):
        with tempfile.TemporaryDirectory() as td:
            base = Path(td); out = Path(td)/"bk.json"
            st = comp("Storage"); ps = comp("PSU")
            sp = TechnicalProfile(component_id=st.id, attributes=[TechnicalAttribute(key="storage_form_factor",value="m2")])
            pp = TechnicalProfile(component_id=ps.id, attributes=[TechnicalAttribute(key="rated_continuous_power_w",value=650,unit="W")])
            with self._env(base):
                save_project_state([st,ps], [], [sp,pp])
                s = InventoryService()
                state = s.get_project_state()
                info = export_project_state(state, out)
                self.assertEqual(len(info.technical_profiles), 2)
                loaded = read_inventory_file(out)
                self.assertEqual(len(loaded.technical_profiles), 2)


if __name__ == "__main__":
    unittest.main()
