r"""Prepare isolated synthetic LOCALAPPDATA for T17.12 psu_case visual validation.

Scenarios S1..S10 cover: exact match, SFX/SFX-L both directions, Other on
either side, Proprietary, unverified data, mixed exact match, recognized
mismatch, and a combined multi-relation physical build. Real APIs only;
never touches real data.
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
    from pc_parts_organizer.technical_profiles import TechnicalAttribute, TechnicalProfile

    def va(key, value):
        return TechnicalAttribute(key=key, value=value, source="official_vendor_doc", confidence="high",
                                  verification_status="verified", evidence_ref="https://vendor.example/doc",
                                  verified_at="2026-01-01")

    def ua(key, value):
        return TechnicalAttribute(key=key, value=value, source="unknown",
                                  confidence="low", verification_status="unverified")

    svc = InventoryService()
    builds = {}

    def add_build(name, psu_attrs, case_attrs):
        psu = svc.add_component("PSU", "T17.12", f"PSU {name}", "", "T17.12")
        case = svc.add_component("Case", "T17.12", f"Case {name}", "", "T17.12")
        svc.set_technical_profile(TechnicalProfile(component_id=psu.id, attributes=psu_attrs))
        svc.set_technical_profile(TechnicalProfile(component_id=case.id, attributes=case_attrs))
        b = svc.add_build(name)
        svc.add_component_to_build(b.id, psu.id)
        svc.add_component_to_build(b.id, case.id)
        return b.id

    builds["S1"] = add_build("T17.12 - S1 exact ATX match", [va("psu_form_factor", "ATX")], [va("supported_psu_form_factors", ["ATX"])])
    builds["S2"] = add_build("T17.12 - S2 SFX vs SFX-L", [va("psu_form_factor", "SFX")], [va("supported_psu_form_factors", ["SFX-L"])])
    builds["S3"] = add_build("T17.12 - S3 SFX-L vs SFX", [va("psu_form_factor", "SFX-L")], [va("supported_psu_form_factors", ["SFX"])])
    builds["S4"] = add_build("T17.12 - S4 PSU Other", [va("psu_form_factor", "Other")], [va("supported_psu_form_factors", ["ATX"])])
    builds["S5"] = add_build("T17.12 - S5 case Other list", [va("psu_form_factor", "ATX")], [va("supported_psu_form_factors", ["Other"])])
    builds["S6"] = add_build("T17.12 - S6 Proprietary", [va("psu_form_factor", "ATX")], [va("supported_psu_form_factors", ["Proprietary"])])
    builds["S7"] = add_build("T17.12 - S7 unverified", [ua("psu_form_factor", "ATX")], [va("supported_psu_form_factors", ["ATX"])])
    builds["S8"] = add_build("T17.12 - S8 mixed exact", [va("psu_form_factor", "SFX")], [va("supported_psu_form_factors", ["ATX", "SFX"])])
    builds["S9"] = add_build("T17.12 - S9 recognized mismatch", [va("psu_form_factor", "ATX")], [va("supported_psu_form_factors", ["SFX"])])

    # S10: combined physical build (MB+GPU+cooler+PSU vs case)
    mb = svc.add_component("Motherboard", "T17.12", "MB S10", "", "T17.12")
    gpu = svc.add_component("GPU", "T17.12", "GPU S10", "", "T17.12")
    cool = svc.add_component("Cooling", "T17.12", "Cooler S10", "", "T17.12")
    psu = svc.add_component("PSU", "T17.12", "PSU S10", "", "T17.12")
    case = svc.add_component("Case", "T17.12", "Case S10", "", "T17.12")
    svc.set_technical_profile(TechnicalProfile(component_id=mb.id, attributes=[va("form_factor", "ATX")]))
    svc.set_technical_profile(TechnicalProfile(component_id=gpu.id, attributes=[va("card_length_mm", 300)]))
    svc.set_technical_profile(TechnicalProfile(component_id=cool.id, attributes=[va("cooler_type", "air_cpu_cooler"), va("cooler_height_mm", 150)]))
    svc.set_technical_profile(TechnicalProfile(component_id=psu.id, attributes=[va("psu_form_factor", "ATX")]))
    svc.set_technical_profile(TechnicalProfile(component_id=case.id, attributes=[
        va("supported_motherboard_form_factors", ["ATX"]), va("max_gpu_length_mm", 350),
        va("max_cpu_cooler_height_mm", 160), va("supported_psu_form_factors", ["ATX"])]))
    b10 = svc.add_build("T17.12 - S10 combined physical")
    for c in (mb, gpu, cool, psu, case):
        svc.add_component_to_build(b10.id, c.id)
    builds["S10"] = b10.id

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
    checks["loaded_builds"] = len(state.builds) >= 10
    checks["all_build_ids_present"] = all(any(b.id == bid for b in state.builds) for bid in builds.values())

    def fs(key, rid):
        return [f for f in reports[key]["findings"] if f["rule_id"] == rid]

    def res(key):
        return [f["result"] for f in fs(key, "psu_case.form_factor")]

    checks["S1_compatible"] = res("S1") == ["compatible"]
    checks["S1_global_rv"] = reports["S1"]["overall"] == "requires_verification"
    checks["S2_sfx_reason"] = (res("S2") == ["requires_verification"]
                               and fs("S2", "psu_case.form_factor")[0]["message_params"].get("reason") == "sfx_sfxl_requires_manual_check")
    checks["S3_sfx_reason"] = (res("S3") == ["requires_verification"]
                               and fs("S3", "psu_case.form_factor")[0]["message_params"].get("reason") == "sfx_sfxl_requires_manual_check")
    checks["S4_other"] = (res("S4") == ["requires_verification"]
                          and fs("S4", "psu_case.form_factor")[0]["message_params"].get("reason") == "other_not_confirmable")
    checks["S5_other_list"] = (res("S5") == ["requires_verification"]
                              and fs("S5", "psu_case.form_factor")[0]["message_params"].get("reason") == "other_not_confirmable")
    checks["S6_proprietary"] = (res("S6") == ["requires_verification"]
                                and fs("S6", "psu_case.form_factor")[0]["message_params"].get("reason") == "proprietary_requires_specific_documentation")
    checks["S7_unverified"] = (res("S7") == ["requires_verification"]
                               and fs("S7", "psu_case.form_factor")[0]["message_params"].get("reason") == "attributes_not_verified")
    checks["S8_mixed_compatible"] = res("S8") == ["compatible"]
    checks["S9_incompatible"] = (res("S9") == ["incompatible"]
                                 and fs("S9", "psu_case.form_factor")[0]["severity"] == "critical"
                                 and reports["S9"]["overall"] == "incompatible")
    checks["S9_no_other_rules_incompatible"] = not any(
        f["result"] == "incompatible" for f in reports["S9"]["findings"] if f["rule_id"] != "psu_case.form_factor")
    s10_rules = {f["rule_id"] for f in reports["S10"]["findings"]}
    checks["S10_multi_physical"] = {"mb_case.form_factor", "gpu_case.max_length",
                                    "cooling_case.air_cooler_height", "psu_case.form_factor"} <= s10_rules
    checks["S10_depth_limits"] = ("psu_case_depth_not_evaluated" in reports["S10"]["limitations"]
                                  and "psu_case_cable_clearance_not_evaluated" in reports["S10"]["limitations"])
    checks["S10_global_rv"] = reports["S10"]["overall"] == "requires_verification"

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
            mw_ok = len([n for n in names if n.startswith("T17.12 - S")]) >= 10
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
        "task": "T17.12 psu_case visual validation prep",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "target_localappdata_root": str(target), "pcpo_data_dir": str(pcpo_sub),
        "real_pcpo_dir_captured": str(real_pcpo) if real_pcpo else None, "temp_root": str(temp_root),
        "builds": {k: {"build_id": v, "name": next(b.name for b in state.builds if b.id == v)} for k, v in builds.items()},
        "reports": reports,
        "checks": checks,
        "all_checks_ok": all(v is True for k, v in checks.items() if k not in ("mainwindow_error",)),
        "visual_manual_completed": False,
    }
    out = pcpo_sub / "t1712_visual_report.json"
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2, default=str) + "\n", encoding="utf-8")
    print(json.dumps({"ok": report["all_checks_ok"], "report": str(out), "target": str(target),
                      "checks": {k: v for k, v in checks.items() if k != "mainwindow_error"}, "mw_err": mw_err},
                     ensure_ascii=False, indent=2))
    return 0 if report["all_checks_ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
