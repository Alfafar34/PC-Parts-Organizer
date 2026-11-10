"""CPU <-> Motherboard socket visibility (T17.11).

Descriptive only. This rule NEVER emits compatible/incompatible and never uses
critical severity: a socket string declares a mechanical interface, not a boot
guarantee (chipset, BIOS/firmware, power delivery and platform generation are
not modeled). No alias or equivalence is ever inferred: comparison is exact
match on the normalized designation. No slot/port assignment is performed.
"""

from __future__ import annotations

from .engine import _finding, attr_low_confidence, attr_verified, get_attr
from .models import (
    RESULT_INSUFFICIENT_DATA,
    RESULT_REQUIRES_VERIFICATION,
    SEVERITY_WARNING,
)

RULESET = "t17.11-cpu-mb-v1"

_UNRESOLVABLE = ("OTHER", "PROPRIETARY")


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


def _is_unresolvable(value) -> bool:
    return isinstance(value, str) and value.strip().upper() in _UNRESOLVABLE


def evaluate_cpu_mb_visibility(ctx):
    """Compare declared CPU and motherboard sockets descriptively.

    Returns ([findings], rules_evaluated). rules_evaluated counts value
    comparisons only (R2.1 contract): 1 when both socket values are present,
    0 for missing components, multiplicity guards and absent attributes.
    """
    findings = []
    cpus = ctx.components_by_category.get("CPU", [])
    mbs = ctx.components_by_category.get("Motherboard", [])
    # Missing components or ambiguity: existing engine guards apply; this rule
    # stays silent (no invented participants, no arbitrary pairing).
    if not cpus or not mbs or len(cpus) > 1 or len(mbs) > 1:
        return findings, 0
    cpu = cpus[0]
    mb = mbs[0]
    cids = [cpu.id, mb.id]
    attrs_compared = ["socket_designation"]
    cprof = ctx.profiles_by_component_id.get(cpu.id)
    mbp = ctx.profiles_by_component_id.get(mb.id)
    csock = get_attr(cprof, "socket_designation")
    msock = get_attr(mbp, "socket_designation")
    cval = csock.value if csock is not None else None
    mval = msock.value if msock is not None else None
    evidence = {
        "cpu": _attr_meta(csock),
        "motherboard": _attr_meta(msock),
        "cpu_socket": cval,
        "motherboard_socket": mval,
    }
    params = {"cpu_socket": cval, "motherboard_socket": mval}
    if csock is None or msock is None:
        missing = []
        if csock is None:
            missing.append(f"cpu[{cpu.id}].socket_designation")
        if msock is None:
            missing.append(f"motherboard[{mb.id}].socket_designation")
        findings.append(_finding(
            rule_id="cpu_mb.socket_visibility", rule_version="1", result=RESULT_INSUFFICIENT_DATA, severity=SEVERITY_WARNING,
            component_ids=cids, attributes_compared=attrs_compared, evidence=evidence,
            message_key="compat.cpu_mb.socket_visibility.insufficient_data",
            message_params=params, missing_information=sorted(set(missing)),
            recommended_action="provide_verified_cpu_mb_sockets",
        ))
        return findings, 0
    c_ok = attr_verified(csock) and not attr_low_confidence(csock)
    m_ok = attr_verified(msock) and not attr_low_confidence(msock)
    if not c_ok or not m_ok:
        if (csock is not None and not attr_verified(csock)) or (msock is not None and not attr_verified(msock)):
            reason = "socket_not_verified"
        else:
            reason = "socket_low_confidence"
        findings.append(_finding(
            rule_id="cpu_mb.socket_visibility", rule_version="1", result=RESULT_REQUIRES_VERIFICATION, severity=SEVERITY_WARNING,
            component_ids=cids, attributes_compared=attrs_compared, evidence=evidence,
            message_key="compat.cpu_mb.socket_visibility.requires_verification",
            message_params={**params, "reason": reason, "match": None},
            recommended_action="verify_cpu_motherboard_socket",
        ))
        return findings, 1
    if _is_unresolvable(cval) or _is_unresolvable(mval):
        findings.append(_finding(
            rule_id="cpu_mb.socket_visibility", rule_version="1", result=RESULT_REQUIRES_VERIFICATION, severity=SEVERITY_WARNING,
            component_ids=cids, attributes_compared=attrs_compared, evidence=evidence,
            message_key="compat.cpu_mb.socket_visibility.requires_verification",
            message_params={**params, "reason": "socket_not_resolvable", "match": None},
            recommended_action="verify_cpu_motherboard_socket",
        ))
        return findings, 1
    match = (cval == mval)
    reason = "socket_match_pending_platform" if match else "socket_mismatch_unresolved"
    findings.append(_finding(
        rule_id="cpu_mb.socket_visibility", rule_version="1", result=RESULT_REQUIRES_VERIFICATION, severity=SEVERITY_WARNING,
        component_ids=cids, attributes_compared=attrs_compared, evidence=evidence,
        message_key="compat.cpu_mb.socket_visibility.requires_verification",
        message_params={**params, "reason": reason, "match": match},
        recommended_action="verify_cpu_motherboard_socket",
    ))
    return findings, 1
