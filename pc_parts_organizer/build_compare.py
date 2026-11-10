"""Build-to-build comparison (T17.14). Pure and deterministic.

Compares two builds by component identity (persistent UUIDs), never by
textual similarity. A is always the reference, B the compared build.
No persistence, no mutation, no I/O. Compatibility analysis itself stays in
compatibility/; this module only pairs findings from two fresh reports.
"""

from __future__ import annotations

from dataclasses import dataclass, field

UNCHANGED = "unchanged"
ADDED = "added"
REMOVED = "removed"
REPLACED = "replaced"
UNKNOWN = "unknown"

COMPONENT_STATES = (UNCHANGED, ADDED, REMOVED, REPLACED, UNKNOWN)

# General fields with hardware meaning on both sides. Inventory metadata
# (status/location/purchase) is intentionally not compared.
GENERAL_FIELDS = ("category", "manufacturer", "model", "specifications")


def _comp_label(component) -> str:
    parts = [str(getattr(component, "manufacturer", "") or "").strip(),
             str(getattr(component, "model", "") or "").strip()]
    return " ".join(p for p in parts if p) or str(getattr(component, "id", ""))


def _attr_value(attr):
    v = getattr(attr, "value", None)
    if isinstance(v, (list, tuple)):
        return tuple(v)
    return v


@dataclass(frozen=True)
class AttributeDiff:
    key: str
    status: str  # equal|different|missing_a|missing_b
    value_a: object = None
    value_b: object = None
    unit_a: object = None
    unit_b: object = None
    meta_differs: bool = False


@dataclass
class ComponentDiff:
    state: str
    category: str
    component_a: object = None
    component_b: object = None
    field_diffs: dict = field(default_factory=dict)
    attribute_diffs: tuple = ()


@dataclass
class HardwareDiff:
    items: tuple = ()
    common_count: int = 0
    added_count: int = 0
    removed_count: int = 0
    replaced_count: int = 0
    unknown_count: int = 0
    tech_changes: int = 0


def _compare_general(ca, cb) -> dict:
    diffs = {}
    for f in GENERAL_FIELDS:
        va = getattr(ca, f, "")
        vb = getattr(cb, f, "")
        if (va or "") != (vb or ""):
            diffs[f] = (va, vb)
    return diffs


def _compare_profiles(pa, pb) -> tuple:
    aa = {a.key: a for a in (getattr(pa, "attributes", []) or [])} if pa is not None else {}
    ab = {b.key: b for b in (getattr(pb, "attributes", []) or [])} if pb is not None else {}
    out = []
    for key in sorted(set(aa) | set(ab)):
        a = aa.get(key)
        b = ab.get(key)
        if a is None:
            out.append(AttributeDiff(key, "missing_a", None, _attr_value(b),
                                     None, getattr(b, "unit", None)))
        elif b is None:
            out.append(AttributeDiff(key, "missing_b", _attr_value(a), None,
                                     getattr(a, "unit", None), None))
        else:
            same = _attr_value(a) == _attr_value(b) and getattr(a, "unit", None) == getattr(b, "unit", None)
            meta = (a.source != b.source or a.confidence != b.confidence
                    or a.verification_status != b.verification_status
                    or (a.evidence_ref or "") != (b.evidence_ref or "")
                    or (a.verified_at or "") != (b.verified_at or ""))
            out.append(AttributeDiff(key, "equal" if same else "different",
                                     _attr_value(a), _attr_value(b),
                                     getattr(a, "unit", None), getattr(b, "unit", None),
                                     meta_differs=meta))
    return tuple(out)


def _is_modified(ca, cb, pa, pb) -> tuple[bool, dict, tuple]:
    fields = _compare_general(ca, cb)
    attrs = _compare_profiles(pa, pb)
    changed = bool(fields) or any(d.status == "different" for d in attrs)
    return changed, fields, attrs


def compare_hardware(build_a, build_b, components_by_id, profiles_by_id) -> HardwareDiff:
    """Pair components across two builds. Deterministic; order-independent."""
    ids_a = list(getattr(build_a, "component_ids", []) or [])
    ids_b = list(getattr(build_b, "component_ids", []) or [])
    set_a, set_b = set(ids_a), set(ids_b)
    items: list[ComponentDiff] = []

    for cid in sorted(set_a & set_b):
        # Same persistent identity resolves to the same live data on both
        # sides: always UNCHANGED in a single snapshot. MODIFIED was removed
        # from the contract (T17.15): no snapshots exist, so divergence is
        # unrepresentable and the state could never fire.
        ca = components_by_id.get(cid)
        items.append(ComponentDiff(UNCHANGED,
                                   getattr(ca, "category", "") if ca else "",
                                   ca, ca, {}, ()))

    only_a = sorted(set_a - set_b)
    only_b = sorted(set_b - set_a)

    def cat_of(cid):
        c = components_by_id.get(cid)
        return getattr(c, "category", "") if c is not None else ""

    cats_a: dict[str, list] = {}
    for cid in only_a:
        cats_a.setdefault(cat_of(cid), []).append(cid)
    cats_b: dict[str, list] = {}
    for cid in only_b:
        cats_b.setdefault(cat_of(cid), []).append(cid)

    for cat in sorted(set(cats_a) | set(cats_b)):
        ra = cats_a.get(cat, [])
        rb = cats_b.get(cat, [])
        if cat in cats_a and cat not in cats_b:
            for cid in ra:
                items.append(ComponentDiff(REMOVED, cat, components_by_id.get(cid), None))
        elif cat in cats_b and cat not in cats_a:
            for cid in rb:
                items.append(ComponentDiff(ADDED, cat, None, components_by_id.get(cid)))
        elif len(ra) == 1 and len(rb) == 1:
            ca, cb = components_by_id.get(ra[0]), components_by_id.get(rb[0])
            _, fields, attrs = _is_modified(ca, cb, profiles_by_id.get(ra[0]), profiles_by_id.get(rb[0])) \
                if ca is not None and cb is not None else ({}, {}, ())
            items.append(ComponentDiff(REPLACED, cat, ca, cb, fields, attrs))
        else:
            # Ambiguous multiplicity: never pair by position.
            for cid in ra:
                items.append(ComponentDiff(UNKNOWN, cat, components_by_id.get(cid), None))
            for cid in rb:
                items.append(ComponentDiff(UNKNOWN, cat, None, components_by_id.get(cid)))

    items.sort(key=lambda i: (
        str(i.category),
        i.state,
        _comp_label(i.component_a or i.component_b) if (i.component_a or i.component_b) else ""))

    def count(s):
        return sum(1 for i in items if i.state == s)

    tech = 0
    for i in items:
        if i.state == REPLACED:
            tech += len(i.field_diffs) + sum(1 for d in i.attribute_diffs if d.status == "different")
        tech += sum(1 for d in i.attribute_diffs if d.status in ("missing_a", "missing_b"))
    return HardwareDiff(
        items=tuple(items),
        common_count=count(UNCHANGED),
        added_count=count(ADDED),
        removed_count=count(REMOVED),
        replaced_count=count(REPLACED),
        unknown_count=count(UNKNOWN),
        tech_changes=tech,
    )


def correspondence_from_hardware(hw) -> dict:
    """Explicit A<->B participant map from demonstrated hardware pairings.

    Only UNCHANGED identities and unequivocal 1:1 REPLACED pairs produce
    correspondences. ADDED/REMOVED/UNKNOWN never map: sharing a category
    alone is not a correspondence.
    """
    shared: set = set()
    pair_of: dict = {}
    for i in hw.items or ():
        ca, cb = getattr(i, "component_a", None), getattr(i, "component_b", None)
        ida = getattr(ca, "id", None) if ca is not None else None
        idb = getattr(cb, "id", None) if cb is not None else None
        if i.state == UNCHANGED and ida is not None:
            shared.add(ida)
        elif i.state == REPLACED and ida is not None and idb is not None:
            pair_of[ida] = idb
            pair_of[idb] = ida
    return {"shared": shared, "pair_of": pair_of}


# --- compatibility report comparison ---

@dataclass(frozen=True)
class FindingPair:
    status: str  # same|resolved|new_issue|changed
    key: tuple = ()
    finding_a: object = None
    finding_b: object = None
    explanation: str = "config_changed"


@dataclass
class CompatDiff:
    pairs: tuple = ()
    new_count: int = 0
    resolved_count: int = 0
    changed_count: int = 0


def _token_of_factory(corr, ids_a=(), ids_b=()):
    """token(cid, side) -> canonical cross-side token.

    shared identity -> ("id", cid); unequivocal replacement pair ->
    ("pair", lo, hi) identical on both sides; anything else ->
    ("solo", side, cid), which can never match across sides. Without an
    explicit map, only persistent ids present on both sides pair (safe
    default derived from the reports themselves).
    """
    if corr is None:
        both = set(ids_a) & set(ids_b)
        shared, pair_of = both, {}
    else:
        shared = set(corr.get("shared", ()))
        pair_of = dict(corr.get("pair_of", {}))

    def token(cid, side):
        if cid in shared:
            return ("id", cid)
        other = pair_of.get(cid)
        if other is not None:
            lo, hi = (cid, other) if str(cid) <= str(other) else (other, cid)
            return ("pair", lo, hi)
        return ("solo", side, cid)

    return token


def _key_for(f, side, token_of):
    cids = list(getattr(f, "component_ids", ()) or ())
    return (getattr(f, "rule_id", ""), tuple(sorted(token_of(c, side) for c in cids)))


def _ids_of(report):
    out = []
    for f in getattr(report, "findings", ()) or ():
        out.extend(getattr(f, "component_ids", ()) or ())
    return out


def compare_reports(report_a, report_b, corr=None) -> CompatDiff:
    """Pair findings by demonstrated participant correspondence.

    The correspondence map comes from correspondence_from_hardware():
    {"shared": {...}, "pair_of": {...}}. Findings whose participants have
    no demonstrated correspondence never pair (shown independent).
    Pairing is positional only within an identical-key group; order of
    findings and of participants never influences the outcome.
    Direction matters (A is the reference).
    """
    token_of = _token_of_factory(
        corr, _ids_of(report_a), _ids_of(report_b))
    fa = sorted(getattr(report_a, "findings", ()) or (),
                key=lambda f: (_key_for(f, "A", token_of), str(getattr(f, "result", ""))))
    fb = sorted(getattr(report_b, "findings", ()) or (),
                key=lambda f: (_key_for(f, "B", token_of), str(getattr(f, "result", ""))))
    groups_a: dict[tuple, list] = {}
    for f in fa:
        groups_a.setdefault(_key_for(f, "A", token_of), []).append(f)
    groups_b: dict[tuple, list] = {}
    for f in fb:
        groups_b.setdefault(_key_for(f, "B", token_of), []).append(f)

    pairs: list[FindingPair] = []
    insufficient_b = {_key_for(f, "B", token_of) for f in fb if getattr(f, "result", "") == "insufficient_data"}
    for key in sorted(set(groups_a) | set(groups_b)):
        la, lb = groups_a.get(key, []), groups_b.get(key, [])
        n = max(len(la), len(lb))
        for i in range(n):
            a = la[i] if i < len(la) else None
            b = lb[i] if i < len(lb) else None
            if a is not None and b is not None:
                ra, rb = getattr(a, "result", ""), getattr(b, "result", "")
                if ra == rb:
                    pairs.append(FindingPair("same", key, a, b, "unchanged"))
                else:
                    pairs.append(FindingPair("changed", key, a, b, _explain_change(a, b, insufficient_b, key)))
            elif a is not None:
                pairs.append(FindingPair("resolved", key, a, None, _explain_resolved(a, insufficient_b, key)))
            else:
                pairs.append(FindingPair("new_issue", key, None, b, _explain_new(b, insufficient_b, key)))

    pairs.sort(key=lambda p: (p.status, str(p.key)))
    return CompatDiff(
        pairs=tuple(pairs),
        new_count=sum(1 for p in pairs if p.status == "new_issue"),
        resolved_count=sum(1 for p in pairs if p.status == "resolved"),
        changed_count=sum(1 for p in pairs if p.status == "changed"),
    )


def _explain_change(a, b, insufficient_b, key) -> str:
    ra, rb = getattr(a, "result", ""), getattr(b, "result", "")
    # Missing data anywhere in the pair vetoes any improvement/regression claim.
    if key in insufficient_b or "insufficient_data" in (ra, rb):
        return "info_loss_possible"
    # Only decisive-to-decisive transitions may claim (im)provement:
    # requires_verification is unverified by definition.
    if ra == "incompatible" and rb == "compatible":
        return "improvement_demonstrated"
    if ra == "compatible" and rb == "incompatible":
        return "regression_demonstrated"
    return "config_changed"


def _explain_resolved(a, insufficient_b, key) -> str:
    # A disappeared finding is not automatically an improvement: the B side
    # may simply lack the data (or the participants) to evaluate it.
    # Group-level info loss (same key insufficient in B) is explicit loss.
    if key in insufficient_b:
        return "info_loss_possible"
    if getattr(a, "result", "") == "incompatible":
        return "improvement_or_info_loss"
    return "config_changed"


def _explain_new(b, insufficient_b, key) -> str:
    # Same veto for leftovers in a group that already shows info loss.
    if key in insufficient_b:
        return "info_loss_possible"
    if getattr(b, "result", "") == "incompatible":
        return "regression_demonstrated"
    return "config_changed"
