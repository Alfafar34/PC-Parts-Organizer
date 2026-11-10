r"""Prepare isolated synthetic LOCALAPPDATA data for T17.11 socket-visibility validation.

Covers verified match/mismatch, missing/unverified sockets, Other values and
multi-component ambiguity. Real APIs only; never touches real data.
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

    def va(key, value, **kw):
        base = dict(source="official_vendor_doc", confidence="high",
                    verification_status="verified", evidence_ref="https://vendor.example/doc",
                    verified_at="2026-01-01")
        base.update(kw)
        return TechnicalAttribute(key=key, value=value, **base)

    def ua(key, value):
        return TechnicalAttribute(key=key, value=value, source="unknown",
                                  confidence="low", verification_status="unverified")

    svc = InventoryService()
    builds = {}

    def add_build(name, specs):
        comps = []
        for cat, model, attrs in specs:
            c = svc.add_component(cat, "T17.11", model, "", "T17.11")
            if attrs is not None:
                svc.set_technical_profile(TechnicalProfile(component_id=c.id, attributes=attrs))
            comps.append(c)
        b = svc.add_build(name)
        for c in comps:
            svc.add_component_to_build(b.id, c.id)
        return b.id

    # S1 match, both verified
    builds["S1"] = add_build("T17.11 - S1 socket match verified", [
        ("CPU", "CPU S1", [va("socket_designation", "AM5")]),
        ("Motherboard", "MB S1", [va("socket_designation", "AM5")]),
    ])
    # S2 mismatch, both verified
    builds["S2"] = add_build("T17.11 - S2 socket mismatch verified", [
        ("CPU", "CPU S2", [va("socket_designation", "AM5")]),
        ("Motherboard", "MB S2", [va("socket_designation", "LGA1700")]),
    ])
    # S3 CPU verified, motherboard without socket
    builds["S3"] = add_build("T17.11 - S3 motherboard socket missing", [
        ("CPU", "CPU S3", [va("socket_designation", "AM5")]),
        ("Motherboard", "MB S3", [va("form_factor", "ATX")]),
    ])
    # S4 motherboard verified, CPU without socket
    builds["S4"] = add_build("T17.11 - S4 CPU socket missing", [
        ("CPU", "CPU S4", None),
        ("Motherboard", "MB S4", [va("socket_designation", "AM5")]),
    ])
    # S5 present but unverified
    builds["S5"] = add_build("T17.11 - S5 socket unverified", [
        ("CPU", "CPU S5", [ua("socket_designation", "AM5")]),
        ("Motherboard", "MB S5", [ua("socket_designation", "AM5")]),
    ])
    # S6 Other value
    builds["S6"] = add_build("T17.11 - S6 socket Other", [
        ("CPU", "CPU S6", [va("socket_designation", "Other")]),
        ("Motherboard", "MB S6", [va("socket_designation", "AM5")]),
    ])
    # S7 multiple CPUs, no arbitrary pairing
    builds["S7"] = add_build("T17.11 - S7 multiple CPUs", [
        ("CPU", "CPU S7A", [va("socket_designation", "AM5")]),
        ("CPU", "CPU S7B", [va("socket_designation", "LGA1700")]),
        ("Motherboard", "MB S7", [va("socket_designation", "AM5")]),
    ])

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
    checks["loaded_builds_count"] = len(state.builds)
    checks["loaded_builds"] = len(state.builds) >= 7
    checks["all_build_ids_present"] = all(any(b.id == bid for b in state.builds) for bid in builds.values())

    def fs(key, rid):
        return [f for f in reports[key]["findings"] if f["rule_id"] == rid]

    def reason(key):
        f = fs(key, "cpu_mb.socket_visibility")
        return (f[0]["message_params"] or {}).get("reason") if f else None

    checks["S1_match_pending_platform"] = (
        any(f["result"] == "requires_verification" for f in fs("S1", "cpu_mb.socket_visibility"))
        and reason("S1") == "socket_match_pending_platform")
    checks["S2_mismatch_unresolved"] = (
        any(f["result"] == "requires_verification" for f in fs("S2", "cpu_mb.socket_visibility"))
        and reason("S2") == "socket_mismatch_unresolved")
    checks["S3_mb_socket_missing"] = any(
        f["result"] == "insufficient_data" for f in fs("S3", "cpu_mb.socket_visibility"))
    checks["S4_cpu_socket_missing"] = any(
        f["result"] == "insufficient_data" for f in fs("S4", "cpu_mb.socket_visibility"))
    checks["S5_not_verified"] = reason("S5") == "socket_not_verified"
    checks["S6_other_unresolvable"] = reason("S6") == "socket_not_resolvable"
    checks["S7_no_arbitrary_pairing"] = (
        fs("S7", "cpu_mb.socket_visibility") == []
        and any("cpu_cooling.cooler_missing" in f["rule_id"] for f in reports["S7"]["findings"]))
    checks["no_decisive_socket_verdict"] = all(
        f["result"] not in ("compatible", "incompatible")
        for r in reports.values() for f in r["findings"] if f["rule_id"] == "cpu_mb.socket_visibility")
    checks["no_critical_socket_severity"] = all(
        f["severity"] != "critical"
        for r in reports.values() for f in r["findings"] if f["rule_id"] == "cpu_mb.socket_visibility")
    checks["ne_present_when_compared"] = all(
        any(n.get("reason") in ("chipset_platform_not_evaluated", "firmware_bios_not_evaluated",
                                "power_delivery_not_evaluated")
            for n in reports[k]["not_evaluated"])
        for k in ("S1", "S2", "S5", "S6"))

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
            mw_ok = len([n for n in names if n.startswith("T17.11 - S")]) >= 7
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
        "task": "T17.11 socket visibility visual validation prep",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "target_localappdata_root": str(target), "pcpo_data_dir": str(pcpo_sub),
        "real_pcpo_dir_captured": str(real_pcpo) if real_pcpo else None, "temp_root": str(temp_root),
        "builds": {k: {"build_id": v, "name": next(b.name for b in state.builds if b.id == v)} for k, v in builds.items()},
        "reports": reports,
        "checks": checks,
        "all_checks_ok": all(v is True for k, v in checks.items() if k not in ("mainwindow_error", "loaded_builds_count")),
        "visual_manual_completed": False,
    }
    out = pcpo_sub / "t1711_visual_report.json"
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2, default=str) + "\n", encoding="utf-8")
    print(json.dumps({"ok": report["all_checks_ok"], "report": str(out), "target": str(target),
                      "checks": {k: v for k, v in checks.items() if k != "mainwindow_error"}, "mw_err": mw_err},
                     ensure_ascii=False, indent=2))
    return 0 if report["all_checks_ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
