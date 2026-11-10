"""Tests for inventory search, filter, and sort (T14.1). Uses fake data only."""

from __future__ import annotations
try:
    import tests._pcpo_test_isolation_bootstrap  # noqa: F401
except Exception:
    import _pcpo_test_isolation_bootstrap  # type: ignore  # noqa: F401

import copy
import unittest
from types import SimpleNamespace

import tkinter as tk

from pc_parts_organizer.localization import Translator
from pc_parts_organizer.ui.inventory_list_view import InventoryListView
from pc_parts_organizer.ui.theme import configure_theme


def C(**o):
    base = dict(id=o.get("id", "id"), category="CPU", manufacturer="", model="", specifications="", notes="")
    base.update(o)
    return SimpleNamespace(**base)


class InventorySearchFilterSortTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.root = tk.Tk()
        cls.root.withdraw()
        configure_theme(cls.root)

    @classmethod
    def tearDownClass(cls):
        try:
            cls.root.destroy()
        except Exception:
            pass

    def setUp(self):
        self.translator = Translator()
        self.view = InventoryListView(self.root, self.translator)
        self.view.grid()
        self.root.update_idletasks()

    def tearDown(self):
        try:
            self.view._cancel_search_after()
            self.view.destroy()
            self.root.update_idletasks()
        except Exception:
            pass

    def shown_ids(self):
        return [self.view._component_ids_by_item[i] for i in self.view.tree.get_children()]

    def sample(self):
        return [
            C(id="1", category="CPU", manufacturer="AMD", model="Ryzen 5", specifications="6 cores", notes="fast"),
            C(id="2", category="GPU", manufacturer="Nvidia", model="RTX 3060", specifications="12GB", notes="gaming"),
            C(id="3", category="RAM", manufacturer="Corsair", model="Vengeance", specifications="DDR4 16GB", notes=""),
            C(id="4", category="CPU", manufacturer="Intel", model="i5", specifications="10 cores", notes="office"),
        ]

    def apply_search(self, text):
        self.view.search_var.set(text)
        self.view._apply_search_from_var()

    def apply_category(self, canonical):
        self.view._category_filter = canonical
        # sync combo display semantically
        if canonical is None:
            self.view.category_var.set(self.view._t("inventory_list.all_categories"))
        else:
            self.view.category_var.set(self.translator.translate_category(canonical))
        self.view._apply_filters()

    def test_search_by_manufacturer(self):
        self.view.set_components(self.sample())
        self.apply_search("nvidia")
        self.assertEqual(self.shown_ids(), ["2"])

    def test_search_by_model(self):
        self.view.set_components(self.sample())
        self.apply_search("Ryzen")
        self.assertEqual(self.shown_ids(), ["1"])

    def test_search_by_specifications(self):
        self.view.set_components(self.sample())
        self.apply_search("ddr4")
        self.assertEqual(self.shown_ids(), ["3"])

    def test_search_by_notes(self):
        self.view.set_components(self.sample())
        self.apply_search("office")
        self.assertEqual(self.shown_ids(), ["4"])

    def test_search_case_insensitive_and_trimmed(self):
        self.view.set_components(self.sample())
        self.apply_search("  aMd  ")
        self.assertEqual(self.shown_ids(), ["1"])

    def test_search_and_category_combined(self):
        self.view.set_components(self.sample())
        self.apply_category("CPU")
        self.apply_search("intel")
        self.assertEqual(self.shown_ids(), ["4"])

    def test_clear_search(self):
        self.view.set_components(self.sample())
        self.apply_search("nvidia")
        self.assertEqual(len(self.shown_ids()), 1)
        self.apply_search("")
        self.assertEqual(len(self.shown_ids()), 4)

    def test_clear_filters(self):
        self.view.set_components(self.sample())
        self.apply_category("GPU")
        self.apply_search("corsair")
        self.assertEqual(self.shown_ids(), [])
        self.view._clear_filters()
        self.assertIsNone(self.view._category_filter)
        self.assertEqual(self.view.search_var.get(), "")
        self.assertEqual(len(self.shown_ids()), 4)

    def test_sort_ascending_descending(self):
        comps = [
            C(id="a", category="GPU", manufacturer="B", model="M"),
            C(id="b", category="CPU", manufacturer="A", model="M"),
            C(id="c", category="RAM", manufacturer="C", model="M"),
        ]
        self.view.set_components(comps)
        self.view._sort_field = "manufacturer"
        self.view._sort_desc = False
        self.view._apply_filters()
        self.assertEqual(self.shown_ids(), ["b", "a", "c"])
        self.view._sort_desc = True
        self.view._apply_filters()
        self.assertEqual(self.shown_ids(), ["c", "a", "b"])

    def test_sort_stable(self):
        comps = [
            C(id="1", category="CPU", manufacturer="Same", model="A"),
            C(id="2", category="CPU", manufacturer="SAME", model="B"),
            C(id="3", category="CPU", manufacturer="same", model="C"),
        ]
        self.view.set_components(comps)
        self.view._sort_field = "manufacturer"
        self.view._sort_desc = False
        self.view._apply_filters()
        self.assertEqual(self.shown_ids(), ["1", "2", "3"])

    def test_no_duplicates_uuid_preserved(self):
        comps = self.sample()
        self.view.set_components(comps)
        ids = self.shown_ids()
        self.assertEqual(len(ids), len(set(ids)))
        self.assertEqual(set(ids), {c.id for c in comps})

    def test_selection_preserved_when_visible(self):
        self.view.set_components(self.sample())
        item = self.view.tree.get_children()[1]  # after default sort this may vary; select by known id flow
        # force sort predictable
        self.view._sort_field = "model"; self.view._sort_desc = False; self.view._apply_filters()
        # select id "1" (Ryzen 5)
        for it in self.view.tree.get_children():
            if self.view._component_ids_by_item[it] == "1":
                self.view.tree.selection_set(it); self.view.tree.focus(it); break
        self.view.update_action_states()
        self.assertEqual(self.view.get_selected_component_id(), "1")
        self.apply_search("cpu")  # matches AMD cpu and Intel cpu, keeps id 1
        self.assertEqual(self.view.get_selected_component_id(), "1")

    def test_selection_cleared_when_not_visible(self):
        self.view.set_components(self.sample())
        self.view._sort_field = "model"; self.view._sort_desc = False; self.view._apply_filters()
        for it in self.view.tree.get_children():
            if self.view._component_ids_by_item[it] == "1":
                self.view.tree.selection_set(it); break
        self.view.update_action_states()
        self.apply_search("nvidia")
        self.assertIsNone(self.view.get_selected_component_id())
        self.assertEqual(str(self.view.edit_button["state"]), "disabled")
        self.assertEqual(str(self.view.view_details_button["state"]), "disabled")
        self.assertEqual(str(self.view.delete_button["state"]), "disabled")

    def test_language_change_preserves_semantic_category_filter(self):
        self.view.set_components(self.sample())
        self.apply_category("GPU")
        self.assertEqual(self.shown_ids(), ["2"])
        en = Translator(); en.set_language("en")
        self.view.set_translator(en)
        self.assertEqual(self.view._category_filter, "GPU")
        self.assertEqual(self.shown_ids(), ["2"])
        es = Translator(); es.set_language("es")
        self.view.set_translator(es)
        self.assertEqual(self.view._category_filter, "GPU")

    def test_empty_inventory(self):
        self.view.set_components([])
        self.assertEqual(self.shown_ids(), [])
        self.assertIsNone(self.view.get_selected_component_id())

    def test_no_mutation_of_original_objects(self):
        comps = self.sample()
        before = copy.deepcopy([c.__dict__ for c in comps])
        self.view.set_components(comps)
        self.apply_search("amd")
        self.view._sort_field = "manufacturer"; self.view._sort_desc = True; self.view._apply_filters()
        after = [c.__dict__ for c in comps]
        self.assertEqual(before, after)

    def _is_visible(self, widget):
        self.root.update_idletasks()
        try:
            return bool(widget.winfo_ismapped()) or bool(widget.grid_info())
        except Exception:
            return False

    def test_empty_state_integrated_visibility_and_restore(self):
        self.view.set_components(self.sample())
        # normal results
        self.assertTrue(self._is_visible(self.view.tree))
        self.assertFalse(self._is_visible(self.view._empty_state_frame))
        # no matches with existing components
        self.apply_search("zzzz-no-match")
        self.assertEqual(self.shown_ids(), [])
        self.assertTrue(self._is_visible(self.view._empty_state_frame))
        self.assertFalse(self._is_visible(self.view.tree))
        self.assertFalse(self._is_visible(self.view._vertical_scroll))
        self.assertFalse(self._is_visible(self.view._horizontal_scroll))
        self.assertTrue(self.view._no_results_title_label.cget("text"))
        self.assertTrue(self.view._no_results_hint_label.cget("text"))
        # selection/actions disabled
        self.assertIsNone(self.view.get_selected_component_id())
        self.assertEqual(str(self.view.edit_button["state"]), "disabled")
        self.assertEqual(str(self.view.view_details_button["state"]), "disabled")
        self.assertEqual(str(self.view.delete_button["state"]), "disabled")
        # clear search restores
        self.apply_search("")
        self.assertEqual(len(self.shown_ids()), 4)
        self.assertTrue(self._is_visible(self.view.tree))
        self.assertFalse(self._is_visible(self.view._empty_state_frame))
        # sort config preserved across filter changes
        self.view._sort_field = "manufacturer"; self.view._sort_desc = True; self.view._apply_filters()
        self.apply_search("zzzz-no-match")
        self.assertEqual(self.view._sort_field, "manufacturer")
        self.assertTrue(self.view._sort_desc)
        self.apply_search("")
        self.assertEqual(self.shown_ids()[0], self.view._component_ids_by_item[self.view.tree.get_children()[0]])

    def test_empty_state_filter_restore_and_i18n(self):
        self.view.set_components(self.sample())
        self.apply_category("GPU")
        self.apply_search("nope")
        self.assertEqual(self.shown_ids(), [])
        self.assertTrue(self._is_visible(self.view._empty_state_frame))
        self.apply_search("")
        self.assertEqual(self.shown_ids(), ["2"])
        self.assertFalse(self._is_visible(self.view._empty_state_frame))
        # i18n updates title/hint
        self.apply_search("nope")
        en = Translator(); en.set_language("en")
        self.view.set_translator(en)
        self.assertIn("match", self.view._no_results_title_label.cget("text").lower() + self.view._no_results_hint_label.cget("text").lower())
        es = Translator(); es.set_language("es")
        self.view.set_translator(es)

    def test_empty_inventory_does_not_show_no_results_state(self):
        self.view.set_components([])
        self.assertEqual(self.shown_ids(), [])
        self.assertFalse(self._is_visible(self.view._empty_state_frame))
        self.assertTrue(self._is_visible(self.view.tree))

    # --- T14.2 counter ---
    def count_text(self):
        return self.view.results_count_label.cget("text")

    def test_counter_empty_and_single_and_many(self):
        self.view.set_components([])
        self.assertEqual(self.count_text(), self.translator.t("inventory_list.count_all_many").format(count=0))
        self.view.set_components([C(id="1")])
        self.assertEqual(self.count_text(), self.translator.t("inventory_list.count_all_one").format(count=1))
        self.assertEqual(len(self.shown_ids()), 1)
        self.view.set_components(self.sample())
        self.assertEqual(self.count_text(), self.translator.t("inventory_list.count_all_many").format(count=4))
        self.assertEqual(len(self.shown_ids()), 4)

    def test_counter_search_filter_combined_and_no_match(self):
        self.view.set_components(self.sample())
        self.apply_search("amd")
        self.assertEqual(self.count_text(), self.translator.t("inventory_list.count_filtered_many").format(shown=1, total=4))
        self.assertEqual(len(self.shown_ids()), 1)
        self.apply_search("")
        self.apply_category("CPU")
        self.assertEqual(self.count_text(), self.translator.t("inventory_list.count_filtered_many").format(shown=2, total=4))
        self.apply_search("intel")
        self.assertEqual(self.count_text(), self.translator.t("inventory_list.count_filtered_many").format(shown=1, total=4))
        self.apply_search("zzzz")
        self.assertEqual(self.count_text(), self.translator.t("inventory_list.count_filtered_many").format(shown=0, total=4))
        self.assertEqual(len(self.shown_ids()), 0)

    def test_counter_clear_filters_and_set_components(self):
        self.view.set_components(self.sample())
        self.apply_search("nvidia")
        self.assertEqual(self.count_text(), self.translator.t("inventory_list.count_filtered_many").format(shown=1, total=4))
        self.view._clear_filters()
        self.assertEqual(self.count_text(), self.translator.t("inventory_list.count_all_many").format(count=4))
        self.view.set_components([C(id="x"), C(id="y")])
        self.assertEqual(self.count_text(), self.translator.t("inventory_list.count_all_many").format(count=2))
        self.assertEqual(len(self.shown_ids()), 2)

    def test_counter_pluralization_en_and_language_change_with_filters(self):
        en = Translator(); en.set_language("en")
        self.view.set_translator(en)
        self.view.set_components([C(id="1")])
        self.assertEqual(self.count_text(), en.t("inventory_list.count_all_one").format(count=1))
        self.view.set_components(self.sample())
        self.assertEqual(self.count_text(), en.t("inventory_list.count_all_many").format(count=4))
        self.view._category_filter = "GPU"
        self.view.category_var.set(en.translate_category("GPU"))
        self.view._apply_filters()
        self.assertEqual(self.view._category_filter, "GPU")
        self.assertEqual(self.count_text(), en.t("inventory_list.count_filtered_many").format(shown=1, total=4))
        es = Translator(); es.set_language("es")
        self.view.set_translator(es)
        self.assertEqual(self.view._category_filter, "GPU")
        self.assertEqual(self.count_text(), es.t("inventory_list.count_filtered_many").format(shown=1, total=4))
        self.assertEqual(len(self.shown_ids()), 1)

    def test_counter_matches_visible_rows_no_mutation(self):
        comps = self.sample()
        before = copy.deepcopy([c.__dict__ for c in comps])
        self.view.set_components(comps)
        for query in ["", "amd", "cpu", "nope"]:
            self.apply_search(query)
            shown = len(self.shown_ids())
            total = 4
            if query.strip():
                expected = self.translator.t("inventory_list.count_filtered_many").format(shown=shown, total=total)
            else:
                expected = self.translator.t("inventory_list.count_all_many").format(count=total)
            self.assertEqual(self.count_text(), expected)
        self.assertEqual([c.__dict__ for c in comps], before)


    # --- T14.5 purchase/warranty date search ---
    def test_search_by_purchase_and_warranty_dates(self):
        self.view.set_components([
            C(id="1", manufacturer="A", model="M", purchase_date="2024-06-01", warranty_end_date="2027-06-01"),
            C(id="2", manufacturer="B", model="N", purchase_date="2020-01-01", warranty_end_date=""),
        ])
        self.apply_search("2024-06-01")
        self.assertEqual(self.shown_ids(), ["1"])
        self.apply_search("2027-06-01")
        self.assertEqual(self.shown_ids(), ["1"])
        self.apply_search("2020")
        self.assertEqual(self.shown_ids(), ["2"])

    # --- T14.6 price/currency search ---
    def test_search_by_price_and_currency(self):
        self.view.set_components([
            C(id="1", manufacturer="A", model="M", purchase_price="149.90", purchase_currency="EUR"),
            C(id="2", manufacturer="B", model="N", purchase_price="20", purchase_currency="USD"),
        ])
        self.apply_search("149.90")
        self.assertEqual(self.shown_ids(), ["1"])
        self.apply_search("eur")
        self.assertEqual(self.shown_ids(), ["1"])
        self.apply_search("usd")
        self.assertEqual(self.shown_ids(), ["2"])

if __name__ == "__main__":
    unittest.main()

    # --- T14.4 status/location search ---
    def test_search_by_location(self):
        self.view.set_components([
            C(id="1", manufacturer="A", model="M", location="Caja de repuestos"),
            C(id="2", manufacturer="B", model="N", location="Escritorio"),
        ])
        self.apply_search("caja")
        self.assertEqual(self.shown_ids(), ["1"])

    def test_search_by_status_canonical_and_translated_es_en(self):
        comps = [
            C(id="1", manufacturer="A", model="M", status="faulty", location=""),
            C(id="2", manufacturer="B", model="N", status="stored", location=""),
        ]
        self.view.set_components(comps)
        self.apply_search("faulty")
        self.assertEqual(self.shown_ids(), ["1"])
        es_faulty = self.translator.translate_status("faulty")
        self.apply_search(es_faulty)
        self.assertEqual(self.shown_ids(), ["1"])
        en = Translator(); en.set_language("en")
        self.view.set_translator(en)
        self.assertEqual(self.shown_ids(), ["1"])
        self.apply_search(en.translate_status("faulty"))
        self.assertEqual(self.shown_ids(), ["1"])
        self.apply_search(en.translate_status("stored"))
        self.assertEqual(self.shown_ids(), ["2"])
