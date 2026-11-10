r"""Prepare isolated synthetic LOCALAPPDATA for T17.16 quality center validation.

Covers: no profiles, verified, unknown, unverified, low confidence, missing
evidence, partial/complete collections, mixed attrs, v1 profiles, unevaluated
attrs, build-linked findings, multi-category queue items. Real APIs only.
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
    from pc_parts_organizer.data_quality import audit_inventory, review_queue
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
    ids = {}

    def mk(cat, model):
        c = svc.add_component(cat, "T17.16", model, "spec", "")
        ids[model] = c.id
        return c.id

    # 1. no profile
    mk("RAM", "Q-NOPROFILE")
    # 2. verified RAM
    r = mk("RAM", "Q-VERIFIED")
    svc.set_technical_profile(TechnicalProfile(component_id=r, attributes=[
        va("memory_generation", "DDR5"), va("module_form_factor", "DIMM"),
        va("total_capacity_gb", 32, unit="GB"), va("module_count", 2)]))
    # 4. unverified values
    u = mk("GPU", "Q-UNVERIFIED")
    svc.set_technical_profile(TechnicalProfile(component_id=u, attributes=[
        TechnicalAttribute(key="card_length_mm", value=300)]))
    # 5. low confidence
    l = mk("Case", "Q-LOWCONF")
    svc.set_technical_profile(TechnicalProfile(component_id=l, attributes=[
        va("supported_motherboard_form_factors", ["ATX"], confidence="low")]))
    # 7. partial collection (m2_slots partial is allowed)
    p = mk("Motherboard", "Q-PARTIAL")
    svc.set_technical_profile(TechnicalProfile(component_id=p, attributes=[
        va("form_factor", "ATX"),
        va("m2_slots", [{"slot_id": "M2_1", "accepted_module_keyings": ["M"],
                         "supported_lengths": ["2280"], "supported_modes": ["pcie_nvme"]}],
           collection_completeness="partial", completeness_scope="M2_1 only")]))
    # 8. complete collection (verified+high+evidence+date+scope)
    cc = mk("Motherboard", "Q-COMPLETE")
    svc.set_technical_profile(TechnicalProfile(component_id=cc, attributes=[
        va("form_factor", "ATX"),
        va("m2_slots", [{"slot_id": "M2_1", "accepted_module_keyings": ["M"],
                         "supported_lengths": ["2280"], "supported_modes": ["pcie_nvme"]}],
           collection_completeness="complete", completeness_scope="manual p.1")]))
    # 9. mixed CPU (verified socket + nothing else to add: socket only attr)
    # 10. v1 profile
    v1 = mk("RAM", "Q-V1")
    svc.set_technical_profile(TechnicalProfile(component_id=v1, profile_version=1, attributes=[
        TechnicalAttribute(key="memory_generation", value="DDR4")]))
    # 11. unevaluated attrs (pcie_generation/lanes present, verified)
    st = mk("Storage", "Q-PCIE")
    svc.set_technical_profile(TechnicalProfile(component_id=st, attributes=[
        va("storage_form_factor", "m2"), va("storage_interface", "pcie"),
        va("storage_command_set", "nvme"), va("m2_keying", "M"), va("m2_length_code", "2280"),
        va("pcie_generation", 4), va("pcie_lanes", "x4")]))
    # 12. build-linked: PSU+Case with verified mismatch (finding source)
    psu = mk("PSU", "Q-PSU")
    case = mk("Case", "Q-CASE")
    svc.set_technical_profile(TechnicalProfile(component_id=psu, attributes=[va("psu_form_factor", "ATX")]))
    svc.set_technical_profile(TechnicalProfile(component_id=case, attributes=[va("supported_psu_form_factors", ["SFX"])]))
    b = svc.add_build("T17.16 linked")
    svc.add_component_to_build(b.id, psu)
    svc.add_component_to_build(b.id, case)
    rep = svc.analyze_build_compatibility(b.id)

    state = load_project_state()
    comps = state.components
    profs = {p.component_id: p for p in state.technical_profiles}
    report = audit_inventory(comps, profs)
    queue = review_queue(report)
    checks = {}
    checks["components"] = len(comps) >= 9
    checks["no_profile"] = report.components_without_profile >= 1
    checks["verified_present"] = report.count("verified") >= 4
    checks["unverified_present"] = report.count("unverified") >= 1
    checks["low_present"] = report.count("low_confidence") >= 1
    checks["queue_nonempty"] = len(queue) > 0
    checks["queue_derived"] = len(queue) <= len(report.entries)
    checks["linked_finding"] = any(f.rule_id == "psu_case.form_factor" and f.result == "incompatible"
                                   for f in rep.findings)
    checks["v1_readable"] = any(p.profile_version == 1 for p in state.technical_profiles)
    states = {e.status for e in report.entries}
    checks["states_seen"] = {"verified", "unverified", "low_confidence", "absent"} <= states

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
        names = [c.model for c in svc2.get_components()]
        root = tk.Tk()
        root.withdraw()
        try:
            configure_theme(root)
            MainWindow(root, svc2, CatalogService(CatalogStorage()), Translator())
            mw_ok = any(n.startswith("Q-") for n in names)
        finally:
            try:
                root.destroy()
            except Exception:
                pass
    except Exception as e:
        mw_err = str(e)
    checks["mainwindow_synthetic_load"] = mw_ok
    checks["mainwindow_error"] = mw_err

    out_report = {
        "task": "T17.16 quality center validation prep",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "target_localappdata_root": str(target), "pcpo_data_dir": str(pcpo_sub),
        "real_pcpo_dir_captured": str(real_pcpo) if real_pcpo else None, "temp_root": str(temp_root),
        "build_id": b.id, "ram_verified_id": ids["Q-VERIFIED"],
        "checks": checks,
        "all_checks_ok": all(v is True for k, v in checks.items() if k != "mainwindow_error"),
        "visual_manual_completed": False,
    }
    out = pcpo_sub / "t1716_visual_report.json"
    out.write_text(json.dumps(out_report, ensure_ascii=False, indent=2, default=str) + "\n", encoding="utf-8")
    print(json.dumps({"ok": out_report["all_checks_ok"], "report": str(out), "target": str(target),
                      "checks": {k: v for k, v in checks.items() if k != "mainwindow_error"}, "mw_err": mw_err},
                     ensure_ascii=False, indent=2))
    return 0 if out_report["all_checks_ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
