"""Compatibility analysis result models (T17.3). Pure/deterministic; no UI text."""

from __future__ import annotations

from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Any, Mapping

RESULT_COMPATIBLE = "compatible"
RESULT_INCOMPATIBLE = "incompatible"
RESULT_REQUIRES_VERIFICATION = "requires_verification"
RESULT_INSUFFICIENT_DATA = "insufficient_data"
RESULTS = (
    RESULT_COMPATIBLE,
    RESULT_INCOMPATIBLE,
    RESULT_REQUIRES_VERIFICATION,
    RESULT_INSUFFICIENT_DATA,
)

SEVERITY_CRITICAL = "critical"
SEVERITY_WARNING = "warning"
SEVERITY_INFO = "info"
SEVERITIES = (SEVERITY_CRITICAL, SEVERITY_WARNING, SEVERITY_INFO)

ENGINE_RULESET_VERSION = "t17.12-v1"


class CompatibilityValidationError(ValueError):
    """Invalid compatibility input."""


def _freeze(obj: Any) -> Any:
    if isinstance(obj, dict):
        return MappingProxyType({k: _freeze(v) for k, v in sorted(obj.items(), key=lambda kv: str(kv[0]))})
    if isinstance(obj, list):
        return tuple(_freeze(v) for v in obj)
    if isinstance(obj, tuple):
        return tuple(_freeze(v) for v in obj)
    if isinstance(obj, set):
        return tuple(sorted((_freeze(v) for v in obj), key=lambda v: str(v)))
    return obj


@dataclass(frozen=True)
class CompatibilityFinding:
    rule_id: str
    rule_version: str
    result: str
    severity: str
    component_ids: tuple[str, ...] = field(default_factory=tuple)
    attributes_compared: tuple[str, ...] = field(default_factory=tuple)
    evidence: Mapping[str, Any] = field(default_factory=dict)
    message_key: str = ""
    message_params: Mapping[str, Any] = field(default_factory=dict)
    missing_information: tuple[str, ...] = field(default_factory=tuple)
    recommended_action: str = ""

    def __post_init__(self) -> None:
        if self.result not in RESULTS:
            raise CompatibilityValidationError(f"Unknown result: {self.result!r}")
        if self.severity not in SEVERITIES:
            raise CompatibilityValidationError(f"Unknown severity: {self.severity!r}")
        if not isinstance(self.rule_id, str) or not self.rule_id.strip():
            raise CompatibilityValidationError("rule_id is required.")
        if not isinstance(self.rule_version, str) or not self.rule_version.strip():
            raise CompatibilityValidationError("rule_version is required.")
        cids = tuple(str(c) for c in (self.component_ids or ()))
        attrs = tuple(str(a) for a in (self.attributes_compared or ()))
        missing = tuple(str(m) for m in (self.missing_information or ()))
        object.__setattr__(self, "component_ids", cids)
        object.__setattr__(self, "attributes_compared", attrs)
        object.__setattr__(self, "missing_information", missing)
        object.__setattr__(self, "evidence", _freeze(dict(self.evidence or {})))
        object.__setattr__(self, "message_params", _freeze(dict(self.message_params or {})))

    def sort_key(self) -> tuple:
        return (self.result, self.severity, self.rule_id, self.component_ids)


@dataclass(frozen=True)
class CompatibilityReport:
    build_id: str
    overall_result: str
    findings: tuple[CompatibilityFinding, ...] = field(default_factory=tuple)
    ruleset_version: str = ENGINE_RULESET_VERSION
    rules_evaluated: int = 0
    not_evaluated_relations: tuple[Mapping[str, Any], ...] = field(default_factory=tuple)
    analysis_limitations: tuple[str, ...] = field(default_factory=tuple)

    def __post_init__(self) -> None:
        if not isinstance(self.build_id, str) or not self.build_id.strip():
            raise CompatibilityValidationError("build_id is required.")
        if self.overall_result not in RESULTS:
            raise CompatibilityValidationError(f"Unknown overall_result: {self.overall_result!r}")
        findings = tuple(sorted(tuple(self.findings or ()), key=lambda f: f.sort_key()))
        object.__setattr__(self, "findings", findings)
        object.__setattr__(self, "not_evaluated_relations", tuple(_freeze(dict(x)) for x in (self.not_evaluated_relations or ())))
        object.__setattr__(self, "analysis_limitations", tuple(str(x) for x in (self.analysis_limitations or ())))
        if not isinstance(self.rules_evaluated, int) or self.rules_evaluated < 0:
            raise CompatibilityValidationError("rules_evaluated must be a non-negative integer.")
        object.__setattr__(self, "rules_evaluated", int(self.rules_evaluated))
