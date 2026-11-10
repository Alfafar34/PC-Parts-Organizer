"""T17.5 technical profile registry/model extensions."""

from __future__ import annotations

try:
    import tests._pcpo_test_isolation_bootstrap  # noqa: F401
except Exception:
    import _pcpo_test_isolation_bootstrap  # type: ignore  # noqa: F401

import unittest
import uuid

from pc_parts_organizer.technical_profiles import (
    ATTRIBUTE_REGISTRY,
    PROFILE_REGISTRY_VERSION,
    PROFILE_VERSION,
    COOLER_TYPES,
    TechnicalAttribute,
    TechnicalProfile,
    TechnicalProfileValidationError,
    allowed_categories,
    allowed_keys_for_category,
    parse_profile_dict,
    validate_profile_for_category,
)


def _cid():
    return str(uuid.uuid4())


class TestT175Registry(unittest.TestCase):
    def test_registry_version_and_structural_version(self):
        self.assertEqual(PROFILE_VERSION, 2)
        self.assertGreaterEqual(PROFILE_REGISTRY_VERSION, 2)
        self.assertIn("CPU", ATTRIBUTE_REGISTRY)
        self.assertIn("GPU", ATTRIBUTE_REGISTRY)
        self.assertIn("Cooling", ATTRIBUTE_REGISTRY)

    def test_new_keys_by_category(self):
        self.assertEqual(allowed_keys_for_category("CPU"), ("socket_designation",))
        self.assertIn("card_length_mm", allowed_keys_for_category("GPU"))
        self.assertEqual(set(allowed_keys_for_category("Cooling")), {"cooler_type", "supported_cpu_sockets", "cooler_height_mm"})
        case = set(allowed_keys_for_category("Case"))
        self.assertIn("max_gpu_length_mm", case)
        self.assertIn("max_cpu_cooler_height_mm", case)
        self.assertIn("supported_motherboard_form_factors", case)

    def test_socket_identifier_normalization_canonical_no_alias(self):
        a = TechnicalAttribute(key="socket_designation", value="  lga 1700  ")
        self.assertEqual(a.value, "LGA 1700")
        b = TechnicalAttribute(key="socket_designation", value="AM5")
        self.assertEqual(b.value, "AM5")
        # no equivalence invented
        self.assertNotEqual(TechnicalAttribute(key="socket_designation", value="LGA1700").value,
                            TechnicalAttribute(key="socket_designation", value="LGA 1700").value)

    def test_socket_identifier_rejects_invalid(self):
        for bad in ("", "   ", "AM5\nX", "AM5\tX" if False else "\x01AM5", "A"*65):
            with self.assertRaises((TechnicalProfileValidationError, Exception)):
                TechnicalAttribute(key="socket_designation", value=bad)
        with self.assertRaises(TechnicalProfileValidationError):
            TechnicalAttribute(key="socket_designation", value=123)  # type: ignore

    def test_mm_positive_integers_and_units(self):
        a = TechnicalAttribute(key="card_length_mm", value=304, unit="mm")
        self.assertEqual(a.value, 304)
        self.assertEqual(a.unit, "mm")
        for key, cat in [("card_length_mm","GPU"), ("max_gpu_length_mm","Case"), ("max_cpu_cooler_height_mm","Case"), ("cooler_height_mm","Cooling")]:
            with self.assertRaises(TechnicalProfileValidationError):
                parse_profile_dict({"component_id": _cid(), "attributes": [{"key": key, "value": 0}]}, 0, cat)
            with self.assertRaises(TechnicalProfileValidationError):
                parse_profile_dict({"component_id": _cid(), "attributes": [{"key": key, "value": -1}]}, 0, cat)
            with self.assertRaises(TechnicalProfileValidationError):
                parse_profile_dict({"component_id": _cid(), "attributes": [{"key": key, "value": True}]}, 0, cat)
            with self.assertRaises(TechnicalProfileValidationError):
                parse_profile_dict({"component_id": _cid(), "attributes": [{"key": key, "value": "304"}]}, 0, cat)

    def test_cooling_types_and_socket_list(self):
        self.assertEqual(COOLER_TYPES, ("air_cpu_cooler","aio_cpu_cooler","custom_loop_cpu_cooler","case_fan","other"))
        p = parse_profile_dict({"component_id": _cid(), "attributes": [
            {"key": "cooler_type", "value": "air_cpu_cooler"},
            {"key": "supported_cpu_sockets", "value": ["am5", " lga1700 ", "AM4"]},
            {"key": "cooler_height_mm", "value": 155, "unit": "mm"},
        ]}, 0, "Cooling")
        sockets = next(a for a in p.attributes if a.key == "supported_cpu_sockets").value
        self.assertEqual(sockets, ["AM4", "AM5", "LGA1700"])  # normalized, sorted
        with self.assertRaises(TechnicalProfileValidationError):
            parse_profile_dict({"component_id": _cid(), "attributes": [{"key": "supported_cpu_sockets", "value": []}]}, 0, "Cooling")
        with self.assertRaises(TechnicalProfileValidationError):
            parse_profile_dict({"component_id": _cid(), "attributes": [{"key": "supported_cpu_sockets", "value": ["AM5", "am5"]}]}, 0, "Cooling")

    def test_old_profiles_still_valid(self):
        # T17.1/T17.2 style profiles remain readable/valid under later registry versions
        ram = parse_profile_dict({"component_id": _cid(), "profile_version": 1, "attributes": [
            {"key":"memory_generation","value":"DDR4"},{"key":"module_form_factor","value":"DIMM"},
            {"key":"total_capacity_gb","value":16,"unit":"GB"},{"key":"module_count","value":2}
        ]}, 0, "RAM")
        self.assertEqual(ram.profile_version, 1)
        mb = parse_profile_dict({"component_id": _cid(), "attributes": [
            {"key":"form_factor","value":"ATX"},{"key":"memory_slot_count","value":4},
            {"key":"supported_memory_generations","value":["DDR5"]},{"key":"supported_memory_module_form_factors","value":["DIMM"]},
            {"key":"max_memory_capacity_gb","value":128,"unit":"GB"}
        ]}, 0, "Motherboard")
        self.assertEqual(mb.profile_version, PROFILE_VERSION)
        case = parse_profile_dict({"component_id": _cid(), "attributes": [{"key":"supported_motherboard_form_factors","value":["ATX"]}]}, 0, "Case")
        self.assertEqual(len(case.attributes), 1)

    def test_category_isolation(self):
        with self.assertRaises(TechnicalProfileValidationError):
            parse_profile_dict({"component_id": _cid(), "attributes": [{"key":"card_length_mm","value":300}]}, 0, "Case")
        with self.assertRaises(TechnicalProfileValidationError):
            parse_profile_dict({"component_id": _cid(), "attributes": [{"key":"socket_designation","value":"AM5"}]}, 0, "GPU")
        p = TechnicalProfile(component_id=_cid(), attributes=[TechnicalAttribute(key="card_length_mm", value=300, unit="mm")])
        with self.assertRaises(TechnicalProfileValidationError):
            validate_profile_for_category(p, "CPU")

    def test_case_new_physical_attributes(self):
        p = parse_profile_dict({"component_id": _cid(), "attributes": [
            {"key":"supported_motherboard_form_factors","value":["ATX"]},
            {"key":"max_gpu_length_mm","value":360,"unit":"mm"},
            {"key":"max_cpu_cooler_height_mm","value":170,"unit":"mm"},
        ]}, 0, "Case")
        keys = {a.key for a in p.attributes}
        self.assertEqual(keys, {"max_cpu_cooler_height_mm","max_gpu_length_mm","supported_motherboard_form_factors"})


if __name__ == "__main__":
    unittest.main()
