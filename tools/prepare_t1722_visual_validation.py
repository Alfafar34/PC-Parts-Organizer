r"""T17.22 visual validation: CSV import flows via real Tk windows.

Synthetic isolated TEMP data only. Drives the real MainWindow handlers with
filedialog returns patched (documented path handoff; no keystroke injection).
Native messageBox dialogs are driven by exact title from a worker thread
(screenshot + targeted WM_CLOSE). Manual acceptance is NOT claimed.
"""
from __future__ import annotations

import argparse
import ctypes
import io
import os
import sys
import tempfile
import threading
import time
from datetime import datetime, timezone
from pathlib import Path


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

    target = Path(args.target).expanduser().resolve()
    if not _is_under_temp(target) or target == Path(tempfile.gettempdir()).resolve():
        print("REFUSED: target must be a dedicated subdir under TEMP.", file=sys.stderr)
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
    from unittest.mock import patch

    from pc_parts_organizer.catalog_service import CatalogService
    from pc_parts_organizer.catalog_storage import CatalogStorage
    from pc_parts_organizer.csv_inventory_import import analyze_csv, csv_template_text
    from pc_parts_organizer.localization import Translator
    from pc_parts_organizer.service import InventoryService
    from pc_parts_organizer.storage import save_project_state
    from pc_parts_organizer.ui.main_window import MainWindow
    from pc_parts_organizer.ui.theme import configure_theme

    import faulthandler

    def _watchdog(secs: float = 480.0) -> None:
        time.sleep(secs)
        print("WATCHDOG: dumping tracebacks", flush=True)
        faulthandler.dump_traceback()
        os._exit(2)

    threading.Thread(target=_watchdog, daemon=True).start()

    shots = target / "shots"
    fixtures = target / "fixtures"
    exports = target / "exports"
    shots.mkdir(exist_ok=True)
    fixtures.mkdir(exist_ok=True)
    exports.mkdir(exist_ok=True)
    checks: dict = {}
    shot_index: list[dict] = []

    def log(msg: str) -> None:
        print(f"[walk] {msg}", flush=True)

    def print_window_png(hwnd: int, path: Path) -> bool:
        import ctypes as _ct

        user32 = _ct.windll.user32
        gdi32 = _ct.windll.gdi32
        from ctypes import wintypes as _wt
        r = _wt.RECT()
        user32.GetWindowRect(hwnd, _ct.byref(r))
        w, h = r.right - r.left, r.bottom - r.top
        if w < 50 or h < 50:
            return False
        hdc = user32.GetDC(None)
        mem = gdi32.CreateCompatibleDC(hdc)
        bmp = gdi32.CreateCompatibleBitmap(hdc, w, h)
        gdi32.SelectObject(mem, bmp)
        user32.PrintWindow(hwnd, mem, 2)
        from PIL import Image as _Img

        buf = _ct.create_string_buffer(w * h * 4)

        class _BMI(_ct.Structure):
            _fields_ = [("s", _ct.c_uint32), ("w", _ct.c_int32), ("h", _ct.c_int32),
                        ("p", _ct.c_uint16), ("b", _ct.c_uint16), ("c", _ct.c_uint32),
                        ("sz", _ct.c_uint32), ("x", _ct.c_int32), ("y", _ct.c_int32),
                        ("u", _ct.c_uint32), ("i", _ct.c_uint32)]

        bmi = _BMI(_ct.sizeof(_BMI), w, -h, 1, 32, 0, 0, 0, 0, 0, 0)
        ok = gdi32.GetDIBits(mem, bmp, 0, h, buf, _ct.byref(bmi), 0)
        gdi32.DeleteObject(bmp)
        gdi32.DeleteDC(mem)
        user32.ReleaseDC(None, hdc)
        if ok:
            _Img.frombuffer("RGBA", (w, h), buf, "raw", "BGRA", 0, 1).save(str(path))
        return bool(ok)

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
            shot_index.append({"name": name, "ok": ok})
            return ok
        except Exception as exc:
            shot_index.append({"name": name, "error": str(exc)})
            return False

    def drive_native_msgbox(titles: dict, shot_prefix: str, timeout: float = 30.0) -> dict:
        user32 = ctypes.windll.user32
        deadline = time.time() + timeout
        while time.time() < deadline:
            for title, tag in titles.items():
                hwnd = user32.FindWindowW(None, title)
                if hwnd:
                    time.sleep(0.5)
                    print_window_png(hwnd, shots / f"{shot_prefix}_{tag}.png")
                    shot_index.append({"name": f"{shot_prefix}_{tag}"})
                    user32.PostMessageW(hwnd, 0x0010, 0, 0)
                    return {"title": title, "tag": tag}
            time.sleep(0.25)
        return {"title": None, "tag": None}

    # ---------------------------------------------------------- synthetic data
    save_project_state([], [], [])
    svc = InventoryService()
    svc.add_component("CPU", "Existing", "Keep-1")
    log("synthetic inventory ready")

    def write_fixture(name: str, text: str, encoding: str = "utf-8") -> Path:
        p = fixtures / name
        p.write_bytes(text.encode(encoding))
        return p

    valid20 = "category,manufacturer,model,specs,notes\n" + "".join(
        f"CPU,Maker{i},Model-{i:02d},spec {i},note {i}\n" for i in range(20))
    p_valid = write_fixture("valid20.csv", valid20)
    mixed = ("category,manufacturer,model,specs,notes\n"
             "CPU,Existing,Keep-1,,\n"
             "CPU,AMD,New-1,6C,\n"
             "CPU,AMD,New-1,,\n"
             "Nope,,,\n"
             "GPU,N,X1,,\n")
    p_mixed = write_fixture("mixed.csv", mixed)
    p_semi = write_fixture("semi.csv", "category;manufacturer;model;specs;notes\nCPU;AMD;Ryzen;6C;\n")
    p_bom = write_fixture("bom.csv", "category,manufacturer,model,specs,notes\nCPU,Intel,Core i5,\"3,4 GHz\",\"Ordenador ñandú\"\n")
    p_bom = fixtures / "bom.csv"
    p_bom.write_bytes(b"\xef\xbb\xbf" + p_bom.read_bytes())
    p_badheader = write_fixture("badheader.csv", "manufacturer,model\nAMD,Ryzen\n")
    big = "category,manufacturer,model,specs,notes\n" + "".join(
        f"RAM,Bulk{i % 20},BulkModel-{i:04d},,\n" for i in range(1000))
    p_big = write_fixture("big1000.csv", big)

    # ------------------------------------------------------------------ Tk app
    root = tk.Tk()
    root.geometry("1280x860+120+60")
    configure_theme(root)
    translator = Translator()
    mw = MainWindow(root, svc, CatalogService(CatalogStorage()), translator)
    root.update()
    time.sleep(0.5)
    checks["mainwindow_open"] = bool(root.winfo_exists())
    log("main window open")

    def top_levels():
        return [w for w in root.winfo_children()
                if w.winfo_class() == "Toplevel" and w.winfo_exists()]

    def open_preview_dialog(csv_path: Path):
        with patch("tkinter.filedialog.askopenfilename", return_value=str(csv_path)):
            mw._open_csv_import()
        root.update()
        time.sleep(0.4)
        dlgs = top_levels()
        return dlgs[-1] if dlgs else None

    # 1. valid 20-row preview (ES)
    dlg = open_preview_dialog(p_valid)
    checks["preview_opens"] = dlg is not None
    if dlg is not None:
        checks["shot_01_preview"] = shoot_window(dlg, "01_preview_valid_es")
        # import via real button event
        for ch in dlg.winfo_children():
            stack = [ch]
            while stack:
                x = stack.pop(0)
                try:
                    if x.winfo_class() == "TButton" and x.cget("text") == translator.t("csv_import.import_valid"):
                        x.invoke()
                        break
                except Exception:
                    pass
                try:
                    stack.extend(x.winfo_children())
                except Exception:
                    pass
        root.update()
        time.sleep(0.4)
    checks["imported_20"] = len(svc.get_components()) == 21
    for leftover in top_levels():
        try:
            leftover.destroy()
        except Exception:
            pass
    log("valid import done")

    # 2. mixed: preview + full result (find newest result dialog)
    before = len(svc.get_components())
    dlg = open_preview_dialog(p_mixed)
    if dlg is not None:
        checks["shot_02_preview_mixed"] = shoot_window(dlg, "02_preview_mixed_es")
        for ch in dlg.winfo_children():
            stack = [ch]
            while stack:
                x = stack.pop(0)
                try:
                    if x.winfo_class() == "TButton" and x.cget("text") == translator.t("csv_import.import_valid"):
                        x.invoke()
                        break
                except Exception:
                    pass
                try:
                    stack.extend(x.winfo_children())
                except Exception:
                    pass
        root.update()
        time.sleep(0.4)
    after = len(svc.get_components())
    checks["mixed_import_delta"] = (after - before) == 2  # AMD New-1 + GPU N X1
    res = top_levels()
    if res:
        checks["shot_03_result_mixed"] = shoot_window(res[-1], "03_result_mixed_es")
        res[-1].destroy()
    log("mixed import done")

    # 3. header error -> native error dialog
    outcome: dict = {}
    titles = {translator.t("csv_import.error_title"): "error"}

    def driver_err():
        outcome.update(drive_native_msgbox(titles, "04_header_error"))

    t = threading.Thread(target=driver_err, daemon=True)
    t.start()
    with patch("tkinter.filedialog.askopenfilename", return_value=str(p_badheader)):
        mw._open_csv_import()
    t.join(timeout=30)
    root.update()
    checks["header_error_shown"] = outcome.get("tag") == "error"
    log(f"header error outcome: {outcome}")

    # 4. semicolon with delimiter override
    dlg = open_preview_dialog(p_semi)
    if dlg is not None:
        # force wrong delimiter first via combo, then correct
        for ch in dlg.winfo_children():
            stack = [ch]
            combos = []
            while stack:
                x = stack.pop(0)
                try:
                    if x.winfo_class() == "TCombobox":
                        combos.append(x)
                except Exception:
                    pass
                try:
                    stack.extend(x.winfo_children())
                except Exception:
                    pass
            if len(combos) >= 2:
                combos[1].set("punto y coma (;)")
                break
        for ch in dlg.winfo_children():
            stack = [ch]
            while stack:
                x = stack.pop(0)
                try:
                    if x.winfo_class() == "TButton" and x.cget("text") == translator.t("csv_import.reanalyze"):
                        x.invoke()
                        break
                except Exception:
                    pass
                try:
                    stack.extend(x.winfo_children())
                except Exception:
                    pass
        root.update()
        time.sleep(0.4)
        checks["shot_05_delimiter"] = shoot_window(dlg, "05_delimiter_override_es")
        dlg.destroy()
    log("delimiter override done")

    # 5. cancel path
    dlg = open_preview_dialog(p_bom)
    if dlg is not None:
        for ch in dlg.winfo_children():
            stack = [ch]
            while stack:
                x = stack.pop(0)
                try:
                    if x.winfo_class() == "TButton" and x.cget("text") == translator.t("csv_import.cancel"):
                        x.invoke()
                        break
                except Exception:
                    pass
                try:
                    stack.extend(x.winfo_children())
                except Exception:
                    pass
        root.update()
        time.sleep(0.5)
        root.update()
    try:
        leftovers = [w.title() for w in top_levels()]
    except Exception:
        leftovers = ["?"]
    checks["cancel_leftovers"] = leftovers
    checks["cancel_clean"] = len(top_levels()) == 0
    log("cancel done")

    # 6. template download (patched save dialog)
    tpl_dest = str(exports / "template.csv")
    outcome_tpl: dict = {}

    def driver_tpl():
        outcome_tpl.update(drive_native_msgbox(
            {translator.t("csv_import.template_success_title"): "ok"}, "06_template_success"))

    t2 = threading.Thread(target=driver_tpl, daemon=True)
    t2.start()
    with patch("tkinter.filedialog.asksaveasfilename", return_value=tpl_dest):
        mw._on_export_csv_template()
    t2.join(timeout=30)
    checks["template_saved"] = Path(tpl_dest).exists()
    if Path(tpl_dest).exists():
        raw = Path(tpl_dest).read_bytes()
        checks["template_utf8sig"] = raw.startswith(b"\xef\xbb\xbf")
        from pc_parts_organizer.csv_inventory_import import analyze_csv as _an
        ta = _an(tpl_dest)
        checks["template_analyzable"] = ta.total_rows == 3
    log(f"template outcome: {outcome_tpl}")

    # 7. large file preview scroll
    dlg = open_preview_dialog(p_big)
    if dlg is not None:
        checks["shot_07_big_preview"] = shoot_window(dlg, "07_big_preview_es")
        dlg.destroy()

    # 8. EN pass
    translator.change_language("en")
    mw.apply_translations()
    root.update()
    time.sleep(0.4)
    dlg = open_preview_dialog(p_mixed)
    if dlg is not None:
        checks["shot_08_preview_en"] = shoot_window(dlg, "08_preview_mixed_en")
        dlg.destroy()
    checks["shot_09_main_en"] = shoot_window(root, "09_main_en")
    log("en pass done")

    try:
        root.destroy()
    except Exception:
        pass

    gate = {k: v for k, v in checks.items() if k != "cancel_leftovers"}
    report = {
        "task": "T17.22 CSV import visual walkthrough",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "target": str(target),
        "checks": checks,
        "shots": shot_index,
        "all_checks_ok": all(v is True for v in gate.values()),
        "visual_manual_completed": False,
    }
    out = pcpo_sub / "t1722_walkthrough_report.json"
    out.write_text(__import__("json").dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(__import__("json").dumps({"ok": report["all_checks_ok"], "report": str(out),
                                    "failed": {k: v for k, v in gate.items() if v is not True}}, ensure_ascii=False, indent=2))
    return 0 if report["all_checks_ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
