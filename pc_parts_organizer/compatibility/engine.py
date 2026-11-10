"""Deterministic compatibility engine (T17.3/T17.5). Pure; no I/O, no mutation."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

from pc_parts_organizer.models import Build
from pc_parts_organizer.technical_profiles import (
    TechnicalProfile,
    TechnicalProfileValidationError,
    validate_profile_for_category,
)

from .models import (
    ENGINE_RULESET_VERSION,
    RESULT_COMPATIBLE,
    RESULT_INCOMPATIBLE,
    RESULT_INSUFFICIENT_DATA,
    RESULT_REQUIRES_VERIFICATION,
    SEVERITY_CRITICAL,
    SEVERITY_INFO,
    SEVERITY_WARNING,
    CompatibilityFinding,
    CompatibilityReport,
    CompatibilityValidationError,
)

IMPLEMENTED_RELATIONS = (
    ("RAM", "Motherboard"), ("Motherboard", "Case"), ("GPU", "Case"), ("CPU", "Cooling"),
    ("Cooling", "Case"), ("Storage", "Motherboard"), ("Storage", "Case"),
    ("PSU", "Motherboard"), ("PSU", "GPU"), ("CPU", "Motherboard"), ("PSU", "Case"),
)
# categories with no implemented compatibility rules at all (PSU has partial connector-inventory rules in T17.8b)
FULLY_OUT_OF_SCOPE_CATEGORIES = ("Monitor", "Peripheral")


@dataclass(frozen=True)
class AnalysisContext:
    build_id: str
    components: tuple
    components_by_id: dict
    profiles_by_component_id: dict
    components_by_category: dict


def _finding(
    *,
    rule_id: str,
    rule_version: str,
    result: str,
    severity: str,
    component_ids: Iterable[str] = (),
    attributes_compared: Iterable[str] = (),
    evidence: dict | None = None,
    message_key: str,
    message_params: dict | None = None,
    missing_information: Iterable[str] = (),
    recommended_action: str = "",
) -> CompatibilityFinding:
    return CompatibilityFinding(
        rule_id=rule_id,
        rule_version=rule_version,
        result=result,
        severity=severity,
        component_ids=tuple(component_ids),
        attributes_compared=tuple(attributes_compared),
        evidence=evidence or {},
        message_key=message_key,
        message_params=message_params or {},
        missing_information=tuple(missing_information),
        recommended_action=recommended_action,
    )


def attr_verified(attr) -> bool:
    return getattr(attr, "verification_status", None) == "verified"


def attr_low_confidence(attr) -> bool:
    conf = getattr(attr, "confidence", "medium")
    src = getattr(attr, "source", "unknown")
    return conf == "low" or (src == "normalized_inferred" and conf != "high")


def get_attr(profile: TechnicalProfile | None, key: str):
    if profile is None:
        return None
    for a in profile.attributes:
        if a.key == key:
            return a
    return None


def build_context(build: Build, components, technical_profiles) -> AnalysisContext:
    if not isinstance(build, Build):
        raise CompatibilityValidationError("build must be a Build instance.")
    if not isinstance(components, (list, tuple)):
        raise CompatibilityValidationError("components must be a list.")
    if not isinstance(technical_profiles, (list, tuple)):
        raise CompatibilityValidationError("technical_profiles must be a list.")
    comp_map = {}
    for c in components:
        cid = getattr(c, "id", None)
        if not isinstance(cid, str):
            raise CompatibilityValidationError("component has invalid id.")
        if cid in comp_map:
            raise CompatibilityValidationError(f"Duplicate component id: {cid}")
        comp_map[cid] = c
    build_comp_ids = list(getattr(build, "component_ids", []) or [])
    resolved = []
    for cid in build_comp_ids:
        if cid not in comp_map:
            raise CompatibilityValidationError(f"Build references unknown component id: {cid}")
        resolved.append(comp_map[cid])
    profile_map = {}
    for p in technical_profiles:
        if not isinstance(p, TechnicalProfile):
            raise CompatibilityValidationError("technical_profiles must contain TechnicalProfile instances.")
        if p.component_id in profile_map:
            raise CompatibilityValidationError(f"Duplicate technical profile for component: {p.component_id}")
        if p.component_id not in comp_map:
            raise CompatibilityValidationError(f"Technical profile references component outside input: {p.component_id}")
        category = getattr(comp_map[p.component_id], "category", None)
        try:
            validate_profile_for_category(p, category)
        except TechnicalProfileValidationError as exc:
            raise CompatibilityValidationError(f"Technical profile incompatible with category: {exc}") from exc
        profile_map[p.component_id] = p
    by_cat: dict[str, list] = {}
    for c in resolved:
        by_cat.setdefault(getattr(c, "category", ""), []).append(c)
    for cat in by_cat:
        by_cat[cat] = sorted(by_cat[cat], key=lambda c: str(getattr(c, "id", "")))
    return AnalysisContext(
        build_id=build.id,
        components=tuple(resolved),
        components_by_id={c.id: c for c in resolved},
        profiles_by_component_id={k: profile_map[k] for k in sorted(profile_map) if k in {c.id for c in resolved}},
        components_by_category=by_cat,
    )


def global_result(findings: list[CompatibilityFinding], not_evaluated_relations: list[dict], has_applicable_scope: bool) -> str:
    has_incompat = any(f.result == RESULT_INCOMPATIBLE and f.severity == SEVERITY_CRITICAL for f in findings)
    if has_incompat:
        return RESULT_INCOMPATIBLE
    has_requires = any(f.result == RESULT_REQUIRES_VERIFICATION for f in findings)
    has_insufficient = any(f.result == RESULT_INSUFFICIENT_DATA for f in findings)
    if has_requires or not_evaluated_relations:
        return RESULT_REQUIRES_VERIFICATION
    if has_insufficient:
        return RESULT_INSUFFICIENT_DATA
    if not has_applicable_scope:
        return RESULT_INSUFFICIENT_DATA
    if findings and all(f.result == RESULT_COMPATIBLE for f in findings):
        return RESULT_COMPATIBLE
    return RESULT_REQUIRES_VERIFICATION


def _add_ne(items: list[dict], category: str, reason: str) -> None:
    entry = {"category": category, "reason": reason}
    if entry not in items:
        items.append(entry)


def analyze_build_compatibility(build: Build, components, technical_profiles) -> CompatibilityReport:
    ctx = build_context(build, components, technical_profiles)
    findings: list[CompatibilityFinding] = []
    rules_evaluated = 0
    not_evaluated: list[dict] = []
    limitations: list[str] = []
    from .rules_ram_mb import evaluate_ram_mb
    from .rules_mb_case import evaluate_mb_case
    from .rules_gpu_case import evaluate_gpu_case
    from .rules_cpu_cooling import cpu_cooler_candidates, evaluate_cpu_cooling
    from .rules_cpu_mb import evaluate_cpu_mb_visibility
    from .rules_cooling_case import evaluate_cooling_case
    from .rules_storage import evaluate_bay_capacity, evaluate_m2_fit
    from .storage_classification import classify_all
    from .rules_storage_sata import (
        evaluate_m2_sata_topology,
        evaluate_sata_port_availability,
    )
    from .rules_psu_connectors import evaluate_psu_connectors
    from .rules_psu_case import evaluate_psu_case

    mbs = ctx.components_by_category.get("Motherboard", [])
    cases = ctx.components_by_category.get("Case", [])
    rams = ctx.components_by_category.get("RAM", [])
    gpus = ctx.components_by_category.get("GPU", [])
    cpus = ctx.components_by_category.get("CPU", [])
    coolings = ctx.components_by_category.get("Cooling", [])
    storages = ctx.components_by_category.get("Storage", [])
    psus = ctx.components_by_category.get("PSU", [])
    cpu_coolers = cpu_cooler_candidates(ctx)

    # ambiguity: multiple MB or Case (existing)
    if len(mbs) > 1:
        findings.append(_finding(rule_id="build.ambiguous_motherboard", rule_version="1", result=RESULT_INSUFFICIENT_DATA, severity=SEVERITY_WARNING,
                                 component_ids=[c.id for c in mbs], message_key="compat.build.ambiguous_motherboard",
                                 message_params={"count": len(mbs)}, missing_information=["single_motherboard"],
                                 recommended_action="review_build_configuration"))
    if len(cases) > 1:
        findings.append(_finding(rule_id="build.ambiguous_case", rule_version="1", result=RESULT_INSUFFICIENT_DATA, severity=SEVERITY_WARNING,
                                 component_ids=[c.id for c in cases], message_key="compat.build.ambiguous_case",
                                 message_params={"count": len(cases)}, missing_information=["single_case"],
                                 recommended_action="review_build_configuration"))
    # ambiguity: multiple CPUs or CPU coolers (T17.5)
    if len(cpus) > 1 and cpu_coolers:
        findings.append(_finding(rule_id="build.ambiguous_cpu", rule_version="1", result=RESULT_INSUFFICIENT_DATA, severity=SEVERITY_WARNING,
                                 component_ids=[c.id for c in cpus], message_key="compat.build.ambiguous_cpu",
                                 message_params={"count": len(cpus)}, missing_information=["single_cpu"],
                                 recommended_action="review_build_configuration"))
    if len(cpu_coolers) > 1 and cpus:
        findings.append(_finding(rule_id="build.ambiguous_cpu_cooler", rule_version="1", result=RESULT_INSUFFICIENT_DATA, severity=SEVERITY_WARNING,
                                 component_ids=[c.id for c, _ in cpu_coolers], message_key="compat.build.ambiguous_cpu_cooler",
                                 message_params={"count": len(cpu_coolers)}, missing_information=["single_cpu_cooler"],
                                 recommended_action="review_build_configuration"))

    # fully out of scope categories
    for cat in sorted(FULLY_OUT_OF_SCOPE_CATEGORIES):
        if ctx.components_by_category.get(cat):
            _add_ne(not_evaluated, cat, "no_rules_implemented")
            limitations.append("out_of_scope_relations_present")

    if not ctx.components:
        limitations.append("empty_build")
        findings.append(_finding(rule_id="build.empty", rule_version="1", result=RESULT_INSUFFICIENT_DATA, severity=SEVERITY_INFO,
                                 message_key="compat.build.empty", recommended_action="add_components"))
        return CompatibilityReport(build_id=ctx.build_id, overall_result=RESULT_INSUFFICIENT_DATA, findings=tuple(findings),
                                   ruleset_version=ENGINE_RULESET_VERSION, rules_evaluated=0,
                                   not_evaluated_relations=tuple(not_evaluated), analysis_limitations=tuple(sorted(set(limitations))))

    has_applicable_scope = False

    # RAM <-> MB (T17.3)
    if rams and mbs and not (len(mbs) > 1):
        rf, re = evaluate_ram_mb(ctx); findings.extend(rf); rules_evaluated += re; has_applicable_scope = has_applicable_scope or re > 0
    elif rams and not mbs:
        findings.append(_finding(rule_id="ram_mb.motherboard_missing", rule_version="1", result=RESULT_INSUFFICIENT_DATA, severity=SEVERITY_INFO,
                                 component_ids=[c.id for c in rams], message_key="compat.ram_mb.motherboard_missing",
                                 missing_information=["motherboard"], recommended_action="add_motherboard"))
    elif mbs and not rams:
        limitations.append("ram_not_present")

    # MB <-> Case (T17.3)
    if mbs and cases and not (len(mbs) > 1) and not (len(cases) > 1):
        cf, ce = evaluate_mb_case(ctx); findings.extend(cf); rules_evaluated += ce; has_applicable_scope = has_applicable_scope or ce > 0
    elif mbs and not cases:
        findings.append(_finding(rule_id="mb_case.case_missing", rule_version="1", result=RESULT_INSUFFICIENT_DATA, severity=SEVERITY_INFO,
                                 component_ids=[c.id for c in mbs], message_key="compat.mb_case.case_missing",
                                 missing_information=["case"], recommended_action="add_case"))
    elif cases and not mbs:
        limitations.append("motherboard_not_present")

    # GPU <-> Case length (T17.5) - partial physical coverage always remains
    if gpus and cases and not (len(cases) > 1):
        gf, ge = evaluate_gpu_case(ctx); findings.extend(gf); rules_evaluated += ge; has_applicable_scope = has_applicable_scope or ge > 0
        _add_ne(not_evaluated, "GPU", "physical_dimensions_partial")
        limitations.append("gpu_geometry_not_fully_evaluated")
    elif gpus and not cases:
        findings.append(_finding(rule_id="gpu_case.case_missing", rule_version="1", result=RESULT_INSUFFICIENT_DATA, severity=SEVERITY_INFO,
                                 component_ids=[c.id for c in gpus], message_key="compat.gpu_case.case_missing",
                                 missing_information=["case"], recommended_action="add_case"))
        _add_ne(not_evaluated, "GPU", "physical_dimensions_not_evaluated")
        limitations.append("gpu_geometry_not_fully_evaluated")
    elif gpus and len(cases) > 1:
        # ambiguity already reported; GPU-case cannot be evaluated
        _add_ne(not_evaluated, "GPU", "physical_dimensions_not_evaluated")
        limitations.append("gpu_geometry_not_fully_evaluated")

    # CPU <-> Cooling socket (T17.5) - thermal/performance not evaluated
    if cpus and cpu_coolers and not (len(cpus) > 1) and not (len(cpu_coolers) > 1):
        sf, se = evaluate_cpu_cooling(ctx); findings.extend(sf); rules_evaluated += se; has_applicable_scope = has_applicable_scope or se > 0
        _add_ne(not_evaluated, "CPU", "thermal_capacity_not_evaluated")
        _add_ne(not_evaluated, "Cooling", "thermal_capacity_not_evaluated")
        limitations.append("thermal_performance_not_evaluated")
    elif cpus and not cpu_coolers and not coolings:
        findings.append(_finding(rule_id="cpu_cooling.cooler_missing", rule_version="1", result=RESULT_INSUFFICIENT_DATA, severity=SEVERITY_INFO,
                                 component_ids=[c.id for c in cpus], message_key="compat.cpu_cooling.cooler_missing",
                                 missing_information=["cpu_cooler"], recommended_action="add_cpu_cooler"))
        _add_ne(not_evaluated, "CPU", "thermal_capacity_not_evaluated")
        _add_ne(not_evaluated, "Cooling", "thermal_capacity_not_evaluated")
        limitations.append("thermal_performance_not_evaluated")
    elif cpus and not cpu_coolers and coolings:
        # only non-CPU coolers (e.g. case fans) or undeclared types
        findings.append(_finding(rule_id="cpu_cooling.cpu_cooler_missing", rule_version="1", result=RESULT_INSUFFICIENT_DATA, severity=SEVERITY_INFO,
                                 component_ids=[c.id for c in cpus], message_key="compat.cpu_cooling.cpu_cooler_missing",
                                 missing_information=["cpu_cooler_type_or_candidate"], recommended_action="add_or_identify_cpu_cooler"))
        _add_ne(not_evaluated, "CPU", "thermal_capacity_not_evaluated")
        limitations.append("thermal_performance_not_evaluated")
    elif cpu_coolers and not cpus:
        limitations.append("cpu_not_present")
        _add_ne(not_evaluated, "Cooling", "thermal_capacity_not_evaluated")
        limitations.append("thermal_performance_not_evaluated")
    elif (len(cpus) > 1 or len(cpu_coolers) > 1) and cpus and cpu_coolers:
        _add_ne(not_evaluated, "CPU", "thermal_capacity_not_evaluated")
        _add_ne(not_evaluated, "Cooling", "thermal_capacity_not_evaluated")
        limitations.append("thermal_performance_not_evaluated")

    # CPU <-> Motherboard socket visibility (T17.11) - descriptive only, never decisive.
    # The rule only compares declared socket strings; chipset, BIOS/firmware and
    # power delivery are explicitly left unevaluated via not_evaluated entries.
    if cpus and mbs and not (len(cpus) > 1) and not (len(mbs) > 1):
        cmbf, cmbr = evaluate_cpu_mb_visibility(ctx)
        findings.extend(cmbf)
        rules_evaluated += cmbr
        has_applicable_scope = has_applicable_scope or cmbr > 0
        if cmbr > 0:
            _add_ne(not_evaluated, "Motherboard", "chipset_platform_not_evaluated")
            _add_ne(not_evaluated, "Motherboard", "firmware_bios_not_evaluated")
            _add_ne(not_evaluated, "Motherboard", "power_delivery_not_evaluated")
            limitations.append("platform_chipset_not_evaluated")
            limitations.append("firmware_bios_not_evaluated")
            limitations.append("power_delivery_not_evaluated")

    # Cooling <-> Case (T17.5) - air height / liquid radiator mounting OOS
    if coolings and cases and not (len(cases) > 1):
        cf, ce = evaluate_cooling_case(ctx); findings.extend(cf); rules_evaluated += ce; has_applicable_scope = has_applicable_scope or ce > 0
        # any CPU-relevant cooling/case relation has residual physical/radiator constraints
        if any(get_attr(ctx.profiles_by_component_id.get(c.id), "cooler_type") and get_attr(ctx.profiles_by_component_id.get(c.id), "cooler_type").value in ("air_cpu_cooler","aio_cpu_cooler","custom_loop_cpu_cooler") for c in coolings):
            _add_ne(not_evaluated, "Cooling", "physical_mounting_partial")
            _add_ne(not_evaluated, "Case", "radiator_mounting_not_evaluated")
            limitations.append("cooling_physical_mounting_not_fully_evaluated")
        # liquid findings themselves carry requires_verification
    elif coolings and not cases:
        has_cpu_relevant = any(get_attr(ctx.profiles_by_component_id.get(c.id), "cooler_type") and get_attr(ctx.profiles_by_component_id.get(c.id), "cooler_type").value in ("air_cpu_cooler","aio_cpu_cooler","custom_loop_cpu_cooler") for c in coolings)
        if has_cpu_relevant:
            findings.append(_finding(rule_id="cooling_case.case_missing", rule_version="1", result=RESULT_INSUFFICIENT_DATA, severity=SEVERITY_INFO,
                                     component_ids=[c.id for c in coolings], message_key="compat.cooling_case.case_missing",
                                     missing_information=["case"], recommended_action="add_case"))
            _add_ne(not_evaluated, "Cooling", "physical_mounting_not_evaluated")
            limitations.append("cooling_physical_mounting_not_fully_evaluated")
    elif coolings and len(cases) > 1:
        _add_ne(not_evaluated, "Cooling", "physical_mounting_not_evaluated")
        limitations.append("cooling_physical_mounting_not_fully_evaluated")

    # Storage <-> Motherboard (M.2) and Storage <-> Case (bays) - no assignment/solver.
    # M.2 relevance is declared form factor only (no inference from other/missing).
    def _is_m2_declared(st):
        ff = get_attr(ctx.profiles_by_component_id.get(st.id), "storage_form_factor")
        return ff is not None and ff.value == "m2"

    m2_declared = [s for s in storages if _is_m2_declared(s)]
    if storages and mbs and not (len(mbs) > 1):
        m2f, m2r = evaluate_m2_fit(ctx)
        findings.extend(m2f)
        rules_evaluated += m2r
        has_applicable_scope = has_applicable_scope or m2r > 0
        if len(m2_declared) > 1:
            _add_ne(not_evaluated, "Storage", "multi_unit_joint_fit_not_demonstrated")
            limitations.append("multi_m2_joint_fit_not_evaluated")
    elif storages and not mbs:
        if m2_declared:
            findings.append(_finding(rule_id="storage_m2.motherboard_missing", rule_version="1", result=RESULT_INSUFFICIENT_DATA, severity=SEVERITY_INFO,
                                     component_ids=[c.id for c in m2_declared], message_key="compat.storage_m2.motherboard_missing",
                                     missing_information=["motherboard"], recommended_action="add_motherboard"))

    # SATA data-port availability + declared M.2/SATA topology (T17.9-R2), no assignment/solver
    sata_findings, sata_rules = evaluate_sata_port_availability(ctx)
    findings.extend(sata_findings)
    rules_evaluated += sata_rules
    has_applicable_scope = has_applicable_scope or sata_rules > 0
    topo_findings, topo_rules = evaluate_m2_sata_topology(ctx)
    findings.extend(topo_findings)
    rules_evaluated += topo_rules
    has_applicable_scope = has_applicable_scope or topo_rules > 0
    _scl = classify_all(ctx)
    sata_confirmed = [s.id for s in storages if _scl.get(s.id) is not None and _scl[s.id].sata == "confirmed"]
    sata_possible = [s.id for s in storages if _scl.get(s.id) is not None and _scl[s.id].sata == "possible"]
    m2_confirmed = [s.id for s in storages if _scl.get(s.id) is not None and _scl[s.id].m2 == "confirmed"]
    m2_possible = [s.id for s in storages if _scl.get(s.id) is not None and _scl[s.id].m2 == "possible"]
    bay_relevant = [s.id for s in storages if _scl.get(s.id) is not None and (_scl[s.id].bay25 in ("confirmed", "possible") or _scl[s.id].bay35 in ("confirmed", "possible"))]
    if storages:
        _add_ne(not_evaluated, "Storage", "storage_controller_and_raid_not_evaluated")
        limitations.append("additional_storage_controllers_not_evaluated")
    if sata_confirmed or sata_possible:
        _add_ne(not_evaluated, "Storage", "sata_port_assignment_and_conditions_not_evaluated")
        limitations.append("sata_port_assignment_not_evaluated")
    else:
        limitations.append("no_sata_data_port_units")
    if m2_confirmed or m2_possible:
        _add_ne(not_evaluated, "Storage", "m2_slot_assignment_and_routing_not_evaluated")
        limitations.append("m2_slot_assignment_and_routing_not_evaluated")
        limitations.append("m2_topology_not_fully_evaluated")
        if sata_confirmed or sata_possible:
            limitations.append("m2_sata_topology_conditional_not_fully_evaluated")
        mb_slots = []
        if mbs and len(mbs) == 1:
            slots_attr = get_attr(ctx.profiles_by_component_id.get(mbs[0].id), "m2_slots")
            mb_slots = list(getattr(slots_attr, "value", ()) or ()) if slots_attr is not None else []
        if any(getattr(s, "shared_resource_group_id", None) for s in mb_slots):
            limitations.append("m2_shared_resource_group_semantics_not_evaluated")
        if any(getattr(s, "disables_sata_port_ids", ()) for s in mb_slots):
            limitations.append("m2_sata_disable_conditions_not_modeled")

    if storages and cases and not (len(cases) > 1):
        bcf, bcr = evaluate_bay_capacity(ctx)
        findings.extend(bcf)
        rules_evaluated += bcr
        has_applicable_scope = has_applicable_scope or bcr > 0
        # Bay totals are declared capacity; free-space/adapters/positions not evaluated
        _add_ne(not_evaluated, "Storage", "bay_free_space_and_adapters_not_evaluated")
        limitations.append("bay_free_space_not_evaluated")
    elif storages and not cases:
        if bay_relevant:
            _bay_units = [c for c in storages if c.id in set(bay_relevant)]
            findings.append(_finding(rule_id="storage_case.case_missing", rule_version="1", result=RESULT_INSUFFICIENT_DATA, severity=SEVERITY_INFO,
                                     component_ids=[c.id for c in _bay_units], message_key="compat.storage_case.case_missing",
                                     missing_information=["case"], recommended_action="add_case"))
            _add_ne(not_evaluated, "Storage", "bay_capacity_not_evaluated")
            limitations.append("bay_free_space_not_evaluated")
    elif storages and len(cases) > 1:
        _add_ne(not_evaluated, "Storage", "bay_capacity_not_evaluated")
        limitations.append("bay_free_space_not_evaluated")

    # PSU connector inventory (T17.8b) - descriptive only, no electrical validation/assignment
    if psus and (mbs or gpus):
        pf, pr = evaluate_psu_connectors(ctx)
        findings.extend(pf)
        rules_evaluated += pr
        has_applicable_scope = has_applicable_scope or pr > 0
        _add_ne(not_evaluated, "PSU", "electrical_power_not_evaluated")
        limitations.append("psu_electrical_capacity_not_evaluated")
        _add_ne(not_evaluated, "PSU", "modular_pinout_and_cable_assignment_not_evaluated")
        limitations.append("psu_pinout_assignment_not_evaluated")
    elif psus and not mbs and not gpus:
        _add_ne(not_evaluated, "PSU", "no_power_requirements_present")
        limitations.append("psu_electrical_capacity_not_evaluated")

    # PSU <-> Case form factor (T17.12) - descriptive mounting only.
    # Depth and cable clearance stay not-evaluated via structured entries.
    if psus and cases and len(psus) == 1 and len(cases) == 1:
        pcf, pcr = evaluate_psu_case(ctx)
        findings.extend(pcf)
        rules_evaluated += pcr
        has_applicable_scope = has_applicable_scope or pcr > 0
        if pcr > 0:
            _add_ne(not_evaluated, "PSU", "case_psu_depth_not_evaluated")
            _add_ne(not_evaluated, "Case", "case_psu_depth_not_evaluated")
            _add_ne(not_evaluated, "PSU", "case_psu_cable_clearance_not_evaluated")
            _add_ne(not_evaluated, "Case", "case_psu_cable_clearance_not_evaluated")
            limitations.append("psu_case_depth_not_evaluated")
            limitations.append("psu_case_cable_clearance_not_evaluated")
    elif psus and not cases and len(psus) == 1:
        findings.append(_finding(rule_id="psu_case.case_missing", rule_version="1", result=RESULT_INSUFFICIENT_DATA, severity=SEVERITY_INFO,
                                 component_ids=[c.id for c in psus], message_key="compat.psu_case.case_missing",
                                 missing_information=["case"], recommended_action="add_case"))
    # Multiple PSUs or cases: no arbitrary comparison. Ambiguity is already
    # reported by build.ambiguous_case / psu_connectors.ambiguous_psu guards.

    # CPU/GPU categories present but not covered by any evaluated relation => mark residual limitations
    if gpus and not any(f.rule_id.startswith("gpu_case.") for f in findings):
        _add_ne(not_evaluated, "GPU", "physical_dimensions_not_evaluated")
        limitations.append("gpu_geometry_not_fully_evaluated")
    if cpus and not any(f.rule_id.startswith("cpu_cooling.") for f in findings) and not cpu_coolers:
        pass  # already handled
    if coolings and not any(f.rule_id.startswith("cooling_case.") or f.rule_id.startswith("cpu_cooling.") for f in findings):
        # only case fans/other? no CPU-relevant relations evaluated
        if not any(get_attr(ctx.profiles_by_component_id.get(c.id), "cooler_type") and get_attr(ctx.profiles_by_component_id.get(c.id), "cooler_type").value in ("air_cpu_cooler","aio_cpu_cooler","custom_loop_cpu_cooler") for c in coolings):
            _add_ne(not_evaluated, "Cooling", "no_rules_implemented")

    if not has_applicable_scope and not findings:
        limitations.append("no_applicable_rules")

    overall = global_result(findings, not_evaluated, has_applicable_scope)
    return CompatibilityReport(
        build_id=ctx.build_id,
        overall_result=overall,
        findings=tuple(findings),
        ruleset_version=ENGINE_RULESET_VERSION,
        rules_evaluated=rules_evaluated,
        not_evaluated_relations=tuple(not_evaluated),
        analysis_limitations=tuple(sorted(set(limitations))),
    )
