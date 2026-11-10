"""Dashboard (Home) view component."""

from __future__ import annotations

import tkinter as tk
from tkinter import ttk
from typing import Any

from pc_parts_organizer.localization import Translator
from pc_parts_organizer.ui.theme import PALETTE


class DashboardView(ttk.Frame):
    """Independent Home/dashboard view. Receives summary data; no persistence access."""

    def __init__(self, parent: tk.Misc, translator: Translator) -> None:
        super().__init__(parent, style="Dashboard.TFrame")
        self.translator = translator
        self._summary: Any = None

        self.dashboard_title_label: ttk.Label | None = None
        self.dashboard_total_label: ttk.Label | None = None
        self.dashboard_total_value: ttk.Label | None = None
        self.dashboard_distribution_label: ttk.Label | None = None
        self.dashboard_empty_label: ttk.Label | None = None
        self._distribution_frame: ttk.Frame | None = None

        self._economic_card: tk.Frame | None = None
        self._economic_title_label: ttk.Label | None = None
        self._priced_label: ttk.Label | None = None
        self._priced_value: ttk.Label | None = None
        self._unpriced_label: ttk.Label | None = None
        self._unpriced_value: ttk.Label | None = None
        self._subtotals_title_label: ttk.Label | None = None
        self._subtotals_frame: ttk.Frame | None = None
        self._no_amounts_label: ttk.Label | None = None
        self._disclaimer_label: ttk.Label | None = None

        self._build_ui()

    def _build_ui(self) -> None:
        self.grid(row=0, column=0, sticky="nsew")
        self.columnconfigure(0, weight=0, minsize=220)
        self.columnconfigure(1, weight=1)

        self.dashboard_title_label = ttk.Label(self, style="DashboardTitle.TLabel")
        self.dashboard_title_label.grid(row=0, column=0, columnspan=2, sticky="w", pady=(0, 8))

        total_card = tk.Frame(
            self,
            background=PALETTE["surface"],
            highlightbackground=PALETTE["border"],
            highlightthickness=1,
            bd=0,
            padx=16,
            pady=14,
        )
        total_card.grid(row=1, column=0, sticky="nsew", padx=(0, 12))
        self.dashboard_total_label = ttk.Label(total_card, style="DashboardLabel.TLabel")
        self.dashboard_total_label.pack(anchor="w")
        self.dashboard_total_value = ttk.Label(total_card, style="DashboardTotal.TLabel", text="0")
        self.dashboard_total_value.pack(anchor="w", pady=(2, 0))

        distribution_card = tk.Frame(
            self,
            background=PALETTE["surface"],
            highlightbackground=PALETTE["border"],
            highlightthickness=1,
            bd=0,
            padx=16,
            pady=14,
        )
        distribution_card.grid(row=1, column=1, sticky="nsew")
        distribution_card.columnconfigure(0, weight=1)
        self.dashboard_distribution_label = ttk.Label(
            distribution_card, style="DashboardLabel.TLabel"
        )
        self.dashboard_distribution_label.grid(row=0, column=0, sticky="w")
        self._distribution_frame = ttk.Frame(distribution_card, style="DashboardCard.TFrame")
        self._distribution_frame.grid(row=1, column=0, sticky="ew", pady=(8, 0))
        self._distribution_frame.columnconfigure(1, weight=1)
        self.dashboard_empty_label = ttk.Label(
            distribution_card, style="DashboardEmpty.TLabel"
        )
        self.dashboard_empty_label.grid(row=2, column=0, sticky="w", pady=(6, 0))
        self.dashboard_empty_label.grid_remove()

        self._economic_card = tk.Frame(
            self,
            background=PALETTE["surface"],
            highlightbackground=PALETTE["border"],
            highlightthickness=1,
            bd=0,
            padx=16,
            pady=14,
        )
        self._economic_card.grid(row=2, column=0, columnspan=2, sticky="nsew", pady=(12, 0))
        self._economic_card.columnconfigure(1, weight=1)
        self._economic_card.grid_remove()

        self._priced_label = ttk.Label(self._economic_card, style="DashboardCategory.TLabel")
        self._priced_label.grid(row=0, column=0, sticky="w", padx=(0, 12), pady=(0, 2))
        self._priced_value = ttk.Label(self._economic_card, style="DashboardCount.TLabel", text="0")
        self._priced_value.grid(row=0, column=1, sticky="e", pady=(0, 2))
        self._unpriced_label = ttk.Label(self._economic_card, style="DashboardCategory.TLabel")
        self._unpriced_label.grid(row=1, column=0, sticky="w", padx=(0, 12), pady=(0, 6))
        self._unpriced_value = ttk.Label(self._economic_card, style="DashboardCount.TLabel", text="0")
        self._unpriced_value.grid(row=1, column=1, sticky="e", pady=(0, 6))

        self._subtotals_title_label = ttk.Label(self._economic_card, style="DashboardLabel.TLabel")
        self._subtotals_title_label.grid(row=2, column=0, columnspan=2, sticky="w", pady=(2, 4))
        self._subtotals_frame = ttk.Frame(self._economic_card, style="DashboardCard.TFrame")
        self._subtotals_frame.grid(row=3, column=0, columnspan=2, sticky="ew")
        self._subtotals_frame.columnconfigure(1, weight=1)
        self._no_amounts_label = ttk.Label(self._economic_card, style="DashboardEmpty.TLabel")
        self._no_amounts_label.grid(row=4, column=0, columnspan=2, sticky="w", pady=(2, 0))
        self._no_amounts_label.grid_remove()
        self._disclaimer_label = ttk.Label(
            self._economic_card, style="DashboardEmpty.TLabel", wraplength=760, justify="left"
        )
        self._disclaimer_label.grid(row=5, column=0, columnspan=2, sticky="w", pady=(6, 0))
        self._disclaimer_label.grid_remove()

        self.apply_translations()

    def set_translator(self, translator: Translator) -> None:
        self.translator = translator
        self.apply_translations()

    def apply_translations(self) -> None:
        if self.dashboard_title_label is not None:
            self.dashboard_title_label.configure(text=self.translator.t("dashboard.title"))
        if self.dashboard_total_label is not None:
            self.dashboard_total_label.configure(text=self.translator.t("dashboard.total_label"))
        if self.dashboard_distribution_label is not None:
            self.dashboard_distribution_label.configure(
                text=self.translator.t("dashboard.category_distribution")
            )
        if self.dashboard_empty_label is not None:
            self.dashboard_empty_label.configure(text=self.translator.t("dashboard.empty_inventory"))
        if self._priced_label is not None:
            self._priced_label.configure(text=self.translator.t("dashboard.priced_components_label"))
        if self._unpriced_label is not None:
            self._unpriced_label.configure(text=self.translator.t("dashboard.unpriced_components_label"))
        if self._subtotals_title_label is not None:
            self._subtotals_title_label.configure(text=self.translator.t("dashboard.registered_subtotals_title"))
        if self._no_amounts_label is not None:
            self._no_amounts_label.configure(text=self.translator.t("dashboard.no_registered_amounts"))
        if self._disclaimer_label is not None:
            self._disclaimer_label.configure(text=self.translator.t("dashboard.subtotals_disclaimer"))
        if self._summary is not None:
            self.update_summary(self._summary)

    def update_summary(self, summary: Any) -> None:
        self._summary = summary
        total_count = getattr(summary, "total_count", 0)
        if self.dashboard_total_value is not None:
            self.dashboard_total_value.configure(text=str(total_count))
        if self._distribution_frame is None or self.dashboard_empty_label is None:
            return
        for child in self._distribution_frame.winfo_children():
            child.destroy()
        self.dashboard_empty_label.grid_remove()
        if total_count == 0:
            self.dashboard_empty_label.grid(row=2, column=0, sticky="w", pady=(6, 0))
            if self._economic_card is not None:
                self._economic_card.grid_remove()
            return
        category_counts = getattr(summary, "category_counts", {}) or {}
        visible_rows = [
            (category, count)
            for category, count in category_counts.items()
            if count > 0
        ]
        if not visible_rows:
            self.dashboard_empty_label.grid(row=2, column=0, sticky="w", pady=(6, 0))
        else:
            for row_index, (category, count) in enumerate(visible_rows):
                ttk.Label(
                    self._distribution_frame,
                    text=self.translator.translate_category(category),
                    style="DashboardCategory.TLabel",
                ).grid(row=row_index, column=0, sticky="w", pady=(0, 2), padx=(0, 12))
                ttk.Label(
                    self._distribution_frame,
                    text=str(count),
                    style="DashboardCount.TLabel",
                ).grid(row=row_index, column=1, sticky="e", pady=(0, 2))

        # Economic summary (presentation only; values computed by InventoryService)
        if self._economic_card is None:
            return
        self._economic_card.grid()
        priced = getattr(summary, "priced_component_count", 0) or 0
        unpriced = getattr(summary, "unpriced_component_count", total_count - priced) or 0
        if self._priced_value is not None:
            self._priced_value.configure(text=str(priced))
        if self._unpriced_value is not None:
            self._unpriced_value.configure(text=str(unpriced))
        if self._subtotals_frame is not None:
            for child in self._subtotals_frame.winfo_children():
                child.destroy()
        subtotals = getattr(summary, "price_subtotals_by_currency", {}) or {}
        if self._no_amounts_label is not None:
            self._no_amounts_label.grid_remove()
        if self._disclaimer_label is not None:
            self._disclaimer_label.grid_remove()
        if priced == 0 or not subtotals:
            if self._subtotals_title_label is not None:
                self._subtotals_title_label.grid()
            if self._no_amounts_label is not None:
                self._no_amounts_label.grid()
            # no fictional subtotals; disclaimer not needed when none registered
            return
        if self._subtotals_title_label is not None:
            self._subtotals_title_label.grid()
        for row_index, (currency, amount) in enumerate(subtotals.items()):
            if self._subtotals_frame is None:
                break
            ttk.Label(
                self._subtotals_frame,
                text=f"{amount} {currency}",
                style="DashboardCategory.TLabel",
            ).grid(row=row_index, column=0, sticky="w", pady=(0, 2))
        if unpriced > 0 and self._disclaimer_label is not None:
            self._disclaimer_label.grid()
