r"""Prepare isolated synthetic LOCALAPPDATA data for T17.9 storage connectivity visual validation.

SAFETY:
- Uses an explicit target directory under the system TEMP directory only.
- Refuses the real %LOCALAPPDATA%\PCPartsOrganizer data directory and any existing non-empty target.
- Does NOT copy/read/modify/export/restore real inventory, settings, or catalog.
- Sets LOCALAPPDATA before importing pc_parts_organizer modules that resolve storage paths.

Usage (from repo root):
  python tools/prepare_t179_visual_validation.py --target %TEMP%\PCPO-T17.9-visual-<stamp>
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


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--target", required=True, help="Absolute path under system TEMP for isolated LOCALAPPDATA root")
    args = ap.parse_args(argv)

    real_pcpo = _real_pcpo_dir()
    target = Path(args.target).expanduser().resolve()
    temp_root = Path(tempfile.gettempdir()).resolve()

    if not _is_under_temp(target):
        print(f"REFUSED: target must be under system TEMP ({temp_root}). Got: {target}", file=sys.stderr)
        return 2
    if target == temp_root:
        print("REFUSED: target must be a dedicated subdirectory under TEMP, not TEMP itself.", file=sys.stderr)
        return 2
    if real_pcpo is not None and (target == real_pcpo or str(target).lower().startswith(str(real_pcpo).lower() + os.sep.lower())):
        print(f"REFUSED: target overlaps real PCPartsOrganizer data dir: {real_pcpo}", file=sys.stderr)
        return 2
    pcpo_sub = target / "PCPartsOrganizer"
    if pcpo_sub.exists():
        if any(pcpo_sub.iterdir()):
            print(f"REFUSED: target already contains data: {pcpo_sub} (choose a new directory)", file=sys.stderr)
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

    def va(key, value):
        return TechnicalAttribute(key=key, value=value, source="official_vendor_doc", confidence="high",
                                  verification_status="verified", evidence_ref="https://vendor.example/doc", verified_at="2026-01-01")

    def ua(key, value):
        return TechnicalAttribute(key=key, value=value, source="unknown", confidence="low", verification_status="unverified")

    def storage_attrs(ff, iface, cmd, key=None, length=None):
        attrs = [va("storage_form_factor", ff), va("storage_interface", iface), va("storage_command_set", cmd)]
        if key is not None:
            attrs.append(va("m2_keying", key))
        if length is not None:
            attrs.append(va("m2_length_code", length))
        return attrs

    def slot(slot_id, keyings=("M",), modes=("pcie_nvme",), disables=(), shared=None, routed="unknown"):
        return M2SlotSpec(slot_id=slot_id, accepted_module_keyings=keyings, supported_lengths=("2280",),
                          supported_modes=modes, disables_sata_port_ids=disables,
                          shared_resource_group_id=shared, routed_to=routed, evidence_ref="https://vendor.example/slot")

    service = InventoryService()
    builds = {}

    def make_build(name, mb_attrs, storage_specs, case_attrs=None):
        mb = service.add_component("Motherboard", "T17.9 Visual", f"MB {name}", "", "T17.9")
        service.set_technical_profile(TechnicalProfile(component_id=mb.id, attributes=mb_attrs))
        comps = [mb]
        for label, attrs in storage_specs:
            st = service.add_component("Storage", "T17.9 Visual", label, "", "T17.9")
            service.set_technical_profile(TechnicalProfile(component_id=st.id, attributes=attrs))
            comps.append(st)
        if case_attrs is not None:
            case = service.add_component("Case", "T17.9 Visual", f"Case {name}", "", "T17.9")
            service.set_technical_profile(TechnicalProfile(component_id=case.id, attributes=case_attrs))
            comps.append(case)
        b = service.add_build(name)
        for c in comps:
            service.add_component_to_build(b.id, c.id)
        return b.id

    # S1: 2.5" SATA unit with available port
    builds["S1"] = make_build(
        "T17.9 Visual - S1 2.5 SATA available ports",
        [va("sata_port_count", 2)],
        [("SSD 2.5 SATA S1", storage_attrs("2_5_in", "sata", "ata"))],
    )

    # S2: 3.5" SATA unit with available port
    builds["S2"] = make_build(
        "T17.9 Visual - S2 3.5 SATA available ports",
        [va("sata_port_count", 2)],
        [("HDD 3.5 SATA S2", storage_attrs("3_5_in", "sata", "ata"))],
    )

    # S3: multiple SATA units within declared count
    builds["S3"] = make_build(
        "T17.9 Visual - S3 multiple SATA within count",
        [va("sata_port_count", 3)],
        [("SSD 2.5 SATA S3", storage_attrs("2_5_in", "sata", "ata")),
         ("HDD 3.5 SATA S3", storage_attrs("3_5_in", "sata", "ata"))],
    )

    # S4: insufficient SATA port information
    builds["S4"] = make_build(
        "T17.9 Visual - S4 missing SATA port count",
        [],
        [("SSD 2.5 SATA S4", storage_attrs("2_5_in", "sata", "ata"))],
    )

    # S5: insufficient declared count, unmodeled alternatives -> requires verification, never incompatible
    builds["S5"] = make_build(
        "T17.9 Visual - S5 insufficient declared SATA ports",
        [va("sata_port_count", 1)],
        [("SSD 2.5 SATA S5 A", storage_attrs("2_5_in", "sata", "ata")),
         ("HDD 3.5 SATA S5 B", storage_attrs("3_5_in", "sata", "ata"))],
    )

    # S6: NVMe only, no SATA data-port units
    builds["S6"] = make_build(
        "T17.9 Visual - S6 NVMe only no SATA units",
        [va("sata_port_count", 2), va("m2_slots", [slot("M2_1")])],
        [("NVMe M.2 S6", storage_attrs("m2", "pcie", "nvme", "M", "2280"))],
    )

    # S7: M.2 SATA + SATA drives with potential SATA-port disabling
    builds["S7"] = make_build(
        "T17.9 Visual - S7 M.2 SATA potential port disable",
        [va("sata_port_count", 2), va("sata_port_identifiers", ["SATA1", "SATA2"]),
         va("m2_slots", [slot("M2_1", keyings=("B_M",), modes=("sata_ata",), disables=("SATA1",))])],
        [("M.2 SATA S7", storage_attrs("m2", "sata", "ata", "B_M", "2280")),
         ("SSD 2.5 SATA S7", storage_attrs("2_5_in", "sata", "ata"))],
    )

    # S8: M.2 NVMe + SATA drives with declared port restriction
    builds["S8"] = make_build(
        "T17.9 Visual - S8 M.2 NVMe declared port restriction",
        [va("sata_port_count", 2), va("sata_port_identifiers", ["SATA1", "SATA2"]),
         va("m2_slots", [slot("M2_1", modes=("pcie_nvme",), disables=("SATA1",))])],
        [("NVMe M.2 S8", storage_attrs("m2", "pcie", "nvme", "M", "2280")),
         ("SSD 2.5 SATA S8", storage_attrs("2_5_in", "sata", "ata"))],
    )

    # S9: several M.2 slots with different restrictions, no assignment known
    builds["S9"] = make_build(
        "T17.9 Visual - S9 multiple slots different restrictions",
        [va("sata_port_count", 2), va("sata_port_identifiers", ["SATA1", "SATA2"]),
         va("m2_slots", [slot("M2_1", disables=("SATA1",)), slot("M2_2")])],
        [("NVMe M.2 S9", storage_attrs("m2", "pcie", "nvme", "M", "2280")),
         ("SSD 2.5 SATA S9", storage_attrs("2_5_in", "sata", "ata"))],
    )

    # S10: mixed M.2 + SATA (2.5/3.5) + case bays; distinct dimensions
    builds["S10"] = make_build(
        "T17.9 Visual - S10 mixed M.2 SATA bays",
        [va("sata_port_count", 3), va("sata_port_identifiers", ["SATA1", "SATA2", "SATA3"]),
         va("m2_slots", [slot("M2_1"), slot("M2_2", disables=("SATA3",), shared="G1", routed="chipset")])],
        [("NVMe M.2 S10", storage_attrs("m2", "pcie", "nvme", "M", "2280")),
         ("SSD 2.5 SATA S10", storage_attrs("2_5_in", "sata", "ata")),
         ("HDD 3.5 SATA S10", storage_attrs("3_5_in", "sata", "ata"))],
        case_attrs=[va("bay_2_5_total", 1), va("bay_3_5_total", 1)],
    )

    state = load_project_state()
    reports = {}

    def analyze(bid):
        r = service.analyze_build_compatibility(bid)
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
    checks["loaded_builds"] = len(state.builds) >= 10
    checks["all_build_ids_present"] = all(any(b.id == bid for b in state.builds) for bid in builds.values())

    def fs(key, rid):
        return [f for f in reports[key]["findings"] if f["rule_id"] == rid]

    def any_result(key, rid, res):
        return any(f["result"] == res for f in fs(key, rid))

    checks["S1_sata_available"] = any_result("S1", "storage_sata.port_availability", "compatible")
    checks["S2_sata_available"] = any_result("S2", "storage_sata.port_availability", "compatible")
    checks["S3_multiple_sata_available"] = any_result("S3", "storage_sata.port_availability", "compatible")
    checks["S4_missing_count_insufficient"] = any_result("S4", "storage_sata.port_availability", "insufficient_data")
    checks["S5_requires_not_incompatible"] = any_result("S5", "storage_sata.port_availability", "requires_verification") and not any(
        f["result"] == "incompatible" for f in reports["S5"]["findings"] if f["rule_id"].startswith("storage_sata."))
    checks["S5_reason_controllers_not_excluded"] = any(
        (f.get("message_params") or {}).get("reason") == "additional_sata_controllers_or_ports_not_excluded"
        for f in fs("S5", "storage_sata.port_availability"))
    checks["S6_no_sata_port_finding"] = not fs("S6", "storage_sata.port_availability")
    checks["S6_no_topology_finding"] = not fs("S6", "storage_sata.m2_topology")
    checks["S6_m2_fit_compatible"] = any_result("S6", "storage_m2.fit", "compatible")
    for key in ("S7", "S8", "S9"):
        checks[f"{key}_potential_conflict"] = any_result(key, "storage_sata.m2_topology", "requires_verification") and any(
            (f.get("message_params") or {}).get("reason") == "m2_slot_may_disable_sata_ports"
            for f in fs(key, "storage_sata.m2_topology"))
        checks[f"{key}_no_incompatible"] = not any(
            f["result"] == "incompatible" for f in reports[key]["findings"] if f["rule_id"].startswith("storage_sata."))
    s9 = fs("S9", "storage_sata.m2_topology")
    checks["S9_candidate_slots_preserved"] = bool(s9) and len(s9[0]["evidence"]["m2_units"][0]["candidate_slots"]) == 2
    checks["S9_restricting_slot_identified"] = bool(s9) and len(s9[0]["evidence"]["restricting_slots"]) == 1
    checks["S10_all_dimensions"] = (any_result("S10", "storage_m2.fit", "compatible") and
                                    any_result("S10", "storage_sata.port_availability", "compatible") and
                                    any_result("S10", "storage_sata.m2_topology", "requires_verification") and
                                    any_result("S10", "storage_case.bay_2_5_capacity", "compatible") and
                                    any_result("S10", "storage_case.bay_3_5_capacity", "compatible"))
    checks["S10_shared_group_limitation"] = "m2_shared_resource_group_semantics_not_evaluated" in reports["S10"]["limitations"]
    checks["S10_disable_condition_limitation"] = "m2_sata_disable_conditions_not_modeled" in reports["S10"]["limitations"]
    checks["S1_no_global_compatible_from_sata_alone"] = reports["S1"]["overall"] != "compatible"

    # MainWindow construction smoke (automated, not visual)
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
            mw_ok = len([n for n in names if n.startswith("T17.9 Visual - S")]) >= 10
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
        "task": "T17.9 storage connectivity visual validation prep",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "target_localappdata_root": str(target), "pcpo_data_dir": str(pcpo_sub),
        "real_pcpo_dir_captured": str(real_pcpo) if real_pcpo else None, "temp_root": str(temp_root),
        "builds": {k: {"build_id": v, "name": next(b.name for b in state.builds if b.id == v)} for k, v in builds.items()},
        "reports": reports,
        "checks": checks,
        "all_checks_ok": all(v is True for k, v in checks.items() if k not in ("mainwindow_error", "loaded_builds_count")),
        "visual_manual_completed": False,
    }
    out = pcpo_sub / "t179_visual_report.json"
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2, default=str) + "\n", encoding="utf-8")
    print(json.dumps({"ok": report["all_checks_ok"], "report": str(out), "target": str(target),
                      "checks": {k: v for k, v in checks.items() if k != "mainwindow_error"}, "mw_err": mw_err},
                     ensure_ascii=False, indent=2))
    return 0 if report["all_checks_ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
