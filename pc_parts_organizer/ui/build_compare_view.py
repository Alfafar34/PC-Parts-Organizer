"""Build comparison view (T17.14). Text-based; receives data, no persistence."""

from __future__ import annotations

import tkinter as tk
from tkinter import ttk
from typing import Any, Callable

from pc_parts_organizer.build_compare import (
    ADDED,
    REMOVED,
    REPLACED,
    UNKNOWN,
)
from pc_parts_organizer.localization import Translator
from pc_parts_organizer.ui.build_detail_view import _fmt_param
from pc_parts_organizer.ui.theme import PALETTE


def _res_label(t, result: str) -> str:
    try:
        return str(t(f"compatibility.results.{result}"))
    except Exception:
        return str(result)


def _label(component: Any, translator: Translator) -> str:
    if component is None:
        return "—"
    try:
        cat = translator.translate_category(getattr(component, "category", "") or "")
    except Exception:
        cat = getattr(component, "category", "") or ""
    parts = [str(getattr(component, "manufacturer", "") or "").strip(),
             str(getattr(component, "model", "") or "").strip()]
    name = " ".join(p for p in parts if p)
    return f"{cat}: {name}" if cat else name


class BuildCompareView(ttk.Frame):
    """Presentation component for A-vs-B comparison. Receives data; no persistence."""

    def __init__(
        self,
        parent: tk.Misc,
        translator: Translator,
        *,
        on_back: Callable[[], None] | None = None,
    ) -> None:
        super().__init__(parent, style="App.TFrame")
        self.translator = translator
        self._on_back = on_back or (lambda: None)
        self._data: dict[str, Any] | None = None
        self._title_label: ttk.Label | None = None
        self._back_button: ttk.Button | None = None
        self._text: tk.Text | None = None
        self._build_ui()

    def _t(self, key: str) -> str:
        try:
            return self.translator.t(key)
        except Exception:
            return key

    def _build_ui(self) -> None:
        self.columnconfigure(0, weight=1)
        self.rowconfigure(1, weight=1)
        header = ttk.Frame(self, style="App.TFrame")
        header.grid(row=0, column=0, sticky="ew", pady=(0, 8))
        header.columnconfigure(0, weight=1)
        self._title_label = ttk.Label(header, style="Title.TLabel")
        self._title_label.grid(row=0, column=0, sticky="w")
        self._back_button = ttk.Button(header, style="Secondary.TButton", command=self._on_back)
        self._back_button.grid(row=0, column=1, sticky="e")
        body = tk.Frame(self, background=PALETTE["surface"],
                        highlightbackground=PALETTE["border"], highlightthickness=1, bd=0)
        body.grid(row=1, column=0, sticky="nsew")
        body.columnconfigure(0, weight=1)
        body.rowconfigure(0, weight=1)
        self._text = tk.Text(body, wrap="word", font=("Segoe UI", 10),
                             background=PALETTE["surface"], foreground=PALETTE["text"],
                             relief="flat", highlightthickness=0, bd=0,
                             padx=14, pady=12, state="disabled")
        self._text.grid(row=0, column=0, sticky="nsew")
        scroll = ttk.Scrollbar(body, orient="vertical", command=self._text.yview)
        scroll.grid(row=0, column=1, sticky="ns")
        self._text.configure(yscrollcommand=scroll.set)
        self.apply_translations()

    def set_translator(self, translator: Translator) -> None:
        self.translator = translator
        self.apply_translations()

    def apply_translations(self) -> None:
        if self._title_label is not None:
            self._title_label.configure(text=self._t("build_compare.title"))
        if self._back_button is not None:
            self._back_button.configure(text=self._t("build_compare.back"))
        if self._data is not None:
            self._render()

    def set_comparison(self, data: dict[str, Any]) -> None:
        self._data = dict(data)
        self._render()

    def clear(self) -> None:
        self._data = None
        if self._text is not None:
            self._text.configure(state="normal")
            self._text.delete("1.0", "end")
            self._text.configure(state="disabled")

    # --- rendering ---
    def _state_tag(self, state: str) -> str:
        return self._t(f"build_compare.state_{state}")

    def _field_label(self, fk: str) -> str:
        for key in (f"component_form.{fk}", f"table.{fk}"):
            try:
                return self.translator.t(key)
            except Exception:
                continue
        return fk

    def _val(self, v: Any, unit: Any) -> str:
        lang = getattr(self.translator, "language", "es")
        s = _fmt_param(v, lang)
        return f"{s} {unit}" if unit not in (None, "") else s

    def _render(self) -> None:
        if self._text is None or self._data is None:
            return
        t = self._t
        lang = getattr(self.translator, "language", "es")
        d = self._data
        hw = d["hardware"]
        rep_a, rep_b = d["report_a"], d["report_b"]
        cdiff = d["compat"]
        lines: list[str] = []
        ba, bb = d["build_a"], d["build_b"]
        lines.append(t("build_compare.direction").format(a=getattr(ba, "name", ""), b=getattr(bb, "name", "")))
        if not getattr(ba, "component_ids", None):
            lines.append(f"A: {t('build_compare.empty_build')}")
        if not getattr(bb, "component_ids", None):
            lines.append(f"B: {t('build_compare.empty_build')}")
        lines.append("")
        lines.append(t("build_compare.summary_title"))
        lines.append(f"- {t('build_compare.common')}: {hw.common_count}")
        lines.append(f"- {t('build_compare.added')}: {hw.added_count}")
        lines.append(f"- {t('build_compare.removed')}: {hw.removed_count}")
        lines.append(f"- {t('build_compare.replaced')}: {hw.replaced_count}")
        lines.append(f"- {t('build_compare.unknown')}: {hw.unknown_count}")
        lines.append(f"- {t('build_compare.tech_changes')}: {hw.tech_changes}")
        lines.append(f"- {t('build_compare.compat_overall_a')}: {_res_label(t, getattr(rep_a, 'overall_result', ''))}")
        lines.append(f"- {t('build_compare.compat_overall_b')}: {_res_label(t, getattr(rep_b, 'overall_result', ''))}")
        lines.append(f"- {t('build_compare.finding_new')}: {cdiff.new_count}")
        lines.append(f"- {t('build_compare.finding_resolved')}: {cdiff.resolved_count}")
        lines.append(f"- {t('build_compare.finding_changed')}: {cdiff.changed_count}")
        lines.append("")
        lines.append(t("build_compare.hardware_title"))
        if not hw.items:
            lines.append(t("build_compare.no_differences"))
        current_cat = None
        for item in hw.items:
            if item.category != current_cat:
                current_cat = item.category
                try:
                    cat = self.translator.translate_category(current_cat or "")
                except Exception:
                    cat = current_cat or ""
                lines.append(f"[{cat}]")
            tag = self._state_tag(item.state)
            la = _label(item.component_a, self.translator)
            lb = _label(item.component_b, self.translator)
            if item.state == REPLACED:
                lines.append(f"  [{tag}] {la} → {lb}")
                for fk, (fva, fvb) in sorted(item.field_diffs.items()):
                    lines.append(f"    {self._field_label(fk)}: {self._val(fva, None)} → {self._val(fvb, None)}")
            elif item.state == ADDED:
                lines.append(f"  [{tag}] → {lb}")
            elif item.state == REMOVED:
                lines.append(f"  [{tag}] {la}")
            elif item.state == UNKNOWN:
                side = "A" if item.component_a is not None else "B"
                lines.append(f"  [{tag} {side}] {la if item.component_a is not None else lb}")
            else:
                lines.append(f"  [{tag}] {la}")
        lines.append("")
        lines.append(t("build_compare.technical_title"))
        shown = False
        for item in hw.items:
            diffs = [x for x in item.attribute_diffs if x.status != "equal"]
            metas = [x for x in item.attribute_diffs if x.status == "equal" and x.meta_differs]
            if not diffs and not metas:
                continue
            shown = True
            la = _label(item.component_a or item.component_b, self.translator)
            lines.append(f"  {la}")
            for ad in diffs:
                st = t(f"build_compare.attr_{ad.status}")
                lines.append(f"    {ad.key} [{st}]: {self._val(ad.value_a, ad.unit_a)} → {self._val(ad.value_b, ad.unit_b)}")
            if metas:
                lines.append(f"    {t('build_compare.metadata_note')}")
        if not shown:
            lines.append(t("build_compare.no_differences"))
        lines.append("")
        lines.append(t("build_compare.compat_title"))
        for pair in cdiff.pairs:
            key = pair.key[0] if pair.key else ""
            try:
                rl = self.translator.t(f"compatibility.rule_labels.{key.replace('.', '__')}")
            except Exception:
                rl = key
            if pair.status == "same":
                st = t("build_compare.finding_same")
            elif pair.status == "resolved":
                st = t("build_compare.finding_resolved")
            elif pair.status == "new_issue":
                st = t("build_compare.finding_new")
            else:
                st = t("build_compare.finding_changed")
            expl = t(f"build_compare.explanation_{pair.explanation}")
            ra = _res_label(t, getattr(pair.finding_a, "result", "")) if pair.finding_a is not None else "—"
            rb = _res_label(t, getattr(pair.finding_b, "result", "")) if pair.finding_b is not None else "—"
            lines.append(f"  [{st}] {rl}: {ra} → {rb}")
            comps = d.get("components_by_id", {}) or {}
            if pair.finding_a is not None:
                names_a = ", ".join(_label(comps.get(c, None), self.translator) if comps.get(c) is not None else str(c)
                                    for c in (getattr(pair.finding_a, "component_ids", ()) or ()))
                lines.append(f"    A: {names_a}")
            if pair.finding_b is not None:
                names_b = ", ".join(_label(comps.get(c, None), self.translator) if comps.get(c) is not None else str(c)
                                    for c in (getattr(pair.finding_b, "component_ids", ()) or ()))
                lines.append(f"    B: {names_b}")
            lines.append(f"    {expl}")
        lines.append("")
        lines.append(t("build_compare.not_evaluated_title"))
        ne_a = sorted({str(n.get('reason', '')) for n in getattr(rep_a, "not_evaluated_relations", ()) or ()})
        ne_b = sorted({str(n.get('reason', '')) for n in getattr(rep_b, "not_evaluated_relations", ()) or ()})
        for reason in sorted(set(ne_a) | set(ne_b)):
            mark = "A+B" if reason in ne_a and reason in ne_b else ("A" if reason in ne_a else "B")
            try:
                label = self.translator.t(f"compatibility.not_evaluated_reason.{reason}")
            except Exception:
                label = reason
            lines.append(f"  [{mark}] {label}")
        lines.append("")
        lines.append(t("build_compare.limitations_title"))
        for lim in sorted(set(getattr(rep_a, "analysis_limitations", ()) or ()) | set(getattr(rep_b, "analysis_limitations", ()) or ())):
            try:
                label = self.translator.t(f"compatibility.limitations_tokens.{lim}")
            except Exception:
                label = lim
            lines.append(f"  - {label}")
        self._text.configure(state="normal")
        self._text.delete("1.0", "end")
        self._text.insert("1.0", "\n".join(lines) + "\n")
        self._text.configure(state="disabled")
