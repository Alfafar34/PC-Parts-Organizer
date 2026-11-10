r"""Prepare isolated synthetic LOCALAPPDATA for T17.17 governance validation.

Revalidation flow + paginated quality center over a 200-component inventory.
Real APIs only; never real data.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile
import time
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

    svc = InventoryService()
    t0 = time.perf_counter()
    # revalidation scenario: verified then changed value via service (simulates
    # what the editor downgrade produces: needs_review + old evidence kept)
    rv = svc.add_component("RAM", "T17.17", "RV-RAM", "", "")
    svc.set_technical_profile(TechnicalProfile(component_id=rv.id, attributes=[va("memory_generation", "DDR4")]))
    svc.set_technical_profile(TechnicalProfile(component_id=rv.id, attributes=[
        TechnicalAttribute(key="memory_generation", value="DDR5", source="official_vendor_doc",
                           confidence="high", verification_status="needs_review",
                           evidence_ref="https://vendor/doc", verified_at="2026-01-01")]))
    # bulk for pagination: 200 components, alternating verified/unverified
    for i in range(200):
        c = svc.add_component("RAM", "T17.17", f"BULK-{i:03d}", "", "")
        if i % 2 == 0:
            svc.set_technical_profile(TechnicalProfile(component_id=c.id, attributes=[va("memory_generation", "DDR5")]))
        else:
            svc.set_technical_profile(TechnicalProfile(component_id=c.id, attributes=[
                TechnicalAttribute(key="memory_generation", value="DDR5")]))
    t_setup = time.perf_counter() - t0

    state = load_project_state()
    comps = state.components
    profs = {p.component_id: p for p in state.technical_profiles}
    t0 = time.perf_counter()
    rep = audit_inventory(comps, profs)
    t_audit = time.perf_counter() - t0
    t0 = time.perf_counter()
    q = review_queue(rep)
    t_queue = time.perf_counter() - t0

    checks = {}
    checks["components"] = len(comps) >= 200
    checks["audit_ms_per_100"] = (t_audit / max(len(comps), 1) * 100 * 1000) < 500
    checks["queue_derived"] = len(q) <= len(rep.entries)
    checks["needs_review_present"] = any(
        a.verification_status == "needs_review"
        for p in state.technical_profiles for a in p.attributes)
    checks["setup_seconds"] = t_setup
    checks["audit_seconds"] = round(t_audit, 3)
    checks["queue_seconds"] = round(t_queue, 3)

    mw_ok = False
    mw_err = None
    try:
        import tkinter as tk
        from pc_parts_organizer.catalog_service import CatalogService
        from pc_parts_organizer.catalog_storage import CatalogStorage
        from pc_parts_organizer.localization import Translator
        from pc_parts_organizer.ui.main_window import MainWindow
        from pc_parts_organizer.ui.theme import configure_theme
        from pc_parts_organizer.ui.quality_center_view import QualityCenterView
        svc2 = InventoryService()
        root = tk.Tk()
        root.withdraw()
        try:
            configure_theme(root)
            MainWindow(root, svc2, CatalogService(CatalogStorage()), Translator())
            mw_ok = len([c for c in svc2.get_components() if c.model.startswith("BULK-")]) >= 200
            win = tk.Toplevel(root)
            qc = QualityCenterView(win, Translator())
            qc.pack(fill="both", expand=True)
            t1 = time.perf_counter()
            qc.set_data(audit_inventory(svc2.get_components(),
                                        {p.component_id: p for p in svc2.get_technical_profiles()}),
                        {c.id: c for c in svc2.get_components()})
            root.update()
            checks["view_render_seconds"] = round(time.perf_counter() - t1, 3)
            checks["view_rows_first_page"] = len(qc.tree.get_children()) == 50
            mw_ok = True
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
        "task": "T17.17 governance validation prep",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "target_localappdata_root": str(target), "pcpo_data_dir": str(pcpo_sub),
        "real_pcpo_dir_captured": str(real_pcpo) if real_pcpo else None, "temp_root": str(temp_root),
        "perf": {"setup_s": round(t_setup, 1), "audit_s": round(t_audit, 3), "queue_s": round(t_queue, 3)},
        "rv_component_id": rv,
        "checks": checks,
        "all_checks_ok": all(v is True for k, v in checks.items()
                             if k not in ("mainwindow_error", "setup_seconds", "audit_seconds",
                                          "queue_seconds", "view_render_seconds")),
        "visual_manual_completed": False,
    }
    out = pcpo_sub / "t1717_visual_report.json"
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2, default=str) + "\n", encoding="utf-8")
    print(json.dumps({"ok": report["all_checks_ok"], "report": str(out), "target": str(target),
                      "checks": {k: v for k, v in checks.items() if k != "mainwindow_error"}, "mw_err": mw_err},
                     ensure_ascii=False, indent=2))
    return 0 if report["all_checks_ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
