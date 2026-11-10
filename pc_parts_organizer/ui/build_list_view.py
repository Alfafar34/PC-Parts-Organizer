"""Builds/equipos list view component."""

from __future__ import annotations

import tkinter as tk
from tkinter import ttk
from typing import Any, Callable

from pc_parts_organizer.localization import Translator
from pc_parts_organizer.ui.theme import PALETTE

BUILD_COLUMNS = ("kind", "name", "component_count")


class BuildListView(ttk.Frame):
    """Presentation component for builds table and actions. No persistence."""

    def __init__(
        self,
        parent: tk.Misc,
        translator: Translator,
        *,
        on_add: Callable[[], None] | None = None,
        on_edit: Callable[[str], None] | None = None,
        on_view_details: Callable[[str], None] | None = None,
        on_delete: Callable[[str], None] | None = None,
        on_compare: Callable[[], None] | None = None,
    ) -> None:
        super().__init__(parent, style="App.TFrame")
        self.translator = translator
        self._on_add = on_add or (lambda: None)
        self._on_edit = on_edit or (lambda _id: None)
        self._on_view_details = on_view_details or (lambda _id: None)
        self._on_delete = on_delete or (lambda _id: None)
        self._on_compare = on_compare or (lambda: None)
        self._builds: list[Any] = []
        self._item_to_id: dict[str, str] = {}
        self._id_to_item: dict[str, str] = {}

        self.tree: ttk.Treeview | None = None
        self.add_button: ttk.Button | None = None
        self.edit_button: ttk.Button | None = None
        self.view_button: ttk.Button | None = None
        self.delete_button: ttk.Button | None = None
        self.compare_button: ttk.Button | None = None
        self.count_label: ttk.Label | None = None
        self.empty_label: ttk.Label | None = None
        self._build_ui()

    def _build_ui(self) -> None:
        self.columnconfigure(0, weight=1)
        self.rowconfigure(1, weight=1)

        toolbar = ttk.Frame(self, style="App.TFrame")
        toolbar.grid(row=0, column=0, sticky="ew", pady=(0, 8))
        toolbar.columnconfigure(1, weight=1)
        self.add_button = ttk.Button(toolbar, style="Primary.TButton", command=self._on_add)
        self.add_button.grid(row=0, column=0, sticky="w")
        self.count_label = ttk.Label(toolbar, style="Body.TLabel")
        self.count_label.grid(row=0, column=1, sticky="w", padx=(12, 0))

        table_container = tk.Frame(
            self,
            background=PALETTE["surface"],
            highlightbackground=PALETTE["border"],
            highlightthickness=1,
            bd=0,
        )
        table_container.grid(row=1, column=0, sticky="nsew")
        table_container.columnconfigure(0, weight=1)
        table_container.rowconfigure(0, weight=1)

        self.tree = ttk.Treeview(
            table_container,
            columns=BUILD_COLUMNS,
            show="headings",
            selectmode="browse",
            style="Inventory.Treeview",
        )
        self.tree.grid(row=0, column=0, sticky="nsew")
        scrollbar = ttk.Scrollbar(table_container, orient="vertical", command=self.tree.yview)
        scrollbar.grid(row=0, column=1, sticky="ns")
        self.tree.configure(yscrollcommand=scrollbar.set)
        self.tree.bind("<<TreeviewSelect>>", lambda _e: self._update_actions())
        self.tree.bind("<Double-1>", self._on_double_click)

        self.empty_label = ttk.Label(
            table_container,
            style="Placeholder.TLabel",
            background=PALETTE["surface"],
            anchor="center",
            justify="center",
        )
        self.empty_label.place(relx=0.5, rely=0.5, anchor="center")

        actions = ttk.Frame(self, style="App.TFrame")
        actions.grid(row=2, column=0, sticky="e", pady=(8, 0))
        self.view_button = ttk.Button(actions, style="Secondary.TButton", command=self._handle_view)
        self.view_button.grid(row=0, column=0, padx=(0, 8))
        self.edit_button = ttk.Button(actions, style="Secondary.TButton", command=self._handle_edit)
        self.edit_button.grid(row=0, column=1, padx=(0, 8))
        self.delete_button = ttk.Button(actions, style="Secondary.TButton", command=self._handle_delete)
        self.delete_button.grid(row=0, column=2, padx=(0, 8))
        self.compare_button = ttk.Button(actions, style="Secondary.TButton", command=self._on_compare)
        self.compare_button.grid(row=0, column=3)

        self.apply_translations()
        self._update_actions()

    def set_translator(self, translator: Translator) -> None:
        self.translator = translator
        self.apply_translations()

    def apply_translations(self) -> None:
        if self.tree is not None:
            self.tree.heading("kind", text=self.translator.t("builds.kind"))
            self.tree.heading("name", text=self.translator.t("builds.name"))
            self.tree.heading("component_count", text=self.translator.t("builds.components"))
            self.tree.column("kind", width=120, minwidth=90, anchor="w")
            self.tree.column("name", width=320, minwidth=160, anchor="w")
            self.tree.column("component_count", width=120, minwidth=90, anchor="e")
        if self.add_button is not None:
            self.add_button.configure(text=self.translator.t("builds.add_build"))
        if self.view_button is not None:
            self.view_button.configure(text=self.translator.t("builds.view_details"))
        if self.edit_button is not None:
            self.edit_button.configure(text=self.translator.t("builds.edit_build"))
        if self.delete_button is not None:
            self.delete_button.configure(text=self.translator.t("builds.delete_build"))
        if self.compare_button is not None:
            self.compare_button.configure(text=self.translator.t("builds.compare_builds"))
        self._refresh_rows()

    def set_builds(self, builds: list[Any]) -> None:
        self._builds = list(builds)
        self._refresh_rows()

    def _kind_label(self, kind: str) -> str:
        key = "builds.kind_planned" if kind == "planned" else "builds.kind_current"
        try:
            return self.translator.t(key)
        except Exception:
            return kind

    def _count_label(self, n: int) -> str:
        key = "builds.component_count_one" if n == 1 else "builds.component_count_many"
        try:
            return self.translator.t(key).format(count=n)
        except Exception:
            return str(n)

    def _refresh_rows(self) -> None:
        if self.tree is None:
            return
        selected_id = self.get_selected_build_id()
        for item in self.tree.get_children():
            self.tree.delete(item)
        self._item_to_id.clear()
        self._id_to_item.clear()
        # stable order by kind (current first), then name casefold
        ordered = sorted(
            self._builds,
            key=lambda b: (0 if getattr(b, "kind", "current") == "current" else 1, str(getattr(b, "name", "")).casefold()),
        )
        for build in ordered:
            bid = getattr(build, "id", "")
            count = len(getattr(build, "component_ids", []) or [])
            item = self.tree.insert(
                "",
                "end",
                values=(self._kind_label(getattr(build, "kind", "current")), getattr(build, "name", ""), self._count_label(count)),
            )
            self._item_to_id[item] = bid
            self._id_to_item[bid] = item
        if selected_id and selected_id in self._id_to_item:
            self.tree.selection_set(self._id_to_item[selected_id])
            self.tree.focus(self._id_to_item[selected_id])
        total = len(self._builds)
        if self.count_label is not None:
            key = "builds.component_count_one" if total == 1 else "builds.component_count_many"
            # reuse count key? better a specific one; fallback to simple
            try:
                self.count_label.configure(text=self.translator.t("builds.title") + f": {total}")
            except Exception:
                self.count_label.configure(text=str(total))
        if self.empty_label is not None:
            if total == 0:
                self.empty_label.configure(text=f"{self.translator.t('builds.empty')}\n{self.translator.t('builds.empty_hint')}")
                self.empty_label.place(relx=0.5, rely=0.5, anchor="center")
                self.empty_label.lift()
            else:
                self.empty_label.place_forget()
        self._update_actions()

    def get_selected_build_id(self) -> str | None:
        if self.tree is None:
            return None
        sel = self.tree.selection()
        if not sel:
            return None
        return self._item_to_id.get(sel[0])

    def clear_selection(self) -> None:
        if self.tree is not None:
            self.tree.selection_remove(self.tree.selection())
        self._update_actions()

    def _update_actions(self) -> None:
        has = self.get_selected_build_id() is not None
        state = "normal" if has else "disabled"
        for btn in (self.view_button, self.edit_button, self.delete_button):
            if btn is not None:
                btn.configure(state=state)
        if self.compare_button is not None:
            self.compare_button.configure(state="normal" if len(self._builds) >= 2 else "disabled")

    def _on_double_click(self, _event: object) -> None:
        bid = self.get_selected_build_id()
        if bid:
            self._on_view_details(bid)

    def _handle_view(self) -> None:
        bid = self.get_selected_build_id()
        if bid:
            self._on_view_details(bid)

    def _handle_edit(self) -> None:
        bid = self.get_selected_build_id()
        if bid:
            self._on_edit(bid)

    def _handle_delete(self) -> None:
        bid = self.get_selected_build_id()
        if bid:
            self._on_delete(bid)
