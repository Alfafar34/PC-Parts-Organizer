"""Modal form for adding or editing builds/equipos."""

from __future__ import annotations

import tkinter as tk
from dataclasses import dataclass
from tkinter import messagebox, ttk
from typing import Any

from pc_parts_organizer.localization import Translator
from pc_parts_organizer.ui.theme import PALETTE


@dataclass
class BuildFormData:
    name: str
    notes: str
    kind: str
    component_ids: list[str]


class BuildForm:
    """Toplevel modal form for build input (add or edit)."""

    def __init__(
        self,
        parent: tk.Misc,
        translator: Translator,
        *,
        build: Any | None = None,
        available_components: list[Any] | None = None,
        associated_components: list[Any] | None = None,
        all_components_by_id: dict[str, Any] | None = None,
    ) -> None:
        self.translator = translator
        self.build_id = getattr(build, "id", None) if build is not None else None
        self._editing = build is not None
        self.result: BuildFormData | None = None
        self._all = dict(all_components_by_id or {})
        self._available = {getattr(c, "id"): c for c in (available_components or [])}
        self._associated_ids: list[str] = list(getattr(build, "component_ids", []) or []) if build is not None else []
        # ensure associated objects are known
        for c in (associated_components or []):
            self._all[getattr(c, "id")] = c

        self.window = tk.Toplevel(parent)
        title = self.translator.t("builds.edit_build") if self._editing else self.translator.t("builds.add_build")
        self.window.title(title)
        self.window.transient(parent)
        self.window.configure(background=PALETTE["surface"])
        self.window.resizable(True, True)
        self.window.geometry("760x700")
        self.window.minsize(680, 560)
        self.window.protocol("WM_DELETE_WINDOW", self._on_cancel)
        self.window.bind("<Escape>", lambda _e: self._on_cancel())

        self._name_entry: ttk.Entry | None = None
        self._kind_combo: ttk.Combobox | None = None
        self._notes_text: tk.Text | None = None
        self._avail_list: tk.Listbox | None = None
        self._assoc_list: tk.Listbox | None = None
        self._avail_ids: list[str] = []
        self._assoc_display_ids: list[str] = []
        self._build_ui(build)
        self.window.grab_set()
        if self._name_entry is not None:
            self._name_entry.focus_set()

    def _comp_label(self, cid: str) -> str:
        c = self._all.get(cid) or self._available.get(cid)
        if c is None:
            return cid
        cat = getattr(c, "category", "")
        try:
            cat_l = self.translator.translate_category(cat)
        except Exception:
            cat_l = cat
        return f"[{cat_l}] {getattr(c, 'manufacturer', '')} — {getattr(c, 'model', '')}"

    def _sorted_ids(self, ids: list[str]) -> list[str]:
        def key(cid: str):
            c = self._all.get(cid) or self._available.get(cid)
            if c is None:
                return ("", "", cid)
            return (str(getattr(c, "category", "")).casefold(), str(getattr(c, "manufacturer", "")).casefold(), str(getattr(c, "model", "")).casefold(), cid)
        return sorted(ids, key=key)

    def _build_ui(self, build: Any | None) -> None:
        frame = ttk.Frame(self.window, style="Form.TFrame", padding=16)
        frame.grid(row=0, column=0, sticky="nsew")
        self.window.columnconfigure(0, weight=1)
        self.window.rowconfigure(0, weight=1)
        frame.columnconfigure(1, weight=1)
        frame.rowconfigure(4, weight=1)

        ttk.Label(frame, text=self.translator.t("builds.name"), style="Form.TLabel").grid(row=0, column=0, sticky="w", pady=(0, 6))
        self._name_entry = ttk.Entry(frame, style="Form.TEntry")
        self._name_entry.grid(row=0, column=1, sticky="ew", pady=(0, 6))

        ttk.Label(frame, text=self.translator.t("builds.kind_label"), style="Form.TLabel").grid(row=1, column=0, sticky="w", pady=(0, 6))
        kind_map = {self.translator.t("builds.kind_current"): "current", self.translator.t("builds.kind_planned"): "planned"}
        self._kind_combo = ttk.Combobox(frame, values=list(kind_map.keys()), state="readonly", style="Form.TCombobox")
        self._kind_combo.grid(row=1, column=1, sticky="ew", pady=(0, 6))
        default_kind = getattr(build, "kind", "current") if build is not None else "current"
        self._kind_combo.set(self.translator.t("builds.kind_planned" if default_kind == "planned" else "builds.kind_current"))
        self._kind_map = kind_map

        ttk.Label(frame, text=self.translator.t("builds.notes_optional"), style="Form.TLabel").grid(row=2, column=0, sticky="nw", pady=(0, 6))
        self._notes_text = tk.Text(frame, height=4, wrap="word", font=("Segoe UI", 10), background=PALETTE["surface"], foreground=PALETTE["text"], highlightbackground=PALETTE["border"], highlightthickness=1, bd=0, padx=6, pady=4)
        self._notes_text.grid(row=2, column=1, sticky="ew", pady=(0, 6))

        ttk.Label(frame, text=self.translator.t("builds.select_component_hint"), style="SurfaceBody.TLabel").grid(row=3, column=0, columnspan=2, sticky="w", pady=(4, 6))

        selector = ttk.Frame(frame, style="Form.TFrame")
        selector.grid(row=4, column=0, columnspan=2, sticky="nsew")
        selector.columnconfigure(0, weight=1)
        selector.columnconfigure(2, weight=1)
        selector.rowconfigure(1, weight=1)

        ttk.Label(selector, text=self.translator.t("builds.available_components"), style="Form.TLabel").grid(row=0, column=0, sticky="w")
        ttk.Label(selector, text=self.translator.t("builds.associated_components"), style="Form.TLabel").grid(row=0, column=2, sticky="w")

        avail_frame = tk.Frame(selector, background=PALETTE["surface"], highlightbackground=PALETTE["border"], highlightthickness=1, bd=0)
        avail_frame.grid(row=1, column=0, sticky="nsew", pady=(4, 0))
        avail_frame.columnconfigure(0, weight=1)
        avail_frame.rowconfigure(0, weight=1)
        self._avail_list = tk.Listbox(avail_frame, selectmode="extended", exportselection=False, font=("Segoe UI", 10), activestyle="none", bd=0, highlightthickness=0)
        self._avail_list.grid(row=0, column=0, sticky="nsew")
        sb1 = ttk.Scrollbar(avail_frame, orient="vertical", command=self._avail_list.yview)
        sb1.grid(row=0, column=1, sticky="ns")
        self._avail_list.configure(yscrollcommand=sb1.set)

        mid = ttk.Frame(selector, style="Form.TFrame")
        mid.grid(row=1, column=1, padx=8)
        ttk.Button(mid, text=self.translator.t("builds.add_selected"), style="Secondary.TButton", command=self._add_selected).grid(row=0, column=0, pady=(40, 6))
        ttk.Button(mid, text=self.translator.t("builds.remove_selected"), style="Secondary.TButton", command=self._remove_selected).grid(row=1, column=0)

        assoc_frame = tk.Frame(selector, background=PALETTE["surface"], highlightbackground=PALETTE["border"], highlightthickness=1, bd=0)
        assoc_frame.grid(row=1, column=2, sticky="nsew", pady=(4, 0))
        assoc_frame.columnconfigure(0, weight=1)
        assoc_frame.rowconfigure(0, weight=1)
        self._assoc_list = tk.Listbox(assoc_frame, selectmode="extended", exportselection=False, font=("Segoe UI", 10), activestyle="none", bd=0, highlightthickness=0)
        self._assoc_list.grid(row=0, column=0, sticky="nsew")
        sb2 = ttk.Scrollbar(assoc_frame, orient="vertical", command=self._assoc_list.yview)
        sb2.grid(row=0, column=1, sticky="ns")
        self._assoc_list.configure(yscrollcommand=sb2.set)

        actions = ttk.Frame(frame, style="Form.TFrame")
        actions.grid(row=5, column=0, columnspan=2, sticky="e", pady=(12, 0))
        ttk.Button(actions, text=self.translator.t("builds.cancel"), style="Secondary.TButton", command=self._on_cancel).grid(row=0, column=0, padx=(0, 8))
        ttk.Button(actions, text=self.translator.t("builds.save"), style="Primary.TButton", command=self._on_submit).grid(row=0, column=1)

        if build is not None:
            self._name_entry.insert(0, getattr(build, "name", ""))
            notes = getattr(build, "notes", "") or ""
            if notes:
                self._notes_text.insert("1.0", notes)
        self._refresh_lists()

    def _refresh_lists(self) -> None:
        if self._avail_list is None or self._assoc_list is None:
            return
        assoc_set = set(self._associated_ids)
        self._avail_ids = self._sorted_ids([cid for cid in self._available.keys() if cid not in assoc_set])
        self._assoc_display_ids = self._sorted_ids(list(self._associated_ids))
        self._avail_list.delete(0, "end")
        for cid in self._avail_ids:
            self._avail_list.insert("end", self._comp_label(cid))
        self._assoc_list.delete(0, "end")
        for cid in self._assoc_display_ids:
            self._assoc_list.insert("end", self._comp_label(cid))

    def _add_selected(self) -> None:
        if self._avail_list is None:
            return
        for idx in reversed(self._avail_list.curselection()):
            cid = self._avail_ids[idx]
            if cid not in self._associated_ids:
                self._associated_ids.append(cid)
        self._refresh_lists()

    def _remove_selected(self) -> None:
        if self._assoc_list is None:
            return
        to_remove = {self._assoc_display_ids[idx] for idx in self._assoc_list.curselection()}
        self._associated_ids = [cid for cid in self._associated_ids if cid not in to_remove]
        self._refresh_lists()

    def _on_submit(self) -> None:
        if self._name_entry is None or self._kind_combo is None or self._notes_text is None:
            return
        name = self._name_entry.get().strip()
        if not name:
            messagebox.showerror(self.translator.t("builds.validation_title"), self.translator.t("builds.name_required"), parent=self.window)
            return
        kind = self._kind_map.get(self._kind_combo.get().strip(), "current")
        notes = self._notes_text.get("1.0", "end-1c").strip()
        # preserve stable order as shown? associated_ids kept in add order; service/model accept list
        self.result = BuildFormData(name=name, notes=notes, kind=kind, component_ids=list(self._associated_ids))
        self.window.destroy()

    def _on_cancel(self) -> None:
        self.result = None
        self.window.destroy()
