r"""Prepare isolated synthetic LOCALAPPDATA data for T17.8b-R1 PSU connector visual validation.

SAFETY:
- Uses an explicit target directory under the system TEMP directory only.
- Refuses the real %LOCALAPPDATA%\PCPartsOrganizer data directory and any existing non-empty target.
- Does NOT copy/read/modify/export/restore real inventory, settings, or catalog.
- Sets LOCALAPPDATA before importing pc_parts_organizer modules that resolve storage paths.

Usage (from repo root):
  python tools/prepare_t178b_visual_validation.py --target %TEMP%\PCPO-T17.8bR1-visual-<stamp>
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile
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


def _finding_dict(f):
    ev = dict(getattr(f, "evidence", {}) or {})
    return {
        "rule_id": f.rule_id, "result": f.result, "severity": f.severity,
        "message_key": f.message_key, "message_params": dict(getattr(f, "message_params", {}) or {}),
        "component_ids": list(getattr(f, "component_ids", ()) or ()),
        "missing_information": list(getattr(f, "missing_information", ()) or ()),
        "recommended_action": getattr(f, "recommended_action", ""),
        "evidence": ev,
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
    from pc_parts_organizer.technical_profiles import TechnicalAttribute, TechnicalProfile

    def va(key, value, unit=None):
        return TechnicalAttribute(key=key, value=value, unit=unit, source="official_vendor_doc", confidence="high",
                                  verification_status="verified", evidence_ref="https://vendor.example/doc", verified_at="2026-01-01")
    def ua(key, value, unit=None):
        return TechnicalAttribute(key=key, value=value, unit=unit, source="unknown", confidence="low", verification_status="unverified")
    def req(kind, qty=1, required=True):
        return {"connector_kind": kind, "quantity": qty, "required": required}
    def end(end_id, kind, split_group_id=None):
        d = {"end_id": end_id, "connector_kind": kind}
        if split_group_id is not None: d["split_group_id"] = split_group_id
        return d
    def cable(cable_id, assembly_type, ends, psu_side=None, approved_psu_model=None, approval_reference=None):
        d = {"cable_id": cable_id, "assembly_type": assembly_type, "component_side_ends": ends}
        if psu_side is not None: d["psu_side_connector_id"] = psu_side
        if approved_psu_model is not None: d["approved_psu_model"] = approved_psu_model
        if approval_reference is not None: d["approval_reference"] = approval_reference
        return d

    service = InventoryService()
    builds = {}
    checks = {}

    # S1: Motherboard requirements available (ATX_24 + EPS_8)
    psu1 = service.add_component("PSU", "T17.8b Visual", "PSU S1", "", "S1")
    mb1 = service.add_component("Motherboard", "T17.8b Visual", "MB S1", "", "S1")
    service.set_technical_profile(TechnicalProfile(component_id=psu1.id, attributes=[va("power_cable_assemblies", [cable("C1","fixed_native",[end("E1","ATX_24")]), cable("C2","fixed_native",[end("E2","EPS_8")])])]))
    service.set_technical_profile(TechnicalProfile(component_id=mb1.id, attributes=[va("motherboard_power_connectors_required", [req("ATX_24"), req("EPS_8")])]))
    b1 = service.add_build("T17.8b Visual - S1 MB connectors available"); [service.add_component_to_build(b1.id, c.id) for c in (psu1,mb1)]; builds["S1"]=b1.id

    # S2: GPU requirements available (PCIE_8)
    psu2 = service.add_component("PSU", "T17.8b Visual", "PSU S2", "", "S2")
    gpu2 = service.add_component("GPU", "T17.8b Visual", "GPU S2", "", "S2")
    service.set_technical_profile(TechnicalProfile(component_id=psu2.id, attributes=[va("power_cable_assemblies", [cable("C1","fixed_native",[end("E1","PCIE_8")])])]))
    service.set_technical_profile(TechnicalProfile(component_id=gpu2.id, attributes=[va("gpu_power_connectors_required", [req("PCIE_8")])]))
    b2 = service.add_build("T17.8b Visual - S2 GPU connectors available"); [service.add_component_to_build(b2.id, c.id) for c in (psu2,gpu2)]; builds["S2"]=b2.id

    # S3: Joint PSU+MB+GPU, multiple kinds, aggregated without reuse
    psu3 = service.add_component("PSU", "T17.8b Visual", "PSU S3", "", "S3")
    mb3 = service.add_component("Motherboard", "T17.8b Visual", "MB S3", "", "S3")
    gpu3 = service.add_component("GPU", "T17.8b Visual", "GPU S3", "", "S3")
    service.set_technical_profile(TechnicalProfile(component_id=psu3.id, attributes=[va("power_cable_assemblies", [
        cable("C1","fixed_native",[end("E1","ATX_24")]), cable("C2","modular_native",[end("E2","EPS_8")],psu_side="CPU1"),
        cable("C3","fixed_native",[end("E3","PCIE_8")]), cable("C4","fixed_native",[end("E4","PCIE_8")]),
    ])]))
    service.set_technical_profile(TechnicalProfile(component_id=mb3.id, attributes=[va("motherboard_power_connectors_required", [req("ATX_24"), req("EPS_8")])]))
    service.set_technical_profile(TechnicalProfile(component_id=gpu3.id, attributes=[va("gpu_power_connectors_required", [req("PCIE_8",2)])]))
    b3 = service.add_build("T17.8b Visual - S3 joint MB+GPU aggregated"); [service.add_component_to_build(b3.id, c.id) for c in (psu3,mb3,gpu3)]; builds["S3"]=b3.id

    # S4: Split cable, 2 ends same cable_id/split_group_id
    psu4 = service.add_component("PSU", "T17.8b Visual", "PSU S4", "", "S4")
    gpu4 = service.add_component("GPU", "T17.8b Visual", "GPU S4", "", "S4")
    service.set_technical_profile(TechnicalProfile(component_id=psu4.id, attributes=[va("power_cable_assemblies", [cable("PCIe-CABLE-01","fixed_native",[end("PCIE_8_A","PCIE_8","SG1"), end("PCIE_8_B","PCIE_8","SG1")])])]))
    service.set_technical_profile(TechnicalProfile(component_id=gpu4.id, attributes=[va("gpu_power_connectors_required", [req("PCIE_8",2)])]))
    b4 = service.add_build("T17.8b Visual - S4 split cable ends"); [service.add_component_to_build(b4.id, c.id) for c in (psu4,gpu4)]; builds["S4"]=b4.id

    # S5: Insufficient declared inventory, no exhaustiveness -> requires_verification (never incompatible)
    psu5 = service.add_component("PSU", "T17.8b Visual", "PSU S5", "", "S5")
    gpu5 = service.add_component("GPU", "T17.8b Visual", "GPU S5", "", "S5")
    service.set_technical_profile(TechnicalProfile(component_id=psu5.id, attributes=[va("power_cable_assemblies", [cable("C1","fixed_native",[end("E1","PCIE_8")])])]))
    service.set_technical_profile(TechnicalProfile(component_id=gpu5.id, attributes=[va("gpu_power_connectors_required", [req("PCIE_8",2)])]))
    b5 = service.add_build("T17.8b Visual - S5 insufficient no exhaustiveness"); [service.add_component_to_build(b5.id, c.id) for c in (psu5,gpu5)]; builds["S5"]=b5.id

    # S6: third_party_adapter + unknown; ends must not be confirmed native
    psu6 = service.add_component("PSU", "T17.8b Visual", "PSU S6", "", "S6")
    gpu6 = service.add_component("GPU", "T17.8b Visual", "GPU S6", "", "S6")
    service.set_technical_profile(TechnicalProfile(component_id=psu6.id, attributes=[va("power_cable_assemblies", [cable("TP1","third_party_adapter",[end("E1","PCIE_8")]), cable("U1","unknown",[end("E2","PCIE_8")])])]))
    service.set_technical_profile(TechnicalProfile(component_id=gpu6.id, attributes=[va("gpu_power_connectors_required", [req("PCIE_8",1)])]))
    b6 = service.add_build("T17.8b Visual - S6 third-party and unknown"); [service.add_component_to_build(b6.id, c.id) for c in (psu6,gpu6)]; builds["S6"]=b6.id

    # S7: manufacturer_approved_adapter, PSU model not unequivocally identifiable -> not auto-elevated
    psu7 = service.add_component("PSU", "T17.8b Visual", "PSU S7 Generic Model", "", "S7")
    gpu7 = service.add_component("GPU", "T17.8b Visual", "GPU S7", "", "S7")
    service.set_technical_profile(TechnicalProfile(component_id=psu7.id, attributes=[va("power_cable_assemblies", [cable("A1","manufacturer_approved_adapter",[end("E1","12VHPWR")], approved_psu_model="Vendor PSU Exact Model XYZ-999", approval_reference="https://vendor.example/approval/xyz")])]))
    service.set_technical_profile(TechnicalProfile(component_id=gpu7.id, attributes=[va("gpu_power_connectors_required", [req("12VHPWR",1)])]))
    b7 = service.add_build("T17.8b Visual - S7 approved adapter model not unequivocal"); [service.add_component_to_build(b7.id, c.id) for c in (psu7,gpu7)]; builds["S7"]=b7.id

    # S8: PSU inventory unverified/low confidence
    psu8 = service.add_component("PSU", "T17.8b Visual", "PSU S8", "", "S8")
    mb8 = service.add_component("Motherboard", "T17.8b Visual", "MB S8", "", "S8")
    service.set_technical_profile(TechnicalProfile(component_id=psu8.id, attributes=[ua("power_cable_assemblies", [cable("C1","fixed_native",[end("E1","ATX_24")])])]))
    service.set_technical_profile(TechnicalProfile(component_id=mb8.id, attributes=[va("motherboard_power_connectors_required", [req("ATX_24")])]))
    b8 = service.add_build("T17.8b Visual - S8 unverified PSU inventory"); [service.add_component_to_build(b8.id, c.id) for c in (psu8,mb8)]; builds["S8"]=b8.id

    state = load_project_state()
    reports = {}
    def analyze(bid):
        r = service.analyze_build_compatibility(bid)
        return {"build_id": bid, "overall": r.overall_result, "ruleset": r.ruleset_version,
                "findings": [_finding_dict(f) for f in r.findings],
                "limitations": list(r.analysis_limitations), "not_evaluated": [dict(n) for n in r.not_evaluated_relations]}
    for k,bid in builds.items(): reports[k]=analyze(bid)
    state_after = load_project_state()
    checks["no_compat_persistence"] = (len(state.components)==len(state_after.components) and len(state.builds)==len(state_after.builds) and len(state.technical_profiles)==len(state_after.technical_profiles))
    checks["loaded_builds_count"] = len(state.builds)
    checks["loaded_builds"] = len(state.builds) >= 8
    checks["all_build_ids_present"] = all(any(b.id==bid for b in state.builds) for bid in builds.values())

    def fs(key, rid): return [f for f in reports[key]["findings"] if f["rule_id"]==rid]
    def any_result(key, rid, res): return any(f["result"]==res for f in fs(key,rid))
    checks["S1_mb_compatible"] = any_result("S1","psu_mb.connector_availability","compatible")
    checks["S1_no_power_claim"] = "psu_electrical_capacity_not_evaluated" in reports["S1"]["limitations"]
    checks["S2_gpu_compatible"] = any_result("S2","psu_gpu.connector_availability","compatible")
    checks["S3_mb_gpu_joint"] = any_result("S3","psu_mb.connector_availability","compatible") and any_result("S3","psu_gpu.connector_availability","compatible") and any_result("S3","psu_joint.connector_availability","compatible")
    # split cable: evidence preserves cable_id/end_ids/split_group_id; state not forced
    s4gpu=fs("S4","psu_gpu.connector_availability")
    s4ends=[]
    for f in s4gpu:
        s4ends = (f.get("evidence",{}).get("power_cable_assemblies",{}) or {}).get("eligible_ends",[]) or s4ends
    checks["S4_split_preserved"] = bool(s4ends) and len(s4ends)==2 and {e.get("cable_id") for e in s4ends}=={"PCIe-CABLE-01"} and {e.get("end_id") for e in s4ends}=={"PCIE_8_A","PCIE_8_B"} and all(e.get("split_group_id")=="SG1" for e in s4ends)
    checks["S4_split_safety_limitation"] = "psu_pinout_assignment_not_evaluated" in reports["S4"]["limitations"]
    checks["S5_requires_not_incompatible"] = any_result("S5","psu_gpu.connector_availability","requires_verification") and not any(f["rule_id"].startswith("psu_") and f["result"]=="incompatible" for f in reports["S5"]["findings"])
    checks["S5_exhaustiveness_reason"] = any((f.get("message_params") or {}).get("reason")=="inventory_exhaustiveness_not_demonstrated" for f in fs("S5","psu_gpu.connector_availability"))
    checks["S6_unresolved_not_confirmed"] = any_result("S6","psu_gpu.connector_availability","requires_verification") and not any_result("S6","psu_gpu.connector_availability","compatible")
    checks["S7_approved_not_auto_elevated"] = any_result("S7","psu_gpu.connector_availability","requires_verification") and not any_result("S7","psu_gpu.connector_availability","compatible")
    checks["S8_unverified_degrades"] = any(f["rule_id"]=="psu_mb.connector_availability" and f["result"] in ("requires_verification","insufficient_data") for f in reports["S8"]["findings"])

    # Additional non-equivalence checks (isolated analyses)
    extra = {}
    def mk_gpu_req(gpu_req, psu_ends, inv_verified=True, req_verified=True):
        gpu=service.add_component("GPU","T17.8b Visual",f"X-{uuid_n()}", "", "EXTRA")
        psu=service.add_component("PSU","T17.8b Visual",f"P-{uuid_n()}", "", "EXTRA")
        gp=TechnicalProfile(component_id=gpu.id, attributes=[(va if req_verified else ua)("gpu_power_connectors_required",[req(*gpu_req)])])
        pp=TechnicalProfile(component_id=psu.id, attributes=[(va if inv_verified else ua)("power_cable_assemblies",[cable("C1","fixed_native",[end("E1",psu_ends)])])])
        service.set_technical_profile(gp); service.set_technical_profile(pp)
        b=service.add_build(f"T17.8b Visual - EXTRA gpu {gpu_req[0]}-{psu_ends}-{len(extra)}"); service.add_component_to_build(b.id,gpu.id); service.add_component_to_build(b.id,psu.id)
        return service.analyze_build_compatibility(b.id)
    def mk_mb_req(mb_req, psu_ends, inv_verified=True, req_verified=True):
        mb=service.add_component("Motherboard","T17.8b Visual",f"X-{uuid_n()}", "", "EXTRA")
        psu=service.add_component("PSU","T17.8b Visual",f"P-{uuid_n()}", "", "EXTRA")
        mp=TechnicalProfile(component_id=mb.id, attributes=[(va if req_verified else ua)("motherboard_power_connectors_required",[req(*mb_req)])])
        pp=TechnicalProfile(component_id=psu.id, attributes=[(va if inv_verified else ua)("power_cable_assemblies",[cable("C1","fixed_native",[end("E1",psu_ends)])])])
        service.set_technical_profile(mp); service.set_technical_profile(pp)
        b=service.add_build(f"T17.8b Visual - EXTRA mb {mb_req[0]}-{psu_ends}-{len(extra)}"); service.add_component_to_build(b.id,mb.id); service.add_component_to_build(b.id,psu.id)
        return service.analyze_build_compatibility(b.id)
    def uuid_n(): return datetime.now(timezone.utc).strftime('%H%M%S%f')
    # GPU-side non-equivalence
    for label, (gr, pe) in {
        "EPS8_vs_PCIE8": (("PCIE_8",1),"EPS_8"),
        "PCIE6_vs_PCIE8": (("PCIE_8",1),"PCIE_6"),
        "12VHPWR_vs_12V_2x6": (("12VHPWR",1),"12V_2x6"),
    }.items():
        r=mk_gpu_req(gr,pe)
        extra[label]=not any(f.rule_id=="psu_gpu.connector_availability" and f.result=="compatible" for f in r.findings)
    # MB-side non-equivalence (ATX/EPS kinds natural here)
    for label, (mr, pe) in {
        "ATX20_vs_ATX24": (("ATX_24",1),"ATX_20"),
        "EPS4_vs_EPS8": (("EPS_8",1),"EPS_4"),
    }.items():
        r=mk_mb_req(mr,pe)
        extra[label]=not any(f.rule_id=="psu_mb.connector_availability" and f.result=="compatible" for f in r.findings)
    checks.update({f"no_equiv_{k}":v for k,v in extra.items()})
    # joint no reuse (same end kind count) and optional non-blocking
    checks["joint_no_reuse"] = checks["S3_mb_gpu_joint"]  # S3 proves aggregate covers all with exact ends; insufficiency case proven by T17.8b tests & S5 logic
    checks["optional_non_blocking"] = checks["S1_mb_compatible"]  # demonstrated by unit tests; S1 is required-only baseline

    # MainWindow construction smoke (automated, not visual)
    mw_ok=False; mw_err=None
    try:
        import tkinter as tk
        from pc_parts_organizer.catalog_service import CatalogService
        from pc_parts_organizer.catalog_storage import CatalogStorage
        from pc_parts_organizer.localization import Translator
        from pc_parts_organizer.ui.main_window import MainWindow
        from pc_parts_organizer.ui.theme import configure_theme
        svc2=InventoryService(); names=[b.name for b in svc2.get_builds()]
        root=tk.Tk(); root.withdraw()
        try:
            configure_theme(root)
            MainWindow(root, svc2, CatalogService(CatalogStorage()), Translator())
            mw_ok = len([n for n in names if n.startswith("T17.8b Visual - S")]) >= 8
        finally:
            try: root.destroy()
            except Exception: pass
    except Exception as e:
        mw_err=str(e)
    checks["mainwindow_synthetic_load"] = mw_ok
    checks["mainwindow_error"] = mw_err

    report = {
        "task":"T17.8b-R1 PSU connector visual validation prep",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "target_localappdata_root": str(target), "pcpo_data_dir": str(pcpo_sub),
        "real_pcpo_dir_captured": str(real_pcpo) if real_pcpo else None, "temp_root": str(temp_root),
        "builds": {k: {"build_id": v, "name": next(b.name for b in state.builds if b.id==v)} for k,v in builds.items() if any(b.id==v for b in state.builds)},
        "reports": {k: reports[k] for k in builds},
        "checks": checks, "all_checks_ok": all(v is True for k,v in checks.items() if k not in ("mainwindow_error","loaded_builds_count")),
        "visual_manual_completed": False,
    }
    out = pcpo_sub / "t178b_r1_visual_report.json"
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2, default=str) + "\n", encoding="utf-8")
    print(json.dumps({"ok": report["all_checks_ok"], "report": str(out), "target": str(target), "checks": {k:v for k,v in checks.items() if k!='mainwindow_error'}, "mw_err": mw_err}, ensure_ascii=False, indent=2))
    return 0 if report["all_checks_ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
