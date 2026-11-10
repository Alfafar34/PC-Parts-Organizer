"""GPU <-> Case compatibility rules (T17.5): card length only."""

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

RULESET = "t17.5-gpu-case-v1"


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


def evaluate_gpu_case(ctx):
    findings = []
    case = ctx.components_by_category.get("Case", [None])[0]
    gpus = ctx.components_by_category.get("GPU", [])
    if case is None or not gpus:
        return findings, 0
    cp = ctx.profiles_by_component_id.get(case.id)
    rules_evaluated = 0
    for gpu in gpus:
        gp = ctx.profiles_by_component_id.get(gpu.id)
        cids = [gpu.id, case.id]
        rules_evaluated += 1
        ga = get_attr(gp, "card_length_mm")
        ca = get_attr(cp, "max_gpu_length_mm")
        if ga is None or ca is None:
            missing = []
            if ga is None:
                missing.append(f"gpu[{gpu.id}].card_length_mm")
            if ca is None:
                missing.append("case.max_gpu_length_mm")
            findings.append(_finding(
                rule_id="gpu_case.max_length", rule_version="1", result=RESULT_INSUFFICIENT_DATA, severity=SEVERITY_WARNING,
                component_ids=cids, attributes_compared=["card_length_mm", "max_gpu_length_mm"],
                evidence={"gpu": _ev(ga) if ga else None, "case": _ev(ca) if ca else None},
                message_key="compat.gpu_case.max_length.insufficient_data",
                message_params={"gpu_id": gpu.id},
                missing_information=missing, recommended_action="provide_verified_attributes",
            ))
            continue
        fits = int(ga.value) <= int(ca.value)
        both_ok = attr_verified(ga) and attr_verified(ca) and not attr_low_confidence(ga) and not attr_low_confidence(ca)
        if fits and both_ok:
            findings.append(_finding(
                rule_id="gpu_case.max_length", rule_version="1", result=RESULT_COMPATIBLE, severity=SEVERITY_INFO,
                component_ids=cids, attributes_compared=["card_length_mm", "max_gpu_length_mm"],
                evidence={"gpu": _ev(ga), "case": _ev(ca)},
                message_key="compat.gpu_case.max_length.compatible",
                message_params={"card_length_mm": int(ga.value), "max_gpu_length_mm": int(ca.value)},
            ))
        elif not fits and both_ok:
            findings.append(_finding(
                rule_id="gpu_case.max_length", rule_version="1", result=RESULT_INCOMPATIBLE, severity=SEVERITY_CRITICAL,
                component_ids=cids, attributes_compared=["card_length_mm", "max_gpu_length_mm"],
                evidence={"gpu": _ev(ga), "case": _ev(ca)},
                message_key="compat.gpu_case.max_length.incompatible",
                message_params={"card_length_mm": int(ga.value), "max_gpu_length_mm": int(ca.value)},
                recommended_action="use_shorter_gpu_or_larger_case",
            ))
        else:
            findings.append(_finding(
                rule_id="gpu_case.max_length", rule_version="1", result=RESULT_REQUIRES_VERIFICATION, severity=SEVERITY_WARNING,
                component_ids=cids, attributes_compared=["card_length_mm", "max_gpu_length_mm"],
                evidence={"gpu": _ev(ga), "case": _ev(ca)},
                message_key="compat.gpu_case.max_length.requires_verification",
                message_params={"card_length_mm": int(ga.value), "max_gpu_length_mm": int(ca.value), "apparent_conflict": not fits},
                recommended_action="verify_attributes_or_official_support",
            ))
    return findings, rules_evaluated
