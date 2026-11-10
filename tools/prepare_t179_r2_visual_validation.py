r"""Prepare isolated synthetic LOCALAPPDATA data for T17.9-R2 visual validation.

Covers classification fixes: indeterminate units, unverified data, empty slot
inventory, multiple motherboards. Reuses real APIs; never touches real data.
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

    def va(key, value):
        return TechnicalAttribute(key=key, value=value, source="official_vendor_doc", confidence="high",
                                  verification_status="verified", evidence_ref="https://vendor.example/doc", verified_at="2026-01-01")

    def ua(key, value):
        return TechnicalAttribute(key=key, value=value, source="unknown", confidence="low", verification_status="unverified")

    def sattr(ff, iface=None, cmd=None, key=None, length=None, ff_v=True, if_v=True, cmd_v=True):
        a = [(va if ff_v else ua)("storage_form_factor", ff)]
        if iface is not None:
            a.append((va if if_v else ua)("storage_interface", iface))
        if cmd is not None:
            a.append((va if cmd_v else ua)("storage_command_set", cmd))
        if key is not None:
            a.append(va("m2_keying", key))
        if length is not None:
            a.append(va("m2_length_code", length))
        return a

    def slot(sid, keyings=("M",), modes=("pcie_nvme",), disables=(), shared=None, routed="unknown", evidence="https://vendor.example/slot"):
        return M2SlotSpec(slot_id=sid, accepted_module_keyings=keyings, supported_lengths=("2280",),
                          supported_modes=modes, disables_sata_port_ids=disables,
                          shared_resource_group_id=shared, routed_to=routed, evidence_ref=evidence)

    svc = InventoryService()
    builds = {}

    def make_build(name, comps_specs):
        # comps_specs: list of (category, model, attrs or None, extra_category_attrs?)
        comps = []
        for cat, model, attrs in comps_specs:
            c = svc.add_component(cat, "T17.9-R2", model, "", "T17.9-R2")
            if attrs is not None:
                svc.set_technical_profile(TechnicalProfile(component_id=c.id, attributes=attrs))
            comps.append(c)
        b = svc.add_build(name)
        for c in comps:
            svc.add_component_to_build(b.id, c.id)
        return b.id

    # S1 SATA 2.5 verified
    builds["S1"] = make_build("T17.9-R2 - S1 SATA 2.5 verified", [
        ("Motherboard", "MB S1", [va("sata_port_count", 2)]),
        ("Storage", "SSD 2.5 S1", sattr("2_5_in", "sata", "ata")),
    ])
    # S2 SATA 3.5 verified
    builds["S2"] = make_build("T17.9-R2 - S2 SATA 3.5 verified", [
        ("Motherboard", "MB S2", [va("sata_port_count", 1)]),
        ("Storage", "HDD 3.5 S2", sattr("3_5_in", "sata", "ata")),
    ])
    # S3 critical repro: verified SATA + unverified 2.5 pcie/nvme
    builds["S3"] = make_build("T17.9-R2 - S3 critical unverified unit", [
        ("Motherboard", "MB S3", [va("sata_port_count", 1)]),
        ("Storage", "SSD A S3", sattr("2_5_in", "sata", "ata")),
        ("Storage", "SSD B S3", sattr("2_5_in", "pcie", "nvme", ff_v=False, if_v=False, cmd_v=False)),
    ])
    # S4 verified count + unverified IDs
    builds["S4"] = make_build("T17.9-R2 - S4 verified count unverified IDs", [
        ("Motherboard", "MB S4", [va("sata_port_count", 1), ua("sata_port_identifiers", ["SATA1"])]),
        ("Storage", "SSD S4", sattr("2_5_in", "sata", "ata")),
    ])
    # S5 count missing + IDs present
    builds["S5"] = make_build("T17.9-R2 - S5 count missing IDs present", [
        ("Motherboard", "MB S5", [va("sata_port_identifiers", ["SATA1", "SATA2"])]),
        ("Storage", "SSD S5", sattr("2_5_in", "sata", "ata")),
    ])
    # S6 count unverified
    builds["S6"] = make_build("T17.9-R2 - S6 count unverified", [
        ("Motherboard", "MB S6", [ua("sata_port_count", 2)]),
        ("Storage", "SSD S6", sattr("2_5_in", "sata", "ata")),
    ])
    # S7 bay + no-profile unit
    b7mb = svc.add_component("Motherboard", "T17.9-R2", "MB S7", "", "")
    svc.set_technical_profile(TechnicalProfile(component_id=b7mb.id, attributes=[va("sata_port_count", 2)]))
    b7case = svc.add_component("Case", "T17.9-R2", "Case S7", "", "")
    svc.set_technical_profile(TechnicalProfile(component_id=b7case.id, attributes=[va("bay_2_5_total", 1)]))
    b7a = svc.add_component("Storage", "T17.9-R2", "SSD S7A", "", "")
    svc.set_technical_profile(TechnicalProfile(component_id=b7a.id, attributes=[va("storage_form_factor", "2_5_in")]))
    b7b = svc.add_component("Storage", "T17.9-R2", "SSD S7B no profile", "", "")
    b7 = svc.add_build("T17.9-R2 - S7 bay plus no-profile unit")
    for c in (b7mb, b7case, b7a, b7b):
        svc.add_component_to_build(b7.id, c.id)
    builds["S7"] = b7.id
    # S8 bay + unverified other
    builds["S8"] = make_build("T17.9-R2 - S8 bay plus unverified other", [
        ("Case", "Case S8", [va("bay_2_5_total", 1)]),
        ("Storage", "SSD S8A", [va("storage_form_factor", "2_5_in")]),
        ("Storage", "SSD S8B", [ua("storage_form_factor", "other")]),
    ])
    # S9 only M.2 no case
    builds["S9"] = make_build("T17.9-R2 - S9 M.2 only no case", [
        ("Motherboard", "MB S9", [va("sata_port_count", 0), va("m2_slots", [slot("M2_1")])]),
        ("Storage", "NVMe S9", sattr("m2", "pcie", "nvme", "M", "2280")),
    ])
    # S10 only addin
    builds["S10"] = make_build("T17.9-R2 - S10 addin only", [
        ("Motherboard", "MB S10", [va("sata_port_count", 2)]),
        ("Storage", "AIC S10", [va("storage_form_factor", "pcie_addin")]),
    ])
    # S11 addin + SATA, no false M.2
    builds["S11"] = make_build("T17.9-R2 - S11 addin plus SATA", [
        ("Motherboard", "MB S11", [va("sata_port_count", 2), va("m2_slots", [slot("M2_1")])]),
        ("Storage", "SSD S11", sattr("2_5_in", "sata", "ata")),
        ("Storage", "AIC S11", [va("storage_form_factor", "pcie_addin")]),
    ])
    # S12 m2_slots missing
    builds["S12"] = make_build("T17.9-R2 - S12 slots missing", [
        ("Motherboard", "MB S12", [va("sata_port_count", 2), va("sata_port_identifiers", ["SATA1", "SATA2"])]),
        ("Storage", "NVMe S12", sattr("m2", "pcie", "nvme", "M", "2280")),
        ("Storage", "SSD S12", sattr("2_5_in", "sata", "ata")),
    ])
    # S13 m2_slots empty verified
    builds["S13"] = make_build("T17.9-R2 - S13 slots empty verified", [
        ("Motherboard", "MB S13", [va("sata_port_count", 2), va("m2_slots", [])]),
        ("Storage", "NVMe S13", sattr("m2", "pcie", "nvme", "M", "2280")),
        ("Storage", "SSD S13", sattr("2_5_in", "sata", "ata")),
    ])
    # S14 M.2 unknown mode + SATA
    builds["S14"] = make_build("T17.9-R2 - S14 M.2 unknown mode", [
        ("Motherboard", "MB S14", [va("sata_port_count", 2), va("sata_port_identifiers", ["SATA1", "SATA2"]), va("m2_slots", [slot("M2_1", disables=("SATA1",))])]),
        ("Storage", "M2 S14", [va("storage_form_factor", "m2"), va("m2_keying", "M"), va("m2_length_code", "2280")]),
        ("Storage", "SSD S14", sattr("2_5_in", "sata", "ata")),
    ])
    # S15 restricting slot, IDs not contrastable
    builds["S15"] = make_build("T17.9-R2 - S15 uncontrastable IDs", [
        ("Motherboard", "MB S15", [va("sata_port_count", 2), va("m2_slots", [slot("M2_1", disables=("SATA9",))])]),
        ("Storage", "NVMe S15", sattr("m2", "pcie", "nvme", "M", "2280")),
        ("Storage", "SSD S15", sattr("2_5_in", "sata", "ata")),
    ])
    # S16 two motherboards
    m16a = svc.add_component("Motherboard", "T17.9-R2", "MB S16A", "", "")
    svc.set_technical_profile(TechnicalProfile(component_id=m16a.id, attributes=[va("sata_port_count", 2), va("m2_slots", [slot("M2_1")])]))
    m16b = svc.add_component("Motherboard", "T17.9-R2", "MB S16B", "", "")
    svc.set_technical_profile(TechnicalProfile(component_id=m16b.id, attributes=[va("sata_port_count", 4), va("m2_slots", [slot("M2_1", disables=("SATA1",)), slot("M2_2")])]))
    s16a = svc.add_component("Storage", "T17.9-R2", "NVMe S16", "", "")
    svc.set_technical_profile(TechnicalProfile(component_id=s16a.id, attributes=sattr("m2", "pcie", "nvme", "M", "2280")))
    s16b = svc.add_component("Storage", "T17.9-R2", "SSD S16", "", "")
    svc.set_technical_profile(TechnicalProfile(component_id=s16b.id, attributes=sattr("2_5_in", "sata", "ata")))
    b16 = svc.add_build("T17.9-R2 - S16 two motherboards")
    for c in (m16a, m16b, s16a, s16b):
        svc.add_component_to_build(b16.id, c.id)
    builds["S16"] = b16.id
    # S17 colon slot IDs + multiple M.2
    builds["S17"] = make_build("T17.9-R2 - S17 colon slots multi M.2", [
        ("Motherboard", "MB S17", [va("sata_port_count", 2), va("sata_port_identifiers", ["SATA1", "SATA2"]), va("m2_slots", [slot("M2:1", disables=("SATA1",)), slot("M2:2", disables=("SATA1",))])]),
        ("Storage", "NVMe S17A", sattr("m2", "pcie", "nvme", "M", "2280")),
        ("Storage", "NVMe S17B", sattr("m2", "pcie", "nvme", "M", "2280")),
        ("Storage", "SSD S17", sattr("2_5_in", "sata", "ata")),
        ("Case", "Case S17", [va("bay_2_5_total", 2)]),
    ])

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
    checks["no_compat_persistence"] = (len(state.components) == len(state_after.components) and len(state.builds) == len(state_after.builds) and len(state.technical_profiles) == len(state_after.technical_profiles))
    checks["loaded_builds_count"] = len(state.builds)
    checks["loaded_builds"] = len(state.builds) >= 17
    checks["all_build_ids_present"] = all(any(b.id == bid for b in state.builds) for bid in builds.values())

    def fs(key, rid):
        return [f for f in reports[key]["findings"] if f["rule_id"] == rid]

    def any_result(key, rid, res):
        return any(f["result"] == res for f in fs(key, rid))

    checks["S1_sata_compatible"] = any_result("S1", "storage_sata.port_availability", "compatible")
    checks["S2_sata_compatible"] = any_result("S2", "storage_sata.port_availability", "compatible")
    checks["S3_critical_requires"] = any_result("S3", "storage_sata.port_availability", "requires_verification") and not any_result("S3", "storage_sata.port_availability", "compatible")
    checks["S4_count_ids_compatible"] = any_result("S4", "storage_sata.port_availability", "compatible")
    checks["S5_count_missing"] = any_result("S5", "storage_sata.port_availability", "insufficient_data")
    checks["S6_count_unverified"] = any_result("S6", "storage_sata.port_availability", "requires_verification")
    checks["S7_bay_indeterminate"] = any_result("S7", "storage_case.bay_2_5_capacity", "requires_verification")
    checks["S8_bay_indeterminate"] = any_result("S8", "storage_case.bay_2_5_capacity", "requires_verification")
    checks["S9_no_case_missing"] = not fs("S9", "storage_case.case_missing")
    checks["S10_no_m2"] = not [f for f in reports["S10"]["findings"] if f["rule_id"].startswith("storage_m2.")]
    checks["S11_no_false_m2"] = any_result("S11", "storage_sata.port_availability", "compatible")
    checks["S12_slots_missing"] = any_result("S12", "storage_sata.m2_topology", "insufficient_data")
    checks["S13_slots_empty"] = any_result("S13", "storage_sata.m2_topology", "requires_verification")
    checks["S14_unknown_mode"] = any_result("S14", "storage_sata.m2_topology", "requires_verification")
    checks["S15_uncontrastable"] = any_result("S15", "storage_sata.m2_topology", "requires_verification")
    s16 = reports["S16"]
    checks["S16_ambiguous"] = any(f["rule_id"] == "storage_sata.ambiguous_motherboard" for f in s16["findings"]) or any(f["rule_id"] == "storage_sata.m2_topology" and f["result"] == "insufficient_data" for f in s16["findings"])
    checks["S17_colon_count"] = True
    s17 = fs("S17", "storage_sata.m2_topology")
    if s17:
        checks["S17_colon_count"] = s17[0]["message_params"].get("restricting_slots") == 2
    checks["S3_no_global_compatible"] = reports["S3"]["overall"] != "compatible"

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
            mw_ok = len([n for n in names if n.startswith("T17.9-R2 - S")]) >= 17
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
        "task": "T17.9-R2 visual validation prep",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "target_localappdata_root": str(target), "pcpo_data_dir": str(pcpo_sub),
        "real_pcpo_dir_captured": str(real_pcpo) if real_pcpo else None, "temp_root": str(temp_root),
        "builds": {k: {"build_id": v, "name": next(b.name for b in state.builds if b.id == v)} for k, v in builds.items()},
        "reports": reports,
        "checks": checks,
        "all_checks_ok": all(v is True for k, v in checks.items() if k not in ("mainwindow_error", "loaded_builds_count")),
        "visual_manual_completed": False,
    }
    out = pcpo_sub / "t179_r2_visual_report.json"
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2, default=str) + "\n", encoding="utf-8")
    print(json.dumps({"ok": report["all_checks_ok"], "report": str(out), "target": str(target),
                      "checks": {k: v for k, v in checks.items() if k != "mainwindow_error"}, "mw_err": mw_err},
                     ensure_ascii=False, indent=2))
    return 0 if report["all_checks_ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
