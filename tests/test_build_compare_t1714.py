"""T17.14: build comparator tests (pure algorithm + integration + UI)."""
from __future__ import annotations

try:
    import tests._pcpo_test_isolation_bootstrap  # noqa: F401
except Exception:
    import _pcpo_test_isolation_bootstrap  # type: ignore  # noqa: F401

import unittest

from pc_parts_organizer.build_compare import (
    ADDED,
    REMOVED,
    REPLACED,
    UNCHANGED,
    UNKNOWN,
    compare_hardware,
    compare_reports,
    correspondence_from_hardware,
)
from pc_parts_organizer.compatibility import (
    RESULT_COMPATIBLE,
    RESULT_INCOMPATIBLE,
    RESULT_INSUFFICIENT_DATA,
    RESULT_REQUIRES_VERIFICATION,
    analyze_build_compatibility,
)
from pc_parts_organizer.models import Build, Component
from pc_parts_organizer.technical_profiles import TechnicalAttribute, TechnicalProfile


def comp(cat, model="X", manufacturer="M"):
    return Component(category=cat, manufacturer=manufacturer, model=model, specifications="", notes="")


def va(key, value, **kw):
    base = dict(source="official_vendor_doc", confidence="high",
                verification_status="verified", evidence_ref="https://vendor/doc",
                verified_at="2026-01-01")
    base.update(kw)
    return TechnicalAttribute(key=key, value=value, **base)


def by_id(comps, profs):
    return ({c.id: c for c in comps}, {p.component_id: p for p in profs})


class TestHardwarePairing(unittest.TestCase):
    def test_identical_builds_all_unchanged(self):
        a, b = comp("RAM", "R1"), comp("GPU", "G1")
        ba = Build(name="A", component_ids=[a.id, b.id])
        bb = Build(name="B", component_ids=[a.id, b.id])
        d = compare_hardware(ba, bb, *by_id([a, b], []))
        self.assertEqual(d.common_count, 2)
        self.assertTrue(all(i.state == UNCHANGED for i in d.items))
        self.assertEqual((d.added_count, d.removed_count, d.replaced_count, d.unknown_count), (0, 0, 0, 0))

    def test_empty_builds(self):
        d = compare_hardware(Build(name="A"), Build(name="B"), {}, {})
        self.assertEqual(len(d.items), 0)

    def test_added_removed(self):
        a, b, c = comp("RAM", "R1"), comp("GPU", "G1"), comp("PSU", "P1")
        d = compare_hardware(Build(name="A", component_ids=[a.id, b.id]),
                             Build(name="B", component_ids=[b.id, c.id]),
                             *by_id([a, b, c], []))
        states = {(i.state, i.category) for i in d.items}
        self.assertIn((REMOVED, "RAM"), states)
        self.assertIn((ADDED, "PSU"), states)
        self.assertIn((UNCHANGED, "GPU"), states)

    def test_replaced_single_pair(self):
        a, b = comp("GPU", "G1"), comp("GPU", "G2", manufacturer="N")
        d = compare_hardware(Build(name="A", component_ids=[a.id]),
                             Build(name="B", component_ids=[b.id]),
                             *by_id([a, b], []))
        self.assertEqual(d.replaced_count, 1)
        item = [i for i in d.items if i.state == REPLACED][0]
        self.assertEqual(item.field_diffs["manufacturer"], ("M", "N"))

    def test_unknown_multiplicity(self):
        a1, a2, b1 = comp("Storage", "S1"), comp("Storage", "S2"), comp("Storage", "S3")
        d = compare_hardware(Build(name="A", component_ids=[a1.id, a2.id]),
                             Build(name="B", component_ids=[b1.id]),
                             *by_id([a1, a2, b1], []))
        self.assertEqual(d.unknown_count, 3)
        self.assertEqual(d.replaced_count, 0)

    def test_modified_state_eliminated(self):
        from pc_parts_organizer import build_compare as bc
        self.assertNotIn("modified", bc.COMPONENT_STATES)
        self.assertFalse(hasattr(bc.HardwareDiff(
            items=(), common_count=0, added_count=0, removed_count=0,
            replaced_count=0, unknown_count=0, tech_changes=0), "modified_count"))
        # shared identity can never diverge in a single snapshot
        a = comp("RAM", "R1")
        pa = TechnicalProfile(component_id=a.id, attributes=[va("memory_generation", "DDR4")])
        d = compare_hardware(Build(name="A", component_ids=[a.id]),
                             Build(name="B", component_ids=[a.id]),
                             {a.id: a}, {a.id: pa})
        self.assertTrue(all(i.state == UNCHANGED for i in d.items))
        self.assertEqual([i.field_diffs for i in d.items], [{}])
        self.assertTrue(all(not i.attribute_diffs for i in d.items))

    def test_metadata_only_not_modified(self):
        x, y = comp("GPU", "G1"), comp("GPU", "G1", manufacturer="M")
        px = TechnicalProfile(component_id=x.id, attributes=[va("card_length_mm", 300)])
        py = TechnicalProfile(component_id=y.id, attributes=[
            TechnicalAttribute(key="card_length_mm", value=300, source="user_input",
                               confidence="medium", verification_status="unverified")])
        d = compare_hardware(Build(name="A", component_ids=[x.id]),
                             Build(name="B", component_ids=[y.id]),
                             {x.id: x, y.id: y}, {x.id: px, y.id: py})
        item = [i for i in d.items if i.state == REPLACED][0]
        self.assertEqual([z.status for z in item.attribute_diffs], ["equal"])
        self.assertTrue(item.attribute_diffs[0].meta_differs)

    def test_missing_attributes(self):
        x, y = comp("GPU", "G1"), comp("GPU", "G2")
        px = TechnicalProfile(component_id=x.id, attributes=[va("card_length_mm", 300)])
        py = TechnicalProfile(component_id=y.id, attributes=[])
        d = compare_hardware(Build(name="A", component_ids=[x.id]),
                             Build(name="B", component_ids=[y.id]),
                             {x.id: x, y.id: y}, {x.id: px, y.id: py})
        item = [i for i in d.items if i.state == REPLACED][0]
        self.assertEqual([z.status for z in item.attribute_diffs], ["missing_b"])

    def test_order_independence(self):
        cs = [comp("RAM", f"R{i}") for i in range(3)] + [comp("GPU", "G1")]
        maps = by_id(cs, [])
        ba = Build(name="A", component_ids=[c.id for c in cs])
        bb = Build(name="B", component_ids=[cs[0].id])
        d1 = compare_hardware(ba, bb, *maps)
        ba2 = Build(name="A", component_ids=[c.id for c in reversed(cs)])
        d3 = compare_hardware(ba2, bb, *maps)
        s1 = sorted((i.state, i.category, (i.component_a.id if i.component_a else None),
                     (i.component_b.id if i.component_b else None)) for i in d1.items)
        s3 = sorted((i.state, i.category, (i.component_a.id if i.component_a else None),
                     (i.component_b.id if i.component_b else None)) for i in d3.items)
        self.assertEqual(s1, s3)
        # direction is significant: swapped sides mirror added/removed
        inv = compare_hardware(bb, ba, *maps)
        self.assertEqual(inv.added_count, d1.removed_count)
        self.assertEqual(inv.removed_count, d1.added_count)

    def test_purity(self):
        import copy
        a, b = comp("RAM", "R1"), comp("GPU", "G1")
        comps = {a.id: a, b.id: b}
        ba = Build(name="A", component_ids=[a.id])
        bb = Build(name="B", component_ids=[b.id])
        before = copy.deepcopy(ba.__dict__)
        d1 = compare_hardware(ba, bb, comps, {})
        d2 = compare_hardware(ba, bb, comps, {})
        self.assertEqual(ba.__dict__, before)
        self.assertEqual([(i.state, i.category) for i in d1.items],
                         [(i.state, i.category) for i in d2.items])

    def test_counts_derive_from_items(self):
        a, b, c = comp("RAM", "R1"), comp("GPU", "G1"), comp("PSU", "P1")
        d = compare_hardware(Build(name="A", component_ids=[a.id, b.id]),
                             Build(name="B", component_ids=[b.id, c.id]),
                             *by_id([a, b, c], []))
        self.assertEqual(d.common_count, sum(1 for i in d.items if i.state == UNCHANGED))
        self.assertEqual(d.added_count, sum(1 for i in d.items if i.state == ADDED))
        self.assertEqual(d.removed_count, sum(1 for i in d.items if i.state == REMOVED))


class TestCompatPairing(unittest.TestCase):
    def _reports(self, attrs_a, attrs_b):
        psu_a, case_a = comp("PSU"), comp("Case")
        ba = Build(name="A", component_ids=[psu_a.id, case_a.id])
        ra = analyze_build_compatibility(ba, [psu_a, case_a], [
            TechnicalProfile(component_id=psu_a.id, attributes=attrs_a[0]),
            TechnicalProfile(component_id=case_a.id, attributes=attrs_a[1])])
        psu_b, case_b = comp("PSU"), comp("Case")
        bb = Build(name="B", component_ids=[psu_b.id, case_b.id])
        rb = analyze_build_compatibility(bb, [psu_b, case_b], [
            TechnicalProfile(component_id=psu_b.id, attributes=attrs_b[0]),
            TechnicalProfile(component_id=case_b.id, attributes=attrs_b[1])])
        comps = {c.id: c for c in (psu_a, case_a, psu_b, case_b)}
        hw = compare_hardware(
            ba, bb, comps,
            {p.component_id: p for p in (
                TechnicalProfile(component_id=psu_a.id, attributes=attrs_a[0]),
                TechnicalProfile(component_id=case_a.id, attributes=attrs_a[1]),
                TechnicalProfile(component_id=psu_b.id, attributes=attrs_b[0]),
                TechnicalProfile(component_id=case_b.id, attributes=attrs_b[1]))})
        return ra, rb, correspondence_from_hardware(hw)

    def test_same_findings(self):
        atx = [va("psu_form_factor", "ATX")]
        sup = [va("supported_psu_form_factors", ["ATX"])]
        ra, rb, corr = self._reports((atx, sup), (atx, sup))
        cd = compare_reports(ra, rb, corr)
        self.assertTrue(all(p.status == "same" for p in cd.pairs if p.key[0] == "psu_case.form_factor"))
        self.assertEqual(cd.new_count, 0)

    def test_regression_demonstrated(self):
        ok_a = ([va("psu_form_factor", "ATX")], [va("supported_psu_form_factors", ["ATX"])])
        bad_b = ([va("psu_form_factor", "ATX")], [va("supported_psu_form_factors", ["SFX"])])
        ra, rb, corr = self._reports(ok_a, bad_b)
        cd = compare_reports(ra, rb, corr)
        regs = [p for p in cd.pairs if p.status in ("new_issue", "changed") and
                (getattr(p.finding_b, "result", "") == "incompatible")]
        self.assertTrue(regs)
        self.assertIn(regs[0].explanation, ("regression_demonstrated", "config_changed"))

    def test_rv_transitions_are_not_demonstrated(self):
        ok = ([va("psu_form_factor", "ATX")], [va("supported_psu_form_factors", ["ATX"])])
        bad = ([va("psu_form_factor", "ATX")], [va("supported_psu_form_factors", ["SFX"])])
        unv = ([va("psu_form_factor", "ATX", verification_status="unverified")],
               [va("supported_psu_form_factors", ["ATX"])])
        # incompatible -> requires_verification: config change, not improvement
        ra, rb, corr = self._reports(bad, unv)
        cd = compare_reports(ra, rb, corr)
        psu = [p for p in cd.pairs if p.key[0] == "psu_case.form_factor"]
        self.assertTrue(psu)
        for p in psu:
            self.assertNotEqual(p.explanation, "improvement_demonstrated")
            self.assertNotEqual(p.explanation, "regression_demonstrated")
        # requires_verification -> incompatible: config change, not regression
        ra, rb, corr = self._reports(unv, bad)
        cd = compare_reports(ra, rb, corr)
        for p in [p for p in cd.pairs if p.key[0] == "psu_case.form_factor"]:
            self.assertNotEqual(p.explanation, "regression_demonstrated")
            self.assertNotEqual(p.explanation, "improvement_demonstrated")
        # incompatible -> compatible: demonstrated improvement
        ra, rb, corr = self._reports(bad, ok)
        cd = compare_reports(ra, rb, corr)
        self.assertIn("improvement_demonstrated",
                      [p.explanation for p in cd.pairs if p.key[0] == "psu_case.form_factor"])
        # compatible -> incompatible: demonstrated regression
        ra, rb, corr = self._reports(ok, bad)
        cd = compare_reports(ra, rb, corr)
        self.assertIn("regression_demonstrated",
                      [p.explanation for p in cd.pairs if p.key[0] == "psu_case.form_factor"])

    def test_resolved_is_not_claimed_improvement_by_default(self):
        bad_a = ([va("psu_form_factor", "ATX")], [va("supported_psu_form_factors", ["SFX"])])
        mise_b = ([], [va("supported_psu_form_factors", ["SFX"])])
        ra, rb, corr = self._reports(bad_a, mise_b)
        cd = compare_reports(ra, rb, corr)
        psu_pairs = [p for p in cd.pairs if p.key[0] == "psu_case.form_factor"]
        self.assertTrue(psu_pairs)
        for p in psu_pairs:
            # missing data on the B side must never read as demonstrated improvement
            self.assertNotEqual(p.explanation, "improvement_demonstrated")

    def test_unpaired_findings_stay_independent(self):
        ok = ([va("psu_form_factor", "ATX")], [va("supported_psu_form_factors", ["ATX"])])
        ra, rb, corr = self._reports(ok, ok)
        # drop a finding from B's tuple to simulate asymmetric scope
        from pc_parts_organizer.compatibility.models import CompatibilityReport
        rb2 = CompatibilityReport(build_id=rb.build_id, overall_result=rb.overall_result,
                                  findings=tuple(f for f in rb.findings if f.rule_id != "psu_case.form_factor"),
                                  ruleset_version=rb.ruleset_version, rules_evaluated=rb.rules_evaluated,
                                  not_evaluated_relations=rb.not_evaluated_relations,
                                  analysis_limitations=rb.analysis_limitations)
        cd = compare_reports(ra, rb2, corr)
        indep = [p for p in cd.pairs if p.status == "resolved" and p.key[0] == "psu_case.form_factor"]
        self.assertTrue(indep)
        self.assertIsNone(indep[0].finding_b)


class TestFindingCorrespondence(unittest.TestCase):
    def _mk(self, rule, cids, result="requires_verification"):
        from pc_parts_organizer.compatibility.models import CompatibilityFinding
        return CompatibilityFinding(rule_id=rule, rule_version="1", result=result,
                                    severity="warning", component_ids=tuple(cids))

    def _rep(self, findings):
        from pc_parts_organizer.compatibility.models import CompatibilityReport
        return CompatibilityReport(build_id="b", overall_result="requires_verification",
                                   findings=tuple(findings), rules_evaluated=len(findings))

    def test_unmapped_same_rule_never_pairs(self):
        # 2xStorage vs 1xStorage -> unknown multiplicity -> no correspondence
        s1, s2, s3 = comp("Storage", "S1"), comp("Storage", "S2"), comp("Storage", "S3")
        from pc_parts_organizer.build_compare import correspondence_from_hardware
        hw = compare_hardware(Build(name="A", component_ids=[s1.id, s2.id]),
                              Build(name="B", component_ids=[s3.id]),
                              *by_id([s1, s2, s3], []))
        corr = correspondence_from_hardware(hw)
        self.assertEqual(corr["pair_of"], {})
        fa = self._mk("storage_case.bay_2_5_capacity", [s1.id])
        fb = self._mk("storage_case.bay_2_5_capacity", [s3.id])
        cd = compare_reports(self._rep([fa]), self._rep([fb]), corr)
        self.assertTrue(all(p.status in ("resolved", "new_issue") for p in cd.pairs))
        self.assertFalse(any(p.finding_a is not None and p.finding_b is not None for p in cd.pairs))

    def test_replaced_participants_pair(self):
        from pc_parts_organizer.build_compare import correspondence_from_hardware
        a, b = comp("GPU", "G1"), comp("GPU", "G2")
        hw = compare_hardware(Build(name="A", component_ids=[a.id]),
                              Build(name="B", component_ids=[b.id]),
                              *by_id([a, b], []))
        corr = correspondence_from_hardware(hw)
        fa = self._mk("gpu_case.max_length", [a.id])
        fb = self._mk("gpu_case.max_length", [b.id])
        cd = compare_reports(self._rep([fa]), self._rep([fb]), corr)
        self.assertEqual(len(cd.pairs), 1)
        self.assertEqual(cd.pairs[0].status, "same")

    def test_participant_order_irrelevant(self):
        from pc_parts_organizer.build_compare import correspondence_from_hardware
        a1, a2, b1, b2 = comp("RAM", "A1"), comp("RAM", "A2"), comp("RAM", "B1"), comp("RAM", "B2")
        comps = {c.id: c for c in (a1, a2, b1, b2)}
        # force two 1:1 pairs via separate categories is impossible; use shared ids
        hw = compare_hardware(Build(name="A", component_ids=[a1.id, a2.id]),
                              Build(name="B", component_ids=[a1.id, a2.id]), comps, {})
        corr = correspondence_from_hardware(hw)
        fa = self._mk("ram_mb.max_capacity", [a2.id, a1.id])
        fb = self._mk("ram_mb.max_capacity", [a1.id, a2.id])
        cd = compare_reports(self._rep([fa]), self._rep([fb]), corr)
        self.assertEqual([(p.status) for p in cd.pairs], ["same"])

    def test_finding_order_irrelevant(self):
        from pc_parts_organizer.build_compare import correspondence_from_hardware
        a, b = comp("GPU", "G1"), comp("GPU", "G2")
        hw = compare_hardware(Build(name="A", component_ids=[a.id]),
                              Build(name="B", component_ids=[b.id]),
                              *by_id([a, b], []))
        corr = correspondence_from_hardware(hw)
        f1a, f2a = self._mk("r.one", [a.id]), self._mk("r.two", [a.id])
        f1b, f2b = self._mk("r.one", [b.id]), self._mk("r.two", [b.id])
        c1 = compare_reports(self._rep([f1a, f2a]), self._rep([f1b, f2b]), corr)
        c2 = compare_reports(self._rep([f2a, f1a]), self._rep([f2b, f1b]), corr)
        self.assertEqual([(p.status, p.key) for p in c1.pairs],
                         [(p.status, p.key) for p in c2.pairs])

    def test_invariants_no_loss_no_dup(self):
        from pc_parts_organizer.build_compare import correspondence_from_hardware
        a, b = comp("GPU", "G1"), comp("GPU", "G2")
        hw = compare_hardware(Build(name="A", component_ids=[a.id]),
                              Build(name="B", component_ids=[b.id]),
                              *by_id([a, b], []))
        corr = correspondence_from_hardware(hw)
        fa = [self._mk("r.one", [a.id]), self._mk("r.two", [a.id])]
        fb = [self._mk("r.one", [b.id])]
        cd = compare_reports(self._rep(fa), self._rep(fb), corr)
        seen_a = [p.finding_a for p in cd.pairs if p.finding_a is not None]
        seen_b = [p.finding_b for p in cd.pairs if p.finding_b is not None]
        self.assertEqual(sorted(map(id, seen_a)), sorted(map(id, fa)))
        self.assertEqual(sorted(map(id, seen_b)), sorted(map(id, fb)))
        self.assertEqual(cd.new_count + cd.resolved_count + cd.changed_count +
                         sum(1 for p in cd.pairs if p.status == "same"), len(cd.pairs))

    def test_multiplicity_pairs_positionally_and_deterministically(self):
        from pc_parts_organizer.build_compare import correspondence_from_hardware
        a, b = comp("GPU", "G1"), comp("GPU", "G2")
        hw = compare_hardware(Build(name="A", component_ids=[a.id]),
                              Build(name="B", component_ids=[b.id]),
                              *by_id([a, b], []))
        corr = correspondence_from_hardware(hw)
        fa = [self._mk("r.one", [a.id], "compatible"), self._mk("r.one", [a.id], "requires_verification")]
        fb = [self._mk("r.one", [b.id], "compatible")]
        c1 = compare_reports(self._rep(fa), self._rep(fb), corr)
        c2 = compare_reports(self._rep(list(reversed(fa))), self._rep(fb), corr)
        self.assertEqual([(p.status, p.explanation) for p in c1.pairs],
                         [(p.status, p.explanation) for p in c2.pairs])
        # 2 vs 1 -> one pair + one leftover, nothing lost
        self.assertEqual(len(c1.pairs), 2)

    def test_default_map_pairs_shared_ids_only(self):
        from pc_parts_organizer.build_compare import correspondence_from_hardware
        a, b = comp("GPU", "G1"), comp("GPU", "G2")
        fa = self._mk("gpu_case.max_length", [a.id])
        fb = self._mk("gpu_case.max_length", [b.id])
        # no explicit map: identical persistent ids still pair; others stay solo
        cd = compare_reports(self._rep([fa]), self._rep([fb]), None)
        self.assertTrue(all(p.status in ("resolved", "new_issue") for p in cd.pairs))
        fc = self._mk("gpu_case.max_length", [a.id])
        cd2 = compare_reports(self._rep([fa]), self._rep([fc]), None)
        self.assertEqual([p.status for p in cd2.pairs], ["same"])

    def test_group_insufficient_vetoes_resolved_and_new(self):
        from pc_parts_organizer.build_compare import correspondence_from_hardware
        g1, g2 = comp("GPU", "G1"), comp("GPU", "G2")
        hw = compare_hardware(Build(name="A", component_ids=[g1.id]),
                              Build(name="B", component_ids=[g1.id, g2.id]),
                              *by_id([g1, g2], []))
        corr = correspondence_from_hardware(hw)
        fa = [self._mk("r.one", [g1.id], "incompatible"), self._mk("r.one", [g1.id], "compatible")]
        fb = [self._mk("r.one", [g1.id], "insufficient_data")]
        cd = compare_reports(self._rep(fa), self._rep(fb), corr)
        by_status = sorted(p.status for p in cd.pairs)
        self.assertEqual(by_status, ["changed", "resolved"])
        for p in cd.pairs:
            self.assertEqual(p.explanation, "info_loss_possible")

    def test_corr_contract_only_demonstrated(self):
        from pc_parts_organizer.build_compare import correspondence_from_hardware
        s1, s2, s3 = comp("Storage", "S1"), comp("Storage", "S2"), comp("Storage", "S3")
        g1, g2 = comp("GPU", "G1"), comp("GPU", "G2")
        comps = {c.id: c for c in (s1, s2, s3, g1, g2)}
        hw = compare_hardware(Build(name="A", component_ids=[s1.id, s2.id, g1.id]),
                              Build(name="B", component_ids=[s3.id, g2.id]), comps, {})
        corr = correspondence_from_hardware(hw)
        # replaced GPU pair maps both directions; unknown storage maps nothing
        self.assertEqual(corr["pair_of"].get(g1.id), g2.id)
        self.assertEqual(corr["pair_of"].get(g2.id), g1.id)
        self.assertNotIn(s1.id, corr["pair_of"])
        self.assertNotIn(s2.id, corr["pair_of"])
        self.assertNotIn(s3.id, corr["pair_of"])


class TestIntegrationService(unittest.TestCase):
    def setUp(self):
        import os, shutil
        from pathlib import Path
        base = Path(os.environ["LOCALAPPDATA"]) / "PCPartsOrganizer"
        if base.exists():
            shutil.rmtree(base)
        from pc_parts_organizer.service import InventoryService
        self.svc = InventoryService()

    def test_compare_reads_fresh_state_no_writes(self):
        from pc_parts_organizer.storage import load_project_state
        from pc_parts_organizer.build_compare import compare_hardware
        a = self.svc.add_component("RAM", "M", "R1", "", "")
        b = self.svc.add_component("RAM", "M", "R2", "", "")
        ba = self.svc.add_build("A")
        bb = self.svc.add_build("B")
        self.svc.add_component_to_build(ba.id, a.id)
        self.svc.add_component_to_build(bb.id, b.id)
        before = load_project_state()
        comps = {c.id: c for c in self.svc.get_components()}
        profs = {p.component_id: p for p in self.svc.get_technical_profiles()}
        d = compare_hardware(self.svc.get_build(ba.id), self.svc.get_build(bb.id), comps, profs)
        self.assertEqual(d.replaced_count, 1)
        after = load_project_state()
        self.assertEqual(len(before.components), len(after.components))
        self.assertEqual(len(before.builds), len(after.builds))
        # edit invalidates: recompute reflects the change
        self.svc.update_component(b.id, "RAM", "M", "R2b", "", "")
        comps2 = {c.id: c for c in self.svc.get_components()}
        d2 = compare_hardware(self.svc.get_build(ba.id), self.svc.get_build(bb.id), comps2, profs)
        self.assertEqual(d2.replaced_count, 1)

    def test_deleted_build_invalidates(self):
        ba = self.svc.add_build("A")
        bb = self.svc.add_build("B")
        self.svc.delete_build(bb.id)
        self.assertIsNone(self.svc.get_build(bb.id))


class TestCompareUI(unittest.TestCase):
    def _tk(self):
        import tkinter as tk
        try:
            root = tk.Tk()
            root.withdraw()
        except tk.TclError as exc:
            self.skipTest(f"Tk unavailable: {exc}")
        return root

    def _data(self):
        from pc_parts_organizer.build_compare import (
            compare_hardware, compare_reports, correspondence_from_hardware)
        a, b = comp("GPU", "G1"), comp("GPU", "G2")
        ba = Build(name="Build A", component_ids=[a.id])
        bb = Build(name="Build B", component_ids=[b.id])
        pa = TechnicalProfile(component_id=a.id, attributes=[va("card_length_mm", 300)])
        comps, profs = {a.id: a, b.id: b}, {a.id: pa}
        hw = compare_hardware(ba, bb, comps, profs)
        ra = analyze_build_compatibility(ba, [a], [pa])
        rb = analyze_build_compatibility(bb, [b], [TechnicalProfile(component_id=b.id, attributes=[])])
        return {"build_a": ba, "build_b": bb, "hardware": hw,
                "report_a": ra, "report_b": rb,
                "compat": compare_reports(ra, rb, correspondence_from_hardware(hw)),
                "components_by_id": comps}

    def test_view_renders_both_languages(self):
        from pc_parts_organizer.localization import Translator
        from pc_parts_organizer.ui.build_compare_view import BuildCompareView
        from pc_parts_organizer.ui.theme import configure_theme
        root = self._tk()
        try:
            configure_theme(root)
            for lang in ("es", "en"):
                tr = Translator()
                tr.set_language(lang)
                v = BuildCompareView(root, tr)
                v.set_comparison(self._data())
                text = v._text.get("1.0", "end")
                self.assertIn("Build A", text)
                self.assertIn("Build B", text)
                self.assertNotIn("{", text.replace("{SFX", "SFX"))
                v.destroy()
        finally:
            root.destroy()

    def test_list_has_compare_button(self):
        from pc_parts_organizer.localization import Translator
        from pc_parts_organizer.ui.build_list_view import BuildListView
        from pc_parts_organizer.ui.theme import configure_theme
        root = self._tk()
        try:
            configure_theme(root)
            tr = Translator()
            v = BuildListView(root, tr, on_compare=lambda: None)
            v.set_builds([Build(name="A"), Build(name="B")])
            self.assertIsNotNone(v.compare_button)
            self.assertEqual(str(v.compare_button["state"]), "normal")
            v.set_builds([Build(name="A")])
            self.assertEqual(str(v.compare_button["state"]), "disabled")
            v.destroy()
        finally:
            root.destroy()

    def test_main_window_compare_flow(self):
        import uuid
        from pc_parts_organizer.localization import Translator
        from pc_parts_organizer.catalog_service import CatalogService
        from pc_parts_organizer.catalog_storage import CatalogStorage
        from pc_parts_organizer.ui.main_window import MainWindow
        from pc_parts_organizer.ui.theme import configure_theme
        root = self._tk()
        try:
            configure_theme(root)
            import os, shutil
            from pathlib import Path
            base = Path(os.environ["LOCALAPPDATA"]) / "PCPartsOrganizer"
            if base.exists():
                shutil.rmtree(base)
            from pc_parts_organizer.service import InventoryService
            svc = InventoryService()
            a = svc.add_component("GPU", "M", "G1", "", "")
            b = svc.add_component("GPU", "M", "G2", "", "")
            ba = svc.add_build("A")
            bb = svc.add_build("B")
            svc.add_component_to_build(ba.id, a.id)
            svc.add_component_to_build(bb.id, b.id)
            tr = Translator()
            win = MainWindow(root, svc, CatalogService(CatalogStorage()), tr)
            from pc_parts_organizer.ui.main_window import NAV_BUILDS
            win._select_notebook_tab(NAV_BUILDS)
            root.update()
            win._show_build_compare(ba.id, bb.id)
            text = win._builds_compare_view._text.get("1.0", "end")
            self.assertIn("G1", text)
            self.assertIn("G2", text)
            # editing a compared component recomputes the visible comparison
            svc.update_component(b.id, "GPU", "M", "G2b", "", "")
            win._refresh_compare_if_visible()
            text2 = win._builds_compare_view._text.get("1.0", "end")
            self.assertIn("G2b", text2)
            # delete B invalidates selection
            svc.delete_build(bb.id)
            win._refresh_compare_if_visible()
            root.destroy()
        finally:
            try:
                root.destroy()
            except Exception:
                pass

    def test_locales_contract(self):
        import json
        from pathlib import Path
        repo = Path(__file__).resolve().parents[1]
        en = json.load(open(repo / "pc_parts_organizer" / "locales" / "en.json", encoding="utf-8"))
        es = json.load(open(repo / "pc_parts_organizer" / "locales" / "es.json", encoding="utf-8"))
        self.assertIn("build_compare", en)
        self.assertIn("build_compare", es)
        self.assertEqual(sorted(en["build_compare"].keys()), sorted(es["build_compare"].keys()))
        self.assertEqual(en["build_compare"]["title"], "Compare builds")
        self.assertIn("builds", en)
        self.assertIn("compare_builds", en["builds"])
        self.assertEqual(en["builds"]["compare_builds"], "Compare builds")


if __name__ == "__main__":
    unittest.main()
