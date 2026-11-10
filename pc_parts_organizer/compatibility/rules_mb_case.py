"""Motherboard <-> Case compatibility rules (T17.3)."""

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

RULESET = "t17.3-mb-case-v1"


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


def evaluate_mb_case(ctx):
    findings = []
    mb = ctx.components_by_category.get("Motherboard", [None])[0]
    case = ctx.components_by_category.get("Case", [None])[0]
    if mb is None or case is None:
        return findings, 0
    mbp = ctx.profiles_by_component_id.get(mb.id)
    cp = ctx.profiles_by_component_id.get(case.id)
    cids = [mb.id, case.id]
    rules_evaluated = 1

    fa = get_attr(mbp, "form_factor")
    sa = get_attr(cp, "supported_motherboard_form_factors")
    if fa is None or sa is None:
        missing = []
        if fa is None:
            missing.append("motherboard.form_factor")
        if sa is None:
            missing.append("case.supported_motherboard_form_factors")
        findings.append(_finding(
            rule_id="mb_case.form_factor", rule_version="1", result=RESULT_INSUFFICIENT_DATA, severity=SEVERITY_WARNING,
            component_ids=cids, attributes_compared=["form_factor", "supported_motherboard_form_factors"],
            evidence={"motherboard": _ev(fa) if fa else None, "case": _ev(sa) if sa else None},
            message_key="compat.mb_case.form_factor.insufficient_data", missing_information=missing,
            recommended_action="provide_verified_attributes",
        ))
        return findings, rules_evaluated

    supported = list(sa.value) if isinstance(sa.value, (list, tuple)) else []
    ff = fa.value
    included = ff in supported
    both_verified_high = attr_verified(fa) and attr_verified(sa) and not attr_low_confidence(fa) and not attr_low_confidence(sa)

    # Other never allows confirmed compatibility, nor confirmed incompatibility:
    # an unresolvable entry cannot prove absence of a matching format.
    if ff == "Other":
        findings.append(_finding(
            rule_id="mb_case.form_factor", rule_version="1", result=RESULT_REQUIRES_VERIFICATION, severity=SEVERITY_WARNING,
            component_ids=cids, attributes_compared=["form_factor", "supported_motherboard_form_factors"],
            evidence={"motherboard": _ev(fa), "case": _ev(sa)},
            message_key="compat.mb_case.form_factor.requires_verification",
            message_params={"form_factor": ff, "supported": supported, "reason": "other_not_confirmable", "apparent_conflict": not included},
            recommended_action="verify_physical_compatibility",
        ))
        return findings, rules_evaluated

    # Proprietary requires caution: no confirmed compatibility without specific model/mount docs
    if ff == "Proprietary" or "Proprietary" in supported:
        # Even if "included", cannot confirm without specific documentation of model+mount.
        findings.append(_finding(
            rule_id="mb_case.form_factor", rule_version="1", result=RESULT_REQUIRES_VERIFICATION, severity=SEVERITY_WARNING,
            component_ids=cids, attributes_compared=["form_factor", "supported_motherboard_form_factors"],
            evidence={"motherboard": _ev(fa), "case": _ev(sa)},
            message_key="compat.mb_case.form_factor.requires_verification",
            message_params={"form_factor": ff, "supported": supported, "reason": "proprietary_requires_specific_documentation", "apparent_match": included, "apparent_conflict": not included},
            recommended_action="verify_specific_mounting_documentation",
        ))
        return findings, rules_evaluated

    if included and both_verified_high:
        findings.append(_finding(
            rule_id="mb_case.form_factor", rule_version="1", result=RESULT_COMPATIBLE, severity=SEVERITY_INFO,
            component_ids=cids, attributes_compared=["form_factor", "supported_motherboard_form_factors"],
            evidence={"motherboard": _ev(fa), "case": _ev(sa)},
            message_key="compat.mb_case.form_factor.compatible",
            message_params={"form_factor": ff},
        ))
    elif not included and "Other" in supported and both_verified_high:
        # An unresolvable entry cannot prove absence: the unknown formats might
        # include this board. Never incompatible on this basis.
        findings.append(_finding(
            rule_id="mb_case.form_factor", rule_version="1", result=RESULT_REQUIRES_VERIFICATION, severity=SEVERITY_WARNING,
            component_ids=cids, attributes_compared=["form_factor", "supported_motherboard_form_factors"],
            evidence={"motherboard": _ev(fa), "case": _ev(sa)},
            message_key="compat.mb_case.form_factor.requires_verification",
            message_params={"form_factor": ff, "supported": supported, "reason": "other_not_confirmable", "apparent_conflict": not included},
            recommended_action="verify_physical_compatibility",
        ))
    elif not included and both_verified_high:
        findings.append(_finding(
            rule_id="mb_case.form_factor", rule_version="1", result=RESULT_INCOMPATIBLE, severity=SEVERITY_CRITICAL,
            component_ids=cids, attributes_compared=["form_factor", "supported_motherboard_form_factors"],
            evidence={"motherboard": _ev(fa), "case": _ev(sa)},
            message_key="compat.mb_case.form_factor.incompatible",
            message_params={"form_factor": ff, "supported": supported},
            recommended_action="use_supported_case_or_motherboard",
        ))
    else:
        findings.append(_finding(
            rule_id="mb_case.form_factor", rule_version="1", result=RESULT_REQUIRES_VERIFICATION, severity=SEVERITY_WARNING,
            component_ids=cids, attributes_compared=["form_factor", "supported_motherboard_form_factors"],
            evidence={"motherboard": _ev(fa), "case": _ev(sa)},
            message_key="compat.mb_case.form_factor.requires_verification",
            message_params={"form_factor": ff, "supported": supported, "apparent_conflict": not included, "reason": "attributes_not_verified"},
            recommended_action="verify_attributes_or_official_support",
        ))
    return findings, rules_evaluated
