"""Tests for DashboardView economic summary presentation (T14.7). No real data."""

from __future__ import annotations
try:
    import tests._pcpo_test_isolation_bootstrap  # noqa: F401
except Exception:
    import _pcpo_test_isolation_bootstrap  # type: ignore  # noqa: F401

import unittest

import tkinter as tk

from pc_parts_organizer.localization import Translator
from pc_parts_organizer.service import InventorySummary
from pc_parts_organizer.ui.dashboard_view import DashboardView
from pc_parts_organizer.ui.theme import configure_theme


def _visible(widget) -> bool:
    try:
        return bool(widget.winfo_manager())
    except Exception:
        return False


class DashboardViewEconomicTests(unittest.TestCase):
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

    def _view(self):
        v = DashboardView(self.root, self.translator)
        self.root.update_idletasks()
        return v

    def test_empty_inventory_keeps_empty_state_no_economic_fiction(self):
        v = self._view()
        v.update_summary(InventorySummary(total_count=0, category_counts={}))
        self.assertTrue(_visible(v.dashboard_empty_label))
        self.assertFalse(_visible(v._economic_card))
        v.destroy()

    def test_no_registered_amounts_shows_counts_and_message_no_fictional_subtotals(self):
        v = self._view()
        v.update_summary(InventorySummary(total_count=3, category_counts={"CPU": 3}, priced_component_count=0, unpriced_component_count=3, price_subtotals_by_currency={}))
        self.assertTrue(_visible(v._economic_card))
        self.assertEqual(v._priced_value.cget("text"), "0")
        self.assertEqual(v._unpriced_value.cget("text"), "3")
        self.assertTrue(_visible(v._no_amounts_label))
        self.assertIn("importe" in v._no_amounts_label.cget("text").lower() or "amount" in v._no_amounts_label.cget("text").lower(), [True])
        self.assertEqual(list(v._subtotals_frame.winfo_children()), [])
        self.assertFalse(_visible(v._disclaimer_label))
        v.destroy()

    def test_renders_subtotals_by_currency_and_counts(self):
        v = self._view()
        v.update_summary(InventorySummary(
            total_count=4,
            category_counts={"CPU": 2, "GPU": 2},
            priced_component_count=3,
            unpriced_component_count=1,
            price_subtotals_by_currency={"EUR": "150", "USD": "25"},
        ))
        self.assertEqual(v._priced_value.cget("text"), "3")
        self.assertEqual(v._unpriced_value.cget("text"), "1")
        texts = [w.cget("text") for w in v._subtotals_frame.winfo_children()]
        self.assertEqual(texts, ["150 EUR", "25 USD"])
        self.assertFalse(_visible(v._no_amounts_label))
        v.destroy()

    def test_disclaimer_when_unpriced_present_not_total_inventory_value(self):
        en = Translator(); en.set_language("en")
        v = DashboardView(self.root, en)
        v.update_summary(InventorySummary(total_count=2, category_counts={"CPU": 2}, priced_component_count=1, unpriced_component_count=1, price_subtotals_by_currency={"EUR": "10"}))
        self.assertTrue(_visible(v._disclaimer_label))
        txt = v._disclaimer_label.cget("text").lower()
        self.assertIn("do not represent", txt)
        self.assertIn("total inventory value", txt)
        v.destroy()

    def test_i18n_es_en_updates_labels(self):
        v = self._view()
        v.update_summary(InventorySummary(total_count=1, category_counts={"CPU": 1}, priced_component_count=0, unpriced_component_count=1, price_subtotals_by_currency={}))
        self.assertIn("registrado", v._priced_label.cget("text").lower())
        self.assertTrue(_visible(v._no_amounts_label))
        en = Translator(); en.set_language("en")
        v.set_translator(en)
        self.assertIn("registered", v._priced_label.cget("text").lower())
        self.assertIn("registered", v._subtotals_title_label.cget("text").lower())
        self.assertIn("amount", v._no_amounts_label.cget("text").lower())
        v.destroy()


if __name__ == "__main__":
    unittest.main()
