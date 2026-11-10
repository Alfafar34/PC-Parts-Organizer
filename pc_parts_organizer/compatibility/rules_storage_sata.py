"""SATA data-port availability + declared M.2/SATA topology (T17.9-R2).

Pure/deterministic. NO assignment/solver, NO RAID/controller modeling, NO lane or
performance validation. Conservative evidence semantics:
- Unknown data never becomes a favorable certainty.
- A verified scalar count is a declared total (descriptive), not proof of every
  physical port or of absence of additional controllers.
- Unverified sata_port_identifiers never degrade a verified count-only result.
- `disables_sata_port_ids` is a declared potential restriction; exact mode/BIOS
  conditions are not modeled.
- `shared_resource_group_id` is descriptive only.
- `routed_to` is descriptive only.
"""

from __future__ import annotations

from .engine import _finding, attr_low_confidence, attr_verified, get_attr
from .models import (
    RESULT_COMPATIBLE,
    RESULT_INSUFFICIENT_DATA,
    RESULT_REQUIRES_VERIFICATION,
    SEVERITY_INFO,
    SEVERITY_WARNING,
)
from .rules_storage import (
    _collection_complete_and_verified,
    _keying_relation,
    _length_ok,
    _mode_ok,
    _slot_meta,
    _storage_mode,
)
from .storage_classification import classify_all, is_collection_complete

RULESET = "t17.9-storage-sata-v2"


def _attr_meta(attr):
    return None if attr is None else {
        "key": attr.key,
        "value": getattr(attr, "value", None),
        "unit": getattr(attr, "unit", None),
        "source": getattr(attr, "source", None),
        "confidence": getattr(attr, "confidence", None),
        "verification_status": getattr(attr, "verification_status", None),
        "evidence_ref": getattr(attr, "evidence_ref", None),
        "verified_at": getattr(attr, "verified_at", None),
        "collection_completeness": getattr(attr, "collection_completeness", "unknown"),
        "completeness_scope": getattr(attr, "completeness_scope", None),
    }


def _is_other(v) -> bool:
    return isinstance(v, str) and v.strip().lower() == "other"


def _unit_meta(cl) -> dict:
    return {
        "id": cl.component_id,
        "classification": cl.status,
        "form_factor": cl.form_factor,
        "interface": cl.interface,
        "command_set": cl.command_set,
        "ff_verified": cl.ff_verified,
        "iface_verified": cl.iface_verified,
        "cmd_verified": cl.cmd_verified,
        "sata_demand": cl.sata,
        "bay25_demand": cl.bay25,
        "bay35_demand": cl.bay35,
        "m2_demand": cl.m2,
    }


def _ordered_unique(ids):
    seen = set()
    out = []
    for i in ids:
        if i not in seen:
            seen.add(i)
            out.append(i)
    return out


def evaluate_sata_port_availability(ctx):
    """Compare confirmed SATA demand with declared integrated port count."""
    findings = []
    cl = classify_all(ctx)
    confirmed = [cid for cid, c in cl.items() if c.sata == "confirmed"]
    possible = [cid for cid, c in cl.items() if c.sata == "possible"]
    contradictory = [cid for cid, c in cl.items() if c.contradictory]
    relevant = _ordered_unique(confirmed + possible)
    if not relevant:
        return findings, 0

    mbs = ctx.components_by_category.get("Motherboard", [])
    if not mbs:
        findings.append(_finding(
            rule_id="storage_sata.motherboard_missing", rule_version="1", result=RESULT_INSUFFICIENT_DATA, severity=SEVERITY_INFO,
            component_ids=relevant, attributes_compared=["storage_form_factor", "storage_interface", "storage_command_set"],
            evidence={
                "sata_units": [_unit_meta(cl[cid]) for cid in confirmed],
                "unknown_units": [_unit_meta(cl[cid]) for cid in possible],
                "contradictory_units": [_unit_meta(cl[cid]) for cid in contradictory],
            },
            message_key="compat.storage_sata.motherboard_missing",
            missing_information=["motherboard"], recommended_action="add_motherboard",
        ))
        return findings, 0
    if len(mbs) > 1:
        findings.append(_finding(
            rule_id="storage_sata.ambiguous_motherboard", rule_version="1", result=RESULT_INSUFFICIENT_DATA, severity=SEVERITY_INFO,
            component_ids=relevant + [mb.id for mb in mbs],
            attributes_compared=["storage_form_factor", "storage_interface", "storage_command_set", "sata_port_count"],
            evidence={
                "sata_units": [_unit_meta(cl[cid]) for cid in confirmed],
                "unknown_units": [_unit_meta(cl[cid]) for cid in possible],
                "contradictory_units": [_unit_meta(cl[cid]) for cid in contradictory],
                "motherboard_count": len(mbs),
            },
            message_key="compat.storage_sata.ambiguous_motherboard",
            message_params={"count": len(mbs)}, missing_information=["single_motherboard"], recommended_action="review_build_configuration",
        ))
        return findings, 0

    mb = mbs[0]
    mbp = ctx.profiles_by_component_id.get(mb.id)
    count_attr = get_attr(mbp, "sata_port_count")
    ids_attr = get_attr(mbp, "sata_port_identifiers")
    cids = relevant + [mb.id]
    attrs_compared = ["storage_form_factor", "storage_interface", "storage_command_set", "sata_port_count"]
    declared_ids = list(getattr(ids_attr, "value", ()) or ()) if ids_attr is not None else []
    evidence = {
        "motherboard": {"sata_port_count": _attr_meta(count_attr), "sata_port_identifiers": _attr_meta(ids_attr)},
        "sata_units": [_unit_meta(cl[cid]) for cid in confirmed],
        "unknown_units": [_unit_meta(cl[cid]) for cid in possible],
        "contradictory_units": [_unit_meta(cl[cid]) for cid in contradictory],
        "required_ports": len(confirmed),
        "possible_additional_ports": len(possible),
        "declared_ports": int(count_attr.value) if count_attr is not None else None,
        "declared_ids": declared_ids,
    }
    params = {
        "required_ports": len(confirmed),
        "possible_additional_ports": len(possible),
        "declared_ports": int(count_attr.value) if count_attr is not None else None,
        "declared_ids": declared_ids,
    }

    if count_attr is None:
        findings.append(_finding(
            rule_id="storage_sata.port_availability", rule_version="1", result=RESULT_INSUFFICIENT_DATA, severity=SEVERITY_WARNING,
            component_ids=cids, attributes_compared=attrs_compared, evidence=evidence,
            message_key="compat.storage_sata.port_availability.count_missing",
            message_params=params, missing_information=["motherboard.sata_port_count"],
            recommended_action="provide_verified_sata_port_count",
        ))
        return findings, 0

    declared = int(count_attr.value)
    declared_verified = attr_verified(count_attr) and not attr_low_confidence(count_attr)

    if contradictory:
        reason, action = "storage_data_contradictory", "verify_storage_profile_data"
    elif possible:
        reason, action = "storage_units_undetermined", "verify_storage_and_slot_attributes"
    elif not declared_verified:
        reason, action = "sata_port_data_not_verified", "verify_sata_port_data"
    elif len(confirmed) > declared:
        reason, action = "additional_sata_controllers_or_ports_not_excluded", "verify_additional_sata_controllers_and_ports"
    else:
        findings.append(_finding(
            rule_id="storage_sata.port_availability", rule_version="1", result=RESULT_COMPATIBLE, severity=SEVERITY_INFO,
            component_ids=cids, attributes_compared=attrs_compared, evidence=evidence,
            message_key="compat.storage_sata.port_availability.compatible", message_params=params,
        ))
        return findings, 1

    findings.append(_finding(
        rule_id="storage_sata.port_availability", rule_version="1", result=RESULT_REQUIRES_VERIFICATION, severity=SEVERITY_WARNING,
        component_ids=cids, attributes_compared=attrs_compared, evidence=evidence,
        message_key="compat.storage_sata.port_availability.requires_verification",
        message_params={**params, "reason": reason}, recommended_action=action,
    ))
    return findings, 1


def evaluate_m2_sata_topology(ctx):
    """Identify declared potential M.2/SATA restrictions without assignment."""
    findings = []
    cl = classify_all(ctx)
    m2_relevant = [cid for cid, c in cl.items() if c.m2 in ("confirmed", "possible")]
    sata_relevant = [cid for cid, c in cl.items() if c.sata in ("confirmed", "possible")]
    if not m2_relevant or not sata_relevant:
        return findings, 0
    mbs = ctx.components_by_category.get("Motherboard", [])
    if not mbs:
        return findings, 0
    if len(mbs) > 1:
        cids = _ordered_unique(m2_relevant + sata_relevant + [mb.id for mb in mbs])
        findings.append(_finding(
            rule_id="storage_sata.m2_topology", rule_version="1", result=RESULT_INSUFFICIENT_DATA, severity=SEVERITY_INFO,
            component_ids=cids,
            attributes_compared=["storage_form_factor", "m2_keying", "m2_length_code", "storage_interface", "storage_command_set", "m2_slots"],
            evidence={
                "m2_units": [_unit_meta(cl[cid]) for cid in m2_relevant],
                "sata_units": [_unit_meta(cl[cid]) for cid in sata_relevant],
                "motherboard_count": len(mbs),
            },
            message_key="compat.storage_sata.m2_topology.ambiguous_motherboard",
            message_params={"count": len(mbs)}, missing_information=["single_motherboard"],
            recommended_action="review_build_configuration",
        ))
        return findings, 0

    mb = mbs[0]
    cids = _ordered_unique(m2_relevant + sata_relevant + [mb.id])
    mbp = ctx.profiles_by_component_id.get(mb.id)
    slots_attr = get_attr(mbp, "m2_slots")
    ids_attr = get_attr(mbp, "sata_port_identifiers")
    declared_ids = list(getattr(ids_attr, "value", ()) or ()) if ids_attr is not None else []
    ids_verified = ids_attr is not None and attr_verified(ids_attr) and not attr_low_confidence(ids_attr)
    slots = list(getattr(slots_attr, "value", ()) or ()) if slots_attr is not None else []

    if slots_attr is None:
        findings.append(_finding(
            rule_id="storage_sata.m2_topology", rule_version="1", result=RESULT_INSUFFICIENT_DATA, severity=SEVERITY_WARNING,
            component_ids=cids,
            attributes_compared=["storage_form_factor", "m2_keying", "m2_length_code", "storage_interface", "storage_command_set", "m2_slots"],
            evidence={
                "m2_units": [_unit_meta(cl[cid]) for cid in m2_relevant],
                "sata_units": [_unit_meta(cl[cid]) for cid in sata_relevant],
            },
            message_key="compat.storage_sata.m2_topology.slots_missing",
            missing_information=["motherboard.m2_slots"], recommended_action="provide_verified_m2_slots",
        ))
        return findings, 0

    if not slots:
        slots_verified = attr_verified(slots_attr) and not attr_low_confidence(slots_attr)
        if slots_verified:
            findings.append(_finding(
                rule_id="storage_sata.m2_topology", rule_version="1", result=RESULT_REQUIRES_VERIFICATION, severity=SEVERITY_WARNING,
                component_ids=cids,
                attributes_compared=["storage_form_factor", "m2_keying", "m2_length_code", "storage_interface", "storage_command_set", "m2_slots"],
                evidence={
                    "m2_units": [_unit_meta(cl[cid]) for cid in m2_relevant],
                    "sata_units": [_unit_meta(cl[cid]) for cid in sata_relevant],
                    "m2_slots": {"collection": _attr_meta(slots_attr), "slots": []},
                },
                message_key="compat.storage_sata.m2_topology.slots_empty",
                message_params={"reason": "m2_slot_inventory_exhaustiveness_not_demonstrated"},
                recommended_action="verify_m2_slot_inventory_and_sata_topology",
            ))
        else:
            findings.append(_finding(
                rule_id="storage_sata.m2_topology", rule_version="1", result=RESULT_INSUFFICIENT_DATA, severity=SEVERITY_WARNING,
                component_ids=cids,
                attributes_compared=["storage_form_factor", "m2_keying", "m2_length_code", "storage_interface", "storage_command_set", "m2_slots"],
                evidence={
                    "m2_units": [_unit_meta(cl[cid]) for cid in m2_relevant],
                    "sata_units": [_unit_meta(cl[cid]) for cid in sata_relevant],
                    "m2_slots": {"collection": _attr_meta(slots_attr), "slots": []},
                },
                message_key="compat.storage_sata.m2_topology.slots_missing",
                missing_information=["motherboard.m2_slots"], recommended_action="provide_verified_m2_slots",
            ))
        return findings, 0

    per_unit = []
    restricting: list[dict] = []
    affected: set[str] = set()
    shared: list[dict] = []
    ambiguous_units: list[str] = []
    contradictory_units = [cid for cid in m2_relevant if cl[cid].contradictory]
    candidate_units = 0
    for cid in m2_relevant:
        p = ctx.profiles_by_component_id.get(cid)
        c = cl[cid]
        mode, _ = _storage_mode(p)
        key_attr = get_attr(p, "m2_keying")
        len_attr = get_attr(p, "m2_length_code")
        key = key_attr.value if key_attr is not None else None
        length = len_attr.value if len_attr is not None else None
        unit_entry: dict = {
            "storage_id": cid,
            "classification": c.status,
            "m2_keying": key,
            "m2_length_code": length,
            "storage_interface": c.interface,
            "storage_command_set": c.command_set,
            "attrs_verified": False,
            "candidate_slots": [],
            "restricting_slots": [],
            "shared_resource_groups": [],
        }
        key_ok = key_attr is not None and attr_verified(key_attr) and not attr_low_confidence(key_attr)
        len_ok = len_attr is not None and attr_verified(len_attr) and not attr_low_confidence(len_attr)
        unit_entry["attrs_verified"] = bool(c.ff_verified and c.iface_verified and c.cmd_verified and key_ok and len_ok)
        undetermined = bool(
            c.contradictory
            or c.m2 == "possible"
            or mode is None
            or key is None
            or length is None
            or _is_other(key)
            or _is_other(length)
        )
        if key_attr is None or len_attr is None:
            undetermined = True
        else:
            key_ok = attr_verified(key_attr) and not attr_low_confidence(key_attr)
            len_ok = attr_verified(len_attr) and not attr_low_confidence(len_attr)
            if not (key_ok and len_ok and c.iface_verified and c.cmd_verified and c.ff_verified):
                undetermined = True
        if undetermined:
            ambiguous_units.append(cid)
            unit_entry["status"] = "unit_attributes_undetermined"
            per_unit.append(unit_entry)
            continue
        for slot in slots:
            k_status, _ = _keying_relation(key, list(getattr(slot, "accepted_module_keyings", ()) or ()))
            m_ok, _ = _mode_ok(mode, list(getattr(slot, "supported_modes", ()) or ()))
            l_ok, _ = _length_ok(length, list(getattr(slot, "supported_lengths", ()) or ()))
            if k_status == "fit" and m_ok and l_ok:
                unit_entry["candidate_slots"].append(slot.slot_id)
                if slot.disables_sata_port_ids:
                    unit_entry["restricting_slots"].append(slot.slot_id)
                    restricting.append({"slot_id": slot.slot_id, "disables_sata_port_ids": list(slot.disables_sata_port_ids)})
                    affected.update(slot.disables_sata_port_ids)
                if slot.shared_resource_group_id:
                    unit_entry["shared_resource_groups"].append({"slot_id": slot.slot_id, "group": slot.shared_resource_group_id})
                    shared.append({"storage_id": cid, "slot_id": slot.slot_id, "group": slot.shared_resource_group_id})
        if unit_entry["candidate_slots"]:
            candidate_units += 1
        unit_entry["status"] = "candidate_slots_declared" if unit_entry["candidate_slots"] else "no_candidate_slot"
        per_unit.append(unit_entry)

    affected_ids = sorted(affected)
    slots_verified = attr_verified(slots_attr) and not attr_low_confidence(slots_attr)
    slots_evidenced = _collection_complete_and_verified(slots_attr, slots)
    ids_complete = is_collection_complete(ids_attr)
    uncontrastable = sorted([pid for pid in affected_ids if pid not in declared_ids]) if affected_ids else []
    nonexistent_within_scope = sorted([pid for pid in uncontrastable]) if (ids_complete and uncontrastable) else []
    ids_contrastable = bool(affected_ids) and ids_verified and not uncontrastable

    if contradictory_units:
        reason, action = "storage_data_contradictory", "verify_storage_profile_data"
    elif ambiguous_units:
        reason, action = "m2_slot_assignment_or_attributes_unknown", "verify_storage_and_slot_attributes"
    elif not (slots_verified and slots_evidenced):
        reason, action = "m2_slot_data_not_verified", "verify_m2_slot_inventory_and_sata_topology"
    elif restricting:
        reason, action = "m2_slot_may_disable_sata_ports", "verify_m2_sata_topology_in_manual"
    elif shared:
        reason, action = "shared_resource_group_semantics_not_evaluated", "verify_m2_slot_inventory_and_sata_topology"
    else:
        reason, action = "m2_slot_inventory_exhaustiveness_not_demonstrated", "verify_m2_slot_inventory_and_sata_topology"

    attrs_compared = ["storage_form_factor", "m2_keying", "m2_length_code", "storage_interface", "storage_command_set", "m2_slots", "disables_sata_port_ids"]
    if shared:
        attrs_compared.append("shared_resource_group_id")
    if restricting:
        attrs_compared.append("sata_port_identifiers")

    evidence = {
        "m2_units": per_unit,
        "sata_units": [_unit_meta(cl[cid]) for cid in sata_relevant],
        "ambiguous_units": [_unit_meta(cl[cid]) for cid in ambiguous_units],
        "contradictory_units": [_unit_meta(cl[cid]) for cid in contradictory_units],
        "m2_slots": {"collection": _attr_meta(slots_attr), "slots": [_slot_meta(s) for s in slots]},
        "sata_port_identifiers": _attr_meta(ids_attr),
        "restricting_slots": restricting,
        "shared_resource_groups": shared,
        "affected_sata_port_ids": affected_ids,
        "uncontrastable_sata_port_ids": uncontrastable,
        "ids_nonexistent_within_scope": nonexistent_within_scope,
        "ids_contrastable": ids_contrastable,
        "candidate_units": candidate_units,
    }
    params = {
        "reason": reason,
        "candidate_units": candidate_units,
        "restricting_slots": len({r["slot_id"] for r in restricting}),
        "affected_sata_port_ids": affected_ids,
        "uncontrastable_sata_port_ids": uncontrastable,
        "ids_nonexistent_within_scope": nonexistent_within_scope,
        "ids_contrastable": ids_contrastable,
    }
    findings.append(_finding(
        rule_id="storage_sata.m2_topology", rule_version="1", result=RESULT_REQUIRES_VERIFICATION, severity=SEVERITY_WARNING,
        component_ids=cids, attributes_compared=attrs_compared,
        evidence=evidence, message_key="compat.storage_sata.m2_topology.requires_verification",
        message_params=params, recommended_action=action,
    ))
    return findings, 1
