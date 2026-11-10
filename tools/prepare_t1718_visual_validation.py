r"""Prepare isolated synthetic LOCALAPPDATA for T17.18 build-audit validation.

Covers: verified build, demonstrated incompatibility, pending verifications,
insufficient data, multi-unit/multi-finding builds, needs_review revalidation.
Real APIs only; never real data.
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
    from pc_parts_organizer.build_audit import build_audit
    from pc_parts_organizer.technical_profiles import TechnicalAttribute, TechnicalProfile

    def va(key, value, **kw):
        base = dict(source="official_vendor_doc", confidence="high",
                    verification_status="verified", evidence_ref="https://vendor.example/doc",
                    verified_at="2026-01-01")
        base.update(kw)
        return TechnicalAttribute(key=key, value=value, **base)

    def ua(key, value, **kw):
        base = dict(source="unknown", confidence="low", verification_status="unverified")
        base.update(kw)
        return TechnicalAttribute(key=key, value=value, **base)

    svc = InventoryService()
    builds = {}

    def mk(cat, model):
        return svc.add_component(cat, "T17.18", model, "", "T17.18").id

    def new_build(name, comp_ids):
        b = svc.add_build(name)
        for cid in comp_ids:
            svc.add_component_to_build(b.id, cid)
        return b.id

    def prof(cid, attrs):
        svc.set_technical_profile(TechnicalProfile(component_id=cid, attributes=attrs))

    # 1. verified build
    v_psu, v_case = mk("PSU", "V-PSU"), mk("Case", "V-CASE")
    prof(v_psu, [va("psu_form_factor", "ATX")])
    prof(v_case, [va("supported_psu_form_factors", ["ATX"])])
    builds["verified"] = new_build("T17.18 - verified", [v_psu, v_case])
    # 2. demonstrated incompatibility
    m_psu, m_case = mk("PSU", "M-PSU"), mk("Case", "M-CASE")
    prof(m_psu, [va("psu_form_factor", "ATX")])
    prof(m_case, [va("supported_psu_form_factors", ["SFX"])])
    builds["mismatch"] = new_build("T17.18 - mismatch", [m_psu, m_case])
    # 3. pending verification (unverified)
    u_psu, u_case = mk("PSU", "U-PSU"), mk("Case", "U-CASE")
    prof(u_psu, [ua("psu_form_factor", "ATX")])
    prof(u_case, [va("supported_psu_form_factors", ["SFX"])])
    builds["pending"] = new_build("T17.18 - pending", [u_psu, u_case])
    # 4. insufficient data (missing psu attr)
    i_psu, i_case = mk("PSU", "I-PSU"), mk("Case", "I-CASE")
    prof(i_case, [va("supported_psu_form_factors", ["ATX"])])
    builds["incomplete"] = new_build("T17.18 - incomplete", [i_psu, i_case])
    # 5. multi-unit multi-finding: GPU+cooler+MB (mixed states)
    g_gpu, g_cool, g_mb, g_case = mk("GPU", "G-GPU"), mk("Cooling", "G-COOL"), mk("Motherboard", "G-MB"), mk("Case", "G-CASE2")
    prof(g_gpu, [va("card_length_mm", 500)])
    prof(g_cool, [va("cooler_type", "air_cpu_cooler"), ua("cooler_height_mm", 150)])
    prof(g_mb, [va("form_factor", "E-ATX")])
    prof(g_case, [va("supported_motherboard_form_factors", ["ATX"]),
                  va("max_gpu_length_mm", 300), va("max_cpu_cooler_height_mm", 200)])
    builds["multi"] = new_build("T17.18 - multi", [g_gpu, g_cool, g_mb, g_case])
    # 6. needs_review for revalidation dialog
    r_ram = mk("RAM", "RV-RAM")
    prof(r_ram, [TechnicalAttribute(key="memory_generation", value="DDR5", source="official_vendor_doc",
                                   confidence="high", verification_status="needs_review",
                                   evidence_ref="https://vendor/doc", verified_at="2026-01-01")])
    solo = svc.add_build("T17.18 - revalidate")
    svc.add_component_to_build(solo.id, r_ram)
    builds["revalidate"] = solo.id

    state = load_project_state()
    comps = {c.id: c for c in state.components}
    profs = {p.component_id: p for p in state.technical_profiles}
    checks = {"builds_present": all(any(b.id == bid for b in state.builds) for bid in builds.values())}

    def audit_of(key):
        bid = builds[key]
        b = next(x for x in state.builds if x.id == bid)
        rep = svc.analyze_build_compatibility(bid)
        return build_audit(b, comps, profs, rep)

    a_mis = audit_of("mismatch")
    a_ver = audit_of("verified")
    checks["mismatch_demonstrated"] = len(a_mis.demonstrated) == 1
    checks["verified_no_demonstrated"] = len(a_ver.demonstrated) == 0
    checks["pending_has_relevant"] = len(audit_of("pending").relevant_pending) > 0
    checks["incomplete_insufficient"] = len(audit_of("incomplete").insufficient) >= 1
    checks["multi_has_findings"] = (len(audit_of("multi").demonstrated) + len(audit_of("multi").pending_verification)) >= 2
    checks["revalidate_present"] = any(
        a.verification_status == "needs_review"
        for p in state.technical_profiles for a in p.attributes)

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
            mw_ok = len([n for n in names if n.startswith("T17.18 - ")]) >= 6
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
        "task": "T17.18 build-audit validation prep",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "target_localappdata_root": str(target), "pcpo_data_dir": str(pcpo_sub),
        "real_pcpo_dir_captured": str(real_pcpo) if real_pcpo else None, "temp_root": str(temp_root),
        "builds": {k: {"build_id": v, "name": next(b.name for b in state.builds if b.id == v)} for k, v in builds.items()},
        "checks": checks,
        "all_checks_ok": all(v is True for k, v in checks.items() if k != "mainwindow_error"),
        "visual_manual_completed": False,
    }
    out = pcpo_sub / "t1718_visual_report.json"
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2, default=str) + "\n", encoding="utf-8")
    print(json.dumps({"ok": report["all_checks_ok"], "report": str(out), "target": str(target),
                      "checks": {k: v for k, v in checks.items() if k != "mainwindow_error"}, "mw_err": mw_err},
                     ensure_ascii=False, indent=2))
    return 0 if report["all_checks_ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
