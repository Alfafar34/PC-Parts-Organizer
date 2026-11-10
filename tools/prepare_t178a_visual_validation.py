r"""Prepare isolated synthetic LOCALAPPDATA data for T17.8a-R2 visual validation.

SAFETY:
- Uses an explicit target directory under the system TEMP directory only.
- Refuses the real %LOCALAPPDATA%\PCPartsOrganizer data directory and any existing non-empty target.
- Does NOT copy/read/modify/export/restore real inventory, settings, or catalog.
- Sets LOCALAPPDATA before importing pc_parts_organizer modules that resolve storage paths.

Usage (from repo root):
  python tools/prepare_t178a_visual_validation.py --target %TEMP%\PCPO-T17.8aR2-visual-<stamp>
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
    ap.add_argument("--target", required=True, help="Absolute path under system TEMP for isolated LOCALAPPDATA root")
    args = ap.parse_args(argv)

    real_pcpo = _real_pcpo_dir()
    target = Path(args.target).expanduser().resolve()
    temp_root = Path(tempfile.gettempdir()).resolve()

    if not _is_under_temp(target):
        print(f"REFUSED: target must be under system TEMP ({temp_root}). Got: {target}", file=sys.stderr)
        return 2
    if target == temp_root:
        print("REFUSED: target must be a dedicated subdirectory under TEMP, not TEMP itself.", file=sys.stderr)
        return 2
    if real_pcpo is not None and (target == real_pcpo or str(target).lower().startswith(str(real_pcpo).lower() + os.sep.lower())):
        print(f"REFUSED: target overlaps real PCPartsOrganizer data dir: {real_pcpo}", file=sys.stderr)
        return 2
    pcpo_sub = target / "PCPartsOrganizer"
    if pcpo_sub.exists():
        if any(pcpo_sub.iterdir()):
            print(f"REFUSED: target already contains data: {pcpo_sub} (choose a new directory)", file=sys.stderr)
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

    def va(key, value, unit=None):
        return TechnicalAttribute(key=key, value=value, unit=unit, source="official_vendor_doc", confidence="high", verification_status="verified", evidence_ref="https://vendor.example/doc", verified_at="2026-01-01")

    def ua(key, value, unit=None):
        return TechnicalAttribute(key=key, value=value, unit=unit, source="unknown", confidence="low", verification_status="unverified")

    service = InventoryService()
    builds = {}

    mb1 = service.add_component("Motherboard", "T17.8a Visual", "MB M2 FIT", "", "S1")
    st1 = service.add_component("Storage", "T17.8a Visual", "SSD NVMe FIT", "", "S1")
    service.set_technical_profile(TechnicalProfile(component_id=mb1.id, attributes=[va("form_factor","ATX"), va("m2_slots", [{"slot_id":"M2_1","accepted_module_keyings":["M"],"supported_lengths":["2280"],"supported_modes":["pcie_nvme"],"evidence_ref":"https://vendor.example/mb/m2_1"}])]))
    service.set_technical_profile(TechnicalProfile(component_id=st1.id, attributes=[va("storage_form_factor","m2"), va("storage_interface","pcie"), va("storage_command_set","nvme"), va("m2_keying","M"), va("m2_length_code","2280")]))
    b1 = service.add_build("T17.8a Visual - S1 M.2 fit documented")
    service.add_component_to_build(b1.id, mb1.id); service.add_component_to_build(b1.id, st1.id); builds["S1"] = b1.id

    mb2 = service.add_component("Motherboard", "T17.8a Visual", "MB M2 UNKNOWN", "", "S2")
    st2 = service.add_component("Storage", "T17.8a Visual", "SSD NVMe UNKNOWN", "", "S2")
    service.set_technical_profile(TechnicalProfile(component_id=mb2.id, attributes=[ua("m2_slots", [{"slot_id":"M2_1","accepted_module_keyings":["M"],"supported_lengths":["2280"],"supported_modes":["pcie_nvme"]}])]))
    service.set_technical_profile(TechnicalProfile(component_id=st2.id, attributes=[va("storage_form_factor","m2"), ua("storage_interface","pcie"), ua("storage_command_set","nvme"), ua("m2_keying","M"), ua("m2_length_code","2280")]))
    b2 = service.add_build("T17.8a Visual - S2 M.2 insufficient info")
    service.add_component_to_build(b2.id, mb2.id); service.add_component_to_build(b2.id, st2.id); builds["S2"] = b2.id

    mb3 = service.add_component("Motherboard", "T17.8a Visual", "MB M2 SATA-ONLY DECL", "", "S3")
    st3 = service.add_component("Storage", "T17.8a Visual", "SSD NVMe NO-MATCH", "", "S3")
    service.set_technical_profile(TechnicalProfile(component_id=mb3.id, attributes=[va("form_factor","ATX"), va("m2_slots", [{"slot_id":"M2_SATA1","accepted_module_keyings":["B_M"],"supported_lengths":["2280"],"supported_modes":["sata_ata"],"evidence_ref":"https://vendor.example/mb/m2_sata1"}])]))
    service.set_technical_profile(TechnicalProfile(component_id=st3.id, attributes=[va("storage_form_factor","m2"), va("storage_interface","pcie"), va("storage_command_set","nvme"), va("m2_keying","M"), va("m2_length_code","2280")]))
    b3 = service.add_build("T17.8a Visual - S3 M.2 no-match no exhaustiveness")
    service.add_component_to_build(b3.id, mb3.id); service.add_component_to_build(b3.id, st3.id); builds["S3"] = b3.id

    case4 = service.add_component("Case", "T17.8a Visual", "CASE BAYS OK", "", "S4")
    s25 = service.add_component("Storage", "T17.8a Visual", "SSD 2.5 OK", "", "S4")
    s35 = service.add_component("Storage", "T17.8a Visual", "HDD 3.5 OK", "", "S4")
    service.set_technical_profile(TechnicalProfile(component_id=case4.id, attributes=[va("supported_motherboard_form_factors", ["ATX"]), va("bay_2_5_total", 2), va("bay_3_5_total", 2)]))
    service.set_technical_profile(TechnicalProfile(component_id=s25.id, attributes=[va("storage_form_factor","2_5_in")]))
    service.set_technical_profile(TechnicalProfile(component_id=s35.id, attributes=[va("storage_form_factor","3_5_in")]))
    b4 = service.add_build("T17.8a Visual - S4 bays sufficient")
    for c in (case4,s25,s35): service.add_component_to_build(b4.id, c.id)
    builds["S4"] = b4.id

    case5 = service.add_component("Case", "T17.8a Visual", "CASE BAYS FULL", "", "S5")
    h1 = service.add_component("Storage", "T17.8a Visual", "HDD 3.5 1", "", "S5")
    h2 = service.add_component("Storage", "T17.8a Visual", "HDD 3.5 2", "", "S5")
    h3 = service.add_component("Storage", "T17.8a Visual", "HDD 3.5 3", "", "S5")
    service.set_technical_profile(TechnicalProfile(component_id=case5.id, attributes=[va("supported_motherboard_form_factors", ["ATX"]), va("bay_3_5_total", 2)]))
    for h in (h1,h2,h3): service.set_technical_profile(TechnicalProfile(component_id=h.id, attributes=[va("storage_form_factor","3_5_in")]))
    b5 = service.add_build("T17.8a Visual - S5 bays insufficient")
    for c in (case5,h1,h2,h3): service.add_component_to_build(b5.id, c.id)
    builds["S5"] = b5.id

    state = load_project_state()
    reports = {}
    checks = {}
    for key, bid in builds.items():
        r = service.analyze_build_compatibility(bid)
        reports[key] = {"build_id": bid, "overall": r.overall_result, "findings": [(f.rule_id, f.result, f.message_key, dict(f.message_params)) for f in r.findings], "limitations": list(r.analysis_limitations), "not_evaluated": [dict(n) for n in r.not_evaluated_relations], "ruleset": r.ruleset_version}
    state3 = load_project_state()
    checks["no_compat_persistence"] = (len(state.technical_profiles) == len(state3.technical_profiles) and len(state.components) == len(state3.components) and len(state.builds) == len(state3.builds))
    checks["loaded_builds"] = len(state.builds)
    checks["all_build_ids_present"] = all(any(b.id == bid for b in state.builds) for bid in builds.values())
    checks["S1_m2_compatible_dimension"] = any(x[0]=="storage_m2.fit" and x[1]=="compatible" for x in reports["S1"]["findings"])
    checks["S2_requires_or_insufficient"] = any(x[0]=="storage_m2.fit" and x[1] in ("requires_verification","insufficient_data") for x in reports["S2"]["findings"])
    s3f = [x for x in reports["S3"]["findings"] if x[0]=="storage_m2.fit"]
    checks["S3_requires_verification_not_incompatible"] = bool(s3f) and all(x[1]=="requires_verification" for x in s3f) and all(x[1]!="incompatible" for x in s3f)
    checks["S3_exhaustiveness_reason"] = any(x[3].get("reason")=="collection_exhaustiveness_not_demonstrated" for x in s3f)
    checks["S4_bays_compatible"] = any("bay" in x[0] and x[1]=="compatible" for x in reports["S4"]["findings"])
    checks["S5_bays_incompatible"] = any("bay" in x[0] and x[1]=="incompatible" for x in reports["S5"]["findings"])

    report = {"task":"T17.8a-R2 visual validation prep","generated_at":datetime.now(timezone.utc).isoformat(),"target_localappdata_root":str(target),"pcpo_data_dir":str(pcpo_sub),"real_pcpo_dir_captured":str(real_pcpo) if real_pcpo else None,"temp_root":str(temp_root),"builds":{k:{"build_id":v,"name":next(b.name for b in state.builds if b.id==v)} for k,v in builds.items()},"reports":reports,"checks":checks,"all_checks_ok":all(checks.values()),"visual_manual_completed":False}
    out = pcpo_sub / "t178a_r2_visual_report.json"
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"ok": report["all_checks_ok"], "report": str(out), "target": str(target), "checks": checks}, ensure_ascii=False, indent=2))
    return 0 if report["all_checks_ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())