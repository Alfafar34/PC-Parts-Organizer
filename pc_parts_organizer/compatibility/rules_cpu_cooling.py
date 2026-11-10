"""CPU <-> Cooling compatibility rules (T17.5): socket support only."""

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

RULESET = "t17.5-cpu-cooling-v1"
CPU_COOLER_TYPES = {"air_cpu_cooler", "aio_cpu_cooler", "custom_loop_cpu_cooler"}


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


def _is_cpu_cooler(component, profile) -> bool:
    if getattr(component, "category", "") != "Cooling":
        return False
    ta = get_attr(profile, "cooler_type")
    if ta is not None:
        return ta.value in CPU_COOLER_TYPES
    # without declared type, do not guess from name/specs; treat as non-confirmed CPU cooler candidate
    return False


def cpu_cooler_candidates(ctx):
    out = []
    for c in ctx.components_by_category.get("Cooling", []):
        p = ctx.profiles_by_component_id.get(c.id)
        if _is_cpu_cooler(c, p):
            out.append((c, p))
    return out


def evaluate_cpu_cooling(ctx):
    findings = []
    cpus = ctx.components_by_category.get("CPU", [])
    coolers = cpu_cooler_candidates(ctx)
    if not cpus or not coolers:
        return findings, 0
    rules_evaluated = 0
    for cpu in cpus:
        cup = ctx.profiles_by_component_id.get(cpu.id)
        for cooler, cop in coolers:
            rules_evaluated += 1
            cids = [cpu.id, cooler.id]
            sa = get_attr(cup, "socket_designation")
            ca = get_attr(cop, "supported_cpu_sockets")
            if sa is None or ca is None:
                missing = []
                if sa is None:
                    missing.append(f"cpu[{cpu.id}].socket_designation")
                if ca is None:
                    missing.append(f"cooling[{cooler.id}].supported_cpu_sockets")
                findings.append(_finding(
                    rule_id="cpu_cooling.socket_support", rule_version="1", result=RESULT_INSUFFICIENT_DATA, severity=SEVERITY_WARNING,
                    component_ids=cids, attributes_compared=["socket_designation", "supported_cpu_sockets"],
                    evidence={"cpu": _ev(sa) if sa else None, "cooling": _ev(ca) if ca else None},
                    message_key="compat.cpu_cooling.socket_support.insufficient_data",
                    missing_information=missing, recommended_action="provide_verified_attributes",
                ))
                continue
            supported = list(ca.value) if isinstance(ca.value, (list, tuple)) else []
            included = sa.value in supported
            both_ok = attr_verified(sa) and attr_verified(ca) and not attr_low_confidence(sa) and not attr_low_confidence(ca)
            if included and both_ok:
                findings.append(_finding(
                    rule_id="cpu_cooling.socket_support", rule_version="1", result=RESULT_COMPATIBLE, severity=SEVERITY_INFO,
                    component_ids=cids, attributes_compared=["socket_designation", "supported_cpu_sockets"],
                    evidence={"cpu": _ev(sa), "cooling": _ev(ca)},
                    message_key="compat.cpu_cooling.socket_support.compatible",
                    message_params={"socket_designation": sa.value},
                ))
            elif not included and both_ok:
                findings.append(_finding(
                    rule_id="cpu_cooling.socket_support", rule_version="1", result=RESULT_INCOMPATIBLE, severity=SEVERITY_CRITICAL,
                    component_ids=cids, attributes_compared=["socket_designation", "supported_cpu_sockets"],
                    evidence={"cpu": _ev(sa), "cooling": _ev(ca)},
                    message_key="compat.cpu_cooling.socket_support.incompatible",
                    message_params={"socket_designation": sa.value, "supported": supported},
                    recommended_action="use_socket_compatible_cooler",
                ))
            else:
                findings.append(_finding(
                    rule_id="cpu_cooling.socket_support", rule_version="1", result=RESULT_REQUIRES_VERIFICATION, severity=SEVERITY_WARNING,
                    component_ids=cids, attributes_compared=["socket_designation", "supported_cpu_sockets"],
                    evidence={"cpu": _ev(sa), "cooling": _ev(ca)},
                    message_key="compat.cpu_cooling.socket_support.requires_verification",
                    message_params={"socket_designation": sa.value, "supported": supported, "apparent_conflict": not included},
                    recommended_action="verify_attributes_or_official_support",
                ))
    return findings, rules_evaluated
