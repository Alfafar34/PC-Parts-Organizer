r"""Prepare isolated synthetic LOCALAPPDATA for T17.13 integral validation.

Rich state: 9 categories, verified profiles, complete + incomplete builds,
multi-finding analysis, catalog entries, v1 + v2 profiles. Real APIs only.
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
    from pc_parts_organizer.catalog_models import CatalogEntry
    from pc_parts_organizer.catalog_service import CatalogService
    from pc_parts_organizer.catalog_storage import CatalogStorage
    from pc_parts_organizer.technical_profiles import TechnicalAttribute, TechnicalProfile

    def va(key, value, **kw):
        base = dict(source="official_vendor_doc", confidence="high",
                    verification_status="verified", evidence_ref="https://vendor.example/doc",
                    verified_at="2026-01-01")
        base.update(kw)
        return TechnicalAttribute(key=key, value=value, **base)

    svc = InventoryService()
    ids = {}
    for cat in ["CPU", "GPU", "Motherboard", "RAM", "Storage", "PSU", "Case", "Cooling", "Monitor"]:
        ids[cat] = svc.add_component(cat, "Brand", f"{cat}-1", "spec", "").id
    svc.set_technical_profile(TechnicalProfile(component_id=ids["CPU"], attributes=[va("socket_designation", "AM5")]))
    svc.set_technical_profile(TechnicalProfile(component_id=ids["Motherboard"], attributes=[
        va("socket_designation", "AM5"), va("form_factor", "ATX"),
        va("supported_memory_generations", ["DDR5"])]))
    svc.set_technical_profile(TechnicalProfile(component_id=ids["RAM"], attributes=[
        va("memory_generation", "DDR5"), va("module_form_factor", "DIMM"),
        va("total_capacity_gb", 32, unit="GB"), va("module_count", 2)]))
    svc.set_technical_profile(TechnicalProfile(component_id=ids["GPU"], attributes=[va("card_length_mm", 300)]))
    svc.set_technical_profile(TechnicalProfile(component_id=ids["PSU"], attributes=[va("psu_form_factor", "SFX")]))
    svc.set_technical_profile(TechnicalProfile(component_id=ids["Case"], attributes=[
        va("supported_motherboard_form_factors", ["ATX"]), va("max_gpu_length_mm", 350),
        va("supported_psu_form_factors", ["SFX-L"])]))
    svc.set_technical_profile(TechnicalProfile(component_id=ids["Cooling"], attributes=[
        va("cooler_type", "air_cpu_cooler"), va("supported_cpu_sockets", ["AM5"]),
        va("cooler_height_mm", 150)]))
    # v1 profile shape on Storage (structural version 1 must stay readable)
    from pc_parts_organizer.technical_profiles import SUPPORTED_PROFILE_STRUCTURAL_VERSIONS
    assert set(SUPPORTED_PROFILE_STRUCTURAL_VERSIONS) >= {1, 2}
    svc.set_technical_profile(TechnicalProfile(component_id=ids["Storage"], profile_version=1, attributes=[
        va("storage_form_factor", "m2"), va("storage_interface", "pcie"),
        va("storage_command_set", "nvme"), va("m2_keying", "M"), va("m2_length_code", "2280")]))

    full = svc.add_build("T17.13 full build")
    for cat in ["CPU", "GPU", "Motherboard", "RAM", "PSU", "Case", "Cooling"]:
        svc.add_component_to_build(full.id, ids[cat])
    partial = svc.add_build("T17.13 partial build")
    svc.add_component_to_build(partial.id, ids["Storage"])
    rep = svc.analyze_build_compatibility(full.id)

    st = CatalogStorage()
    st.initialize()
    cs = CatalogService(st)
    cs.add_entry(CatalogEntry(category="GPU", manufacturer="Brand", model="Cat-GPU-9", specifications="8GB", notes=""))
    cs.add_entry(CatalogEntry(category="RAM", manufacturer="Brand", model="Cat-RAM-9", specifications="DDR5", notes=""))

    state = load_project_state()
    checks = {}
    checks["components"] = len(state.components) >= 9
    checks["profiles"] = len(state.technical_profiles) >= 8
    checks["builds"] = len(state.builds) >= 2
    checks["full_findings"] = len(rep.findings) >= 5
    checks["full_global_rv"] = rep.overall_result == "requires_verification"
    checks["catalog"] = cs.count_entries() >= 2
    checks["v1_profile_readable"] = any(
        p.profile_version == 1 for p in state.technical_profiles)

    mw_ok = False
    mw_err = None
    try:
        import tkinter as tk
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
            mw_ok = any(n.startswith("T17.13") for n in names)
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
        "task": "T17.13 integral validation prep",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "target_localappdata_root": str(target), "pcpo_data_dir": str(pcpo_sub),
        "real_pcpo_dir_captured": str(real_pcpo) if real_pcpo else None, "temp_root": str(temp_root),
        "full_build_id": full.id, "partial_build_id": partial.id,
        "monitor_id": ids["Monitor"], "ram_id": ids["RAM"],
        "full_report": {"overall": rep.overall_result, "rules": rep.rules_evaluated,
                        "findings": [{"rule_id": f.rule_id, "result": f.result} for f in rep.findings]},
        "checks": checks,
        "all_checks_ok": all(v is True for k, v in checks.items() if k != "mainwindow_error"),
        "visual_manual_completed": False,
    }
    out = pcpo_sub / "t1713_visual_report.json"
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2, default=str) + "\n", encoding="utf-8")
    print(json.dumps({"ok": report["all_checks_ok"], "report": str(out), "target": str(target),
                      "checks": {k: v for k, v in checks.items() if k != "mainwindow_error"}, "mw_err": mw_err},
                     ensure_ascii=False, indent=2))
    return 0 if report["all_checks_ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
