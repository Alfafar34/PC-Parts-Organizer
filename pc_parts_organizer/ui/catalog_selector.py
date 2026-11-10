"""Catalog reference selector for the component form."""

from __future__ import annotations

import tkinter as tk
from tkinter import messagebox, ttk
from typing import Callable

from pc_parts_organizer.catalog_models import CatalogEntry
from pc_parts_organizer.catalog_service import CatalogService, CatalogStorageError
from pc_parts_organizer.localization import Translator
from pc_parts_organizer.models import CATEGORIES
from pc_parts_organizer.ui.theme import PALETTE

DEFAULT_PAGE_SIZE = 100
CHUNK_SIZE = 500
TABLE_COLUMNS = ("category", "manufacturer", "model", "source")


class CatalogSelectorWindow:
    """Compact modal window to search and select a catalog reference."""

    def __init__(
        self,
        parent: tk.Misc,
        catalog_service: CatalogService,
        translator: Translator,
        on_close: Callable[[], None] | None = None,
        *,
        multi: bool = False,
    ) -> None:
        self.parent = parent
        self.catalog_service = catalog_service
        self.translator = translator
        self.on_close = on_close
        self.multi = bool(multi)
        self.result: CatalogEntry | None = None
        self.results: list[CatalogEntry] = []
        self.window = tk.Toplevel(parent)
        title_key = "catalog_selector.multi_title" if self.multi else "catalog_selector.title"
        self.window.title(self.translator.t(title_key))
        self.window.transient(parent)
        self.window.configure(background=PALETTE["background"])
        self.window.geometry("850x600")
        self.window.minsize(700, 480)
        self.window.protocol("WM_DELETE_WINDOW", self._on_cancel)

        self._entry_ids_by_item: dict[str, str] = {}
        self._query = ""
        self._category: str | None = None
        self._offset = 0
        self._total = 0
        self._current_count = 0
        self._show_all = False
        self._load_token = 0
        self._selected_id_pending: str | None = None
        self._selected_ids: set[str] = set()
        self._category_display_to_canonical: dict[str, str | None] = {}
        self._page_size_display_to_value: dict[str, int | None] = {}
        self._search_var = tk.StringVar()
        self._category_var = tk.StringVar()
        self._page_size_var = tk.StringVar()

        self.tree: ttk.Treeview | None = None
        self.status_label: ttk.Label | None = None
        self.selection_label: ttk.Label | None = None
        self.use_button: ttk.Button | None = None
        self.prev_button: ttk.Button | None = None
        self.next_button: ttk.Button | None = None
        self.search_entry: ttk.Entry | None = None
        self.category_combo: ttk.Combobox | None = None
        self.page_size_combo: ttk.Combobox | None = None
        self._detail_vars: dict[str, tk.StringVar] = {}
        self._detail_texts: dict[str, tk.Text] = {}

        self._build_ui()
        self.refresh_results(reset_page=True)
        self.window.grab_set()
        if self.search_entry is not None:
            self.search_entry.focus_set()

    def _build_ui(self) -> None:
        content = ttk.Frame(self.window, style="App.TFrame", padding=16)
        content.grid(row=0, column=0, sticky="nsew")
        self.window.columnconfigure(0, weight=1)
        self.window.rowconfigure(0, weight=1)
        content.columnconfigure(0, weight=1)
        content.rowconfigure(3, weight=3)
        content.rowconfigure(4, weight=2)

        ttk.Label(content, text=self.translator.t("catalog_selector.title"), style="SectionTitle.TLabel").grid(
            row=0, column=0, sticky="w"
        )
        desc_key = "catalog_selector.multi_description" if self.multi else "catalog_selector.description"
        ttk.Label(content, text=self.translator.t(desc_key), style="Body.TLabel").grid(
            row=1, column=0, sticky="w", pady=(2, 10)
        )

        filters = ttk.Frame(content, style="App.TFrame")
        filters.grid(row=2, column=0, sticky="ew", pady=(0, 8))
        filters.columnconfigure(1, weight=1)
        ttk.Label(filters, text=self.translator.t("catalog_selector.search_placeholder"), style="Body.TLabel").grid(
            row=0, column=0, sticky="w", padx=(0, 8)
        )
        self.search_entry = ttk.Entry(filters, textvariable=self._search_var, style="Form.TEntry")
        self.search_entry.grid(row=0, column=1, sticky="ew", padx=(0, 8))
        self.search_entry.bind("<Return>", lambda _e: self._on_search())
        self._build_category_filter(filters)
        ttk.Button(
            filters,
            text=self.translator.t("catalog_selector.search"),
            style="Secondary.TButton",
            command=self._on_search,
        ).grid(row=0, column=3, padx=(0, 6))
        ttk.Button(
            filters,
            text=self.translator.t("catalog_selector.clear_filters"),
            style="Secondary.TButton",
            command=self._on_clear,
        ).grid(row=0, column=4)

        table_surface = tk.Frame(
            content,
            background=PALETTE["surface"],
            highlightbackground=PALETTE["border"],
            highlightthickness=1,
            bd=0,
        )
        table_surface.grid(row=3, column=0, sticky="nsew", pady=(0, 8))
        table_surface.columnconfigure(0, weight=1)
        table_surface.rowconfigure(0, weight=1)
        table_surface.rowconfigure(1, weight=0)

        table_frame = ttk.Frame(table_surface, style="Surface.TFrame", padding=(10, 10, 10, 6))
        table_frame.grid(row=0, column=0, sticky="nsew")
        table_frame.columnconfigure(0, weight=1)
        table_frame.rowconfigure(0, weight=1)
        self.tree = ttk.Treeview(
            table_frame,
            columns=TABLE_COLUMNS,
            show="headings",
            selectmode="extended" if self.multi else "browse",
            style="Inventory.Treeview",
        )
        self.tree.heading("category", text=self.translator.t("catalog_selector.category"), anchor="w")
        self.tree.heading("manufacturer", text=self.translator.t("catalog_selector.manufacturer"), anchor="w")
        self.tree.heading("model", text=self.translator.t("catalog_selector.model"), anchor="w")
        self.tree.heading("source", text=self.translator.t("catalog_selector.source"), anchor="w")
        self.tree.column("category", width=130, minwidth=100, anchor="w")
        self.tree.column("manufacturer", width=190, minwidth=120, anchor="w")
        self.tree.column("model", width=250, minwidth=140, anchor="w")
        self.tree.column("source", width=150, minwidth=100, anchor="w")
        vs = ttk.Scrollbar(table_frame, orient="vertical", command=self.tree.yview)
        hs = ttk.Scrollbar(table_frame, orient="horizontal", command=self.tree.xview)
        self.tree.configure(yscrollcommand=vs.set, xscrollcommand=hs.set)
        self.tree.grid(row=0, column=0, sticky="nsew")
        vs.grid(row=0, column=1, sticky="ns")
        hs.grid(row=1, column=0, sticky="ew")
        self.tree.bind("<<TreeviewSelect>>", lambda _e: self._on_selection_changed())
        self.tree.bind("<Double-1>", lambda _e: self._on_use_selected())

        paging = ttk.Frame(table_surface, style="Surface.TFrame", padding=(10, 0, 10, 10))
        paging.grid(row=1, column=0, sticky="ew")
        paging.columnconfigure(3, weight=1)
        ttk.Label(paging, text=self.translator.t("catalog_selector.page_size_label"), style="SurfaceBody.TLabel").grid(row=0, column=0, padx=(0, 6))
        self._build_page_size_control(paging)
        self.prev_button = ttk.Button(
            paging,
            text=self.translator.t("catalog_selector.previous_page"),
            style="Secondary.TButton",
            command=self._on_prev,
        )
        self.prev_button.grid(row=0, column=2, padx=(8, 0))
        self.status_label = ttk.Label(paging, style="SurfaceBody.TLabel")
        self.status_label.grid(row=0, column=3)
        self.next_button = ttk.Button(
            paging,
            text=self.translator.t("catalog_selector.next_page"),
            style="Secondary.TButton",
            command=self._on_next,
        )
        self.next_button.grid(row=0, column=4)

        detail_surface = tk.Frame(
            content,
            background=PALETTE["surface"],
            highlightbackground=PALETTE["border"],
            highlightthickness=1,
            bd=0,
        )
        detail_surface.grid(row=4, column=0, sticky="nsew", pady=(0, 8))
        detail_surface.columnconfigure(0, weight=1)
        detail = ttk.Frame(detail_surface, style="Surface.TFrame", padding=10)
        detail.grid(row=0, column=0, sticky="nsew")
        detail.columnconfigure(1, weight=1)
        ttk.Label(detail, text=self.translator.t("catalog_selector.details_title"), style="SurfaceTitle.TLabel").grid(
            row=0, column=0, columnspan=2, sticky="w", pady=(0, 6)
        )
        self._build_detail_row(detail, 1, "specifications", multiline=True, height=3)
        self._build_detail_row(detail, 2, "notes", multiline=True, height=2)
        self._build_detail_row(detail, 3, "source")
        self._build_detail_row(detail, 4, "source_url")
        self._build_detail_row(detail, 5, "verified_at")
        self._clear_details()

        actions = ttk.Frame(content, style="App.TFrame")
        actions.grid(row=5, column=0, sticky="ew")
        actions.columnconfigure(0, weight=1)
        self.selection_label = ttk.Label(actions, style="Body.TLabel")
        self.selection_label.grid(row=0, column=0, sticky="w")
        ttk.Button(
            actions,
            text=self.translator.t("catalog_selector.cancel"),
            style="Secondary.TButton",
            command=self._on_cancel,
        ).grid(row=0, column=1, padx=(0, 8))
        use_key = "catalog_selector.use_selected_multi" if self.multi else "catalog_selector.use_selected"
        self.use_button = ttk.Button(
            actions,
            text=self.translator.t(use_key),
            style="Primary.TButton",
            command=self._on_use_selected,
            state="disabled",
        )
        self.use_button.grid(row=0, column=2)
        self._refresh_multi_state()

    def _build_category_filter(self, parent: ttk.Frame) -> None:
        all_label = self.translator.t("catalog_selector.all_categories")
        values = [all_label] + [self.translator.translate_category(c) for c in CATEGORIES]
        self._category_display_to_canonical = {all_label: None}
        for canonical in CATEGORIES:
            self._category_display_to_canonical[self.translator.translate_category(canonical)] = canonical
        self.category_combo = ttk.Combobox(
            parent,
            values=values,
            state="readonly",
            width=20,
            style="Form.TCombobox",
            textvariable=self._category_var,
        )
        self.category_combo.grid(row=0, column=2, padx=(0, 8))
        self.category_combo.set(all_label)

    def _build_page_size_control(self, parent: ttk.Frame) -> None:
        all_label = self.translator.t("catalog_selector.page_size_all")
        self._page_size_display_to_value = {str(DEFAULT_PAGE_SIZE): DEFAULT_PAGE_SIZE, all_label: None}
        self.page_size_combo = ttk.Combobox(
            parent,
            values=list(self._page_size_display_to_value.keys()),
            state="readonly",
            width=8,
            style="Form.TCombobox",
            textvariable=self._page_size_var,
        )
        self.page_size_combo.grid(row=0, column=1)
        self.page_size_combo.set(str(DEFAULT_PAGE_SIZE))
        self.page_size_combo.bind("<<ComboboxSelected>>", lambda _e: self._on_page_size_changed())

    def _build_detail_row(
        self, parent: ttk.Frame, row: int, key: str, multiline: bool = False, height: int = 2
    ) -> None:
        ttk.Label(parent, text=self.translator.t(f"catalog_selector.{key}"), style="Form.TLabel").grid(
            row=row, column=0, sticky="nw", pady=(0, 4), padx=(0, 8)
        )
        if multiline:
            text = tk.Text(
                parent,
                height=height,
                wrap="word",
                font=("Segoe UI", 9),
                background=PALETTE["surface"],
                foreground=PALETTE["text"],
                highlightbackground=PALETTE["border"],
                highlightthickness=1,
                bd=0,
                padx=4,
                pady=2,
                state="disabled",
            )
            text.grid(row=row, column=1, sticky="ew", pady=(0, 4))
            self._detail_texts[key] = text
        else:
            var = tk.StringVar(value="")
            ttk.Label(parent, textvariable=var, style="SurfaceBody.TLabel", wraplength=520).grid(
                row=row, column=1, sticky="w", pady=(0, 4)
            )
            self._detail_vars[key] = var

    def _set_detail_text(self, key: str, value: str) -> None:
        widget = self._detail_texts.get(key)
        if widget is None:
            return
        widget.configure(state="normal")
        widget.delete("1.0", "end")
        if value:
            widget.insert("1.0", value)
        widget.configure(state="disabled")

    def _clear_details(self) -> None:
        for key in ("specifications", "notes"):
            self._set_detail_text(key, "")
        for key in ("source", "source_url", "verified_at"):
            if key in self._detail_vars:
                self._detail_vars[key].set("")

    def _selected_entry_id(self) -> str | None:
        if self.tree is None:
            return None
        sel = self.tree.selection()
        if not sel:
            return None
        # Single mode: the visible selection. Multi mode: first visible item.
        return self._entry_ids_by_item.get(sel[0])

    def _page_entry_ids(self) -> dict[str, str]:
        """Map entry id -> tree item for the current page."""
        return {entry_id: item for item, entry_id in self._entry_ids_by_item.items()}

    def _refresh_multi_state(self) -> None:
        if not self.multi:
            return
        if self.selection_label is not None:
            try:
                text = self.translator.t("catalog_selector.selection_count").format(count=len(self._selected_ids))
            except Exception:
                text = str(len(self._selected_ids))
            self.selection_label.configure(text=text)
        if self.use_button is not None:
            self.use_button.configure(state="normal" if self._selected_ids else "disabled")

    def _on_selection_changed(self) -> None:
        if self.multi:
            # Merge current page selection into the cross-page set.
            if self.tree is not None:
                current_ids = set(self._entry_ids_by_item.values())
                visible_selected = {self._entry_ids_by_item[i] for i in self.tree.selection() if i in self._entry_ids_by_item}
                self._selected_ids = (self._selected_ids - current_ids) | visible_selected
            self._refresh_multi_state()
            # Detail panel follows the first visible selection, if any.
            entry_id = self._selected_entry_id()
            if not entry_id:
                self._clear_details()
                return
        else:
            entry_id = self._selected_entry_id()
            if self.use_button is not None:
                self.use_button.configure(state="normal" if entry_id else "disabled")
            if not entry_id:
                self._clear_details()
                return
        try:
            entry = self.catalog_service.get_entry(entry_id)
        except CatalogStorageError:
            messagebox.showerror(
                self.translator.t("messages.catalog_error_title"),
                self.translator.t("catalog_selector.unavailable_error"),
                parent=self.window,
            )
            self._clear_details()
            return
        if entry is None:
            self._clear_details()
            return
        self._set_detail_text("specifications", entry.specifications)
        self._set_detail_text("notes", entry.notes)
        self._detail_vars["source"].set(entry.source or "")
        self._detail_vars["source_url"].set(entry.source_url or "")
        self._detail_vars["verified_at"].set(entry.verified_at or "")

    def refresh_results(self, reset_page: bool = False) -> None:
        if reset_page:
            self._offset = 0
        self._load_token += 1
        token = self._load_token
        if self.status_label is not None and self._show_all:
            self.status_label.configure(text=self.translator.t("catalog_selector.loading_progress").format(loaded=0, total=0))
            self.window.update_idletasks()
        try:
            self._total = self.catalog_service.count_entries(query=self._query, category=self._category)
            if token != self._load_token:
                return
            if self._show_all:
                entries = self.catalog_service.search_entries(query=self._query, category=self._category, limit=None, offset=0)
            else:
                entries = self.catalog_service.search_entries(
                    query=self._query,
                    category=self._category,
                    limit=DEFAULT_PAGE_SIZE,
                    offset=self._offset,
                )
        except CatalogStorageError:
            if token != self._load_token:
                return
            messagebox.showerror(
                self.translator.t("messages.catalog_error_title"),
                self.translator.t("catalog_selector.unavailable_error"),
                parent=self.window,
            )
            return
        if token != self._load_token:
            return
        self._current_count = len(entries)
        self._begin_table_load(entries, token)

    def _begin_table_load(self, entries: list[CatalogEntry], token: int) -> None:
        if self.tree is None:
            return
        if self.multi:
            self._selected_id_pending = None
        else:
            self._selected_id_pending = self._selected_entry_id()
        for item in self.tree.get_children():
            self.tree.delete(item)
        self._entry_ids_by_item.clear()
        if self.use_button is not None and not self.multi:
            self.use_button.configure(state="disabled")
        self._clear_details()
        if not entries:
            self._finish_table_load(token, None)
            return
        if self._show_all and len(entries) > CHUNK_SIZE:
            self._insert_chunk(entries, 0, token, self._selected_id_pending)
        else:
            selected_item = self._insert_entries(entries, self._selected_id_pending)
            self._finish_table_load(token, selected_item)

    def _insert_entries(self, entries: list[CatalogEntry], selected_id: str | None = None) -> str | None:
        if self.tree is None:
            return None
        selected_item = None
        for entry in entries:
            item_id = self.tree.insert(
                "",
                "end",
                values=(
                    self.translator.translate_category(entry.category),
                    entry.manufacturer,
                    entry.model,
                    entry.source,
                ),
            )
            self._entry_ids_by_item[item_id] = entry.id
            if selected_id and entry.id == selected_id:
                selected_item = item_id
        return selected_item

    def _insert_chunk(self, entries: list[CatalogEntry], index: int, token: int, selected_id: str | None) -> None:
        if token != self._load_token or self.tree is None or not self.window.winfo_exists():
            return
        end = min(index + CHUNK_SIZE, len(entries))
        selected_item = self._insert_entries(entries[index:end], selected_id)
        loaded = end
        if self.status_label is not None:
            self.status_label.configure(
                text=self.translator.t("catalog_selector.loading_progress").format(loaded=loaded, total=self._total)
            )
        if selected_item is not None:
            self.tree.selection_set(selected_item)
            self.tree.focus(selected_item)
        if end < len(entries):
            self.window.after(1, lambda: self._insert_chunk(entries, end, token, selected_id))
        else:
            self._finish_table_load(token, selected_item)

    def _finish_table_load(self, token: int, selected_item: str | None) -> None:
        if token != self._load_token or self.tree is None:
            return
        if self.multi:
            # Restore cross-page selection on the fresh page.
            by_entry = {eid: item for item, eid in self._entry_ids_by_item.items()}
            to_select = [by_entry[eid] for eid in self._selected_ids if eid in by_entry]
            if to_select:
                self.tree.selection_set(to_select)
                self.tree.focus(to_select[0])
                self._on_selection_changed()
            self._refresh_multi_state()
            self._update_status()
            return
        if selected_item is not None:
            self.tree.selection_set(selected_item)
            self.tree.focus(selected_item)
            self._on_selection_changed()
        if self.use_button is not None:
            self.use_button.configure(state="normal" if self._selected_entry_id() else "disabled")
        self._update_status()

    def _populate_table(self, entries: list[CatalogEntry]) -> None:
        self._load_token += 1
        self._begin_table_load(entries, self._load_token)

    def _update_status(self) -> None:
        pages = max(1, (self._total + DEFAULT_PAGE_SIZE - 1) // DEFAULT_PAGE_SIZE)
        page = (self._offset // DEFAULT_PAGE_SIZE) + 1 if self._total else 1
        if self.status_label is not None:
            if self._total == 0:
                key = "catalog_selector.no_catalog_entries" if not self._query and self._category is None else "catalog_selector.no_results"
                self.status_label.configure(text=self.translator.t(key))
            elif self._show_all:
                self.status_label.configure(text=self.translator.t("catalog_selector.showing_all").format(total=self._total))
            else:
                shown = self._offset + self._current_count
                summary = self.translator.t("catalog_selector.results_summary").format(shown=shown, total=self._total)
                page_text = self.translator.t("catalog_selector.page_label").format(page=page, pages=pages)
                self.status_label.configure(text=f"{summary} · {page_text}")
        if self.prev_button is not None:
            self.prev_button.configure(state="normal" if (not self._show_all and self._offset > 0) else "disabled")
        if self.next_button is not None:
            self.next_button.configure(state="normal" if (not self._show_all and self._offset + DEFAULT_PAGE_SIZE < self._total) else "disabled")

    def _on_page_size_changed(self) -> None:
        selected = self._page_size_var.get()
        value = self._page_size_display_to_value.get(selected, DEFAULT_PAGE_SIZE)
        self._show_all = value is None
        self.refresh_results(reset_page=True)

    def _on_search(self) -> None:
        self._query = self._search_var.get().strip()
        selected = self._category_var.get()
        self._category = self._category_display_to_canonical.get(selected)
        self.refresh_results(reset_page=True)

    def _on_clear(self) -> None:
        self._search_var.set("")
        self._query = ""
        self._category = None
        if self.category_combo is not None:
            self.category_combo.set(self.translator.t("catalog_selector.all_categories"))
        self.refresh_results(reset_page=True)

    def _on_prev(self) -> None:
        if self._show_all or self._offset < DEFAULT_PAGE_SIZE:
            return
        self._offset -= DEFAULT_PAGE_SIZE
        self.refresh_results(reset_page=False)

    def _on_next(self) -> None:
        if self._show_all or self._offset + DEFAULT_PAGE_SIZE >= self._total:
            return
        self._offset += DEFAULT_PAGE_SIZE
        self.refresh_results(reset_page=False)

    def _on_use_selected(self) -> None:
        if self.multi:
            if not self._selected_ids:
                return
            entries: list[CatalogEntry] = []
            try:
                for entry_id in sorted(self._selected_ids):
                    entry = self.catalog_service.get_entry(entry_id)
                    if entry is not None:
                        entries.append(entry)
            except CatalogStorageError:
                messagebox.showerror(
                    self.translator.t("messages.catalog_error_title"),
                    self.translator.t("catalog_selector.unavailable_error"),
                    parent=self.window,
                )
                return
            if not entries:
                messagebox.showerror(
                    self.translator.t("messages.catalog_error_title"),
                    self.translator.t("catalog_selector.unavailable_error"),
                    parent=self.window,
                )
                return
            self.results = entries
            self.result = entries[0]
            self._load_token += 1
            self.window.destroy()
            if self.on_close is not None:
                self.on_close()
            return
        entry_id = self._selected_entry_id()
        if not entry_id:
            return
        try:
            entry = self.catalog_service.get_entry(entry_id)
        except CatalogStorageError:
            messagebox.showerror(
                self.translator.t("messages.catalog_error_title"),
                self.translator.t("catalog_selector.unavailable_error"),
                parent=self.window,
            )
            return
        if entry is None:
            messagebox.showerror(
                self.translator.t("messages.catalog_error_title"),
                self.translator.t("catalog_selector.unavailable_error"),
                parent=self.window,
            )
            return
        self.result = entry
        self._load_token += 1
        self.window.destroy()
        if self.on_close is not None:
            self.on_close()

    def _on_cancel(self) -> None:
        self.result = None
        self.results = []
        self._load_token += 1
        self.window.destroy()
        if self.on_close is not None:
            self.on_close()
