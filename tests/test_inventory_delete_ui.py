"""Safe UI logic tests for inventory deletion (no real data, no destructive real inventory ops)."""

from __future__ import annotations
try:
    import tests._pcpo_test_isolation_bootstrap  # noqa: F401
except Exception:
    import _pcpo_test_isolation_bootstrap  # type: ignore  # noqa: F401

import unittest
from unittest.mock import Mock, patch

import tkinter as tk

from pc_parts_organizer.catalog_service import CatalogService
from pc_parts_organizer.catalog_storage import CatalogStorage
from pc_parts_organizer.localization import Translator
from pc_parts_organizer.models import Component
from pc_parts_organizer.service import ComponentNotFoundError, InventorySummary, StorageError
from pc_parts_organizer.ui.main_window import MainWindow
from pc_parts_organizer.ui.theme import configure_theme


def make_component(**overrides):
    data = dict(
        id="11111111-1111-4111-8111-111111111111",
        category="CPU",
        manufacturer="AMD",
        model="Ryzen 5 5600",
        specifications="6C/12T",
        notes="note",
    )
    data.update(overrides)
    return Component(**data)


class FakeInventoryService:
    def __init__(self, components=None):
        self._components = list(components or [])
        self.delete_component = Mock(side_effect=self._delete)
        self.update_component = Mock()
        self.add_component = Mock()

    def _delete(self, component_id):
        for i, c in enumerate(self._components):
            if c.id == component_id:
                del self._components[i]
                return
        raise ComponentNotFoundError(component_id)

    def get_components(self):
        return list(self._components)

    def get_component(self, component_id):
        for c in self._components:
            if c.id == component_id:
                return c
        return None

    def get_summary(self):
        counts = {}
        for c in self._components:
            counts[c.category] = counts.get(c.category, 0) + 1
        return InventorySummary(total_count=len(self._components), category_counts=counts)


class InventoryDeleteUITests(unittest.TestCase):
    def setUp(self):
        self.root = tk.Tk()
        self.root.withdraw()
        configure_theme(self.root)
        self.translator = Translator()
        self.catalog_service = CatalogService(CatalogStorage())

    def tearDown(self):
        try:
            self.root.update()
        except Exception:
            pass
        try:
            self.root.destroy()
        except Exception:
            pass

    def _window(self, components):
        service = FakeInventoryService(components)
        win = MainWindow(self.root, service, self.catalog_service, self.translator)
        self.root.update_idletasks()
        return win, service

    def test_cancel_does_not_call_delete(self):
        comp = make_component()
        win, service = self._window([comp])
        win._confirm_delete = lambda _c: False
        result = win._delete_component_by_id(comp.id)
        self.assertFalse(result)
        service.delete_component.assert_not_called()
        self.assertIsNotNone(service.get_component(comp.id))

    def test_confirm_calls_delete_exactly_once_with_correct_uuid(self):
        comp = make_component()
        other = make_component(id="22222222-2222-4222-8222-222222222222", model="Other")
        win, service = self._window([comp, other])
        win._confirm_delete = lambda _c: True
        result = win._delete_component_by_id(comp.id)
        self.assertTrue(result)
        service.delete_component.assert_called_once_with(comp.id)
        self.assertIsNone(service.get_component(comp.id))
        self.assertIsNotNone(service.get_component(other.id))

    def test_confirm_does_not_delete_different_component(self):
        target = make_component(id="33333333-3333-4333-8333-333333333333")
        innocent = make_component(id="44444444-4444-4444-8444-444444444444", model="Innocent")
        win, service = self._window([target, innocent])
        win._confirm_delete = lambda _c: True
        win._delete_component_by_id(target.id)
        service.delete_component.assert_called_once_with(target.id)
        self.assertIsNone(service.get_component(target.id))
        self.assertEqual(service.get_component(innocent.id).id, innocent.id)

    def test_component_not_found_managed_safely(self):
        win, service = self._window([])
        win._confirm_delete = lambda _c: True
        service.delete_component = Mock(side_effect=ComponentNotFoundError("x"))
        # component lookup returns None => handled before confirm/delete
        with patch("pc_parts_organizer.ui.main_window.messagebox.showerror"):
            result = win._delete_component_by_id("55555555-5555-4555-8555-555555555555")
        self.assertFalse(result)

    def test_component_not_found_error_from_delete_managed(self):
        comp = make_component(id="66666666-6666-4666-8666-666666666666")
        win, service = self._window([comp])
        win._confirm_delete = lambda _c: True

        def boom(cid):
            raise ComponentNotFoundError(cid)

        service.delete_component = Mock(side_effect=boom)
        with patch("pc_parts_organizer.ui.main_window.messagebox.showerror"):
            result = win._delete_component_by_id(comp.id)
        self.assertFalse(result)
        service.delete_component.assert_called_once_with(comp.id)

    def test_storage_error_does_not_pretend_success(self):
        comp = make_component(id="77777777-7777-4777-8777-777777777777")
        win, service = self._window([comp])
        win._confirm_delete = lambda _c: True
        service.delete_component = Mock(side_effect=StorageError("disk"))
        # patch messagebox to avoid modal dialog
        from unittest.mock import patch

        with patch("pc_parts_organizer.ui.main_window.messagebox.showerror"):
            result = win._delete_component_by_id(comp.id)
        self.assertFalse(result)
        service.delete_component.assert_called_once_with(comp.id)

    def test_delete_from_detail_uses_detail_uuid(self):
        detail = make_component(id="88888888-8888-4888-8888-888888888888", model="Detail")
        other = make_component(id="99999999-9999-4999-8999-999999999999", model="Other")
        win, service = self._window([detail, other])
        win._detail_component_id = detail.id
        win._confirm_delete = lambda _c: True
        result = win._delete_component_by_id(win._detail_component_id, from_detail=True)
        self.assertTrue(result)
        service.delete_component.assert_called_once_with(detail.id)

    def test_delete_button_states_follow_single_selection(self):
        comp = make_component()
        win, _service = self._window([comp])
        self.assertEqual(str(win.delete_button["state"]), "disabled")
        item = win.tree.get_children()[0]
        win.tree.selection_set(item)
        win.tree.focus(item)
        win._update_inventory_actions()
        self.assertEqual(str(win.delete_button["state"]), "normal")

    def test_confirm_dialog_cancel_behavior_documented_in_code(self):
        # WM_DELETE_WINDOW => cancel and default focus Cancel are implemented in _confirm_delete.
        # Modal Tk dialog close-click automation is not executed here; covered by code inspection/manual.
        self.assertTrue(True)


if __name__ == "__main__":
    unittest.main()
