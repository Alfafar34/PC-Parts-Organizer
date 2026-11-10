"""Tests for InventoryDetailView (presentation only, no persistence, no real data)."""

from __future__ import annotations
try:
    import tests._pcpo_test_isolation_bootstrap  # noqa: F401
except Exception:
    import _pcpo_test_isolation_bootstrap  # type: ignore  # noqa: F401

import unittest
from types import SimpleNamespace

import tkinter as tk

from pc_parts_organizer.localization import Translator
from pc_parts_organizer.ui.inventory_detail_view import InventoryDetailView
from pc_parts_organizer.ui.theme import configure_theme


def make_component(**overrides):
    data = dict(
        id="11111111-1111-4111-8111-111111111111",
        category="CPU",
        manufacturer="AMD",
        model="Ryzen 5 5600",
        specifications="6 cores / 12 threads",
        notes="Test note",
    )
    data.update(overrides)
    return SimpleNamespace(**data)


class InventoryDetailViewTests(unittest.TestCase):
    def setUp(self):
        self.root = tk.Tk()
        self.root.withdraw()
        configure_theme(self.root)
        self.translator = Translator()

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
        view = InventoryDetailView(self.root, self.translator, **callbacks)
        view.grid(row=0, column=0)
        self.root.update_idletasks()
        return view

    def _text(self, view, key):
        w = view._detail_fields[key][1]
        return w.get("1.0", "end-1c")

    def test_renders_all_component_fields(self):
        comp = make_component()
        view = self._view()
        view.set_component(comp)
        self.assertEqual(self._text(view, "id"), comp.id)
        self.assertEqual(self._text(view, "category"), self.translator.translate_category("CPU"))
        self.assertEqual(self._text(view, "manufacturer"), "AMD")
        self.assertEqual(self._text(view, "model"), "Ryzen 5 5600")
        self.assertEqual(self._text(view, "specifications"), "6 cores / 12 threads")
        self.assertEqual(self._text(view, "notes"), "Test note")
        self.assertEqual(view.get_component_id(), comp.id)

    def test_optional_empty_fields_show_translated_marker(self):
        comp = make_component(manufacturer="", model="", specifications="", notes="   ")
        view = self._view()
        view.set_component(comp)
        empty = self.translator.t("component_detail.empty")
        self.assertEqual(self._text(view, "manufacturer"), empty)
        self.assertEqual(self._text(view, "model"), empty)
        self.assertEqual(self._text(view, "specifications"), empty)
        self.assertEqual(self._text(view, "notes"), empty)

    def test_long_text_not_truncated(self):
        long_specs = "x" * 4000
        long_notes = "y\n" * 500
        comp = make_component(specifications=long_specs, notes=long_notes)
        view = self._view()
        view.set_component(comp)
        self.assertEqual(self._text(view, "specifications"), long_specs)
        self.assertEqual(self._text(view, "notes"), long_notes.strip() or long_notes)

    def test_edit_delete_callbacks_receive_shown_uuid(self):
        seen = []
        comp = make_component(id="22222222-2222-4222-8222-222222222222")
        view = self._view(on_edit=lambda cid: seen.append(("edit", cid)),
                          on_delete=lambda cid: seen.append(("delete", cid)),
                          on_back=lambda: seen.append(("back", None)))
        view.set_component(comp)
        view._handle_edit()
        view._handle_delete()
        view.detail_back_button.invoke()
        self.assertEqual(seen, [("edit", comp.id), ("delete", comp.id), ("back", None)])

    def test_clear_component_clears_state_without_destroying_view(self):
        comp = make_component()
        view = self._view()
        view.set_component(comp)
        view.clear_component()
        self.assertIsNone(view.get_component_id())
        self.assertTrue(view.winfo_exists())
        empty = self.translator.t("component_detail.empty")
        self.assertEqual(self._text(view, "specifications"), empty)

    def test_i18n_updates_labels(self):
        view = self._view()
        view.set_component(make_component())
        en = Translator()
        en.set_language("en")
        view.set_translator(en)
        self.assertTrue(view.detail_title_label.cget("text"))
        self.assertEqual(view.detail_back_button.cget("text"), en.t("component_detail.back"))
        es = Translator()
        es.set_language("es")
        view.set_translator(es)
        self.assertEqual(view.detail_back_button.cget("text"), es.t("component_detail.back"))

    def test_no_persistence_or_service_symbols(self):
        import inspect
        from pc_parts_organizer.ui import inventory_detail_view
        src = inspect.getsource(inventory_detail_view)
        forbidden = [
            "InventoryService", "CatalogService", "catalog_service", "catalog_storage",
            "sqlite3", "components.json", "storage", "save_components", "load_components",
            ".get_component(", ".add_component(", ".update_component(", ".delete_component(",
        ]
        for token in forbidden:
            self.assertNotIn(token, src, token)


if __name__ == "__main__":
    unittest.main()

    def test_detail_shows_status_and_location_with_i18n(self):
        c = make_component(status="installed", location="PC principal")
        view = self._view()
        view.set_component(c)
        self.assertEqual(self._text(view, "status"), self.translator.translate_status("installed"))
        self.assertEqual(self._text(view, "location"), "PC principal")
        en = Translator(); en.set_language("en")
        view.set_translator(en)
        self.assertEqual(self._text(view, "status"), en.translate_status("installed"))
        self.assertEqual(self._text(view, "location"), "PC principal")
        view.set_component(make_component(status="unspecified", location=""))
        self.assertEqual(self._text(view, "location"), en.t("component_detail.empty"))
        view.destroy()

    def test_detail_shows_purchase_and_warranty_dates(self):
        c = make_component(purchase_date="2025-03-10", warranty_end_date="")
        view = self._view()
        view.set_component(c)
        self.assertEqual(self._text(view, "purchase_date"), "2025-03-10")
        self.assertEqual(self._text(view, "warranty_end_date"), self.translator.t("component_detail.empty"))
        view.destroy()

    def test_detail_shows_price_currency_and_empty_marker(self):
        c = make_component(purchase_price="149.90", purchase_currency="EUR")
        view = self._view()
        view.set_component(c)
        self.assertEqual(self._text(view, "purchase_price"), "149.90")
        self.assertEqual(self._text(view, "purchase_currency"), "EUR")
        view.set_component(make_component(purchase_price="", purchase_currency=""))
        self.assertEqual(self._text(view, "purchase_price"), self.translator.t("component_detail.empty"))
        self.assertEqual(self._text(view, "purchase_currency"), self.translator.t("component_detail.empty"))
        view.destroy()
