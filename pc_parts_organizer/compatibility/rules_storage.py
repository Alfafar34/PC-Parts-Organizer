"""Storage physical compatibility rules (T17.8a): M.2 slot fit and bay capacity only.

Pure/deterministic. No slot assignment, no solver, no topology, no PSU/power rules.
A declared descriptive inventory (e.g. m2_slots) is NOT assumed complete unless the
collection itself is verified; absence from a non-complete collection never proves
incompatibility. 'other' and missing values never allow confirmed compatibility.
"""

from __future__ import annotations

from .engine import _finding, attr_low_confidence, attr_verified, get_attr
from .models import (
    RESULT_COMPATIBLE,
    RESULT_INCOMPATIBLE,
    RESULT_INSUFFICIENT_DATA,
    RESULT_REQUIRES_VERIFICATION,
    SEVERITY_CRITICAL,
    SEVERITY_INFO,
    SEVERITY_WARNING,
)

RULESET = "t17.8-storage-v1"


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


def _slot_meta(slot):
    return {
        "slot_id": getattr(slot, "slot_id", None),
        "accepted_module_keyings": list(getattr(slot, "accepted_module_keyings", ()) or ()),
        "supported_lengths": list(getattr(slot, "supported_lengths", ()) or ()),
        "supported_modes": list(getattr(slot, "supported_modes", ()) or ()),
        "pcie_generation_max": getattr(slot, "pcie_generation_max", None),
        "pcie_lanes_max": getattr(slot, "pcie_lanes_max", None),
        "routed_to": getattr(slot, "routed_to", None),
        "shared_resource_group_id": getattr(slot, "shared_resource_group_id", None),
        "disables_sata_port_ids": list(getattr(slot, "disables_sata_port_ids", ()) or ()),
        "notes": getattr(slot, "notes", None),
        "evidence_ref": getattr(slot, "evidence_ref", None),
    }


def _storage_mode(profile) -> tuple[str | None, bool]:
    """Derive coherent storage mode from interface+command set; None if unknown/other."""
    interface = get_attr(profile, "storage_interface")
    command = get_attr(profile, "storage_command_set")
    iv = interface.value if interface is not None else None
    cv = command.value if command is not None else None
    pair = {(iv, cv)}
    if pair == {("sata", "ata")}:
        return "sata_ata", True
    if pair == {("pcie", "nvme")}:
        return "pcie_nvme", True
    return None, False


def _is_other_token(v) -> bool:
    return isinstance(v, str) and v.strip().lower() == "other"


def _keying_relation(unit_key, slot_keyings) -> tuple[str, str | None]:
    """Return (status, reason). status: 'fit'|'undemonstrated'.

    Conservative/source-grounded: require an exact shared documented keying token.
    We do NOT assume B+M is a wildcard, nor that B fits an M-keyed slot or vice versa.
    Absent/fundamentally undocumented relations degrade to requires_verification.
    """
    keys = list(slot_keyings or ())
    if unit_key is None or _is_other_token(unit_key):
        return "undemonstrated", "keying_other_or_undocumented"
    if any(_is_other_token(k) for k in keys):
        return "undemonstrated", "keying_other_or_undocumented"
    if unit_key in keys:
        return "fit", None
    return "undemonstrated", "keying_not_demonstrated"


def _mode_ok(mode, slot_modes):
    if mode is None:
        return False, "mode_unknown_or_other"
    if mode in (slot_modes or ()):
        return True, None
    if any(m in ("sata_ata", "pcie_nvme") for m in (slot_modes or ())):
        return False, "mode_contradiction"
    return False, "mode_not_demonstrated"


def _length_ok(length, supported):
    sup = list(supported or ())
    if length is None:
        return False, "length_missing"
    if _is_other_token(length):
        return False, "length_other"  # ambiguous: never confirms, never contradicts by itself
    if length in sup:
        return True, None
    if any(_is_other_token(v) for v in sup):
        return False, "length_not_demonstrated"
    if any(not _is_other_token(v) for v in sup):
        return False, "length_not_supported"
    return False, "length_not_demonstrated"


def _collection_complete_and_verified(slots_attr, slot_objs) -> bool:
    # Completeness is never guaranteed by presence alone. A negative conclusion is
    # only allowed when the descriptive collection itself is verified/high-confidence
    # AND every declared slot is documented with its own evidence pointer (granular).
    if not attr_verified(slots_attr) or attr_low_confidence(slots_attr):
        return False
    if not slot_objs:
        return False
    return all(getattr(s, "evidence_ref", None) for s in slot_objs)


def _slots_collection_complete(slots_attr) -> bool:
    from .storage_classification import is_collection_complete
    return is_collection_complete(slots_attr)


def _slot_fully_described(slot) -> bool:
    keyings = list(getattr(slot, "accepted_module_keyings", ()) or ())
    lengths = list(getattr(slot, "supported_lengths", ()) or ())
    modes = list(getattr(slot, "supported_modes", ()) or ())
    if not keyings or not lengths or not modes:
        return False
    if any(_is_other_token(v) for v in keyings + lengths):
        return False
    if not getattr(slot, "evidence_ref", None):
        return False
    return True


def evaluate_m2_fit(ctx):
    """Evaluate each M.2 storage unit against declared M.2 slots (no assignment)."""
    findings = []
    mbs = ctx.components_by_category.get("Motherboard", [])
    storages = ctx.components_by_category.get("Storage", [])
    if not storages or not mbs or len(mbs) > 1:
        return findings, 0
    mb = mbs[0]
    mbp = ctx.profiles_by_component_id.get(mb.id)
    slots_attr = get_attr(mbp, "m2_slots")
    slot_objs = list(getattr(slots_attr, "value", ()) or ()) if slots_attr is not None else []
    if not slot_objs:
        # Only declared M.2 form factor is M.2-relevant (no inference).
        m2_units = []
        for st in storages:
            p = ctx.profiles_by_component_id.get(st.id)
            ff = get_attr(p, "storage_form_factor")
            if ff is not None and ff.value == "m2":
                m2_units.append(st)
        if m2_units:
            cids = [c.id for c in m2_units] + [mb.id]
            if slots_attr is None:
                findings.append(_finding(
                    rule_id="storage_m2.slots_absent", rule_version="1", result=RESULT_INSUFFICIENT_DATA, severity=SEVERITY_WARNING,
                    component_ids=cids, attributes_compared=["m2_slots", "storage_form_factor"],
                    evidence={"m2_slots": _attr_meta(slots_attr), "m2_units": [c.id for c in m2_units]},
                    message_key="compat.storage_m2.slots_absent", missing_information=["motherboard.m2_slots"],
                    recommended_action="provide_verified_m2_slots",
                ))
            else:
                slots_verified = attr_verified(slots_attr) and not attr_low_confidence(slots_attr)
                if _slots_collection_complete(slots_attr):
                    all_known = True
                    for ust in m2_units:
                        up = ctx.profiles_by_component_id.get(ust.id)
                        umode, _ = _storage_mode(up)
                        uk = get_attr(up, "m2_keying")
                        ul = get_attr(up, "m2_length_code")
                        uif = get_attr(up, "storage_interface")
                        uc = get_attr(up, "storage_command_set")
                        uff = get_attr(up, "storage_form_factor")
                        uattrs = [a for a in (uff, uk, ul, uif, uc) if a is not None]
                        kv = uk.value if uk is not None else None
                        lv = ul.value if ul is not None else None
                        if not uattrs or umode is None or kv is None or lv is None:
                            all_known = False
                            break
                        if kv.strip().lower() == "other" or lv.strip().lower() == "other":
                            all_known = False
                            break
                        if not all(attr_verified(a) and not attr_low_confidence(a) for a in uattrs):
                            all_known = False
                            break
                    if all_known:
                        findings.append(_finding(
                            rule_id="storage_m2.slots_absent", rule_version="1", result=RESULT_INCOMPATIBLE, severity=SEVERITY_CRITICAL,
                            component_ids=cids, attributes_compared=["m2_slots", "storage_form_factor"],
                            evidence={"m2_slots": _attr_meta(slots_attr), "m2_units": [c.id for c in m2_units]},
                            message_key="compat.storage_m2.slots_empty_complete",
                            message_params={"units": len(m2_units)},
                            recommended_action="use_documented_compatible_slot_or_storage",
                        ))
                    else:
                        findings.append(_finding(
                            rule_id="storage_m2.slots_absent", rule_version="1", result=RESULT_REQUIRES_VERIFICATION, severity=SEVERITY_WARNING,
                            component_ids=cids, attributes_compared=["m2_slots", "storage_form_factor"],
                            evidence={"m2_slots": _attr_meta(slots_attr), "m2_units": [c.id for c in m2_units]},
                            message_key="compat.storage_m2.slots_empty",
                            message_params={"reason": "m2_slot_inventory_exhaustiveness_not_demonstrated"},
                            recommended_action="verify_m2_slot_inventory_and_sata_topology",
                        ))
                elif slots_verified:
                    findings.append(_finding(
                        rule_id="storage_m2.slots_absent", rule_version="1", result=RESULT_REQUIRES_VERIFICATION, severity=SEVERITY_WARNING,
                        component_ids=cids, attributes_compared=["m2_slots", "storage_form_factor"],
                        evidence={"m2_slots": _attr_meta(slots_attr), "m2_units": [c.id for c in m2_units]},
                        message_key="compat.storage_m2.slots_empty",
                        message_params={"reason": "m2_slot_inventory_exhaustiveness_not_demonstrated"},
                        recommended_action="verify_m2_slot_inventory_and_sata_topology",
                    ))
                else:
                    findings.append(_finding(
                        rule_id="storage_m2.slots_absent", rule_version="1", result=RESULT_INSUFFICIENT_DATA, severity=SEVERITY_WARNING,
                        component_ids=cids, attributes_compared=["m2_slots", "storage_form_factor"],
                        evidence={"m2_slots": _attr_meta(slots_attr), "m2_units": [c.id for c in m2_units]},
                        message_key="compat.storage_m2.slots_empty",
                        missing_information=["motherboard.m2_slots"],
                        recommended_action="provide_verified_m2_slots",
                    ))
        return findings, 0
    rules_evaluated = 0
    for st in storages:
        p = ctx.profiles_by_component_id.get(st.id)
        ff = get_attr(p, "storage_form_factor")
        if ff is None or ff.value != "m2":
            # T17.8a handles only M.2 form factor here; others left to bay rules/OOS.
            continue
        rules_evaluated += 1
        cids = [st.id, mb.id]
        keying = get_attr(p, "m2_keying")
        length = get_attr(p, "m2_length_code")
        interface = get_attr(p, "storage_interface")
        command = get_attr(p, "storage_command_set")
        unit_attrs = [a for a in (ff, keying, length, interface, command) if a is not None]
        required_keys = ("m2_keying", "m2_length_code", "storage_interface", "storage_command_set")
        missing = [f"storage[{st.id}].{k}" for k in required_keys if get_attr(p, k) is None]
        # per-slot evaluation (no assignment/reservation)
        mode, _ = _storage_mode(p)
        key = keying.value if keying is not None else None
        length_v = length.value if length is not None else None
        slot_metas = [_slot_meta(s) for s in slot_objs]
        fits = []
        contradictions = []
        for s in slot_objs:
            k_status, k_reason = _keying_relation(key, list(getattr(s, "accepted_module_keyings", ()) or ()))
            m_status, m_reason = _mode_ok(mode, list(getattr(s, "supported_modes", ()) or ()))
            l_status, l_reason = _length_ok(length_v, list(getattr(s, "supported_lengths", ()) or ()))
            if k_status == "fit" and m_status and l_status:
                fits.append(s.slot_id)
            if m_reason == "mode_contradiction" or l_reason == "length_not_supported":
                contradictions.append((s.slot_id, k_reason, m_reason, l_reason))
        verified_ok = bool(unit_attrs) and all(attr_verified(a) and not attr_low_confidence(a) for a in unit_attrs) and attr_verified(slots_attr) and not attr_low_confidence(slots_attr)
        base = {
            "component_ids": cids,
            "attributes_compared": ["storage_form_factor", "m2_keying", "m2_length_code", "storage_interface", "storage_command_set", "m2_slots"],
            "evidence": {
                "storage": {a.key: _attr_meta(a) for a in unit_attrs},
                "m2_slots": {"collection": _attr_meta(slots_attr), "slots": slot_metas},
            },
        }
        if not unit_attrs or (mode is None) or key is None or length_v is None:
            findings.append(_finding(
                rule_id="storage_m2.fit", rule_version="1", result=RESULT_INSUFFICIENT_DATA, severity=SEVERITY_WARNING,
                message_key="compat.storage_m2.fit.insufficient_data", message_params={"storage_id": st.id},
                missing_information=sorted(set(missing)) or ["storage.m2_attributes"],
                recommended_action="provide_verified_storage_attributes", **base,
            ))
            continue
        if fits and verified_ok:
            findings.append(_finding(
                rule_id="storage_m2.fit", rule_version="1", result=RESULT_COMPATIBLE, severity=SEVERITY_INFO,
                message_key="compat.storage_m2.fit.compatible",
                message_params={"storage_id": st.id, "candidate_slots": fits},
                **base,
            ))
        elif fits and not verified_ok:
            findings.append(_finding(
                rule_id="storage_m2.fit", rule_version="1", result=RESULT_REQUIRES_VERIFICATION, severity=SEVERITY_WARNING,
                message_key="compat.storage_m2.fit.requires_verification",
                message_params={"storage_id": st.id, "candidate_slots": fits, "reason": "storage_or_slot_data_not_verified"},
                recommended_action="verify_storage_and_slot_attributes", **base,
            ))
        elif not fits:
            unit_known = verified_ok and not _is_other_token(key) and not _is_other_token(length_v)
            collection_complete = _slots_collection_complete(slots_attr)
            slots_resolvable = bool(slot_objs) and all(_slot_fully_described(s) for s in slot_objs)
            if unit_known and collection_complete and slots_resolvable:
                findings.append(_finding(
                    rule_id="storage_m2.fit", rule_version="1", result=RESULT_INCOMPATIBLE, severity=SEVERITY_CRITICAL,
                    message_key="compat.storage_m2.fit.incompatible",
                    message_params={"storage_id": st.id, "slot_ids": [s.slot_id for s in slot_objs]},
                    recommended_action="use_documented_compatible_slot_or_storage", **base,
                ))
            elif contradictions:
                # Without formal collection completeness, absence from the declared
                # list cannot prove no compatible physical slot exists.
                findings.append(_finding(
                    rule_id="storage_m2.fit", rule_version="1", result=RESULT_REQUIRES_VERIFICATION, severity=SEVERITY_WARNING,
                    message_key="compat.storage_m2.fit.requires_verification",
                    message_params={"storage_id": st.id, "slot_ids": [c[0] for c in contradictions], "reason": "collection_exhaustiveness_not_demonstrated"},
                    recommended_action="verify_complete_m2_slot_inventory_and_physical_fit", **base,
                ))
            else:
                reason = "keying_or_mode_or_length_not_demonstrated"
                findings.append(_finding(
                    rule_id="storage_m2.fit", rule_version="1", result=RESULT_REQUIRES_VERIFICATION, severity=SEVERITY_WARNING,
                    message_key="compat.storage_m2.fit.requires_verification",
                    message_params={"storage_id": st.id, "reason": reason, "apparent_fit": bool(fits)},
                    recommended_action="verify_physical_slot_compatibility", **base,
                ))
        else:
            reason = "keying_or_mode_or_length_not_demonstrated"
            findings.append(_finding(
                rule_id="storage_m2.fit", rule_version="1", result=RESULT_REQUIRES_VERIFICATION, severity=SEVERITY_WARNING,
                message_key="compat.storage_m2.fit.requires_verification",
                message_params={"storage_id": st.id, "reason": reason, "apparent_fit": bool(fits)},
                recommended_action="verify_physical_slot_compatibility", **base,
            ))
    return findings, rules_evaluated


def evaluate_bay_capacity(ctx):
    """Compare 2.5"/3.5" storage units against declared total bay counts. No free-bay inference, no adapters."""
    findings = []
    cases = ctx.components_by_category.get("Case", [])
    storages = ctx.components_by_category.get("Storage", [])
    if not storages or not cases or len(cases) > 1:
        return findings, 0
    from .storage_classification import classify_all
    case = cases[0]
    cp = ctx.profiles_by_component_id.get(case.id)
    counts = {k: get_attr(cp, k) for k in ("bay_2_5_total", "bay_3_5_total")}
    rules_evaluated = 0
    cl = classify_all(ctx)
    groups = {"2_5_in": {"confirmed": [], "possible": []}, "3_5_in": {"confirmed": [], "possible": []}}
    for st in storages:
        c = cl.get(st.id)
        if c is None:
            continue
        if c.bay25 == "confirmed":
            groups["2_5_in"]["confirmed"].append(st.id)
        elif c.bay25 == "possible":
            groups["2_5_in"]["possible"].append(st.id)
        if c.bay35 == "confirmed":
            groups["3_5_in"]["confirmed"].append(st.id)
        elif c.bay35 == "possible":
            groups["3_5_in"]["possible"].append(st.id)
    for ff_value, attr_key, size in (("2_5_in", "bay_2_5_total", "2_5"), ("3_5_in", "bay_3_5_total", "3_5")):
        confirmed_ids = groups[ff_value]["confirmed"]
        possible_ids = groups[ff_value]["possible"]
        units = len(confirmed_ids)
        possible = len(possible_ids)
        if units == 0 and possible == 0:
            continue
        ba = counts[attr_key]
        cids = confirmed_ids + possible_ids + [case.id]
        attrs = [attr_key, "storage_form_factor"]
        ev_base = {"case": _attr_meta(ba), "units": units, "possible_units": possible,
                   "confirmed_unit_ids": confirmed_ids, "possible_unit_ids": possible_ids}
        if ba is None:
            findings.append(_finding(
                rule_id=f"storage_case.bay_{size}_capacity", rule_version="1", result=RESULT_INSUFFICIENT_DATA, severity=SEVERITY_WARNING,
                component_ids=cids, attributes_compared=attrs, evidence=ev_base,
                message_key=f"compat.storage_case.bay_{size}_capacity.insufficient_data",
                message_params={"units": units, "possible_units": possible}, missing_information=[f"case.{attr_key}"],
                recommended_action="provide_verified_bay_counts",
            ))
            continue
        rules_evaluated += 1
        bay_value = int(ba.value)
        verified_ok = attr_verified(ba) and not attr_low_confidence(ba)
        base = dict(component_ids=cids, attributes_compared=attrs, evidence={**ev_base, "bays": bay_value})
        params = {"units": units, "possible_units": possible, "bays": bay_value}
        if units > bay_value and verified_ok:
            findings.append(_finding(
                rule_id=f"storage_case.bay_{size}_capacity", rule_version="1", result=RESULT_INCOMPATIBLE, severity=SEVERITY_CRITICAL,
                message_key=f"compat.storage_case.bay_{size}_capacity.incompatible",
                message_params=params,
                recommended_action="use_larger_case_or_remove_units", **base,
            ))
        elif possible > 0:
            findings.append(_finding(
                rule_id=f"storage_case.bay_{size}_capacity", rule_version="1", result=RESULT_REQUIRES_VERIFICATION, severity=SEVERITY_WARNING,
                message_key=f"compat.storage_case.bay_{size}_capacity.requires_verification",
                message_params={**params, "reason": "bay_demand_undetermined"},
                recommended_action="verify_bay_capacity_and_unit_form_factors", **base,
            ))
        elif units > bay_value:
            findings.append(_finding(
                rule_id=f"storage_case.bay_{size}_capacity", rule_version="1", result=RESULT_REQUIRES_VERIFICATION, severity=SEVERITY_WARNING,
                message_key=f"compat.storage_case.bay_{size}_capacity.requires_verification",
                message_params={**params, "reason": "capacity_data_not_verified"},
                recommended_action="verify_bay_capacity_and_unit_form_factors", **base,
            ))
        elif units <= bay_value and verified_ok:
            findings.append(_finding(
                rule_id=f"storage_case.bay_{size}_capacity", rule_version="1", result=RESULT_COMPATIBLE, severity=SEVERITY_INFO,
                message_key=f"compat.storage_case.bay_{size}_capacity.compatible",
                message_params=params, **base,
            ))
        else:
            findings.append(_finding(
                rule_id=f"storage_case.bay_{size}_capacity", rule_version="1", result=RESULT_REQUIRES_VERIFICATION, severity=SEVERITY_WARNING,
                message_key=f"compat.storage_case.bay_{size}_capacity.requires_verification",
                message_params={**params, "reason": "capacity_data_not_verified"},
                recommended_action="verify_bay_capacity_and_unit_form_factors", **base,
            ))
    return findings, rules_evaluated
