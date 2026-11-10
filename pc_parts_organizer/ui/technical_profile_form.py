"""Modal form for creating/editing a component technical profile (T17.2)."""

from __future__ import annotations

import tkinter as tk
from tkinter import messagebox, ttk

from pc_parts_organizer.localization import Translator
from pc_parts_organizer.technical_profiles import (
    ATTRIBUTE_REGISTRY,
    PROFILE_VERSION,
    M2SlotSpec,
    PowerCableAssembly,
    PowerCableEndSpec,
    PowerConnectorRequirement,
    TechnicalAttribute,
    TechnicalProfile,
    TechnicalProfileValidationError,
)
from pc_parts_organizer.ui.theme import PALETTE

_SOURCES = ("user_input", "catalog_import", "official_vendor_doc", "normalized_inferred", "unknown")
_CONFIDENCE = ("high", "medium", "low")
_VERIFICATION = ("unverified", "verified", "needs_review")


def _values_equal(old_value, old_unit, new_value, new_unit) -> bool:
    """Multiset value equality (reorder-insensitive, duplicates matter)."""
    from collections import Counter

    def _bag(v):
        items = list(v) if isinstance(v, (list, tuple)) else [v]
        return Counter(map(repr, items))

    return _bag(old_value) == _bag(new_value) and old_unit == new_unit


class TechnicalProfileForm:
    """Modal editor for a single component's technical profile. No persistence."""

    def __init__(
        self,
        parent: tk.Misc,
        translator: Translator,
        *,
        component_id: str,
        category: str,
        profile: TechnicalProfile | None = None,
    ) -> None:
        self.translator = translator
        self.component_id = component_id
        self.category = category
        self.result: TechnicalProfile | None = None
        self._existing = {a.key: a for a in (profile.attributes if profile else [])}
        self._rows: dict[str, dict[str, object]] = {}

        self.window = tk.Toplevel(parent)
        self.window.title(translator.t("technical_profile.edit" if profile else "technical_profile.add"))
        self.window.transient(parent)
        self.window.configure(background=PALETTE["surface"])
        self.window.geometry("860x720")
        self.window.minsize(760, 560)
        self.window.protocol("WM_DELETE_WINDOW", self._on_cancel)
        self.window.bind("<Escape>", lambda _e: self._on_cancel())
        self._build_ui()
        self.window.grab_set()

    def _t(self, key: str, **kw) -> str:
        try:
            return self.translator.t(key, **kw)
        except Exception:
            return key

    def _attr_label(self, key: str) -> str:
        return self._t(f"technical_profile.attributes.{key}")

    def _build_ui(self) -> None:
        outer = ttk.Frame(self.window, style="Form.TFrame", padding=12)
        outer.grid(row=0, column=0, sticky="nsew")
        self.window.columnconfigure(0, weight=1)
        self.window.rowconfigure(0, weight=1)
        outer.columnconfigure(0, weight=1)
        outer.rowconfigure(1, weight=1)

        header = ttk.Label(outer, text=self._t("technical_profile.section_title"), style="SectionTitle.TLabel")
        header.grid(row=0, column=0, sticky="w", pady=(0, 8))

        canvas = tk.Canvas(outer, background=PALETTE["surface"], highlightthickness=0, bd=0)
        scroll = ttk.Scrollbar(outer, orient="vertical", command=canvas.yview)
        body = ttk.Frame(canvas, style="Form.TFrame")
        body.columnconfigure(1, weight=1)
        body.bind("<Configure>", lambda _e: canvas.configure(scrollregion=canvas.bbox("all")))
        canvas.create_window((0, 0), window=body, anchor="nw")
        canvas.configure(yscrollcommand=scroll.set)
        canvas.grid(row=1, column=0, sticky="nsew")
        scroll.grid(row=1, column=1, sticky="ns")

        specs = ATTRIBUTE_REGISTRY.get(self.category, {})
        if not specs:
            ttk.Label(body, text=self._t("technical_profile.unsupported"), style="Form.TLabel", wraplength=720).grid(row=0, column=0, sticky="w")
        row = 0
        for key in sorted(specs.keys()):
            spec = specs[key]
            row = self._build_attr_row(body, row, key, spec)

        actions = ttk.Frame(outer, style="Form.TFrame")
        actions.grid(row=2, column=0, columnspan=2, sticky="e", pady=(10, 0))
        ttk.Button(actions, text=self._t("technical_profile.cancel"), style="Secondary.TButton", command=self._on_cancel).grid(row=0, column=0, padx=(0, 8))
        ttk.Button(actions, text=self._t("technical_profile.save"), style="Primary.TButton", command=self._on_save).grid(row=0, column=1)

    def _build_attr_row(self, parent: ttk.Frame, row: int, key: str, spec) -> int:
        existing = self._existing.get(key)
        card = tk.Frame(parent, background=PALETTE["surface"], highlightbackground=PALETTE["border"], highlightthickness=1, bd=0, padx=10, pady=8)
        card.grid(row=row, column=0, sticky="ew", pady=(0, 8))
        card.columnconfigure(1, weight=1)

        enabled_var = tk.BooleanVar(value=existing is not None)
        chk = ttk.Checkbutton(card, text=self._attr_label(key), variable=enabled_var)
        chk.grid(row=0, column=0, columnspan=2, sticky="w")

        ttk.Label(card, text=self._t("technical_profile.value"), style="Form.TLabel").grid(row=1, column=0, sticky="w", pady=(4, 2))
        value_widget = self._build_value_widget(card, spec, existing)
        self._grid_value_widget(value_widget, 1, 1)

        unit_text = ""
        if spec.allowed_units != (None,):
            units = [u for u in spec.allowed_units if u]
            if units:
                unit_text = units[0]
        if unit_text:
            ttk.Label(card, text=f"{self._t('technical_profile.unit')}: {unit_text}", style="Form.TLabel").grid(row=2, column=1, sticky="w")

        meta_row = 3
        ttk.Label(card, text=self._t("technical_profile.source"), style="Form.TLabel").grid(row=meta_row, column=0, sticky="w")
        source_cb = ttk.Combobox(card, values=[self._t(f"technical_profile.sources.{s}") for s in _SOURCES], state="readonly", width=24)
        source_cb.grid(row=meta_row, column=1, sticky="w")
        src_val = existing.source if existing else "user_input"
        source_cb.set(self._t(f"technical_profile.sources.{src_val}"))
        meta_row += 1
        ttk.Label(card, text=self._t("technical_profile.confidence"), style="Form.TLabel").grid(row=meta_row, column=0, sticky="w")
        conf_cb = ttk.Combobox(card, values=[self._t(f"technical_profile.confidence_levels.{c}") for c in _CONFIDENCE], state="readonly", width=24)
        conf_cb.grid(row=meta_row, column=1, sticky="w")
        conf_val = existing.confidence if existing else "medium"
        conf_cb.set(self._t(f"technical_profile.confidence_levels.{conf_val}"))
        meta_row += 1
        ttk.Label(card, text=self._t("technical_profile.verification_status"), style="Form.TLabel").grid(row=meta_row, column=0, sticky="w")
        ver_cb = ttk.Combobox(card, values=[self._t(f"technical_profile.status_{v}") for v in _VERIFICATION], state="readonly", width=24)
        ver_cb.grid(row=meta_row, column=1, sticky="w")
        ver_val = existing.verification_status if existing else "unverified"
        ver_cb.set(self._t(f"technical_profile.status_{ver_val}"))
        meta_row += 1
        ttk.Label(card, text=self._t("technical_profile.original_value"), style="Form.TLabel").grid(row=meta_row, column=0, sticky="w")
        orig_e = ttk.Entry(card, width=50)
        orig_e.grid(row=meta_row, column=1, sticky="ew")
        if existing and existing.original_value:
            orig_e.insert(0, existing.original_value)
        meta_row += 1
        ttk.Label(card, text=self._t("technical_profile.evidence_ref"), style="Form.TLabel").grid(row=meta_row, column=0, sticky="w")
        ev_e = ttk.Entry(card, width=50)
        ev_e.grid(row=meta_row, column=1, sticky="ew")
        if existing and existing.evidence_ref:
            ev_e.insert(0, existing.evidence_ref)
        meta_row += 1
        ttk.Label(card, text=self._t("technical_profile.verified_at"), style="Form.TLabel").grid(row=meta_row, column=0, sticky="w")
        vat_e = ttk.Entry(card, width=20)
        vat_e.grid(row=meta_row, column=1, sticky="w")
        if existing and existing.verified_at:
            vat_e.insert(0, existing.verified_at)

        comp_cb = None
        scope_e = None
        if getattr(spec, "allows_completeness", False):
            meta_row += 1
            ttk.Label(card, text=self._t("technical_profile.collection_completeness"), style="Form.TLabel").grid(row=meta_row, column=0, sticky="w")
            comp_cb = ttk.Combobox(card, values=[
                self._t("technical_profile.completeness_unknown"),
                self._t("technical_profile.completeness_partial"),
                self._t("technical_profile.completeness_complete"),
            ], state="readonly", width=24)
            comp_cb.grid(row=meta_row, column=1, sticky="w")
            comp_val = existing.collection_completeness if existing else "unknown"
            comp_cb.set(self._t(f"technical_profile.completeness_{comp_val}"))
            meta_row += 1
            ttk.Label(card, text=self._t("technical_profile.completeness_scope"), style="Form.TLabel").grid(row=meta_row, column=0, sticky="w")
            scope_e = ttk.Entry(card, width=50)
            scope_e.grid(row=meta_row, column=1, sticky="ew")
            if existing and existing.completeness_scope:
                scope_e.insert(0, existing.completeness_scope)
            meta_row += 1
            ttk.Label(card, text=self._t("technical_profile.completeness_help"), style="Form.TLabel", wraplength=520).grid(row=meta_row, column=0, columnspan=2, sticky="w")

        self._rows[key] = {
            "enabled": enabled_var,
            "spec": spec,
            "value": value_widget,
            "source": source_cb,
            "confidence": conf_cb,
            "verification": ver_cb,
            "original": orig_e,
            "evidence": ev_e,
            "verified_at": vat_e,
            "completeness": comp_cb,
            "scope": scope_e,
            "existing": existing,
        }
        return row + 1

    def _enum_display(self, key: str, canonical: str) -> str:
        for path in (f"technical_profile.{key}s.{canonical}", f"technical_profile.enum_values.{key}.{canonical}"):
            try:
                v = self.translator.t(path)
                if v != path:
                    return v
            except Exception:
                pass
        return canonical

    def _enum_canonical(self, key: str, display: str, values) -> str:
        for c in (values or ()):
            if self._enum_display(key, c) == display or c == display:
                return c
        return display

    def _build_value_widget(self, parent, spec, existing):
        if spec.value_type == "enum":
            vals = list(spec.enum_values or ())
            cb = ttk.Combobox(parent, values=[self._enum_display(spec.key, v) for v in vals], state="readonly", width=30)
            if existing is not None:
                cb.set(self._enum_display(spec.key, str(existing.value)))
            return ("enum", cb, spec.key, vals)
        if spec.value_type in ("int", "int_non_negative"):
            e = ttk.Entry(parent, width=20)
            if existing is not None:
                e.insert(0, str(existing.value))
            return (spec.value_type, e)
        if spec.value_type == "enum_list":
            lb = tk.Listbox(parent, selectmode="extended", height=min(8, max(3, len(spec.enum_values or ()))), exportselection=False)
            vals = list(spec.enum_values or ())
            for v in vals:
                lb.insert("end", v)
            if existing is not None and isinstance(existing.value, list):
                for idx, v in enumerate(vals):
                    if v in existing.value:
                        lb.selection_set(idx)
            return ("enum_list", lb)
        if spec.value_type == "identifier":
            e = ttk.Entry(parent, width=30)
            if existing is not None:
                e.insert(0, str(existing.value))
            return ("identifier", e)
        if spec.value_type == "identifier_list":
            t = tk.Text(parent, height=3, width=40, wrap="word", font=("Segoe UI", 9))
            if existing is not None and isinstance(existing.value, list):
                t.insert("1.0", "\n".join(str(v) for v in existing.value))
            return ("identifier_list", t)
        if spec.value_type == "typed_object_list":
            items = []
            if existing is not None and isinstance(existing.value, list):
                items = [v.copy() if hasattr(v, "copy") else v for v in existing.value]
            frame = ttk.Frame(parent)
            lb = tk.Listbox(frame, height=4, width=52, exportselection=False)
            lb.grid(row=0, column=0, rowspan=3, sticky="nsew")
            sb = ttk.Scrollbar(frame, orient="vertical", command=lb.yview)
            sb.grid(row=0, column=1, rowspan=3, sticky="ns")
            lb.configure(yscrollcommand=sb.set)
            state = {"spec": spec, "items": items, "listbox": lb}
            def _refresh(st=state):
                st["listbox"].delete(0, "end")
                for it in st["items"]:
                    st["listbox"].insert("end", self._typed_summary(st["spec"], it))
            def _add(st=state):
                obj = self._edit_typed_item(st["spec"], None)
                if obj is not None:
                    st["items"].append(obj); _refresh()
            def _edit(st=state):
                sel = st["listbox"].curselection()
                if not sel: return
                i = sel[0]
                obj = self._edit_typed_item(st["spec"], st["items"][i])
                if obj is not None:
                    st["items"][i] = obj; _refresh()
            def _remove(st=state):
                sel = st["listbox"].curselection()
                if not sel: return
                del st["items"][sel[0]]; _refresh()
            ttk.Button(frame, text=self._t("technical_profile.typed.add"), command=_add, style="Compact.TButton").grid(row=0, column=2, padx=(6,0), pady=1, sticky="ew")
            ttk.Button(frame, text=self._t("technical_profile.typed.edit"), command=_edit, style="Compact.TButton").grid(row=1, column=2, padx=(6,0), pady=1, sticky="ew")
            ttk.Button(frame, text=self._t("technical_profile.typed.remove"), command=_remove, style="Compact.TButton").grid(row=2, column=2, padx=(6,0), pady=1, sticky="ew")
            frame.columnconfigure(0, weight=1)
            _refresh()
            return ("typed_object_list", frame, state)
        e = ttk.Entry(parent, width=30)
        return ("text", e)

    def _grid_value_widget(self, widget, row, col):
        kind = widget[0]
        w = widget[1]
        sticky = "w" if kind in ("enum_list", "identifier_list", "typed_object_list") else "ew"
        w.grid(row=row, column=col, sticky=sticky)

    def _read_value(self, widget, spec):
        if widget[0] == "enum":
            _kind, w, key, vals = widget
            return self._enum_canonical(key, w.get().strip(), vals)
        if widget[0] == "typed_object_list":
            return list(widget[2]["items"])
        kind, w = widget
        if kind in ("int", "int_non_negative"):
            raw = w.get().strip()
            if not raw:
                return None
            try:
                n = int(raw)
            except ValueError as exc:
                raise TechnicalProfileValidationError(self._t("technical_profile.errors.invalid_integer")) from exc
            return n
        if kind == "enum_list":
            sel = w.curselection()
            return [w.get(i) for i in sel]
        if kind == "identifier":
            return w.get().strip()
        if kind == "identifier_list":
            raw = w.get("1.0", "end")
            parts = []
            for line in raw.replace(",", "\n").splitlines():
                s = line.strip()
                if s:
                    parts.append(s)
            return parts
        return w.get().strip()

    def _label_to_source(self, label: str) -> str:
        for s in _SOURCES:
            if self._t(f"technical_profile.sources.{s}") == label:
                return s
        return label

    def _label_to_confidence(self, label: str) -> str:
        for c in _CONFIDENCE:
            if self._t(f"technical_profile.confidence_levels.{c}") == label:
                return c
        return label

    def _label_to_verification(self, label: str) -> str:
        for v in _VERIFICATION:
            if self._t(f"technical_profile.status_{v}") == label:
                return v
        return label

    def _label_to_completeness(self, label: str) -> str:
        for v in ("unknown", "partial", "complete"):
            if self._t(f"technical_profile.completeness_{v}") == label:
                return v
        return label

    def _disp_value(self, value: object) -> str:
        if value is None:
            return "—"
        if isinstance(value, (list, tuple)):
            return ", ".join(self._disp_value(v) for v in value) or "—"
        if hasattr(value, "to_dict") and not isinstance(value, (str, int, float, bool)):
            try:
                detail = value.to_dict()
            except Exception:
                return str(value)
            if not isinstance(detail, dict):
                return str(value)
            parts = [f"{k}={v}" for k, v in detail.items()
                     if k not in ("schema_version",) and v not in (None, "", [], {})]
            name = type(value).__name__
            return f"{name}({'; '.join(parts)})" if parts else name
        return str(value)

    def _confirm_revalidation(self, *, key: str, old_value: object, new_value: object,
                              old_evidence: str | None, new_evidence: str | None,
                              old_date: str | None, new_date: str | None) -> bool:
        """Explicit revalidation gate: needs_review -> verified only by confirm.

        Shows previous vs current value and previous vs current evidence so
        old evidence is never silently recycled for a different value.
        Separated for tests (patchable).
        """
        result = {"confirmed": False}
        w = tk.Toplevel(self.window)
        w.title(self._t("technical_profile.revalidate_title"))
        w.transient(self.window)
        w.configure(background=PALETTE["surface"])
        w.geometry("560x420")
        w.resizable(False, False)
        w.protocol("WM_DELETE_WINDOW", w.destroy)
        w.bind("<Escape>", lambda _e: w.destroy())
        frame = ttk.Frame(w, style="Form.TFrame", padding=20)
        frame.grid(row=0, column=0, sticky="nsew")
        frame.columnconfigure(1, weight=1)
        ttk.Label(frame, text=self._t("technical_profile.revalidate_intro"),
                  style="Form.TLabel", wraplength=500).grid(row=0, column=0, columnspan=2, sticky="w", pady=(0, 10))
        rows = (
            (self._t("technical_profile.revalidate_old_value"), self._disp_value(old_value)),
            (self._t("technical_profile.revalidate_new_value"), self._disp_value(new_value)),
            (self._t("technical_profile.revalidate_old_evidence"),
             f"{old_evidence or '—'}" + (f" ({old_date})" if old_date else "")),
            (self._t("technical_profile.revalidate_new_evidence"),
             f"{new_evidence or '—'}" + (f" ({new_date})" if new_date else "")),
        )
        for i, (label, val) in enumerate(rows, start=1):
            ttk.Label(frame, text=label, style="Form.TLabel").grid(row=i, column=0, sticky="w", pady=2)
            ttk.Label(frame, text=val, style="Form.TLabel", wraplength=340).grid(row=i, column=1, sticky="w", pady=2)
        same_evidence = (old_evidence or "") == (new_evidence or "") and old_evidence
        note_key = ("technical_profile.revalidate_note_same_evidence"
                    if same_evidence else "technical_profile.revalidate_note_new_evidence")
        ttk.Label(frame, text=self._t(note_key), style="Form.TLabel",
                  wraplength=500).grid(row=5, column=0, columnspan=2, sticky="w", pady=(10, 10))

        def on_confirm() -> None:
            result["confirmed"] = True
            w.destroy()

        actions = ttk.Frame(frame, style="Form.TFrame")
        actions.grid(row=6, column=0, columnspan=2, sticky="e")
        ttk.Button(actions, text=self._t("technical_profile.cancel"), style="Secondary.TButton",
                   command=w.destroy).grid(row=0, column=0, padx=(0, 8))
        ttk.Button(actions, text=self._t("technical_profile.revalidate_confirm"),
                   style="Primary.TButton", command=on_confirm).grid(row=0, column=1)
        w.grab_set()
        self.window.wait_window(w)
        return result["confirmed"]

    def _on_save(self) -> None:
        attrs: list[TechnicalAttribute] = []
        for key, row in self._rows.items():
            if not row["enabled"].get():
                continue
            try:
                value = self._read_value(row["value"], row["spec"])
                if value is None or value == "" or (value == [] and row["value"][0] != "typed_object_list"):
                    raise TechnicalProfileValidationError(self._t("technical_profile.errors.required_value"))
                unit = None
                units = [u for u in row["spec"].allowed_units if u]
                if units and row["spec"].value_type in ("int", "int_non_negative"):
                    unit = units[0]
                verification = self._label_to_verification(row["verification"].get())
                evidence = row["evidence"].get().strip() or None
                verified_at = row["verified_at"].get().strip() or None
                existing = row.get("existing")
                old_value = getattr(existing, "value", None) if existing is not None else None
                old_unit = getattr(existing, "unit", None) if existing is not None else None
                changed = existing is not None and not _values_equal(old_value, old_unit, value, unit)
                if changed:
                    if verification == "verified":
                        # Changed value re-verified in the same save: the old
                        # and new value AND the old and new evidence are shown
                        # together and require an explicit confirmation.
                        if not self._confirm_revalidation(
                            key=key,
                            old_value=old_value,
                            new_value=value,
                            old_evidence=getattr(existing, "evidence_ref", None),
                            new_evidence=evidence,
                            old_date=getattr(existing, "verified_at", None),
                            new_date=verified_at,
                        ):
                            return
                    else:
                        # Any value change voids a previous verification and may
                        # never settle back to plain unverified: that would let a
                        # later silent re-verify launder the old verification.
                        verification = "needs_review"
                elif (verification == "verified" and existing is not None
                        and getattr(existing, "verification_status", None) == "needs_review"):
                    # needs_review -> verified requires explicit revalidation:
                    # old evidence is never recycled silently for a new value.
                    if not self._confirm_revalidation(
                        key=key,
                        old_value=getattr(existing, "value", None),
                        new_value=value,
                        old_evidence=getattr(existing, "evidence_ref", None),
                        new_evidence=evidence,
                        old_date=getattr(existing, "verified_at", None),
                        new_date=verified_at,
                    ):
                        return
                if verification == "verified" and (not evidence or not verified_at):
                    raise TechnicalProfileValidationError(self._t("technical_profile.errors.verified_requires_evidence"))
                completeness = "unknown"
                scope = None
                if row.get("completeness") is not None:
                    completeness = self._label_to_completeness(row["completeness"].get())
                    scope = row["scope"].get().strip() or None
                    if completeness == "complete":
                        if verification != "verified":
                            raise TechnicalProfileValidationError(self._t("technical_profile.errors.completeness_requires_verified"))
                        if self._label_to_confidence(row["confidence"].get()) != "high":
                            raise TechnicalProfileValidationError(self._t("technical_profile.errors.completeness_requires_high_confidence"))
                        if not evidence or not verified_at:
                            raise TechnicalProfileValidationError(self._t("technical_profile.errors.verified_requires_evidence"))
                        if not scope:
                            raise TechnicalProfileValidationError(self._t("technical_profile.errors.completeness_requires_scope"))
                    elif completeness == "partial":
                        if not scope:
                            raise TechnicalProfileValidationError(self._t("technical_profile.errors.completeness_requires_scope"))
                    else:
                        if scope:
                            raise TechnicalProfileValidationError(self._t("technical_profile.errors.completeness_unknown_no_scope"))
                attrs.append(
                    TechnicalAttribute(
                        key=key,
                        value=value,
                        unit=unit,
                        original_value=row["original"].get().strip() or None,
                        source=self._label_to_source(row["source"].get()),
                        confidence=self._label_to_confidence(row["confidence"].get()),
                        verification_status=verification,
                        evidence_ref=evidence,
                        verified_at=verified_at,
                        collection_completeness=completeness,
                        completeness_scope=scope,
                    )
                )
            except TechnicalProfileValidationError as exc:
                messagebox.showerror(self._t("technical_profile.errors.validation_title"), str(exc), parent=self.window)
                return
            except Exception as exc:
                messagebox.showerror(self._t("technical_profile.errors.validation_title"), str(exc), parent=self.window)
                return
        try:
            self.result = TechnicalProfile(component_id=self.component_id, profile_version=PROFILE_VERSION, attributes=attrs)
        except TechnicalProfileValidationError as exc:
            messagebox.showerror(self._t("technical_profile.errors.validation_title"), str(exc), parent=self.window)
            return
        self.window.destroy()

    def _on_cancel(self) -> None:
        self.result = None
        self.window.destroy()

    # --- typed_object_list editors (T17.7b, no JSON manual, transactional at profile save) ---
    def _typed_summary(self, spec, item) -> str:
        try:
            if spec.schema_id == "M2SlotSpec" or hasattr(item, "slot_id"):
                return f"{getattr(item,'slot_id','?')} | {','.join(getattr(item,'supported_modes',()))} | {','.join(getattr(item,'accepted_module_keyings',()))} | {','.join(getattr(item,'supported_lengths',()))}"
            if spec.schema_id == "PowerConnectorRequirement" or (hasattr(item, "connector_kind") and hasattr(item, "quantity")):
                req = "req" if getattr(item,'required',True) else "opt"
                return f"{getattr(item,'connector_kind','?')} x{getattr(item,'quantity','?')} ({req})"
            if spec.schema_id == "PowerCableAssembly" or hasattr(item, "cable_id"):
                ends = getattr(item,'component_side_ends',())
                return f"{getattr(item,'cable_id','?')} [{getattr(item,'assembly_type','?')}] {len(ends)} end(s)"
        except Exception:
            pass
        return str(item)

    def _edit_typed_item(self, spec, existing):
        sid = getattr(spec, "schema_id", None)
        if sid == "M2SlotSpec":
            return self._edit_m2_slot(existing)
        if sid == "PowerConnectorRequirement":
            return self._edit_power_requirement(existing)
        if sid == "PowerCableAssembly":
            return self._edit_power_cable(existing)
        messagebox.showerror(self._t("technical_profile.errors.validation_title"), f"Unsupported schema: {sid}", parent=self.window)
        return None

    def _dialog(self, title):
        w = tk.Toplevel(self.window)
        w.title(title)
        w.transient(self.window)
        w.grab_set()
        w.configure(bg=PALETTE["bg"])
        body = ttk.Frame(w, padding=10)
        body.grid(row=0, column=0, sticky="nsew")
        w.columnconfigure(0, weight=1)
        return w, body

    def _labeled_entry(self, parent, row, label, value=""):
        ttk.Label(parent, text=label).grid(row=row, column=0, sticky="w", pady=2)
        e = ttk.Entry(parent, width=36)
        e.grid(row=row, column=1, sticky="ew", pady=2)
        if value not in (None, ""):
            e.insert(0, str(value))
        return e

    def _labeled_combo(self, parent, row, label, values, value=None):
        ttk.Label(parent, text=label).grid(row=row, column=0, sticky="w", pady=2)
        cb = ttk.Combobox(parent, values=list(values), state="readonly", width=33)
        cb.grid(row=row, column=1, sticky="ew", pady=2)
        if value is not None:
            cb.set(str(value))
        elif values:
            cb.current(0)
        return cb

    def _multi_list(self, parent, row, label, values, selected=()):
        ttk.Label(parent, text=label).grid(row=row, column=0, sticky="nw", pady=2)
        lb = tk.Listbox(parent, selectmode="extended", height=min(6, max(3, len(values))), exportselection=False)
        for v in values:
            lb.insert("end", v)
        selset = set(selected or ())
        for i, v in enumerate(values):
            if v in selset:
                lb.selection_set(i)
        lb.grid(row=row, column=1, sticky="w", pady=2)
        return lb

    def _get_multi(self, lb):
        return [lb.get(i) for i in lb.curselection()]

    def _edit_m2_slot(self, existing):
        w, body = self._dialog(self._t("technical_profile.typed.item") + " - M.2")
        r = 0
        slot = self._labeled_entry(body, r, "slot_id", getattr(existing, "slot_id", "")); r += 1
        keyings = self._multi_list(body, r, "accepted_module_keyings", ["B","M","B_M"], getattr(existing, "accepted_module_keyings", ())); r += 1
        lengths = self._multi_list(body, r, "supported_lengths", ["2230","2242","2260","2280","22110","other"], getattr(existing, "supported_lengths", ())); r += 1
        modes = self._multi_list(body, r, "supported_modes", ["sata_ata","pcie_nvme"], getattr(existing, "supported_modes", ())); r += 1
        gen = self._labeled_entry(body, r, "pcie_generation_max", "" if getattr(existing, "pcie_generation_max", None) is None else existing.pcie_generation_max); r += 1
        lanes = self._labeled_combo(body, r, "pcie_lanes_max", ["", "x1","x2","x4"], getattr(existing, "pcie_lanes_max", "") or ""); r += 1
        routed = self._labeled_combo(body, r, "routed_to", ["unknown","cpu","chipset"], getattr(existing, "routed_to", "unknown")); r += 1
        shared = self._labeled_entry(body, r, "shared_resource_group_id", getattr(existing, "shared_resource_group_id", "") or ""); r += 1
        disables = self._labeled_entry(body, r, "disables_sata_port_ids (,)", ", ".join(getattr(existing, "disables_sata_port_ids", ()) or ())); r += 1
        notes = self._labeled_entry(body, r, "notes", getattr(existing, "notes", "") or ""); r += 1
        ev = self._labeled_entry(body, r, "evidence_ref", getattr(existing, "evidence_ref", "") or ""); r += 1
        result = {"value": None}
        def ok():
            try:
                g = gen.get().strip()
                d = {"slot_id": slot.get().strip(), "accepted_module_keyings": self._get_multi(keyings), "supported_lengths": self._get_multi(lengths), "supported_modes": self._get_multi(modes), "pcie_generation_max": int(g) if g else None, "pcie_lanes_max": lanes.get().strip() or None, "routed_to": routed.get().strip() or "unknown", "shared_resource_group_id": shared.get().strip() or None, "disables_sata_port_ids": [s.strip() for s in disables.get().replace(";", ",").split(",") if s.strip()], "notes": notes.get().strip() or None, "evidence_ref": ev.get().strip() or None}
                result["value"] = M2SlotSpec.from_dict(d)
                w.destroy()
            except Exception as exc:
                messagebox.showerror(self._t("technical_profile.errors.validation_title"), str(exc), parent=w)
        btns = ttk.Frame(body); btns.grid(row=r, column=0, columnspan=2, pady=(8,0))
        ttk.Button(btns, text="OK", command=ok).pack(side="left", padx=4)
        ttk.Button(btns, text=self._t("technical_profile.cancel"), command=w.destroy).pack(side="left", padx=4)
        self.window.wait_window(w)
        return result["value"]

    def _edit_power_requirement(self, existing):
        w, body = self._dialog(self._t("technical_profile.typed.item") + " - Power connector")
        r = 0
        kind = self._labeled_combo(body, r, "connector_kind", ["ATX_20","ATX_24","EPS_4","EPS_8","PCIE_6","PCIE_8","12VHPWR","12V_2x6"], getattr(existing, "connector_kind", "ATX_24")); r += 1
        qty = self._labeled_entry(body, r, "quantity", getattr(existing, "quantity", 1)); r += 1
        reqv = tk.BooleanVar(value=bool(getattr(existing, "required", True)))
        ttk.Checkbutton(body, text="required", variable=reqv).grid(row=r, column=1, sticky="w", pady=2); r += 1
        notes = self._labeled_entry(body, r, "notes", getattr(existing, "notes", "") or ""); r += 1
        result = {"value": None}
        def ok():
            try:
                result["value"] = PowerConnectorRequirement.from_dict({"connector_kind": kind.get().strip(), "quantity": int(qty.get().strip()), "required": bool(reqv.get()), "notes": notes.get().strip() or None})
                w.destroy()
            except Exception as exc:
                messagebox.showerror(self._t("technical_profile.errors.validation_title"), str(exc), parent=w)
        btns = ttk.Frame(body); btns.grid(row=r, column=0, columnspan=2, pady=(8,0))
        ttk.Button(btns, text="OK", command=ok).pack(side="left", padx=4)
        ttk.Button(btns, text=self._t("technical_profile.cancel"), command=w.destroy).pack(side="left", padx=4)
        self.window.wait_window(w)
        return result["value"]

    def _edit_power_cable(self, existing):
        w, body = self._dialog(self._t("technical_profile.typed.item") + " - Power cable")
        r = 0
        cid = self._labeled_entry(body, r, "cable_id", getattr(existing, "cable_id", "")); r += 1
        atype = self._labeled_combo(body, r, "assembly_type", ["fixed_native","modular_native","manufacturer_approved_adapter","third_party_adapter","unknown"], getattr(existing, "assembly_type", "fixed_native")); r += 1
        psu_side = self._labeled_entry(body, r, "psu_side_connector_id", getattr(existing, "psu_side_connector_id", "") or ""); r += 1
        approved_model = self._labeled_entry(body, r, "approved_psu_model", getattr(existing, "approved_psu_model", "") or ""); r += 1
        approval_ref = self._labeled_entry(body, r, "approval_reference", getattr(existing, "approval_reference", "") or ""); r += 1
        notes = self._labeled_entry(body, r, "notes", getattr(existing, "notes", "") or ""); r += 1
        ttk.Label(body, text="component_side_ends").grid(row=r, column=0, sticky="nw", pady=2)
        ends_frame = ttk.Frame(body); ends_frame.grid(row=r, column=1, sticky="ew", pady=2); r += 1
        ends_lb = tk.Listbox(ends_frame, height=4, width=42, exportselection=False)
        ends_lb.grid(row=0, column=0, rowspan=3, sticky="w")
        ends = [e.copy() if hasattr(e, "copy") else e for e in (getattr(existing, "component_side_ends", ()) or ())]
        def refresh_ends():
            ends_lb.delete(0, "end")
            for e in ends:
                sg = f" grp={e.split_group_id}" if getattr(e,'split_group_id',None) else ""
                ends_lb.insert("end", f"{e.end_id}: {e.connector_kind}{sg}")
        def add_end():
            e = self._edit_cable_end(None)
            if e: ends.append(e); refresh_ends()
        def edit_end():
            sel = ends_lb.curselection()
            if not sel: return
            e = self._edit_cable_end(ends[sel[0]])
            if e: ends[sel[0]] = e; refresh_ends()
        def del_end():
            sel = ends_lb.curselection()
            if sel: del ends[sel[0]]; refresh_ends()
        ttk.Button(ends_frame, text=self._t("technical_profile.typed.add"), command=add_end).grid(row=0,column=1,padx=4)
        ttk.Button(ends_frame, text=self._t("technical_profile.typed.edit"), command=edit_end).grid(row=1,column=1,padx=4)
        ttk.Button(ends_frame, text=self._t("technical_profile.typed.remove"), command=del_end).grid(row=2,column=1,padx=4)
        refresh_ends()
        result = {"value": None}
        def ok():
            try:
                d = {"cable_id": cid.get().strip(), "assembly_type": atype.get().strip(), "psu_side_connector_id": psu_side.get().strip() or None, "approved_psu_model": approved_model.get().strip() or None, "approval_reference": approval_ref.get().strip() or None, "notes": notes.get().strip() or None, "component_side_ends": [e.to_dict() if hasattr(e,'to_dict') else e for e in ends]}
                result["value"] = PowerCableAssembly.from_dict(d)
                w.destroy()
            except Exception as exc:
                messagebox.showerror(self._t("technical_profile.errors.validation_title"), str(exc), parent=w)
        btns = ttk.Frame(body); btns.grid(row=r, column=0, columnspan=2, pady=(8,0))
        ttk.Button(btns, text="OK", command=ok).pack(side="left", padx=4)
        ttk.Button(btns, text=self._t("technical_profile.cancel"), command=w.destroy).pack(side="left", padx=4)
        self.window.wait_window(w)
        return result["value"]

    def _edit_cable_end(self, existing):
        w, body = self._dialog(self._t("technical_profile.typed.item") + " - Cable end")
        r = 0
        eid = self._labeled_entry(body, r, "end_id", getattr(existing, "end_id", "")); r += 1
        kind = self._labeled_combo(body, r, "connector_kind", ["ATX_20","ATX_24","EPS_4","EPS_8","PCIE_6","PCIE_8","12VHPWR","12V_2x6"], getattr(existing, "connector_kind", "PCIE_8")); r += 1
        grp = self._labeled_entry(body, r, "split_group_id", getattr(existing, "split_group_id", "") or ""); r += 1
        result = {"value": None}
        def ok():
            try:
                result["value"] = PowerCableEndSpec.from_dict({"end_id": eid.get().strip(), "connector_kind": kind.get().strip(), "split_group_id": grp.get().strip() or None})
                w.destroy()
            except Exception as exc:
                messagebox.showerror(self._t("technical_profile.errors.validation_title"), str(exc), parent=w)
        btns = ttk.Frame(body); btns.grid(row=r, column=0, columnspan=2, pady=(8,0))
        ttk.Button(btns, text="OK", command=ok).pack(side="left", padx=4)
        ttk.Button(btns, text=self._t("technical_profile.cancel"), command=w.destroy).pack(side="left", padx=4)
        self.window.wait_window(w)
        return result["value"]
