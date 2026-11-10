"""Data-quality center view (T17.16). Derived read-only view; no persistence.

Shows the epistemic state of every technical profile, a work queue with
navigation to the profile editor, and per-component detail including the
engine rules that consume each attribute.
"""

from __future__ import annotations

import tkinter as tk
from tkinter import ttk
from typing import Any, Callable

from pc_parts_organizer.data_quality import (
    ABSENT,
    INCONSISTENT_METADATA,
    LOW_CONFIDENCE,
    MISSING_EVIDENCE,
    UNKNOWN,
    UNVERIFIED,
    VERIFIED,
    review_queue,
)
from pc_parts_organizer.localization import Translator
from pc_parts_organizer.ui.theme import PALETTE

TABLE_COLUMNS = ("component", "category", "profile", "attrs", "verified",
                 "pending", "collections", "inconsistent")
QUEUE_COLUMNS = ("component", "attribute", "state", "used_by")


class QualityCenterView(ttk.Frame):
    """Presentation component for the quality center. Receives data; no persistence."""

    def __init__(
        self,
        parent: tk.Misc,
        translator: Translator,
        *,
        on_back: Callable[[], None] | None = None,
        on_edit_profile: Callable[[str], None] | None = None,
    ) -> None:
        super().__init__(parent, style="App.TFrame")
        self.translator = translator
        self._on_back = on_back or (lambda: None)
        self._on_edit_profile = on_edit_profile or (lambda _id: None)
        self._report = None
        self._components_by_id: dict[str, Any] = {}
        self._category_filter: str | None = None
        self._state_filter: str | None = None
        self._search_text = ""
        self._page_size = 50
        self._table_page = 0
        self._queue_page = 0
        self._selected_cid: str | None = None
        self._queue_selected: tuple[str, str] | None = None
        self._build_ui()

    def _t(self, key: str) -> str:
        try:
            return self.translator.t(key)
        except Exception:
            return key

    def set_translator(self, translator: Translator) -> None:
        self.translator = translator
        self.apply_translations()

    def set_data(self, report, components_by_id: dict) -> None:
        self._report = report
        self._components_by_id = dict(components_by_id)
        self._render()

    def clear(self) -> None:
        self._report = None
        self._components_by_id = {}
        self._render()

    # --- ui ---
    def _build_ui(self) -> None:
        self.columnconfigure(0, weight=1)
        self.rowconfigure(3, weight=1)
        header = ttk.Frame(self, style="App.TFrame")
        header.grid(row=0, column=0, sticky="ew", pady=(0, 8))
        header.columnconfigure(0, weight=1)
        self.title_label = ttk.Label(header, style="Title.TLabel")
        self.title_label.grid(row=0, column=0, sticky="w")
        btns = ttk.Frame(header, style="App.TFrame")
        btns.grid(row=0, column=1, sticky="e")
        self.open_editor_button = ttk.Button(btns, style="Secondary.TButton", command=self._handle_open_editor)
        self.open_editor_button.grid(row=0, column=0, padx=(0, 8))
        self.back_button = ttk.Button(btns, style="Secondary.TButton", command=self._on_back)
        self.back_button.grid(row=0, column=1)
        self.summary_label = ttk.Label(self, style="Body.TLabel", wraplength=1100, justify="left")
        self.summary_label.grid(row=1, column=0, sticky="ew", pady=(0, 8))
        filters = ttk.Frame(self, style="App.TFrame")
        filters.grid(row=2, column=0, sticky="ew", pady=(0, 8))
        self.cat_combo = ttk.Combobox(filters, state="readonly", width=20)
        self.cat_combo.grid(row=0, column=0, padx=(0, 8))
        self.cat_combo.bind("<<ComboboxSelected>>", lambda _e: self._apply_filter())
        self.state_combo = ttk.Combobox(filters, state="readonly", width=24)
        self.state_combo.grid(row=0, column=1, padx=(0, 8))
        self.state_combo.bind("<<ComboboxSelected>>", lambda _e: self._apply_filter())
        self.search_var = tk.StringVar()
        self.search_entry = ttk.Entry(filters, textvariable=self.search_var, width=24)
        self.search_entry.grid(row=0, column=2, padx=(0, 8))
        self.search_entry.bind("<KeyRelease>", lambda _e: self._apply_search())
        self.page_size_combo = ttk.Combobox(filters, state="readonly", width=8,
                                            values=["25", "50", "100", "200"])
        self.page_size_combo.grid(row=0, column=3)
        self.page_size_combo.bind("<<ComboboxSelected>>", lambda _e: self._apply_page_size())
        panes = ttk.Panedwindow(self, orient="vertical")
        panes.grid(row=3, column=0, sticky="nsew")
        top = ttk.Frame(panes, style="App.TFrame")
        top.columnconfigure(0, weight=1)
        top.rowconfigure(1, weight=1)
        self.table_label = ttk.Label(top, style="SectionTitle.TLabel")
        self.table_label.grid(row=0, column=0, sticky="w", pady=(0, 4))
        self.tree = ttk.Treeview(top, columns=TABLE_COLUMNS, show="headings", style="Inventory.Treeview")
        self.tree.grid(row=1, column=0, sticky="nsew")
        sb = ttk.Scrollbar(top, orient="vertical", command=self.tree.yview)
        sb.grid(row=1, column=1, sticky="ns")
        self.tree.configure(yscrollcommand=sb.set)
        self.tree.bind("<<TreeviewSelect>>", lambda _e: self._render_detail())
        self.table_nav = ttk.Frame(top, style="App.TFrame")
        self.table_nav.grid(row=2, column=0, columnspan=2, sticky="ew", pady=(4, 0))
        self.table_prev = ttk.Button(self.table_nav, style="Secondary.TButton",
                                     command=lambda: self._goto_page("table", -1))
        self.table_prev.grid(row=0, column=0, padx=(0, 8))
        self.table_page_label = ttk.Label(self.table_nav, style="Body.TLabel")
        self.table_page_label.grid(row=0, column=1, padx=(0, 8))
        self.table_next = ttk.Button(self.table_nav, style="Secondary.TButton",
                                     command=lambda: self._goto_page("table", 1))
        self.table_next.grid(row=0, column=2)
        panes.add(top, weight=3)
        mid = ttk.Frame(panes, style="App.TFrame")
        mid.columnconfigure(0, weight=1)
        mid.rowconfigure(1, weight=1)
        self.queue_label = ttk.Label(mid, style="SectionTitle.TLabel")
        self.queue_label.grid(row=0, column=0, sticky="w", pady=(4, 4))
        self.queue = ttk.Treeview(mid, columns=QUEUE_COLUMNS, show="headings", style="Inventory.Treeview")
        self.queue.grid(row=1, column=0, sticky="nsew")
        sb2 = ttk.Scrollbar(mid, orient="vertical", command=self.queue.yview)
        sb2.grid(row=1, column=1, sticky="ns")
        self.queue.configure(yscrollcommand=sb2.set)
        self.queue.bind("<Double-1>", lambda _e: self._handle_open_editor())
        self.queue_nav = ttk.Frame(mid, style="App.TFrame")
        self.queue_nav.grid(row=2, column=0, columnspan=2, sticky="ew", pady=(4, 0))
        self.queue_prev = ttk.Button(self.queue_nav, style="Secondary.TButton",
                                     command=lambda: self._goto_page("queue", -1))
        self.queue_prev.grid(row=0, column=0, padx=(0, 8))
        self.queue_page_label = ttk.Label(self.queue_nav, style="Body.TLabel")
        self.queue_page_label.grid(row=0, column=1, padx=(0, 8))
        self.queue_next = ttk.Button(self.queue_nav, style="Secondary.TButton",
                                     command=lambda: self._goto_page("queue", 1))
        self.queue_next.grid(row=0, column=2)
        panes.add(mid, weight=2)
        bot = ttk.Frame(panes, style="App.TFrame")
        bot.columnconfigure(0, weight=1)
        bot.rowconfigure(1, weight=1)
        self.detail_label = ttk.Label(bot, style="SectionTitle.TLabel")
        self.detail_label.grid(row=0, column=0, sticky="w", pady=(4, 4))
        self.detail_text = tk.Text(bot, wrap="word", font=("Segoe UI", 10), height=8,
                                   background=PALETTE["surface"], foreground=PALETTE["text"],
                                   relief="flat", highlightthickness=0, state="disabled")
        self.detail_text.grid(row=1, column=0, sticky="nsew")
        panes.add(bot, weight=2)
        self.apply_translations()

    def _comp_label(self, cid: str) -> str:
        c = self._components_by_id.get(cid)
        if c is None:
            return cid
        parts = [str(getattr(c, "manufacturer", "") or "").strip(),
                 str(getattr(c, "model", "") or "").strip()]
        name = " ".join(p for p in parts if p)
        return name or cid

    def _cat_label(self, cat: str) -> str:
        try:
            return self.translator.translate_category(cat)
        except Exception:
            return cat

    def _meta_text(self, group: str, value: str) -> str:
        if not value:
            return "—"
        table = {
            "sources": ("technical_profile.sources", "."),
            "confidence": ("technical_profile.confidence_levels", "."),
            "status": ("technical_profile.status", "_"),
            "completeness": ("technical_profile.completeness", "_"),
        }
        entry = table.get(group)
        if entry is None:
            return value
        prefix, sep = entry
        try:
            out = self.translator.t(f"{prefix}{sep}{value}")
            return out if out != f"{prefix}{sep}{value}" else value
        except Exception:
            return value

    def _state_label(self, state: str) -> str:
        return self._t(f"quality.state_{state}")

    # --- rendering ---
    def apply_translations(self) -> None:
        if getattr(self, "title_label", None) is not None:
            # Preserve active filters, search, page size and pages across languages.
            kept_cat, kept_state = self._category_filter, self._state_filter
            kept_search = self.search_var.get() if getattr(self, "search_var", None) is not None else ""
            kept_size = self._page_size
            self.title_label.configure(text=self._t("quality.title"))
            self.back_button.configure(text=self._t("quality.back"))
            self.open_editor_button.configure(text=self._t("quality.open_editor"))
            self.table_label.configure(text=self._t("quality.table_title"))
            self.queue_label.configure(text=self._t("quality.queue_title"))
            self.detail_label.configure(text=self._t("quality.detail_title"))
            for col in TABLE_COLUMNS:
                self.tree.heading(col, text=self._t(f"quality.col_{col}"))
            for col in QUEUE_COLUMNS:
                self.queue.heading(col, text=self._t(f"quality.queue_{col}"))
            cats = [self._t("quality.filter_all")]
            try:
                from pc_parts_organizer.models import CATEGORIES
                cats += [self._cat_label(c) for c in CATEGORIES]
            except Exception:
                pass
            self.cat_combo.configure(values=cats)
            self.cat_combo.set(cats[0])
            states = [self._t("quality.filter_all")] + [self._state_label(s) for s in
                      (ABSENT, UNKNOWN, UNVERIFIED, LOW_CONFIDENCE, MISSING_EVIDENCE, INCONSISTENT_METADATA, VERIFIED)]
            self.state_combo.configure(values=states)
            if kept_state in (ABSENT, UNKNOWN, UNVERIFIED, LOW_CONFIDENCE,
                              MISSING_EVIDENCE, INCONSISTENT_METADATA, VERIFIED):
                self.state_combo.set(self._state_label(kept_state))
                self._state_filter = kept_state
            else:
                self.state_combo.set(states[0])
                self._state_filter = None
            if kept_cat:
                self.cat_combo.set(self._cat_label(kept_cat))
                self._category_filter = kept_cat
            else:
                self.cat_combo.set(cats[0])
                self._category_filter = None
            self.search_var.set(kept_search)
            self._search_text = kept_search.strip().casefold()
            self.page_size_combo.configure(values=["25", "50", "100", "200"])
            self.page_size_combo.set(str(kept_size if kept_size in (25, 50, 100, 200) else 50))
            self._page_size = int(self.page_size_combo.get())
            self.table_prev.configure(text=self._t("quality.prev"))
            self.table_next.configure(text=self._t("quality.next"))
            self.queue_prev.configure(text=self._t("quality.prev"))
            self.queue_next.configure(text=self._t("quality.next"))
        self._render()

    def _apply_filter(self) -> None:
        all_label = self._t("quality.filter_all")
        cat_disp = self.cat_combo.get()
        self._category_filter = None
        if cat_disp != all_label:
            try:
                from pc_parts_organizer.models import CATEGORIES
                for c in CATEGORIES:
                    if self._cat_label(c) == cat_disp:
                        self._category_filter = c
                        break
            except Exception:
                pass
        st_disp = self.state_combo.get()
        states = [ABSENT, UNKNOWN, UNVERIFIED, LOW_CONFIDENCE, MISSING_EVIDENCE, INCONSISTENT_METADATA, VERIFIED]
        self._state_filter = None
        if st_disp != all_label:
            for s in states:
                if self._state_label(s) == st_disp:
                    self._state_filter = s
                    break
        self._render()

    def _apply_search(self) -> None:
        self._search_text = (self.search_var.get() if self.search_var is not None else "").strip().casefold()
        self._table_page = 0
        self._queue_page = 0
        self._render()

    def _apply_page_size(self) -> None:
        try:
            size = int(self.page_size_combo.get())
        except (ValueError, TypeError):
            size = 50
        if size not in (25, 50, 100, 200):
            size = 50
            self.page_size_combo.set("50")
        self._page_size = size
        self._table_page = 0
        self._queue_page = 0
        self._render()

    def _goto_page(self, which: str, delta: int) -> None:
        if which == "table":
            self._table_page = max(0, self._table_page + delta)
        else:
            self._queue_page = max(0, self._queue_page + delta)
        self._render()

    def _page_label(self, page: int, total: int) -> str:
        pages = max(1, (total + self._page_size - 1) // self._page_size)
        page = min(page, pages - 1)
        return self._t("quality.page_of").format(page=page + 1, pages=pages, total=total)

    def _matches_search(self, cid: str) -> bool:
        if not self._search_text:
            return True
        return self._search_text in self._comp_label(cid).casefold()

    def _table_rows(self, by_comp: dict) -> list:
        rows = []
        for cid in sorted(by_comp, key=lambda c: self._comp_label(c).casefold()):
            es = by_comp[cid]
            if es:
                cat = es[0].category
            else:
                comp = self._components_by_id.get(cid)
                cat = getattr(comp, "category", "") if comp is not None else ""
            if self._category_filter and cat != self._category_filter:
                continue
            if self._state_filter and not any(x.status == self._state_filter for x in es):
                continue
            if not self._matches_search(cid):
                continue
            rows.append((cid, es, cat))
        return rows

    def _queue_rows(self, rep) -> list:
        rows = []
        for e in review_queue(rep):
            comp = self._components_by_id.get(e.component_id)
            if self._category_filter and (comp is None or getattr(comp, "category", "") != self._category_filter):
                continue
            if self._state_filter and e.status != self._state_filter:
                continue
            if not self._matches_search(e.component_id):
                continue
            rows.append(e)
        return rows

    def _render(self) -> None:
        if getattr(self, "tree", None) is None:
            return
        # Capture selections BEFORE clearing so they can be restored.
        self._queue_selected = None
        qsel = self.queue.selection()
        if qsel:
            qtags = self.queue.item(qsel[0], "tags")
            if qtags and len(qtags) >= 2:
                self._queue_selected = (str(qtags[0]), str(qtags[1]))
        for item in self.tree.get_children():
            self.tree.delete(item)
        for item in self.queue.get_children():
            self.queue.delete(item)
        if self._report is None:
            if self.summary_label is not None:
                self.summary_label.configure(text="")
            return
        rep = self._report
        parts = [
            f"{self._t('quality.summary_components')}: {rep.components_total}",
            f"{self._t('quality.summary_without_profile')}: {rep.components_without_profile}",
            f"{self._t('quality.summary_verified')}: {rep.count(VERIFIED)}",
            f"{self._t('quality.summary_unverified')}: {rep.count(UNVERIFIED)}",
            f"{self._t('quality.summary_low_confidence')}: {rep.count(LOW_CONFIDENCE)}",
            f"{self._t('quality.summary_missing_evidence')}: {rep.count(MISSING_EVIDENCE)}",
            f"{self._t('quality.summary_inconsistent')}: {rep.count(INCONSISTENT_METADATA)}",
            f"{self._t('quality.summary_absent')}: {rep.count(ABSENT)}",
            f"{self._t('quality.summary_unknown')}: {rep.count(UNKNOWN)}",
        ]
        self.summary_label.configure(text=" | ".join(parts))
        by_comp: dict[str, list] = {}
        for e in rep.entries:
            by_comp.setdefault(e.component_id, []).append(e)
        # Components without any registry entry (unsupported category) still
        # get a row so the table adds up to components_total.
        for cid in self._components_by_id:
            by_comp.setdefault(cid, [])
        rows = self._table_rows(by_comp)
        pages = max(1, (len(rows) + self._page_size - 1) // self._page_size)
        self._table_page = min(self._table_page, pages - 1)
        page_rows = rows[self._table_page * self._page_size:(self._table_page + 1) * self._page_size]
        for cid, es, cat in page_rows:
            has_profile = any(x.status != ABSENT for x in es)
            n_verified = sum(1 for x in es if x.status == VERIFIED)
            pending = sum(1 for x in es if x.status in (UNVERIFIED, LOW_CONFIDENCE, MISSING_EVIDENCE, UNKNOWN, INCONSISTENT_METADATA))
            colls = sorted({f"{x.key}:{x.collection_completeness}" for x in es
                            if x.collection_completeness in ("partial", "complete")})
            incons = sum(1 for x in es if x.status == INCONSISTENT_METADATA)
            self.tree.insert("", "end", values=(
                self._comp_label(cid), self._cat_label(cat),
                self._t("quality.yes") if has_profile else self._t("quality.no"),
                len([x for x in es if x.status != ABSENT]), n_verified, pending,
                ", ".join(colls) if colls else "—", incons), tags=(cid,))
        # restore selection when still present on this page
        if self._selected_cid:
            for item in self.tree.get_children():
                tags = self.tree.item(item, "tags")
                if tags and str(tags[0]) == self._selected_cid:
                    self.tree.selection_set(item)
                    self.tree.see(item)
                    break
        self.table_page_label.configure(text=self._page_label(self._table_page, len(rows)))
        self.table_prev.configure(state="normal" if self._table_page > 0 else "disabled")
        self.table_next.configure(state="normal" if self._table_page < pages - 1 else "disabled")
        qrows = self._queue_rows(rep)
        qpages = max(1, (len(qrows) + self._page_size - 1) // self._page_size)
        self._queue_page = min(self._queue_page, qpages - 1)
        for e in qrows[self._queue_page * self._page_size:(self._queue_page + 1) * self._page_size]:
            used = ", ".join(e.consumed_by) if e.consumed_by else self._t("quality.unused")
            self.queue.insert("", "end", values=(
                self._comp_label(e.component_id), e.key, self._state_label(e.status), used),
                tags=(e.component_id, e.key))
        self.queue_page_label.configure(text=self._page_label(self._queue_page, len(qrows)))
        self.queue_prev.configure(state="normal" if self._queue_page > 0 else "disabled")
        self.queue_next.configure(state="normal" if self._queue_page < qpages - 1 else "disabled")
        if self._queue_selected is not None:
            for item in self.queue.get_children():
                tags = self.queue.item(item, "tags")
                if tags and len(tags) >= 2 and (str(tags[0]), str(tags[1])) == self._queue_selected:
                    self.queue.selection_set(item)
                    self.queue.see(item)
                    break
        self._render_detail()

    def _selected_component_id(self) -> str | None:
        sel = self.tree.selection()
        if sel:
            tags = self.tree.item(sel[0], "tags")
            if tags:
                self._selected_cid = str(tags[0])
                return self._selected_cid
            return None
        # No live selection: keep the stored one only while it is visible.
        if self._selected_cid and any(
                str(self.tree.item(i, "tags")[0]) == self._selected_cid
                for i in self.tree.get_children() if self.tree.item(i, "tags")):
            return self._selected_cid
        self._selected_cid = None
        return None

    def _render_detail(self) -> None:
        if self.detail_text is None:
            return
        self.detail_text.configure(state="normal")
        self.detail_text.delete("1.0", "end")
        if self._report is not None:
            cid = self._selected_component_id()
            if cid:
                lines = []
                for e in [x for x in self._report.entries if x.component_id == cid]:
                    if e.status == ABSENT:
                        continue
                    lines.append(f"{e.key} [{self._state_label(e.status)}]")
                    meta = []
                    if e.unit:
                        meta.append(f"{self._t('quality.meta_unit')}: {e.unit}")
                    meta.append(f"{self._t('quality.meta_source')}: {self._meta_text('sources', e.source)}")
                    meta.append(f"{self._t('quality.meta_confidence')}: {self._meta_text('confidence', e.confidence)}")
                    meta.append(f"{self._t('quality.meta_verification')}: {self._meta_text('status', e.verification_status)}")
                    meta.append(f"{self._t('quality.meta_evidence')}: {e.evidence_ref or '—'}")
                    meta.append(f"{self._t('quality.meta_date')}: {e.verified_at or '—'}")
                    if e.collection_completeness != "unknown":
                        meta.append(f"{self._t('quality.meta_completeness')}: {self._meta_text('completeness', e.collection_completeness)}"
                                    + (f" ({e.completeness_scope})" if e.completeness_scope else ""))
                    lines.append("  " + " | ".join(meta))
                    if e.consumed_by:
                        lines.append("  " + self._t("quality.used_by") + ": " + ", ".join(e.consumed_by))
                    else:
                        lines.append("  " + self._t("quality.unused"))
                self.detail_text.insert("1.0", "\n".join(lines) + ("\n" if lines else ""))
        self.detail_text.configure(state="disabled")

    def _handle_open_editor(self) -> None:
        cid = None
        qsel = self.queue.selection()
        if qsel:
            tags = self.queue.item(qsel[0], "tags")
            if tags:
                cid = str(tags[0])
        if cid is None:
            cid = self._selected_component_id()
        if cid:
            self._on_edit_profile(cid)
