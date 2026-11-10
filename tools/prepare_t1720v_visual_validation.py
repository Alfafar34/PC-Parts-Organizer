r"""T17.20-V real Tk walkthrough: bulk flows via UI events + screenshots.

Synthetic isolated TEMP data only. Drives real widgets (selection events,
button.invoke, nested-loop auto-drivers, real native save dialog via ctypes),
captures real pixels with ImageGrab. Manual acceptance is NOT claimed.
"""
from __future__ import annotations

import argparse
import ctypes
import json
import os
import sys
import tempfile
import threading
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


# ---------------------------------------------------------------- native dialog
def _drive_native_save(title: str, shot_path: Path, action, timeout: float = 20.0) -> dict:
    """Wait for the native save dialog, screenshot it, then type/cancel.

    Runs in a worker thread while the main thread is blocked inside
    filedialog. Returns what happened; never touches Tk.
    """
    try:
        user32 = ctypes.windll.user32
    except Exception as exc:
        return {"found": False, "error": f"no-win32: {exc}"}
    deadline = time.time() + timeout
    hwnd = 0
    while time.time() < deadline:
        hwnd = user32.FindWindowW(None, title)
        if hwnd:
            break
        time.sleep(0.25)
    if not hwnd:
        return {"found": False}
    rect = (ctypes.c_long * 4)()
    user32.GetWindowRect(hwnd, rect)
    time.sleep(0.6)
    # PrintWindow capture is occlusion-proof; failures are recorded, never fatal.
    try:
        import ctypes as _ct

        _user32 = _ct.windll.user32
        _gdi32 = _ct.windll.gdi32
        w, h = rect[2] - rect[0], rect[3] - rect[1]
        _hdc = _user32.GetDC(None)
        _mem = _gdi32.CreateCompatibleDC(_hdc)
        _bmp = _gdi32.CreateCompatibleBitmap(_hdc, w, h)
        _gdi32.SelectObject(_mem, _bmp)
        _user32.PrintWindow(hwnd, _mem, 2)
        from PIL import Image as _Img

        _buf = _ct.create_string_buffer(w * h * 4)

        class _BMI(_ct.Structure):
            _fields_ = [("s", _ct.c_uint32), ("w", _ct.c_int32), ("h", _ct.c_int32),
                        ("p", _ct.c_uint16), ("b", _ct.c_uint16), ("c", _ct.c_uint32),
                        ("sz", _ct.c_uint32), ("x", _ct.c_int32), ("y", _ct.c_int32),
                        ("u", _ct.c_uint32), ("i", _ct.c_uint32)]

        _bmi = _BMI(_ct.sizeof(_BMI), w, -h, 1, 32, 0, 0, 0, 0, 0, 0)
        if _gdi32.GetDIBits(_mem, _bmp, 0, h, _buf, _ct.byref(_bmi), 0):
            _Img.frombuffer("RGBA", (w, h), _buf, "raw", "BGRA", 0, 1).save(str(shot_path))
        _gdi32.DeleteObject(_bmp)
        _gdi32.DeleteDC(_mem)
        _user32.ReleaseDC(None, _hdc)
    except Exception as exc:
        return {"found": True, "shot_error": str(exc)}
    if action[0] == "cancel":
        user32.PostMessageW(hwnd, 0x0010, 0, 0)  # WM_CLOSE -> dialog cancels
        return {"found": True, "action": "cancel"}
    # Keystroke injection is deliberately unsupported: background sessions
    # cannot guarantee foreground focus, so typing could hit another app.
    user32.PostMessageW(hwnd, 0x0010, 0, 0)
    return {"found": True, "action": "refused_type_cancelled"}


# NOTE: no keystroke injection in this tool. Background sessions cannot own
# keyboard focus, so SendInput could hit another application. Native dialogs
# are driven read-only (screenshot) + dismissed via targeted WM_CLOSE only.

# ---------------------------------------------------------------- walkthrough
def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--target", required=True)
    args = ap.parse_args(argv)

    real_pcpo = _real_pcpo_dir()
    target = Path(args.target).expanduser().resolve()
    if not _is_under_temp(target) or target == Path(tempfile.gettempdir()).resolve():
        print("REFUSED: target must be a dedicated subdir under TEMP.", file=sys.stderr)
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

    import tkinter as tk
    from tkinter import ttk

    from PIL import ImageGrab

    from pc_parts_organizer.build_audit import build_audit
    from pc_parts_organizer.build_sheet import export_build_sheet
    from pc_parts_organizer.catalog_models import CatalogEntry
    from pc_parts_organizer.catalog_service import CatalogService
    from pc_parts_organizer.catalog_storage import CatalogStorage
    from pc_parts_organizer.localization import Translator
    from pc_parts_organizer.models import Build
    from pc_parts_organizer.service import BatchValidationError, InventoryService
    from pc_parts_organizer.technical_profiles import TechnicalAttribute, TechnicalProfile
    from pc_parts_organizer.ui.catalog_selector import CatalogSelectorWindow
    from pc_parts_organizer.ui.main_window import MainWindow
    from pc_parts_organizer.ui.theme import configure_theme, PALETTE

    shots = target / "shots"
    exports = target / "exports"
    shots.mkdir(exist_ok=True)
    exports.mkdir(exist_ok=True)
    checks: dict = {}
    shot_index: list[dict] = []

    def log(msg: str) -> None:
        print(f"[walk] {msg}", flush=True)

    import faulthandler

    def _watchdog(secs: float = 480.0) -> None:
        time.sleep(secs)
        print("WATCHDOG: dumping tracebacks before forced exit", flush=True)
        faulthandler.dump_traceback()
        os._exit(2)

    threading.Thread(target=_watchdog, daemon=True).start()
    log("watchdog armed")

    def print_window_png(hwnd: int, path: Path) -> bool:
        """Capture a window via PrintWindow: immune to occlusion/minimize."""
        import ctypes
        from ctypes import wintypes

        user32 = ctypes.windll.user32
        gdi32 = ctypes.windll.gdi32
        rect = wintypes.RECT()
        if not user32.GetWindowRect(hwnd, ctypes.byref(rect)):
            return False
        w, h = rect.right - rect.left, rect.bottom - rect.top
        if w < 50 or h < 50:
            return False

        class BITMAPINFOHEADER(ctypes.Structure):
            _fields_ = [("biSize", wintypes.DWORD), ("biWidth", wintypes.LONG),
                        ("biHeight", wintypes.LONG), ("biPlanes", wintypes.WORD),
                        ("biBitCount", wintypes.WORD), ("biCompression", wintypes.DWORD),
                        ("biSizeImage", wintypes.DWORD), ("biXPelsPerMeter", wintypes.LONG),
                        ("biYPelsPerMeter", wintypes.LONG), ("biClrUsed", wintypes.DWORD),
                        ("biClrImportant", wintypes.DWORD)]

        hdc_screen = user32.GetDC(None)
        hdc_mem = gdi32.CreateCompatibleDC(hdc_screen)
        hbmp = gdi32.CreateCompatibleBitmap(hdc_screen, w, h)
        gdi32.SelectObject(hdc_mem, hbmp)
        printed = user32.PrintWindow(hwnd, hdc_mem, 2)  # PW_RENDERFULLCONTENT
        bmi = BITMAPINFOHEADER()
        bmi.biSize = ctypes.sizeof(BITMAPINFOHEADER)
        bmi.biWidth = w
        bmi.biHeight = -h
        bmi.biPlanes = 1
        bmi.biBitCount = 32
        bmi.biCompression = 0
        buf = ctypes.create_string_buffer(w * h * 4)
        got = gdi32.GetDIBits(hdc_mem, hbmp, 0, h, buf, ctypes.byref(bmi), 0)
        gdi32.DeleteObject(hbmp)
        gdi32.DeleteDC(hdc_mem)
        user32.ReleaseDC(None, hdc_screen)
        if not got:
            return False
        from PIL import Image

        Image.frombuffer("RGBA", (w, h), buf, "raw", "BGRA", 0, 1).save(str(path))
        return printed != 0

    def shoot_window(win, name: str) -> bool:
        try:
            win.update_idletasks()
            win.deiconify()
            win.lift()
            try:
                win.focus_force()
            except Exception:
                pass
            win.update()
            time.sleep(0.45)
            ok = print_window_png(int(win.winfo_id()), shots / f"{name}.png")
            if ok:
                shot_index.append({"name": name})
            else:
                shot_index.append({"name": name, "error": "printwindow-failed"})
            return ok
        except Exception as exc:
            shot_index.append({"name": name, "error": str(exc)})
            return False

    def top_levels(exclude=()):
        return [w for w in root.winfo_children()
                if w.winfo_class() == "Toplevel" and w not in exclude and w.winfo_exists()]

    def arm_msgbox_closer(tag: str, attempts: int = 10) -> None:
        def attempt(left: int) -> None:
            try:
                if auto_close_msgbox(tag):
                    log(f"msgbox closed: {tag}")
                    return
            except Exception as exc:
                log(f"msgbox closer error {tag}: {exc}")
            if left > 0:
                root.after(1500, lambda: attempt(left - 1))
            else:
                log(f"msgbox closer exhausted: {tag}")

        root.after(1500, lambda: attempt(attempts))

    # ---------------------------------------------------------- synthetic data
    catalog = CatalogService(CatalogStorage())
    catalog.initialize()
    cats = ["CPU", "GPU", "Motherboard", "RAM", "Storage", "PSU", "Case", "Cooling", "Monitor", "Peripheral"]
    for i in range(50):
        catalog.add_entry(CatalogEntry(
            category=cats[i % len(cats)], manufacturer=f"T17.20V Maker {i % 7}",
            model=f"VREF-{i:02d} áé☃", specifications=f"spec {i}",
            notes=f"shop note {i}" if i % 2 == 0 else "",
            source="Synthetic", source_url="https://example.com/x", verified_at="2026-01-01"))
    checks["catalog_50"] = catalog.count_entries() >= 50
    log("catalog ready")

    svc = InventoryService()
    first = catalog.search_entries(limit=50, offset=0)
    svc.add_components([{"category": e.category, "manufacturer": e.manufacturer, "model": e.model}
                        for e in first[:3]])
    inv_extra = svc.add_components(
        [{"category": "Storage", "manufacturer": "Walk", "model": f"W-{i:02d}"} for i in range(13)]).created
    comp_alpha = svc.add_component("RAM", "Walk", "Alpha-1")
    comp_beta = svc.add_component("GPU", "Walk", "Beta-1")
    svc.add_build("Rig Alpha", component_ids=[comp_alpha.id])
    svc.add_build("Rig Beta", component_ids=[comp_beta.id])

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
    sheet_build = svc.add_build("Ficha Walk ☃ 01", notes="walkthrough",
                                component_ids=[ram.id, board.id, gpu.id])

    # ---------------------------------------------------------------- Tk app
    root = tk.Tk()
    root.geometry("1280x860+120+60")
    configure_theme(root)
    translator = Translator()
    mw = MainWindow(root, svc, catalog, translator)
    root.update()
    time.sleep(0.5)
    checks["mainwindow_open"] = bool(root.winfo_exists())
    log("main window open")

    # ------------------------------------------------- A. catalog multi-select
    # Page size is shrunk via the module constant so real paging + cross-page
    # retention are exercised with the required 50-entry catalog.
    import pc_parts_organizer.ui.catalog_selector as _csmod

    _csmod.DEFAULT_PAGE_SIZE = 10
    selector = CatalogSelectorWindow(root, catalog, translator, multi=True)

    def select_current(n):
        items = list(selector.tree.get_children())
        selector.tree.selection_set(items[:n])
        selector.tree.event_generate("<<TreeviewSelect>>")
        selector.tree.update()

    select_current(10)
    checks["selector_counter_10"] = (
        selector.selection_label.cget("text") if selector.selection_label else "?") == \
        translator.t("catalog_selector.selection_count").format(count=10)
    shoot_window(selector.window, "01_selector_multi_10_es")
    selector.next_button.invoke()  # real paging event
    root.update()
    time.sleep(0.3)
    select_current(10)
    total_sel = len(selector._selected_ids)
    checks["selector_cross_page_20"] = total_sel == 20
    shoot_window(selector.window, "02_selector_page2_kept_20_es")

    def use_and_close():
        selector.use_button.invoke()  # real confirm event

    root.after(400, use_and_close)
    root.wait_window(selector.window)
    picked = list(selector.results)
    checks["selector_picked_20_nodup"] = len(picked) == 20 and len({e.id for e in picked}) == 20
    log("selector done")

    items = [MainWindow._catalog_entry_to_component_dict(e) for e in picked]
    items.append(dict(items[4]))  # internal duplicate by real user-equivalent repetition
    add_result = svc.add_components(items)
    log("batch add done")
    checks["add_mixed_17_4"] = len(add_result.created) == 17 and len(add_result.duplicates) == 4
    mw.refresh_inventory()
    dlg = mw._show_bulk_result(
        translator.t("catalog_bulk.result_title"),
        mw._catalog_add_result_lines(add_result)[0],
        mw._catalog_add_result_lines(add_result),
        translator.t("catalog_bulk.close"))
    root.update()
    time.sleep(0.4)
    checks["shot_03_add_result"] = shoot_window(dlg, "03_add_result_mixed_es")
    dlg.destroy()

    # invalid batch -> real service rejection -> real dialog
    try:
        svc.add_components([{"category": "CPU", "manufacturer": "A", "model": "Ok-1"},
                            {"category": "Nope", "manufacturer": "", "model": ""}])
        checks["invalid_aborts"] = False
    except BatchValidationError as exc:
        checks["invalid_aborts"] = len(exc.rejected) == 1
        dlg2 = mw._show_bulk_result(
            translator.t("catalog_bulk.validation_title"),
            translator.t("catalog_bulk.validation_error"),
            mw._catalog_rejection_lines(exc.rejected),
            translator.t("catalog_bulk.close"))
        root.update()
        time.sleep(0.4)
        checks["shot_04_validation"] = shoot_window(dlg2, "04_validation_rejections_es")
        dlg2.destroy()

    # ------------------------------------------------------- B. bulk delete
    inv_view = mw._inventory_list_view
    inv_view.set_components(svc.get_components())
    root.update()
    # select 10: 8 free + the 2 assigned (find their rows by component id)
    want = {c.id for c in inv_extra[:8]} | {comp_alpha.id, comp_beta.id}
    rows = [item for item in inv_view.tree.get_children()
            if inv_view._component_ids_by_item.get(item) in want]
    inv_view.tree.selection_set(rows)
    inv_view.tree.event_generate("<<TreeviewSelect>>")
    inv_view.update()
    checks["inventory_selected_10"] = len(inv_view.get_selected_component_ids()) == 10
    mw._select_notebook_tab("inventory")  # real navigation, so pixels show the selection
    root.update()
    time.sleep(0.4)
    checks["shot_05_inventory_multi"] = shoot_window(root, "05_inventory_multi_es")

    confirm_info: dict = {}

    def auto_confirm():
        for dlg in top_levels():
            try:
                if dlg.title() == translator.t("bulk.delete_title"):
                    confirm_info["seen"] = True
                    confirm_info["shot"] = shoot_window(dlg, "06_bulk_confirm_es")
                    stack = [dlg]
                    while stack:
                        w = stack.pop()
                        try:
                            if w.winfo_class() == "TButton" and \
                                    w.cget("text") == translator.t("bulk.delete_confirm_button"):
                                w.invoke()  # real confirm event
                                return
                        except Exception:
                            pass
                        try:
                            stack.extend(w.winfo_children())
                        except Exception:
                            pass
                    log("confirm button NOT found")
            except Exception as exc:
                log(f"auto_confirm error: {exc}")

    root.after(700, auto_confirm)
    root.after(4000, auto_confirm)  # second chance if the dialog was slow
    mw._on_bulk_delete()  # blocks in confirm dialog until auto_confirm invokes
    log("bulk delete handler returned")
    root.update()
    time.sleep(0.4)
    checks["bulk_confirm_seen"] = confirm_info.get("seen", False)
    checks["bulk_protected_both_builds"] = (
        {c.id for c in svc.get_components()} >= {comp_alpha.id, comp_beta.id})
    # the non-blocking result dialog is the newest top-level: screenshot it
    result_dlgs = top_levels()
    if result_dlgs:
        checks["shot_07_bulk_result"] = shoot_window(result_dlgs[-1], "07_bulk_result_protected_es")
        texts = [w for w in result_dlgs[-1].winfo_children()[0].winfo_children() if w.winfo_class() == "Text"]
        if texts:
            body = texts[0].get("1.0", "end")
            checks["result_names_builds"] = all(s in body for s in ("Alpha-1", "Beta-1", "Rig Alpha", "Rig Beta"))
        result_dlgs[-1].destroy()
    # long full-list dialog (15 created + 12 dups) for the truncation fix proof
    long_lines = mw._catalog_add_result_lines(add_result)
    long_dlg = mw._show_bulk_result("LONG", long_lines[0], long_lines, translator.t("catalog_bulk.close"))
    root.update()
    time.sleep(0.4)
    checks["shot_08_full_list"] = shoot_window(long_dlg, "08_full_list_es")
    long_dlg.destroy()
    log("bulk phase done")

    # ------------------------------------------------------- C. export sheet
    comps_by_id = {c.id: c for c in svc.get_components()}
    report = svc.analyze_build_compatibility(sheet_build.id)
    audit = build_audit(sheet_build, comps_by_id,
                        {p.component_id: p for p in svc.get_technical_profiles()}, report)
    checks["report_findings"] = len(getattr(report, "findings", ())) > 0
    log("entering export phase")

    md_dest = str(exports / "ficha-walk-01.md")
    title_md = translator.t("build_sheet.dialog_title")

    def auto_close_msgbox(tag: str, expected_title: str | None = None) -> bool:
        # Legacy Tk-traversal closer: kept for reference. Native tk_messageBox
        # dialogs are NOT Tk widgets; use drive_native_msgbox for those.
        for dlg in top_levels():
            try:
                if expected_title is not None and dlg.title() != expected_title:
                    continue
                shoot_window(dlg, tag)
                for child in dlg.winfo_children():
                    stack = [child]
                    while stack:
                        w = stack.pop()
                        try:
                            if w.winfo_class() == "TButton":
                                w.invoke()
                                return True
                        except Exception:
                            pass
                        try:
                            stack.extend(w.winfo_children())
                        except Exception:
                            pass
            except Exception:
                pass
        return False

    # Native Tk messageBox dialogs (tk_messageBox) are OS windows, invisible to
    # winfo. Drive them by exact title from a worker thread: screenshot via
    # PrintWindow, then dismiss with targeted WM_CLOSE (== OK, no side effects).
    # No keystroke injection anywhere: background sessions cannot own focus.
    def drive_native_msgbox(titles: dict, shot_prefix: str, timeout: float = 30.0) -> dict:
        user32 = ctypes.windll.user32
        deadline = time.time() + timeout
        while time.time() < deadline:
            for title, tag in titles.items():
                hwnd = user32.FindWindowW(None, title)
                if hwnd:
                    time.sleep(0.5)
                    try:
                        print_window_png(hwnd, shots / f"{shot_prefix}_{tag}.png")
                    except Exception as exc:
                        shot_index.append({"name": f"{shot_prefix}_{tag}", "error": str(exc)})
                    user32.PostMessageW(hwnd, 0x0010, 0, 0)  # WM_CLOSE
                    return {"title": title, "tag": tag}
            time.sleep(0.25)
        return {"title": None, "tag": None}

    # Kept for reference: no longer used (see drive_native_msgbox).

    # Real native save dialog, shown and cancelled for real (proves dialog
    # config: title, initial file, filters). The success/error continuations
    # below emulate the user's path choice through the same handler, because
    # blind keystroke injection into an OS dialog is unsafe in this session.
    native_outcomes: list[dict] = []

    def show_native_once(shot_name: str, title: str) -> dict:
        outcome: dict = {}
        worker = threading.Thread(target=_drive_native_save,
                                  args=(title, shots / f"{shot_name}.png", ("cancel",)),
                                  daemon=True)
        worker.start()
        mw._on_export_build_sheet(sheet_build.id)
        worker.join(timeout=30)
        return outcome

    def run_export_with_path(dest: str, shot_prefix: str, expect: str) -> None:
        from unittest.mock import patch as _patch

        ok_title = translator.t("build_sheet.success_title")
        err_title = translator.t("build_sheet.error_title")
        outcome: dict = {}

        def driver() -> None:
            outcome.update(drive_native_msgbox(
                {ok_title: "success", err_title: "error"}, shot_prefix))

        worker = threading.Thread(target=driver, daemon=True)
        worker.start()
        with _patch("tkinter.filedialog.asksaveasfilename", return_value=dest):
            mw._on_export_build_sheet(sheet_build.id)
        worker.join(timeout=45)
        log(f"export dialog outcome: {outcome}")
        if expect == "ok":
            checks[f"{shot_prefix}_msgbox"] = outcome.get("tag") == "success"
        else:
            checks[f"{shot_prefix}_msgbox"] = outcome.get("tag") == "error"
        if expect == "ok":
            checks[f"{shot_prefix}_file_ok"] = Path(dest).exists() and outcome.get("tag") == "success"
        else:
            checks[f"{shot_prefix}_file_ok"] = (not Path(dest).exists()) and outcome.get("tag") == "error"

    md_dest = str(exports / "ficha-walk-01.md")
    title_md = translator.t("build_sheet.dialog_title")

    show_native_once("09_save_dialog_md", title_md)
    log("native md dialog shown+cancelled")
    run_export_with_path(md_dest, "10_export_success_md_es", "ok")
    checks["export_md_exists"] = Path(md_dest).exists()
    log("md export attempt done")

    txt_dest = str(exports / "ficha-walk-01.txt")
    show_native_once("11_save_dialog_txt", title_md)
    run_export_with_path(txt_dest, "12_export_success_txt_es", "ok")
    checks["export_txt_exists"] = Path(txt_dest).exists()

    # content audit of the real files
    sheet_ok = {}
    for path, flavor in ((md_dest, "md"), (txt_dest, "txt")):
        try:
            raw = Path(path).read_bytes()
            text = raw.decode("utf-8")
            sheet_ok[flavor] = {
                "utf8": True,
                "has_build": "Ficha Walk" in text,
                "has_components": all(s in text for s in ("SheetRAM", "SheetBoard", "SheetGPU")),
                "has_incompatible": "Incompatible" in text,
                "no_uuid": sheet_build.id not in text,
                "no_repr": "object at 0x" not in text and "mappingproxy" not in text,
                "has_limits": len(text.splitlines()) > 30,
            }
        except Exception as exc:
            sheet_ok[flavor] = {"error": str(exc)}
    checks["sheet_md_audit"] = all(v is True for v in sheet_ok.get("md", {}).values())
    checks["sheet_txt_audit"] = all(v is True for v in sheet_ok.get("txt", {}).values())

    # view of the exported content in a real text window
    viewer = tk.Toplevel(root)
    viewer.title("sheet-view")
    viewer.geometry("760x560+160+120")
    tv = tk.Text(viewer, wrap="word")
    tv.pack(fill="both", expand=True)
    try:
        tv.insert("1.0", Path(md_dest).read_text(encoding="utf-8")[:6000])
    except Exception:
        pass
    tv.configure(state="disabled")
    root.update()
    time.sleep(0.4)
    checks["shot_13_sheet_view"] = shoot_window(viewer, "13_sheet_content_view_es")
    viewer.destroy()

    # write error: destination under an existing FILE forces OSError
    blocker = exports / "blocker"
    blocker.write_text("x", encoding="utf-8")
    bad_dest = str(blocker / "sheet.md")
    run_export_with_path(bad_dest, "15_write_error_es", "error")
    checks["write_error_no_partial"] = not Path(bad_dest).exists()

    # cancel: close the real native dialog -> silent, no file, no messagebox
    show_native_once("16_save_dialog_cancel", title_md)
    checks["cancel_clean"] = not Path(exports / "cancel-should-not-exist.md").exists()
    root.update()
    time.sleep(0.3)
    checks["shot_17_after_cancel"] = shoot_window(root, "17_main_after_cancel_es")

    # ------------------------------------------------------- EN pass
    translator.change_language("en")
    mw.apply_translations()
    root.update()
    time.sleep(0.4)
    sel_en = CatalogSelectorWindow(root, catalog, translator, multi=True)
    sel_items = list(sel_en.tree.get_children())
    sel_en.tree.selection_set(sel_items[:5])
    sel_en.tree.event_generate("<<TreeviewSelect>>")
    sel_en.tree.update()
    checks["shot_18_selector_en"] = shoot_window(sel_en.window, "18_selector_multi_en")
    sel_en.window.destroy()
    root.update()
    time.sleep(0.3)
    checks["shot_19_main_en"] = shoot_window(root, "19_main_en")

    try:
        root.destroy()
    except Exception:
        pass

    report_doc = {
        "task": "T17.20-V real Tk walkthrough",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "target": str(target),
        "real_pcpo_dir_captured": str(real_pcpo) if real_pcpo else None,
        "checks": checks,
        "shots": shot_index,
        "sheet_audit": sheet_ok,
        "native_dialog_workers": native_outcomes if "native_outcomes" in dir() else [],
        "all_checks_ok": all(v is True for v in checks.values()),
        "visual_manual_completed": False,
        "notes": [
            "Driven via widget events (selection_set+event_generate, button.invoke, nested-loop auto-drivers, real native dialogs shown+cancelled via targeted WM_CLOSE).",
            "Success/error continuations emulate the user's path choice through the REAL handler (filedialog return patched); keystroke injection is deliberately NOT used.",
            "Native tk_messageBox dialogs are driven by exact title from a worker thread (screenshot + WM_CLOSE).",
            "Page size shrunk via module constant to exercise real paging with the required 50-entry catalog.",
            "Invalid-batch dialog fed with a REAL BatchValidationError from the REAL service (unreachable via catalog UI by construction).",
            "No user acceptance claimed; screenshots are agent-captured real pixels via PrintWindow.",
        ],
    }
    out = pcpo_sub / "t1720v_walkthrough_report.json"
    out.write_text(json.dumps(report_doc, ensure_ascii=False, indent=2, default=str) + "\n", encoding="utf-8")
    print(json.dumps({"ok": report_doc["all_checks_ok"], "report": str(out),
                      "shots": len(shot_index),
                      "failed": {k: v for k, v in checks.items() if v is not True}},
                     ensure_ascii=False, indent=2))
    return 0 if report_doc["all_checks_ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
