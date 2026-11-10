"""Inventory list/table view component."""

from __future__ import annotations

import tkinter as tk
from tkinter import ttk
from typing import Any, Callable

from pc_parts_organizer.localization import Translator
from pc_parts_organizer.models import CATEGORIES
from pc_parts_organizer.ui.theme import PALETTE

TABLE_COLUMNS = ("category", "manufacturer", "model")
_SORT_FIELDS = ("category", "manufacturer", "model")
_SEARCH_DEBOUNCE_MS = 180


class InventoryListView(ttk.Frame):
    """Presentation component for inventory table and actions. No persistence/CRUD."""

    def __init__(
        self,
        parent: tk.Misc,
        translator: Translator,
        *,
        on_add: Callable[[], None] | None = None,
        on_edit: Callable[[str], None] | None = None,
        on_view_details: Callable[[str], None] | None = None,
        on_delete: Callable[[str], None] | None = None,
        on_manage_catalog: Callable[[], None] | None = None,
        on_export: Callable[[], None] | None = None,
        on_restore: Callable[[], None] | None = None,
        on_quality: Callable[[], None] | None = None,
        on_add_from_catalog: Callable[[], None] | None = None,
        on_bulk_delete: Callable[[], None] | None = None,
        on_import_csv: Callable[[], None] | None = None,
        on_export_csv_template: Callable[[], None] | None = None,
    ) -> None:
        super().__init__(parent, style="App.TFrame")
        self.translator = translator
        self._on_add = on_add or (lambda: None)
        self._on_edit = on_edit or (lambda _id: None)
        self._on_view_details = on_view_details or (lambda _id: None)
        self._on_delete = on_delete or (lambda _id: None)
        self._on_manage_catalog = on_manage_catalog or (lambda: None)
        self._on_export = on_export or (lambda: None)
        self._on_restore = on_restore or (lambda: None)
        self._on_quality = on_quality or (lambda: None)
        self._on_add_from_catalog = on_add_from_catalog or (lambda: None)
        self._on_bulk_delete = on_bulk_delete or (lambda: None)
        self._on_import_csv = on_import_csv or (lambda: None)
        self._on_export_csv_template = on_export_csv_template or (lambda: None)

        self._component_ids_by_item: dict[str, str] = {}
        self._component_categories_by_item: dict[str, str] = {}
        self._all_components: list[Any] = []
        self._search_text: str = ""
        self._category_filter: str | None = None  # canonical
        self._sort_field: str = "category"
        self._sort_desc: bool = False
        self._search_after_id: str | None = None
        self._category_display_to_canonical: dict[str, str | None] = {}
        self._sort_display_to_field: dict[str, str] = {}
        self._dir_display_to_desc: dict[str, bool] = {}

        self.inventory_title_label: ttk.Label | None = None
        self.manage_catalog_button: ttk.Button | None = None
        self.quality_button: ttk.Button | None = None
        self.export_button: ttk.Button | None = None
        self.restore_button: ttk.Button | None = None
        self.view_details_button: ttk.Button | None = None
        self.edit_button: ttk.Button | None = None
        self.delete_button: ttk.Button | None = None
        self.bulk_delete_button: ttk.Button | None = None
        self.import_csv_button: ttk.Button | None = None
        self.template_csv_button: ttk.Button | None = None
        self.add_button: ttk.Button | None = None
        self.add_from_catalog_button: ttk.Button | None = None
        self.table_frame: tk.Frame | None = None
        self.tree: ttk.Treeview | None = None
        self._vertical_scroll: ttk.Scrollbar | None = None
        self._horizontal_scroll: ttk.Scrollbar | None = None
        self._empty_state_frame: tk.Frame | None = None
        self._no_results_title_label: ttk.Label | None = None
        self._no_results_hint_label: ttk.Label | None = None
        self.results_count_label: ttk.Label | None = None
        self._last_shown_count: int = 0
        self._last_total_count: int = 0
        self.search_var = tk.StringVar()
        self.category_var = tk.StringVar()
        self.sort_field_var = tk.StringVar()
        self.sort_dir_var = tk.StringVar()
        self.search_entry: ttk.Entry | None = None
        self.clear_button: ttk.Button | None = None
        self.category_combo: ttk.Combobox | None = None
        self.sort_field_combo: ttk.Combobox | None = None
        self.sort_dir_combo: ttk.Combobox | None = None

        self._build_ui()
        self.apply_translations()

    def destroy(self) -> None:  # type: ignore[override]
        self._cancel_search_after()
        super().destroy()

    def _cancel_search_after(self) -> None:
        if self._search_after_id is not None:
            try:
                self.after_cancel(self._search_after_id)
            except Exception:
                pass
            self._search_after_id = None

    def _build_ui(self) -> None:
        self.columnconfigure(0, weight=1)
        self.rowconfigure(3, weight=1)

        toolbar = ttk.Frame(self, style="App.TFrame")
        toolbar.grid(row=0, column=0, sticky="ew", pady=(0, 8))
        toolbar.columnconfigure(0, weight=1)

        self.inventory_title_label = ttk.Label(toolbar, style="SectionTitle.TLabel")
        self.inventory_title_label.grid(row=0, column=0, sticky="w")

        actions = ttk.Frame(toolbar, style="App.TFrame")
        actions.grid(row=0, column=1, sticky="e")
        self.export_button = ttk.Button(
            actions, style="Secondary.TButton", command=self._on_export
        )
        self.export_button.grid(row=0, column=0, padx=(0, 8))
        self.restore_button = ttk.Button(
            actions, style="Secondary.TButton", command=self._on_restore
        )
        self.restore_button.grid(row=0, column=1, padx=(0, 8))
        self.manage_catalog_button = ttk.Button(
            actions, style="Secondary.TButton", command=self._on_manage_catalog
        )
        self.manage_catalog_button.grid(row=0, column=2, padx=(0, 8))
        self.quality_button = ttk.Button(
            actions, style="Secondary.TButton", command=self._on_quality
        )
        self.quality_button.grid(row=0, column=3, padx=(0, 8))
        self.view_details_button = ttk.Button(
            actions, style="Secondary.TButton", command=self._handle_view_details, state="disabled"
        )
        self.view_details_button.grid(row=0, column=4, padx=(0, 8))
        self.edit_button = ttk.Button(
            actions, style="Secondary.TButton", command=self._handle_edit, state="disabled"
        )
        self.edit_button.grid(row=0, column=5, padx=(0, 8))
        self.delete_button = ttk.Button(
            actions, style="Secondary.TButton", command=self._handle_delete, state="disabled"
        )
        self.delete_button.grid(row=0, column=6, padx=(0, 8))
        self.bulk_delete_button = ttk.Button(
            actions, style="Secondary.TButton", command=self._on_bulk_delete, state="disabled"
        )
        self.bulk_delete_button.grid(row=0, column=7, padx=(0, 8))
        self.import_csv_button = ttk.Button(
            actions, style="Secondary.TButton", command=self._on_import_csv
        )
        self.import_csv_button.grid(row=0, column=8, padx=(0, 8))
        self.template_csv_button = ttk.Button(
            actions, style="Secondary.TButton", command=self._on_export_csv_template
        )
        self.template_csv_button.grid(row=0, column=9, padx=(0, 8))
        self.add_from_catalog_button = ttk.Button(
            actions, style="Secondary.TButton", command=self._on_add_from_catalog
        )
        self.add_from_catalog_button.grid(row=0, column=8, padx=(0, 8))
        self.add_button = ttk.Button(
            actions, style="Primary.TButton", command=self._on_add
        )
        self.add_button.grid(row=0, column=9)

        filters = ttk.Frame(self, style="App.TFrame")
        filters.grid(row=1, column=0, sticky="ew", pady=(0, 8))
        for col in (0, 2, 3, 4):
            filters.columnconfigure(col, weight=0)
        filters.columnconfigure(0, weight=1)

        self.search_entry = ttk.Entry(filters, textvariable=self.search_var, width=28)
        self.search_entry.grid(row=0, column=0, sticky="ew", padx=(0, 8))
        self.search_entry.bind("<KeyRelease>", self._on_search_key)
        self.clear_button = ttk.Button(filters, style="Secondary.TButton", command=self._clear_filters)
        self.clear_button.grid(row=0, column=1, padx=(0, 8))
        self.category_combo = ttk.Combobox(filters, textvariable=self.category_var, state="readonly", width=18)
        self.category_combo.grid(row=0, column=2, padx=(0, 8))
        self.category_combo.bind("<<ComboboxSelected>>", lambda _e: self._apply_filters())
        self.sort_field_combo = ttk.Combobox(filters, textvariable=self.sort_field_var, state="readonly", width=14)
        self.sort_field_combo.grid(row=0, column=3, padx=(0, 8))
        self.sort_field_combo.bind("<<ComboboxSelected>>", self._on_sort_changed)
        self.sort_dir_combo = ttk.Combobox(filters, textvariable=self.sort_dir_var, state="readonly", width=12)
        self.sort_dir_combo.grid(row=0, column=4)
        self.sort_dir_combo.bind("<<ComboboxSelected>>", self._on_sort_changed)

        self.results_count_label = ttk.Label(self, style="Body.TLabel", anchor="e")
        self.results_count_label.grid(row=2, column=0, sticky="e", pady=(0, 4))

        self.table_frame = tk.Frame(
            self,
            background=PALETTE["surface"],
            highlightbackground=PALETTE["border"],
            highlightthickness=1,
            bd=0,
        )
        self.table_frame.grid(row=3, column=0, sticky="nsew")
        self.table_frame.columnconfigure(0, weight=1)
        self.table_frame.rowconfigure(0, weight=1)

        self.tree = ttk.Treeview(
            self.table_frame,
            columns=TABLE_COLUMNS,
            show="headings",
            selectmode="extended",
            style="Inventory.Treeview",
        )
        self._vertical_scroll = ttk.Scrollbar(self.table_frame, orient="vertical", command=self.tree.yview)
        self._horizontal_scroll = ttk.Scrollbar(self.table_frame, orient="horizontal", command=self.tree.xview)
        self.tree.configure(yscrollcommand=self._vertical_scroll.set, xscrollcommand=self._horizontal_scroll.set)

        self.tree.grid(row=0, column=0, sticky="nsew")
        self._vertical_scroll.grid(row=0, column=1, sticky="ns")
        self._horizontal_scroll.grid(row=1, column=0, sticky="ew")
        self.tree.bind("<<TreeviewSelect>>", self._on_tree_select)
        self.tree.bind("<Double-1>", self._on_tree_double_click)

        self._empty_state_frame = tk.Frame(self.table_frame, background=PALETTE["surface"])
        self._empty_state_frame.grid(row=0, column=0, sticky="nsew")
        self._empty_state_frame.grid_remove()
        center = ttk.Frame(self._empty_state_frame, style="Surface.TFrame")
        center.place(relx=0.5, rely=0.5, anchor="center")
        self._no_results_title_label = ttk.Label(center, style="SurfaceTitle.TLabel", anchor="center", justify="center")
        self._no_results_title_label.pack(pady=(0, 6))
        self._no_results_hint_label = ttk.Label(
            center, style="SurfaceBody.TLabel", anchor="center", justify="center", wraplength=420
        )
        self._no_results_hint_label.pack()

    def _t(self, key: str) -> str:
        try:
            return self.translator.t(key)
        except Exception:
            return key

    def set_translator(self, translator: Translator) -> None:
        self.translator = translator
        self.apply_translations()

    def apply_translations(self) -> None:
        if self.inventory_title_label is not None:
            self.inventory_title_label.configure(text=self.translator.t("app.section_title"))
        if self.add_button is not None:
            self.add_button.configure(text=self.translator.t("actions.add_component"))
        if self.edit_button is not None:
            self.edit_button.configure(text=self.translator.t("actions.edit_component"))
        if self.delete_button is not None:
            self.delete_button.configure(text=self.translator.t("actions.delete_component"))
        if self.bulk_delete_button is not None:
            self.bulk_delete_button.configure(text=self._t("actions.delete_selected"))
        if self.add_from_catalog_button is not None:
            self.add_from_catalog_button.configure(text=self._t("actions.add_from_catalog"))
        if self.import_csv_button is not None:
            self.import_csv_button.configure(text=self._t("actions.import_csv"))
        if self.template_csv_button is not None:
            self.template_csv_button.configure(text=self._t("csv_import.template_action"))
        if self.view_details_button is not None:
            self.view_details_button.configure(text=self.translator.t("actions.view_details"))
        if self.manage_catalog_button is not None:
            self.manage_catalog_button.configure(text=self.translator.t("actions.manage_catalog"))
        if self.quality_button is not None:
            self.quality_button.configure(text=self.translator.t("actions.review_data"))
        if self.export_button is not None:
            self.export_button.configure(text=self.translator.t("backup.export_action"))
        if self.restore_button is not None:
            self.restore_button.configure(text=self.translator.t("backup.restore_action"))
        if self.clear_button is not None:
            self.clear_button.configure(text=self._t("inventory_list.clear_filters"))
        if self._no_results_title_label is not None:
            self._no_results_title_label.configure(text=self._t("inventory_list.no_results"))
        if self._no_results_hint_label is not None:
            self._no_results_hint_label.configure(text=self._t("inventory_list.no_results_hint"))
        self._update_results_count_label(self._last_shown_count, self._last_total_count)
        if self.tree is not None:
            self.tree.heading("category", text=self.translator.t("table.category"), anchor="w")
            self.tree.heading("manufacturer", text=self.translator.t("table.manufacturer"), anchor="w")
            self.tree.heading("model", text=self.translator.t("table.model"), anchor="w")

        all_label = self._t("inventory_list.all_categories")
        cat_values = [all_label] + [self.translator.translate_category(c) for c in CATEGORIES]
        self._category_display_to_canonical = {all_label: None}
        display_for_current = all_label
        for canonical in CATEGORIES:
            disp = self.translator.translate_category(canonical)
            self._category_display_to_canonical[disp] = canonical
            if canonical == self._category_filter:
                display_for_current = disp
        if self.category_combo is not None:
            self.category_combo.configure(values=cat_values)
            self.category_combo.set(display_for_current)

        sort_fields = [
            (self._t("inventory_list.sort_category"), "category"),
            (self._t("inventory_list.sort_manufacturer"), "manufacturer"),
            (self._t("inventory_list.sort_model"), "model"),
        ]
        self._sort_display_to_field = {d: f for d, f in sort_fields}
        sort_field_display = next((d for d, f in sort_fields if f == self._sort_field), sort_fields[0][0])
        if self.sort_field_combo is not None:
            self.sort_field_combo.configure(values=[d for d, _ in sort_fields])
            self.sort_field_combo.set(sort_field_display)

        sort_dirs = [
            (self._t("inventory_list.sort_asc"), False),
            (self._t("inventory_list.sort_desc"), True),
        ]
        self._dir_display_to_desc = {d: v for d, v in sort_dirs}
        sort_dir_display = next((d for d, v in sort_dirs if v == self._sort_desc), sort_dirs[0][0])
        if self.sort_dir_combo is not None:
            self.sort_dir_combo.configure(values=[d for d, _ in sort_dirs])
            self.sort_dir_combo.set(sort_dir_display)

        if self.search_entry is not None:
            try:
                self.search_entry.configure()  # placeholder handled by value; keep simple
            except Exception:
                pass
        # Re-render rows with translated category labels and current filters/sort
        self._render_current_view(preserve_selection=True, preserve_scroll=False)

    def get_selected_component_id(self) -> str | None:
        ids = self.get_selected_component_ids()
        return ids[0] if ids else None

    def get_selected_component_ids(self) -> list[str]:
        if self.tree is None:
            return []
        ordered: list[str] = []
        seen: set[str] = set()
        for item in self.tree.selection():
            cid = self._component_ids_by_item.get(item)
            if cid and cid not in seen:
                seen.add(cid)
                ordered.append(cid)
        return ordered

    def clear_selection(self) -> None:
        if self.tree is not None:
            for item in self.tree.selection():
                self.tree.selection_remove(item)
        self.update_action_states()

    def update_action_states(self) -> None:
        ids = self.get_selected_component_ids()
        single = len(ids) == 1
        single_state = "normal" if single else "disabled"
        bulk_state = "normal" if ids else "disabled"
        if self.edit_button is not None:
            self.edit_button.configure(state=single_state)
        if self.delete_button is not None:
            self.delete_button.configure(state=single_state)
        if self.view_details_button is not None:
            self.view_details_button.configure(state=single_state)
        if self.bulk_delete_button is not None:
            self.bulk_delete_button.configure(state=bulk_state)

    def set_components(self, components: list[Any]) -> None:
        """Receive full component list (reference kept for filtering)."""
        self._all_components = list(components)
        self._render_current_view(preserve_selection=True, preserve_scroll=True)

    def _on_search_key(self, _event: object = None) -> None:
        self._cancel_search_after()
        try:
            self._search_after_id = self.after(_SEARCH_DEBOUNCE_MS, self._apply_search_from_var)
        except Exception:
            self._apply_search_from_var()

    def _apply_search_from_var(self) -> None:
        self._search_after_id = None
        self._search_text = self.search_var.get()
        self._apply_filters()

    def _on_sort_changed(self, _event: object = None) -> None:
        self._sort_field = self._sort_display_to_field.get(self.sort_field_var.get(), "category")
        self._sort_desc = self._dir_display_to_desc.get(self.sort_dir_var.get(), False)
        self._apply_filters()

    def _clear_filters(self) -> None:
        self._cancel_search_after()
        self._search_text = ""
        self.search_var.set("")
        self._category_filter = None
        all_label = self._t("inventory_list.all_categories")
        if self.category_combo is not None and all_label in [self.category_combo.cget("values")] or True:
            self.category_var.set(all_label)
        self._apply_filters()

    def _apply_filters(self) -> None:
        # sync category from combo (canonical) while preserving semantic filter
        selected = self.category_var.get()
        if selected in self._category_display_to_canonical:
            self._category_filter = self._category_display_to_canonical[selected]
        self._render_current_view(preserve_selection=True, preserve_scroll=False)

    def _matches(self, component: Any, query: str) -> bool:
        if self._category_filter is not None and getattr(component, "category", None) != self._category_filter:
            return False
        if not query:
            return True
        category = getattr(component, "category", "") or ""
        try:
            translated_cat = self.translator.translate_category(category)
        except Exception:
            translated_cat = category
        status = getattr(component, "status", "") or ""
        try:
            translated_status = self.translator.translate_status(status) if status else ""
        except Exception:
            translated_status = status
        hay = " ".join([
            str(category),
            str(translated_cat),
            str(getattr(component, "manufacturer", "") or ""),
            str(getattr(component, "model", "") or ""),
            str(getattr(component, "specifications", "") or ""),
            str(getattr(component, "notes", "") or ""),
            str(getattr(component, "location", "") or ""),
            str(status),
            str(translated_status),
            str(getattr(component, "purchase_date", "") or ""),
            str(getattr(component, "warranty_end_date", "") or ""),
            str(getattr(component, "purchase_price", "") or ""),
            str(getattr(component, "purchase_currency", "") or ""),
        ]).casefold()
        return query in hay

    def _sort_key(self, component: Any):
        field = self._sort_field if self._sort_field in _SORT_FIELDS else "category"
        value = getattr(component, field, "") or ""
        return (str(value).casefold(), str(getattr(component, "id", "") or ""))

    def _filters_active(self) -> bool:
        return bool((self._search_text or "").strip()) or self._category_filter is not None

    def _update_results_count_label(self, shown_count: int, total_count: int) -> None:
        if self.results_count_label is None:
            return
        if total_count == 0:
            text = self._t("inventory_list.count_all_many").format(count=0)
        elif self._filters_active():
            key = "inventory_list.count_filtered_one" if total_count == 1 else "inventory_list.count_filtered_many"
            text = self._t(key).format(shown=shown_count, total=total_count)
        else:
            key = "inventory_list.count_all_one" if total_count == 1 else "inventory_list.count_all_many"
            text = self._t(key).format(count=total_count)
        self.results_count_label.configure(text=text)

    def _filtered_sorted_components(self) -> list[Any]:
        query = (self._search_text or "").strip().casefold()
        filtered = [c for c in self._all_components if self._matches(c, query)]
        # stable sort
        return sorted(filtered, key=self._sort_key, reverse=self._sort_desc)

    def _render_current_view(self, preserve_selection: bool, preserve_scroll: bool) -> None:
        if self.tree is None:
            return
        selected_ids = set(self.get_selected_component_ids()) if preserve_selection else set()
        yview = None
        if preserve_scroll:
            try:
                yview = self.tree.yview()
            except Exception:
                yview = None

        displayed = self._filtered_sorted_components()
        shown_count = len(displayed)
        total_count = len(self._all_components)
        self._last_shown_count = shown_count
        self._last_total_count = total_count
        self._update_results_count_label(shown_count, total_count)
        for item in self.tree.get_children():
            self.tree.delete(item)
        self._component_ids_by_item.clear()
        self._component_categories_by_item.clear()

        show_empty = bool(not displayed and self._all_components)
        self._set_empty_state(show_empty)

        selected_item = None
        selected_items: list[str] = []
        for component in displayed:
            category = getattr(component, "category", "")
            try:
                category_label = self.translator.translate_category(category)
            except Exception:
                category_label = category
            item_id = self.tree.insert(
                "",
                "end",
                values=(category_label, getattr(component, "manufacturer", ""), getattr(component, "model", "")),
            )
            cid = getattr(component, "id", None)
            self._component_ids_by_item[item_id] = cid
            self._component_categories_by_item[item_id] = category
            if cid in selected_ids:
                selected_items.append(item_id)
                if selected_item is None:
                    selected_item = item_id

        if selected_items:
            self.tree.selection_set(selected_items)
            self.tree.focus(selected_items[0])
            if yview and isinstance(yview, tuple) and len(yview) > 0:
                try:
                    self.tree.yview_moveto(yview[0])
                except Exception:
                    pass
        # if previously selected not visible -> selection cleared by rebuild, actions disabled
        self.update_action_states()

    def _set_empty_state(self, show: bool) -> None:
        if self.tree is None or self._empty_state_frame is None:
            return
        if show:
            self.tree.grid_remove()
            if self._vertical_scroll is not None:
                self._vertical_scroll.grid_remove()
            if self._horizontal_scroll is not None:
                self._horizontal_scroll.grid_remove()
            self._empty_state_frame.grid()
        else:
            self._empty_state_frame.grid_remove()
            self.tree.grid()
            if self._vertical_scroll is not None:
                self._vertical_scroll.grid()
            if self._horizontal_scroll is not None:
                self._horizontal_scroll.grid()

    def _on_tree_select(self, _event: object = None) -> None:
        self.update_action_states()

    def _on_tree_double_click(self, event: object = None) -> None:
        if self.tree is None:
            return
        row = self.tree.identify_row(getattr(event, "y", 0))
        if not row:
            return
        self.tree.selection_set(row)
        self.tree.focus(row)
        component_id = self._component_ids_by_item.get(row)
        if component_id:
            self._on_view_details(component_id)

    def _handle_edit(self) -> None:
        cid = self.get_selected_component_id()
        if cid:
            self._on_edit(cid)

    def _handle_view_details(self) -> None:
        cid = self.get_selected_component_id()
        if cid:
            self._on_view_details(cid)

    def _handle_delete(self) -> None:
        cid = self.get_selected_component_id()
        if cid:
            self._on_delete(cid)
