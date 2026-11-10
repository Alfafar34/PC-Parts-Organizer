"""Build detail view component."""

from __future__ import annotations

import tkinter as tk
from tkinter import ttk
from typing import Any, Callable, Mapping

from pc_parts_organizer.localization import LocalizationError, Translator
from pc_parts_organizer.ui.theme import PALETTE


def _fmt_param(v: Any, language: str) -> str:
    if isinstance(v, bool):
        return ("Sí" if language == "es" else "Yes") if v else "No"
    if isinstance(v, (list, tuple)):
        # Avoid dataclass repr leaks in generic formatting.
        parts = []
        for x in v:
            if hasattr(x, "__dataclass_fields__"):
                n = type(x).__name__
                if n == "PowerConnectorRequirement":
                    req = "obligatorio" if language == "es" else "required"
                    opt = "opcional" if language == "es" else "optional"
                    parts.append(f"{getattr(x,'connector_kind','?')} x{getattr(x,'quantity','?')} ({req if getattr(x,'required',True) else opt})")
                elif n == "PowerCableEndSpec":
                    sg = getattr(x, "split_group_id", None)
                    parts.append(f"{getattr(x,'end_id','?')}:{getattr(x,'connector_kind','?')}" + (f"[{sg}]" if sg else ""))
                elif n == "PowerCableAssembly":
                    parts.append(f"{getattr(x,'cable_id','?')}:{getattr(x,'assembly_type','?')}")
                else:
                    parts.append(n)
            else:
                parts.append(str(x))
        return ", ".join(parts)
    if v is None:
        return "—"
    if hasattr(v, "__dataclass_fields__"):
        return _fmt_param([v], language)
    return str(v)


class BuildDetailView(ttk.Frame):
    """Presentation component for build detail. Receives data; no persistence."""

    def __init__(
        self,
        parent: tk.Misc,
        translator: Translator,
        *,
        on_back: Callable[[], None] | None = None,
        on_edit: Callable[[str], None] | None = None,
        on_delete: Callable[[str], None] | None = None,
        on_view_component: Callable[[str], None] | None = None,
        on_analyze: Callable[[str], None] | None = None,
        on_open_quality: Callable[[], None] | None = None,
        on_export_sheet: Callable[[str], None] | None = None,
    ) -> None:
        super().__init__(parent, style="App.TFrame")
        self.translator = translator
        self._on_back = on_back or (lambda: None)
        self._on_edit = on_edit or (lambda _id: None)
        self._on_delete = on_delete or (lambda _id: None)
        self._on_view_component = on_view_component or (lambda _id: None)
        self._on_analyze = on_analyze or (lambda _id: None)
        self._on_open_quality = on_open_quality or (lambda: None)
        self._on_export_sheet = on_export_sheet or (lambda _id: None)
        self._build: Any = None
        self._components_by_id: dict[str, Any] = {}
        self._profiles_by_id: dict[str, Any] = {}
        self._compat_report: Any = None
        self._compat_stale = False
        self._compat_error: str | None = None

        self.title_label: ttk.Label | None = None
        self.back_button: ttk.Button | None = None
        self.edit_button: ttk.Button | None = None
        self.delete_button: ttk.Button | None = None
        self.analyze_button: ttk.Button | None = None
        self.export_sheet_button: ttk.Button | None = None
        self._meta_text: tk.Text | None = None
        self._comp_tree: ttk.Treeview | None = None
        self._comp_item_to_id: dict[str, str] = {}
        self._empty_comp_label: ttk.Label | None = None
        self._compat_title: ttk.Label | None = None
        self._compat_status: ttk.Label | None = None
        self._compat_text: tk.Text | None = None
        self._compat_comp_combo: ttk.Combobox | None = None
        self._compat_open_btn: ttk.Button | None = None
        self._compat_comp_map: dict[str, str] = {}
        self._audit_title: ttk.Label | None = None
        self._audit_text: tk.Text | None = None
        self._audit_quality_btn: ttk.Button | None = None
        self._build_ui()

    def _build_ui(self) -> None:
        self.columnconfigure(0, weight=1)
        self.rowconfigure(2, weight=2)
        self.rowconfigure(3, weight=1)
        self.rowconfigure(4, weight=1)

        toolbar = ttk.Frame(self, style="App.TFrame")
        toolbar.grid(row=0, column=0, sticky="ew", pady=(0, 12))
        toolbar.columnconfigure(0, weight=1)
        self.title_label = ttk.Label(toolbar, style="SectionTitle.TLabel")
        self.title_label.grid(row=0, column=0, sticky="w")
        actions = ttk.Frame(toolbar, style="App.TFrame")
        actions.grid(row=0, column=1, sticky="e")
        self.edit_button = ttk.Button(actions, style="Secondary.TButton", command=self._handle_edit)
        self.edit_button.grid(row=0, column=0, padx=(0, 8))
        self.delete_button = ttk.Button(actions, style="Secondary.TButton", command=self._handle_delete)
        self.delete_button.grid(row=0, column=1, padx=(0, 8))
        self.export_sheet_button = ttk.Button(actions, style="Secondary.TButton", command=self._handle_export_sheet)
        self.export_sheet_button.grid(row=0, column=2, padx=(0, 8))
        self.back_button = ttk.Button(actions, style="Secondary.TButton", command=self._on_back)
        self.back_button.grid(row=0, column=3)

        meta_card = tk.Frame(
            self, background=PALETTE["surface"], highlightbackground=PALETTE["border"], highlightthickness=1, bd=0, padx=14, pady=12,
        )
        meta_card.grid(row=1, column=0, sticky="ew", pady=(0, 10))
        meta_card.columnconfigure(0, weight=1)
        self._meta_text = tk.Text(
            meta_card, height=4, wrap="word", font=("Segoe UI", 10), background=PALETTE["surface"],
            foreground=PALETTE["text"], relief="flat", highlightthickness=0, bd=0,
        )
        self._meta_text.grid(row=0, column=0, sticky="ew")
        self._meta_text.configure(state="disabled")

        comp_card = tk.Frame(
            self, background=PALETTE["surface"], highlightbackground=PALETTE["border"], highlightthickness=1, bd=0, padx=10, pady=10,
        )
        comp_card.grid(row=2, column=0, sticky="nsew", pady=(0, 10))
        comp_card.columnconfigure(0, weight=1)
        comp_card.rowconfigure(1, weight=1)
        ttk.Label(comp_card, text=self.translator.t("builds.composition"), style="SurfaceTitle.TLabel").grid(row=0, column=0, sticky="w", pady=(0, 6))
        tree_frame = ttk.Frame(comp_card, style="Surface.TFrame")
        tree_frame.grid(row=1, column=0, sticky="nsew")
        tree_frame.columnconfigure(0, weight=1)
        tree_frame.rowconfigure(0, weight=1)
        self._comp_tree = ttk.Treeview(tree_frame, columns=("manufacturer", "model"), show="tree headings", style="Inventory.Treeview")
        self._comp_tree.heading("#0", text=self.translator.t("table.category"), anchor="w")
        self._comp_tree.heading("manufacturer", text=self.translator.t("table.manufacturer"))
        self._comp_tree.heading("model", text=self.translator.t("table.model"))
        self._comp_tree.column("#0", width=180, minwidth=120)
        self._comp_tree.column("manufacturer", width=180, minwidth=120)
        self._comp_tree.column("model", width=260, minwidth=140)
        self._comp_tree.grid(row=0, column=0, sticky="nsew")
        sb = ttk.Scrollbar(tree_frame, orient="vertical", command=self._comp_tree.yview)
        sb.grid(row=0, column=1, sticky="ns")
        self._comp_tree.configure(yscrollcommand=sb.set)
        self._comp_tree.bind("<Double-1>", self._on_comp_double)
        self._empty_comp_label = ttk.Label(comp_card, style="Placeholder.TLabel", background=PALETTE["surface"])
        self._empty_comp_label.grid(row=2, column=0, sticky="w", pady=(6, 0))

        compat_card = tk.Frame(
            self, background=PALETTE["surface"], highlightbackground=PALETTE["border"], highlightthickness=1, bd=0, padx=10, pady=10,
        )
        compat_card.grid(row=3, column=0, sticky="nsew")
        compat_card.columnconfigure(0, weight=1)
        compat_card.rowconfigure(2, weight=1)
        top = ttk.Frame(compat_card, style="Surface.TFrame")
        top.grid(row=0, column=0, sticky="ew", pady=(0, 6))
        top.columnconfigure(0, weight=1)
        self._compat_title = ttk.Label(top, style="SurfaceTitle.TLabel")
        self._compat_title.grid(row=0, column=0, sticky="w")
        self.analyze_button = ttk.Button(top, style="Secondary.TButton", command=self._handle_analyze)
        self.analyze_button.grid(row=0, column=1, sticky="e")
        self._compat_status = ttk.Label(compat_card, style="Muted.TLabel", background=PALETTE["surface"], wraplength=760, justify="left")
        self._compat_status.grid(row=1, column=0, sticky="ew", pady=(0, 6))
        text_frame = ttk.Frame(compat_card, style="Surface.TFrame")
        text_frame.grid(row=2, column=0, sticky="nsew")
        text_frame.columnconfigure(0, weight=1)
        text_frame.rowconfigure(0, weight=1)
        self._compat_text = tk.Text(
            text_frame, height=10, wrap="word", font=("Segoe UI", 10), background=PALETTE["surface"],
            foreground=PALETTE["text"], relief="flat", highlightthickness=0, bd=0,
        )
        self._compat_text.grid(row=0, column=0, sticky="nsew")
        csb = ttk.Scrollbar(text_frame, orient="vertical", command=self._compat_text.yview)
        csb.grid(row=0, column=1, sticky="ns")
        self._compat_text.configure(yscrollcommand=csb.set, state="disabled")
        nav = ttk.Frame(compat_card, style="Surface.TFrame")
        nav.grid(row=3, column=0, sticky="ew", pady=(6, 0))
        nav.columnconfigure(0, weight=1)
        self._compat_comp_combo = ttk.Combobox(nav, state="readonly")
        self._compat_comp_combo.grid(row=0, column=0, sticky="ew", padx=(0, 8))
        self._compat_open_btn = ttk.Button(nav, style="Secondary.TButton", command=self._handle_open_implicated)
        self._compat_open_btn.grid(row=0, column=1)
        audit_card = tk.Frame(
            self, background=PALETTE["surface"], highlightbackground=PALETTE["border"], highlightthickness=1, bd=0, padx=10, pady=10,
        )
        audit_card.grid(row=4, column=0, sticky="nsew", pady=(10, 0))
        audit_card.columnconfigure(0, weight=1)
        audit_card.rowconfigure(1, weight=1)
        audit_top = ttk.Frame(audit_card, style="Surface.TFrame")
        audit_top.grid(row=0, column=0, sticky="ew", pady=(0, 6))
        audit_top.columnconfigure(0, weight=1)
        self._audit_title = ttk.Label(audit_top, style="SurfaceTitle.TLabel")
        self._audit_title.grid(row=0, column=0, sticky="w")
        self._audit_quality_btn = ttk.Button(audit_top, style="Secondary.TButton", command=self._on_open_quality)
        self._audit_quality_btn.grid(row=0, column=1, sticky="e")
        audit_frame = ttk.Frame(audit_card, style="Surface.TFrame")
        audit_frame.grid(row=1, column=0, sticky="nsew")
        audit_frame.columnconfigure(0, weight=1)
        audit_frame.rowconfigure(0, weight=1)
        self._audit_text = tk.Text(
            audit_frame, height=10, wrap="word", font=("Segoe UI", 10), background=PALETTE["surface"],
            foreground=PALETTE["text"], relief="flat", highlightthickness=0, bd=0,
        )
        self._audit_text.grid(row=0, column=0, sticky="nsew")
        asb = ttk.Scrollbar(audit_frame, orient="vertical", command=self._audit_text.yview)
        asb.grid(row=0, column=1, sticky="ns")
        self._audit_text.configure(yscrollcommand=asb.set, state="disabled")
        self.apply_translations()

    def set_translator(self, translator: Translator) -> None:
        self.translator = translator
        self.apply_translations()

    def apply_translations(self) -> None:
        if self.title_label is not None:
            self.title_label.configure(text=self.translator.t("builds.title"))
        if self.back_button is not None:
            self.back_button.configure(text=self.translator.t("builds.back"))
        if self.edit_button is not None:
            self.edit_button.configure(text=self.translator.t("builds.edit_build"))
        if self.delete_button is not None:
            self.delete_button.configure(text=self.translator.t("builds.delete_build"))
        if self.export_sheet_button is not None:
            try:
                self.export_sheet_button.configure(text=self.translator.t("build_sheet.export_action"))
            except Exception:
                self.export_sheet_button.configure(text="build_sheet.export_action")
        if self.analyze_button is not None:
            self.analyze_button.configure(text=self.translator.t("compatibility.analyze_button"))
        if self._compat_title is not None:
            self._compat_title.configure(text=self.translator.t("compatibility.section_title"))
        if self._compat_open_btn is not None:
            self._compat_open_btn.configure(text=self.translator.t("compatibility.finding.open_component"))
        if self._audit_title is not None:
            self._audit_title.configure(text=self.translator.t("build_audit.title"))
        if self._audit_quality_btn is not None:
            self._audit_quality_btn.configure(text=self.translator.t("build_audit.open_quality"))
        if self._comp_tree is not None:
            self._comp_tree.heading("#0", text=self.translator.t("table.category"), anchor="w")
            self._comp_tree.heading("manufacturer", text=self.translator.t("table.manufacturer"))
            self._comp_tree.heading("model", text=self.translator.t("table.model"))
        if self._build is not None:
            self._render()
        self._render_compatibility()

    def set_build(self, build: Any, components_by_id: dict[str, Any]) -> None:
        self._build = build
        self._components_by_id = dict(components_by_id)
        self._profiles_by_id = {}
        self._compat_report = None
        self._compat_stale = False
        self._compat_error = None
        self._render()
        self._render_compatibility()

    def invalidate_compatibility(self, stale: bool = True) -> None:
        if self._compat_report is not None:
            self._compat_stale = bool(stale)
        self._compat_error = None
        self._render_compatibility()

    def set_compatibility_report(self, report: Any, profiles_by_id: dict | None = None) -> None:
        self._compat_report = report
        if profiles_by_id is not None:
            self._profiles_by_id = dict(profiles_by_id)
        self._compat_stale = False
        self._compat_error = None
        self._render_compatibility()

    def set_compatibility_error(self, message_key: str = "compatibility.error") -> None:
        self._compat_report = None
        self._compat_stale = False
        self._compat_error = message_key
        self._render_compatibility()

    def get_build_id(self) -> str | None:
        return getattr(self._build, "id", None) if self._build is not None else None

    def _set_meta(self, text: str) -> None:
        if self._meta_text is None:
            return
        self._meta_text.configure(state="normal")
        self._meta_text.delete("1.0", "end")
        self._meta_text.insert("1.0", text)
        self._meta_text.configure(state="disabled")

    def _set_compat_text(self, text: str) -> None:
        if self._compat_text is None:
            return
        self._compat_text.configure(state="normal")
        self._compat_text.delete("1.0", "end")
        self._compat_text.insert("1.0", text)
        self._compat_text.configure(state="disabled")

    def _render(self) -> None:
        if self._build is None or self._comp_tree is None:
            return
        kind = getattr(self._build, "kind", "current")
        kind_label = self.translator.t("builds.kind_planned" if kind == "planned" else "builds.kind_current")
        name = getattr(self._build, "name", "") or self.translator.t("builds.unnamed")
        notes = (getattr(self._build, "notes", "") or "").strip() or self.translator.t("component_detail.empty")
        count = len(getattr(self._build, "component_ids", []) or [])
        self._set_meta(f"{self.translator.t('builds.name')}: {name}\n{self.translator.t('builds.kind')}: {kind_label}\n{self.translator.t('builds.components')}: {count}\n{self.translator.t('builds.notes')}: {notes}")
        for item in self._comp_tree.get_children():
            self._comp_tree.delete(item)
        self._comp_item_to_id.clear()
        ids = list(getattr(self._build, "component_ids", []) or [])
        if not ids:
            if self._empty_comp_label is not None:
                self._empty_comp_label.configure(text=self.translator.t("builds.no_components"))
            return
        if self._empty_comp_label is not None:
            self._empty_comp_label.configure(text="")
        groups: dict[str, list[Any]] = {}
        for cid in ids:
            comp = self._components_by_id.get(cid)
            if comp is None:
                continue
            cat = getattr(comp, "category", "Other") or "Other"
            groups.setdefault(cat, []).append(comp)
        for cat in sorted(groups.keys(), key=lambda c: c.casefold()):
            try:
                cat_label = self.translator.translate_category(cat)
            except Exception:
                cat_label = cat
            parent = self._comp_tree.insert("", "end", text=cat_label, open=True)
            for comp in sorted(groups[cat], key=lambda c: (str(getattr(c, "manufacturer", "")).casefold(), str(getattr(c, "model", "")).casefold())):
                iid = self._comp_tree.insert(parent, "end", values=(getattr(comp, "manufacturer", ""), getattr(comp, "model", "")))
                self._comp_item_to_id[iid] = getattr(comp, "id", "")
        for parent in self._comp_tree.get_children():
            self._comp_tree.item(parent, open=True)

    def _safe_t(self, key: str) -> str:
        try:
            return self.translator.t(key)
        except LocalizationError:
            return key

    def _rule_label(self, rule_id: str) -> str:
        try:
            return self.translator.t(f"compatibility.rule_labels.{rule_id.replace('.', '__')}")
        except LocalizationError:
            return rule_id

    def _evidence_label(self, key: str) -> str:
        try:
            return self.translator.t(f"compatibility.evidence_keys.{key}")
        except LocalizationError:
            return key

    def _resolve_param_value(self, key: str, v: Any) -> str:
        lang = getattr(self.translator, "language", "es")
        if key == "reason" and isinstance(v, str):
            try:
                resolved = self.translator.t(f"compatibility.reasons.{v}")
            except Exception:
                resolved = str(v)
            # reason is interpolated as a clause; avoid duplicated terminal punctuation
            return resolved.rstrip().rstrip('.') if isinstance(resolved, str) else resolved
        if key == "storage_id" and isinstance(v, str) and v in self._components_by_id:
            return self._comp_label(v)
        if isinstance(v, str) and v in self._components_by_id and (key.endswith("_id") or key == "component_id"):
            return self._comp_label(v)
        if isinstance(v, (list, tuple)):
            if v and all(isinstance(x, str) and x in self._components_by_id for x in v) and key not in ("candidate_slots", "slot_ids") and (key.endswith("_ids") or key == "component_ids"):
                return ", ".join(self._comp_label(x) for x in v)
            return _fmt_param(v, lang)
        return _fmt_param(v, lang)

    def _format_message(self, finding: Any) -> str:
        key = getattr(finding, "message_key", "") or ""
        params = dict(getattr(finding, "message_params", {}) or {})
        safe = {k: self._resolve_param_value(k, v) for k, v in params.items()}
        tail = "; ".join(f"{k}={safe.get(k, v)}" for k, v in params.items())
        if not key:
            base = self._safe_t("compatibility.finding.unknown_message")
            return f"{base} ({tail})" if tail else base
        template = None
        for candidate in (f"compatibility.messages.{key}", key):
            try:
                template = self.translator.t(candidate)
                break
            except LocalizationError:
                continue
        if template is None:
            base = self._safe_t("compatibility.finding.unknown_message")
            extra = f" key={key}" + (f"; {tail}" if tail else "")
            return f"{base} ({extra.strip()})"
        try:
            return template.format(**safe)
        except Exception:
            return f"{template} ({tail})" if tail else template

    def _comp_label(self, cid: str) -> str:
        c = self._components_by_id.get(cid)
        if c is None:
            return cid
        try:
            cat = self.translator.translate_category(getattr(c, "category", "") or "")
        except Exception:
            cat = getattr(c, "category", "") or ""
        parts = [str(x).strip() for x in (getattr(c, "manufacturer", ""), getattr(c, "model", "")) if str(x).strip()]
        name = " ".join(parts) or cid
        return f"{cat}: {name}" if cat else name

    def _resolve_missing(self, token: str) -> str:
        # dynamic tokens like ram[uuid].total_capacity_gb / gpu[uuid].card_length_mm
        if "[" in token and "]." in token:
            try:
                rid = token[token.index("[") + 1 : token.index("]")]
                attr = token.split("].", 1)[1]
                try:
                    attr_label = self.translator.t(f"technical_profile.attributes.{attr}")
                except Exception:
                    attr_label = attr
                return f"{self._comp_label(rid)} — {attr_label}"
            except Exception:
                pass
        try:
            return self.translator.t(f"compatibility.missing_info.{token}")
        except LocalizationError:
            try:
                return self.translator.t(f"technical_profile.attributes.{token.split('.',1)[-1]}")
            except Exception:
                return token

    def _resolve_action(self, token: str) -> str:
        if not token:
            return ""
        for candidate in (f"compatibility.recommended_actions.{token}", f"compatibility.recommended_action.{token}"):
            try:
                return self.translator.t(candidate)
            except LocalizationError:
                continue
        return ""

    def _sv(self, key: str, fallback: str | None = None) -> str:
        try:
            return self.translator.t(f"compatibility.slot_values.{key}")
        except Exception:
            return fallback if fallback is not None else key

    def _slot_token(self, v: Any) -> str:
        if v is None:
            return self._sv("not_declared")
        if isinstance(v, str):
            if v == "":
                return self._sv("not_declared")
            try:
                return self.translator.t(f"compatibility.slot_values.{v}")
            except Exception:
                return v
        if isinstance(v, (list, tuple)):
            if not v:
                return self._sv("not_declared")
            return ", ".join(self._slot_token(x) for x in v)
        if isinstance(v, bool):
            return self._sv("yes" if v else "no")
        return str(v)

    def _render_m2_slot(self, slot: Mapping, indent: str) -> list[str]:
        nd = self._sv("not_declared")
        sid = slot.get("slot_id") or "?"
        lines = [f"{indent}- {self._sv('m2_slot')}: {sid}"]
        i2 = indent + "  "
        fields = [
            ("accepted_keyings", "accepted_module_keyings"),
            ("supported_lengths", "supported_lengths"),
            ("supported_modes", "supported_modes"),
            ("pcie_gen_max", "pcie_generation_max"),
            ("pcie_lanes_max", "pcie_lanes_max"),
            ("routed_to", "routed_to"),
            ("shared_resource_group", "shared_resource_group_id"),
            ("disables_sata_ports", "disables_sata_port_ids"),
        ]
        for label_key, attr in fields:
            val = slot.get(attr)
            if attr in ("pcie_generation_max", "pcie_lanes_max", "routed_to", "shared_resource_group_id") and val in (None, "", ()):
                shown = nd
            elif attr == "disables_sata_port_ids" and not val:
                shown = nd
            else:
                shown = self._slot_token(val)
            lines.append(f"{i2}{self._sv(label_key)}: {shown}")
        ev = slot.get("evidence_ref")
        if ev:
            lines.append(f"{i2}{self._sv('slot_evidence')}: {self._sv('evidence_available')}")
        return lines



    def _psu_connector_label(self, kind: Any) -> str:
        k = str(kind or "")
        es = getattr(self.translator, "language", "en") == "es"
        labels = {
            "ATX_20": "ATX_20", "ATX_24": "ATX_24", "EPS_4": "EPS_4", "EPS_8": "EPS_8",
            "PCIE_6": "PCIe 6 pines" if es else "PCIe 6-pin",
            "PCIE_8": "PCIe 8 pines" if es else "PCIe 8-pin",
            "12VHPWR": "12VHPWR", "12V_2x6": "12V-2x6",
        }
        return labels.get(k, k)

    def _psu_nd(self) -> str:
        return self._safe_t("compatibility.psu_evidence.not_declared")

    def _render_psu_typed_item(self, item: Any, indent: str) -> list[str]:
        if isinstance(item, Mapping):
            # defensive
            return [f"{indent}- {k}: {self._slot_token(v) if not hasattr(v,'__dataclass_fields__') else _fmt_param(v, getattr(self.translator,'language','es'))}" for k, v in item.items()]
        if not hasattr(item, "__dataclass_fields__"):
            return [f"{indent}- {_fmt_param(item, getattr(self.translator,'language','es'))}"]
        n = type(item).__name__
        lang = getattr(self.translator, "language", "es")
        if n == "PowerConnectorRequirement":
            req = self._safe_t("compatibility.psu_evidence.required") if getattr(item, "required", True) else self._safe_t("compatibility.psu_evidence.optional")
            lines = [f"{indent}- {self._psu_connector_label(getattr(item,'connector_kind',''))} × {getattr(item,'quantity','?')} — {req}"]
            notes = getattr(item, "notes", None)
            if notes:
                lines.append(f"{indent}  {self._safe_t('compatibility.psu_evidence.notes')}: {notes}")
            return lines
        if n == "PowerCableEndSpec":
            sg = getattr(item, "split_group_id", None)
            line = f"{indent}- {self._safe_t('compatibility.psu_evidence.end')} {getattr(item,'end_id','?')} — {self._psu_connector_label(getattr(item,'connector_kind',''))}"
            if sg:
                line += f" — {self._safe_t('compatibility.psu_evidence.split_group')} {sg}"
            return [line]
        if n == "PowerCableAssembly":
            nd = self._psu_nd()
            at = getattr(item, "assembly_type", "") or ""
            try:
                at_l = self.translator.t(f"compatibility.psu_evidence.assembly_types.{at}")
            except Exception:
                at_l = at
            lines = [f"{indent}- {self._safe_t('compatibility.psu_evidence.cable_assembly')}: {getattr(item,'cable_id','?')}"]
            i2 = indent + "  "
            lines.append(f"{i2}{self._safe_t('compatibility.psu_evidence.assembly_type')}: {at_l}")
            ps = getattr(item, "psu_side_connector_id", None)
            if at == "modular_native":
                lines.append(f"{i2}{self._safe_t('compatibility.psu_evidence.psu_side_connector')}: {ps or nd}")
                lines.append(f"{i2}{self._safe_t('compatibility.psu_evidence.modular_note')}")
            elif ps:
                lines.append(f"{i2}{self._safe_t('compatibility.psu_evidence.psu_side_connector')}: {ps}")
            apm = getattr(item, "approved_psu_model", None)
            apr = getattr(item, "approval_reference", None)
            if apm or apr or at == "manufacturer_approved_adapter":
                lines.append(f"{i2}{self._safe_t('compatibility.psu_evidence.approved_psu_model')}: {apm or nd}")
                lines.append(f"{i2}{self._safe_t('compatibility.psu_evidence.approval_reference')}: {(apr + ' (' + self._safe_t('compatibility.psu_evidence.approval_declared_not_authenticated') + ')') if apr else nd}")
            notes = getattr(item, "notes", None)
            if notes:
                lines.append(f"{i2}{self._safe_t('compatibility.psu_evidence.notes')}: {notes}")
            ends = list(getattr(item, "component_side_ends", ()) or ())
            if ends:
                lines.append(f"{i2}{self._safe_t('compatibility.psu_evidence.component_side_ends')}:")
                for e in ends:
                    lines.extend(self._render_psu_typed_item(e, i2 + "  "))
            if at in ("third_party_adapter", "unknown", "manufacturer_approved_adapter"):
                lines.append(f"{i2}{self._safe_t('compatibility.psu_evidence.not_counted_confirmed')}")
            return lines
        return [f"{indent}- {_fmt_param(item, lang)}"]

    def _psu_s7_note(self, finding: Any) -> str | None:
        ev = getattr(finding, "evidence", None) or {}
        pca = ev.get("power_cable_assemblies") or {}
        unresolved = list(pca.get("unresolved_assemblies") or []) if isinstance(pca, Mapping) else []
        approved = [u for u in unresolved if isinstance(u, Mapping) and u.get("assembly_type") == "manufacturer_approved_adapter"]
        if not approved:
            return None
        cids = list(getattr(finding, "component_ids", ()) or [])
        psu_c = None
        for cid in cids:
            c = self._components_by_id.get(cid)
            if c is not None and getattr(c, "category", "") == "PSU":
                psu_c = c; break
        psu_label = self._comp_label(psu_c.id) if psu_c is not None else self._safe_t("compatibility.psu_evidence.not_declared")
        parts = []
        for u in approved:
            apm = u.get("approved_psu_model") or self._psu_nd()
            apr = u.get("approval_reference") or self._psu_nd()
            try:
                parts.append(self.translator.t("compatibility.psu_evidence.s7_correspondence_note").format(approved_model=apm, psu_label=psu_label, approval_reference=apr))
            except Exception:
                parts.append(f"approved={apm} psu={psu_label} ref={apr}")
        return " ".join(parts) if parts else None

    def _render_generic_evidence_mapping(self, item: Mapping, indent: str) -> list[str]:
        lines = [f"{indent}-"]
        for k, v in item.items():
            label = self._evidence_label(str(k))
            if isinstance(v, Mapping):
                lines.append(f"{indent}  {label}:")
                if "key" in v and "source" in v:
                    lines.extend(self._render_evidence(v, indent + "    "))
                else:
                    for kk, vv in v.items():
                        lines.append(f"{indent}    {self._evidence_label(str(kk))}: {self._slot_token(vv)}")
            else:
                if isinstance(v, str) and (str(k) == "id" or str(k).endswith("_id")) and v in self._components_by_id:
                    shown = self._comp_label(v)
                else:
                    shown = self._slot_token(v)
                lines.append(f"{indent}  {label}: {shown}")
        return lines

    def _render_evidence(self, ev: Any, indent: str = "    ") -> list[str]:
        lines: list[str] = []
        if not isinstance(ev, Mapping):
            return lines
        # simple attr evidence
        if "key" in ev and "source" in ev:
            src = ev.get("source")
            conf = ev.get("confidence")
            vs = ev.get("verification_status")
            try:
                src_l = self.translator.t(f"technical_profile.sources.{src}") if src else self._safe_t("compatibility.evidence_labels.not_set")
            except Exception:
                src_l = str(src or "")
            try:
                conf_l = self.translator.t(f"technical_profile.confidence_levels.{conf}") if conf else self._safe_t("compatibility.evidence_labels.not_set")
            except Exception:
                conf_l = str(conf or "")
            try:
                vs_l = self.translator.t(f"compatibility.verification_statuses.{vs}") if vs else self._safe_t("compatibility.evidence_labels.not_set")
            except Exception:
                vs_l = str(vs or "")
            unit = ev.get("unit")
            val = ev.get("value")
            lang = getattr(self.translator, "language", "es")
            k = ev.get("key")
            if k == "m2_slots" and isinstance(val, (list, tuple)):
                val_s = f"{len(val)}"
            elif k in ("power_cable_assemblies", "motherboard_power_connectors_required", "gpu_power_connectors_required") and isinstance(val, (list, tuple)):
                # Never repr typed dataclass collections.
                if k == "power_cable_assemblies":
                    label = self._safe_t("compatibility.psu_evidence.cable_assembly")
                    val_s = f"{len(val)} ({label})" if len(val) != 1 else f"1 ({label})"
                else:
                    label = self._safe_t("compatibility.psu_evidence.declared_requirements")
                    val_s = f"{len(val)}"
                # Render structured typed items below if present (defensive); value line stays summary.
                _psu_typed_items = list(val)
            else:
                val_s = _fmt_param(val, lang)
                _psu_typed_items = None
            if unit:
                val_s = f"{val_s} {unit}"
            lines.append(f"{indent}{self._safe_t('compatibility.evidence_labels.value')}: {val_s}")
            lines.append(f"{indent}{self._safe_t('compatibility.evidence_labels.source')}: {src_l}")
            lines.append(f"{indent}{self._safe_t('compatibility.evidence_labels.confidence')}: {conf_l}")
            lines.append(f"{indent}{self._safe_t('compatibility.evidence_labels.verification_status')}: {vs_l}")
            lines.append(f"{indent}{self._safe_t('compatibility.evidence_labels.evidence_ref')}: {ev.get('evidence_ref') or self._safe_t('compatibility.evidence_labels.not_set')}")
            lines.append(f"{indent}{self._safe_t('compatibility.evidence_labels.verified_at')}: {ev.get('verified_at') or self._safe_t('compatibility.evidence_labels.not_set')}")
            if k in ("m2_slots", "sata_port_identifiers", "power_cable_assemblies"):
                comp = ev.get("collection_completeness", "unknown")
                try:
                    comp_l = self.translator.t(f"technical_profile.completeness_{comp}")
                except Exception:
                    comp_l = str(comp)
                lines.append(f"{indent}{self._safe_t('compatibility.evidence_keys.collection_completeness')}: {comp_l}")
                scope = ev.get("completeness_scope")
                lines.append(f"{indent}{self._safe_t('compatibility.evidence_keys.completeness_scope')}: {scope or self._safe_t('compatibility.evidence_labels.not_set')}")
                if comp == "partial":
                    lines.append(f"{indent}{self._safe_t('compatibility.completeness_note_partial')}")
                elif comp == "unknown":
                    lines.append(f"{indent}{self._safe_t('compatibility.completeness_note_unknown')}")
            if k in ("power_cable_assemblies", "motherboard_power_connectors_required", "gpu_power_connectors_required") and isinstance(val, (list, tuple)):
                for item in val:
                    lines.extend(self._render_psu_typed_item(item, indent + "  "))
            return lines
        # nested evidence (aggregated)
        for k, v in ev.items():
            if isinstance(v, Mapping) and "key" in v and "source" in v:
                lines.append(f"{indent}{self._evidence_label(k)}:")
                lines.extend(self._render_evidence(v, indent + "  "))
            elif isinstance(v, (list, tuple)):
                if not v:
                    lines.append(f"{indent}{self._evidence_label(k)}: {self._sv('not_declared')}")
                    continue
                lines.append(f"{indent}{self._evidence_label(k)}:")
                for item in v:
                    if isinstance(item, Mapping) and "slot_id" in item and ("supported_modes" in item or "accepted_module_keyings" in item):
                        lines.extend(self._render_m2_slot(item, indent + "  "))
                    elif isinstance(item, Mapping) and "attr" in item:
                        lines.append(f"{indent}  - {self._comp_label(str(item.get('id','')))}")
                        lines.extend(self._render_evidence(item.get("attr"), indent + "    "))
                    elif isinstance(item, Mapping) and "connector_kind" in item and "end_id" in item and "cable_id" in item:
                        sg = item.get("split_group_id")
                        parts = [f"{item.get('connector_kind')}", f"end={item.get('end_id')}", f"cable={item.get('cable_id')}", f"type={item.get('assembly_type','')}"]
                        if sg: parts.append(f"split={sg}")
                        lines.append(f"{indent}  - " + ", ".join(parts))
                    elif isinstance(item, Mapping) and "connector_kind" in item and "quantity" in item and "required" in item:
                        req_l = self._safe_t('compatibility.psu_evidence.required') if item.get('required') else self._safe_t('compatibility.psu_evidence.optional')
                        lines.append(f"{indent}  - {self._psu_connector_label(item.get('connector_kind',''))} × {item.get('quantity')} — {req_l}")
                        if item.get('notes'):
                            lines.append(f"{indent}    {self._safe_t('compatibility.psu_evidence.notes')}: {item.get('notes')}")
                    elif isinstance(item, Mapping) and "assembly_type" in item and "cable_id" in item and "ends" in item:
                        nd = self._psu_nd()
                        at = item.get('assembly_type','') or ''
                        try:
                            at_l = self.translator.t(f"compatibility.psu_evidence.assembly_types.{at}")
                        except Exception:
                            at_l = at
                        lines.append(f"{indent}  - {self._safe_t('compatibility.psu_evidence.unresolved_assembly')}: {item.get('cable_id','')} — {at_l}")
                        i2 = indent + "    "
                        apm = item.get('approved_psu_model')
                        apr = item.get('approval_reference')
                        if apm or apr or at == 'manufacturer_approved_adapter':
                            lines.append(f"{i2}{self._safe_t('compatibility.psu_evidence.approved_psu_model')}: {apm or nd}")
                            if apr:
                                lines.append(f"{i2}{self._safe_t('compatibility.psu_evidence.approval_reference')}: {apr} ({self._safe_t('compatibility.psu_evidence.approval_declared_not_authenticated')})")
                            else:
                                lines.append(f"{i2}{self._safe_t('compatibility.psu_evidence.approval_reference')}: {nd}")
                        ends = item.get('ends') or []
                        if ends:
                            lines.append(f"{i2}{self._safe_t('compatibility.psu_evidence.component_side_ends')}:")
                            for e in ends:
                                if isinstance(e, Mapping):
                                    sg = e.get('split_group_id')
                                    el = f"{self._safe_t('compatibility.psu_evidence.end')} {e.get('end_id','?')} — {self._psu_connector_label(e.get('connector_kind',''))}"
                                    if sg:
                                        el += f" — {self._safe_t('compatibility.psu_evidence.split_group')} {sg}"
                                    lines.append(f"{i2}  - {el}")
                        lines.append(f"{i2}{self._safe_t('compatibility.psu_evidence.not_counted_confirmed')}")
                    elif isinstance(item, Mapping):
                        if "slot_id" in item:
                            lines.extend(self._render_m2_slot(item, indent + "  "))
                        else:
                            lines.extend(self._render_generic_evidence_mapping(item, indent + "  "))
                    else:
                        lines.append(f"{indent}  - {self._slot_token(item) if isinstance(item, str) else item}")
            elif isinstance(v, Mapping):
                lines.append(f"{indent}{self._evidence_label(k)}:")
                lines.extend(self._render_evidence(v, indent + "  "))
            else:
                lines.append(f"{indent}{self._evidence_label(k)}: {_fmt_param(v, getattr(self.translator,'language','es'))}")
        return lines

    def _render_compatibility(self) -> None:
        self._compat_comp_map = {}
        if self._compat_comp_combo is not None:
            self._compat_comp_combo.set("")
            self._compat_comp_combo.configure(values=[])
        if self._compat_status is None:
            return
        if self._compat_error:
            self._compat_status.configure(text=self._safe_t(self._compat_error))
            self._set_compat_text("")
            self._render_audit()
            return
        if self._compat_report is None:
            self._compat_status.configure(text=self._safe_t("compatibility.not_analyzed"))
            self._set_compat_text("")
            self._render_audit()
            return
        r = self._compat_report
        stale_prefix = f"[{self._safe_t('compatibility.stale')}] " if self._compat_stale else ""
        overall = getattr(r, "overall_result", "")
        overall_label = self._safe_t(f"compatibility.results.{overall}")
        explanation = self._safe_t(f"compatibility.result_explanations.{overall}")
        crit = sum(1 for f in getattr(r, "findings", ()) if getattr(f, "result", "") == "incompatible" and getattr(f, "severity", "") == "critical")
        status = f"{stale_prefix}{self._safe_t('compatibility.summary_title')}: {overall_label}. {explanation}"
        if crit:
            try:
                status += " " + self.translator.t("compatibility.critical_count").format(count=crit)
            except Exception:
                status += f" Critical: {crit}"
        try:
            status += " " + self.translator.t("compatibility.rules_evaluated").format(count=getattr(r, "rules_evaluated", 0))
        except Exception:
            pass
        self._compat_status.configure(text=status)
        lines: list[str] = []
        findings = list(getattr(r, "findings", ()) or [])
        storage_findings = [f for f in findings if getattr(f, "rule_id", "").startswith("storage_")]
        if storage_findings:
            def _worst(items):
                order = {"incompatible": 0, "requires_verification": 1, "insufficient_data": 2, "compatible": 3}
                return min(items, key=lambda x: order.get(getattr(x, "result", ""), 4))
            dims = [
                ("m2_fit", [f for f in storage_findings if getattr(f, "rule_id", "").startswith("storage_m2.")]),
                ("sata_ports", [f for f in storage_findings if getattr(f, "rule_id", "") in ("storage_sata.port_availability", "storage_sata.motherboard_missing", "storage_sata.ambiguous_motherboard")]),
                ("m2_sata_topology", [f for f in storage_findings if getattr(f, "rule_id", "") == "storage_sata.m2_topology"]),
                ("bay_capacity", [f for f in storage_findings if getattr(f, "rule_id", "").startswith("storage_case.")]),
            ]
            lines.append(f"== {self._safe_t('compatibility.sections.storage_connectivity')} ==")
            for dim_key, dim_fs in dims:
                if not dim_fs:
                    continue
                w = _worst(dim_fs)
                result_key = f"compatibility.results.{getattr(w, 'result', '')}"
                lines.append(f"- {self._safe_t(f'compatibility.storage_dimension_labels.{dim_key}')}: {self._safe_t(result_key)}")
            lines.append(self._safe_t("compatibility.storage_dimensions_note"))
            lines.append("")
        groups = [
            ("compatibility.sections.incompatibilities", [f for f in findings if getattr(f, "result", "") == "incompatible"]),
            ("compatibility.sections.requires_verification", [f for f in findings if getattr(f, "result", "") == "requires_verification"]),
            ("compatibility.sections.insufficient_data", [f for f in findings if getattr(f, "result", "") == "insufficient_data"]),
            ("compatibility.sections.compatible", [f for f in findings if getattr(f, "result", "") == "compatible"]),
            ("compatibility.sections.info", [f for f in findings if getattr(f, "result", "") not in ("incompatible", "requires_verification", "insufficient_data", "compatible")]),
        ]
        implicated: list[str] = []
        for title_key, fs in groups:
            if not fs:
                continue
            lines.append(f"== {self._safe_t(title_key)} ==")
            for f in fs:
                lines.append(f"- {self._safe_t('compatibility.finding.rule')}: {self._rule_label(getattr(f,'rule_id',''))}")
                res = getattr(f, "result", "")
                sev = getattr(f, "severity", "")
                lines.append(f"  {self._safe_t('compatibility.finding.result')}: {self._safe_t(f'compatibility.results.{res}')} | {self._safe_t('compatibility.finding.severity')}: {self._safe_t(f'compatibility.severity.{sev}')}")
                cids = list(getattr(f, "component_ids", ()) or [])
                if cids:
                    clabels = [self._comp_label(cid) for cid in cids]
                    lines.append(f"  {self._safe_t('compatibility.finding.components')}: " + "; ".join(clabels))
                    for cid in cids:
                        if cid not in implicated:
                            implicated.append(cid)
                attrs = list(getattr(f, "attributes_compared", ()) or [])
                if attrs:
                    alabels = []
                    for a in attrs:
                        try:
                            alabels.append(self.translator.t(f"technical_profile.attributes.{a}"))
                        except Exception:
                            alabels.append(a)
                    lines.append(f"  {self._safe_t('compatibility.finding.attributes')}: " + ", ".join(alabels))
                lines.append(f"  {self._safe_t('compatibility.finding.explanation')}: {self._format_message(f)}")
                s7_note = self._psu_s7_note(f)
                if s7_note:
                    lines.append(f"  {self._safe_t('compatibility.finding.explanation')}: {s7_note}")
                missing = list(getattr(f, "missing_information", ()) or [])
                if missing:
                    lines.append(f"  {self._safe_t('compatibility.finding.missing')}: " + "; ".join(self._resolve_missing(m) for m in missing))
                action = self._resolve_action(getattr(f, "recommended_action", "") or "")
                if action:
                    lines.append(f"  {self._safe_t('compatibility.finding.recommended')}: {action}")
                ev = getattr(f, "evidence", None)
                ev_lines = self._render_evidence(ev) if ev else []
                if ev_lines:
                    lines.append(f"  {self._safe_t('compatibility.sections.evidence')}:")
                    lines.extend(ev_lines)
                lines.append("")
        not_eval = list(getattr(r, "not_evaluated_relations", ()) or [])
        limitations = list(getattr(r, "analysis_limitations", ()) or [])
        if not_eval or limitations or True:
            lines.append(f"== {self._safe_t('compatibility.sections.not_evaluated')} ==")
            if not_eval:
                for item in not_eval:
                    cat = item.get("category", "") if isinstance(item, Mapping) else str(item)
                    reason = item.get("reason", "") if isinstance(item, Mapping) else ""
                    try:
                        cat_l = self.translator.translate_category(cat)
                    except Exception:
                        cat_l = cat
                    try:
                        reason_l = self.translator.t(f"compatibility.not_evaluated_reason.{reason}")
                    except Exception:
                        reason_l = reason
                    lines.append(f"- {cat_l}: {reason_l}")
            else:
                lines.append(f"- {self._safe_t('compatibility.evidence_labels.not_set')}")
            lines.append(f"== {self._safe_t('compatibility.sections.limitations')} ==")
            if limitations:
                seen_lim = set()
                rendered = 0
                for lim in limitations:
                    if lim in seen_lim:
                        continue
                    seen_lim.add(lim)
                    # Presentation-only: avoid irrelevant PSU-noise; keep electrical/case/geometry limitations.
                    if lim == "ram_not_present":
                        continue
                    rendered += 1
                    try:
                        lines.append(f"- {self.translator.t(f'compatibility.limitations_tokens.{lim}')}")
                    except Exception:
                        lines.append(f"- {lim}")
                if not rendered:
                    lines.append(f"- {self._safe_t('compatibility.evidence_labels.not_set')}")
            else:
                lines.append(f"- {self._safe_t('compatibility.evidence_labels.not_set')}")
        lines.append("")
        lines.append(self._safe_t("compatibility.evidence_disclaimer"))
        lines.append(self._safe_t("compatibility.scope_note"))
        self._set_compat_text("\n".join(lines))
        if implicated and self._compat_comp_combo is not None:
            labels = []
            for cid in implicated:
                label = self._comp_label(cid)
                self._compat_comp_map[label] = cid
                labels.append(label)
            self._compat_comp_combo.configure(values=labels)
            if labels:
                self._compat_comp_combo.set(labels[0])
        self._render_audit()

    def _set_audit_text(self, text: str) -> None:
        if self._audit_text is None:
            return
        self._audit_text.configure(state="normal")
        self._audit_text.delete("1.0", "end")
        self._audit_text.insert("1.0", text)
        self._audit_text.configure(state="disabled")

    def _audit_attr_label(self, cat: str, key: str) -> str:
        try:
            disp = self.translator.t(f"technical_profile.attributes.{key}")
            return disp if disp != f"technical_profile.attributes.{key}" else key
        except Exception:
            return key

    def _render_audit(self) -> None:
        if self._audit_text is None:
            return
        t = self._safe_t
        if self._build is None or self._compat_report is None:
            self._set_audit_text(t("build_audit.no_report"))
            return
        if not self._profiles_by_id:
            self._set_audit_text(t("build_audit.no_profiles"))
            return
        lang = getattr(self.translator, "language", "es")
        try:
            from pc_parts_organizer.build_audit import build_audit
            audit = build_audit(self._build, self._components_by_id, self._profiles_by_id, self._compat_report)
        except Exception:
            self._set_audit_text(t("build_audit.unavailable"))
            return
        if self._compat_stale:
            stale = t("compatibility.stale")
        else:
            stale = ""
        lines: list[str] = []
        if stale:
            lines.append(f"[{stale}]")
        # Summary counts distinct (component, attribute) pairs per dimension.
        # Dimensions intentionally overlap (an inconsistent attribute can also
        # block a rule); displayed rows never repeat the same (component, key).
        rel_keys = {(a.component_id, a.key) for a in audit.relevant_pending}
        fut_keys = {(a.component_id, a.key) for a in audit.future_pending} - rel_keys
        inc_keys = {(a.component_id, a.key) for a in audit.inconsistent}
        lines.append(t("build_audit.summary").format(
            demonstrated=len(audit.demonstrated), pending=len(audit.pending_verification),
            insufficient=len(audit.insufficient), not_evaluated=len(audit.not_evaluated),
            relevant=len(rel_keys), inconsistent=len(inc_keys)))
        lines.append("")
        shown_relevant = rel_keys | inc_keys
        if audit.demonstrated:
            lines.append(f"== {t('build_audit.demonstrated_title')} ==")
            for entry in audit.demonstrated:
                f = entry.finding
                lines.append(f"- {self._rule_label(str(getattr(f, 'rule_id', '')))} "
                             f"[{t('compatibility.results.' + str(getattr(f, 'result', '')))} | "
                             f"{t('compatibility.severity.' + str(getattr(f, 'severity', '')))}]")
                for c in (getattr(f, "component_ids", None) or []):
                    lines.append(f"  {self._comp_label(str(c))}")
            lines.append("")
        if audit.pending_verification:
            lines.append(f"== {t('build_audit.pending_title')} ==")
            for entry in audit.pending_verification:
                f = entry.finding
                reason = ""
                try:
                    reason = str(dict(getattr(f, "message_params", None) or {}).get("reason", "") or "")
                    if reason:
                        reason = self.translator.t(f"compatibility.reasons.{reason}")
                except Exception:
                    pass
                lines.append(f"- {self._rule_label(str(getattr(f, 'rule_id', '')))}" + (f" ({reason})" if reason else ""))
                for la in entry.linked:
                    mark = t("build_audit.link_direct") if la.direct else t("build_audit.link_context")
                    lines.append(f"  [{mark}] {self._comp_label(la.component_id)}: {la.key} "
                                 f"[{t('quality.state_' + la.status)}]")
            lines.append("")
        if audit.insufficient:
            lines.append(f"== {t('build_audit.insufficient_title')} ==")
            for entry in audit.insufficient:
                f = entry.finding
                missing = list(getattr(f, "missing_information", None) or [])
                lines.append(f"- {self._rule_label(str(getattr(f, 'rule_id', '')))}"
                             + (": " + ", ".join(str(m) for m in missing) if missing else ""))
                for la in entry.linked:
                    mark = t("build_audit.link_direct") if la.direct else t("build_audit.link_context")
                    lines.append(f"  [{mark}] {self._comp_label(la.component_id)}: {la.key} "
                                 f"[{t('quality.state_' + la.status)}]")
            lines.append("")
        if audit.not_evaluated:
            lines.append(f"== {t('build_audit.not_evaluated_title')} ==")
            for n in audit.not_evaluated:
                if isinstance(n, Mapping):
                    reason = n.get("reason", "")
                    cat = n.get("category", "")
                else:
                    reason = getattr(n, "reason", "")
                    cat = getattr(n, "category", "")
                try:
                    reason_l = self.translator.t(f"compatibility.not_evaluated_reason.{reason}") if reason else ""
                except Exception:
                    reason_l = str(reason)
                try:
                    cat_l = self.translator.translate_category(cat) if cat else ""
                except Exception:
                    cat_l = str(cat)
                lines.append(f"  - {cat_l + ': ' if cat_l else ''}{reason_l or reason}")
            lines.append("")
        if audit.limitations:
            lines.append(f"== {t('build_audit.limitations_title')} ==")
            for lim in audit.limitations:
                if lim == "ram_not_present":
                    continue  # same presentation rule as the compat section above
                try:
                    label = self.translator.t(f"compatibility.limitations_tokens.{lim}")
                except Exception:
                    label = str(lim)
                lines.append(f"  - {label}")
            lines.append("")
        if audit.relevant_pending or audit.inconsistent:
            lines.append(f"== {t('build_audit.relevant_title')} ==")
            rel_grouped: dict[tuple, list] = {}
            for a in list(audit.relevant_pending) + [x for x in audit.inconsistent if (x.component_id, x.key) not in shown_relevant]:
                rel_grouped.setdefault((a.component_id, a.key, a.status, a.category), []).append(a)
            for (cid, key, status, cat) in sorted(rel_grouped, key=lambda k: (str(k[0]), str(k[1]))):
                items = rel_grouped[(cid, key, status, cat)]
                mark = t("build_audit.link_direct") if any(i.direct for i in items) else t("build_audit.link_context")
                lines.append(f"  [{mark}] {self._comp_label(cid)}: {self._audit_attr_label(cat, key)} "
                             f"[{t('quality.state_' + status)}]")
                rules = sorted({i.rule_id for i in items if i.rule_id})
                if rules:
                    lines.append("      " + t("build_audit.used_by") + ": "
                                 + ", ".join(self._rule_label(r) for r in rules))
            lines.append("")
        future_rows = [a for a in audit.future_pending if (a.component_id, a.key) not in shown_relevant]
        # group identical (component, key) rows: same datum, several consumer rules
        grouped: dict[tuple, list] = {}
        for a in future_rows:
            grouped.setdefault((a.component_id, a.key, a.status), []).append(a.rule_id)
        if grouped and len(grouped) <= 20:
            lines.append(f"== {t('build_audit.future_title')} ==")
            for (cid, key, status), rules in sorted(grouped.items(), key=lambda kv: (kv[0][0], kv[0][1])):
                comp = self._components_by_id.get(cid)
                cat = getattr(comp, "category", "") if comp is not None else ""
                lines.append(f"  - {self._comp_label(cid)}: {self._audit_attr_label(cat, key)} "
                             f"[{t('quality.state_' + status)}]")
                uniq_rules = sorted(set(r for r in rules if r))
                if uniq_rules:
                    lines.append("      " + t("build_audit.used_by") + ": "
                                 + ", ".join(self._rule_label(r) for r in uniq_rules))
            lines.append("")
        elif grouped:
            lines.append(f"== {t('build_audit.future_title')} ({len(grouped)}) ==")
            lines.append("")
        lines.append(t("build_audit.note_no_score"))
        self._set_audit_text("\n".join(lines).rstrip() + "\n")

    def _on_comp_double(self, _event: object) -> None:
        if self._comp_tree is None:
            return
        sel = self._comp_tree.selection()
        if not sel:
            return
        cid = self._comp_item_to_id.get(sel[0])
        if cid:
            self._on_view_component(cid)

    def _handle_open_implicated(self) -> None:
        if self._compat_comp_combo is None:
            return
        label = self._compat_comp_combo.get()
        cid = self._compat_comp_map.get(label)
        if cid:
            self._on_view_component(cid)

    def _handle_edit(self) -> None:
        bid = self.get_build_id()
        if bid:
            self._on_edit(bid)

    def _handle_delete(self) -> None:
        bid = self.get_build_id()
        if bid:
            self._on_delete(bid)

    def _handle_analyze(self) -> None:
        bid = self.get_build_id()
        if bid:
            self._on_analyze(bid)

    def _handle_export_sheet(self) -> None:
        bid = self.get_build_id()
        if bid:
            self._on_export_sheet(bid)
