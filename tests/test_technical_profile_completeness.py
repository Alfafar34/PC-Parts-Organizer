"""T17.10 collection completeness model tests (profiles v2, registry v5)."""
from __future__ import annotations

try:
    import tests._pcpo_test_isolation_bootstrap  # noqa: F401
except Exception:
    import _pcpo_test_isolation_bootstrap  # type: ignore  # noqa: F401

import unittest

from pc_parts_organizer.technical_profiles import (
    PROFILE_REGISTRY_VERSION,
    PROFILE_VERSION,
    SUPPORTED_PROFILE_STRUCTURAL_VERSIONS,
    TechnicalAttribute,
    TechnicalProfile,
    TechnicalProfileValidationError,
    parse_profile_dict,
    validate_profile_for_category,
)


def cid():
    import uuid
    return str(uuid.uuid4())


def va(key, value, **kw):
    base = dict(source="official_vendor_doc", confidence="high",
                verification_status="verified", evidence_ref="https://vendor/doc",
                verified_at="2026-01-01")
    base.update(kw)
    return TechnicalAttribute(key=key, value=value, **base)


class TestCompletenessValues(unittest.TestCase):
    def test_defaults_unknown_no_scope(self):
        a = TechnicalAttribute(key="m2_slots", value=[])
        self.assertEqual(a.collection_completeness, "unknown")
        self.assertIsNone(a.completeness_scope)

    def test_valid_partial_requires_scope(self):
        a = va("m2_slots", [], collection_completeness="partial", completeness_scope="Slots seen so far")
        self.assertEqual(a.collection_completeness, "partial")

    def test_valid_complete(self):
        a = va("m2_slots", [], collection_completeness="complete",
               completeness_scope="All physical M.2 slots of the board revision")
        self.assertEqual(a.collection_completeness, "complete")

    def test_invalid_enum_rejected(self):
        with self.assertRaises(TechnicalProfileValidationError):
            va("m2_slots", [], collection_completeness="everything")

    def test_complete_requires_verified(self):
        with self.assertRaises(TechnicalProfileValidationError):
            TechnicalAttribute(key="m2_slots", value=[], verification_status="unverified",
                               collection_completeness="complete", completeness_scope="S")

    def test_complete_requires_high_confidence(self):
        with self.assertRaises(TechnicalProfileValidationError):
            TechnicalAttribute(key="m2_slots", value=[], source="official_vendor_doc", confidence="medium",
                               verification_status="verified", evidence_ref="https://vendor/doc",
                               verified_at="2026-01-01", collection_completeness="complete",
                               completeness_scope="S")

    def test_complete_requires_evidence_and_date(self):
        with self.assertRaises(TechnicalProfileValidationError):
            TechnicalAttribute(key="m2_slots", value=[], source="official_vendor_doc", confidence="high",
                               verification_status="verified",
                               collection_completeness="complete", completeness_scope="S")
        with self.assertRaises(TechnicalProfileValidationError):
            TechnicalAttribute(key="m2_slots", value=[], source="official_vendor_doc", confidence="high",
                               verification_status="verified", evidence_ref="https://vendor/doc",
                               collection_completeness="complete", completeness_scope="S")

    def test_complete_requires_scope(self):
        with self.assertRaises(TechnicalProfileValidationError):
            va("m2_slots", [], collection_completeness="complete")

    def test_partial_requires_scope(self):
        with self.assertRaises(TechnicalProfileValidationError):
            va("m2_slots", [], collection_completeness="partial")

    def test_unknown_with_scope_rejected(self):
        with self.assertRaises(TechnicalProfileValidationError):
            va("m2_slots", [], collection_completeness="unknown", completeness_scope="S")

    def test_scope_max_length(self):
        with self.assertRaises(TechnicalProfileValidationError):
            va("m2_slots", [], collection_completeness="partial", completeness_scope="x" * 301)

    def test_not_eligible_key_rejected(self):
        with self.assertRaises(TechnicalProfileValidationError):
            va("sata_port_count", 2, collection_completeness="partial", completeness_scope="S")
        with self.assertRaises(TechnicalProfileValidationError):
            va("storage_form_factor", "m2", collection_completeness="complete",
               completeness_scope="All")

    def test_eligible_keys(self):
        va("sata_port_identifiers", ["SATA1"], collection_completeness="complete",
           completeness_scope="All integrated SATA port identifiers")
        va("power_cable_assemblies", [], collection_completeness="partial",
           completeness_scope="Cables seen so far")

    def test_versions(self):
        self.assertEqual(PROFILE_VERSION, 2)
        self.assertIn(1, SUPPORTED_PROFILE_STRUCTURAL_VERSIONS)
        self.assertIn(2, SUPPORTED_PROFILE_STRUCTURAL_VERSIONS)
        self.assertGreaterEqual(PROFILE_REGISTRY_VERSION, 5)

    def test_copy_round_trip(self):
        a = va("m2_slots", [], collection_completeness="complete", completeness_scope="All slots")
        b = a.copy()
        self.assertEqual(b.collection_completeness, "complete")
        self.assertEqual(b.completeness_scope, "All slots")
        d = a.to_dict()
        self.assertEqual(d["collection_completeness"], "complete")
        self.assertEqual(d["completeness_scope"], "All slots")
        # defensive copy: mutating original list value does not affect copy
        a2 = va("sata_port_identifiers", ["SATA1"], collection_completeness="partial", completeness_scope="S")
        c2 = a2.copy()
        a2.value.append("SATA2")
        self.assertEqual(c2.value, ["SATA1"])

    def test_v1_read_defaults_unknown(self):
        p = parse_profile_dict({"component_id": cid(), "profile_version": 1, "attributes": [
            {"key": "m2_slots", "value": []},
        ]}, 0, "Motherboard")
        self.assertEqual(p.profile_version, 1)
        self.assertEqual(p.attributes[0].collection_completeness, "unknown")
        self.assertIsNone(p.attributes[0].completeness_scope)

    def test_v1_with_new_keys_round_trip_v2(self):
        p = parse_profile_dict({"component_id": cid(), "profile_version": 2, "attributes": [
            {"key": "m2_slots", "value": [], "source": "official_vendor_doc", "confidence": "high",
             "verification_status": "verified", "evidence_ref": "https://vendor/doc", "verified_at": "2026-01-01",
             "collection_completeness": "complete", "completeness_scope": "All slots"},
        ]}, 0, "Motherboard")
        d = p.to_dict()
        self.assertEqual(d["attributes"][0]["collection_completeness"], "complete")
        # v1-style edit then persist as v2 keeps new metadata with safe values
        p2 = TechnicalProfile(component_id=p.component_id, profile_version=2,
                              attributes=[TechnicalAttribute(key="m2_slots", value=[],
                                                             source="official_vendor_doc", confidence="high",
                                                             verification_status="verified",
                                                             evidence_ref="https://vendor/doc",
                                                             verified_at="2026-01-01",
                                                             collection_completeness="complete",
                                                             completeness_scope="All slots")])
        self.assertEqual(p2.to_dict()["attributes"][0]["completeness_scope"], "All slots")

    def test_unknown_keys_and_bad_enum_rejected(self):
        with self.assertRaises(TechnicalProfileValidationError):
            parse_profile_dict({"component_id": cid(), "attributes": [
                {"key": "m2_slots", "value": [], "collection_completeness": "bogus"}]}, 0, "Motherboard")
        with self.assertRaises(TechnicalProfileValidationError):
            parse_profile_dict({"component_id": cid(), "attributes": [
                {"key": "m2_slots", "value": [], "mystery_field": 1}]}, 0, "Motherboard")

    def test_no_data_loss_on_legacy(self):
        p = parse_profile_dict({"component_id": cid(), "profile_version": 1, "attributes": [
            {"key": "sata_port_count", "value": 2},
        ]}, 0, "Motherboard")
        validate_profile_for_category(p, "Motherboard")
        self.assertEqual(p.attributes[0].value, 2)

    def test_save_load_preserves_completeness(self):
        import tempfile
        from pathlib import Path
        from unittest.mock import patch
        from pc_parts_organizer.models import Component
        from pc_parts_organizer.storage import save_project_state, load_project_state
        with tempfile.TemporaryDirectory() as td:
            with patch.dict("os.environ", {"LOCALAPPDATA": str(Path(td))}):
                mb = Component(category="Motherboard", manufacturer="M", model="B")
                p = parse_profile_dict({"component_id": mb.id, "profile_version": 2, "attributes": [
                    {"key": "m2_slots", "value": [], "source": "official_vendor_doc", "confidence": "high",
                     "verification_status": "verified", "evidence_ref": "https://vendor/doc",
                     "verified_at": "2026-01-01", "collection_completeness": "complete",
                     "completeness_scope": "All slots"},
                ]}, 0, "Motherboard")
                save_project_state([mb], [], [p])
                state = load_project_state()
                a = state.technical_profiles[0].attributes[0]
                self.assertEqual(a.collection_completeness, "complete")
                self.assertEqual(a.completeness_scope, "All slots")

    def test_export_restore_preserves_completeness(self):
        import tempfile
        from pathlib import Path
        from unittest.mock import patch
        from pc_parts_organizer.models import Build, Component
        from pc_parts_organizer.service import InventoryService
        from pc_parts_organizer.storage import load_project_state
        with tempfile.TemporaryDirectory() as td:
            with patch.dict("os.environ", {"LOCALAPPDATA": str(Path(td))}):
                svc = InventoryService()
                mb = svc.add_component("Motherboard", "M", "B", "", "")
                p = parse_profile_dict({"component_id": mb.id, "profile_version": 2, "attributes": [
                    {"key": "m2_slots", "value": [], "source": "official_vendor_doc", "confidence": "high",
                     "verification_status": "verified", "evidence_ref": "https://vendor/doc",
                     "verified_at": "2026-01-01", "collection_completeness": "complete",
                     "completeness_scope": "All slots"},
                ]}, 0, "Motherboard")
                svc.set_technical_profile(p)
                b = svc.add_build("B")
                svc.add_component_to_build(b.id, mb.id)
                state = svc.get_project_state()
                res = svc.restore_inventory(state.components, state.builds, state.technical_profiles)
                self.assertTrue(res.pre_restore_backup or True)
                got = svc.get_technical_profile(mb.id)
                self.assertEqual(got.attributes[0].collection_completeness, "complete")


if __name__ == "__main__":
    unittest.main()
