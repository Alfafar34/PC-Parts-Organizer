"""Tests for compatibility result models (T17.3)."""

from __future__ import annotations

try:
    import tests._pcpo_test_isolation_bootstrap  # noqa: F401
except Exception:
    import _pcpo_test_isolation_bootstrap  # type: ignore  # noqa: F401

import unittest
import uuid

from pc_parts_organizer.compatibility import (
    CompatibilityFinding,
    CompatibilityReport,
    CompatibilityValidationError,
    ENGINE_RULESET_VERSION,
    RESULT_COMPATIBLE,
    RESULT_INCOMPATIBLE,
    RESULT_INSUFFICIENT_DATA,
    RESULT_REQUIRES_VERIFICATION,
    SEVERITY_CRITICAL,
    SEVERITY_INFO,
    SEVERITY_WARNING,
)


class TestCompatibilityModels(unittest.TestCase):
    def test_finding_validation_and_defaults(self) -> None:
        f = CompatibilityFinding(
            rule_id="r1",
            rule_version="1",
            result=RESULT_COMPATIBLE,
            severity=SEVERITY_INFO,
            component_ids=[str(uuid.uuid4())],
            attributes_compared=["a"],
            evidence={"x": 1},
            message_key="k",
            message_params={"p": 2},
        )
        self.assertEqual(f.rule_id, "r1")
        self.assertIsInstance(f.component_ids, tuple)
        self.assertEqual(f.message_key, "k")
        self.assertEqual(f.evidence["x"], 1)

    def test_rejects_invalid_result_and_severity(self) -> None:
        with self.assertRaises(CompatibilityValidationError):
            CompatibilityFinding(rule_id="r", rule_version="1", result="maybe", severity=SEVERITY_INFO)
        with self.assertRaises(CompatibilityValidationError):
            CompatibilityFinding(rule_id="r", rule_version="1", result=RESULT_COMPATIBLE, severity="fatal")

    def test_evidence_and_params_immutable_defensive(self) -> None:
        ev = {"nested": {"a": 1}}
        mp = {"q": [1, 2]}
        f = CompatibilityFinding(
            rule_id="r",
            rule_version="1",
            result=RESULT_INSUFFICIENT_DATA,
            severity=SEVERITY_WARNING,
            evidence=ev,
            message_params=mp,
        )
        ev["nested"]["a"] = 9
        mp["q"].append(3)
        self.assertEqual(f.evidence["nested"]["a"], 1)
        self.assertEqual(tuple(f.message_params["q"]), (1, 2))
        with self.assertRaises(TypeError):
            f.evidence["nested"] = {}  # type: ignore[index]

    def test_report_sorts_findings_deterministically(self) -> None:
        bid = str(uuid.uuid4())
        f2 = CompatibilityFinding(rule_id="b", rule_version="1", result=RESULT_COMPATIBLE, severity=SEVERITY_INFO)
        f1 = CompatibilityFinding(rule_id="a", rule_version="1", result=RESULT_COMPATIBLE, severity=SEVERITY_INFO)
        f3 = CompatibilityFinding(rule_id="a", rule_version="1", result=RESULT_INCOMPATIBLE, severity=SEVERITY_CRITICAL)
        r = CompatibilityReport(build_id=bid, overall_result=RESULT_INCOMPATIBLE, findings=[f2, f3, f1], rules_evaluated=3)
        # stable deterministic key is (result, severity, rule_id, component_ids)
        self.assertEqual([(x.result, x.rule_id) for x in r.findings],
                         [(RESULT_COMPATIBLE, "a"), (RESULT_COMPATIBLE, "b"), (RESULT_INCOMPATIBLE, "a")])
        keys = [f.sort_key() for f in r.findings]
        self.assertEqual(keys, sorted(keys))
        self.assertEqual(r.ruleset_version, ENGINE_RULESET_VERSION)

    def test_report_validation(self) -> None:
        bid = str(uuid.uuid4())
        with self.assertRaises(CompatibilityValidationError):
            CompatibilityReport(build_id=bid, overall_result="ok")
        with self.assertRaises(CompatibilityValidationError):
            CompatibilityReport(build_id="", overall_result=RESULT_COMPATIBLE)
        with self.assertRaises(CompatibilityValidationError):
            CompatibilityReport(build_id=bid, overall_result=RESULT_COMPATIBLE, rules_evaluated=-1)


if __name__ == "__main__":
    unittest.main()
