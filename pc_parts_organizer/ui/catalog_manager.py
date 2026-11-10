"""Catalog management view (embeddable)."""

from __future__ import annotations

import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

from pc_parts_organizer.catalog_models import CatalogEntry
from pc_parts_organizer.catalog_service import (
    CatalogDuplicateError,
    CatalogEntryNotFoundError,
    CatalogFileError,
    CatalogImportError,
    CatalogService,
    CatalogStorageError,
    CatalogValidationError,
)
from pc_parts_organizer.localization import Translator
from pc_parts_organizer.models import CATEGORIES
from pc_parts_organizer.ui.catalog_entry_form import CatalogEntryForm
from pc_parts_organizer.ui.theme import PALETTE

DEFAULT_PAGE_SIZE = 100
CHUNK_SIZE = 500
TABLE_COLUMNS = ("category", "manufacturer", "model", "source")


class CatalogManagerView(ttk.Frame):
    """Embeddable catalog administration view for the main window."""

    def __init__(
        self,
        parent: tk.Misc,
        catalog_service: CatalogService,
        translator: Translator,
    ) -> None:
        super().__init__(parent, style="App.TFrame")
        self.catalog_service = catalog_service
        self.translator = translator
        self._entry_ids_by_item: dict[str, str] = {}
        self._query = ""
        self._category: str | None = None
        self._offset = 0
        self._total = 0
        self._current_count = 0
        self._show_all = False
        self._load_token = 0
        self._selected_id_pending: str | None = None
        self._category_display_to_canonical: dict[str, str | None] = {}
        self._page_size_display_to_value: dict[str, int | None] = {}
        self._search_var = tk.StringVar()
        self._category_var = tk.StringVar()
        self._page_size_var = tk.StringVar()
        self.tree: ttk.Treeview | None = None
        self.status_label: ttk.Label | None = None
        self.edit_button: ttk.Button | None = None
        self.delete_button: ttk.Button | None = None
        self.prev_button: ttk.Button | None = None
        self.next_button: ttk.Button | None = None
        self.search_entry: ttk.Entry | None = None
        self.category_combo: ttk.Combobox | None = None
        self.page_size_combo: ttk.Combobox | None = None
        self.title_label: ttk.Label | None = None
        self.description_label: ttk.Label | None = None
        self.search_label: ttk.Label | None = None
        self.search_button: ttk.Button | None = None
        self.clear_button: ttk.Button | None = None
        self.add_button: ttk.Button | None = None
        self.import_button: ttk.Button | None = None
        self.export_button: ttk.Button | None = None
        self.page_size_label: ttk.Label | None = None
        self._build_ui()

    @property
    def _dialog_parent(self) -> tk.Misc:
        return self.winfo_toplevel()

    def cancel_pending(self) -> None:
        self._load_token += 1

    def destroy(self) -> None:  # type: ignore[override]
        self.cancel_pending()
        super().destroy()

    def set_translator(self, translator: Translator) -> None:
        self.translator = translator
        self.apply_translations()

    def apply_translations(self) -> None:
        if self.title_label is not None:
            self.title_label.configure(text=self.translator.t("catalog_manager.title"))
        if self.description_label is not None:
            self.description_label.configure(text=self.translator.t("catalog_manager.description"))
        if self.search_label is not None:
            self.search_label.configure(text=self.translator.t("catalog_manager.search_placeholder"))
        if self.search_button is not None:
            self.search_button.configure(text=self.translator.t("catalog_manager.search"))
        if self.clear_button is not None:
            self.clear_button.configure(text=self.translator.t("catalog_manager.clear_filters"))
        if self.add_button is not None:
            self.add_button.configure(text=self.translator.t("catalog_manager.add_entry"))
        if self.edit_button is not None:
            self.edit_button.configure(text=self.translator.t("catalog_manager.edit_entry"))
        if self.delete_button is not None:
            self.delete_button.configure(text=self.translator.t("catalog_manager.delete_entry"))
        if self.import_button is not None:
            self.import_button.configure(text=self.translator.t("catalog_manager.import_catalog"))
        if self.export_button is not None:
            self.export_button.configure(text=self.translator.t("catalog_manager.export_catalog"))
        if self.prev_button is not None:
            self.prev_button.configure(text=self.translator.t("catalog_manager.previous_page"))
        if self.next_button is not None:
            self.next_button.configure(text=self.translator.t("catalog_manager.next_page"))
        if self.page_size_label is not None:
            self.page_size_label.configure(text=self.translator.t("catalog_manager.page_size_label"))
        if self.tree is not None:
            self.tree.heading("category", text=self.translator.t("catalog_entry_form.category"), anchor="w")
            self.tree.heading("manufacturer", text=self.translator.t("catalog_entry_form.manufacturer"), anchor="w")
            self.tree.heading("model", text=self.translator.t("catalog_entry_form.model"), anchor="w")
            self.tree.heading("source", text=self.translator.t("catalog_entry_form.source"), anchor="w")

        current_category = self._category
        current_show_all = self._show_all
        all_categories = self.translator.t("catalog_manager.all_categories")
        values = [all_categories] + [self.translator.translate_category(c) for c in CATEGORIES]
        self._category_display_to_canonical = {all_categories: None}
        category_display = all_categories
        for canonical in CATEGORIES:
            display = self.translator.translate_category(canonical)
            self._category_display_to_canonical[display] = canonical
            if canonical == current_category:
                category_display = display
        if self.category_combo is not None:
            self.category_combo.configure(values=values)
            self.category_combo.set(category_display)

        all_label = self.translator.t("catalog_manager.page_size_all")
        self._page_size_display_to_value = {str(DEFAULT_PAGE_SIZE): DEFAULT_PAGE_SIZE, all_label: None}
        if self.page_size_combo is not None:
            self.page_size_combo.configure(values=list(self._page_size_display_to_value.keys()))
            self.page_size_combo.set(all_label if current_show_all else str(DEFAULT_PAGE_SIZE))

        self._update_status()
        # Re-render rows: category cells are translated at insert time and
        # would otherwise stay in the previous language (T17.13).
        self.refresh_results(reset_page=False)

    def _build_ui(self) -> None:
        content = ttk.Frame(self, style="App.TFrame", padding=20)
        content.grid(row=0, column=0, sticky="nsew")
        self.columnconfigure(0, weight=1)
        self.rowconfigure(0, weight=1)
        content.columnconfigure(0, weight=1)
        content.rowconfigure(3, weight=1)

        self.title_label = ttk.Label(content, text=self.translator.t("catalog_manager.title"), style="SectionTitle.TLabel")
        self.title_label.grid(row=0, column=0, sticky="w")
        self.description_label = ttk.Label(content, text=self.translator.t("catalog_manager.description"), style="Body.TLabel")
        self.description_label.grid(row=1, column=0, sticky="w", pady=(4, 12))

        filters = ttk.Frame(content, style="App.TFrame")
        filters.grid(row=2, column=0, sticky="ew", pady=(0, 10))
        filters.columnconfigure(1, weight=1)
        self.search_label = ttk.Label(filters, text=self.translator.t("catalog_manager.search_placeholder"), style="Body.TLabel")
        self.search_label.grid(row=0, column=0, sticky="w", padx=(0, 8))
        self.search_entry = ttk.Entry(filters, textvariable=self._search_var, style="Form.TEntry")
        self.search_entry.grid(row=0, column=1, sticky="ew", padx=(0, 8))
        self.search_entry.bind("<Return>", lambda _e: self._on_search())
        self._build_category_filter(filters)
        self.search_button = ttk.Button(filters, text=self.translator.t("catalog_manager.search"), style="Secondary.TButton", command=self._on_search)
        self.search_button.grid(row=0, column=3, padx=(0, 6))
        self.clear_button = ttk.Button(filters, text=self.translator.t("catalog_manager.clear_filters"), style="Secondary.TButton", command=self._on_clear)
        self.clear_button.grid(row=0, column=4)

        surface = tk.Frame(content, background=PALETTE["surface"], highlightbackground=PALETTE["border"], highlightthickness=1, bd=0)
        surface.grid(row=3, column=0, sticky="nsew")
        surface.columnconfigure(0, weight=1)
        surface.rowconfigure(1, weight=1)

        actions = ttk.Frame(surface, style="Surface.TFrame", padding=(12, 12, 12, 8))
        actions.grid(row=0, column=0, sticky="ew")
        self.add_button = ttk.Button(actions, text=self.translator.t("catalog_manager.add_entry"), style="Primary.TButton", command=self._on_add)
        self.add_button.grid(row=0, column=0, padx=(0, 8))
        self.edit_button = ttk.Button(actions, text=self.translator.t("catalog_manager.edit_entry"), style="Secondary.TButton", command=self._on_edit, state="disabled")
        self.edit_button.grid(row=0, column=1, padx=(0, 8))
        self.delete_button = ttk.Button(actions, text=self.translator.t("catalog_manager.delete_entry"), style="Secondary.TButton", command=self._on_delete, state="disabled")
        self.delete_button.grid(row=0, column=2, padx=(0, 8))
        self.import_button = ttk.Button(actions, text=self.translator.t("catalog_manager.import_catalog"), style="Secondary.TButton", command=self._on_import_catalog)
        self.import_button.grid(row=0, column=3, padx=(0, 8))
        self.export_button = ttk.Button(actions, text=self.translator.t("catalog_manager.export_catalog"), style="Secondary.TButton", command=self._on_export_catalog)
        self.export_button.grid(row=0, column=4)

        table_frame = ttk.Frame(surface, style="Surface.TFrame", padding=(12, 0, 12, 12))
        table_frame.grid(row=1, column=0, sticky="nsew")
        table_frame.columnconfigure(0, weight=1)
        table_frame.rowconfigure(0, weight=1)
        self.tree = ttk.Treeview(table_frame, columns=TABLE_COLUMNS, show="headings", selectmode="browse", style="Inventory.Treeview")
        self.tree.heading("category", text=self.translator.t("catalog_entry_form.category"), anchor="w")
        self.tree.heading("manufacturer", text=self.translator.t("catalog_entry_form.manufacturer"), anchor="w")
        self.tree.heading("model", text=self.translator.t("catalog_entry_form.model"), anchor="w")
        self.tree.heading("source", text=self.translator.t("catalog_entry_form.source"), anchor="w")
        self.tree.column("category", width=150, minwidth=110, anchor="w")
        self.tree.column("manufacturer", width=220, minwidth=140, anchor="w")
        self.tree.column("model", width=300, minwidth=180, anchor="w")
        self.tree.column("source", width=180, minwidth=120, anchor="w")
        vs = ttk.Scrollbar(table_frame, orient="vertical", command=self.tree.yview)
        hs = ttk.Scrollbar(table_frame, orient="horizontal", command=self.tree.xview)
        self.tree.configure(yscrollcommand=vs.set, xscrollcommand=hs.set)
        self.tree.grid(row=0, column=0, sticky="nsew")
        vs.grid(row=0, column=1, sticky="ns")
        hs.grid(row=1, column=0, sticky="ew")
        self.tree.bind("<<TreeviewSelect>>", lambda _e: self._update_actions())

        paging = ttk.Frame(surface, style="Surface.TFrame", padding=(12, 0, 12, 12))
        paging.grid(row=2, column=0, sticky="ew")
        paging.columnconfigure(3, weight=1)
        self.page_size_label = ttk.Label(paging, text=self.translator.t("catalog_manager.page_size_label"), style="SurfaceBody.TLabel")
        self.page_size_label.grid(row=0, column=0, padx=(0, 6))
        self._build_page_size_control(paging)
        self.prev_button = ttk.Button(paging, text=self.translator.t("catalog_manager.previous_page"), style="Secondary.TButton", command=self._on_prev)
        self.prev_button.grid(row=0, column=2, padx=(8, 0))
        self.status_label = ttk.Label(paging, style="SurfaceBody.TLabel")
        self.status_label.grid(row=0, column=3)
        self.next_button = ttk.Button(paging, text=self.translator.t("catalog_manager.next_page"), style="Secondary.TButton", command=self._on_next)
        self.next_button.grid(row=0, column=4)

    def _build_category_filter(self, parent: ttk.Frame) -> None:
        all_label = self.translator.t("catalog_manager.all_categories")
        values = [all_label] + [self.translator.translate_category(c) for c in CATEGORIES]
        self._category_display_to_canonical = {all_label: None}
        for canonical in CATEGORIES:
            self._category_display_to_canonical[self.translator.translate_category(canonical)] = canonical
        self.category_combo = ttk.Combobox(parent, values=values, state="readonly", width=22, style="Form.TCombobox", textvariable=self._category_var)
        self.category_combo.grid(row=0, column=2, padx=(0, 8))
        self.category_combo.set(all_label)

    def _build_page_size_control(self, parent: ttk.Frame) -> None:
        all_label = self.translator.t("catalog_manager.page_size_all")
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

    def _selected_entry_id(self) -> str | None:
        if self.tree is None:
            return None
        sel = self.tree.selection()
        if not sel:
            return None
        return self._entry_ids_by_item.get(sel[0])

    def _update_actions(self) -> None:
        state = "normal" if self._selected_entry_id() else "disabled"
        if self.edit_button is not None:
            self.edit_button.configure(state=state)
        if self.delete_button is not None:
            self.delete_button.configure(state=state)

    def _show_error(self, message_key: str) -> None:
        messagebox.showerror(
            self.translator.t("messages.catalog_error_title"),
            self.translator.t(message_key),
            parent=self._dialog_parent,
        )

    def refresh_results(self, reset_page: bool = False) -> None:
        if reset_page:
            self._offset = 0
        self._load_token += 1
        token = self._load_token
        if self.status_label is not None and self._show_all:
            self.status_label.configure(text=self.translator.t("catalog_manager.loading_progress").format(loaded=0, total=0))
            if self.winfo_exists():
                self.update_idletasks()
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
            self._show_error("messages.catalog_unavailable_error")
            return
        if token != self._load_token:
            return
        self._current_count = len(entries)
        self._begin_table_load(entries, token)

    def _begin_table_load(self, entries: list[CatalogEntry], token: int) -> None:
        if self.tree is None:
            return
        self._selected_id_pending = self._selected_entry_id()
        for item in self.tree.get_children():
            self.tree.delete(item)
        self._entry_ids_by_item.clear()
        self._update_actions()
        if not entries:
            self._finish_table_load(token, None)
            return
        if self._show_all and len(entries) > CHUNK_SIZE:
            self._insert_chunk(entries, 0, token, self._selected_id_pending)
        else:
            selected_item = self._insert_entries(entries)
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
        if token != self._load_token or self.tree is None or not self.winfo_exists():
            return
        end = min(index + CHUNK_SIZE, len(entries))
        selected_item = self._insert_entries(entries[index:end], selected_id)
        loaded = end
        if self.status_label is not None:
            self.status_label.configure(
                text=self.translator.t("catalog_manager.loading_progress").format(loaded=loaded, total=self._total)
            )
        if selected_item is not None:
            self.tree.selection_set(selected_item)
            self.tree.focus(selected_item)
        if end < len(entries):
            self.after(1, lambda: self._insert_chunk(entries, end, token, selected_id))
        else:
            self._finish_table_load(token, selected_item)

    def _finish_table_load(self, token: int, selected_item: str | None) -> None:
        if token != self._load_token or self.tree is None:
            return
        if selected_item is not None:
            self.tree.selection_set(selected_item)
            self.tree.focus(selected_item)
        self._update_actions()
        self._update_status()

    def _populate_table(self, entries: list[CatalogEntry]) -> None:
        self._load_token += 1
        self._begin_table_load(entries, self._load_token)

    def _update_status(self) -> None:
        pages = max(1, (self._total + DEFAULT_PAGE_SIZE - 1) // DEFAULT_PAGE_SIZE)
        page = (self._offset // DEFAULT_PAGE_SIZE) + 1 if self._total else 1
        if self.status_label is not None:
            if self._total == 0:
                self.status_label.configure(text=self.translator.t("catalog_manager.no_results"))
            elif self._show_all:
                self.status_label.configure(text=self.translator.t("catalog_manager.showing_all").format(total=self._total))
            else:
                shown = self._offset + self._current_count
                summary = self.translator.t("catalog_manager.results_summary").format(shown=shown, total=self._total)
                page_text = self.translator.t("catalog_manager.page_label").format(page=page, pages=pages)
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
        self._category = None
        if self.category_combo is not None:
            self.category_combo.set(self.translator.t("catalog_manager.all_categories"))
        self._query = ""
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

    def _on_add(self) -> None:
        form = CatalogEntryForm(self._dialog_parent, self.translator)
        self._dialog_parent.wait_window(form.window)
        if form.result is None:
            return
        try:
            self.catalog_service.add_entry(form.result)
        except CatalogValidationError:
            self._show_error("messages.validation_error")
            return
        except CatalogDuplicateError:
            self._show_error("messages.catalog_duplicate_error")
            return
        except CatalogStorageError:
            self._show_error("messages.catalog_unavailable_error")
            return
        self._query = self._search_var.get().strip()
        self._category = self._category_display_to_canonical.get(self._category_var.get())
        self.refresh_results(reset_page=True)

    def _on_edit(self) -> None:
        entry_id = self._selected_entry_id()
        if not entry_id:
            return
        try:
            entry = self.catalog_service.get_entry(entry_id)
        except CatalogStorageError:
            self._show_error("messages.catalog_unavailable_error")
            return
        if entry is None:
            self._show_error("messages.catalog_not_found_error")
            self.refresh_results(reset_page=False)
            return
        form = CatalogEntryForm(self._dialog_parent, self.translator, entry=entry)
        self._dialog_parent.wait_window(form.window)
        if form.result is None:
            return
        try:
            self.catalog_service.update_entry(form.result)
        except CatalogValidationError:
            self._show_error("messages.validation_error")
            return
        except CatalogDuplicateError:
            self._show_error("messages.catalog_duplicate_error")
            return
        except CatalogEntryNotFoundError:
            self._show_error("messages.catalog_not_found_error")
            self.refresh_results(reset_page=False)
            return
        except CatalogStorageError:
            self._show_error("messages.catalog_unavailable_error")
            return
        self.refresh_results(reset_page=False)

    def _on_delete(self) -> None:
        entry_id = self._selected_entry_id()
        if not entry_id:
            return
        confirmed = messagebox.askyesno(
            self.translator.t("catalog_manager.delete_confirmation_title"),
            self.translator.t("catalog_manager.delete_confirmation"),
            parent=self._dialog_parent,
            icon="warning",
        )
        if not confirmed:
            return
        try:
            self.catalog_service.delete_entry(entry_id)
        except CatalogEntryNotFoundError:
            self._show_error("messages.catalog_not_found_error")
        except CatalogStorageError:
            self._show_error("messages.catalog_unavailable_error")
            return
        self.refresh_results(reset_page=False)

    def _on_import_catalog(self) -> None:
        filetypes = [
            (self.translator.t("catalog_manager.import_dialog_csv"), "*.csv"),
            (self.translator.t("catalog_manager.import_dialog_json"), "*.json"),
            (self.translator.t("catalog_manager.import_dialog_all"), "*.csv *.json"),
        ]
        selected = filedialog.askopenfilename(
            parent=self._dialog_parent,
            title=self.translator.t("catalog_manager.import_dialog_title"),
            filetypes=filetypes,
        )
        if not selected:
            return
        try:
            result = self.catalog_service.import_file(Path(selected), skip_duplicates=True)
        except CatalogImportError as exc:
            detail = self.translator.t("catalog_manager.import_invalid_file")
            if exc.row_number is not None and exc.field:
                detail += "\n" + self.translator.t("catalog_manager.import_invalid_row_field").format(
                    row_number=exc.row_number, field=exc.field
                )
            elif exc.row_number is not None:
                detail += "\n" + self.translator.t("catalog_manager.import_invalid_row").format(
                    row_number=exc.row_number
                )
            elif exc.field:
                detail += "\n" + self.translator.t("catalog_manager.import_invalid_field").format(field=exc.field)
            messagebox.showerror(
                self.translator.t("messages.catalog_error_title"),
                detail,
                parent=self._dialog_parent,
            )
            return
        except CatalogDuplicateError:
            self._show_error("messages.catalog_duplicate_error")
            return
        except CatalogFileError:
            messagebox.showerror(
                self.translator.t("messages.catalog_error_title"),
                self.translator.t("catalog_manager.import_file_error"),
                parent=self._dialog_parent,
            )
            return
        except CatalogStorageError:
            messagebox.showerror(
                self.translator.t("messages.catalog_error_title"),
                self.translator.t("catalog_manager.import_storage_error"),
                parent=self._dialog_parent,
            )
            return
        self._search_var.set("")
        self._query = ""
        self._category = None
        if self.category_combo is not None:
            self.category_combo.set(self.translator.t("catalog_manager.all_categories"))
        self.refresh_results(reset_page=True)
        summary = self.translator.t("catalog_manager.import_success_summary").format(
            total_entries=result.total_entries,
            inserted_count=result.inserted_count,
            duplicate_count=result.duplicate_count,
        )
        messagebox.showinfo(
            self.translator.t("catalog_manager.import_success_title"),
            summary,
            parent=self._dialog_parent,
        )

    def _on_export_catalog(self) -> None:
        filetypes = [
            (self.translator.t("catalog_manager.export_dialog_csv"), "*.csv"),
            (self.translator.t("catalog_manager.export_dialog_json"), "*.json"),
        ]
        selected = filedialog.asksaveasfilename(
            parent=self._dialog_parent,
            title=self.translator.t("catalog_manager.export_dialog_title"),
            defaultextension=".csv",
            initialfile="catalog.csv",
            filetypes=filetypes,
        )
        if not selected:
            return
        try:
            exported_count = self.catalog_service.export_file(Path(selected))
        except CatalogFileError:
            messagebox.showerror(
                self.translator.t("messages.catalog_error_title"),
                self.translator.t("catalog_manager.export_file_error"),
                parent=self._dialog_parent,
            )
            return
        except CatalogStorageError:
            messagebox.showerror(
                self.translator.t("messages.catalog_error_title"),
                self.translator.t("catalog_manager.export_storage_error"),
                parent=self._dialog_parent,
            )
            return
        messagebox.showinfo(
            self.translator.t("catalog_manager.export_success_title"),
            self.translator.t("catalog_manager.export_success_summary").format(exported_count=exported_count),
            parent=self._dialog_parent,
        )


# Compatibility alias (legacy name)
CatalogManagerWindow = CatalogManagerView
