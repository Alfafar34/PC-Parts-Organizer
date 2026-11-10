"""Tests for technical profile models and registry (T17.1)."""

from __future__ import annotations

try:
    import tests._pcpo_test_isolation_bootstrap  # noqa: F401
except Exception:
    import _pcpo_test_isolation_bootstrap  # type: ignore  # noqa: F401

import unittest
import uuid

from pc_parts_organizer.technical_profiles import (
    PROFILE_VERSION,
    TechnicalAttribute,
    TechnicalProfile,
    TechnicalProfileValidationError,
    allowed_keys_for_category,
    parse_profile_dict,
    validate_profile_for_category,
)


def _cid():
    return str(uuid.uuid4())


class TestTechnicalProfileModels(unittest.TestCase):
    def test_ram_profile_valid_and_deterministic_serialization(self) -> None:
        p = TechnicalProfile(
            component_id=_cid(),
            attributes=[
                TechnicalAttribute(key="module_count", value=2, unit=None),
                TechnicalAttribute(key="memory_generation", value="ddr4", unit=None),
                TechnicalAttribute(key="total_capacity_gb", value=32, unit="GB"),
                TechnicalAttribute(key="module_form_factor", value="DIMM", unit=None),
            ],
        )
        self.assertEqual(p.profile_version, PROFILE_VERSION)
        self.assertEqual([a.key for a in p.attributes], ["memory_generation", "module_count", "module_form_factor", "total_capacity_gb"])
        self.assertEqual(p.attributes[0].value, "DDR4")
        d = p.to_dict()
        self.assertEqual([a["key"] for a in d["attributes"]], ["memory_generation", "module_count", "module_form_factor", "total_capacity_gb"])

    def test_defensive_copies(self) -> None:
        p = TechnicalProfile(
            component_id=_cid(),
            attributes=[TechnicalAttribute(key="memory_generation", value="DDR5")],
        )
        got = p.copy()
        got.attributes[0] = TechnicalAttribute(key="memory_generation", value="DDR2")
        self.assertEqual(p.attributes[0].value, "DDR5")
        d = p.to_dict()
        d["attributes"][0]["value"] = "DDR3"
        self.assertEqual(p.attributes[0].value, "DDR5")

    def test_defaults_provenance_confidence_verification(self) -> None:
        a = TechnicalAttribute(key="memory_generation", value="DDR4")
        self.assertEqual(a.source, "user_input")
        self.assertEqual(a.confidence, "medium")
        self.assertEqual(a.verification_status, "unverified")
        self.assertIsNone(a.original_value)
        self.assertIsNone(a.evidence_ref)
        self.assertIsNone(a.verified_at)

    def test_rejects_unknown_key_for_category(self) -> None:
        p = TechnicalProfile(component_id=_cid(), attributes=[TechnicalAttribute(key="memory_generation", value="DDR4")])
        with self.assertRaises(TechnicalProfileValidationError):
            validate_profile_for_category(p, "Case")

    def test_rejects_duplicate_keys(self) -> None:
        cid = _cid()
        with self.assertRaises(TechnicalProfileValidationError):
            TechnicalProfile(
                component_id=cid,
                attributes=[
                    TechnicalAttribute(key="memory_generation", value="DDR4"),
                    TechnicalAttribute(key="memory_generation", value="DDR5"),
                ],
            )

    def test_rejects_invalid_uuid_type_and_value(self) -> None:
        with self.assertRaises(TechnicalProfileValidationError):
            TechnicalProfile(component_id="not-a-uuid", attributes=[])
        with self.assertRaises(TechnicalProfileValidationError):
            TechnicalProfile(component_id=123, attributes=[])  # type: ignore[arg-type]
        with self.assertRaises(TechnicalProfileValidationError):
            TechnicalAttribute(key="memory_generation", value="DDR99")

    def test_motherboard_and_case_registry(self) -> None:
        self.assertIn("form_factor", allowed_keys_for_category("Motherboard"))
        self.assertIn("supported_motherboard_form_factors", allowed_keys_for_category("Case"))
        mb = parse_profile_dict(
            {
                "component_id": _cid(),
                "profile_version": 1,
                "attributes": [
                    {"key": "form_factor", "value": "micro-atx"},
                    {"key": "supported_memory_generations", "value": ["DDR5", "DDR4"]},
                    {"key": "supported_memory_module_form_factors", "value": ["DIMM"]},
                    {"key": "memory_slot_count", "value": 4},
                    {"key": "max_memory_capacity_gb", "value": 128, "unit": "GB"},
                ],
            },
            0,
            "Motherboard",
        )
        ff = next(a for a in mb.attributes if a.key == "form_factor").value
        self.assertEqual(ff, "Micro-ATX")
        gens = next(a for a in mb.attributes if a.key == "supported_memory_generations").value
        self.assertEqual(gens, ["DDR4", "DDR5"])  # deterministic normalized order

    def test_case_rejects_duplicate_list_values(self) -> None:
        with self.assertRaises(TechnicalProfileValidationError):
            parse_profile_dict(
                {
                    "component_id": _cid(),
                    "attributes": [{"key": "supported_motherboard_form_factors", "value": ["ATX", "ATX"]}],
                },
                0,
                "Case",
            )

    def test_rejects_nan_inf_bool_and_invalid_types(self) -> None:
        with self.assertRaises(TechnicalProfileValidationError):
            parse_profile_dict({"component_id": _cid(), "attributes": [{"key": "module_count", "value": True}]}, 0, "RAM")
        with self.assertRaises(TechnicalProfileValidationError):
            parse_profile_dict({"component_id": _cid(), "attributes": [{"key": "module_count", "value": "2"}]}, 0, "RAM")
        with self.assertRaises(TechnicalProfileValidationError):
            parse_profile_dict({"component_id": _cid(), "attributes": [{"key": "memory_generation", "value": "DDR9"}]}, 0, "RAM")

    def test_rejects_unknown_source_confidence_status(self) -> None:
        base = {"key": "memory_generation", "value": "DDR4"}
        with self.assertRaises(TechnicalProfileValidationError):
            TechnicalAttribute(**{**base, "source": "alien"})  # type: ignore[arg-type]
        with self.assertRaises(TechnicalProfileValidationError):
            TechnicalAttribute(**{**base, "confidence": "sure"})  # type: ignore[arg-type]
        with self.assertRaises(TechnicalProfileValidationError):
            TechnicalAttribute(**{**base, "verification_status": "yes"})  # type: ignore[arg-type]

    def test_verified_at_and_optional_fields(self) -> None:
        a = TechnicalAttribute(
            key="memory_generation",
            value="DDR4",
            original_value=" DDR4 ",
            evidence_ref=" https://example.invalid/spec ",
            verification_status="verified",
            verified_at="2026-01-02",
        )
        self.assertEqual(a.original_value, "DDR4")
        self.assertEqual(a.evidence_ref, "https://example.invalid/spec")
        self.assertEqual(a.verified_at, "2026-01-02")
        with self.assertRaises(TechnicalProfileValidationError):
            TechnicalAttribute(key="memory_generation", value="DDR4", verified_at="2026-02-30")

    def test_unknown_attribute_dict_key_rejected(self) -> None:
        with self.assertRaises(TechnicalProfileValidationError):
            parse_profile_dict(
                {"component_id": _cid(), "attributes": [{"key": "memory_generation", "value": "DDR4", "bogus": 1}]},
                0,
                "RAM",
            )


if __name__ == "__main__":
    unittest.main()
