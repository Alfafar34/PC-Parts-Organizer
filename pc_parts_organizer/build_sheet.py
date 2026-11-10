"""Exportable build configuration sheets (T17.20).

Renders Markdown (.md) and plain text (.txt) from a fresh compatibility
report plus the technical audit derived from it. Pure presentation:
no second analysis engine, no invented specs, no provenance transfer.
"""

from __future__ import annotations

import re
import tempfile
from pathlib import Path
from typing import Any, Mapping


def sanitize_build_sheet_filename(name: str) -> str:
    """Derive a safe file stem from a build name (no UUID, no private data)."""
    base = re.sub(r"\s+", " ", str(name or "").strip()).strip()
    base = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "", base)
    base = base.strip(" .")
    if not base:
        base = "build"
    if len(base) > 80:
        base = base[:80].rstrip()
    return base or "build"


def _safe_t(translator: Any, key: str) -> str:
    try:
        return translator.t(key)
    except Exception:
        return key


def _comp_label(components_by_id: dict, translator: Any, cid: str) -> str:
    comp = components_by_id.get(cid)
    if comp is None:
        return str(cid)
    try:
        cat = translator.translate_category(getattr(comp, "category", "") or "")
    except Exception:
        cat = getattr(comp, "category", "") or ""
    parts = [str(x).strip() for x in (getattr(comp, "manufacturer", ""), getattr(comp, "model", "")) if str(x).strip()]
    name = " ".join(parts) or str(cid)
    return f"{cat}: {name}" if cat else name


def _fmt_value(value: Any, language: str) -> str:
    if isinstance(value, bool):
        return ("Sí" if language == "es" else "Yes") if value else "No"
    if value is None:
        return "—"
    if hasattr(value, "__dataclass_fields__"):
        # Never leak dataclass repr: summarize structurally.
        fields = []
        try:
            for f in getattr(value, "__dataclass_fields__", {}):
                fields.append(f"{f}={getattr(value, f, '?')}")
        except Exception:
            return type(value).__name__
        return f"{type(value).__name__}({', '.join(fields)})"
    if isinstance(value, (list, tuple)):
        return ", ".join(_fmt_value(v, language) for v in value)
    return str(value)


def _label_or_value(text: Any, components_by_id: dict, translator: Any, language: str) -> str:
    if isinstance(text, str) and text in components_by_id:
        return _comp_label(components_by_id, translator, text)
    return _fmt_value(text, language)


def _render_evidence_lines(ev: Any, components_by_id: dict, translator: Any, language: str, indent: str) -> list[str]:
    """Render evidence without repr leaks or raw component UUIDs."""
    lines: list[str] = []
    if isinstance(ev, Mapping):
        # Audit-style link: {'id': <component>, 'attr': {...}}.
        if set(ev.keys()) == {"id", "attr"} and isinstance(ev.get("id"), str):
            lines.append(f"{indent}- {_comp_label(components_by_id, translator, ev['id'])}:")
            lines.extend(_render_evidence_lines(ev["attr"], components_by_id, translator, language, indent + "  "))
            return lines
        for key, value in ev.items():
            if isinstance(key, str) and key in ("id", "component_id") and isinstance(value, str):
                lines.append(f"{indent}- {_comp_label(components_by_id, translator, value)}")
            elif isinstance(value, Mapping):
                lines.append(f"{indent}- {key}:")
                lines.extend(_render_evidence_lines(value, components_by_id, translator, language, indent + "  "))
            elif isinstance(value, (list, tuple)):
                if not value:
                    lines.append(f"{indent}- {key}: —")
                else:
                    lines.append(f"{indent}- {key}:")
                    for item in value:
                        if isinstance(item, Mapping):
                            lines.extend(_render_evidence_lines(item, components_by_id, translator, language, indent + "  "))
                        else:
                            lines.append(f"{indent}  - {_label_or_value(item, components_by_id, translator, language)}")
            else:
                lines.append(f"{indent}- {key}: {_label_or_value(value, components_by_id, translator, language)}")
        return lines
    if isinstance(ev, (list, tuple)):
        for item in ev:
            if isinstance(item, Mapping):
                lines.extend(_render_evidence_lines(item, components_by_id, translator, language, indent))
            else:
                lines.append(f"{indent}- {_label_or_value(item, components_by_id, translator, language)}")
        return lines
    lines.append(f"{indent}- {_label_or_value(ev, components_by_id, translator, language)}")
    return lines


def _format_finding_message(finding: Any, components_by_id: dict, translator: Any) -> str:
    key = getattr(finding, "message_key", "") or ""
    params = dict(getattr(finding, "message_params", {}) or {})
    safe: dict[str, str] = {}
    lang = getattr(translator, "language", "es")
    for k, v in params.items():
        if isinstance(v, str) and v in components_by_id and (k.endswith("_id") or k == "component_id"):
            safe[k] = _comp_label(components_by_id, translator, v)
        elif isinstance(v, (list, tuple)) and v and all(isinstance(x, str) and x in components_by_id for x in v):
            safe[k] = ", ".join(_comp_label(components_by_id, translator, x) for x in v)
        else:
            safe[k] = _fmt_value(v, lang)
    template = None
    for candidate in (f"compatibility.messages.{key}", key):
        if not key and candidate == "compatibility.messages.":
            continue
        try:
            template = translator.t(candidate)
            break
        except Exception:
            continue
    if template is None:
        tail = "; ".join(f"{k}={safe.get(k, v)}" for k, v in params.items())
        base = _safe_t(translator, "compatibility.finding.unknown_message")
        return f"{base} ({tail})" if tail else base
    try:
        return template.format(**safe)
    except Exception:
        tail = "; ".join(f"{k}={safe.get(k, v)}" for k, v in params.items())
        return f"{template} ({tail})" if tail else template


def render_build_sheet(
    build: Any,
    components_by_id: dict,
    report: Any,
    audit: Any,
    translator: Any,
    *,
    flavor: str = "markdown",
) -> str:
    """Render the sheet reusing the live report + audit. No I/O."""
    md = flavor == "markdown"
    t = lambda k: _safe_t(translator, k)  # noqa: E731
    lang = getattr(translator, "language", "es")
    lines: list[str] = []
    name = getattr(build, "name", "") or t("builds.unnamed")
    kind = getattr(build, "kind", "current")
    kind_label = t("builds.kind_planned" if kind == "planned" else "builds.kind_current")
    notes = (getattr(build, "notes", "") or "").strip() or t("component_detail.empty")
    comp_ids = list(getattr(build, "component_ids", []) or [])

    def h(level: int, text: str) -> str:
        return f"{'#' * level} {text}" if md else text

    def rule(text: str) -> str:
        return "---" if md else ("-" * 40)

    lines.append(h(1, f"{t('builds.title')}: {name}"))
    lines.append(f"{t('builds.kind')}: {kind_label}")
    lines.append(f"{t('builds.components')}: {len(comp_ids)}")
    lines.append(f"{t('builds.notes')}: {notes}")
    lines.append(rule(""))

    lines.append(h(2, t("builds.composition")))
    if not comp_ids:
        lines.append(t("builds.no_components"))
    else:
        groups: dict[str, list[Any]] = {}
        for cid in comp_ids:
            comp = components_by_id.get(cid)
            if comp is None:
                continue
            groups.setdefault(getattr(comp, "category", "Other") or "Other", []).append(comp)
        for cat in sorted(groups, key=lambda c: c.casefold()):
            try:
                cat_label = translator.translate_category(cat)
            except Exception:
                cat_label = cat
            lines.append(f"- {cat_label}:" if not md else f"- **{cat_label}**:")
            for comp in sorted(groups[cat], key=lambda c: (str(getattr(c, "manufacturer", "")).casefold(), str(getattr(c, "model", "")).casefold())):
                maker = str(getattr(comp, "manufacturer", "") or "").strip()
                model = str(getattr(comp, "model", "") or "").strip()
                label = " ".join(p for p in (maker, model) if p) or t("component_detail.empty")
                lines.append(f"  - {label}")
                for field_key, field_label in (("specifications", "component_detail.specifications"), ("notes", "component_detail.notes")):
                    val = str(getattr(comp, field_key, "") or "").strip()
                    if val:
                        lines.append(f"    - {t(field_label)}: {val}")
    lines.append(rule(""))

    overall = getattr(report, "overall_result", "") if report is not None else ""
    lines.append(h(2, t("compatibility.section_title")))
    if report is None:
        lines.append(t("compatibility.not_analyzed"))
    else:
        lines.append(f"{t('compatibility.summary_title')}: {t(f'compatibility.results.{overall}')}")
        lines.append(t(f"compatibility.result_explanations.{overall}"))
        try:
            lines.append(t("compatibility.rules_evaluated").format(count=int(getattr(report, "rules_evaluated", 0) or 0)))
        except Exception:
            pass
        findings = list(getattr(report, "findings", ()) or [])
        for f in findings:
            rule_id = str(getattr(f, "rule_id", ""))
            try:
                rule_label = translator.t(f"compatibility.rule_labels.{rule_id.replace('.', '__')}")
            except Exception:
                rule_label = rule_id
            result = str(getattr(f, "result", ""))
            severity = str(getattr(f, "severity", ""))
            lines.append(f"- {t('compatibility.finding.rule')}: {rule_label}")
            lines.append(f"  {t('compatibility.finding.result')}: {t(f'compatibility.results.{result}')} | "
                         f"{t('compatibility.finding.severity')}: {t(f'compatibility.severity.{severity}')}")
            cids = list(getattr(f, "component_ids", ()) or [])
            if cids:
                lines.append(f"  {t('compatibility.finding.components')}: " + "; ".join(_comp_label(components_by_id, translator, c) for c in cids))
            attrs = list(getattr(f, "attributes_compared", ()) or [])
            if attrs:
                labels = []
                for a in attrs:
                    try:
                        labels.append(translator.t(f"technical_profile.attributes.{a}"))
                    except Exception:
                        labels.append(str(a))
                lines.append(f"  {t('compatibility.finding.attributes')}: " + ", ".join(labels))
            lines.append(f"  {t('compatibility.finding.explanation')}: {_format_finding_message(f, components_by_id, translator)}")
            missing = list(getattr(f, "missing_information", ()) or [])
            if missing:
                lines.append(f"  {t('compatibility.finding.missing')}: " + "; ".join(str(m) for m in missing))
            try:
                action = translator.t(f"compatibility.recommended_actions.{getattr(f, 'recommended_action', '') or ''}")
                if getattr(f, "recommended_action", ""):
                    lines.append(f"  {t('compatibility.finding.recommended')}: {action}")
            except Exception:
                pass
            ev = getattr(f, "evidence", None)
            if isinstance(ev, Mapping) and ev:
                lines.append(f"  {t('compatibility.sections.evidence')}:")
                lines.extend(_render_evidence_lines(ev, components_by_id, translator, lang, "    "))
            lines.append("")
        not_eval = list(getattr(report, "not_evaluated_relations", ()) or [])
        limitations = list(getattr(report, "analysis_limitations", ()) or [])
        lines.append(h(3, t("compatibility.sections.not_evaluated")))
        if not_eval:
            for item in not_eval:
                if isinstance(item, Mapping):
                    cat = str(item.get("category", ""))
                    reason = str(item.get("reason", ""))
                    try:
                        cat_l = translator.translate_category(cat)
                    except Exception:
                        cat_l = cat or "—"
                    try:
                        reason_l = translator.t(f"compatibility.not_evaluated_reason.{reason}") if reason else "—"
                    except Exception:
                        reason_l = reason or "—"
                    lines.append(f"- {cat_l}: {reason_l}")
                else:
                    lines.append(f"- {_fmt_value(item, lang)}")
        else:
            lines.append(f"- {t('compatibility.evidence_labels.not_set')}")
        lines.append(h(3, t("compatibility.sections.limitations")))
        if limitations:
            for lim in sorted(set(str(x) for x in limitations)):
                try:
                    lines.append(f"- {translator.t(f'compatibility.limitations_tokens.{lim}')}")
                except Exception:
                    lines.append(f"- {lim}")
        else:
            lines.append(f"- {t('compatibility.evidence_labels.not_set')}")
        lines.append(t("compatibility.evidence_disclaimer"))
        lines.append(t("compatibility.scope_note"))
    lines.append(rule(""))

    lines.append(h(2, t("build_audit.title")))
    if audit is None:
        lines.append(t("build_audit.no_report"))
    else:
        rel_keys = {(a.component_id, a.key) for a in (getattr(audit, "relevant_pending", ()) or [])}
        inc_keys = {(a.component_id, a.key) for a in (getattr(audit, "inconsistent", ()) or [])}
        try:
            lines.append(t("build_audit.summary").format(
                demonstrated=len(getattr(audit, "demonstrated", ()) or ()),
                pending=len(getattr(audit, "pending_verification", ()) or ()),
                insufficient=len(getattr(audit, "insufficient", ()) or ()),
                not_evaluated=len(getattr(audit, "not_evaluated", ()) or ()),
                relevant=len(rel_keys),
                inconsistent=len(inc_keys),
            ))
        except Exception:
            pass
        pending_sets = [
            (t("build_audit.relevant_title"), getattr(audit, "relevant_pending", ()) or ()),
            (t("build_audit.future_title"), getattr(audit, "future_pending", ()) or ()),
        ]
        for title, attrs in pending_sets:
            if not attrs:
                continue
            lines.append(h(3, title))
            seen_pending: set[tuple] = set()
            for a in attrs:
                tag = (a.component_id, a.key, a.status)
                if tag in seen_pending:
                    continue
                seen_pending.add(tag)
                lines.append(f"- {_comp_label(components_by_id, translator, a.component_id)}: {a.key} [{a.status}]")
        lines.append(t("build_audit.note_no_score"))
    return "\n".join(lines).rstrip() + "\n"


def export_build_sheet(
    build: Any,
    components_by_id: dict,
    report: Any,
    audit: Any,
    translator: Any,
    destination: str | Path,
    *,
    flavor: str = "markdown",
    active_inventory_path: str | Path | None = None,
) -> Path:
    """Write the sheet atomically (temp + replace). Refuses active inventory path."""
    dest = Path(destination)
    if active_inventory_path is not None:
        try:
            if dest.resolve(strict=False) == Path(active_inventory_path).resolve(strict=False):
                raise ValueError("refusing to export over the active inventory file")
        except ValueError:
            raise
        except Exception:
            pass
    text = render_build_sheet(build, components_by_id, report, audit, translator, flavor=flavor)
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = None
    try:
        with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=str(dest.parent), delete=False, suffix=".tmp") as fh:
            tmp = Path(fh.name)
            fh.write(text)
        tmp.replace(dest)
    finally:
        try:
            if tmp is not None and tmp.exists() and tmp != dest:
                tmp.unlink()
        except Exception:
            pass
    return dest
