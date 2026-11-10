"""Unit tests for the inventory service."""

try:
    import tests._pcpo_test_isolation_bootstrap  # noqa: F401
except Exception:
    import _pcpo_test_isolation_bootstrap  # type: ignore  # noqa: F401

import ast
import inspect
import pathlib
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from pc_parts_organizer.models import CATEGORIES, Component, ComponentValidationError
from pc_parts_organizer.service import (
    ComponentNotFoundError,
    InventoryService,
    InventorySummary,
)
from pc_parts_organizer.storage import StorageError


class TestInventoryService(unittest.TestCase):
    def _component(self, **overrides):
        data = {
            "category": "CPU",
            "manufacturer": "AMD",
            "model": "Ryzen 5",
            "specifications": "",
            "notes": "",
        }
        data.update(overrides)
        return Component(**data)

    @patch("pc_parts_organizer.service.save_components")
    @patch("pc_parts_organizer.service.load_components")
    def test_constructor_loads_inventory(self, mock_load, mock_save) -> None:
        loaded = [self._component(model="Loaded")]
        mock_load.return_value = loaded
        service = InventoryService()
        components = service.get_components()
        self.assertEqual(len(components), 1)
        self.assertEqual(components[0].model, "Loaded")
        mock_load.assert_called_once_with()
        mock_save.assert_not_called()

    @patch("pc_parts_organizer.service.save_components")
    @patch("pc_parts_organizer.service.load_components")
    def test_constructor_propagates_storage_error(self, mock_load, mock_save) -> None:
        mock_load.side_effect = StorageError("boom")
        with self.assertRaises(StorageError):
            InventoryService()
        mock_save.assert_not_called()

    @patch("pc_parts_organizer.service.save_components")
    @patch("pc_parts_organizer.service.load_components")
    def test_get_components_returns_copies(self, mock_load, mock_save) -> None:
        mock_load.return_value = [self._component(model="Original")]
        service = InventoryService()
        components = service.get_components()
        components[0].model = "Mutated"
        components.append(self._component(model="Extra"))
        self.assertEqual(service.get_components()[0].model, "Original")
        self.assertEqual(len(service.get_components()), 1)
        mock_save.assert_not_called()

    @patch("pc_parts_organizer.service.save_components")
    @patch("pc_parts_organizer.service.load_components")
    def test_get_component_returns_copy_or_none(self, mock_load, mock_save) -> None:
        component = self._component(model="Target")
        mock_load.return_value = [component]
        service = InventoryService()
        found = service.get_component(component.id)
        self.assertIsNotNone(found)
        assert found is not None
        self.assertEqual(found.id, component.id)
        found.model = "Mutated"
        self.assertEqual(service.get_component(component.id).model, "Target")
        self.assertIsNone(service.get_component("00000000-0000-4000-8000-000000000000"))
        mock_save.assert_not_called()

    @patch("pc_parts_organizer.service.save_components")
    @patch("pc_parts_organizer.service.load_components")
    def test_add_component_saves_then_commits(self, mock_load, mock_save) -> None:
        mock_load.return_value = []
        service = InventoryService()
        created = service.add_component(
            category="cpu",
            manufacturer="  Intel  ",
            model="  Core i5  ",
            specifications=None,
            notes="note",
        )
        self.assertEqual(created.category, "CPU")
        self.assertEqual(created.manufacturer, "Intel")
        self.assertEqual(created.model, "Core i5")
        self.assertEqual(created.specifications, "")
        self.assertEqual(created.notes, "note")
        self.assertRegex(created.id, r"^[0-9a-f-]{36}$")
        mock_save.assert_called_once()
        saved = mock_save.call_args.args[0]
        self.assertEqual(len(saved), 1)
        self.assertEqual(saved[0].id, created.id)
        stored = service.get_component(created.id)
        assert stored is not None
        self.assertEqual(stored.model, "Core i5")

    @patch("pc_parts_organizer.service.save_components")
    @patch("pc_parts_organizer.service.load_components")
    def test_add_component_returns_independent_copy(self, mock_load, mock_save) -> None:
        mock_load.return_value = []
        service = InventoryService()
        created = service.add_component("RAM", "Corsair", "Vengeance")
        created.model = "Mutated"
        self.assertEqual(service.get_component(created.id).model, "Vengeance")

    @patch("pc_parts_organizer.service.save_components")
    @patch("pc_parts_organizer.service.load_components")
    def test_add_validation_failure_does_not_save(self, mock_load, mock_save) -> None:
        mock_load.return_value = []
        service = InventoryService()
        with self.assertRaises(ComponentValidationError):
            service.add_component("BadCategory", "Intel", "i5")
        mock_save.assert_not_called()
        self.assertEqual(service.get_components(), [])

    @patch("pc_parts_organizer.service.save_components")
    @patch("pc_parts_organizer.service.load_components")
    def test_add_storage_error_does_not_commit(self, mock_load, mock_save) -> None:
        mock_load.return_value = []
        mock_save.side_effect = StorageError("disk")
        service = InventoryService()
        with self.assertRaises(StorageError):
            service.add_component("GPU", "NVIDIA", "RTX")
        self.assertEqual(service.get_components(), [])

    @patch("pc_parts_organizer.service.save_components")
    @patch("pc_parts_organizer.service.load_components")
    def test_update_component_saves_then_commits_and_keeps_id(self, mock_load, mock_save) -> None:
        original = self._component(manufacturer="Old", model="Old")
        mock_load.return_value = [original]
        service = InventoryService()
        updated = service.update_component(
            original.id,
            category="gpu",
            manufacturer="NVIDIA",
            model="RTX 4070",
            specifications="12GB",
            notes="",
        )
        self.assertEqual(updated.id, original.id)
        self.assertEqual(updated.category, "GPU")
        self.assertEqual(updated.model, "RTX 4070")
        mock_save.assert_called_once()
        saved = mock_save.call_args.args[0]
        self.assertEqual(saved[0].id, original.id)
        self.assertEqual(service.get_component(original.id).model, "RTX 4070")

    @patch("pc_parts_organizer.service.save_components")
    @patch("pc_parts_organizer.service.load_components")
    def test_update_missing_id_raises_and_does_not_save(self, mock_load, mock_save) -> None:
        mock_load.return_value = [self._component()]
        service = InventoryService()
        with self.assertRaises(ComponentNotFoundError):
            service.update_component(
                "00000000-0000-4000-8000-000000000000", "CPU", "A", "B"
            )
        mock_save.assert_not_called()

    @patch("pc_parts_organizer.service.save_components")
    @patch("pc_parts_organizer.service.load_components")
    def test_update_validation_failure_does_not_change_state(self, mock_load, mock_save) -> None:
        original = self._component(model="Keep")
        mock_load.return_value = [original]
        service = InventoryService()
        with self.assertRaises(ComponentValidationError):
            service.update_component(original.id, "CPU", "", "B")
        mock_save.assert_not_called()
        self.assertEqual(service.get_component(original.id).model, "Keep")

    @patch("pc_parts_organizer.service.save_components")
    @patch("pc_parts_organizer.service.load_components")
    def test_update_storage_error_keeps_original(self, mock_load, mock_save) -> None:
        original = self._component(model="Keep")
        mock_load.return_value = [original]
        mock_save.side_effect = StorageError("disk")
        service = InventoryService()
        with self.assertRaises(StorageError):
            service.update_component(original.id, "CPU", "Intel", "New")
        self.assertEqual(service.get_component(original.id).model, "Keep")

    @patch("pc_parts_organizer.service.save_components")
    @patch("pc_parts_organizer.service.load_components")
    def test_delete_component_saves_then_commits(self, mock_load, mock_save) -> None:
        target = self._component(model="Delete me")
        keep = self._component(model="Keep")
        mock_load.return_value = [target, keep]
        service = InventoryService()
        service.delete_component(target.id)
        mock_save.assert_called_once()
        saved = mock_save.call_args.args[0]
        self.assertEqual([c.id for c in saved], [keep.id])
        self.assertIsNone(service.get_component(target.id))
        self.assertEqual(len(service.get_components()), 1)

    @patch("pc_parts_organizer.service.save_components")
    @patch("pc_parts_organizer.service.load_components")
    def test_delete_last_component_saves_empty_list(self, mock_load, mock_save) -> None:
        target = self._component()
        mock_load.return_value = [target]
        service = InventoryService()
        service.delete_component(target.id)
        self.assertEqual(mock_save.call_args.args[0], [])
        self.assertEqual(service.get_components(), [])

    @patch("pc_parts_organizer.service.save_components")
    @patch("pc_parts_organizer.service.load_components")
    def test_delete_missing_id_raises_and_does_not_save(self, mock_load, mock_save) -> None:
        mock_load.return_value = [self._component()]
        service = InventoryService()
        with self.assertRaises(ComponentNotFoundError):
            service.delete_component("00000000-0000-4000-8000-000000000000")
        mock_save.assert_not_called()

    @patch("pc_parts_organizer.service.save_components")
    @patch("pc_parts_organizer.service.load_components")
    def test_delete_storage_error_preserves_inventory(self, mock_load, mock_save) -> None:
        target = self._component()
        mock_load.return_value = [target]
        mock_save.side_effect = StorageError("disk")
        service = InventoryService()
        with self.assertRaises(StorageError):
            service.delete_component(target.id)
        self.assertIsNotNone(service.get_component(target.id))



    @patch("pc_parts_organizer.service.save_components")
    @patch("pc_parts_organizer.service.load_components")
    def test_add_component_defaults_status_and_location(self, mock_load, mock_save) -> None:
        mock_load.return_value = []
        service = InventoryService()
        created = service.add_component("CPU", "AMD", "Ryzen")
        self.assertEqual(created.status, "unspecified")
        self.assertEqual(created.location, "")
        saved = mock_save.call_args[0][0][0]
        self.assertEqual(saved.status, "unspecified")
        self.assertEqual(saved.location, "")

    @patch("pc_parts_organizer.service.save_components")
    @patch("pc_parts_organizer.service.load_components")
    def test_add_and_update_component_with_status_location(self, mock_load, mock_save) -> None:
        mock_load.return_value = []
        service = InventoryService()
        created = service.add_component("CPU", "AMD", "Ryzen", status="stored", location="  Shelf  ")
        self.assertEqual(created.status, "stored")
        self.assertEqual(created.location, "Shelf")
        updated = service.update_component(
            created.id,
            "CPU",
            "AMD",
            "Ryzen 7",
            specifications="8c",
            notes="n",
            status="installed",
            location="Desk",
        )
        self.assertEqual(updated.status, "installed")
        self.assertEqual(updated.location, "Desk")
        self.assertEqual(updated.id, created.id)

    @patch("pc_parts_organizer.service.save_components")
    @patch("pc_parts_organizer.service.load_components")
    def test_update_omitting_new_params_preserves_existing(self, mock_load, mock_save) -> None:
        existing = self._component(id="550e8400-e29b-41d4-a716-446655440000", status="loaned", location="Lab")
        mock_load.return_value = [existing]
        service = InventoryService()
        updated = service.update_component(
            existing.id,
            "CPU",
            "AMD",
            "Ryzen Updated",
            specifications="new",
            notes="note",
        )
        self.assertEqual(updated.status, "loaned")
        self.assertEqual(updated.location, "Lab")
        self.assertEqual(updated.model, "Ryzen Updated")

    @patch("pc_parts_organizer.service.save_components")
    @patch("pc_parts_organizer.service.load_components")
    def test_update_can_set_empty_location_and_unspecified_explicitly(self, mock_load, mock_save) -> None:
        existing = self._component(id="550e8400-e29b-41d4-a716-446655440000", status="stored", location="Shelf")
        mock_load.return_value = [existing]
        service = InventoryService()
        updated = service.update_component(
            existing.id, "CPU", "AMD", "Ryzen", "", "", status="unspecified", location=""
        )
        self.assertEqual(updated.status, "unspecified")
        self.assertEqual(updated.location, "")


    @patch("pc_parts_organizer.service.save_components")
    @patch("pc_parts_organizer.service.load_components")
    def test_add_update_dates_and_preserve_clear(self, mock_load, mock_save) -> None:
        mock_load.return_value = []
        service = InventoryService()
        created = service.add_component("CPU", "AMD", "Ryzen", purchase_date="2024-01-01", warranty_end_date="2026-01-01")
        self.assertEqual(created.purchase_date, "2024-01-01")
        self.assertEqual(created.warranty_end_date, "2026-01-01")
        # omit dates -> preserve
        updated = service.update_component(created.id, "CPU", "AMD", "Ryzen", status="stored")
        self.assertEqual(updated.purchase_date, "2024-01-01")
        self.assertEqual(updated.warranty_end_date, "2026-01-01")
        self.assertEqual(updated.status, "stored")
        # explicit clear
        cleared = service.update_component(created.id, "CPU", "AMD", "Ryzen", purchase_date="", warranty_end_date="")
        self.assertEqual(cleared.purchase_date, "")
        self.assertEqual(cleared.warranty_end_date, "")
        self.assertEqual(cleared.id, created.id)


    @patch("pc_parts_organizer.service.save_components")
    @patch("pc_parts_organizer.service.load_components")
    def test_add_update_price_currency_preserve_clear_and_pair(self, mock_load, mock_save) -> None:
        mock_load.return_value = []
        service = InventoryService()
        created = service.add_component("CPU", "AMD", "Ryzen", purchase_price="149,90", purchase_currency="eur")
        self.assertEqual(created.purchase_price, "149.90")
        self.assertEqual(created.purchase_currency, "EUR")
        # omit preserves
        updated = service.update_component(created.id, "CPU", "AMD", "Ryzen", status="stored")
        self.assertEqual(updated.purchase_price, "149.90")
        self.assertEqual(updated.purchase_currency, "EUR")
        # explicit joint clear
        cleared = service.update_component(created.id, "CPU", "AMD", "Ryzen", purchase_price="", purchase_currency="")
        self.assertEqual(cleared.purchase_price, "")
        self.assertEqual(cleared.purchase_currency, "")
        self.assertEqual(cleared.id, created.id)
        # incomplete pair rejected, state not committed
        with self.assertRaises(ComponentValidationError):
            service.update_component(created.id, "CPU", "AMD", "Ryzen", purchase_price="10", purchase_currency="")
        self.assertEqual(service.get_component(created.id).purchase_price, "")

class TestInventorySummaryAndErrors(unittest.TestCase):
    def _component(self, **overrides):
        data = {
            "category": "CPU",
            "manufacturer": "AMD",
            "model": "Ryzen 5",
            "specifications": "",
            "notes": "",
        }
        data.update(overrides)
        return Component(**data)

    @patch("pc_parts_organizer.service.save_components")
    @patch("pc_parts_organizer.service.load_components")
    def test_empty_inventory_summary(self, mock_load, mock_save) -> None:
        mock_load.return_value = []
        service = InventoryService()
        summary = service.get_summary()
        self.assertIsInstance(summary, InventorySummary)
        self.assertEqual(summary.total_count, 0)
        self.assertEqual(summary.category_counts, {})
        mock_save.assert_not_called()

    @patch("pc_parts_organizer.service.save_components")
    @patch("pc_parts_organizer.service.load_components")
    def test_summary_counts_totals_groups_and_order(self, mock_load, mock_save) -> None:
        mock_load.return_value = [
            self._component(category="GPU"),
            self._component(category="CPU"),
            self._component(category="GPU"),
            self._component(category="RAM"),
        ]
        service = InventoryService()
        summary = service.get_summary()
        self.assertEqual(summary.total_count, 4)
        self.assertEqual(summary.category_counts, {"CPU": 1, "GPU": 2, "RAM": 1})
        self.assertEqual(list(summary.category_counts.keys()), ["CPU", "GPU", "RAM"])
        self.assertTrue(set(summary.category_counts.keys()).issubset(set(CATEGORIES)))
        for category in summary.category_counts:
            self.assertGreater(summary.category_counts[category], 0)

    @patch("pc_parts_organizer.service.save_components")
    @patch("pc_parts_organizer.service.load_components")
    def test_summary_reflects_add_update_delete(self, mock_load, mock_save) -> None:
        original = self._component(category="CPU", model="Old")
        mock_load.return_value = [original]
        service = InventoryService()

        added = service.add_component("GPU", "NVIDIA", "RTX")
        summary = service.get_summary()
        self.assertEqual(summary.total_count, 2)
        self.assertEqual(summary.category_counts, {"CPU": 1, "GPU": 1})

        service.update_component(added.id, "RAM", "Corsair", "Vengeance")
        summary = service.get_summary()
        self.assertEqual(summary.category_counts, {"CPU": 1, "RAM": 1})

        service.delete_component(original.id)
        summary = service.get_summary()
        self.assertEqual(summary.total_count, 1)
        self.assertEqual(summary.category_counts, {"RAM": 1})

    @patch("pc_parts_organizer.service.save_components")
    @patch("pc_parts_organizer.service.load_components")
    def test_summary_is_isolated_and_independent(self, mock_load, mock_save) -> None:
        mock_load.return_value = [self._component(category="CPU")]
        service = InventoryService()
        summary = service.get_summary()
        summary.category_counts["CPU"] = 999
        summary.category_counts["GPU"] = 1
        fresh = service.get_summary()
        self.assertEqual(fresh.total_count, 1)
        self.assertEqual(fresh.category_counts, {"CPU": 1})

    @patch("pc_parts_organizer.service.save_components")
    @patch("pc_parts_organizer.service.load_components")
    def test_summary_is_global_and_has_no_filter_parameters(self, mock_load, mock_save) -> None:
        mock_load.return_value = [self._component(category="CPU"), self._component(category="GPU")]
        service = InventoryService()
        self.assertEqual(inspect.signature(service.get_summary).parameters, {})
        summary = service.get_summary()
        self.assertEqual(summary.total_count, 2)
        mock_load.assert_called_once_with()
        mock_save.assert_not_called()

    @patch("pc_parts_organizer.service.save_components")
    @patch("pc_parts_organizer.service.load_components")
    def test_error_contract_propagates_expected_exceptions(self, mock_load, mock_save) -> None:
        mock_load.return_value = [self._component()]
        service = InventoryService()

        with self.assertRaises(ComponentValidationError):
            service.add_component("CPU", "", "Model")

        mock_save.side_effect = StorageError("disk")
        with self.assertRaises(StorageError):
            service.add_component("CPU", "Intel", "i5")
        self.assertEqual(len(service.get_components()), 1)

        mock_save.side_effect = None
        with self.assertRaises(ComponentNotFoundError):
            service.delete_component("00000000-0000-4000-8000-000000000000")

    def test_service_module_has_no_ui_imports_and_exports_contract(self) -> None:
        service_path = pathlib.Path(__file__).resolve().parents[1] / "pc_parts_organizer" / "service.py"
        tree = ast.parse(service_path.read_text(encoding="utf-8"))
        imports = []
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imports.extend(alias.name for alias in node.names)
            if isinstance(node, ast.ImportFrom) and node.module:
                imports.append(node.module)
        self.assertFalse(any("tkinter" in name or "ui" in name for name in imports))
        import pc_parts_organizer.service as service_module

        self.assertTrue(hasattr(service_module, "InventorySummary"))
        self.assertIn("InventorySummary", service_module.__all__)


if __name__ == "__main__":
    unittest.main()


    # --- T14.7 economic summary ---
    @patch("pc_parts_organizer.service.save_components")
    @patch("pc_parts_organizer.service.load_components")
    def test_summary_economic_empty_and_no_priced(self, mock_load, mock_save) -> None:
        mock_load.return_value = []
        summary = InventoryService().get_summary()
        self.assertEqual((summary.priced_component_count, summary.unpriced_component_count, summary.price_subtotals_by_currency), (0, 0, {}))
        mock_load.return_value = [self._component(category="CPU"), self._component(category="GPU")]
        summary = InventoryService().get_summary()
        self.assertEqual(summary.total_count, 2)
        self.assertEqual(summary.priced_component_count, 0)
        self.assertEqual(summary.unpriced_component_count, 2)
        self.assertEqual(summary.price_subtotals_by_currency, {})
        mock_save.assert_not_called()

    @patch("pc_parts_organizer.service.save_components")
    @patch("pc_parts_organizer.service.load_components")
    def test_summary_economic_single_same_currency_multi_currency_mix(self, mock_load, mock_save) -> None:
        mock_load.return_value = [self._component(purchase_price="100", purchase_currency="EUR")]
        s = InventoryService().get_summary()
        self.assertEqual(s.priced_component_count, 1); self.assertEqual(s.unpriced_component_count, 0)
        self.assertEqual(s.price_subtotals_by_currency, {"EUR": "100"})
        mock_load.return_value = [
            self._component(purchase_price="100", purchase_currency="EUR"),
            self._component(purchase_price="50", purchase_currency="EUR"),
        ]
        s = InventoryService().get_summary()
        self.assertEqual(s.price_subtotals_by_currency, {"EUR": "150"})
        mock_load.return_value = [
            self._component(purchase_price="100", purchase_currency="EUR"),
            self._component(purchase_price="50", purchase_currency="EUR"),
            self._component(purchase_price="200", purchase_currency="USD"),
            self._component(purchase_price="25", purchase_currency="USD"),
        ]
        s = InventoryService().get_summary()
        self.assertEqual(s.price_subtotals_by_currency, {"EUR": "150", "USD": "225"})  # never mixed
        self.assertEqual(list(s.price_subtotals_by_currency.keys()), ["EUR", "USD"])  # deterministic
        mock_load.return_value = [
            self._component(purchase_price="100", purchase_currency="EUR"),
            self._component(category="GPU"),
            self._component(purchase_price="25", purchase_currency="USD"),
        ]
        s = InventoryService().get_summary()
        self.assertEqual(s.total_count, 3); self.assertEqual(s.priced_component_count, 2); self.assertEqual(s.unpriced_component_count, 1)
        self.assertEqual(s.price_subtotals_by_currency, {"EUR": "100", "USD": "25"})

    @patch("pc_parts_organizer.service.save_components")
    @patch("pc_parts_organizer.service.load_components")
    def test_summary_economic_decimal_precision_normalization(self, mock_load, mock_save) -> None:
        mock_load.return_value = [
            self._component(purchase_price="10", purchase_currency="EUR"),
            self._component(purchase_price="10.5000", purchase_currency="EUR"),
            self._component(purchase_price="0.1250", purchase_currency="EUR"),
        ]
        s = InventoryService().get_summary()
        self.assertEqual(s.price_subtotals_by_currency, {"EUR": "20.625"})  # exact, no rounding, no sci notation
        mock_load.return_value = [self._component(purchase_price="0", purchase_currency="USD")]
        self.assertEqual(InventoryService().get_summary().price_subtotals_by_currency, {"USD": "0"})

    @patch("pc_parts_organizer.service.save_components")
    @patch("pc_parts_organizer.service.load_components")
    def test_summary_economic_updates_after_crud_and_preserve_clear(self, mock_load, mock_save) -> None:
        mock_load.return_value = []
        service = InventoryService()
        c = service.add_component("CPU", "A", "M", purchase_price="10", purchase_currency="EUR")
        self.assertEqual(service.get_summary().price_subtotals_by_currency, {"EUR": "10"})
        service.update_component(c.id, "CPU", "A", "M")  # omit preserves
        self.assertEqual(service.get_summary().price_subtotals_by_currency, {"EUR": "10"})
        service.update_component(c.id, "CPU", "A", "M", purchase_price="15.5", purchase_currency="USD")
        self.assertEqual(service.get_summary().price_subtotals_by_currency, {"USD": "15.5"})
        service.update_component(c.id, "CPU", "A", "M", purchase_price="", purchase_currency="")  # explicit clear
        s = service.get_summary(); self.assertEqual((s.priced_component_count, s.price_subtotals_by_currency), (0, {}))
        c2 = service.add_component("GPU", "B", "N", purchase_price="5", purchase_currency="EUR")
        service.delete_component(c2.id)
        self.assertEqual(service.get_summary().price_subtotals_by_currency, {})

    @patch("pc_parts_organizer.service.save_components")
    @patch("pc_parts_organizer.service.load_components")
    def test_summary_economic_legacy_no_price_fields_and_no_float(self, mock_load, mock_save) -> None:
        # Components with defaults (legacy-like loaded state) count as unpriced
        mock_load.return_value = [Component(category="CPU", manufacturer="A", model="M")]
        s = InventoryService().get_summary()
        self.assertEqual((s.priced_component_count, s.unpriced_component_count, s.price_subtotals_by_currency), (0, 1, {}))
        mock_load.return_value = [self._component(purchase_price="1.23", purchase_currency="EUR")]
        service = InventoryService(); mock_load.reset_mock(); mock_save.reset_mock()
        service.get_summary()
        mock_load.assert_not_called(); mock_save.assert_not_called()
        # no float in implementation
        import inspect, pathlib
        src = pathlib.Path(inspect.getfile(service.get_summary)).read_text(encoding="utf-8")
        i = src.index("def get_summary"); j = src.index("def _find_index", i)
        block = src[i:j]
        self.assertNotIn("float(", block); self.assertIn("Decimal(", block)


    # --- T15 restore ---
    @patch("pc_parts_organizer.service.create_pre_restore_backup")
    @patch("pc_parts_organizer.service.save_components")
    @patch("pc_parts_organizer.service.load_components")
    def test_restore_replaces_inventory_after_verified_pre_backup(self, mock_load, mock_save, mock_pre) -> None:
        current = self._component(category="CPU", manufacturer="A", model="Old")
        mock_load.return_value = [current]
        pre = SimpleNamespace(path=Path("C:/tmp/pre.json"), sha256="abc", components=[current], schema_version=2)
        mock_pre.return_value = pre
        service = InventoryService()
        replacement = [self._component(category="GPU", manufacturer="N", model="New"), self._component(category="RAM", manufacturer="C", model="X")]
        result = service.restore_inventory(replacement)
        self.assertEqual(result.restored_count, 2)
        self.assertIs(result.pre_restore_backup, pre)
        mock_pre.assert_called_once()
        mock_save.assert_called_once()
        comps = service.get_components()
        self.assertEqual([c.category for c in comps], ["GPU", "RAM"])
        self.assertEqual(service.get_summary().total_count, 2)
        # UUIDs preserved
        self.assertEqual(comps[0].id, replacement[0].id)

    @patch("pc_parts_organizer.service.create_pre_restore_backup")
    @patch("pc_parts_organizer.service.save_components")
    @patch("pc_parts_organizer.service.load_components")
    def test_restore_empty_replaces_and_summary_updates(self, mock_load, mock_save, mock_pre) -> None:
        mock_load.return_value = [self._component()]
        mock_pre.return_value = SimpleNamespace(path=Path("p"), sha256="x", components=[], schema_version=2)
        service = InventoryService()
        result = service.restore_inventory([])
        self.assertEqual(result.restored_count, 0)
        self.assertEqual(service.get_components(), [])
        s = service.get_summary()
        self.assertEqual((s.total_count, s.priced_component_count, s.price_subtotals_by_currency), (0, 0, {}))

    @patch("pc_parts_organizer.service.create_pre_restore_backup")
    @patch("pc_parts_organizer.service.save_components")
    @patch("pc_parts_organizer.service.load_components")
    def test_restore_aborts_if_pre_backup_fails(self, mock_load, mock_save, mock_pre) -> None:
        current = self._component(model="Keep")
        mock_load.return_value = [current]
        mock_pre.side_effect = StorageError("backup failed")
        service = InventoryService()
        with self.assertRaises(StorageError):
            service.restore_inventory([self._component(model="New")])
        mock_save.assert_not_called()
        self.assertEqual(service.get_components()[0].model, "Keep")

    @patch("pc_parts_organizer.service.create_pre_restore_backup")
    @patch("pc_parts_organizer.service.save_components")
    @patch("pc_parts_organizer.service.load_components")
    def test_restore_preserves_memory_and_pre_backup_if_save_fails(self, mock_load, mock_save, mock_pre) -> None:
        current = self._component(model="Keep")
        mock_load.return_value = [current]
        mock_pre.return_value = SimpleNamespace(path=Path("C:/tmp/pre.json"), sha256="x", components=[current], schema_version=2)
        mock_save.side_effect = StorageError("disk")
        service = InventoryService()
        with self.assertRaises(StorageError):
            service.restore_inventory([self._component(model="New")])
        self.assertEqual(service.get_components()[0].model, "Keep")
        mock_pre.assert_called_once()  # created before save attempt
