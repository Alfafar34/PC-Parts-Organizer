"""T17.8a audit: deep immutability and defensive copy of typed structures."""

from __future__ import annotations

try:
    import tests._pcpo_test_isolation_bootstrap  # noqa: F401
except Exception:
    import _pcpo_test_isolation_bootstrap  # type: ignore  # noqa: F401

import unittest

from pc_parts_organizer.technical_profiles import (
    M2SlotSpec,
    PowerCableAssembly,
    PowerCableEndSpec,
    PowerConnectorRequirement,
    TechnicalAttribute,
    TechnicalProfile,
    TechnicalProfileValidationError,
)


def m2(slot_id="M2_1", **o):
    d = {"slot_id": slot_id, "accepted_module_keyings": ["M"], "supported_lengths": ["2280"], "supported_modes": ["pcie_nvme"]}
    d.update(o); return M2SlotSpec.from_dict(d)


class TestDeepImmutability(unittest.TestCase):
    def test_m2_lists_are_tuples_and_to_dict_is_independent(self):
        s = m2()
        self.assertIsInstance(s.accepted_module_keyings, tuple)
        self.assertIsInstance(s.supported_lengths, tuple)
        self.assertIsInstance(s.supported_modes, tuple)
        d = s.to_dict()
        d["accepted_module_keyings"].append("B")
        d["supported_lengths"].clear()
        self.assertEqual(s.accepted_module_keyings, ("M",))
        self.assertEqual(s.supported_lengths, ("2280",))
        with self.assertRaises(Exception):
            s.accepted_module_keyings = ()  # frozen dataclass

    def test_cable_ends_immutable_tuple_and_independent_to_dict(self):
        c = PowerCableAssembly.from_dict({"cable_id":"C1","assembly_type":"fixed_native","component_side_ends":[{"end_id":"E1","connector_kind":"PCIE_8"},{"end_id":"E2","connector_kind":"PCIE_8"}]})
        self.assertIsInstance(c.component_side_ends, tuple)
        d = c.to_dict()
        d["component_side_ends"][0]["end_id"] = "HACK"
        self.assertEqual(c.component_side_ends[0].end_id, "E1")
        with self.assertRaises(Exception):
            c.component_side_ends = ()

    def test_power_requirement_immutable(self):
        r = PowerConnectorRequirement.from_dict({"connector_kind":"ATX_24","quantity":1,"required":True})
        d = r.to_dict(); d["quantity"] = 99
        self.assertEqual(r.quantity, 1)
        with self.assertRaises(Exception):
            r.quantity = 2

    def test_technical_attribute_value_defensive_copy_no_shared_reference(self):
        s = m2()
        a = TechnicalAttribute(key="m2_slots", value=[s])
        # caller mutates its own dict after attribute construction; object unchanged
        raw = {"slot_id":"M2_1","accepted_module_keyings":["M"],"supported_lengths":["2280"],"supported_modes":["pcie_nvme"],"routed_to":"cpu"}
        a2 = TechnicalAttribute(key="m2_slots", value=[raw])
        raw["accepted_module_keyings"].append("B")
        self.assertEqual(a2.value[0].accepted_module_keyings, ("M",))
        # copies and round-trip independent
        c = a2.copy(); self.assertEqual(c.value[0].accepted_module_keyings, ("M",))
        self.assertIsNot(a2.value[0], c.value[0])

    def test_profile_attribute_copy_and_to_dict_independent(self):
        p = TechnicalProfile(component_id="00000000-0000-4000-8000-000000000000",
                             attributes=[TechnicalAttribute(key="m2_slots", value=[m2()])])
        d = p.to_dict()
        d["attributes"][0]["value"][0]["supported_lengths"].clear()
        self.assertEqual(p.attributes[0].value[0].supported_lengths, ("2280",))
        c = p.copy()
        self.assertEqual(c.attributes[0].value[0].supported_lengths, ("2280",))

    def test_end_to_end_json_reconstruction_preserves_immutability(self):
        p = TechnicalProfile(component_id="00000000-0000-4000-8000-000000000000",
                             attributes=[TechnicalAttribute(key="m2_slots", value=[m2().to_dict()])])
        blob = p.to_dict()
        import json
        text = json.dumps(blob)
        from pc_parts_organizer.technical_profiles import parse_profile_dict
        p2 = parse_profile_dict(json.loads(text), 0, "Motherboard")
        self.assertIsInstance(p2.attributes[0].value[0].supported_lengths, tuple)


if __name__ == "__main__":
    unittest.main()
