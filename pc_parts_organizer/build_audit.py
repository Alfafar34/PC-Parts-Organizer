"""Per-build technical audit (T17.18). Pure and deterministic.

Derives a structured audit from a fresh compatibility report plus the
build's technical profiles. Never re-evaluates rules, never invents
causes, never scores. Findings are grouped; attributes are linked to
findings only through demonstrated relations (CONSUMERS rules,
missing_information tokens, real participants).
"""

from __future__ import annotations

from dataclasses import dataclass, field

from pc_parts_organizer.data_quality import (
    CONSUMERS,
    INCONSISTENT_METADATA,
    LOW_CONFIDENCE,
    MISSING_EVIDENCE,
    UNKNOWN,
    UNVERIFIED,
    audit_inventory,
    classify_attribute,
)
from pc_parts_organizer.technical_profiles import ATTRIBUTE_REGISTRY

PENDING_STATES = (UNVERIFIED, LOW_CONFIDENCE, MISSING_EVIDENCE, UNKNOWN, INCONSISTENT_METADATA)


@dataclass(frozen=True)
class LinkedAttribute:
    component_id: str
    category: str
    key: str
    status: str
    direct: bool  # True: missing_information names it; False: shared rule context
    rule_id: str = ""


@dataclass(frozen=True)
class AuditFinding:
    finding: object
    linked: tuple = ()


@dataclass
class BuildAudit:
    demonstrated: tuple = ()      # AuditFinding(result=incompatible)
    pending_verification: tuple = ()  # AuditFinding(result=requires_verification)
    insufficient: tuple = ()      # AuditFinding(result=insufficient_data)
    not_evaluated: tuple = ()
    limitations: tuple = ()
    relevant_pending: tuple = ()  # LinkedAttribute, blocking current analysis
    future_pending: tuple = ()    # LinkedAttribute, not blocking now
    inconsistent: tuple = ()      # LinkedAttribute with inconsistent metadata
    evaluated_rules: tuple = ()
    rules_evaluated: int = 0
    global_result: str = ""


def _parse_missing_token(token: str) -> tuple[str | None, str | None, str | None]:
    """Parse missing_information tokens like 'ram.memory_generation',
    'gpu[<id>].card_length_mm', 'case'. Returns (category, key, comp_id|None).
    Bare scope ids ('single_case', 'motherboard') carry no attribute reference."""
    import re
    if not isinstance(token, str) or not token:
        return None, None, None
    m = re.match(r"^([A-Za-z_]+)(?:\[([^\]]+)\])?\.([A-Za-z0-9_]+)$", token.strip())
    if not m:
        return None, None, None
    return m.group(1).lower(), m.group(3), m.group(2)


def _canonical_category(raw: str, categories: set[str]) -> str | None:
    for c in categories:
        if c.lower() == raw:
            return c
    return None


def _rules_for_attribute(category: str, key: str) -> tuple:
    return tuple(CONSUMERS.get((category, key), ()))


def _invert_consumers() -> dict[str, list]:
    inv: dict[str, list] = {}
    for (cat, key), rules in CONSUMERS.items():
        for r in rules:
            inv.setdefault(r, []).append((cat, key))
    return inv


def build_audit(build, components_by_id: dict, profiles_by_id: dict, report) -> BuildAudit:
    """Build the audit from live inputs. No I/O, no mutation."""
    comp_ids = [str(c) for c in (getattr(build, "component_ids", None) or [])]
    comp_ids = [c for c in comp_ids if c in components_by_id]
    categories = {getattr(components_by_id[c], "category", "") for c in comp_ids}
    findings = list(getattr(report, "findings", ()) or ())
    evaluated = sorted({str(getattr(f, "rule_id", "")) for f in findings if getattr(f, "rule_id", "")})
    rules_by_attr = _invert_consumers()

    demonstrated: list[AuditFinding] = []
    pending: list[AuditFinding] = []
    insufficient: list[AuditFinding] = []
    seen: set[int] = set()

    for f in findings:
        key = (str(getattr(f, "rule_id", "")), tuple(getattr(f, "component_ids", ()) or ()))
        if id(f) in seen:
            continue
        seen.add(id(f))
        result = getattr(f, "result", "")
        linked = _link_finding(f, comp_ids, components_by_id, profiles_by_id, rules_by_attr, categories)
        entry = AuditFinding(finding=f, linked=tuple(linked))
        if result == "incompatible":
            demonstrated.append(entry)
        elif result == "requires_verification":
            pending.append(entry)
        elif result == "insufficient_data":
            insufficient.append(entry)
        # compatible findings need no audit action

    # relevant pending attributes: consumed by evaluated rules that did NOT
    # reach a compatible verdict (a compatible rule has already decided, so
    # its other pending attributes are not blocking it).
    blocking_rules = set()
    for f in findings:
        if getattr(f, "result", "") in ("incompatible", "requires_verification", "insufficient_data"):
            blocking_rules.add(str(getattr(f, "rule_id", "")))
    relevant: dict[tuple, LinkedAttribute] = {}
    evaluated_set = set(evaluated)
    for e in audit_inventory([components_by_id[c] for c in comp_ids],
                             {c: profiles_by_id[c] for c in comp_ids if c in profiles_by_id}).entries:
        if e.status not in PENDING_STATES and e.status != "absent":
            continue
        rules = [r for r in _rules_for_attribute(e.category, e.key) if r in blocking_rules]
        if not rules:
            continue
        for r in rules:
            direct = any(
                f is not None and getattr(f, "rule_id", "") == r
                and _names_attribute(getattr(f, "missing_information", None), e.category, e.key, categories, e.component_id)
                for f in findings)
            relevant[(e.component_id, e.key, r)] = LinkedAttribute(
                e.component_id, e.category, e.key, e.status, direct, r)

    future: dict[tuple, LinkedAttribute] = {}
    for e in audit_inventory([components_by_id[c] for c in comp_ids],
                             {c: profiles_by_id.get(c) for c in comp_ids}).entries:
        if e.status not in PENDING_STATES and e.status != "absent":
            continue
        rules = [r for r in _rules_for_attribute(e.category, e.key) if r not in evaluated_set]
        for r in rules:
            future[(e.component_id, e.key, r)] = LinkedAttribute(
                e.component_id, e.category, e.key, e.status, False, r)

    inconsistent = [a for a in list(relevant.values()) + list(future.values())
                    if a.status == INCONSISTENT_METADATA]
    # deduplicate: same attribute pending under several rules counts once per (attr, rule)
    return BuildAudit(
        demonstrated=tuple(demonstrated),
        pending_verification=tuple(pending),
        insufficient=tuple(insufficient),
        not_evaluated=tuple(getattr(report, "not_evaluated_relations", ()) or ()),
        limitations=tuple(getattr(report, "analysis_limitations", ()) or ()),
        relevant_pending=tuple(relevant.values()),
        future_pending=tuple(future.values()),
        inconsistent=tuple(inconsistent),
        evaluated_rules=tuple(evaluated),
        rules_evaluated=int(getattr(report, "rules_evaluated", 0) or 0),
        global_result=str(getattr(report, "overall_result", "") or ""),
    )


def _names_attribute(missing, category: str, key: str, categories: set[str], component_id: str | None = None) -> bool:
    for tok in missing or ():
        cat_raw, k, cid = _parse_missing_token(tok)
        if cat_raw is None:
            continue
        canon = _canonical_category(cat_raw, categories)
        if canon == category and k == key and (cid is None or component_id is None or cid == component_id):
            return True
    return False


def _link_finding(finding, comp_ids: list, components_by_id: dict,
                  profiles_by_id: dict, rules_by_attr: dict, categories: set) -> list:
    """Link a finding to attributes only through demonstrated relations.

    Direct: missing_information names the exact (category, key); when it
    carries a bracket id, only that component is linked. Context: CONSUMERS
    attributes of the rule, restricted to actual participants when the
    finding names any (whole build only as fallback). Never invents.
    """
    rule_id = str(getattr(finding, "rule_id", "") or "")
    out: list[LinkedAttribute] = []
    seen: set[tuple] = set()
    missing = list(getattr(finding, "missing_information", None) or ())
    participants = [str(c) for c in (getattr(finding, "component_ids", None) or ())]
    participant_cats = {getattr(components_by_id.get(c), "category", "") for c in participants
                        if c in components_by_id}
    participant_cats.discard("")

    for tok in missing:
        cat_raw, key, named_cid = _parse_missing_token(tok)
        if cat_raw is None:
            continue
        cat = _canonical_category(cat_raw, categories)
        if cat is None:
            continue
        spec = ATTRIBUTE_REGISTRY.get(cat, {}).get(key)
        if spec is None:
            continue
        if named_cid is not None:
            # Bracket id: attribute the missing datum to that component only.
            holders = [named_cid] if named_cid in comp_ids and getattr(
                components_by_id.get(named_cid), "category", "") == cat else []
        else:
            holders = [c for c in comp_ids if getattr(components_by_id.get(c), "category", "") == cat]
        for h in holders:
            prof = profiles_by_id.get(h)
            attr = None
            if prof is not None:
                for a in getattr(prof, "attributes", []) or []:
                    if getattr(a, "key", None) == key:
                        attr = a
                        break
            status = classify_attribute(key, attr, spec) if attr is not None else "absent"
            tag = (h, key, rule_id)
            if tag not in seen:
                seen.add(tag)
                out.append(LinkedAttribute(h, cat, key, status, True, rule_id))

    participants_in_build = [c for c in participants if c in comp_ids]
    scope_ids = participants_in_build if participants_in_build else list(comp_ids)
    for cat, key in rules_by_attr.get(rule_id, []):
        # Context requires a demonstrated scope: the finding's participants
        # when it names any; the whole build only as fallback.
        if participants and cat not in participant_cats:
            continue
        for h in scope_ids:
            if getattr(components_by_id.get(h), "category", "") != cat:
                continue
            prof = profiles_by_id.get(h)
            attr = None
            if prof is not None:
                for a in getattr(prof, "attributes", []) or []:
                    if getattr(a, "key", None) == key:
                        attr = a
                        break
            if attr is None:
                continue
            spec = ATTRIBUTE_REGISTRY.get(cat, {}).get(key)
            if spec is None:
                continue
            tag = (h, key, rule_id)
            if tag not in seen:
                seen.add(tag)
                out.append(LinkedAttribute(h, cat, key, classify_attribute(key, attr, spec), False, rule_id))
    out.sort(key=lambda e: (e.component_id, e.key, e.rule_id, not e.direct))
    return out
