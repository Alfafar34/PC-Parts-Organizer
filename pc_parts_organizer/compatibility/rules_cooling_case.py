"""Cooling <-> Case compatibility rules (T17.5): air cooler height / liquid OOS."""

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

RULESET = "t17.5-cooling-case-v1"


def _ev(attr):
    return {
        "key": attr.key,
        "value": attr.value,
        "unit": attr.unit,
        "source": attr.source,
        "confidence": attr.confidence,
        "verification_status": attr.verification_status,
        "evidence_ref": attr.evidence_ref,
        "verified_at": attr.verified_at,
    }


def evaluate_cooling_case(ctx):
    findings = []
    case = ctx.components_by_category.get("Case", [None])[0]
    coolings = ctx.components_by_category.get("Cooling", [])
    if case is None or not coolings:
        return findings, 0
    cp = ctx.profiles_by_component_id.get(case.id)
    rules_evaluated = 0
    for cooler in coolings:
        cop = ctx.profiles_by_component_id.get(cooler.id)
        ctype_attr = get_attr(cop, "cooler_type")
        ctype = ctype_attr.value if ctype_attr is not None else None
        cids = [cooler.id, case.id]
        if ctype in ("case_fan", "other"):
            continue  # no CPU cooler height requirement
        if ctype in ("aio_cpu_cooler", "custom_loop_cpu_cooler"):
            # liquid: no air height rule; radiator/mounting out of scope
            findings.append(_finding(
                rule_id="cooling_case.liquid_mounting_scope", rule_version="1", result=RESULT_REQUIRES_VERIFICATION, severity=SEVERITY_WARNING,
                component_ids=cids, attributes_compared=["cooler_type"],
                evidence={"cooling": _ev(ctype_attr) if ctype_attr else None},
                message_key="compat.cooling_case.liquid_out_of_scope",
                message_params={"cooler_type": ctype},
                recommended_action="verify_radiator_mounting_documentation",
            ))
            continue
        if ctype != "air_cpu_cooler":
            # unknown/undeclared type: cannot safely apply height rule or assume liquid
            if ctype_attr is None:
                findings.append(_finding(
                    rule_id="cooling_case.air_cooler_height", rule_version="1", result=RESULT_INSUFFICIENT_DATA, severity=SEVERITY_WARNING,
                    component_ids=cids, attributes_compared=["cooler_type", "cooler_height_mm", "max_cpu_cooler_height_mm"],
                    evidence={"cooling": None},
                    message_key="compat.cooling_case.air_cooler_height.insufficient_data",
                    message_params={"reason": "cooler_type_missing"},
                    missing_information=[f"cooling[{cooler.id}].cooler_type"], recommended_action="provide_verified_attributes",
                ))
            continue
        # air_cpu_cooler
        rules_evaluated += 1
        ha = get_attr(cop, "cooler_height_mm")
        ca = get_attr(cp, "max_cpu_cooler_height_mm")
        if ha is None or ca is None:
            missing = []
            if ha is None:
                missing.append(f"cooling[{cooler.id}].cooler_height_mm")
            if ca is None:
                missing.append("case.max_cpu_cooler_height_mm")
            findings.append(_finding(
                rule_id="cooling_case.air_cooler_height", rule_version="1", result=RESULT_INSUFFICIENT_DATA, severity=SEVERITY_WARNING,
                component_ids=cids, attributes_compared=["cooler_height_mm", "max_cpu_cooler_height_mm"],
                evidence={"cooling": _ev(ha) if ha else None, "case": _ev(ca) if ca else None},
                message_key="compat.cooling_case.air_cooler_height.insufficient_data",
                missing_information=missing, recommended_action="provide_verified_attributes",
            ))
            continue
        fits = int(ha.value) <= int(ca.value)
        both_ok = attr_verified(ha) and attr_verified(ca) and not attr_low_confidence(ha) and not attr_low_confidence(ca)
        if fits and both_ok:
            findings.append(_finding(
                rule_id="cooling_case.air_cooler_height", rule_version="1", result=RESULT_COMPATIBLE, severity=SEVERITY_INFO,
                component_ids=cids, attributes_compared=["cooler_height_mm", "max_cpu_cooler_height_mm"],
                evidence={"cooling": _ev(ha), "case": _ev(ca)},
                message_key="compat.cooling_case.air_cooler_height.compatible",
                message_params={"cooler_height_mm": int(ha.value), "max_cpu_cooler_height_mm": int(ca.value)},
            ))
        elif not fits and both_ok:
            findings.append(_finding(
                rule_id="cooling_case.air_cooler_height", rule_version="1", result=RESULT_INCOMPATIBLE, severity=SEVERITY_CRITICAL,
                component_ids=cids, attributes_compared=["cooler_height_mm", "max_cpu_cooler_height_mm"],
                evidence={"cooling": _ev(ha), "case": _ev(ca)},
                message_key="compat.cooling_case.air_cooler_height.incompatible",
                message_params={"cooler_height_mm": int(ha.value), "max_cpu_cooler_height_mm": int(ca.value)},
                recommended_action="use_shorter_cooler_or_larger_case",
            ))
        else:
            findings.append(_finding(
                rule_id="cooling_case.air_cooler_height", rule_version="1", result=RESULT_REQUIRES_VERIFICATION, severity=SEVERITY_WARNING,
                component_ids=cids, attributes_compared=["cooler_height_mm", "max_cpu_cooler_height_mm"],
                evidence={"cooling": _ev(ha), "case": _ev(ca)},
                message_key="compat.cooling_case.air_cooler_height.requires_verification",
                message_params={"cooler_height_mm": int(ha.value), "max_cpu_cooler_height_mm": int(ca.value), "apparent_conflict": not fits},
                recommended_action="verify_attributes_or_official_support",
            ))
    return findings, rules_evaluated
