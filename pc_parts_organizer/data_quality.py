"""Data-quality audit for technical profiles (T17.16). Pure and deterministic.

Classifies every attribute of every component from its real state only:
verification, confidence, evidence, dates, collection completeness.
No scores, no percentages, no invented requirements. Summaries derive
from the classified entries; nothing is persisted (recomputed on demand).
"""

from __future__ import annotations

from dataclasses import dataclass, field

from pc_parts_organizer.technical_profiles import ATTRIBUTE_REGISTRY

ABSENT = "absent"
UNKNOWN = "unknown"
UNVERIFIED = "unverified"
LOW_CONFIDENCE = "low_confidence"
MISSING_EVIDENCE = "missing_evidence"
INCONSISTENT_METADATA = "inconsistent_metadata"
VERIFIED = "verified"
NOT_APPLICABLE = "not_applicable"

ATTRIBUTE_STATES = (
    ABSENT, UNKNOWN, UNVERIFIED, LOW_CONFIDENCE, MISSING_EVIDENCE,
    INCONSISTENT_METADATA, VERIFIED, NOT_APPLICABLE,
)


def _is_low_confidence(attr) -> bool:
    conf = getattr(attr, "confidence", "medium")
    src = getattr(attr, "source", "unknown")
    return conf == "low" or (src == "normalized_inferred" and conf != "high")


def _is_verified(attr) -> bool:
    return getattr(attr, "verification_status", None) == "verified"


def _completeness_contract_ok(key: str, attr, spec) -> bool:
    """Mirror of the registry completeness policy (read-only check)."""
    cc = getattr(attr, "collection_completeness", "unknown")
    scope = getattr(attr, "completeness_scope", None)
    if cc not in ("unknown", "partial", "complete"):
        return False
    if cc == "unknown":
        return scope is None
    if not getattr(spec, "allows_completeness", False):
        return False
    if scope is None:
        return False
    if cc == "complete":
        return (
            _is_verified(attr)
            and not _is_low_confidence(attr)
            and getattr(attr, "confidence", None) == "high"
            and bool(getattr(attr, "evidence_ref", None))
            and bool(getattr(attr, "verified_at", None))
        )
    return True  # partial with scope on an eligible key


def classify_attribute(key: str, attr, spec) -> str:
    """Classify one present attribute. Never invents a favorable state."""
    if attr is None:
        return ABSENT
    value = getattr(attr, "value", None)
    if value is None or (isinstance(value, str) and not value.strip()):
        return UNKNOWN
    if not _completeness_contract_ok(key, attr, spec):
        return INCONSISTENT_METADATA
    if _is_verified(attr):
        if not getattr(attr, "evidence_ref", None) or not getattr(attr, "verified_at", None):
            return MISSING_EVIDENCE
        if _is_low_confidence(attr):
            return LOW_CONFIDENCE
        # verified + evidence + date (+ not low confidence) is the engine's
        # decisive gate; high confidence is additionally required only for
        # complete collections, not for plain attributes.
        return VERIFIED
    if _is_low_confidence(attr):
        return LOW_CONFIDENCE
    return UNVERIFIED


@dataclass(frozen=True)
class AttributeEntry:
    component_id: str
    category: str
    key: str
    status: str
    unit: object = None
    source: str = ""
    confidence: str = ""
    verification_status: str = ""
    evidence_ref: object = None
    verified_at: object = None
    collection_completeness: str = "unknown"
    completeness_scope: object = None
    consumed_by: tuple = ()


@dataclass
class QualityReport:
    entries: tuple = ()
    components_total: int = 0
    components_without_profile: int = 0
    components_with_profile: int = 0

    def count(self, status: str) -> int:
        return sum(1 for e in self.entries if e.status == status)


# Attribute -> engine rules that read it. Declarative and minimal; a test
# verifies every get_attr key used by compatibility/rules_*.py is covered.
CONSUMERS: dict[tuple[str, str], tuple[str, ...]] = {
    ("RAM", "memory_generation"): ("ram_mb.memory_generation",),
    ("RAM", "module_form_factor"): ("ram_mb.module_form_factor",),
    ("RAM", "total_capacity_gb"): ("ram_mb.max_capacity",),
    ("RAM", "module_count"): ("ram_mb.module_slots",),
    ("Motherboard", "form_factor"): ("mb_case.form_factor",),
    ("Motherboard", "supported_memory_generations"): ("ram_mb.memory_generation",),
    ("Motherboard", "supported_memory_module_form_factors"): ("ram_mb.module_form_factor",),
    ("Motherboard", "memory_slot_count"): ("ram_mb.module_slots",),
    ("Motherboard", "max_memory_capacity_gb"): ("ram_mb.max_capacity",),
    ("Motherboard", "sata_port_count"): ("storage_sata.port_availability",),
    ("Motherboard", "sata_port_identifiers"): ("storage_sata.m2_topology", "storage_sata.port_availability"),
    ("Motherboard", "socket_designation"): ("cpu_mb.socket_visibility",),
    ("Motherboard", "m2_slots"): ("storage_m2.fit", "storage_m2.slots_absent", "storage_sata.m2_topology"),
    ("Motherboard", "motherboard_power_connectors_required"): (
        "psu_mb.connector_availability", "psu_joint.connector_availability"),
    ("Case", "supported_motherboard_form_factors"): ("mb_case.form_factor",),
    ("Case", "max_gpu_length_mm"): ("gpu_case.max_length",),
    ("Case", "max_cpu_cooler_height_mm"): ("cooling_case.air_cooler_height",),
    ("Case", "bay_2_5_total"): ("storage_case.bay_2_5_capacity",),
    ("Case", "bay_3_5_total"): ("storage_case.bay_3_5_capacity",),
    ("Case", "supported_psu_form_factors"): ("psu_case.form_factor",),
    ("CPU", "socket_designation"): ("cpu_mb.socket_visibility", "cpu_cooling.socket_support"),
    ("GPU", "card_length_mm"): ("gpu_case.max_length",),
    ("GPU", "recommended_psu_power_w"): (),
    ("GPU", "gpu_power_connectors_required"): (
        "psu_gpu.connector_availability", "psu_joint.connector_availability"),
    ("Cooling", "cooler_type"): ("cooling_case.liquid_mounting_scope", "cpu_cooling.socket_support"),
    ("Cooling", "supported_cpu_sockets"): ("cpu_cooling.socket_support",),
    ("Cooling", "cooler_height_mm"): ("cooling_case.air_cooler_height",),
    ("Storage", "storage_form_factor"): (
        "storage_m2.fit", "storage_m2.slots_absent", "storage_case.bay_2_5_capacity",
        "storage_case.bay_3_5_capacity", "storage_sata.port_availability", "storage_sata.m2_topology"),
    ("Storage", "storage_interface"): ("storage_m2.fit", "storage_sata.port_availability", "storage_sata.m2_topology"),
    ("Storage", "storage_command_set"): ("storage_m2.fit", "storage_sata.port_availability", "storage_sata.m2_topology"),
    ("Storage", "m2_keying"): ("storage_m2.fit", "storage_sata.m2_topology"),
    ("Storage", "m2_length_code"): ("storage_m2.fit", "storage_sata.m2_topology"),
    ("Storage", "pcie_generation"): (),
    ("Storage", "pcie_lanes"): (),
    ("PSU", "rated_continuous_power_w"): (),
    ("PSU", "power_cable_assemblies"): (
        "psu_mb.connector_availability", "psu_gpu.connector_availability",
        "psu_joint.connector_availability"),
    ("PSU", "psu_form_factor"): ("psu_case.form_factor",),
}


def consumers_for(category: str, key: str) -> tuple:
    return tuple(CONSUMERS.get((category, key), ()))


def audit_inventory(components, profiles_by_component_id) -> QualityReport:
    """Audit every component against its category registry. Pure."""
    entries: list[AttributeEntry] = []
    without = 0
    for comp in components or ():
        cid = getattr(comp, "id", "")
        cat = getattr(comp, "category", "")
        specs = ATTRIBUTE_REGISTRY.get(cat, {})
        prof = (profiles_by_component_id or {}).get(cid)
        if prof is None:
            without += 1
            for key in sorted(specs):
                entries.append(AttributeEntry(cid, cat, key, ABSENT,
                                              consumed_by=consumers_for(cat, key)))
            continue
        by_key = {a.key: a for a in (getattr(prof, "attributes", None) or [])}
        for key in sorted(specs):
            attr = by_key.get(key)
            if attr is None:
                entries.append(AttributeEntry(cid, cat, key, ABSENT,
                                              consumed_by=consumers_for(cat, key)))
                continue
            entries.append(AttributeEntry(
                cid, cat, key, classify_attribute(key, attr, specs[key]),
                unit=getattr(attr, "unit", None),
                source=getattr(attr, "source", "") or "",
                confidence=getattr(attr, "confidence", "") or "",
                verification_status=getattr(attr, "verification_status", "") or "",
                evidence_ref=getattr(attr, "evidence_ref", None),
                verified_at=getattr(attr, "verified_at", None),
                collection_completeness=getattr(attr, "collection_completeness", "unknown"),
                completeness_scope=getattr(attr, "completeness_scope", None),
                consumed_by=consumers_for(cat, key),
            ))
    total = len(list(components or ()))
    return QualityReport(entries=tuple(entries), components_total=total,
                         components_without_profile=without,
                         components_with_profile=total - without)


def review_queue(report: QualityReport, *, important_only: bool = True) -> tuple:
    """Work list: entries needing attention. No auto-resolution."""
    out = []
    for e in report.entries:
        if e.status in (ABSENT, UNKNOWN, UNVERIFIED, LOW_CONFIDENCE,
                        MISSING_EVIDENCE, INCONSISTENT_METADATA):
            if important_only and e.status == ABSENT and not e.consumed_by:
                continue
            out.append(e)
    order = {ABSENT: 0, UNKNOWN: 1, MISSING_EVIDENCE: 2, INCONSISTENT_METADATA: 3,
             LOW_CONFIDENCE: 4, UNVERIFIED: 5}
    out.sort(key=lambda e: (order.get(e.status, 9), e.category, e.key, e.component_id))
    return tuple(out)
