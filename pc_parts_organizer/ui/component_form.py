"""Modal form for adding or editing components."""

from __future__ import annotations

import re
import tkinter as tk
from dataclasses import dataclass
from datetime import date
from decimal import Decimal, InvalidOperation
from tkinter import messagebox, ttk

from pc_parts_organizer.catalog_service import CatalogService, CatalogStorageError
from pc_parts_organizer.localization import LocalizationError, Translator
from pc_parts_organizer.models import CATEGORIES, COMPONENT_STATUSES, Component
from pc_parts_organizer.ui.catalog_selector import CatalogSelectorWindow
from pc_parts_organizer.ui.theme import PALETTE


_ISO_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_CURRENCY_RE = re.compile(r"^[A-Za-z]{3}$")


def _normalize_form_date(value: str) -> str:
    normalized = value.strip()
    if not normalized:
        return ""
    if not _ISO_DATE_RE.fullmatch(normalized):
        raise ValueError("invalid date")
    date.fromisoformat(normalized)
    return normalized


def _normalize_form_price(value: str) -> str:
    raw = value.strip()
    if not raw:
        return ""
    if "e" in raw.lower():
        raise ValueError("invalid price")
    if raw.count(",") + raw.count(".") > 1 or ("," in raw and "." in raw):
        raise ValueError("invalid price")
    sep = "," if "," in raw else ("." if "." in raw else None)
    int_part, frac_part = raw.split(sep) if sep else (raw, "")
    if not int_part:
        int_part = "0"
    if not int_part.isdigit() or (frac_part and not frac_part.isdigit()):
        raise ValueError("invalid price")
    if len(frac_part) > 4:
        raise ValueError("invalid price")
    int_canonical = str(int(int_part))
    if len(int_canonical) > 12:
        raise ValueError("invalid price")
    decimal_text = int_canonical + ("." + frac_part if frac_part else "")
    try:
        dec = Decimal(decimal_text)
    except InvalidOperation as exc:
        raise ValueError("invalid price") from exc
    if dec < 0 or not dec.is_finite() or dec.is_nan():
        raise ValueError("invalid price")
    return decimal_text


def _normalize_form_currency(value: str) -> str:
    normalized = value.strip()
    if not normalized:
        return ""
    if not _CURRENCY_RE.fullmatch(normalized):
        raise ValueError("invalid currency")
    return normalized.upper()


@dataclass
class ComponentFormData:
    """Validated form data for a component."""

    category: str
    manufacturer: str
    model: str
    specifications: str
    notes: str
    status: str = "unspecified"
    location: str = ""
    purchase_date: str = ""
    warranty_end_date: str = ""
    purchase_price: str = ""
    purchase_currency: str = ""


class ComponentForm:
    """Toplevel modal form for component input (add or edit)."""

    def __init__(
        self,
        parent: tk.Misc,
        translator: Translator,
        catalog_service: CatalogService,
        component: Component | None = None,
    ) -> None:
        self.translator = translator
        self.catalog_service = catalog_service
        self.component_id = component.id if component is not None else None
        self._editing = component is not None
        self.result: ComponentFormData | None = None
        self._status_display_to_canonical: dict[str, str] = {}
        self.window = tk.Toplevel(parent)
        title_key = "component_form.title_edit" if self._editing else "component_form.title_add"
        self.window.title(self.translator.t(title_key))
        self.window.transient(parent)
        self.window.configure(background=PALETTE["surface"])
        self.window.resizable(False, False)
        self.window.geometry("560x760")
        self.window.minsize(520, 680)
        self.window.protocol("WM_DELETE_WINDOW", self._on_cancel)
        self.window.bind("<Escape>", lambda _e: self._on_cancel())

        self._category_combo: ttk.Combobox | None = None
        self._manufacturer_entry: ttk.Entry | None = None
        self._model_entry: ttk.Entry | None = None
        self._status_combo: ttk.Combobox | None = None
        self._location_entry: ttk.Entry | None = None
        self._purchase_date_entry: ttk.Entry | None = None
        self._warranty_end_date_entry: ttk.Entry | None = None
        self._purchase_price_entry: ttk.Entry | None = None
        self._purchase_currency_entry: ttk.Entry | None = None
        self._specs_text: tk.Text | None = None
        self._notes_text: tk.Text | None = None
        self._build_ui(component)
        self.window.grab_set()
        if self._manufacturer_entry is not None:
            self._manufacturer_entry.focus_set()

    def _build_ui(self, component: Component | None = None) -> None:
        frame = ttk.Frame(self.window, style="Form.TFrame", padding=20)
        frame.grid(row=0, column=0, sticky="nsew")
        self.window.columnconfigure(0, weight=1)
        self.window.rowconfigure(0, weight=1)
        frame.columnconfigure(1, weight=1)

        row = 0
        ttk.Button(
            frame,
            text=self.translator.t("component_form.search_catalog"),
            style="Secondary.TButton",
            command=self._on_search_catalog,
        ).grid(row=row, column=0, columnspan=2, sticky="w", pady=(0, 10))

        row += 1
        ttk.Label(frame, text=self.translator.t("component_form.category"), style="Form.TLabel").grid(
            row=row, column=0, sticky="w", pady=(0, 6)
        )
        labels = [self.translator.translate_category(category) for category in CATEGORIES]
        self._category_combo = ttk.Combobox(
            frame, values=labels, state="readonly", style="Form.TCombobox", width=40
        )
        self._category_combo.grid(row=row, column=1, sticky="ew", pady=(0, 6))
        if labels:
            self._category_combo.set(labels[0])

        row += 1
        ttk.Label(frame, text=self.translator.t("component_form.manufacturer"), style="Form.TLabel").grid(
            row=row, column=0, sticky="w", pady=(0, 6)
        )
        self._manufacturer_entry = ttk.Entry(frame, style="Form.TEntry")
        self._manufacturer_entry.grid(row=row, column=1, sticky="ew", pady=(0, 6))

        row += 1
        ttk.Label(frame, text=self.translator.t("component_form.model"), style="Form.TLabel").grid(
            row=row, column=0, sticky="w", pady=(0, 6)
        )
        self._model_entry = ttk.Entry(frame, style="Form.TEntry")
        self._model_entry.grid(row=row, column=1, sticky="ew", pady=(0, 6))

        row += 1
        ttk.Label(
            frame, text=self.translator.t("component_form.status_location_group"), style="Form.TLabel"
        ).grid(row=row, column=0, columnspan=2, sticky="w", pady=(6, 4))

        row += 1
        ttk.Label(frame, text=self.translator.t("component_form.status"), style="Form.TLabel").grid(
            row=row, column=0, sticky="w", pady=(0, 6)
        )
        status_labels = []
        self._status_display_to_canonical = {}
        for canonical in COMPONENT_STATUSES:
            label = self.translator.translate_status(canonical)
            status_labels.append(label)
            self._status_display_to_canonical[label] = canonical
        self._status_combo = ttk.Combobox(
            frame, values=status_labels, state="readonly", style="Form.TCombobox", width=40
        )
        self._status_combo.grid(row=row, column=1, sticky="ew", pady=(0, 6))
        self._status_combo.set(self.translator.translate_status("unspecified"))

        row += 1
        ttk.Label(frame, text=self.translator.t("component_form.location"), style="Form.TLabel").grid(
            row=row, column=0, sticky="w", pady=(0, 6)
        )
        self._location_entry = ttk.Entry(frame, style="Form.TEntry")
        self._location_entry.grid(row=row, column=1, sticky="ew", pady=(0, 6))

        row += 1
        ttk.Label(
            frame, text=self.translator.t("component_form.acquisition_warranty_group"), style="Form.TLabel"
        ).grid(row=row, column=0, columnspan=2, sticky="w", pady=(6, 4))

        row += 1
        ttk.Label(frame, text=self.translator.t("component_form.purchase_date"), style="Form.TLabel").grid(
            row=row, column=0, sticky="w", pady=(0, 6)
        )
        self._purchase_date_entry = ttk.Entry(frame, style="Form.TEntry")
        self._purchase_date_entry.grid(row=row, column=1, sticky="ew", pady=(0, 6))

        row += 1
        ttk.Label(frame, text=self.translator.t("component_form.warranty_end_date"), style="Form.TLabel").grid(
            row=row, column=0, sticky="w", pady=(0, 6)
        )
        self._warranty_end_date_entry = ttk.Entry(frame, style="Form.TEntry")
        self._warranty_end_date_entry.grid(row=row, column=1, sticky="ew", pady=(0, 6))

        row += 1
        ttk.Label(frame, text=self.translator.t("component_form.purchase_price"), style="Form.TLabel").grid(
            row=row, column=0, sticky="w", pady=(0, 6)
        )
        price_frame = ttk.Frame(frame, style="Form.TFrame")
        price_frame.grid(row=row, column=1, sticky="ew", pady=(0, 6))
        price_frame.columnconfigure(0, weight=1)
        self._purchase_price_entry = ttk.Entry(price_frame, style="Form.TEntry", width=16)
        self._purchase_price_entry.grid(row=0, column=0, sticky="ew", padx=(0, 8))
        ttk.Label(price_frame, text=self.translator.t("component_form.purchase_currency"), style="Form.TLabel").grid(
            row=0, column=1, sticky="w", padx=(0, 6)
        )
        self._purchase_currency_entry = ttk.Entry(price_frame, style="Form.TEntry", width=6)
        self._purchase_currency_entry.grid(row=0, column=2, sticky="w")

        row += 1
        ttk.Label(frame, text=self.translator.t("component_form.date_format_help"), style="SurfaceBody.TLabel").grid(
            row=row, column=1, sticky="w", pady=(0, 2)
        )
        row += 1
        ttk.Label(frame, text=self.translator.t("component_form.price_currency_help"), style="SurfaceBody.TLabel").grid(
            row=row, column=1, sticky="w", pady=(0, 6)
        )

        row += 1
        ttk.Label(frame, text=self.translator.t("component_form.specifications"), style="Form.TLabel").grid(
            row=row, column=0, sticky="nw", pady=(0, 6)
        )
        self._specs_text = tk.Text(
            frame,
            height=6,
            wrap="word",
            font=("Segoe UI", 10),
            background=PALETTE["surface"],
            foreground=PALETTE["text"],
            insertbackground=PALETTE["text"],
            highlightbackground=PALETTE["border"],
            highlightthickness=1,
            bd=0,
            padx=6,
            pady=4,
        )
        self._specs_text.grid(row=row, column=1, sticky="ew", pady=(0, 6))

        row += 1
        ttk.Label(frame, text=self.translator.t("component_form.notes"), style="Form.TLabel").grid(
            row=row, column=0, sticky="nw", pady=(0, 6)
        )
        self._notes_text = tk.Text(
            frame,
            height=5,
            wrap="word",
            font=("Segoe UI", 10),
            background=PALETTE["surface"],
            foreground=PALETTE["text"],
            insertbackground=PALETTE["text"],
            highlightbackground=PALETTE["border"],
            highlightthickness=1,
            bd=0,
            padx=6,
            pady=4,
        )
        self._notes_text.grid(row=row, column=1, sticky="ew", pady=(0, 6))

        row += 1
        actions = ttk.Frame(frame, style="Form.TFrame")
        actions.grid(row=row, column=0, columnspan=2, sticky="e", pady=(10, 0))
        ttk.Button(
            actions,
            text=self.translator.t("component_form.cancel"),
            style="Secondary.TButton",
            command=self._on_cancel,
        ).grid(row=0, column=0, padx=(0, 8))
        save_key = "component_form.save_edit" if self._editing else "component_form.save"
        ttk.Button(
            actions,
            text=self.translator.t(save_key),
            style="Primary.TButton",
            command=self._on_submit,
        ).grid(row=0, column=1)

        if component is not None:
            self._load_component(component)

    def _load_component(self, component: Component) -> None:
        if self._category_combo is not None:
            self._category_combo.set(self.translator.translate_category(component.category))
        if self._manufacturer_entry is not None:
            self._manufacturer_entry.delete(0, "end")
            self._manufacturer_entry.insert(0, component.manufacturer)
        if self._model_entry is not None:
            self._model_entry.delete(0, "end")
            self._model_entry.insert(0, component.model)
        if self._status_combo is not None:
            status = getattr(component, "status", "unspecified") or "unspecified"
            try:
                self._status_combo.set(self.translator.translate_status(status))
            except Exception:
                self._status_combo.set(self.translator.translate_status("unspecified"))
        if self._location_entry is not None:
            self._location_entry.delete(0, "end")
            self._location_entry.insert(0, getattr(component, "location", "") or "")
        if self._purchase_date_entry is not None:
            self._purchase_date_entry.delete(0, "end")
            self._purchase_date_entry.insert(0, getattr(component, "purchase_date", "") or "")
        if self._warranty_end_date_entry is not None:
            self._warranty_end_date_entry.delete(0, "end")
            self._warranty_end_date_entry.insert(0, getattr(component, "warranty_end_date", "") or "")
        if self._purchase_price_entry is not None:
            self._purchase_price_entry.delete(0, "end")
            self._purchase_price_entry.insert(0, getattr(component, "purchase_price", "") or "")
        if self._purchase_currency_entry is not None:
            self._purchase_currency_entry.delete(0, "end")
            self._purchase_currency_entry.insert(0, getattr(component, "purchase_currency", "") or "")
        self._set_text(self._specs_text, component.specifications or "")
        self._set_text(self._notes_text, component.notes or "")

    def _text_value(self, widget: tk.Text | None) -> str:
        if widget is None:
            return ""
        # tk.Text adds a trailing newline; preserve user content/newlines except that artifact.
        return widget.get("1.0", "end-1c")

    def _set_text(self, widget: tk.Text | None, value: str) -> None:
        if widget is None:
            return
        widget.delete("1.0", "end")
        if value:
            widget.insert("1.0", value)

    def _on_search_catalog(self) -> None:
        try:
            self.catalog_service.initialize()
        except CatalogStorageError:
            messagebox.showerror(
                self.translator.t("messages.catalog_error_title"),
                self.translator.t("catalog_selector.initialization_error"),
                parent=self.window,
            )
            return
        selector = CatalogSelectorWindow(self.window, self.catalog_service, self.translator)
        self.window.wait_window(selector.window)
        if selector.result is None:
            return
        entry = selector.result
        if self._category_combo is not None:
            self._category_combo.set(self.translator.translate_category(entry.category))
        if self._manufacturer_entry is not None:
            self._manufacturer_entry.delete(0, "end")
            self._manufacturer_entry.insert(0, entry.manufacturer)
        if self._model_entry is not None:
            self._model_entry.delete(0, "end")
            self._model_entry.insert(0, entry.model)
        self._set_text(self._specs_text, entry.specifications)
        # Intentionally does not alter status or location.

    def _on_submit(self) -> None:
        if (
            self._category_combo is None
            or self._manufacturer_entry is None
            or self._model_entry is None
            or self._status_combo is None
            or self._location_entry is None
        ):
            return
        manufacturer = self._manufacturer_entry.get().strip()
        model = self._model_entry.get().strip()
        category_label = self._category_combo.get().strip()
        if not manufacturer or not model or not category_label:
            messagebox.showerror(
                self.translator.t("messages.validation_title"),
                self.translator.t("component_form.required_fields_error"),
                parent=self.window,
            )
            return
        try:
            category = self.translator.category_from_label(category_label)
        except (LocalizationError, KeyError, ValueError):
            messagebox.showerror(
                self.translator.t("messages.validation_title"),
                self.translator.t("component_form.required_fields_error"),
                parent=self.window,
            )
            return
        status_label = self._status_combo.get().strip()
        try:
            status = self._status_display_to_canonical.get(status_label) or self.translator.status_from_label(status_label)
        except (LocalizationError, KeyError, ValueError):
            status = "unspecified"
        location = self._location_entry.get().strip()
        purchase_raw = self._purchase_date_entry.get() if self._purchase_date_entry is not None else ""
        warranty_raw = self._warranty_end_date_entry.get() if self._warranty_end_date_entry is not None else ""
        try:
            purchase_date = _normalize_form_date(purchase_raw)
            warranty_end_date = _normalize_form_date(warranty_raw)
        except ValueError:
            messagebox.showerror(
                self.translator.t("messages.validation_title"),
                self.translator.t("component_form.invalid_date_error"),
                parent=self.window,
            )
            return
        price_raw = self._purchase_price_entry.get() if self._purchase_price_entry is not None else ""
        currency_raw = self._purchase_currency_entry.get() if self._purchase_currency_entry is not None else ""
        try:
            purchase_price = _normalize_form_price(price_raw)
        except ValueError:
            messagebox.showerror(
                self.translator.t("messages.validation_title"),
                self.translator.t("component_form.invalid_price_error"),
                parent=self.window,
            )
            return
        try:
            purchase_currency = _normalize_form_currency(currency_raw)
        except ValueError:
            messagebox.showerror(
                self.translator.t("messages.validation_title"),
                self.translator.t("component_form.invalid_currency_error"),
                parent=self.window,
            )
            return
        if bool(purchase_price) != bool(purchase_currency):
            messagebox.showerror(
                self.translator.t("messages.validation_title"),
                self.translator.t("component_form.price_currency_pair_error"),
                parent=self.window,
            )
            return
        self.result = ComponentFormData(
            category=category,
            manufacturer=manufacturer,
            model=model,
            specifications=self._text_value(self._specs_text),
            notes=self._text_value(self._notes_text),
            status=status,
            location=location,
            purchase_date=purchase_date,
            warranty_end_date=warranty_end_date,
            purchase_price=purchase_price,
            purchase_currency=purchase_currency,
        )
        self.window.destroy()

    def _on_cancel(self) -> None:
        self.result = None
        self.window.destroy()
