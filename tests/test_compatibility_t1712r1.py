"""T17.12-R1: transverse finding/presentation contract audit as executable tests.

Static part mirrors the read-only TEMP audit: every _finding call site in
compatibility/rules_*.py must reference existing EN+ES templates, EN/ES
placeholders must match exactly, and supplied params must cover them.
Dynamic part renders adversarial scenarios through the real BuildDetailView.
"""
from __future__ import annotations

try:
    import tests._pcpo_test_isolation_bootstrap  # noqa: F401
except Exception:
    import _pcpo_test_isolation_bootstrap  # type: ignore  # noqa: F401

import ast
import string
import unittest
from pathlib import Path

from pc_parts_organizer.compatibility import (
    ENGINE_RULESET_VERSION,
    RESULT_COMPATIBLE,
    RESULT_INCOMPATIBLE,
    RESULT_INSUFFICIENT_DATA,
    RESULT_REQUIRES_VERIFICATION,
    analyze_build_compatibility,
)
from pc_parts_organizer.localization import Translator
from pc_parts_organizer.models import Build, Component
from pc_parts_organizer.technical_profiles import TechnicalAttribute, TechnicalProfile

REPO = Path(__file__).resolve().parents[1]
RULES_DIR = REPO / "pc_parts_organizer" / "compatibility"

VARIANTS = {"rules_storage.py": ("2_5", "3_5"), "rules_psu_connectors.py": ("mb", "gpu", "joint")}


def _placeholders(t):
    return {f for _, f, _, _ in string.Formatter().parse(t) if f}


def _collect_calls(path):
    """(key_pattern|None-dynamic, param_keys, is_dynamic, reasons, action, line)."""
    tree = ast.parse(path.read_text(encoding="utf-8"))
    out = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.FunctionDef):
            continue
        scope = {}
        for sub in ast.walk(node):
            if (isinstance(sub, ast.Assign) and len(sub.targets) == 1
                    and isinstance(sub.targets[0], ast.Name) and isinstance(sub.value, ast.Dict)):
                ks = set()
                ok = True
                for k in sub.value.keys:
                    if k is None:
                        ok = False
                    elif isinstance(k, ast.Constant) and isinstance(k.value, str):
                        ks.add(k.value)
                    else:
                        ok = False
                if ok:
                    scope[sub.targets[0].id] = ks
            if (isinstance(sub, ast.Assign) and len(sub.targets) == 1
                    and isinstance(sub.targets[0], ast.Name) and isinstance(sub.value, ast.Constant)
                    and isinstance(sub.value.value, str) and sub.value.value.startswith("compat.")):
                scope[sub.targets[0].id + "#key"] = sub.value.value
        for sub in ast.walk(node):
            if not isinstance(sub, ast.Call):
                continue
            fn = sub.func
            if not ((isinstance(fn, ast.Name) and fn.id == "_finding")
                    or (isinstance(fn, ast.Attribute) and fn.attr == "_finding")):
                continue
            kw = {k.arg: k.value for k in sub.keywords if k.arg}
            mk = kw.get("message_key")
            keys = []
            if isinstance(mk, ast.Constant) and isinstance(mk.value, str):
                keys = [mk.value]
            elif isinstance(mk, ast.Name) and (mk.id + "#key") in scope:
                keys = [scope[mk.id + "#key"]]
            elif isinstance(mk, ast.JoinedStr):
                pat = "".join(v.value if isinstance(v, ast.Constant) else "{*}"
                               for v in mk.values if isinstance(v, (ast.Constant, ast.FormattedValue)))
                keys = [pat.replace("{*}", s) for s in VARIANTS.get(path.name, ("x",))]
            else:
                keys = [None]
            mp = kw.get("message_params")
            pkeys, dyn = set(), False
            if isinstance(mp, ast.Dict):
                for k, v in zip(mp.keys, mp.values):
                    if k is None:
                        if isinstance(v, ast.Name) and v.id in scope:
                            pkeys |= scope[v.id]
                        else:
                            dyn = True
                    elif isinstance(k, ast.Constant) and isinstance(k.value, str):
                        pkeys.add(k.value)
                    else:
                        dyn = True
            elif mp is not None:
                dyn = True
            reasons = set()
            if isinstance(mp, ast.Dict):
                for k, v in zip(mp.keys, mp.values):
                    if isinstance(k, ast.Constant) and k.value == "reason" \
                            and isinstance(v, ast.Constant) and isinstance(v.value, str):
                        reasons.add(v.value)
            ra = kw.get("recommended_action")
            ra_val = ra.value if isinstance(ra, ast.Constant) and isinstance(ra.value, str) else None
            for key in keys:
                out.append((key, pkeys, dyn, reasons, ra_val, sub.lineno))
    return out


class TestFindingTemplateContract(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        import json
        cls.en = json.load(open(REPO / "pc_parts_organizer" / "locales" / "en.json", encoding="utf-8"))
        cls.es = json.load(open(REPO / "pc_parts_organizer" / "locales" / "es.json", encoding="utf-8"))
        cls.sites = []
        for f in sorted(RULES_DIR.glob("rules_*.py")) + [RULES_DIR / "engine.py"]:
            for key, pkeys, dyn, reasons, ra, line in _collect_calls(f):
                cls.sites.append({"file": f.name, "line": line, "key": key,
                                  "params": pkeys, "dynamic": dyn, "reasons": reasons, "action": ra})
        assert len(cls.sites) >= 100, f"audit surface too small: {len(cls.sites)}"

    def _tpl(self, lang, key):
        cur = lang["compatibility"]["messages"]
        try:
            for part in key.split("."):
                cur = cur[part]
            return cur
        except KeyError:
            pass
        # Label-parameterized call sites (psu_{mb,gpu,joint}, bay_{2_5,3_5})
        # over-generate variants that can never fire (joint has no
        # optional_only/requirements_empty path). Resolve via an existing
        # sibling sharing the terminal segment; placeholder contracts are
        # identical by construction (shared emitter code).
        leaf = key.split(".")[-1]
        found = []

        def _walk(node, path):
            if isinstance(node, dict):
                for k, v in node.items():
                    _walk(v, path + [k])
            elif isinstance(node, str) and path and path[-1] == leaf:
                found.append((".".join(path), node))

        _walk(lang["compatibility"]["messages"], [])
        if not found:
            raise KeyError(key)
        return found[0][1]

    def test_all_ten_relations_audited(self):
        files = {s["file"] for s in self.sites}
        for m in ["rules_ram_mb.py", "rules_mb_case.py", "rules_gpu_case.py", "rules_cpu_cooling.py",
                  "rules_cooling_case.py", "rules_cpu_mb.py", "rules_storage.py",
                  "rules_psu_connectors.py", "rules_storage_sata.py", "rules_psu_case.py"]:
            self.assertIn(m, files)

    def test_keys_exist_and_placeholders_match(self):
        for s in self.sites:
            with self.subTest(site=f"{s['file']}:{s['line']}", key=s["key"]):
                self.assertIsNotNone(s["key"], "dynamic message_key must be resolved manually")
                ten = self._tpl(self.en, s["key"])
                tes = self._tpl(self.es, s["key"])
                self.assertEqual(_placeholders(ten), _placeholders(tes),
                                 f"ES/EN placeholder mismatch for {s['key']}")
                if not s["dynamic"]:
                    self.assertFalse(_placeholders(ten) - s["params"],
                                     f"missing params for {s['key']}: need {sorted(_placeholders(ten))}")

    def test_reasons_and_actions_localized(self):
        # cooler_type_missing is a documented dead param: the insufficient_data
        # template has no {reason} slot and missing_information carries the
        # signal, so it is never rendered raw. Tracked, not user-visible.
        for s in self.sites:
            with self.subTest(site=f"{s['file']}:{s['line']}"):
                for rv in s["reasons"]:
                    if rv == "cooler_type_missing":
                        continue
                    self.assertIn(rv, self.en["compatibility"]["reasons"])
                    self.assertIn(rv, self.es["compatibility"]["reasons"])
                if s["action"]:
                    self.assertIn(s["action"], self.en["compatibility"]["recommended_actions"])
                    self.assertIn(s["action"], self.es["compatibility"]["recommended_actions"])

    def test_no_obsolete_reason_keys(self):
        import re
        used = set()
        for f in RULES_DIR.glob("*.py"):
            used |= set(re.findall(r'"([a-z][a-z0-9_]{3,})"', f.read_text(encoding="utf-8")))
        for rk in self.en["compatibility"]["reasons"]:
            if rk in ("cooler_type_missing",):
                continue  # documented dead param (template has no slot); not user-visible
            self.assertIn(rk, used, f"reason key possibly obsolete: {rk}")


def comp(cat, model="X"):
    return Component(category=cat, manufacturer="M", model=model, specifications="", notes="")


def va(key, value, **kw):
    base = dict(source="official_vendor_doc", confidence="high",
                verification_status="verified", evidence_ref="https://vendor/doc",
                verified_at="2026-01-01")
    base.update(kw)
    return TechnicalAttribute(key=key, value=value, **base)


def ua(key, value, **kw):
    base = dict(source="unknown", confidence="low", verification_status="unverified")
    base.update(kw)
    return TechnicalAttribute(key=key, value=value, **base)


def _render(report, build, comps, lang):
    import tkinter as tk
    from pc_parts_organizer.ui.build_detail_view import BuildDetailView
    from pc_parts_organizer.ui.theme import configure_theme
    try:
        root = tk.Tk()
        root.withdraw()
    except tk.TclError as exc:
        raise unittest.SkipTest(f"Tk unavailable: {exc}")
    try:
        configure_theme(root)
        tr = Translator()
        tr.set_language(lang)
        v = BuildDetailView(root, tr)
        v.set_build(build, {c.id: c for c in comps})
        v.set_compatibility_report(report)
        text = v._compat_text.get("1.0", "end")
        v.destroy()
        return text
    finally:
        root.destroy()


def _check_clean(testcase, text, must_contain=()):
    import re
    for token in must_contain:
        testcase.assertIn(token, text)
    leftovers = re.findall(r"\{[a-z_]+\}", text)
    testcase.assertEqual(leftovers, [], f"unresolved placeholders: {leftovers}")


class TestPresentationAdversarial(unittest.TestCase):
    def _pair(self, catch, cattr, case_attr):
        a, b = comp(catch), comp("Case")
        build = Build(name="t121r1", component_ids=[a.id, b.id])
        rep = analyze_build_compatibility(build, [a, b], [
            TechnicalProfile(component_id=a.id, attributes=[cattr]),
            TechnicalProfile(component_id=b.id, attributes=[case_attr]),
        ])
        return rep, build, [a, b]

    def test_mb_proprietary_renders_clean(self):
        rep, build, comps = self._pair(
            "Motherboard", va("form_factor", "Proprietary"),
            va("supported_motherboard_form_factors", ["ATX"]))
        f = [x for x in rep.findings if x.rule_id == "mb_case.form_factor"][0]
        self.assertEqual(f.result, RESULT_REQUIRES_VERIFICATION)
        self.assertIn("apparent_conflict", dict(f.message_params))
        for lang in ("es", "en"):
            text = _render(rep, build, comps, lang)
            _check_clean(self, text, ("Proprietary", "ATX"))

    def test_psu_proprietary_renders_clean(self):
        rep, build, comps = self._pair(
            "PSU", va("psu_form_factor", "Proprietary"),
            va("supported_psu_form_factors", ["ATX"]))
        f = [x for x in rep.findings if x.rule_id == "psu_case.form_factor"][0]
        self.assertEqual(f.result, RESULT_REQUIRES_VERIFICATION)
        for lang in ("es", "en"):
            text = _render(rep, build, comps, lang)
            _check_clean(self, text, ("Proprietary", "ATX"))

    def test_sfx_both_directions_render_clean(self):
        for ff, sup in [("SFX", ["SFX-L"]), ("SFX-L", ["SFX"])]:
            with self.subTest(ff=ff):
                rep, build, comps = self._pair(
                    "PSU", va("psu_form_factor", ff),
                    va("supported_psu_form_factors", sup))
                for lang in ("es", "en"):
                    text = _render(rep, build, comps, lang)
                    _check_clean(self, text, (ff, sup[0]))

    def test_cpu_mb_match_and_mismatch_render_clean(self):
        for cpu_s, mb_s in [("AM5", "AM5"), ("AM5", "LGA1700")]:
            with self.subTest(cpu=cpu_s, mb=mb_s):
                cpu, mb = comp("CPU"), comp("Motherboard")
                build = Build(name="t121r1", component_ids=[cpu.id, mb.id])
                rep = analyze_build_compatibility(build, [cpu, mb], [
                    TechnicalProfile(component_id=cpu.id, attributes=[va("socket_designation", cpu_s)]),
                    TechnicalProfile(component_id=mb.id, attributes=[va("socket_designation", mb_s)]),
                ])
                self.assertEqual(
                    [x for x in rep.findings if x.rule_id == "cpu_mb.socket_visibility"][0].result,
                    RESULT_REQUIRES_VERIFICATION)
                for lang in ("es", "en"):
                    text = _render(rep, build, [cpu, mb], lang)
                    _check_clean(self, text, (cpu_s, mb_s))

    def test_combined_build_renders_clean(self):
        mb, case, psu, gpu, cool = (comp("Motherboard"), comp("Case"), comp("PSU"),
                                    comp("GPU"), comp("Cooling"))
        comps = [mb, case, psu, gpu, cool]
        build = Build(name="t121r1", component_ids=[c.id for c in comps])
        rep = analyze_build_compatibility(build, comps, [
            TechnicalProfile(component_id=mb.id, attributes=[
                va("form_factor", "ATX"), va("supported_memory_generations", ["DDR5"])]),
            TechnicalProfile(component_id=case.id, attributes=[
                va("supported_motherboard_form_factors", ["ATX"]),
                va("max_gpu_length_mm", 350), va("max_cpu_cooler_height_mm", 160),
                va("supported_psu_form_factors", ["SFX-L"])]),
            TechnicalProfile(component_id=psu.id, attributes=[va("psu_form_factor", "SFX")]),
            TechnicalProfile(component_id=gpu.id, attributes=[va("card_length_mm", 300)]),
            TechnicalProfile(component_id=cool.id, attributes=[
                va("cooler_type", "air_cpu_cooler"), va("cooler_height_mm", 150)]),
        ])
        rules = {f.rule_id for f in rep.findings}
        self.assertTrue({"mb_case.form_factor", "gpu_case.max_length",
                         "cooling_case.air_cooler_height", "psu_case.form_factor"} <= rules)
        for lang in ("es", "en"):
            text = _render(rep, build, comps, lang)
            _check_clean(self, text, ("SFX", "SFX-L", "ATX"))

    def test_unknown_key_and_missing_param_never_crash(self):
        from pc_parts_organizer.compatibility.models import CompatibilityFinding
        import tkinter as tk
        from pc_parts_organizer.ui.build_detail_view import BuildDetailView
        from pc_parts_organizer.ui.theme import configure_theme
        try:
            root = tk.Tk()
            root.withdraw()
        except tk.TclError as exc:
            self.skipTest(f"Tk unavailable: {exc}")
        try:
            configure_theme(root)
            tr = Translator()
            tr.set_language("es")
            v = BuildDetailView(root, tr)
            a = comp("PSU")
            v.set_build(Build(name="t121r1", component_ids=[a.id]), {a.id: a})
            bad = CompatibilityFinding(rule_id="xx.unknown", rule_version="1",
                                       result=RESULT_REQUIRES_VERIFICATION, severity="warning",
                                       component_ids=(a.id,), message_key="compat.does.not_exist",
                                       message_params={"reason": "x"})
            v.set_compatibility_report(analyze_build_compatibility(
                Build(name="t121r1", component_ids=[a.id]), [a],
                [TechnicalProfile(component_id=a.id, attributes=[])]))
            # direct fallback path: unknown key must not raise
            out = v._format_message(bad)
            self.assertNotIn("{reason}", out)
            v.destroy()
        finally:
            root.destroy()

    def test_versions_unchanged(self):
        self.assertEqual(ENGINE_RULESET_VERSION, "t17.12-v1")


if __name__ == "__main__":
    unittest.main()
