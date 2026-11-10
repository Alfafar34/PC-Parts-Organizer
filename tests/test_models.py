"""Unit tests for PC Parts Organizer data models."""

try:
    import tests._pcpo_test_isolation_bootstrap  # noqa: F401
except Exception:
    import _pcpo_test_isolation_bootstrap  # type: ignore  # noqa: F401

import unittest
import uuid

from pc_parts_organizer.models import (
    CATEGORIES,
    COMPONENT_STATUSES,
    MAX_LOCATION_LENGTH,
    Component,
    ComponentValidationError,
)


class TestCategories(unittest.TestCase):
    def test_canonical_categories_exact_order(self) -> None:
        expected = (
            "CPU",
            "GPU",
            "Motherboard",
            "RAM",
            "Storage",
            "PSU",
            "Case",
            "Cooling",
            "Monitor",
            "Peripheral",
            "Other",
        )
        self.assertEqual(CATEGORIES, expected)

    def test_categories_are_immutable_tuple(self) -> None:
        self.assertIsInstance(CATEGORIES, tuple)
        with self.assertRaises(TypeError):
            CATEGORIES[0] = "Changed"  # type: ignore[misc]


class TestComponent(unittest.TestCase):
    def test_create_valid_component(self) -> None:
        component = Component(
            category="CPU",
            manufacturer="AMD",
            model="Ryzen 7 7800X3D",
            specifications="8 cores",
            notes="Main build",
        )
        self.assertEqual(component.category, "CPU")
        self.assertEqual(component.manufacturer, "AMD")
        self.assertEqual(component.model, "Ryzen 7 7800X3D")
        self.assertEqual(component.specifications, "8 cores")
        self.assertEqual(component.notes, "Main build")
        parsed = uuid.UUID(component.id)
        self.assertEqual(parsed.version, 4)

    def test_generates_uuid_v4_automatically(self) -> None:
        component = Component(category="GPU", manufacturer="NVIDIA", model="RTX 4070")
        parsed = uuid.UUID(component.id)
        self.assertEqual(parsed.version, 4)

    def test_two_new_components_receive_different_ids(self) -> None:
        first = Component(category="RAM", manufacturer="Corsair", model="Vengeance")
        second = Component(category="RAM", manufacturer="Corsair", model="Vengeance")
        self.assertNotEqual(first.id, second.id)

    def test_accepts_all_eleven_canonical_categories(self) -> None:
        for category in CATEGORIES:
            component = Component(category=category, manufacturer="Maker", model="Model")
            self.assertEqual(component.category, category)

    def test_normalizes_category_case_insensitively(self) -> None:
        component = Component(category="  motherboard  ", manufacturer="ASUS", model="B650")
        self.assertEqual(component.category, "Motherboard")

    def test_rejects_empty_category(self) -> None:
        with self.assertRaises(ComponentValidationError):
            Component(category="   ", manufacturer="Intel", model="i5")

    def test_rejects_unknown_category(self) -> None:
        with self.assertRaises(ComponentValidationError):
            Component(category="SoundCard", manufacturer="Creative", model="X")

    def test_normalizes_manufacturer_and_model_outer_spaces(self) -> None:
        component = Component(category="Storage", manufacturer="  Samsung  ", model="  990 Pro  ")
        self.assertEqual(component.manufacturer, "Samsung")
        self.assertEqual(component.model, "990 Pro")

    def test_rejects_empty_manufacturer(self) -> None:
        with self.assertRaises(ComponentValidationError):
            Component(category="PSU", manufacturer="   ", model="RM750")

    def test_rejects_empty_model(self) -> None:
        with self.assertRaises(ComponentValidationError):
            Component(category="Case", manufacturer="Fractal", model="   ")

    def test_normalizes_specifications_and_notes_none_to_empty_string(self) -> None:
        component = Component(
            category="Cooling",
            manufacturer="Noctua",
            model="NH-D15",
            specifications=None,
            notes=None,
        )
        self.assertEqual(component.specifications, "")
        self.assertEqual(component.notes, "")

    def test_preserves_internal_newlines_in_specifications_and_notes(self) -> None:
        specs = "Line 1\n  Line 2\tTabbed"
        notes = "Note A\nNote B"
        component = Component(
            category="Monitor",
            manufacturer="Dell",
            model="U2723QE",
            specifications=specs,
            notes=notes,
        )
        self.assertEqual(component.specifications, specs)
        self.assertEqual(component.notes, notes)

    def test_rejects_incorrect_types(self) -> None:
        with self.assertRaises(ComponentValidationError):
            Component(category=123, manufacturer="A", model="B")  # type: ignore[arg-type]
        with self.assertRaises(ComponentValidationError):
            Component(category="CPU", manufacturer=None, model="B")  # type: ignore[arg-type]
        with self.assertRaises(ComponentValidationError):
            Component(category="CPU", manufacturer="A", model=["B"])  # type: ignore[arg-type]
        with self.assertRaises(ComponentValidationError):
            Component(category="CPU", manufacturer="A", model="B", specifications=123)  # type: ignore[arg-type]
        with self.assertRaises(ComponentValidationError):
            Component(category="CPU", manufacturer="A", model="B", notes=object())  # type: ignore[arg-type]

    def test_accepts_explicit_valid_uuid_v4(self) -> None:
        explicit = uuid.uuid4()
        component = Component(
            category="Peripheral",
            manufacturer="Logitech",
            model="MX Master",
            id=explicit,
        )
        self.assertEqual(component.id, str(explicit))

    def test_accepts_explicit_valid_uuid_v4_string(self) -> None:
        explicit = str(uuid.uuid4())
        component = Component(
            category="Peripheral",
            manufacturer="Logitech",
            model="MX Master",
            id=explicit,
        )
        self.assertEqual(component.id, explicit)

    def test_rejects_invalid_uuid_v4_identifiers(self) -> None:
        with self.assertRaises(ComponentValidationError):
            Component(category="CPU", manufacturer="A", model="B", id="not-a-uuid")
        with self.assertRaises(ComponentValidationError):
            Component(category="CPU", manufacturer="A", model="B", id=str(uuid.uuid1()))
        with self.assertRaises(ComponentValidationError):
            Component(category="CPU", manufacturer="A", model="B", id=123)  # type: ignore[arg-type]

    def test_status_and_location_defaults(self) -> None:
        component = Component(category="CPU", manufacturer="AMD", model="Ryzen 5")
        self.assertEqual(component.status, "unspecified")
        self.assertEqual(component.location, "")

    def test_status_canonical_values_accepted(self) -> None:
        self.assertEqual(
            COMPONENT_STATUSES,
            ("unspecified", "installed", "stored", "faulty", "under_repair", "loaned", "retired"),
        )
        for status in COMPONENT_STATUSES:
            component = Component(category="RAM", manufacturer="Corsair", model="X", status=status)
            self.assertEqual(component.status, status)

    def test_status_normalization_and_rejection(self) -> None:
        component = Component(category="CPU", manufacturer="AMD", model="X", status="  Installed  ")
        self.assertEqual(component.status, "installed")
        with self.assertRaises(ComponentValidationError):
            Component(category="CPU", manufacturer="AMD", model="X", status="broken")
        with self.assertRaises(ComponentValidationError):
            Component(category="CPU", manufacturer="AMD", model="X", status=123)  # type: ignore[arg-type]

    def test_location_normalization_and_limit(self) -> None:
        component = Component(category="CPU", manufacturer="AMD", model="X", location="  Desk  shelf  ")
        self.assertEqual(component.location, "Desk  shelf")
        component_none = Component(category="CPU", manufacturer="AMD", model="X", location=None)
        self.assertEqual(component_none.location, "")
        Component(category="CPU", manufacturer="AMD", model="X", location="x" * MAX_LOCATION_LENGTH)
        with self.assertRaises(ComponentValidationError):
            Component(category="CPU", manufacturer="AMD", model="X", location="x" * (MAX_LOCATION_LENGTH + 1))
        with self.assertRaises(ComponentValidationError):
            Component(category="CPU", manufacturer="AMD", model="X", location=123)  # type: ignore[arg-type]


    def test_purchase_warranty_dates_defaults_and_valid(self) -> None:
        c = Component(category="CPU", manufacturer="AMD", model="X")
        self.assertEqual(c.purchase_date, "")
        self.assertEqual(c.warranty_end_date, "")
        c = Component(category="CPU", manufacturer="AMD", model="X", purchase_date="2026-11-08", warranty_end_date="2028-11-08")
        self.assertEqual(c.purchase_date, "2026-11-08")
        self.assertEqual(c.warranty_end_date, "2028-11-08")
        c = Component(category="CPU", manufacturer="AMD", model="X", purchase_date=" 2030-01-01 ", warranty_end_date=None)
        self.assertEqual(c.purchase_date, "2030-01-01")
        self.assertEqual(c.warranty_end_date, "")
        # pre-sale / no relation constraint
        Component(category="CPU", manufacturer="AMD", model="X", purchase_date="2035-06-01", warranty_end_date="2020-01-01")

    def test_purchase_warranty_dates_invalid(self) -> None:
        bad = ["2026-02-30", "2026-13-01", "26-01-01", "2026/01/01", "20260101", "2026-1-1", "invalid", "2026-00-10"]
        for v in bad:
            with self.assertRaises(ComponentValidationError, msg=v):
                Component(category="CPU", manufacturer="AMD", model="X", purchase_date=v)
            with self.assertRaises(ComponentValidationError, msg=v):
                Component(category="CPU", manufacturer="AMD", model="X", warranty_end_date=v)
        with self.assertRaises(ComponentValidationError):
            Component(category="CPU", manufacturer="AMD", model="X", purchase_date=20261108)  # type: ignore[arg-type]
        # preserves previous fields
        c = Component(category="GPU", manufacturer="N", model="M", status="stored", location="Shelf", purchase_date="2024-05-05")
        self.assertEqual(c.status, "stored"); self.assertEqual(c.location, "Shelf"); self.assertEqual(c.purchase_date, "2024-05-05")

    def test_purchase_price_currency_defaults_and_normalization(self) -> None:
        c = Component(category="CPU", manufacturer="AMD", model="X")
        self.assertEqual(c.purchase_price, ""); self.assertEqual(c.purchase_currency, "")
        c = Component(category="CPU", manufacturer="AMD", model="X", purchase_price="149.90", purchase_currency="eur")
        self.assertEqual(c.purchase_price, "149.90"); self.assertEqual(c.purchase_currency, "EUR")
        c = Component(category="CPU", manufacturer="AMD", model="X", purchase_price="149,90", purchase_currency="usd")
        self.assertEqual(c.purchase_price, "149.90")
        c = Component(category="CPU", manufacturer="AMD", model="X", purchase_price="1250", purchase_currency="gbp")
        self.assertEqual(c.purchase_price, "1250")
        c = Component(category="CPU", manufacturer="AMD", model="X", purchase_price="12.345", purchase_currency="chf")
        self.assertEqual(c.purchase_price, "12.345")
        c = Component(category="CPU", manufacturer="AMD", model="X", purchase_price="0", purchase_currency="jpy")
        self.assertEqual(c.purchase_price, "0")
        c = Component(category="CPU", manufacturer="AMD", model="X", purchase_price="010.50", purchase_currency="EUR")
        self.assertEqual(c.purchase_price, "10.50")
        c = Component(category="CPU", manufacturer="AMD", model="X", purchase_price=None, purchase_currency=None)
        self.assertEqual(c.purchase_price, ""); self.assertEqual(c.purchase_currency, "")

    def test_purchase_price_currency_validation(self) -> None:
        # negative, scientific, decimals>4, integers>12, thousands/both separators
        bad_prices = ["-1", "1e2", "1E2", "1.23456", "1234567890123", "1,234.56", "1.234,56", "abc", "1..2"]
        for p in bad_prices:
            with self.assertRaises(ComponentValidationError, msg=p):
                Component(category="CPU", manufacturer="AMD", model="X", purchase_price=p, purchase_currency="EUR")
        # currency format
        for cur in ["EU", "EURO", "E1R", "12$", "???"]:
            with self.assertRaises(ComponentValidationError, msg=cur):
                Component(category="CPU", manufacturer="AMD", model="X", purchase_price="10", purchase_currency=cur)
        with self.assertRaises(ComponentValidationError):
            Component(category="CPU", manufacturer="AMD", model="X", purchase_price="10", purchase_currency=123)  # type: ignore[arg-type]
        # pair coherence
        with self.assertRaises(ComponentValidationError):
            Component(category="CPU", manufacturer="AMD", model="X", purchase_price="10", purchase_currency="")
        with self.assertRaises(ComponentValidationError):
            Component(category="CPU", manufacturer="AMD", model="X", purchase_price="", purchase_currency="EUR")
        # preserves previous fields
        c = Component(category="GPU", manufacturer="N", model="M", status="stored", location="Shelf", purchase_price="99.99", purchase_currency="USD")
        self.assertEqual(c.status, "stored"); self.assertEqual(c.purchase_price, "99.99"); self.assertEqual(c.purchase_currency, "USD")

if __name__ == "__main__":
    unittest.main()
