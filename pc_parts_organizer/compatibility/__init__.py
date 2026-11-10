"""Deterministic compatibility analysis (T17.3)."""

from .engine import analyze_build_compatibility
from .models import (
    ENGINE_RULESET_VERSION,
    RESULT_COMPATIBLE,
    RESULT_INCOMPATIBLE,
    RESULT_INSUFFICIENT_DATA,
    RESULT_REQUIRES_VERIFICATION,
    SEVERITY_CRITICAL,
    SEVERITY_INFO,
    SEVERITY_WARNING,
    CompatibilityFinding,
    CompatibilityReport,
    CompatibilityValidationError,
)

__all__ = [
    "analyze_build_compatibility",
    "CompatibilityFinding",
    "CompatibilityReport",
    "CompatibilityValidationError",
    "ENGINE_RULESET_VERSION",
    "RESULT_COMPATIBLE",
    "RESULT_INCOMPATIBLE",
    "RESULT_REQUIRES_VERIFICATION",
    "RESULT_INSUFFICIENT_DATA",
    "SEVERITY_CRITICAL",
    "SEVERITY_WARNING",
    "SEVERITY_INFO",
]
