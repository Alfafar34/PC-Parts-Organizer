"""PSU <-> Case compatibility rules (T17.12): physical form factor only.

Descriptive mounting check. Compares the declared PSU form factor against the
case's declared list of supported PSU form factors. No electrical validation:
no power/current/margins/transients, no connectors/pinout/modular
interchangeability (see rules_psu_connectors.py), no depth/cable-clearance
geometry (reported as not-evaluated limitations by the engine).

Semantics (mirrors rules_mb_case.py T17.11-R1):
- Exact recognized match, both verified-high => compatible (descriptive).
- Recognized mismatch with no unresolvable entry, both verified-high =>
  incompatible/critical (the declared support demonstrably excludes it).
- "Other" on the PSU side, or "Other" anywhere in the case list without an
  exact match => requires_verification, never decisive either way.
- "Proprietary" on either side => requires_verification (mounting needs
  model-specific documentation; even Proprietary==Proprietary proves nothing).
- SFX/SFX-L cross without exact match => requires_verification, never
  incompatible: same mounting pattern and width, only depth differs (~30mm),
  and case depth/cage geometry is not modeled, so physical exclusion cannot
  be demonstrated from the declaration alone.
- Anything missing/unverified/low-confidence => insufficient_data or
  requires_verification, never critical.

Ambiguous participants (multiple PSUs or cases) are never compared; the
caller only invokes this rule with exactly one of each.
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

RULESET = "t17.12-psu-case-v1"

# Same mounting pattern, different depth. Cross pairs prove nothing alone.
_SFX_FAMILY = frozenset({"SFX", "SFX-L"})


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


def evaluate_psu_case(ctx):
    findings = []
    psu = ctx.components_by_category.get("PSU", [None])[0]
    case = ctx.components_by_category.get("Case", [None])[0]
    if psu is None or case is None:
        return findings, 0
    psup = ctx.profiles_by_component_id.get(psu.id)
    cp = ctx.profiles_by_component_id.get(case.id)
    cids = [psu.id, case.id]
    rules_evaluated = 1

    fa = get_attr(psup, "psu_form_factor")
    sa = get_attr(cp, "supported_psu_form_factors")
    if fa is None or sa is None:
        missing = []
        if fa is None:
            missing.append("psu.psu_form_factor")
        if sa is None:
            missing.append("case.supported_psu_form_factors")
        findings.append(_finding(
            rule_id="psu_case.form_factor", rule_version="1", result=RESULT_INSUFFICIENT_DATA, severity=SEVERITY_WARNING,
            component_ids=cids, attributes_compared=["psu_form_factor", "supported_psu_form_factors"],
            evidence={"psu": _ev(fa) if fa else None, "case": _ev(sa) if sa else None},
            message_key="compat.psu_case.form_factor.insufficient_data", missing_information=missing,
            recommended_action="provide_verified_attributes",
        ))
        return findings, rules_evaluated

    supported = list(sa.value) if isinstance(sa.value, (list, tuple)) else []
    ff = fa.value
    included = ff in supported
    both_verified_high = attr_verified(fa) and attr_verified(sa) and not attr_low_confidence(fa) and not attr_low_confidence(sa)

    # Other never allows confirmed compatibility, nor confirmed incompatibility.
    if ff == "Other":
        findings.append(_finding(
            rule_id="psu_case.form_factor", rule_version="1", result=RESULT_REQUIRES_VERIFICATION, severity=SEVERITY_WARNING,
            component_ids=cids, attributes_compared=["psu_form_factor", "supported_psu_form_factors"],
            evidence={"psu": _ev(fa), "case": _ev(sa)},
            message_key="compat.psu_case.form_factor.requires_verification",
            message_params={"form_factor": ff, "supported": supported, "reason": "other_not_confirmable", "apparent_conflict": not included},
            recommended_action="verify_physical_compatibility",
        ))
        return findings, rules_evaluated

    # Proprietary mounting needs model-specific documentation; never decisive.
    if ff == "Proprietary" or "Proprietary" in supported:
        findings.append(_finding(
            rule_id="psu_case.form_factor", rule_version="1", result=RESULT_REQUIRES_VERIFICATION, severity=SEVERITY_WARNING,
            component_ids=cids, attributes_compared=["psu_form_factor", "supported_psu_form_factors"],
            evidence={"psu": _ev(fa), "case": _ev(sa)},
            message_key="compat.psu_case.form_factor.requires_verification",
            message_params={"form_factor": ff, "supported": supported, "reason": "proprietary_requires_specific_documentation", "apparent_match": included, "apparent_conflict": not included},
            recommended_action="verify_specific_mounting_documentation",
        ))
        return findings, rules_evaluated

    if included and both_verified_high:
        findings.append(_finding(
            rule_id="psu_case.form_factor", rule_version="1", result=RESULT_COMPATIBLE, severity=SEVERITY_INFO,
            component_ids=cids, attributes_compared=["psu_form_factor", "supported_psu_form_factors"],
            evidence={"psu": _ev(fa), "case": _ev(sa)},
            message_key="compat.psu_case.form_factor.compatible",
            message_params={"form_factor": ff},
        ))
    elif not included and "Other" in supported and both_verified_high:
        # An unresolvable entry cannot prove absence of a matching format.
        findings.append(_finding(
            rule_id="psu_case.form_factor", rule_version="1", result=RESULT_REQUIRES_VERIFICATION, severity=SEVERITY_WARNING,
            component_ids=cids, attributes_compared=["psu_form_factor", "supported_psu_form_factors"],
            evidence={"psu": _ev(fa), "case": _ev(sa)},
            message_key="compat.psu_case.form_factor.requires_verification",
            message_params={"form_factor": ff, "supported": supported, "reason": "other_not_confirmable", "apparent_conflict": not included},
            recommended_action="verify_physical_compatibility",
        ))
    elif (not included and both_verified_high and ff in _SFX_FAMILY
            and _SFX_FAMILY.intersection(supported)):
        # Any SFX-family member declared without an exact match: SFX and SFX-L
        # share mount and width and only differ in depth, which is not modeled,
        # so physical exclusion cannot be demonstrated from the declaration.
        findings.append(_finding(
            rule_id="psu_case.form_factor", rule_version="1", result=RESULT_REQUIRES_VERIFICATION, severity=SEVERITY_WARNING,
            component_ids=cids, attributes_compared=["psu_form_factor", "supported_psu_form_factors"],
            evidence={"psu": _ev(fa), "case": _ev(sa)},
            message_key="compat.psu_case.form_factor.requires_verification",
            message_params={"form_factor": ff, "supported": supported, "reason": "sfx_sfxl_requires_manual_check", "apparent_conflict": not included},
            recommended_action="verify_physical_compatibility",
        ))
    elif not included and both_verified_high:
        findings.append(_finding(
            rule_id="psu_case.form_factor", rule_version="1", result=RESULT_INCOMPATIBLE, severity=SEVERITY_CRITICAL,
            component_ids=cids, attributes_compared=["psu_form_factor", "supported_psu_form_factors"],
            evidence={"psu": _ev(fa), "case": _ev(sa)},
            message_key="compat.psu_case.form_factor.incompatible",
            message_params={"form_factor": ff, "supported": supported},
            recommended_action="use_supported_psu_or_case",
        ))
    else:
        findings.append(_finding(
            rule_id="psu_case.form_factor", rule_version="1", result=RESULT_REQUIRES_VERIFICATION, severity=SEVERITY_WARNING,
            component_ids=cids, attributes_compared=["psu_form_factor", "supported_psu_form_factors"],
            evidence={"psu": _ev(fa), "case": _ev(sa)},
            message_key="compat.psu_case.form_factor.requires_verification",
            message_params={"form_factor": ff, "supported": supported, "apparent_conflict": not included, "reason": "attributes_not_verified"},
            recommended_action="verify_attributes_or_official_support",
        ))
    return findings, rules_evaluated
