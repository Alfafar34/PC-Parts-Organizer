"""PSU connector inventory evaluation (T17.8b): descriptive availability only.

Pure/deterministic. Compares declared power-connector requirements (Motherboard/GPU)
against declared PSU cable assembly component-side ends. NO electrical validation:
no wattage/margin/current/transients/pinout/modular interchangeability/assignment/
solver. Exact connector_kind matching only (no EPS<->PCIe, no 12VHPWR<->12V-2x6, etc.).

Exhaustiveness: a verified collection does NOT formally prove all physical PSU cables
are recorded. Sufficient declared eligible ends => positive descriptive availability
(dimension-limited). Insufficient declared eligible ends => requires_verification
(never incompatible from absence-in-collection without formal exhaustiveness).
"""
from __future__ import annotations

from collections import Counter, defaultdict

from .engine import _finding, attr_low_confidence, attr_verified, get_attr
from .storage_classification import is_collection_complete
from .models import (
    RESULT_COMPATIBLE,
    RESULT_INCOMPATIBLE,
    RESULT_INSUFFICIENT_DATA,
    RESULT_REQUIRES_VERIFICATION,
    SEVERITY_CRITICAL,
    SEVERITY_INFO,
    SEVERITY_WARNING,
)

RULESET = "t17.8-psu-connectors-v1"

_ELIGIBLE_NATIVE = {"fixed_native", "modular_native"}
_UNRESOLVED = {"manufacturer_approved_adapter", "third_party_adapter", "unknown"}


def _attr_meta(attr):
    return None if attr is None else {
        "key": attr.key, "value": getattr(attr, "value", None), "unit": getattr(attr, "unit", None),
        "source": getattr(attr, "source", None), "confidence": getattr(attr, "confidence", None),
        "verification_status": getattr(attr, "verification_status", None),
        "evidence_ref": getattr(attr, "evidence_ref", None), "verified_at": getattr(attr, "verified_at", None),
        "collection_completeness": getattr(attr, "collection_completeness", "unknown"),
        "completeness_scope": getattr(attr, "completeness_scope", None),
    }


def _req_meta(req):
    return {"connector_kind": req.connector_kind, "quantity": req.quantity, "required": req.required, "notes": req.notes, "schema_version": req.schema_version}


def _end_meta(cable, end):
    return {"cable_id": cable.cable_id, "assembly_type": cable.assembly_type, "psu_side_connector_id": cable.psu_side_connector_id,
            "approved_psu_model": cable.approved_psu_model, "approval_reference": cable.approval_reference,
            "end_id": end.end_id, "connector_kind": end.connector_kind, "split_group_id": end.split_group_id}


def _count_requirements(reqs):
    required = Counter(); optional = Counter()
    for r in (reqs or ()):
        t = required if r.required else optional
        t[r.connector_kind] += int(r.quantity)
    return required, optional


def _analyze_assemblies(attr):
    assemblies = list(getattr(attr, "value", ()) or ()) if attr is not None else []
    eligible = Counter(); eligible_meta = []; unresolved = []; issues = []
    for cable in assemblies:
        if cable.assembly_type in _ELIGIBLE_NATIVE:
            for end in cable.component_side_ends:
                eligible[end.connector_kind] += 1
                eligible_meta.append(_end_meta(cable, end))
        elif cable.assembly_type in _UNRESOLVED:
            unresolved.append({"cable_id": cable.cable_id, "assembly_type": cable.assembly_type,
                               "approved_psu_model": cable.approved_psu_model, "approval_reference": cable.approval_reference,
                               "ends": [{"end_id": e.end_id, "connector_kind": e.connector_kind, "split_group_id": e.split_group_id} for e in cable.component_side_ends]})
            if cable.assembly_type == "manufacturer_approved_adapter":
                issues.append("approved_adapter_not_unequivocally_validated")
            elif cable.assembly_type == "third_party_adapter":
                issues.append("third_party_adapter_not_counted")
            else:
                issues.append("unknown_assembly_not_counted")
        else:
            issues.append("unknown_assembly_not_counted")
    return assemblies, eligible, eligible_meta, unresolved, sorted(set(issues))


def _dimension(ctx, psu, psu_profile, psu_cable_attr, label, req_attr_key, component, component_category):
    findings = []
    if component is None or psu is None:
        return findings
    cprof = ctx.profiles_by_component_id.get(component.id)
    req_attr = get_attr(cprof, req_attr_key)
    cids = [component.id, psu.id]
    attrs_compared = [req_attr_key, "power_cable_assemblies"]
    if req_attr is None:
        findings.append(_finding(rule_id=f"psu_{label}.requirements_missing", rule_version="1", result=RESULT_INSUFFICIENT_DATA, severity=SEVERITY_WARNING,
                                 component_ids=cids, attributes_compared=attrs_compared,
                                 evidence={"requirements": None, "power_cable_assemblies": _attr_meta(psu_cable_attr)},
                                 message_key=f"compat.psu_{label}.requirements_missing",
                                 missing_information=[f"{component_category}.{req_attr_key}"],
                                 recommended_action=f"provide_verified_{label}_power_requirements"))
        return findings
    if psu_cable_attr is None:
        findings.append(_finding(rule_id=f"psu_{label}.psu_inventory_missing", rule_version="1", result=RESULT_INSUFFICIENT_DATA, severity=SEVERITY_WARNING,
                                 component_ids=cids, attributes_compared=attrs_compared,
                                 evidence={"requirements": _attr_meta(req_attr), "power_cable_assemblies": None},
                                 message_key=f"compat.psu_{label}.psu_inventory_missing",
                                 missing_information=["psu.power_cable_assemblies"],
                                 recommended_action="provide_verified_psu_cable_inventory"))
        return findings
    reqs = list(getattr(req_attr, "value", ()) or ())
    required, optional = _count_requirements(reqs)
    assemblies, eligible, eligible_meta, unresolved, issues = _analyze_assemblies(psu_cable_attr)
    req_verified = attr_verified(req_attr) and not attr_low_confidence(req_attr)
    inv_verified = attr_verified(psu_cable_attr) and not attr_low_confidence(psu_cable_attr)
    inv_complete = is_collection_complete(psu_cable_attr)
    evidence = {"requirements": {"collection": _attr_meta(req_attr), "items": [_req_meta(r) for r in reqs]},
                "power_cable_assemblies": {"collection": _attr_meta(psu_cable_attr), "declared_eligible_end_count": sum(eligible.values()),
                                            "eligible_ends": eligible_meta, "unresolved_assemblies": unresolved}}
    params = {"component_id": component.id, "required": dict(required), "optional": dict(optional), "eligible": dict(eligible)}
    missing_kinds = {k: (required[k] - eligible.get(k, 0)) for k in required if eligible.get(k, 0) < required[k]}
    if not required and optional:
        if req_verified and inv_verified:
            findings.append(_finding(rule_id=f"psu_{label}.connector_availability", rule_version="1", result=RESULT_COMPATIBLE, severity=SEVERITY_INFO,
                                     component_ids=cids, attributes_compared=attrs_compared, evidence=evidence,
                                     message_key=f"compat.psu_{label}.optional_only", message_params=params))
        else:
            findings.append(_finding(rule_id=f"psu_{label}.connector_availability", rule_version="1", result=RESULT_REQUIRES_VERIFICATION, severity=SEVERITY_WARNING,
                                     component_ids=cids, attributes_compared=attrs_compared, evidence=evidence,
                                     message_key=f"compat.psu_{label}.requires_verification",
                                     message_params={**params, "reason": "requirements_or_inventory_not_verified"},
                                     recommended_action="verify_psu_connectors_and_inventory"))
        return findings
    if not required and not optional:
        findings.append(_finding(rule_id=f"psu_{label}.requirements_empty", rule_version="1", result=RESULT_INSUFFICIENT_DATA, severity=SEVERITY_INFO,
                                 component_ids=cids, attributes_compared=attrs_compared, evidence=evidence,
                                 message_key=f"compat.psu_{label}.requirements_empty", message_params=params,
                                 missing_information=[f"{component_category}.{req_attr_key}"]))
        return findings
    if missing_kinds:
        if inv_complete and inv_verified and req_verified and not unresolved and not issues:
            findings.append(_finding(rule_id=f"psu_{label}.connector_availability", rule_version="1", result=RESULT_INCOMPATIBLE, severity=SEVERITY_CRITICAL,
                                     component_ids=cids, attributes_compared=attrs_compared, evidence=evidence,
                                     message_key=f"compat.psu_{label}.insufficient_complete_inventory",
                                     message_params={**params, "missing": missing_kinds},
                                     recommended_action="use_psu_with_sufficient_declared_connectors"))
        else:
            findings.append(_finding(rule_id=f"psu_{label}.connector_availability", rule_version="1", result=RESULT_REQUIRES_VERIFICATION, severity=SEVERITY_WARNING,
                                     component_ids=cids, attributes_compared=attrs_compared, evidence=evidence,
                                     message_key=f"compat.psu_{label}.insufficient_declared_inventory",
                                     message_params={**params, "missing": missing_kinds, "reason": "inventory_exhaustiveness_not_demonstrated"},
                                     recommended_action="verify_complete_psu_cable_inventory"))
        return findings
    if unresolved or issues or not req_verified or not inv_verified:
        findings.append(_finding(rule_id=f"psu_{label}.connector_availability", rule_version="1", result=RESULT_REQUIRES_VERIFICATION, severity=SEVERITY_WARNING,
                                 component_ids=cids, attributes_compared=attrs_compared, evidence=evidence,
                                 message_key=f"compat.psu_{label}.requires_verification",
                                 message_params={**params, "reason": issues[0] if issues else "requirements_or_inventory_not_verified"},
                                 recommended_action="verify_psu_connectors_and_inventory"))
        return findings
    findings.append(_finding(rule_id=f"psu_{label}.connector_availability", rule_version="1", result=RESULT_COMPATIBLE, severity=SEVERITY_INFO,
                             component_ids=cids, attributes_compared=attrs_compared, evidence=evidence,
                             message_key=f"compat.psu_{label}.connector_availability.compatible",
                             message_params=params))
    return findings


def evaluate_psu_connectors(ctx):
    """Evaluate PSU connector inventory availability (descriptive only)."""
    findings = []
    psus = ctx.components_by_category.get("PSU", [])
    mbs = ctx.components_by_category.get("Motherboard", [])
    gpus = ctx.components_by_category.get("GPU", [])
    if not psus or (not mbs and not gpus):
        return findings, 0
    if len(psus) > 1:
        findings.append(_finding(rule_id="psu_connectors.ambiguous_psu", rule_version="1", result=RESULT_INSUFFICIENT_DATA, severity=SEVERITY_INFO,
                                 component_ids=[p.id for p in psus], message_key="compat.psu_connectors.ambiguous_psu",
                                 missing_information=["single_psu"], recommended_action="select_single_psu"))
        return findings, 0
    psu = psus[0]
    psu_profile = ctx.profiles_by_component_id.get(psu.id)
    psu_cable_attr = get_attr(psu_profile, "power_cable_assemblies")
    rules_evaluated = 0
    mb = mbs[0] if len(mbs) == 1 else None
    gpu = gpus[0] if len(gpus) == 1 else None
    if mb is not None:
        findings.extend(_dimension(ctx, psu, psu_profile, psu_cable_attr, "mb", "motherboard_power_connectors_required", mb, "Motherboard"))
        rules_evaluated += 1
    if gpu is not None:
        findings.extend(_dimension(ctx, psu, psu_profile, psu_cable_attr, "gpu", "gpu_power_connectors_required", gpu, "GPU"))
        rules_evaluated += 1
    # Joint aggregate view (MB+GPU required quantities vs eligible ends; each end counted once) - no assignment/solver.
    if mb is not None and gpu is not None and psu_cable_attr is not None:
        mb_req = get_attr(ctx.profiles_by_component_id.get(mb.id), "motherboard_power_connectors_required")
        gpu_req = get_attr(ctx.profiles_by_component_id.get(gpu.id), "gpu_power_connectors_required")
        if mb_req is not None and gpu_req is not None:
            req_mb, _ = _count_requirements(getattr(mb_req, "value", ()) or ())
            req_gpu, _ = _count_requirements(getattr(gpu_req, "value", ()) or ())
            total_req = Counter(req_mb) + Counter(req_gpu)
            _, eligible, eligible_meta, unresolved, issues = _analyze_assemblies(psu_cable_attr)
            missing = {k: total_req[k] - eligible.get(k, 0) for k in total_req if eligible.get(k, 0) < total_req[k]}
            cids = [mb.id, gpu.id, psu.id]
            evidence = {"total_required": dict(total_req), "eligible": dict(eligible), "eligible_ends": eligible_meta, "unresolved_assemblies": unresolved}
            params = {"total_required": dict(total_req), "eligible": dict(eligible), "missing": missing}
            joint_verified = (attr_verified(mb_req) and not attr_low_confidence(mb_req) and attr_verified(gpu_req) and not attr_low_confidence(gpu_req) and attr_verified(psu_cable_attr) and not attr_low_confidence(psu_cable_attr))
            joint_complete = is_collection_complete(psu_cable_attr)
            if missing:
                if joint_complete and joint_verified and not unresolved and not issues:
                    findings.append(_finding(rule_id="psu_joint.connector_availability", rule_version="1", result=RESULT_INCOMPATIBLE, severity=SEVERITY_CRITICAL,
                                             component_ids=cids, attributes_compared=["motherboard_power_connectors_required","gpu_power_connectors_required","power_cable_assemblies"],
                                             evidence=evidence, message_key="compat.psu_joint.insufficient_complete_inventory",
                                             message_params=params,
                                             recommended_action="use_psu_with_sufficient_declared_connectors"))
                else:
                    findings.append(_finding(rule_id="psu_joint.connector_availability", rule_version="1", result=RESULT_REQUIRES_VERIFICATION, severity=SEVERITY_WARNING,
                                             component_ids=cids, attributes_compared=["motherboard_power_connectors_required","gpu_power_connectors_required","power_cable_assemblies"],
                                             evidence=evidence, message_key="compat.psu_joint.insufficient_declared_inventory",
                                             message_params={**params, "reason": "inventory_exhaustiveness_not_demonstrated"},
                                             recommended_action="verify_complete_psu_cable_inventory"))
            elif unresolved or issues or not (attr_verified(mb_req) and not attr_low_confidence(mb_req) and attr_verified(gpu_req) and not attr_low_confidence(gpu_req) and attr_verified(psu_cable_attr) and not attr_low_confidence(psu_cable_attr)):
                findings.append(_finding(rule_id="psu_joint.connector_availability", rule_version="1", result=RESULT_REQUIRES_VERIFICATION, severity=SEVERITY_WARNING,
                                         component_ids=cids, attributes_compared=["motherboard_power_connectors_required","gpu_power_connectors_required","power_cable_assemblies"],
                                         evidence=evidence, message_key="compat.psu_joint.requires_verification",
                                         message_params={**params, "reason": issues[0] if issues else "requirements_or_inventory_not_verified"},
                                         recommended_action="verify_psu_connectors_and_inventory"))
            else:
                findings.append(_finding(rule_id="psu_joint.connector_availability", rule_version="1", result=RESULT_COMPATIBLE, severity=SEVERITY_INFO,
                                         component_ids=cids, attributes_compared=["motherboard_power_connectors_required","gpu_power_connectors_required","power_cable_assemblies"],
                                         evidence=evidence, message_key="compat.psu_joint.connector_availability.compatible",
                                         message_params=params))
            rules_evaluated += 1
    return findings, rules_evaluated
