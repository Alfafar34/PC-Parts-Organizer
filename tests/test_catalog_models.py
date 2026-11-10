"""Unit tests for catalog data models."""

try:
    import tests._pcpo_test_isolation_bootstrap  # noqa: F401
except Exception:
    import _pcpo_test_isolation_bootstrap  # type: ignore  # noqa: F401

import unittest
import uuid
from dataclasses import FrozenInstanceError

from pc_parts_organizer.catalog_models import (
    CatalogEntry,
    CatalogValidationError,
    catalog_duplicate_key,
)
from pc_parts_organizer.models import CATEGORIES


class TestCatalogEntry(unittest.TestCase):
    def test_creates_valid_entry(self) -> None:
        entry = CatalogEntry(
            category="CPU",
            manufacturer="AMD",
            model="Ryzen 7 7800X3D",
            specifications="8 cores",
            notes="Reference",
            source="Vendor",
            source_url="https://example.com/cpu",
            source_license="CC-BY-4.0",
            attribution="Example",
            verified_at="2026-01-15",
        )
        self.assertEqual(entry.category, "CPU")
        self.assertEqual(entry.manufacturer, "AMD")
        self.assertEqual(entry.model, "Ryzen 7 7800X3D")
        self.assertEqual(entry.specifications, "8 cores")
        self.assertEqual(entry.source_url, "https://example.com/cpu")
        self.assertEqual(entry.verified_at, "2026-01-15")
        self.assertEqual(uuid.UUID(entry.id).version, 4)

    def test_uuid_v4_generated_automatically(self) -> None:
        entry = CatalogEntry(category="GPU", manufacturer="NVIDIA", model="RTX 4070")
        self.assertEqual(uuid.UUID(entry.id).version, 4)

    def test_two_entries_receive_different_ids(self) -> None:
        first = CatalogEntry(category="RAM", manufacturer="Corsair", model="Vengeance")
        second = CatalogEntry(category="RAM", manufacturer="Corsair", model="Vengeance")
        self.assertNotEqual(first.id, second.id)

    def test_accepts_explicit_valid_uuid_v4(self) -> None:
        explicit = uuid.uuid4()
        entry = CatalogEntry(
            category="Storage",
            manufacturer="Samsung",
            model="990 Pro",
            id=explicit,
        )
        self.assertEqual(entry.id, str(explicit))

    def test_accepts_explicit_valid_uuid_v4_string(self) -> None:
        explicit = str(uuid.uuid4())
        entry = CatalogEntry(
            category="Storage",
            manufacturer="Samsung",
            model="990 Pro",
            id=explicit,
        )
        self.assertEqual(entry.id, explicit)

    def test_rejects_invalid_and_non_v4_uuid(self) -> None:
        with self.assertRaises(CatalogValidationError):
            CatalogEntry(category="CPU", manufacturer="A", model="B", id="not-a-uuid")
        with self.assertRaises(CatalogValidationError):
            CatalogEntry(category="CPU", manufacturer="A", model="B", id=str(uuid.uuid1()))
        with self.assertRaises(CatalogValidationError):
            CatalogEntry(category="CPU", manufacturer="A", model="B", id=123)  # type: ignore[arg-type]

    def test_accepts_and_normalizes_all_eleven_categories(self) -> None:
        for category in CATEGORIES:
            entry = CatalogEntry(category=category, manufacturer="Maker", model="Model")
            self.assertEqual(entry.category, category)
        entry = CatalogEntry(category="  motherboard  ", manufacturer="ASUS", model="B650")
        self.assertEqual(entry.category, "Motherboard")

    def test_rejects_empty_or_unknown_category(self) -> None:
        with self.assertRaises(CatalogValidationError):
            CatalogEntry(category="   ", manufacturer="Intel", model="i5")
        with self.assertRaises(CatalogValidationError):
            CatalogEntry(category="SoundCard", manufacturer="Creative", model="X")
        with self.assertRaises(CatalogValidationError):
            CatalogEntry(category=123, manufacturer="A", model="B")  # type: ignore[arg-type]

    def test_normalizes_required_fields_and_rejects_empty(self) -> None:
        entry = CatalogEntry(category="CPU", manufacturer="  AMD  ", model="  Ryzen  5  ")
        self.assertEqual(entry.manufacturer, "AMD")
        self.assertEqual(entry.model, "Ryzen  5")
        with self.assertRaises(CatalogValidationError):
            CatalogEntry(category="CPU", manufacturer="   ", model="B")
        with self.assertRaises(CatalogValidationError):
            CatalogEntry(category="CPU", manufacturer="A", model="   ")

    def test_optional_fields_accept_none_and_preserve_newlines(self) -> None:
        specs = "Line 1\n  Line 2\tTabbed"
        notes = "Note A\nNote B"
        attribution = "Attr\nLine"
        entry = CatalogEntry(
            category="Monitor",
            manufacturer="Dell",
            model="U2723QE",
            specifications=None,
            notes=notes,
            source=None,
            source_url=None,
            source_license=None,
            attribution=attribution,
            verified_at=None,
        )
        self.assertEqual(entry.specifications, "")
        self.assertEqual(entry.notes, notes)
        self.assertEqual(entry.source, "")
        self.assertEqual(entry.source_url, "")
        self.assertEqual(entry.source_license, "")
        self.assertEqual(entry.attribution, attribution)
        self.assertEqual(entry.verified_at, "")

    def test_rejects_incorrect_optional_types(self) -> None:
        with self.assertRaises(CatalogValidationError):
            CatalogEntry(category="CPU", manufacturer="A", model="B", specifications=123)  # type: ignore[arg-type]
        with self.assertRaises(CatalogValidationError):
            CatalogEntry(category="CPU", manufacturer="A", model="B", notes=[])  # type: ignore[arg-type]
        with self.assertRaises(CatalogValidationError):
            CatalogEntry(category="CPU", manufacturer="A", model="B", source_url=object())  # type: ignore[arg-type]

    def test_validates_verified_at_iso_date(self) -> None:
        ok = CatalogEntry(category="CPU", manufacturer="A", model="B", verified_at="2024-02-29")
        self.assertEqual(ok.verified_at, "2024-02-29")
        for bad in ("2024/01/01", "2024-13-01", "2023-02-29", "01-01-2024", "not-a-date"):
            with self.subTest(bad=bad):
                with self.assertRaises(CatalogValidationError):
                    CatalogEntry(category="CPU", manufacturer="A", model="B", verified_at=bad)

    def test_validates_source_url(self) -> None:
        ok = CatalogEntry(category="CPU", manufacturer="A", model="B", source_url="https://Example.com/path?q=1")
        self.assertEqual(ok.source_url, "https://Example.com/path?q=1")
        for bad in ("ftp://example.com", "http:/bad", "//example.com", "https://", "example.com", "not a url"):
            with self.subTest(bad=bad):
                with self.assertRaises(CatalogValidationError):
                    CatalogEntry(category="CPU", manufacturer="A", model="B", source_url=bad)

    def test_duplicate_keys_are_equivalent(self) -> None:
        a = CatalogEntry(category="GPU", manufacturer="  Nvidia  ", model="RTX  4070 ")
        b = CatalogEntry(category="gpu", manufacturer="NVIDIA", model="rtx 4070")
        c = CatalogEntry(category="GPU", manufacturer="AMD", model="RTX 4070")
        self.assertEqual(catalog_duplicate_key(a), catalog_duplicate_key(b))
        self.assertNotEqual(catalog_duplicate_key(a), catalog_duplicate_key(c))

    def test_is_frozen_dataclass(self) -> None:
        entry = CatalogEntry(category="CPU", manufacturer="A", model="B")
        with self.assertRaises((FrozenInstanceError, AttributeError)):
            entry.model = "C"  # type: ignore[misc]


if __name__ == "__main__":
    unittest.main()
