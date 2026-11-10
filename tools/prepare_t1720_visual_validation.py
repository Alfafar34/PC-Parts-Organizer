r"""Prepare isolated synthetic TEMP data for T17.20 visual validation.

Batch add from catalog (50 entries, 20-selection, dups, invalid abort),
bulk delete (10 free + 2 assigned), build sheets (md/txt) in ES/EN.
Real APIs only; never real data. Manual Tk review still required.
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
    if pcpo_sub.exists() and any(pcpo_sub.iterdir()):
        print(f"REFUSED: target already contains data: {pcpo_sub}", file=sys.stderr)
        return 2
    pcpo_sub.mkdir(parents=True, exist_ok=True)

    os.environ["LOCALAPPDATA"] = str(target)
    os.environ["PYTHONDONTWRITEBYTECODE"] = "1"
    repo = Path(__file__).resolve().parents[1]
    if str(repo) not in sys.path:
        sys.path.insert(0, str(repo))

    from unittest.mock import patch

    from pc_parts_organizer.build_audit import build_audit
    from pc_parts_organizer.build_sheet import export_build_sheet
    from pc_parts_organizer.catalog_models import CatalogEntry
    from pc_parts_organizer.catalog_service import CatalogService
    from pc_parts_organizer.catalog_storage import CatalogStorage
    from pc_parts_organizer.localization import Translator
    from pc_parts_organizer.models import Build
    from pc_parts_organizer.service import BatchValidationError, InventoryService
    from pc_parts_organizer.technical_profiles import TechnicalAttribute, TechnicalProfile

    checks: dict = {}
    perf: dict = {}

    catalog = CatalogService(CatalogStorage())
    catalog.initialize()
    cats = ["CPU", "GPU", "Motherboard", "RAM", "Storage", "PSU", "Case", "Cooling", "Monitor", "Peripheral"]
    t0 = time.perf_counter()
    for i in range(50):
        catalog.add_entry(CatalogEntry(
            category=cats[i % len(cats)], manufacturer=f"T17.20-Maker {i % 7}",
            model=f"REF-{i:02d} ☃", specifications=f"spec {i}",
            notes=f"shop note {i}" if i % 2 == 0 else "",
            source="Synthetic", source_url="https://example.com/x",
            verified_at="2026-01-01"))
    perf["catalog_50_s"] = round(time.perf_counter() - t0, 3)
    checks["catalog_50"] = catalog.count_entries() >= 50

    svc = InventoryService()
    # pre-existing duplicates for the "existing dup" scenario
    first_entries = catalog.search_entries(limit=50, offset=0)
    svc.add_components([{"category": e.category, "manufacturer": e.manufacturer, "model": e.model}
                        for e in first_entries[:3]])

    commits = {"n": 0}
    import pc_parts_organizer.service as svcmod

    real_save = svcmod.save_project_state

    def counting(*a, **k):
        commits["n"] += 1
        return real_save(*a, **k)

    # 20-selection with 3 existing dups + 1 internal dup
    batch20 = [{"category": e.category, "manufacturer": e.manufacturer, "model": e.model,
                "specifications": e.specifications, "notes": e.notes} for e in first_entries[:20]]
    batch20.append(dict(batch20[5]))
    t0 = time.perf_counter()
    with patch.object(svcmod, "save_project_state", side_effect=counting):
        result20 = svc.add_components(batch20)
    perf["batch_20_s"] = round(time.perf_counter() - t0, 3)
    perf["batch_20_commits"] = commits["n"]
    checks["batch_20_single_commit"] = commits["n"] == 1
    checks["batch_20_created"] = len(result20.created) == 17
    checks["batch_20_duplicates"] = len(result20.duplicates) == 4  # 3 existing + 1 internal
    checks["no_provenance_profile"] = len(svc.get_technical_profiles()) == 0

    # invalid entry aborts the whole batch with zero writes
    bad = [{"category": "CPU", "manufacturer": "A", "model": "Ok-1"},
           {"category": "Nope", "manufacturer": "", "model": ""}]
    commits["n"] = 0
    before = len(svc.get_components())
    try:
        with patch.object(svcmod, "save_project_state", side_effect=counting):
            svc.add_components(bad)
        checks["invalid_aborts"] = False
    except BatchValidationError as exc:
        checks["invalid_aborts"] = len(exc.rejected) == 1 and len(svc.get_components()) == before and commits["n"] == 0

    # perf: 100 unit adds vs 1 batch of 100 (synthetic, timed)
    from pc_parts_organizer.storage import save_project_state as real_save_ps

    with tempfile.TemporaryDirectory() as td2:
        with patch.dict(os.environ, {"LOCALAPPDATA": td2}):
            real_save_ps([], [], [])
            s2 = InventoryService()
            t0 = time.perf_counter()
            for i in range(100):
                s2.add_component("RAM", "Perf", f"U-{i:03d}")
            perf["unit_100_s"] = round(time.perf_counter() - t0, 3)
    with tempfile.TemporaryDirectory() as td3:
        with patch.dict(os.environ, {"LOCALAPPDATA": td3}):
            real_save_ps([], [], [])
            s3 = InventoryService()
            t0 = time.perf_counter()
            with patch.object(svcmod, "save_project_state", side_effect=counting):
                commits["n"] = 0
                s3.add_components([{"category": "RAM", "manufacturer": "Perf", "model": f"B-{i:03d}"} for i in range(100)])
            perf["batch_100_s"] = round(time.perf_counter() - t0, 3)
            perf["batch_100_commits"] = commits["n"]
    checks["batch_single_commit_100"] = perf.get("batch_100_commits") == 1

    # inventory: 10 free + 2 assigned, bulk delete all 12
    free = svc.add_components([{"category": "Storage", "manufacturer": "Del", "model": f"D-{i}"} for i in range(10)]).created
    asg = svc.add_components([{"category": "RAM", "manufacturer": "Keep", "model": f"K-{i}"} for i in range(2)]).created
    rig = svc.add_build("Visual Rig", component_ids=[c.id for c in asg])
    del_ids = [c.id for c in free] + [c.id for c in asg]
    commits["n"] = 0
    t0 = time.perf_counter()
    with patch.object(svcmod, "save_project_state", side_effect=counting):
        del_result = svc.delete_components(del_ids)
    perf["bulk_delete_12_s"] = round(time.perf_counter() - t0, 3)
    perf["bulk_delete_commits"] = commits["n"]
    checks["bulk_delete_single_commit"] = commits["n"] == 1
    checks["bulk_delete_counts"] = len(del_result.deleted) == 10 and len(del_result.skipped_in_use) == 2
    checks["bulk_delete_names_builds"] = all(s.name and s.build_name == "Visual Rig" for s in del_result.skipped_in_use)

    # build sheet: incompatible RAM vs board + GPU without profile (uncertainty/limits)
    ram = svc.add_component("RAM", "SheetRAM", "DDR4-8G")
    board = svc.add_component("Motherboard", "SheetBoard", "B-500")
    gpu = svc.add_component("GPU", "SheetGPU", "G-1")
    svc.set_technical_profile(TechnicalProfile(component_id=ram.id, attributes=[
        TechnicalAttribute(key="memory_generation", value="DDR4", source="official_vendor_doc",
                           confidence="high", verification_status="verified",
                           evidence_ref="https://vendor/doc", verified_at="2026-01-01"),
        TechnicalAttribute(key="module_form_factor", value="DIMM", source="official_vendor_doc",
                           confidence="high", verification_status="verified",
                           evidence_ref="https://vendor/doc", verified_at="2026-01-01"),
        TechnicalAttribute(key="total_capacity_gb", value=8, unit="GB", source="official_vendor_doc",
                           confidence="high", verification_status="verified",
                           evidence_ref="https://vendor/doc", verified_at="2026-01-01"),
        TechnicalAttribute(key="module_count", value=1, source="official_vendor_doc",
                           confidence="high", verification_status="verified",
                           evidence_ref="https://vendor/doc", verified_at="2026-01-01")]))
    svc.set_technical_profile(TechnicalProfile(component_id=board.id, attributes=[
        TechnicalAttribute(key="supported_memory_generations", value=["DDR5"], source="official_vendor_doc",
                           confidence="high", verification_status="verified",
                           evidence_ref="https://vendor/doc", verified_at="2026-01-01"),
        TechnicalAttribute(key="supported_memory_module_form_factors", value=["DIMM"], source="official_vendor_doc",
                           confidence="high", verification_status="verified",
                           evidence_ref="https://vendor/doc", verified_at="2026-01-01"),
        TechnicalAttribute(key="max_memory_capacity_gb", value=128, unit="GB", source="official_vendor_doc",
                           confidence="high", verification_status="verified",
                           evidence_ref="https://vendor/doc", verified_at="2026-01-01"),
        TechnicalAttribute(key="memory_slot_count", value=4, source="official_vendor_doc",
                           confidence="high", verification_status="verified",
                           evidence_ref="https://vendor/doc", verified_at="2026-01-01"),
        TechnicalAttribute(key="form_factor", value="ATX", source="official_vendor_doc",
                           confidence="high", verification_status="verified",
                           evidence_ref="https://vendor/doc", verified_at="2026-01-01")]))
    sheet_build = svc.add_build("Ficha Visual ☃ 01", notes="build de validación",
                                component_ids=[ram.id, board.id, gpu.id])
    comps_by_id = {c.id: c for c in svc.get_components()}
    report = svc.analyze_build_compatibility(sheet_build.id)
    audit = build_audit(sheet_build, comps_by_id,
                        {p.component_id: p for p in svc.get_technical_profiles()}, report)
    sheets_dir = target / "sheets"
    sheets_dir.mkdir(exist_ok=True)
    exported = {}
    for lang in ("es", "en"):
        tr = Translator()
        tr.set_language(lang)
        for flavor, ext in (("markdown", "md"), ("text", "txt")):
            dest = sheets_dir / f"ficha-visual-01.{lang}.{ext}"
            t0 = time.perf_counter()
            export_build_sheet(sheet_build, comps_by_id, report, audit, tr, dest, flavor=flavor)
            perf[f"export_{lang}_{ext}_s"] = round(time.perf_counter() - t0, 3)
            text = dest.read_text(encoding="utf-8")
            exported[str(dest.name)] = len(text)
    md_text = (sheets_dir / "ficha-visual-01.es.md").read_text(encoding="utf-8")
    checks["sheet_has_build_and_components"] = all(s in md_text for s in ("Ficha Visual", "SheetRAM", "SheetBoard"))
    checks["sheet_no_uuid_primary"] = sheet_build.id not in md_text.split("\n")[0]
    checks["sheet_no_repr"] = "object at 0x" not in md_text and "CatalogEntry(" not in md_text

    # UI smoke: windows construct on synthetic state (manual look still required)
    mw_ok, mw_err = False, None
    try:
        import tkinter as tk

        from pc_parts_organizer.ui.catalog_selector import CatalogSelectorWindow
        from pc_parts_organizer.ui.main_window import MainWindow
        from pc_parts_organizer.ui.theme import configure_theme

        root = tk.Tk()
        root.withdraw()
        try:
            configure_theme(root)
            MainWindow(root, InventoryService(), CatalogService(CatalogStorage()), Translator())
            inv = svc.get_components()
            mw_ok = len(inv) > 0
            sel = CatalogSelectorWindow(root, catalog, Translator(), multi=True)
            mw_ok = mw_ok and str(sel.tree.cget("selectmode")) == "extended"
            try:
                sel.window.destroy()
            except Exception:
                pass
        finally:
            try:
                root.destroy()
            except Exception:
                pass
    except Exception as e:  # noqa: BLE001
        mw_err = str(e)
    checks["mainwindow_synthetic_load"] = mw_ok if mw_err is None else False
    checks["mainwindow_error"] = mw_err

    report_doc = {
        "task": "T17.20 bulk + build sheet validation prep",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "target_localappdata_root": str(target),
        "pcpo_data_dir": str(pcpo_sub),
        "real_pcpo_dir_captured": str(real_pcpo) if real_pcpo else None,
        "temp_root": str(temp_root),
        "perf": perf,
        "exported_sheets": exported,
        "checks": checks,
        "all_checks_ok": all(v is True for k, v in checks.items() if k != "mainwindow_error"),
        "visual_manual_completed": False,
    }
    out = pcpo_sub / "t1720_visual_report.json"
    out.write_text(json.dumps(report_doc, ensure_ascii=False, indent=2, default=str) + "\n", encoding="utf-8")
    print(json.dumps({"ok": report_doc["all_checks_ok"], "report": str(out),
                      "checks": {k: v for k, v in checks.items() if k != "mainwindow_error"},
                      "mw_err": mw_err, "perf": perf}, ensure_ascii=False, indent=2))
    return 0 if report_doc["all_checks_ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
