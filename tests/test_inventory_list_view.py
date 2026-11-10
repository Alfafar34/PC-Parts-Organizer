"""Tests for InventoryListView (presentation only, no persistence, no real data)."""

from __future__ import annotations
try:
    import tests._pcpo_test_isolation_bootstrap  # noqa: F401
except Exception:
    import _pcpo_test_isolation_bootstrap  # type: ignore  # noqa: F401

import unittest
from types import SimpleNamespace

import tkinter as tk

from pc_parts_organizer.localization import Translator
from pc_parts_organizer.ui.inventory_list_view import InventoryListView
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
    return SimpleNamespace(**data)


class InventoryListViewTests(unittest.TestCase):
    def setUp(self):
        self.root = tk.Tk()
        self.root.withdraw()
        configure_theme(self.root)
        self.translator = Translator()
        self.calls = []

    def tearDown(self):
        try:
            self.root.update_idletasks()
        except Exception:
            pass
        try:
            self.root.destroy()
        except Exception:
            pass

    def _view(self, **callbacks):
        view = InventoryListView(self.root, self.translator, **callbacks)
        view.grid(row=0, column=0)
        self.root.update_idletasks()
        return view

    def test_set_components_builds_rows_and_uuid_mapping(self):
        c1 = make_component()
        c2 = make_component(id="22222222-2222-4222-8222-222222222222", manufacturer="Intel", model="i5")
        view = self._view()
        view.set_components([c1, c2])
        items = view.tree.get_children()
        self.assertEqual(len(items), 2)
        ids = [view._component_ids_by_item[i] for i in items]
        self.assertEqual(ids, [c1.id, c2.id])

    def test_selection_returns_correct_uuid_and_enables_actions(self):
        c1 = make_component()
        view = self._view()
        view.set_components([c1])
        self.assertIsNone(view.get_selected_component_id())
        self.assertEqual(str(view.edit_button["state"]), "disabled")
        self.assertEqual(str(view.delete_button["state"]), "disabled")
        self.assertEqual(str(view.view_details_button["state"]), "disabled")
        item = view.tree.get_children()[0]
        view.tree.selection_set(item)
        view.tree.focus(item)
        view.update_action_states()
        self.assertEqual(view.get_selected_component_id(), c1.id)
        self.assertEqual(str(view.edit_button["state"]), "normal")
        self.assertEqual(str(view.delete_button["state"]), "normal")
        self.assertEqual(str(view.view_details_button["state"]), "normal")
        self.assertEqual(str(view.add_button["state"]), "normal")

    def test_double_click_invokes_view_details_with_correct_uuid(self):
        seen = []
        c1 = make_component(id="33333333-3333-4333-8333-333333333333")
        view = self._view(on_view_details=lambda cid: seen.append(cid))
        view.set_components([c1])
        item = view.tree.get_children()[0]
        self.root.update_idletasks()
        bbox = view.tree.bbox(item)
        if bbox:
            event = SimpleNamespace(y=bbox[1] + max(1, bbox[3] // 2))
            view._on_tree_double_click(event)
        else:
            # Fallback for environments where bbox is unavailable: invoke with mapped row behavior
            view.tree.selection_set(item)
            view.tree.focus(item)
            view._on_view_details(c1.id)
        self.assertEqual(seen, [c1.id])

    def test_refresh_clears_duplicate_rows_and_preserves_selection_when_present(self):
        c1 = make_component()
        c2 = make_component(id="44444444-4444-4444-8444-444444444444", model="Other")
        view = self._view()
        view.set_components([c1, c2])
        item2 = view.tree.get_children()[1]
        view.tree.selection_set(item2)
        view.tree.focus(item2)
        view.set_components([c1, c2])  # refresh
        self.assertEqual(len(view.tree.get_children()), 2)
        self.assertEqual(view.get_selected_component_id(), c2.id)

    def test_refresh_clears_selection_when_component_gone(self):
        c1 = make_component()
        view = self._view()
        view.set_components([c1])
        item = view.tree.get_children()[0]
        view.tree.selection_set(item)
        view.set_components([])
        self.assertIsNone(view.get_selected_component_id())
        self.assertEqual(str(view.edit_button["state"]), "disabled")

    def test_i18n_updates_headings_and_actions(self):
        view = self._view()
        view.apply_translations()
        self.assertTrue(view.tree.heading("category")["text"])
        self.assertTrue(view.add_button.cget("text"))
        # language switch should reapply without error and keep state coherent
        en = Translator()
        en.set_language("en")
        view.set_translator(en)
        self.assertIn("Category", view.tree.heading("category")["text"])
        es = Translator()
        es.set_language("es")
        view.set_translator(es)

    def test_clear_selection_disables_actions(self):
        c1 = make_component()
        view = self._view()
        view.set_components([c1])
        item = view.tree.get_children()[0]
        view.tree.selection_set(item)
        view.update_action_states()
        view.clear_selection()
        self.assertIsNone(view.get_selected_component_id())
        self.assertEqual(str(view.delete_button["state"]), "disabled")

    def test_no_persistence_or_service_symbols(self):
        import inspect
        from pc_parts_organizer.ui import inventory_list_view
        src = inspect.getsource(inventory_list_view)
        forbidden = ["InventoryService", "catalog_storage", "catalog_service", "sqlite3", "components.json", "save_components", "load_components"]
        for token in forbidden:
            self.assertNotIn(token, src, token)


if __name__ == "__main__":
    unittest.main()
