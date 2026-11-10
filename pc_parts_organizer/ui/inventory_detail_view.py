"""Inventory detail view component."""

from __future__ import annotations

import tkinter as tk
from tkinter import ttk
from typing import Any, Callable

from pc_parts_organizer.localization import Translator
from pc_parts_organizer.technical_profiles import ATTRIBUTE_REGISTRY
from pc_parts_organizer.ui.theme import PALETTE


class InventoryDetailView(ttk.Frame):
    """Presentation component for component detail. Receives Component data; no persistence/CRUD."""

    def __init__(
        self,
        parent: tk.Misc,
        translator: Translator,
        *,
        on_back: Callable[[], None] | None = None,
        on_edit: Callable[[str], None] | None = None,
        on_delete: Callable[[str], None] | None = None,
        on_add_technical_profile: Callable[[str], None] | None = None,
        on_edit_technical_profile: Callable[[str], None] | None = None,
        on_delete_technical_profile: Callable[[str], None] | None = None,
    ) -> None:
        super().__init__(parent, style="App.TFrame")
        self.translator = translator
        self._on_back = on_back or (lambda: None)
        self._on_edit = on_edit or (lambda _id: None)
        self._on_delete = on_delete or (lambda _id: None)
        self._on_add_technical_profile = on_add_technical_profile or (lambda _id: None)
        self._on_edit_technical_profile = on_edit_technical_profile or (lambda _id: None)
        self._on_delete_technical_profile = on_delete_technical_profile or (lambda _id: None)
        self._component: Any = None
        self._technical_profile: Any = None

        self.detail_title_label: ttk.Label | None = None
        self.detail_back_button: ttk.Button | None = None
        self.detail_edit_button: ttk.Button | None = None
        self.detail_delete_button: ttk.Button | None = None
        self._detail_fields: dict[str, tuple[ttk.Label, tk.Text]] = {}
        self._tech_title_label: ttk.Label | None = None
        self._tech_status_label: ttk.Label | None = None
        self._tech_text: tk.Text | None = None
        self._tech_add_btn: ttk.Button | None = None
        self._tech_edit_btn: ttk.Button | None = None
        self._tech_delete_btn: ttk.Button | None = None

        self._build_ui()

    def _build_ui(self) -> None:
        self.columnconfigure(0, weight=1)
        self.rowconfigure(1, weight=1)

        toolbar = ttk.Frame(self, style="App.TFrame")
        toolbar.grid(row=0, column=0, sticky="ew", pady=(0, 12))
        toolbar.columnconfigure(0, weight=1)

        self.detail_title_label = ttk.Label(toolbar, style="SectionTitle.TLabel")
        self.detail_title_label.grid(row=0, column=0, sticky="w")

        actions = ttk.Frame(toolbar, style="App.TFrame")
        actions.grid(row=0, column=1, sticky="e")
        self.detail_edit_button = ttk.Button(actions, style="Secondary.TButton", command=self._handle_edit)
        self.detail_edit_button.grid(row=0, column=0, padx=(0, 8))
        self.detail_delete_button = ttk.Button(actions, style="Secondary.TButton", command=self._handle_delete)
        self.detail_delete_button.grid(row=0, column=1, padx=(0, 8))
        self.detail_back_button = ttk.Button(actions, style="Secondary.TButton", command=self._on_back)
        self.detail_back_button.grid(row=0, column=2)

        card = tk.Frame(
            self,
            background=PALETTE["surface"],
            highlightbackground=PALETTE["border"],
            highlightthickness=1,
            bd=0,
            padx=16,
            pady=14,
        )
        card.grid(row=1, column=0, sticky="nsew")
        card.columnconfigure(1, weight=1)

        fields = [
            ("id", "component_detail.id", 1),
            ("category", "component_detail.category", 1),
            ("manufacturer", "component_detail.manufacturer", 1),
            ("model", "component_detail.model", 1),
            ("status", "component_detail.status", 1),
            ("location", "component_detail.location", 1),
            ("purchase_date", "component_detail.purchase_date", 1),
            ("warranty_end_date", "component_detail.warranty_end_date", 1),
            ("purchase_price", "component_detail.purchase_price", 1),
            ("purchase_currency", "component_detail.purchase_currency", 1),
            ("specifications", "component_detail.specifications", 5),
            ("notes", "component_detail.notes", 5),
        ]
        for row, (_key, _label_key, height) in enumerate(fields):
            if height > 1:
                card.rowconfigure(row, weight=1)
        self._detail_fields = {}
        for row, (key, _label_key, height) in enumerate(fields):
            label = ttk.Label(card, style="Form.TLabel")
            label.grid(row=row, column=0, sticky="nw", padx=(0, 12), pady=(0, 8))
            value = tk.Text(
                card,
                height=height,
                wrap="word",
                font=("Segoe UI", 10),
                background=PALETTE["surface"],
                foreground=PALETTE["text"],
                relief="flat",
                highlightthickness=0,
                bd=0,
                padx=0,
                pady=0,
            )
            value.grid(row=row, column=1, sticky="nsew", pady=(0, 8))
            value.configure(state="disabled")
            self._detail_fields[key] = (label, value)

        tech = tk.Frame(self, background=PALETTE["surface"], highlightbackground=PALETTE["border"], highlightthickness=1, bd=0, padx=16, pady=12)
        tech.grid(row=2, column=0, sticky="nsew", pady=(12, 0))
        tech.columnconfigure(0, weight=1)
        tech.rowconfigure(2, weight=1)
        self.rowconfigure(2, weight=1)
        tech_header = ttk.Frame(tech, style="Form.TFrame")
        tech_header.grid(row=0, column=0, sticky="ew")
        tech_header.columnconfigure(0, weight=1)
        self._tech_title_label = ttk.Label(tech_header, style="SectionTitle.TLabel")
        self._tech_title_label.grid(row=0, column=0, sticky="w")
        tech_actions = ttk.Frame(tech_header, style="Form.TFrame")
        tech_actions.grid(row=0, column=1, sticky="e")
        self._tech_add_btn = ttk.Button(tech_actions, style="Secondary.TButton", command=self._handle_tech_add)
        self._tech_add_btn.grid(row=0, column=0, padx=(0, 8))
        self._tech_edit_btn = ttk.Button(tech_actions, style="Secondary.TButton", command=self._handle_tech_edit)
        self._tech_edit_btn.grid(row=0, column=1, padx=(0, 8))
        self._tech_delete_btn = ttk.Button(tech_actions, style="Secondary.TButton", command=self._handle_tech_delete)
        self._tech_delete_btn.grid(row=0, column=2)
        self._tech_status_label = ttk.Label(tech, style="Form.TLabel")
        self._tech_status_label.grid(row=1, column=0, sticky="w", pady=(6, 4))
        self._tech_text = tk.Text(tech, height=6, wrap="word", font=("Segoe UI", 10), background=PALETTE["surface"], foreground=PALETTE["text"], relief="flat", highlightthickness=0, bd=0)
        self._tech_text.grid(row=2, column=0, sticky="nsew")
        self._tech_text.configure(state="disabled")

    def _set_text(self, widget: tk.Text, text: str) -> None:
        widget.configure(state="normal")
        widget.delete("1.0", "end")
        widget.insert("1.0", text)
        widget.configure(state="disabled")

    def set_translator(self, translator: Translator) -> None:
        self.translator = translator
        self.apply_translations()

    def apply_translations(self) -> None:
        if self.detail_title_label is not None:
            self.detail_title_label.configure(text=self.translator.t("component_detail.title"))
        if self.detail_back_button is not None:
            self.detail_back_button.configure(text=self.translator.t("component_detail.back"))
        if self.detail_edit_button is not None:
            self.detail_edit_button.configure(text=self.translator.t("component_detail.edit"))
        if self.detail_delete_button is not None:
            self.detail_delete_button.configure(text=self.translator.t("actions.delete_component"))
        if self._tech_title_label is not None:
            self._tech_title_label.configure(text=self.translator.t("technical_profile.section_title"))
        if self._tech_add_btn is not None:
            self._tech_add_btn.configure(text=self.translator.t("technical_profile.add"))
        if self._tech_edit_btn is not None:
            self._tech_edit_btn.configure(text=self.translator.t("technical_profile.edit"))
        if self._tech_delete_btn is not None:
            self._tech_delete_btn.configure(text=self.translator.t("technical_profile.delete"))
        for key, (label, _widget) in self._detail_fields.items():
            label.configure(text=self.translator.t(f"component_detail.{key}"))
        if self._component is not None:
            self.set_component(self._component)
            self._render_technical_profile()
        else:
            self._render_technical_profile()

    def set_component(self, component: Any) -> None:
        self._component = component
        empty = self.translator.t("component_detail.empty")
        raw_status = getattr(component, "status", "unspecified") or "unspecified"
        try:
            status_label = self.translator.translate_status(raw_status)
        except Exception:
            status_label = raw_status or empty
        location = (getattr(component, "location", "") or "").strip() or empty
        purchase_date = (getattr(component, "purchase_date", "") or "").strip() or empty
        warranty_end_date = (getattr(component, "warranty_end_date", "") or "").strip() or empty
        purchase_price = (getattr(component, "purchase_price", "") or "").strip()
        purchase_currency = (getattr(component, "purchase_currency", "") or "").strip()
        if purchase_price and purchase_currency:
            price_display = purchase_price
            currency_display = purchase_currency
        else:
            price_display = empty
            currency_display = empty
        values = {
            "id": getattr(component, "id", ""),
            "category": self.translator.translate_category(getattr(component, "category", "")),
            "manufacturer": getattr(component, "manufacturer", "") or empty,
            "model": getattr(component, "model", "") or empty,
            "status": status_label,
            "location": location,
            "purchase_date": purchase_date,
            "warranty_end_date": warranty_end_date,
            "purchase_price": price_display,
            "purchase_currency": currency_display,
            "specifications": (getattr(component, "specifications", "") or "").strip() or empty,
            "notes": (getattr(component, "notes", "") or "").strip() or empty,
        }
        for key, (_label, widget) in self._detail_fields.items():
            self._set_text(widget, values.get(key, empty))
        self._render_technical_profile()

    def set_technical_profile(self, profile: Any) -> None:
        self._technical_profile = profile
        self._render_technical_profile()

    def clear_component(self) -> None:
        self._component = None
        self._technical_profile = None
        empty = self.translator.t("component_detail.empty")
        for _key, (_label, widget) in self._detail_fields.items():
            self._set_text(widget, empty)
        self._render_technical_profile()

    def get_component_id(self) -> str | None:
        if self._component is None:
            return None
        return getattr(self._component, "id", None)

    def _handle_edit(self) -> None:
        cid = self.get_component_id()
        if cid:
            self._on_edit(cid)

    def _handle_delete(self) -> None:
        cid = self.get_component_id()
        if cid:
            self._on_delete(cid)


    def _profile_supported(self) -> bool:
        if self._component is None:
            return False
        return getattr(self._component, "category", "") in ATTRIBUTE_REGISTRY

    def _render_technical_profile(self) -> None:
        if self._tech_text is None:
            return
        supported = self._profile_supported()
        has_profile = self._technical_profile is not None
        if self._tech_add_btn is not None:
            self._tech_add_btn.configure(state=("normal" if supported and not has_profile and self._component else "disabled"))
        if self._tech_edit_btn is not None:
            self._tech_edit_btn.configure(state=("normal" if supported and has_profile and self._component else "disabled"))
        if self._tech_delete_btn is not None:
            self._tech_delete_btn.configure(state=("normal" if supported and has_profile and self._component else "disabled"))
        if self._tech_status_label is not None:
            if not self._component:
                self._tech_status_label.configure(text="")
            elif not supported:
                self._tech_status_label.configure(text=self.translator.t("technical_profile.unsupported"))
            elif not has_profile:
                self._tech_status_label.configure(text=self.translator.t("technical_profile.empty"))
            elif not getattr(self._technical_profile, "attributes", []):
                self._tech_status_label.configure(text=self.translator.t("technical_profile.no_attributes"))
            else:
                statuses = [getattr(a, "verification_status", "unverified") for a in self._technical_profile.attributes]
                if "needs_review" in statuses:
                    st = "status_needs_review"
                elif statuses and all(s == "verified" for s in statuses):
                    st = "status_verified"
                else:
                    st = "status_unverified"
                self._tech_status_label.configure(text=f"{self.translator.t('technical_profile.status_label')}: {self.translator.t(f'technical_profile.{st}')}")
        lines = []
        if self._component and supported and has_profile and getattr(self._technical_profile, "attributes", []):
            for a in self._technical_profile.attributes:
                key = getattr(a, "key", "")
                try:
                    label = self.translator.t(f"technical_profile.attributes.{key}")
                except Exception:
                    label = key
                val = getattr(a, "value", "")
                if isinstance(val, list):
                    if val and hasattr(val[0], "to_dict"):
                        parts = []
                        for obj in val:
                            if hasattr(obj, "slot_id"):
                                parts.append(f"[{obj.slot_id}] modes={','.join(getattr(obj,'supported_modes',()))} keyings={','.join(getattr(obj,'accepted_module_keyings',()))} lengths={','.join(getattr(obj,'supported_lengths',()))}")
                            elif hasattr(obj, "cable_id"):
                                ends = getattr(obj, "component_side_ends", ())
                                end_s = ",".join(f"{getattr(e,'end_id','?')}:{getattr(e,'connector_kind','?')}" for e in ends)
                                parts.append(f"[{obj.cable_id}] {getattr(obj,'assembly_type','')} -> {end_s}")
                            elif hasattr(obj, "connector_kind") and hasattr(obj, "quantity"):
                                req = getattr(obj, 'required', True)
                                parts.append(f"{obj.connector_kind} x{obj.quantity} {'required' if req else 'optional'}")
                            else:
                                try:
                                    parts.append(str(obj.to_dict()))
                                except Exception:
                                    parts.append(str(obj))
                        val = "; ".join(parts)
                    else:
                        val = ", ".join(str(x) for x in val)
                unit = getattr(a, "unit", None)
                val_text = f"{val} {unit}".strip() if unit else str(val)
                vstatus = getattr(a, "verification_status", "unverified")
                try:
                    vlabel = self.translator.t(f"technical_profile.status_{vstatus}")
                except Exception:
                    vlabel = vstatus
                src = getattr(a, "source", "unknown")
                try:
                    slabel = self.translator.t(f"technical_profile.sources.{src}")
                except Exception:
                    slabel = src
                conf = getattr(a, "confidence", "medium")
                try:
                    clabel = self.translator.t(f"technical_profile.confidence_levels.{conf}")
                except Exception:
                    clabel = conf
                line = f"{label}: {val_text} | {vlabel} | {self.translator.t('technical_profile.source')}: {slabel} | {self.translator.t('technical_profile.confidence')}: {clabel}"
                ev = getattr(a, "evidence_ref", None)
                vat = getattr(a, "verified_at", None)
                if ev:
                    line += f" | {self.translator.t('technical_profile.evidence_ref')}: {ev}"
                if vat:
                    line += f" | {self.translator.t('technical_profile.verified_at')}: {vat}"
                if key in ("rated_continuous_power_w", "recommended_psu_power_w"):
                    try:
                        note = self.translator.t("technical_profile.descriptive_power_note")
                    except Exception:
                        note = "Descriptive only; not an electrical compatibility check."
                    line += f" | {note}"
                lines.append(line)
        elif self._component and not supported:
            lines = [self.translator.t("technical_profile.unsupported")]
        elif self._component and not has_profile:
            lines = [self.translator.t("technical_profile.empty")]
        elif self._component and has_profile:
            lines = [self.translator.t("technical_profile.no_attributes")]
        else:
            lines = [""]
        self._set_text(self._tech_text, "\n".join(lines))

    def _handle_tech_add(self) -> None:
        cid = self.get_component_id()
        if cid:
            self._on_add_technical_profile(cid)

    def _handle_tech_edit(self) -> None:
        cid = self.get_component_id()
        if cid:
            self._on_edit_technical_profile(cid)

    def _handle_tech_delete(self) -> None:
        cid = self.get_component_id()
        if cid:
            self._on_delete_technical_profile(cid)
