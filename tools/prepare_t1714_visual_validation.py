r"""Prepare isolated synthetic LOCALAPPDATA for T17.14 comparator validation.

Scenario builds for the A/B matrix. Real APIs only; never real data.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile
from collections.abc import Mapping as ABCMapping
from dataclasses import is_dataclass
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
    if is_dataclass(value):
        if hasattr(value, "to_dict"):
            return _jsonable(value.to_dict())
        from dataclasses import fields
        return {f.name: _jsonable(getattr(value, f.name)) for f in fields(value)}
    if isinstance(value, ABCMapping):
        return {str(k): _jsonable(v) for k, v in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_jsonable(v) for v in value]
    return value


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
    if repo not in sys.path:
        sys.path.insert(0, str(repo))

    from pc_parts_organizer.service import InventoryService
    from pc_parts_organizer.storage import load_project_state
    from pc_parts_organizer.build_compare import compare_hardware, compare_reports, correspondence_from_hardware
    from pc_parts_organizer.technical_profiles import TechnicalAttribute, TechnicalProfile

    def va(key, value):
        return TechnicalAttribute(key=key, value=value, source="official_vendor_doc", confidence="high",
                                  verification_status="verified", evidence_ref="https://vendor.example/doc",
                                  verified_at="2026-01-01")

    def ua(key, value):
        return TechnicalAttribute(key=key, value=value, source="unknown",
                                  confidence="low", verification_status="unverified")

    svc = InventoryService()

    def mk(cat, model):
        return svc.add_component(cat, "T17.14", model, "", "T17.14")

    builds = {}

    def new_build(name, comp_ids):
        b = svc.add_build(name)
        for cid in comp_ids:
            svc.add_component_to_build(b.id, cid)
        return b.id

    # base verified parts (one set per build; instances differ across builds)
    g1, g2 = mk("GPU", "GPU-A"), mk("GPU", "GPU-B")
    cpu1, cpu2 = mk("CPU", "CPU-A"), mk("CPU", "CPU-B")
    mb1, mb2 = mk("Motherboard", "MB-A"), mk("Motherboard", "MB-B")
    psu1, psu2 = mk("PSU", "PSU-ATX"), mk("PSU", "PSU-SFX")
    case1, case2 = mk("Case", "CASE-ATX"), mk("Case", "CASE-SFX")
    s1, s2, s3 = mk("Storage", "SSD-1"), mk("Storage", "SSD-2"), mk("Storage", "SSD-3")
    for c, v in [(cpu1, "AM5"), (mb1, "AM5")]:
        svc.set_technical_profile(TechnicalProfile(component_id=c.id, attributes=[va("socket_designation", v)]))
    svc.set_technical_profile(TechnicalProfile(component_id=mb1.id, attributes=[
        va("socket_designation", "AM5"), va("form_factor", "ATX")]))
    svc.set_technical_profile(TechnicalProfile(component_id=mb2.id, attributes=[va("form_factor", "ATX")]))
    svc.set_technical_profile(TechnicalProfile(component_id=psu1.id, attributes=[va("psu_form_factor", "ATX")]))
    svc.set_technical_profile(TechnicalProfile(component_id=psu2.id, attributes=[va("psu_form_factor", "SFX")]))
    svc.set_technical_profile(TechnicalProfile(component_id=case1.id, attributes=[va("supported_psu_form_factors", ["ATX"])]))
    svc.set_technical_profile(TechnicalProfile(component_id=case2.id, attributes=[va("supported_psu_form_factors", ["SFX"])]))
    svc.set_technical_profile(TechnicalProfile(component_id=g1.id, attributes=[va("card_length_mm", 300)]))
    svc.set_technical_profile(TechnicalProfile(component_id=g2.id, attributes=[va("card_length_mm", 250)]))
    svc.set_technical_profile(TechnicalProfile(component_id=s1.id, attributes=[
        va("storage_form_factor", "m2"), va("storage_interface", "pcie"),
        va("storage_command_set", "nvme"), va("m2_keying", "M"), va("m2_length_code", "2280")]))

    builds["fullA"] = new_build("T17.14 - fullA", [cpu1.id, mb1.id, g1.id, psu1.id, case1.id, s1.id])
    builds["fullB"] = new_build("T17.14 - fullB", [cpu2.id, mb2.id, g2.id, psu2.id, case2.id, s2.id, s3.id])
    builds["empty"] = new_build("T17.14 - empty", [])
    big_ids = [mk("Storage", f"BIG-{i:02d}").id for i in range(12)]
    builds["big"] = new_build("T17.14 - big", big_ids)

    state = load_project_state()
    comps = {c.id: c for c in state.components}
    profs = {p.component_id: p for p in state.technical_profiles}
    cats = {c.id: c.category for c in state.components}
    by_name = {b.name: b for b in state.builds}
    checks = {}
    checks["builds_present"] = all(any(b.id == bid for b in state.builds) for bid in builds.values())

    def pair(an, bn):
        a, b = by_name[an], by_name[bn]
        hw = compare_hardware(a, b, comps, profs)
        ra = svc.analyze_build_compatibility(a.id)
        rb = svc.analyze_build_compatibility(b.id)
        cd = compare_reports(ra, rb, correspondence_from_hardware(hw))
        return {"hw": {"counts": [hw.common_count, hw.added_count, hw.removed_count,
                                  hw.replaced_count, hw.unknown_count],
                       "tech": hw.tech_changes},
                "overall": [ra.overall_result, rb.overall_result],
                "pairs": len(cd.pairs), "new": cd.new_count,
                "resolved": cd.resolved_count, "changed": cd.changed_count}

    reports = {
        "self": pair("T17.14 - fullA", "T17.14 - fullA"),
        "fullAB": pair("T17.14 - fullA", "T17.14 - fullB"),
        "empty": pair("T17.14 - fullA", "T17.14 - empty"),
        "big": pair("T17.14 - big", "T17.14 - empty"),
    }
    # self-compare: everything unchanged (shared ids)
    checks["self_all_unchanged"] = reports["self"]["hw"]["counts"] == [6, 0, 0, 0, 0]
    checks["fullAB_has_replacements"] = reports["fullAB"]["hw"]["counts"][3] >= 3
    checks["fullAB_has_unknown"] = reports["fullAB"]["hw"]["counts"][4] >= 2  # 1 vs 2 storage
    checks["fullAB_pairs"] = reports["fullAB"]["pairs"] > 0
    checks["empty_all_removed"] = reports["empty"]["hw"]["counts"] == [0, 0, 6, 0, 0]
    checks["big_removed"] = reports["big"]["hw"]["counts"] == [0, 0, 12, 0, 0]

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
            mw_ok = len([n for n in names if n.startswith("T17.14 - ")]) >= 4
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
        "task": "T17.14 comparator validation prep",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "target_localappdata_root": str(target), "pcpo_data_dir": str(pcpo_sub),
        "real_pcpo_dir_captured": str(real_pcpo) if real_pcpo else None, "temp_root": str(temp_root),
        "builds": {k: {"build_id": v, "name": next(b.name for b in state.builds if b.id == v)} for k, v in builds.items()},
        "reports": reports,
        "checks": checks,
        "all_checks_ok": all(v is True for k, v in checks.items() if k != "mainwindow_error"),
        "visual_manual_completed": False,
    }
    out = pcpo_sub / "t1714_visual_report.json"
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2, default=str) + "\n", encoding="utf-8")
    print(json.dumps({"ok": report["all_checks_ok"], "report": str(out), "target": str(target),
                      "checks": {k: v for k, v in checks.items() if k != "mainwindow_error"}, "mw_err": mw_err},
                     ensure_ascii=False, indent=2))
    return 0 if report["all_checks_ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
