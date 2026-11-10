r"""Prepare isolated synthetic LOCALAPPDATA data for T17.11-R1 mb_case validation.

Scenarios: unresolvable Other list, recognized incompatible pair, unverified
data. Real APIs only; never touches real data.
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

    def va(key, value):
        return TechnicalAttribute(key=key, value=value, source="official_vendor_doc", confidence="high",
                                  verification_status="verified", evidence_ref="https://vendor.example/doc",
                                  verified_at="2026-01-01")

    def ua(key, value):
        return TechnicalAttribute(key=key, value=value, source="unknown",
                                  confidence="low", verification_status="unverified")

    svc = InventoryService()
    builds = {}

    def add_build(name, mb_attrs, case_attrs):
        mb = svc.add_component("Motherboard", "T17.11-R1", f"MB {name}", "", "T17.11-R1")
        case = svc.add_component("Case", "T17.11-R1", f"Case {name}", "", "T17.11-R1")
        svc.set_technical_profile(TechnicalProfile(component_id=mb.id, attributes=mb_attrs))
        svc.set_technical_profile(TechnicalProfile(component_id=case.id, attributes=case_attrs))
        b = svc.add_build(name)
        svc.add_component_to_build(b.id, mb.id)
        svc.add_component_to_build(b.id, case.id)
        return b.id

    # S1: unresolvable Other list, verified both sides -> requires_verification
    builds["S1"] = add_build(
        "T17.11-R1 - S1 Other list requires verification",
        [va("form_factor", "ATX")],
        [va("supported_motherboard_form_factors", ["Other"])],
    )
    # S2: recognized incompatible pair, verified -> incompatible (preserved)
    builds["S2"] = add_build(
        "T17.11-R1 - S2 recognized mismatch incompatible",
        [va("form_factor", "E-ATX")],
        [va("supported_motherboard_form_factors", ["ATX"])],
    )
    # S3: unverified data -> requires_verification (generic path)
    builds["S3"] = add_build(
        "T17.11-R1 - S3 unverified data",
        [ua("form_factor", "ATX")],
        [va("supported_motherboard_form_factors", ["ATX"])],
    )

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
    checks["loaded_builds"] = len(state.builds) >= 3
    checks["all_build_ids_present"] = all(any(b.id == bid for b in state.builds) for bid in builds.values())

    def fs(key, rid):
        return [f for f in reports[key]["findings"] if f["rule_id"] == rid]

    checks["S1_other_requires_verification"] = (
        any(f["result"] == "requires_verification" for f in fs("S1", "mb_case.form_factor"))
        and not any(f["result"] == "incompatible" for f in reports["S1"]["findings"]
                    if f["rule_id"] == "mb_case.form_factor")
        and any((f.get("message_params") or {}).get("reason") == "other_not_confirmable"
                for f in fs("S1", "mb_case.form_factor")))
    checks["S1_no_critical"] = not any(
        f["severity"] == "critical" for f in reports["S1"]["findings"]
        if f["rule_id"] == "mb_case.form_factor")
    checks["S2_recognized_incompatible"] = any(
        f["result"] == "incompatible" and f["severity"] == "critical"
        for f in fs("S2", "mb_case.form_factor"))
    checks["S3_unverified_requires_verification"] = any(
        f["result"] == "requires_verification" for f in fs("S3", "mb_case.form_factor"))
    checks["global_no_false_incompatible"] = not any(
        f["result"] == "incompatible" for f in reports["S1"]["findings"])

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
            mw_ok = len([n for n in names if n.startswith("T17.11-R1 - S")]) >= 3
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
        "task": "T17.11-R1 mb_case Other/Proprietary visual validation prep",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "target_localappdata_root": str(target), "pcpo_data_dir": str(pcpo_sub),
        "real_pcpo_dir_captured": str(real_pcpo) if real_pcpo else None, "temp_root": str(temp_root),
        "builds": {k: {"build_id": v, "name": next(b.name for b in state.builds if b.id == v)} for k, v in builds.items()},
        "reports": reports,
        "checks": checks,
        "all_checks_ok": all(v is True for k, v in checks.items() if k not in ("mainwindow_error", "loaded_builds_count")),
        "visual_manual_completed": False,
    }
    out = pcpo_sub / "t1711_r1_visual_report.json"
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2, default=str) + "\n", encoding="utf-8")
    print(json.dumps({"ok": report["all_checks_ok"], "report": str(out), "target": str(target),
                      "checks": {k: v for k, v in checks.items() if k != "mainwindow_error"}, "mw_err": mw_err},
                     ensure_ascii=False, indent=2))
    return 0 if report["all_checks_ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
