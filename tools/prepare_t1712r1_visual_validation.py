r"""Prepare isolated synthetic LOCALAPPDATA for T17.12-R1 contract validation.

Builds R1..R6: mb Proprietary, psu Proprietary, SFX vs SFX-L, cpu_mb match,
cpu_mb mismatch, combined physical build. Real APIs only; never real data.
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

    svc = InventoryService()
    builds = {}

    def add_pair(cat_a, attrs_a, cat_b, attrs_b, name):
        a = svc.add_component(cat_a, "T17.12-R1", f"{cat_a} {name}", "", "T17.12-R1")
        b = svc.add_component(cat_b, "T17.12-R1", f"{cat_b} {name}", "", "T17.12-R1")
        svc.set_technical_profile(TechnicalProfile(component_id=a.id, attributes=attrs_a))
        svc.set_technical_profile(TechnicalProfile(component_id=b.id, attributes=attrs_b))
        bl = svc.add_build(name)
        svc.add_component_to_build(bl.id, a.id)
        svc.add_component_to_build(bl.id, b.id)
        return bl.id

    builds["R1"] = add_pair("Motherboard", [va("form_factor", "Proprietary")],
                            "Case", [va("supported_motherboard_form_factors", ["ATX"])],
                            "T17.12-R1 - R1 mb Proprietary")
    builds["R2"] = add_pair("PSU", [va("psu_form_factor", "Proprietary")],
                            "Case", [va("supported_psu_form_factors", ["ATX"])],
                            "T17.12-R1 - R2 psu Proprietary")
    builds["R3"] = add_pair("PSU", [va("psu_form_factor", "SFX")],
                            "Case", [va("supported_psu_form_factors", ["SFX-L"])],
                            "T17.12-R1 - R3 SFX vs SFX-L")
    builds["R4"] = add_pair("CPU", [va("socket_designation", "AM5")],
                            "Motherboard", [va("socket_designation", "AM5")],
                            "T17.12-R1 - R4 cpu_mb match")
    builds["R5"] = add_pair("CPU", [va("socket_designation", "AM5")],
                            "Motherboard", [va("socket_designation", "LGA1700")],
                            "T17.12-R1 - R5 cpu_mb mismatch")

    mb = svc.add_component("Motherboard", "T17.12-R1", "MB R6", "", "T17.12-R1")
    gpu = svc.add_component("GPU", "T17.12-R1", "GPU R6", "", "T17.12-R1")
    cool = svc.add_component("Cooling", "T17.12-R1", "Cooler R6", "", "T17.12-R1")
    psu = svc.add_component("PSU", "T17.12-R1", "PSU R6", "", "T17.12-R1")
    case = svc.add_component("Case", "T17.12-R1", "Case R6", "", "T17.12-R1")
    svc.set_technical_profile(TechnicalProfile(component_id=mb.id, attributes=[va("form_factor", "ATX")]))
    svc.set_technical_profile(TechnicalProfile(component_id=gpu.id, attributes=[va("card_length_mm", 300)]))
    svc.set_technical_profile(TechnicalProfile(component_id=cool.id, attributes=[va("cooler_type", "air_cpu_cooler"), va("cooler_height_mm", 150)]))
    svc.set_technical_profile(TechnicalProfile(component_id=psu.id, attributes=[va("psu_form_factor", "SFX")]))
    svc.set_technical_profile(TechnicalProfile(component_id=case.id, attributes=[
        va("supported_motherboard_form_factors", ["ATX"]), va("max_gpu_length_mm", 350),
        va("max_cpu_cooler_height_mm", 160), va("supported_psu_form_factors", ["SFX-L"])]))
    b6 = svc.add_build("T17.12-R1 - R6 combined")
    for c in (mb, gpu, cool, psu, case):
        svc.add_component_to_build(b6.id, c.id)
    builds["R6"] = b6.id

    state = load_project_state()
    reports = {}

    def analyze(bid):
        r = svc.analyze_build_compatibility(bid)
        return {"build_id": bid, "overall": r.overall_result, "ruleset": r.ruleset_version,
                "rules_evaluated": r.rules_evaluated,
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
    checks["loaded_builds"] = len(state.builds) >= 6
    checks["all_build_ids_present"] = all(any(b.id == bid for b in state.builds) for bid in builds.values())

    def one(key, rid):
        fs = [f for f in reports[key]["findings"] if f["rule_id"] == rid]
        assert len(fs) == 1, f"{key}/{rid}: {len(fs)}"
        return fs[0]

    checks["R1_mb_prop_rv"] = (lambda f: f["result"] == "requires_verification"
                               and f["message_params"].get("reason") == "proprietary_requires_specific_documentation"
                               and "apparent_conflict" in f["message_params"])(one("R1", "mb_case.form_factor"))
    checks["R2_psu_prop_rv"] = (lambda f: f["result"] == "requires_verification"
                                and f["message_params"].get("reason") == "proprietary_requires_specific_documentation"
                                and "apparent_conflict" in f["message_params"])(one("R2", "psu_case.form_factor"))
    checks["R3_sfx_rv"] = (lambda f: f["result"] == "requires_verification"
                           and f["message_params"].get("reason") == "sfx_sfxl_requires_manual_check")(one("R3", "psu_case.form_factor"))
    checks["R4_match_rv"] = (lambda f: f["result"] == "requires_verification"
                             and f["message_params"].get("reason") == "socket_match_pending_platform")(one("R4", "cpu_mb.socket_visibility"))
    checks["R5_mismatch_rv"] = (lambda f: f["result"] == "requires_verification"
                                and f["message_params"].get("reason") == "socket_mismatch_unresolved")(one("R5", "cpu_mb.socket_visibility"))
    checks["R6_rules"] = {"mb_case.form_factor", "gpu_case.max_length",
                          "cooling_case.air_cooler_height", "psu_case.form_factor"} <= {f["rule_id"] for f in reports["R6"]["findings"]}
    checks["R6_global_rv"] = reports["R6"]["overall"] == "requires_verification"

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
            mw_ok = len([n for n in names if n.startswith("T17.12-R1 - R")]) >= 6
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
        "task": "T17.12-R1 contract validation prep",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "target_localappdata_root": str(target), "pcpo_data_dir": str(pcpo_sub),
        "real_pcpo_dir_captured": str(real_pcpo) if real_pcpo else None, "temp_root": str(temp_root),
        "builds": {k: {"build_id": v, "name": next(b.name for b in state.builds if b.id == v)} for k, v in builds.items()},
        "reports": reports,
        "checks": checks,
        "all_checks_ok": all(v is True for k, v in checks.items() if k != "mainwindow_error"),
        "visual_manual_completed": False,
    }
    out = pcpo_sub / "t1712r1_visual_report.json"
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2, default=str) + "\n", encoding="utf-8")
    print(json.dumps({"ok": report["all_checks_ok"], "report": str(out), "target": str(target),
                      "checks": {k: v for k, v in checks.items() if k != "mainwindow_error"}, "mw_err": mw_err},
                     ensure_ascii=False, indent=2))
    return 0 if report["all_checks_ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
