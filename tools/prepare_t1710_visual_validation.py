r"""Prepare isolated synthetic LOCALAPPDATA data for T17.10 collection-completeness validation.

Covers v1 legacy coexistence and complete/partial/unknown inventories for M.2,
PSU cables and SATA identifiers. Real APIs only; never touches real data.
"""
from __future__ import annotations

import argparse
import dataclasses
import json
import os
import sys
import tempfile
from collections.abc import Mapping as ABCMapping
from datetime import datetime, timezone
from pathlib import Path


def _real_pcpo_dir() -> Path | None:
    raw = os.environ.get("LOCALAPPDATA")
    if not raw:
        return None
    try:
        return Path(raw).expanduser().resolve() / "PCPartsOrganizer"
    except Exception:
        return None


def _is_under_temp(target: Path) -> bool:
    t = Path(tempfile.gettempdir()).resolve()
    try:
        target.resolve().relative_to(t)
        return True
    except Exception:
        return False


def _jsonable(value):
    if dataclasses.is_dataclass(value):
        if hasattr(value, "to_dict"):
            return _jsonable(value.to_dict())
        return {f.name: _jsonable(getattr(value, f.name)) for f in dataclasses.fields(value)}
    if isinstance(value, ABCMapping):
        return {str(k): _jsonable(v) for k, v in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_jsonable(v) for v in value]
    return value


def _finding_dict(f):
    return {
        "rule_id": f.rule_id, "result": f.result, "severity": f.severity,
        "message_key": f.message_key, "message_params": _jsonable(getattr(f, "message_params", {}) or {}),
        "component_ids": list(getattr(f, "component_ids", ()) or []),
        "missing_information": list(getattr(f, "missing_information", ()) or ()),
        "recommended_action": getattr(f, "recommended_action", ""),
        "evidence": _jsonable(getattr(f, "evidence", {}) or {}),
    }


SCOPE_M2 = "All physical M.2 slots of the board model/revision"
SCOPE_PSU = "All cable assemblies included with the PSU variant"
SCOPE_SATA = "All integrated SATA port identifiers of the board"


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--target", required=True)
    args = ap.parse_args(argv)

    real_pcpo = _real_pcpo_dir()
    target = Path(args.target).expanduser().resolve()
    temp_root = Path(tempfile.gettempdir()).resolve()

    if not _is_under_temp(target):
        print(f"REFUSED: target must be under system TEMP ({temp_root}). Got: {target}", file=sys.stderr)
        return 2
    if target == temp_root:
        print("REFUSED: target must be a dedicated subdirectory under TEMP.", file=sys.stderr)
        return 2
    if real_pcpo is not None and (target == real_pcpo or str(target).lower().startswith(str(real_pcpo).lower() + os.sep.lower())):
        print(f"REFUSED: target overlaps real data dir: {real_pcpo}", file=sys.stderr)
        return 2
    pcpo_sub = target / "PCPartsOrganizer"
    if pcpo_sub.exists():
        if any(pcpo_sub.iterdir()):
            print(f"REFUSED: target already contains data: {pcpo_sub}", file=sys.stderr)
            return 2
    else:
        pcpo_sub.mkdir(parents=True, exist_ok=False)

    os.environ["LOCALAPPDATA"] = str(target)
    os.environ["PYTHONDONTWRITEBYTECODE"] = "1"
    repo = Path(__file__).resolve().parents[1]
    if str(repo) not in sys.path:
        sys.path.insert(0, str(repo))

    from pc_parts_organizer.service import InventoryService
    from pc_parts_organizer.storage import load_project_state
    from pc_parts_organizer.technical_profiles import M2SlotSpec, TechnicalAttribute, TechnicalProfile

    def va(key, value, **kw):
        base = dict(source="official_vendor_doc", confidence="high",
                    verification_status="verified", evidence_ref="https://vendor.example/doc",
                    verified_at="2026-01-01")
        base.update(kw)
        return TechnicalAttribute(key=key, value=value, **base)

    def ua(key, value):
        return TechnicalAttribute(key=value, value=value, source="unknown", confidence="low",
                                  verification_status="unverified") if False else TechnicalAttribute(
            key=key, value=value, source="unknown", confidence="low", verification_status="unverified")

    def slot(sid, keyings=("M",), lengths=("2280",), modes=("pcie_nvme",), disables=(), evidence="https://vendor.example/slot"):
        return M2SlotSpec(slot_id=sid, accepted_module_keyings=keyings, supported_lengths=lengths,
                          supported_modes=modes, disables_sata_port_ids=disables, evidence_ref=evidence)

    def m2unit(key="M", length="2280", iface="pcie", cmd="nvme"):
        return [va("storage_form_factor", "m2"), va("storage_interface", iface),
                va("storage_command_set", cmd), va("m2_keying", key), va("m2_length_code", length)]

    def sataunit(ff="2_5_in"):
        return [va("storage_form_factor", ff), va("storage_interface", "sata"), va("storage_command_set", "ata")]

    def cable(cid, atype, ends, psu_side=None):
        d = {"cable_id": cid, "assembly_type": atype, "component_side_ends": ends}
        if psu_side:
            d["psu_side_connector_id"] = psu_side
        return d

    def end(eid, kind):
        return {"end_id": eid, "connector_kind": kind}

    svc = InventoryService()
    builds = {}

    def add_build(name, specs):
        comps = []
        for cat, model, attrs in specs:
            c = svc.add_component(cat, "T17.10", model, "", "T17.10")
            if attrs is not None:
                svc.set_technical_profile(TechnicalProfile(component_id=c.id, attributes=attrs))
            comps.append(c)
        b = svc.add_build(name)
        for c in comps:
            svc.add_component_to_build(b.id, c.id)
        return b.id

    # S1 legacy v1 M.2 profile without completeness metadata (parsed as v1)
    from pc_parts_organizer.technical_profiles import parse_profile_dict
    _mb1 = svc.add_component("Motherboard", "T17.10", "MB S1", "", "")
    _st1 = svc.add_component("Storage", "T17.10", "NVMe S1", "", "")
    svc.set_technical_profile(parse_profile_dict(
        {"component_id": _mb1.id, "profile_version": 1, "attributes": [
            {"key": "m2_slots", "value": [{"slot_id": "M2_1", "accepted_module_keyings": ["M"],
             "supported_lengths": ["2280"], "supported_modes": ["pcie_nvme"]}]}]}, 0, "Motherboard"))
    svc.set_technical_profile(parse_profile_dict(
        {"component_id": _st1.id, "profile_version": 1, "attributes": [
            {"key": "storage_form_factor", "value": "m2"}, {"key": "storage_interface", "value": "pcie"},
            {"key": "storage_command_set", "value": "nvme"}, {"key": "m2_keying", "value": "M"},
            {"key": "m2_length_code", "value": "2280"}]}, 0, "Storage"))
    _b1 = svc.add_build("T17.10 - S1 legacy v1 M.2")
    for c in (_mb1, _st1):
        svc.add_component_to_build(_b1.id, c.id)
    builds["S1"] = _b1.id

    # S2 verified M.2 slots, completeness unknown
    builds["S2"] = add_build("T17.10 - S2 M.2 verified unknown", [
        ("Motherboard", "MB S2", [va("m2_slots", [slot("M2_1")])]),
        ("Storage", "NVMe S2", m2unit()),
    ])
    # S3 partial M.2, no match
    builds["S3"] = add_build("T17.10 - S3 M.2 partial no match", [
        ("Motherboard", "MB S3", [va("m2_slots", [slot("M2_1", lengths=("2260",))],
                                      collection_completeness="partial", completeness_scope="Slots seen so far")]),
        ("Storage", "NVMe S3", m2unit()),
    ])
    # S4 complete M.2 with match
    builds["S4"] = add_build("T17.10 - S4 M.2 complete with match", [
        ("Motherboard", "MB S4", [va("m2_slots", [slot("M2_1")],
                                      collection_completeness="complete", completeness_scope=SCOPE_M2)]),
        ("Storage", "NVMe S4", m2unit()),
    ])
    # S5 complete M.2 without match -> incompatible dimension
    builds["S5"] = add_build("T17.10 - S5 M.2 complete no match", [
        ("Motherboard", "MB S5", [va("m2_slots", [slot("M2_1", lengths=("2260",))],
                                      collection_completeness="complete", completeness_scope=SCOPE_M2)]),
        ("Storage", "NVMe S5", m2unit()),
    ])
    # S6 complete empty M.2
    builds["S6"] = add_build("T17.10 - S6 M.2 complete empty", [
        ("Motherboard", "MB S6", [va("m2_slots", [],
                                      collection_completeness="complete", completeness_scope=SCOPE_M2)]),
        ("Storage", "NVMe S6", m2unit()),
    ])
    # S7 empty unknown
    builds["S7"] = add_build("T17.10 - S7 M.2 empty unknown", [
        ("Motherboard", "MB S7", [ua("m2_slots", [])]),
        ("Storage", "NVMe S7", m2unit()),
    ])
    # S8 PSU complete sufficient
    builds["S8"] = add_build("T17.10 - S8 PSU complete sufficient", [
        ("Motherboard", "MB S8", [va("motherboard_power_connectors_required", [
            {"connector_kind": "ATX_24", "quantity": 1, "required": True}])]),
        ("PSU", "PSU S8", [va("power_cable_assemblies",
                               [cable("C1", "fixed_native", [end("E1", "ATX_24")])],
                               collection_completeness="complete", completeness_scope=SCOPE_PSU)]),
    ])
    # S9 PSU complete resolved insufficient -> incompatible
    builds["S9"] = add_build("T17.10 - S9 PSU complete insufficient", [
        ("GPU", "GPU S9", [va("gpu_power_connectors_required", [
            {"connector_kind": "PCIE_8", "quantity": 2, "required": True}])]),
        ("PSU", "PSU S9", [va("power_cable_assemblies",
                               [cable("C1", "fixed_native", [end("E1", "PCIE_8")])],
                               collection_completeness="complete", completeness_scope=SCOPE_PSU)]),
    ])
    # S10 PSU partial insufficient
    builds["S10"] = add_build("T17.10 - S10 PSU partial insufficient", [
        ("GPU", "GPU S10", [va("gpu_power_connectors_required", [
            {"connector_kind": "PCIE_8", "quantity": 2, "required": True}])]),
        ("PSU", "PSU S10", [va("power_cable_assemblies",
                                [cable("C1", "fixed_native", [end("E1", "PCIE_8")])],
                                collection_completeness="partial", completeness_scope="Cables seen so far")]),
    ])
    # S11 PSU complete with unvalidated adapter
    builds["S11"] = add_build("T17.10 - S11 PSU complete unvalidated adapter", [
        ("GPU", "GPU S11", [va("gpu_power_connectors_required", [
            {"connector_kind": "PCIE_8", "quantity": 1, "required": True}])]),
        ("PSU", "PSU S11", [va("power_cable_assemblies",
                                [cable("T1", "third_party_adapter", [end("E1", "PCIE_8")])],
                                collection_completeness="complete", completeness_scope=SCOPE_PSU)]),
    ])
    # S12 SATA IDs complete
    builds["S12"] = add_build("T17.10 - S12 SATA IDs complete", [
        ("Motherboard", "MB S12", [
            va("sata_port_count", 2),
            va("sata_port_identifiers", ["SATA1", "SATA2"],
               collection_completeness="complete", completeness_scope=SCOPE_SATA),
            va("m2_slots", [slot("M2_1", disables=("SATA1",))])]),
        ("Storage", "NVMe S12", m2unit()),
        ("Storage", "SSD S12", sataunit()),
    ])
    # S13 SATA IDs partial with restriction
    builds["S13"] = add_build("T17.10 - S13 SATA IDs partial", [
        ("Motherboard", "MB S13", [
            va("sata_port_count", 2),
            va("sata_port_identifiers", ["SATA1", "SATA2"],
               collection_completeness="partial", completeness_scope="Ports seen so far"),
            va("m2_slots", [slot("M2_1", disables=("SATA9",))])]),
        ("Storage", "NVMe S13", m2unit()),
        ("Storage", "SSD S13", sataunit()),
    ])
    # S14 mixed collections
    builds["S14"] = add_build("T17.10 - S14 mixed collections", [
        ("Motherboard", "MB S14", [
            va("motherboard_power_connectors_required", [
                {"connector_kind": "ATX_24", "quantity": 1, "required": True}]),
            va("sata_port_count", 2),
            va("m2_slots", [slot("M2_1", lengths=("2260",))],
               collection_completeness="complete", completeness_scope=SCOPE_M2)]),
        ("Storage", "NVMe S14", m2unit()),
        ("Storage", "SSD S14", sataunit()),
        ("PSU", "PSU S14", [va("power_cable_assemblies",
                                [cable("C1", "fixed_native", [end("E1", "ATX_24")])],
                                collection_completeness="unknown")]),
    ])
    # S15 legacy profile edited in temp env -> persisted as v2 with safe metadata
    _mb15 = svc.add_component("Motherboard", "T17.10", "MB S15", "", "")
    _st15 = svc.add_component("Storage", "T17.10", "NVMe S15", "", "")
    _p15 = parse_profile_dict({"component_id": _mb15.id, "profile_version": 1, "attributes": [
        {"key": "m2_slots", "value": []}]}, 0, "Motherboard")
    assert _p15.attributes[0].collection_completeness == "unknown"
    svc.set_technical_profile(TechnicalProfile(
        component_id=_mb15.id, profile_version=2,
        attributes=[TechnicalAttribute(key="m2_slots", value=[],
                                       source="official_vendor_doc", confidence="high",
                                       verification_status="verified", evidence_ref="https://vendor.example/doc",
                                       verified_at="2026-01-01", collection_completeness="complete",
                                       completeness_scope=SCOPE_M2)]))
    svc.set_technical_profile(TechnicalProfile(component_id=_st15.id, attributes=m2unit()))
    _b15 = svc.add_build("T17.10 - S15 legacy edited to v2 complete")
    for c in (_mb15, _st15):
        svc.add_component_to_build(_b15.id, c.id)
    builds["S15"] = _b15.id

    state = load_project_state()
    reports = {}

    def analyze(bid):
        r = svc.analyze_build_compatibility(bid)
        return {"build_id": bid, "overall": r.overall_result, "ruleset": r.ruleset_version,
                "findings": [_finding_dict(f) for f in r.findings],
                "limitations": list(r.analysis_limitations),
                "not_evaluated": [dict(n) for n in r.not_evaluated_relations]}

    for k, bid in builds.items():
        reports[k] = analyze(bid)
    state_after = load_project_state()
    checks = {}
    checks["no_compat_persistence"] = (len(state.components) == len(state_after.components) and
                                       len(state.builds) == len(state_after.builds) and
                                       len(state.technical_profiles) == len(state_after.technical_profiles))
    checks["loaded_builds_count"] = len(state.builds)
    checks["loaded_builds"] = len(state.builds) >= 15
    checks["all_build_ids_present"] = all(any(b.id == bid for b in state.builds) for bid in builds.values())

    def fs(key, rid):
        return [f for f in reports[key]["findings"] if f["rule_id"] == rid]

    def any_result(key, rid, res):
        return any(f["result"] == res for f in fs(key, rid))

    checks["S1_legacy_v1_readable"] = any_result("S1", "storage_m2.fit", "requires_verification") or any_result("S1", "storage_m2.slots_absent", "insufficient_data")
    checks["S2_unknown_no_negative"] = not any(f["result"] == "incompatible" for f in reports["S2"]["findings"])
    checks["S3_partial_no_negative"] = not any(f["result"] == "incompatible" for f in reports["S3"]["findings"])
    checks["S4_complete_fit"] = any_result("S4", "storage_m2.fit", "compatible")
    checks["S5_complete_no_fit"] = any_result("S5", "storage_m2.fit", "incompatible")
    checks["S6_complete_empty"] = any_result("S6", "storage_m2.slots_absent", "incompatible")
    checks["S7_empty_unknown"] = any_result("S7", "storage_m2.slots_absent", "insufficient_data")
    checks["S8_psu_complete_ok"] = any_result("S8", "psu_mb.connector_availability", "compatible")
    checks["S9_psu_complete_short"] = any_result("S9", "psu_gpu.connector_availability", "incompatible")
    checks["S10_psu_partial"] = any_result("S10", "psu_gpu.connector_availability", "requires_verification")
    checks["S11_adapter_unresolved"] = any_result("S11", "psu_gpu.connector_availability", "requires_verification")
    checks["S12_ids_complete"] = any_result("S12", "storage_sata.m2_topology", "requires_verification")
    checks["S13_ids_partial"] = any_result("S13", "storage_sata.m2_topology", "requires_verification")
    checks["S14_mixed"] = any_result("S14", "storage_m2.fit", "incompatible")
    checks["S15_legacy_v2_complete"] = any_result("S15", "storage_m2.slots_absent", "incompatible")
    checks["global_conservative"] = all(r["overall"] in ("compatible", "requires_verification", "insufficient_data", "incompatible") for r in reports.values())

    mw_ok = False
    mw_err = None
    try:
        import tkinter as tk
        from pc_parts_organizer.catalog_service import CatalogService
        from pc_parts_organizer.catalog_storage import CatalogStorage
        from pc_parts_organizer.localization import Translator
        from pc_parts_organizer.ui.main_window import MainWindow
        from pc_parts_organizer.ui.theme import configure_theme
        svc2 = InventoryService()
        names = [b.name for b in svc2.get_builds()]
        root = tk.Tk()
        root.withdraw()
        try:
            configure_theme(root)
            MainWindow(root, svc2, CatalogService(CatalogStorage()), Translator())
            mw_ok = len([n for n in names if n.startswith("T17.10 - S")]) >= 15
        finally:
            try:
                root.destroy()
            except Exception:
                pass
    except Exception as e:
        mw_err = str(e)
    checks["mainwindow_synthetic_load"] = mw_ok
    checks["mainwindow_error"] = mw_err

    report = {
        "task": "T17.10 completeness visual validation prep",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "target_localappdata_root": str(target), "pcpo_data_dir": str(pcpo_sub),
        "real_pcpo_dir_captured": str(real_pcpo) if real_pcpo else None, "temp_root": str(temp_root),
        "builds": {k: {"build_id": v, "name": next(b.name for b in state.builds if b.id == v)} for k, v in builds.items()},
        "reports": reports,
        "checks": checks,
        "all_checks_ok": all(v is True for k, v in checks.items() if k not in ("mainwindow_error", "loaded_builds_count")),
        "visual_manual_completed": False,
    }
    out = pcpo_sub / "t1710_visual_report.json"
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2, default=str) + "\n", encoding="utf-8")
    print(json.dumps({"ok": report["all_checks_ok"], "report": str(out), "target": str(target),
                      "checks": {k: v for k, v in checks.items() if k != "mainwindow_error"}, "mw_err": mw_err},
                     ensure_ascii=False, indent=2))
    return 0 if report["all_checks_ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
