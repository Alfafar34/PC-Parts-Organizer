"""RAM <-> Motherboard compatibility rules (T17.3)."""

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

RULESET = "t17.3-ram-mb-v1"


def _ev(attr):
    return {
        "key": attr.key,
        "value": attr.value,
        "unit": attr.unit,
        "source": attr.source,
        "confidence": attr.confidence,
        "verification_status": attr.verification_status,
        "evidence_ref": attr.evidence_ref,
    }


def _can_confirm_positive(*attrs) -> bool:
    return all(a is not None and attr_verified(a) and not attr_low_confidence(a) for a in attrs)


def evaluate_ram_mb(ctx):
    findings = []
    mb = ctx.components_by_category.get("Motherboard", [None])[0]
    rams = ctx.components_by_category.get("RAM", [])
    if mb is None or not rams:
        return findings, 0
    mbp = ctx.profiles_by_component_id.get(mb.id)
    rules_evaluated = 0

    # Per-RAM: generation and form factor
    for ram in rams:
        rp = ctx.profiles_by_component_id.get(ram.id)
        cids = [ram.id, mb.id]
        # 5.1 generation
        rules_evaluated += 1
        ra = get_attr(rp, "memory_generation")
        ma = get_attr(mbp, "supported_memory_generations")
        if ra is None or ma is None:
            findings.append(_finding(rule_id="ram_mb.memory_generation", rule_version="1", result=RESULT_INSUFFICIENT_DATA, severity=SEVERITY_WARNING,
                                     component_ids=cids, attributes_compared=["memory_generation", "supported_memory_generations"],
                                     evidence={"ram": _ev(ra) if ra else None, "motherboard": _ev(ma) if ma else None},
                                     message_key="compat.ram_mb.memory_generation.insufficient_data",
                                     missing_information=[x for x in (None if ra else "ram.memory_generation", None if ma else "motherboard.supported_memory_generations") if x],
                                     recommended_action="provide_verified_attributes"))
        else:
            supported = list(ma.value) if isinstance(ma.value, (list, tuple)) else []
            included = ra.value in supported
            if included and _can_confirm_positive(ra, ma):
                findings.append(_finding(rule_id="ram_mb.memory_generation", rule_version="1", result=RESULT_COMPATIBLE, severity=SEVERITY_INFO,
                                         component_ids=cids, attributes_compared=["memory_generation", "supported_memory_generations"],
                                         evidence={"ram": _ev(ra), "motherboard": _ev(ma)},
                                         message_key="compat.ram_mb.memory_generation.compatible", message_params={"generation": ra.value}))
            elif not included and attr_verified(ra) and attr_verified(ma) and not attr_low_confidence(ra) and not attr_low_confidence(ma):
                findings.append(_finding(rule_id="ram_mb.memory_generation", rule_version="1", result=RESULT_INCOMPATIBLE, severity=SEVERITY_CRITICAL,
                                         component_ids=cids, attributes_compared=["memory_generation", "supported_memory_generations"],
                                         evidence={"ram": _ev(ra), "motherboard": _ev(ma)},
                                         message_key="compat.ram_mb.memory_generation.incompatible",
                                         message_params={"generation": ra.value, "supported": supported},
                                         recommended_action="use_supported_memory_generation"))
            else:
                key = "compat.ram_mb.memory_generation.requires_verification"
                params = {"generation": ra.value, "supported": supported, "apparent_conflict": not included}
                findings.append(_finding(rule_id="ram_mb.memory_generation", rule_version="1", result=RESULT_REQUIRES_VERIFICATION, severity=SEVERITY_WARNING,
                                         component_ids=cids, attributes_compared=["memory_generation", "supported_memory_generations"],
                                         evidence={"ram": _ev(ra), "motherboard": _ev(ma)},
                                         message_key=key, message_params=params,
                                         missing_information=[] if not included else [],
                                         recommended_action="verify_attributes_or_official_support"))

        # 5.2 module form factor
        rules_evaluated += 1
        ra = get_attr(rp, "module_form_factor")
        ma = get_attr(mbp, "supported_memory_module_form_factors")
        if ra is None or ma is None:
            findings.append(_finding(rule_id="ram_mb.module_form_factor", rule_version="1", result=RESULT_INSUFFICIENT_DATA, severity=SEVERITY_WARNING,
                                     component_ids=cids, attributes_compared=["module_form_factor", "supported_memory_module_form_factors"],
                                     evidence={"ram": _ev(ra) if ra else None, "motherboard": _ev(ma) if ma else None},
                                     message_key="compat.ram_mb.module_form_factor.insufficient_data",
                                     missing_information=[x for x in (None if ra else "ram.module_form_factor", None if ma else "motherboard.supported_memory_module_form_factors") if x],
                                     recommended_action="provide_verified_attributes"))
        else:
            supported = list(ma.value) if isinstance(ma.value, (list, tuple)) else []
            included = ra.value in supported
            if included and _can_confirm_positive(ra, ma):
                findings.append(_finding(rule_id="ram_mb.module_form_factor", rule_version="1", result=RESULT_COMPATIBLE, severity=SEVERITY_INFO,
                                         component_ids=cids, attributes_compared=["module_form_factor", "supported_memory_module_form_factors"],
                                         evidence={"ram": _ev(ra), "motherboard": _ev(ma)},
                                         message_key="compat.ram_mb.module_form_factor.compatible", message_params={"form_factor": ra.value}))
            elif not included and attr_verified(ra) and attr_verified(ma) and not attr_low_confidence(ra) and not attr_low_confidence(ma):
                findings.append(_finding(rule_id="ram_mb.module_form_factor", rule_version="1", result=RESULT_INCOMPATIBLE, severity=SEVERITY_CRITICAL,
                                         component_ids=cids, attributes_compared=["module_form_factor", "supported_memory_module_form_factors"],
                                         evidence={"ram": _ev(ra), "motherboard": _ev(ma)},
                                         message_key="compat.ram_mb.module_form_factor.incompatible",
                                         message_params={"form_factor": ra.value, "supported": supported},
                                         recommended_action="use_supported_module_form_factor"))
            else:
                findings.append(_finding(rule_id="ram_mb.module_form_factor", rule_version="1", result=RESULT_REQUIRES_VERIFICATION, severity=SEVERITY_WARNING,
                                         component_ids=cids, attributes_compared=["module_form_factor", "supported_memory_module_form_factors"],
                                         evidence={"ram": _ev(ra), "motherboard": _ev(ma)},
                                         message_key="compat.ram_mb.module_form_factor.requires_verification",
                                         message_params={"form_factor": ra.value, "supported": supported, "apparent_conflict": not included},
                                         recommended_action="verify_attributes_or_official_support"))

    # 5.3 aggregated capacity - only complete if ALL RAM have total_capacity_gb
    rules_evaluated += 1
    all_ram_ids = [r.id for r in rams]
    cids = all_ram_ids + [mb.id]
    cap_attrs = []
    missing_caps = []
    for ram in rams:
        rp = ctx.profiles_by_component_id.get(ram.id)
        a = get_attr(rp, "total_capacity_gb")
        if a is None:
            missing_caps.append(ram.id)
        else:
            cap_attrs.append((ram.id, a))
    ma = get_attr(mbp, "max_memory_capacity_gb")
    if missing_caps or ma is None:
        missing = [f"ram[{rid}].total_capacity_gb" for rid in missing_caps]
        if ma is None:
            missing.append("motherboard.max_memory_capacity_gb")
        findings.append(_finding(rule_id="ram_mb.max_capacity", rule_version="1", result=RESULT_INSUFFICIENT_DATA, severity=SEVERITY_WARNING,
                                 component_ids=cids, attributes_compared=["total_capacity_gb", "max_memory_capacity_gb"],
                                 evidence={"ram_components": [{"id": rid, "attr": _ev(a)} for rid, a in cap_attrs], "motherboard": _ev(ma) if ma else None},
                                 message_key="compat.ram_mb.max_capacity.insufficient_data",
                                 message_params={"ram_count": len(rams), "missing_ram_components": missing_caps},
                                 missing_information=missing, recommended_action="provide_verified_attributes"))
    else:
        total = sum(int(a.value) for _, a in cap_attrs)
        exceeds = total > int(ma.value)
        if not exceeds and _can_confirm_positive(*[a for _, a in cap_attrs], ma):
            findings.append(_finding(rule_id="ram_mb.max_capacity", rule_version="1", result=RESULT_COMPATIBLE, severity=SEVERITY_INFO,
                                     component_ids=cids, attributes_compared=["total_capacity_gb", "max_memory_capacity_gb"],
                                     evidence={"total_capacity_gb": total, "ram_components": [{"id": rid, "attr": _ev(a)} for rid, a in cap_attrs], "motherboard": _ev(ma)},
                                     message_key="compat.ram_mb.max_capacity.compatible",
                                     message_params={"total_capacity_gb": total, "max_memory_capacity_gb": int(ma.value)}))
        elif exceeds and all(attr_verified(a) and not attr_low_confidence(a) for _, a in cap_attrs) and attr_verified(ma) and not attr_low_confidence(ma):
            findings.append(_finding(rule_id="ram_mb.max_capacity", rule_version="1", result=RESULT_INCOMPATIBLE, severity=SEVERITY_CRITICAL,
                                     component_ids=cids, attributes_compared=["total_capacity_gb", "max_memory_capacity_gb"],
                                     evidence={"total_capacity_gb": total, "ram_components": [{"id": rid, "attr": _ev(a)} for rid, a in cap_attrs], "motherboard": _ev(ma)},
                                     message_key="compat.ram_mb.max_capacity.incompatible",
                                     message_params={"total_capacity_gb": total, "max_memory_capacity_gb": int(ma.value)},
                                     recommended_action="reduce_capacity_or_change_motherboard"))
        else:
            findings.append(_finding(rule_id="ram_mb.max_capacity", rule_version="1", result=RESULT_REQUIRES_VERIFICATION, severity=SEVERITY_WARNING,
                                     component_ids=cids, attributes_compared=["total_capacity_gb", "max_memory_capacity_gb"],
                                     evidence={"total_capacity_gb": total, "ram_components": [{"id": rid, "attr": _ev(a)} for rid, a in cap_attrs], "motherboard": _ev(ma)},
                                     message_key="compat.ram_mb.max_capacity.requires_verification",
                                     message_params={"total_capacity_gb": total, "max_memory_capacity_gb": int(ma.value), "apparent_conflict": exceeds},
                                     recommended_action="verify_attributes_or_official_support"))

    # 5.4 aggregated module count
    rules_evaluated += 1
    mod_attrs = []
    missing_mods = []
    for ram in rams:
        rp = ctx.profiles_by_component_id.get(ram.id)
        a = get_attr(rp, "module_count")
        if a is None:
            missing_mods.append(ram.id)
        else:
            mod_attrs.append((ram.id, a))
    ma = get_attr(mbp, "memory_slot_count")
    if missing_mods or ma is None:
        missing = [f"ram[{rid}].module_count" for rid in missing_mods]
        if ma is None:
            missing.append("motherboard.memory_slot_count")
        findings.append(_finding(rule_id="ram_mb.module_slots", rule_version="1", result=RESULT_INSUFFICIENT_DATA, severity=SEVERITY_WARNING,
                                 component_ids=cids, attributes_compared=["module_count", "memory_slot_count"],
                                 evidence={"ram_components": [{"id": rid, "attr": _ev(a)} for rid, a in mod_attrs], "motherboard": _ev(ma) if ma else None},
                                 message_key="compat.ram_mb.module_slots.insufficient_data",
                                 message_params={"ram_count": len(rams), "missing_ram_components": missing_mods},
                                 missing_information=missing, recommended_action="provide_verified_attributes"))
    else:
        total = sum(int(a.value) for _, a in mod_attrs)
        exceeds = total > int(ma.value)
        if not exceeds and _can_confirm_positive(*[a for _, a in mod_attrs], ma):
            findings.append(_finding(rule_id="ram_mb.module_slots", rule_version="1", result=RESULT_COMPATIBLE, severity=SEVERITY_INFO,
                                     component_ids=cids, attributes_compared=["module_count", "memory_slot_count"],
                                     evidence={"total_module_count": total, "ram_components": [{"id": rid, "attr": _ev(a)} for rid, a in mod_attrs], "motherboard": _ev(ma)},
                                     message_key="compat.ram_mb.module_slots.compatible",
                                     message_params={"total_module_count": total, "memory_slot_count": int(ma.value)}))
        elif exceeds and all(attr_verified(a) and not attr_low_confidence(a) for _, a in mod_attrs) and attr_verified(ma) and not attr_low_confidence(ma):
            findings.append(_finding(rule_id="ram_mb.module_slots", rule_version="1", result=RESULT_INCOMPATIBLE, severity=SEVERITY_CRITICAL,
                                     component_ids=cids, attributes_compared=["module_count", "memory_slot_count"],
                                     evidence={"total_module_count": total, "ram_components": [{"id": rid, "attr": _ev(a)} for rid, a in mod_attrs], "motherboard": _ev(ma)},
                                     message_key="compat.ram_mb.module_slots.incompatible",
                                     message_params={"total_module_count": total, "memory_slot_count": int(ma.value)},
                                     recommended_action="reduce_modules_or_change_motherboard"))
        else:
            findings.append(_finding(rule_id="ram_mb.module_slots", rule_version="1", result=RESULT_REQUIRES_VERIFICATION, severity=SEVERITY_WARNING,
                                     component_ids=cids, attributes_compared=["module_count", "memory_slot_count"],
                                     evidence={"total_module_count": total, "ram_components": [{"id": rid, "attr": _ev(a)} for rid, a in mod_attrs], "motherboard": _ev(ma)},
                                     message_key="compat.ram_mb.module_slots.requires_verification",
                                     message_params={"total_module_count": total, "memory_slot_count": int(ma.value), "apparent_conflict": exceeds},
                                     recommended_action="verify_attributes_or_official_support"))

    return findings, rules_evaluated
