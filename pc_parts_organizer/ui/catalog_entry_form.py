"""Modal form for catalog entry creation and editing."""

from __future__ import annotations

import tkinter as tk
from tkinter import messagebox, ttk

from pc_parts_organizer.catalog_models import CatalogEntry, CatalogValidationError
from pc_parts_organizer.localization import Translator
from pc_parts_organizer.models import CATEGORIES
from pc_parts_organizer.ui.theme import PALETTE


class CatalogEntryForm:
    """Toplevel modal form for a catalog reference."""

    def __init__(
        self,
        parent: tk.Misc,
        translator: Translator,
        entry: CatalogEntry | None = None,
    ) -> None:
        self.translator = translator
        self.entry = entry
        self.result: CatalogEntry | None = None
        self.window = tk.Toplevel(parent)
        title_key = "catalog_entry_form.edit_title" if entry is not None else "catalog_entry_form.add_title"
        self.window.title(self.translator.t(title_key))
        self.window.transient(parent)
        self.window.configure(background=PALETTE["surface"])
        self.window.geometry("620x720")
        self.window.minsize(560, 520)
        self.window.protocol("WM_DELETE_WINDOW", self._on_cancel)
        self.window.bind("<Escape>", lambda _e: self._on_cancel())
        self._category_combo: ttk.Combobox | None = None
        self._manufacturer: ttk.Entry | None = None
        self._model: ttk.Entry | None = None
        self._specs: tk.Text | None = None
        self._notes: tk.Text | None = None
        self._source: ttk.Entry | None = None
        self._source_url: ttk.Entry | None = None
        self._source_license: ttk.Entry | None = None
        self._attribution: tk.Text | None = None
        self._verified_at: ttk.Entry | None = None
        self._build_ui()
        self._load_entry()
        self.window.grab_set()
        if self._manufacturer is not None:
            self._manufacturer.focus_set()

    def _build_ui(self) -> None:
        outer = ttk.Frame(self.window, style="Form.TFrame")
        outer.grid(row=0, column=0, sticky="nsew")
        self.window.columnconfigure(0, weight=1)
        self.window.rowconfigure(0, weight=1)
        outer.columnconfigure(0, weight=1)
        outer.rowconfigure(0, weight=1)

        canvas = tk.Canvas(outer, background=PALETTE["surface"], highlightthickness=0, bd=0)
        scrollbar = ttk.Scrollbar(outer, orient="vertical", command=canvas.yview)
        canvas.configure(yscrollcommand=scrollbar.set)
        canvas.grid(row=0, column=0, sticky="nsew")
        scrollbar.grid(row=0, column=1, sticky="ns")

        frame = ttk.Frame(canvas, style="Form.TFrame", padding=20)
        frame.columnconfigure(1, weight=1)
        window_id = canvas.create_window((0, 0), window=frame, anchor="nw")

        def on_configure(_event: object = None) -> None:
            canvas.configure(scrollregion=canvas.bbox("all"))
            canvas.itemconfigure(window_id, width=canvas.winfo_width())

        frame.bind("<Configure>", on_configure)
        canvas.bind("<Configure>", on_configure)

        row = 0
        self._add_label(frame, row, "catalog_entry_form.category")
        labels = [self.translator.translate_category(c) for c in CATEGORIES]
        self._category_combo = ttk.Combobox(frame, values=labels, state="readonly", style="Form.TCombobox")
        self._category_combo.grid(row=row, column=1, sticky="ew", pady=(0, 6))
        if labels:
            self._category_combo.set(labels[0])

        row += 1
        self._add_label(frame, row, "catalog_entry_form.manufacturer")
        self._manufacturer = ttk.Entry(frame, style="Form.TEntry")
        self._manufacturer.grid(row=row, column=1, sticky="ew", pady=(0, 6))

        row += 1
        self._add_label(frame, row, "catalog_entry_form.model")
        self._model = ttk.Entry(frame, style="Form.TEntry")
        self._model.grid(row=row, column=1, sticky="ew", pady=(0, 6))

        row += 1
        self._add_label(frame, row, "catalog_entry_form.specifications", top=True)
        self._specs = self._make_text(frame, row, 5)

        row += 1
        self._add_label(frame, row, "catalog_entry_form.notes", top=True)
        self._notes = self._make_text(frame, row, 4)

        row += 1
        self._add_label(frame, row, "catalog_entry_form.source")
        self._source = ttk.Entry(frame, style="Form.TEntry")
        self._source.grid(row=row, column=1, sticky="ew", pady=(0, 6))

        row += 1
        self._add_label(frame, row, "catalog_entry_form.source_url")
        self._source_url = ttk.Entry(frame, style="Form.TEntry")
        self._source_url.grid(row=row, column=1, sticky="ew", pady=(0, 6))

        row += 1
        self._add_label(frame, row, "catalog_entry_form.source_license")
        self._source_license = ttk.Entry(frame, style="Form.TEntry")
        self._source_license.grid(row=row, column=1, sticky="ew", pady=(0, 6))

        row += 1
        self._add_label(frame, row, "catalog_entry_form.attribution", top=True)
        self._attribution = self._make_text(frame, row, 4)

        row += 1
        self._add_label(frame, row, "catalog_entry_form.verified_at")
        self._verified_at = ttk.Entry(frame, style="Form.TEntry")
        self._verified_at.grid(row=row, column=1, sticky="ew", pady=(0, 6))

        row += 1
        actions = ttk.Frame(frame, style="Form.TFrame")
        actions.grid(row=row, column=0, columnspan=2, sticky="e", pady=(10, 0))
        ttk.Button(actions, text=self.translator.t("catalog_entry_form.cancel"), style="Secondary.TButton", command=self._on_cancel).grid(row=0, column=0, padx=(0, 8))
        ttk.Button(actions, text=self.translator.t("catalog_entry_form.save"), style="Primary.TButton", command=self._on_submit).grid(row=0, column=1)

    def _add_label(self, frame: ttk.Frame, row: int, key: str, top: bool = False) -> None:
        ttk.Label(frame, text=self.translator.t(key), style="Form.TLabel").grid(
            row=row, column=0, sticky="nw" if top else "w", pady=(0, 6), padx=(0, 10)
        )

    def _make_text(self, frame: ttk.Frame, row: int, height: int) -> tk.Text:
        widget = tk.Text(
            frame, height=height, wrap="word", font=("Segoe UI", 10),
            background=PALETTE["surface"], foreground=PALETTE["text"],
            insertbackground=PALETTE["text"], highlightbackground=PALETTE["border"],
            highlightthickness=1, bd=0, padx=6, pady=4,
        )
        widget.grid(row=row, column=1, sticky="ew", pady=(0, 6))
        return widget

    def _text_value(self, widget: tk.Text | None) -> str:
        if widget is None:
            return ""
        return widget.get("1.0", "end-1c")

    def _set_text(self, widget: tk.Text | None, value: str) -> None:
        if widget is None:
            return
        widget.delete("1.0", "end")
        if value:
            widget.insert("1.0", value)

    def _load_entry(self) -> None:
        if self.entry is None:
            return
        if self._category_combo is not None:
            self._category_combo.set(self.translator.translate_category(self.entry.category))
        if self._manufacturer is not None:
            self._manufacturer.insert(0, self.entry.manufacturer)
        if self._model is not None:
            self._model.insert(0, self.entry.model)
        self._set_text(self._specs, self.entry.specifications)
        self._set_text(self._notes, self.entry.notes)
        if self._source is not None:
            self._source.insert(0, self.entry.source)
        if self._source_url is not None:
            self._source_url.insert(0, self.entry.source_url)
        if self._source_license is not None:
            self._source_license.insert(0, self.entry.source_license)
        self._set_text(self._attribution, self.entry.attribution)
        if self._verified_at is not None:
            self._verified_at.insert(0, self.entry.verified_at)

    def _on_submit(self) -> None:
        if self._category_combo is None or self._manufacturer is None or self._model is None:
            return
        try:
            category = self.translator.category_from_label(self._category_combo.get())
            data = {
                "category": category,
                "manufacturer": self._manufacturer.get(),
                "model": self._model.get(),
                "specifications": self._text_value(self._specs),
                "notes": self._text_value(self._notes),
                "source": self._source.get() if self._source is not None else "",
                "source_url": self._source_url.get() if self._source_url is not None else "",
                "source_license": self._source_license.get() if self._source_license is not None else "",
                "attribution": self._text_value(self._attribution),
                "verified_at": self._verified_at.get() if self._verified_at is not None else "",
            }
            if self.entry is not None:
                data["id"] = self.entry.id
            self.result = CatalogEntry(**data)
        except CatalogValidationError:
            messagebox.showerror(
                self.translator.t("messages.validation_title"),
                self.translator.t("messages.validation_error"),
                parent=self.window,
            )
            return
        self.window.destroy()

    def _on_cancel(self) -> None:
        self.result = None
        self.window.destroy()
