"""Technical profiles for PC Parts Organizer (T17.1/T17.2).

Independent structured attributes linked to components by UUID. No parsing of
Component.specifications; no modification of Component.

Versioning (T17.2 policy):
- PROFILE_VERSION / SUPPORTED_PROFILE_STRUCTURAL_VERSIONS: structural shape/version of the
  serialized TechnicalProfile object (v4 `profile_version`). Controls whether the stored
  object can be interpreted structurally.
- PROFILE_REGISTRY_VERSION: version of attribute definitions/validation rules
  (ATTRIBUTE_REGISTRY). A profile is interpretable when its structural version is
  supported and every stored key/value is valid for the component's current category
  under the active registry. New attributes may be added without invalidating old
  profiles (absence is allowed). Removing/replacing keys or changing normalization
  requires explicit, verified migration logic; unknown keys/values fail validation
  (no silent loss). T17.2 makes no schema-v4 migration.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date
from typing import Any
from uuid import UUID

# Structural version of the serialized TechnicalProfile object (v4 field).
PROFILE_VERSION = 2
SUPPORTED_PROFILE_STRUCTURAL_VERSIONS = (1, 2)

SOURCES = ("user_input", "catalog_import", "official_vendor_doc", "normalized_inferred", "unknown")
CONFIDENCE_LEVELS = ("high", "medium", "low")
VERIFICATION_STATUSES = ("verified", "unverified", "needs_review")
COLLECTION_COMPLETENESS = ("unknown", "partial", "complete")
MAX_COMPLETENESS_SCOPE_LENGTH = 300
COMPLETENESS_ELIGIBLE_KEYS = frozenset({"m2_slots", "sata_port_identifiers", "power_cable_assemblies"})
_SOURCE_MAP = {v: v for v in SOURCES}
_CONFIDENCE_MAP = {v: v for v in CONFIDENCE_LEVELS}
_VERIFICATION_MAP = {v.casefold(): v for v in VERIFICATION_STATUSES}

MEMORY_GENERATIONS = ("DDR2", "DDR3", "DDR4", "DDR5")
_MEMGEN_MAP = {v.casefold(): v for v in MEMORY_GENERATIONS}
MODULE_FORM_FACTORS = ("DIMM", "SO-DIMM")
_MODULE_FF_MAP = {v.casefold(): v for v in MODULE_FORM_FACTORS}
MOTHERBOARD_FORM_FACTORS = (
    "ATX",
    "Micro-ATX",
    "Mini-ITX",
    "E-ATX",
    "XL-ATX",
    "Mini-DTX",
    "DTX",
    "FlexATX",
    "Thin Mini-ITX",
    "SSI-CEB",
    "SSI-EEB",
    "Proprietary",
    "Other",
)
_MB_FF_MAP = {v.casefold(): v for v in MOTHERBOARD_FORM_FACTORS}
COOLER_TYPES = (
    "air_cpu_cooler",
    "aio_cpu_cooler",
    "custom_loop_cpu_cooler",
    "case_fan",
    "other",
)
_PSU_FORM_FACTORS = (
    "ATX",
    "SFX",
    "SFX-L",
    "TFX",
    "FlexATX",
    "Proprietary",
    "Other",
)
_PSU_FF_MAP = {v.casefold(): v for v in _PSU_FORM_FACTORS}
PSU_FORM_FACTORS = _PSU_FORM_FACTORS
_COOLER_TYPE_MAP = {v.casefold(): v for v in COOLER_TYPES}
STORAGE_FORM_FACTORS = ("m2", "2_5_in", "3_5_in", "pcie_addin", "other")
_STORAGE_FF_MAP = {v.casefold(): v for v in STORAGE_FORM_FACTORS}
STORAGE_INTERFACES = ("sata", "pcie", "other")
_STORAGE_IFACE_MAP = {v.casefold(): v for v in STORAGE_INTERFACES}
STORAGE_COMMAND_SETS = ("ata", "nvme", "other")
_STORAGE_CMD_MAP = {v.casefold(): v for v in STORAGE_COMMAND_SETS}
M2_KEYINGS = ("B", "M", "B_M", "Other")
_M2_KEYING_MAP = {v.casefold().replace("+", "_").replace("-", "_").replace(" ", "_"): v for v in M2_KEYINGS}
M2_LENGTH_CODES = ("2230", "2242", "2260", "2280", "22110", "Other")
_M2_LENGTH_MAP = {v.casefold(): v for v in M2_LENGTH_CODES}
PCIE_LANES = ("x1", "x2", "x4")
_PCIE_LANES_MAP = {v.casefold().replace("×", "x"): v for v in PCIE_LANES}
MAX_SOCKET_ID_LENGTH = 64
# explicit normalization aliases (documented, conservative)
_MB_FF_ALIASES = {
    "micro atx": "Micro-ATX",
    "microatx": "Micro-ATX",
    "m-atx": "Micro-ATX",
    "matx": "Micro-ATX",
    "mini itx": "Mini-ITX",
    "miniitx": "Mini-ITX",
    "m-itx": "Mini-ITX",
    "mitx": "Mini-ITX",
    "e atx": "E-ATX",
    "eatx": "E-ATX",
    "xl atx": "XL-ATX",
    "xlatx": "XL-ATX",
    "mini dtx": "Mini-DTX",
    "minidtx": "Mini-DTX",
    "thin mini itx": "Thin Mini-ITX",
    "thin mini-itx": "Thin Mini-ITX",
    "thinminiitx": "Thin Mini-ITX",
    "ssi ceb": "SSI-CEB",
    "ssiceb": "SSI-CEB",
    "ssi eeb": "SSI-EEB",
    "ssieeb": "SSI-EEB",
    "flex atx": "FlexATX",
    "flexatx": "FlexATX",
}

_ISO_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
MAX_ORIGINAL_VALUE_LENGTH = 500
MAX_EVIDENCE_REF_LENGTH = 500


def _normalize_collection_completeness(value: object) -> str:
    if value is None:
        return "unknown"
    if not isinstance(value, str):
        raise TechnicalProfileValidationError("collection_completeness must be a string.")
    normalized = value.strip().casefold()
    mapping = {v.casefold(): v for v in COLLECTION_COMPLETENESS}
    canonical = mapping.get(normalized)
    if canonical is None:
        raise TechnicalProfileValidationError(f"Unknown collection_completeness: {value!r}")
    return canonical


def _validate_completeness_policy(key: str, completeness: str, scope: str | None,
                                  verification_status: str, confidence: str,
                                  evidence_ref: str | None, verified_at: str | None) -> None:
    if completeness == "unknown":
        if scope is not None:
            raise TechnicalProfileValidationError(
                "completeness_scope must be empty when collection_completeness is unknown.")
        return
    if key not in COMPLETENESS_ELIGIBLE_KEYS:
        raise TechnicalProfileValidationError(
            f"collection_completeness is not supported for attribute {key!r}.")
    if scope is None:
        raise TechnicalProfileValidationError(
            "completeness_scope is required when collection_completeness is partial or complete.")
    if completeness == "complete":
        if verification_status != "verified":
            raise TechnicalProfileValidationError(
                "collection_completeness=complete requires verification_status=verified.")
        if confidence != "high":
            raise TechnicalProfileValidationError(
                "collection_completeness=complete requires confidence=high.")
        if not evidence_ref:
            raise TechnicalProfileValidationError(
                "collection_completeness=complete requires a non-empty evidence_ref.")
        if not verified_at:
            raise TechnicalProfileValidationError(
                "collection_completeness=complete requires a valid verified_at date.")


class TechnicalProfileValidationError(ValueError):
    """Raised when technical profile data is invalid."""


def _normalize_uuid(value: object, field_name: str) -> str:
    if isinstance(value, UUID):
        candidate = value
    elif isinstance(value, str):
        try:
            candidate = UUID(value)
        except (ValueError, AttributeError, TypeError) as exc:
            raise TechnicalProfileValidationError(f"{field_name} must be a valid UUID v4.") from exc
    else:
        raise TechnicalProfileValidationError(f"{field_name} must be a UUID v4 string or UUID object.")
    if candidate.version != 4:
        raise TechnicalProfileValidationError(f"{field_name} must be a valid UUID v4.")
    return str(candidate)


def _normalize_key(value: object) -> str:
    if not isinstance(value, str):
        raise TechnicalProfileValidationError("key must be a string.")
    normalized = value.strip()
    if not normalized:
        raise TechnicalProfileValidationError("key is required.")
    return normalized


def _normalize_source(value: object) -> str:
    if not isinstance(value, str):
        raise TechnicalProfileValidationError("source must be a string.")
    normalized = value.strip()
    if normalized not in _SOURCE_MAP:
        raise TechnicalProfileValidationError(f"Unknown source: {normalized!r}")
    return _SOURCE_MAP[normalized]


def _normalize_confidence(value: object) -> str:
    if not isinstance(value, str):
        raise TechnicalProfileValidationError("confidence must be a string.")
    normalized = value.strip()
    if normalized not in _CONFIDENCE_MAP:
        raise TechnicalProfileValidationError(f"Unknown confidence: {normalized!r}")
    return _CONFIDENCE_MAP[normalized]


def _normalize_verification_status(value: object) -> str:
    if not isinstance(value, str):
        raise TechnicalProfileValidationError("verification_status must be a string.")
    normalized = value.strip()
    if not normalized:
        raise TechnicalProfileValidationError("verification_status is required.")
    canonical = _VERIFICATION_MAP.get(normalized.casefold())
    if canonical is None:
        raise TechnicalProfileValidationError(f"Unknown verification_status: {normalized!r}")
    return canonical


def _normalize_optional_text(value: object, field_name: str, max_length: int) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise TechnicalProfileValidationError(f"{field_name} must be a string or None.")
    normalized = value.strip()
    if not normalized:
        return None
    if len(normalized) > max_length:
        raise TechnicalProfileValidationError(f"{field_name} must be at most {max_length} characters.")
    return normalized


def _normalize_optional_iso_date(value: object, field_name: str) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise TechnicalProfileValidationError(f"{field_name} must be a string or None.")
    normalized = value.strip()
    if not normalized:
        return None
    if not _ISO_DATE_RE.fullmatch(normalized):
        raise TechnicalProfileValidationError(f"{field_name} must be in YYYY-MM-DD format.")
    try:
        date.fromisoformat(normalized)
    except ValueError as exc:
        raise TechnicalProfileValidationError(f"{field_name} must be a valid calendar date.") from exc
    return normalized


def _validate_verification_policy(verification_status: str, evidence_ref: str | None, verified_at: str | None) -> None:
    if verification_status == "verified":
        if not evidence_ref:
            raise TechnicalProfileValidationError("verified attributes require a non-empty evidence_ref.")
        if not verified_at:
            raise TechnicalProfileValidationError("verified attributes require a valid verified_at date.")


def _normalize_unit(value: object, allowed: tuple[str | None, ...], key: str) -> str | None:
    if value is None:
        if None not in allowed:
            raise TechnicalProfileValidationError(f"unit is required for {key}.")
        return None
    if not isinstance(value, str):
        raise TechnicalProfileValidationError("unit must be a string or None.")
    normalized = value.strip()
    if not normalized:
        if None not in allowed:
            raise TechnicalProfileValidationError(f"unit is required for {key}.")
        return None
    if normalized not in allowed:
        raise TechnicalProfileValidationError(f"Invalid unit for {key}: {normalized!r}")
    return normalized


def _reject_bad_number(value: Any, key: str) -> None:
    # bool is subclass of int; reject
    if isinstance(value, bool):
        raise TechnicalProfileValidationError(f"{key} must not be a boolean.")


def _normalize_positive_int(value: object, key: str) -> int:
    _reject_bad_number(value, key)
    if not isinstance(value, int):
        raise TechnicalProfileValidationError(f"{key} must be an integer.")
    if value <= 0:
        raise TechnicalProfileValidationError(f"{key} must be a positive integer.")
    # no NaN/inf possible for int, but be defensive
    return value


def _normalize_non_negative_int(value: object, key: str) -> int:
    _reject_bad_number(value, key)
    if not isinstance(value, int):
        raise TechnicalProfileValidationError(f"{key} must be an integer.")
    if value < 0:
        raise TechnicalProfileValidationError(f"{key} must be a non-negative integer.")
    return value


def _normalize_cooler_type(value: object, key: str) -> str:
    if not isinstance(value, str):
        raise TechnicalProfileValidationError(f"{key} must be a string.")
    normalized = value.strip()
    canonical = _COOLER_TYPE_MAP.get(normalized.casefold())
    if canonical is None:
        raise TechnicalProfileValidationError(f"Invalid {key}: {normalized!r}")
    return canonical


def _normalize_storage_form_factor(value: object, key: str) -> str:
    if not isinstance(value, str):
        raise TechnicalProfileValidationError(f"{key} must be a string.")
    canonical = _STORAGE_FF_MAP.get(value.strip().casefold())
    if canonical is None:
        raise TechnicalProfileValidationError(f"Invalid {key}: {value!r}")
    return canonical


def _normalize_storage_interface(value: object, key: str) -> str:
    if not isinstance(value, str):
        raise TechnicalProfileValidationError(f"{key} must be a string.")
    canonical = _STORAGE_IFACE_MAP.get(value.strip().casefold())
    if canonical is None:
        raise TechnicalProfileValidationError(f"Invalid {key}: {value!r}")
    return canonical


def _normalize_storage_command_set(value: object, key: str) -> str:
    if not isinstance(value, str):
        raise TechnicalProfileValidationError(f"{key} must be a string.")
    canonical = _STORAGE_CMD_MAP.get(value.strip().casefold())
    if canonical is None:
        raise TechnicalProfileValidationError(f"Invalid {key}: {value!r}")
    return canonical


def _normalize_m2_keying(value: object, key: str) -> str:
    if not isinstance(value, str):
        raise TechnicalProfileValidationError(f"{key} must be a string.")
    norm = value.strip().casefold().replace("+", "_").replace("-", "_").replace(" ", "_")
    canonical = _M2_KEYING_MAP.get(norm)
    if canonical is None:
        raise TechnicalProfileValidationError(f"Invalid {key}: {value!r}")
    return canonical


def _normalize_m2_length_code(value: object, key: str) -> str:
    if not isinstance(value, str):
        raise TechnicalProfileValidationError(f"{key} must be a string.")
    canonical = _M2_LENGTH_MAP.get(value.strip().casefold())
    if canonical is None:
        raise TechnicalProfileValidationError(f"Invalid {key}: {value!r}")
    return canonical


def _normalize_pcie_lanes(value: object, key: str) -> str:
    if not isinstance(value, str):
        raise TechnicalProfileValidationError(f"{key} must be a string.")
    canonical = _PCIE_LANES_MAP.get(value.strip().casefold().replace("×", "x"))
    if canonical is None:
        raise TechnicalProfileValidationError(f"Invalid {key}: {value!r}")
    return canonical


def _normalize_socket_identifier(value: object, key: str) -> str:
    """Normalize a CPU socket designation to a stable canonical form.

    Conservative: strip outer whitespace, uppercase, collapse internal whitespace to
    single spaces. No aliases/equivalences between different sockets.
    """
    if not isinstance(value, str):
        raise TechnicalProfileValidationError(f"{key} must be a string.")
    raw = value.strip()
    if not raw:
        raise TechnicalProfileValidationError(f"{key} value is required.")
    if len(raw) > MAX_SOCKET_ID_LENGTH:
        raise TechnicalProfileValidationError(f"{key} must be at most {MAX_SOCKET_ID_LENGTH} characters.")
    if any((not ch.isprintable()) or ord(ch) < 32 for ch in raw):
        raise TechnicalProfileValidationError(f"{key} contains invalid control characters.")
    canonical = " ".join(raw.split()).upper()
    if not canonical:
        raise TechnicalProfileValidationError(f"{key} value is required.")
    return canonical


def _normalize_socket_identifier_list(value: object, key: str) -> list[str]:
    if not isinstance(value, (list, tuple)):
        raise TechnicalProfileValidationError(f"{key} must be a list.")
    if len(value) == 0:
        raise TechnicalProfileValidationError(f"{key} must not be empty.")
    normalized = [_normalize_socket_identifier(item, key) for item in value]
    seen: set[str] = set()
    deduped: list[str] = []
    for item in normalized:
        if item in seen:
            raise TechnicalProfileValidationError(f"{key} must not contain duplicates.")
        seen.add(item)
        deduped.append(item)
    return sorted(deduped)


def _normalize_memory_generation(value: object, key: str) -> str:
    if not isinstance(value, str):
        raise TechnicalProfileValidationError(f"{key} must be a string.")
    normalized = value.strip()
    canonical = _MEMGEN_MAP.get(normalized.casefold())
    if canonical is None:
        raise TechnicalProfileValidationError(f"Invalid {key}: {normalized!r}")
    return canonical


def _normalize_module_form_factor(value: object, key: str) -> str:
    if not isinstance(value, str):
        raise TechnicalProfileValidationError(f"{key} must be a string.")
    normalized = value.strip()
    canonical = _MODULE_FF_MAP.get(normalized.casefold())
    if canonical is None:
        raise TechnicalProfileValidationError(f"Invalid {key}: {normalized!r}")
    return canonical


def _normalize_motherboard_form_factor(value: object, key: str) -> str:
    if not isinstance(value, str):
        raise TechnicalProfileValidationError(f"{key} must be a string.")
    raw = value.strip()
    if not raw:
        raise TechnicalProfileValidationError(f"{key} value is required.")
    canonical = _MB_FF_MAP.get(raw.casefold())
    if canonical is not None:
        return canonical
    alias = _MB_FF_ALIASES.get(raw.strip().casefold().replace("_", " "))
    if alias is not None:
        return alias
    # Do not coerce unknown to a known format. Allow only registered values.
    raise TechnicalProfileValidationError(f"Invalid {key}: {raw!r}")


def _normalize_psu_form_factor(value: object, key: str) -> str:
    # Closed vocabulary, no aliases or equivalences (SFX != SFX-L).
    if not isinstance(value, str):
        raise TechnicalProfileValidationError(f"{key} must be a string.")
    raw = value.strip()
    if not raw:
        raise TechnicalProfileValidationError(f"{key} value is required.")
    canonical = _PSU_FF_MAP.get(raw.casefold())
    if canonical is None:
        raise TechnicalProfileValidationError(f"Invalid {key}: {raw!r}")
    return canonical


def _normalize_port_identifier_list(value: object, key: str) -> list[str]:
    if not isinstance(value, (list, tuple)):
        raise TechnicalProfileValidationError(f"{key} must be a list.")
    if len(value) == 0:
        raise TechnicalProfileValidationError(f"{key} must not be empty.")
    seen: set[str] = set()
    out: list[str] = []
    for item in value:
        v = _normalize_exact_identifier(item, key)
        if v in seen:
            raise TechnicalProfileValidationError(f"{key} must not contain duplicates.")
        seen.add(v)
        out.append(v)
    return sorted(out)


def _normalize_enum_list(value: object, key: str, normalizer) -> list[str]:
    if not isinstance(value, (list, tuple)):
        raise TechnicalProfileValidationError(f"{key} must be a list.")
    if len(value) == 0:
        raise TechnicalProfileValidationError(f"{key} must not be empty.")
    normalized = [normalizer(item, key) for item in value]
    # no duplicates
    seen: set[str] = set()
    deduped: list[str] = []
    for item in normalized:
        if item in seen:
            raise TechnicalProfileValidationError(f"{key} must not contain duplicates.")
        seen.add(item)
        deduped.append(item)
    return sorted(deduped)


@dataclass(frozen=True)
class AttributeSpec:
    key: str
    value_type: str  # enum|int|int_non_negative|enum_list|identifier|identifier_list|typed_object_list
    allowed_units: tuple[str | None, ...]
    enum_values: tuple[str, ...] | None = None
    normalizer: Any = None
    schema_id: str | None = None
    object_schema_version: int | None = None
    allows_completeness: bool = False


def _make_registry() -> dict[str, dict[str, AttributeSpec]]:
    ram = {
        "memory_generation": AttributeSpec("memory_generation", "enum", (None,), MEMORY_GENERATIONS, _normalize_memory_generation),
        "module_form_factor": AttributeSpec("module_form_factor", "enum", (None,), MODULE_FORM_FACTORS, _normalize_module_form_factor),
        "total_capacity_gb": AttributeSpec("total_capacity_gb", "int", ("GB", None), None, _normalize_positive_int),
        "module_count": AttributeSpec("module_count", "int", (None,), None, _normalize_positive_int),
    }
    motherboard = {
        "form_factor": AttributeSpec("form_factor", "enum", (None,), MOTHERBOARD_FORM_FACTORS, _normalize_motherboard_form_factor),
        "supported_memory_generations": AttributeSpec("supported_memory_generations", "enum_list", (None,), MEMORY_GENERATIONS, lambda v, k: _normalize_enum_list(v, k, _normalize_memory_generation)),
        "supported_memory_module_form_factors": AttributeSpec("supported_memory_module_form_factors", "enum_list", (None,), MODULE_FORM_FACTORS, lambda v, k: _normalize_enum_list(v, k, _normalize_module_form_factor)),
        "memory_slot_count": AttributeSpec("memory_slot_count", "int", (None,), None, _normalize_positive_int),
        "max_memory_capacity_gb": AttributeSpec("max_memory_capacity_gb", "int", ("GB", None), None, _normalize_positive_int),
        "sata_port_count": AttributeSpec("sata_port_count", "int_non_negative", (None,), None, _normalize_non_negative_int),
        "sata_port_identifiers": AttributeSpec("sata_port_identifiers", "identifier_list", (None,), None, _normalize_port_identifier_list, allows_completeness=True),
        "socket_designation": AttributeSpec("socket_designation", "identifier", (None,), None, _normalize_socket_identifier),
        "m2_slots": AttributeSpec("m2_slots", "typed_object_list", (None,), None, lambda v, k: _normalize_typed_object_list(v, k, M2SlotSpec), "M2SlotSpec", 1, True),
        "motherboard_power_connectors_required": AttributeSpec("motherboard_power_connectors_required", "typed_object_list", (None,), None, lambda v, k: _normalize_typed_object_list(v, k, PowerConnectorRequirement), "PowerConnectorRequirement", 1),
    }
    case = {
        "supported_motherboard_form_factors": AttributeSpec("supported_motherboard_form_factors", "enum_list", (None,), MOTHERBOARD_FORM_FACTORS, lambda v, k: _normalize_enum_list(v, k, _normalize_motherboard_form_factor)),
        "supported_psu_form_factors": AttributeSpec("supported_psu_form_factors", "enum_list", (None,), PSU_FORM_FACTORS, lambda v, k: _normalize_enum_list(v, k, _normalize_psu_form_factor)),
        "max_gpu_length_mm": AttributeSpec("max_gpu_length_mm", "int", ("mm", None), None, _normalize_positive_int),
        "max_cpu_cooler_height_mm": AttributeSpec("max_cpu_cooler_height_mm", "int", ("mm", None), None, _normalize_positive_int),
        "bay_2_5_total": AttributeSpec("bay_2_5_total", "int_non_negative", (None,), None, _normalize_non_negative_int),
        "bay_3_5_total": AttributeSpec("bay_3_5_total", "int_non_negative", (None,), None, _normalize_non_negative_int),
    }
    cpu = {
        "socket_designation": AttributeSpec("socket_designation", "identifier", (None,), None, _normalize_socket_identifier),
    }
    gpu = {
        "card_length_mm": AttributeSpec("card_length_mm", "int", ("mm", None), None, _normalize_positive_int),
        "recommended_psu_power_w": AttributeSpec("recommended_psu_power_w", "int", ("W", None), None, _normalize_positive_int),
        "gpu_power_connectors_required": AttributeSpec("gpu_power_connectors_required", "typed_object_list", (None,), None, lambda v, k: _normalize_typed_object_list(v, k, PowerConnectorRequirement), "PowerConnectorRequirement", 1),
    }
    cooling = {
        "cooler_type": AttributeSpec("cooler_type", "enum", (None,), COOLER_TYPES, _normalize_cooler_type),
        "supported_cpu_sockets": AttributeSpec("supported_cpu_sockets", "identifier_list", (None,), None, _normalize_socket_identifier_list),
        "cooler_height_mm": AttributeSpec("cooler_height_mm", "int", ("mm", None), None, _normalize_positive_int),
    }
    storage = {
        "storage_form_factor": AttributeSpec("storage_form_factor", "enum", (None,), STORAGE_FORM_FACTORS, _normalize_storage_form_factor),
        "storage_interface": AttributeSpec("storage_interface", "enum", (None,), STORAGE_INTERFACES, _normalize_storage_interface),
        "storage_command_set": AttributeSpec("storage_command_set", "enum", (None,), STORAGE_COMMAND_SETS, _normalize_storage_command_set),
        "m2_keying": AttributeSpec("m2_keying", "enum", (None,), M2_KEYINGS, _normalize_m2_keying),
        "m2_length_code": AttributeSpec("m2_length_code", "enum", (None,), M2_LENGTH_CODES, _normalize_m2_length_code),
        "pcie_generation": AttributeSpec("pcie_generation", "int", (None,), None, _normalize_positive_int),
        "pcie_lanes": AttributeSpec("pcie_lanes", "enum", (None,), PCIE_LANES, _normalize_pcie_lanes),
    }
    psu = {
        "rated_continuous_power_w": AttributeSpec("rated_continuous_power_w", "int", ("W", None), None, _normalize_positive_int),
        "psu_form_factor": AttributeSpec("psu_form_factor", "enum", (None,), PSU_FORM_FACTORS, _normalize_psu_form_factor),
        "power_cable_assemblies": AttributeSpec("power_cable_assemblies", "typed_object_list", (None,), None, lambda v, k: _normalize_typed_object_list(v, k, PowerCableAssembly), "PowerCableAssembly", 1, True),
    }
    return {
        "RAM": ram, "Motherboard": motherboard, "Case": case, "CPU": cpu, "GPU": gpu,
        "Cooling": cooling, "Storage": storage, "PSU": psu,
    }


ATTRIBUTE_REGISTRY: dict[str, dict[str, AttributeSpec]] = _make_registry()
PROFILE_REGISTRY_VERSION = 7

# key -> spec (keys are unique across initial registry; generic normalization helper)
_KEY_SPECS: dict[str, AttributeSpec] = {}
_KEY_CATEGORY: dict[str, str] = {}
for _cat, _cat_specs in ATTRIBUTE_REGISTRY.items():
    for _k, _spec in _cat_specs.items():
        _KEY_SPECS.setdefault(_k, _spec)
        _KEY_CATEGORY.setdefault(_k, _cat)


def _spec_category_for_key(key: str) -> str:
    category = _KEY_CATEGORY.get(key)
    if category is None:
        raise TechnicalProfileValidationError(f"Unknown technical attribute key: {key!r}")
    return category


def allowed_categories() -> tuple[str, ...]:
    return tuple(sorted(ATTRIBUTE_REGISTRY.keys()))


def allowed_keys_for_category(category: str) -> tuple[str, ...]:
    specs = ATTRIBUTE_REGISTRY.get(category)
    if specs is None:
        return ()
    return tuple(sorted(specs.keys()))


def validate_attribute_value(category: str, key: str, value: object, unit: object) -> tuple[Any, str | None]:
    specs = ATTRIBUTE_REGISTRY.get(category)
    if specs is None:
        raise TechnicalProfileValidationError(f"Category has no technical attribute registry: {category!r}")
    spec = specs.get(key)
    if spec is None:
        raise TechnicalProfileValidationError(f"Attribute key {key!r} is not allowed for category {category!r}.")
    normalized_unit = _normalize_unit(unit, spec.allowed_units, key)
    normalized_value = spec.normalizer(value, key)
    return normalized_value, normalized_unit


ATTRIBUTE_KEYS = {"key", "value", "unit", "original_value", "source", "confidence", "verification_status", "evidence_ref", "verified_at", "collection_completeness", "completeness_scope"}
PROFILE_KEYS = {"component_id", "profile_version", "attributes"}


@dataclass
class TechnicalAttribute:
    key: str
    value: Any
    unit: str | None = None
    original_value: str | None = None
    source: str = "user_input"
    confidence: str = "medium"
    verification_status: str = "unverified"
    evidence_ref: str | None = None
    verified_at: str | None = None
    collection_completeness: str = "unknown"
    completeness_scope: str | None = None

    def __post_init__(self) -> None:
        self.key = _normalize_key(self.key)
        self.source = _normalize_source(self.source)
        self.confidence = _normalize_confidence(self.confidence)
        self.verification_status = _normalize_verification_status(self.verification_status)
        self.collection_completeness = _normalize_collection_completeness(self.collection_completeness)
        self.original_value = _normalize_optional_text(self.original_value, "original_value", MAX_ORIGINAL_VALUE_LENGTH)
        self.evidence_ref = _normalize_optional_text(self.evidence_ref, "evidence_ref", MAX_EVIDENCE_REF_LENGTH)
        self.verified_at = _normalize_optional_iso_date(self.verified_at, "verified_at")
        self.completeness_scope = _normalize_optional_text(self.completeness_scope, "completeness_scope", MAX_COMPLETENESS_SCOPE_LENGTH)
        _validate_verification_policy(self.verification_status, self.evidence_ref, self.verified_at)
        _validate_completeness_policy(self.key, self.collection_completeness, self.completeness_scope,
                                      self.verification_status, self.confidence, self.evidence_ref, self.verified_at)
        # reject NaN/inf floats explicitly
        if isinstance(self.value, float):
            import math

            if math.isnan(self.value) or math.isinf(self.value):
                raise TechnicalProfileValidationError(f"{self.key} must not be NaN or infinite.")
        spec = _KEY_SPECS.get(self.key)
        if spec is not None:
            self.value, self.unit = validate_attribute_value(_spec_category_for_key(self.key), self.key, self.value, self.unit)
        else:
            raise TechnicalProfileValidationError(f"Unknown technical attribute key: {self.key!r}")
        # defensive copy / normalization for list values (including typed objects)
        if isinstance(self.value, tuple):
            self.value = list(self.value)
        elif isinstance(self.value, list):
            self.value = list(self.value)
        if isinstance(self.value, list):
            self.value = [v.copy() if hasattr(v, "copy") and hasattr(v, "to_dict") and not isinstance(v, (str, int, float, bool, dict)) else v for v in self.value]

    def copy(self) -> "TechnicalAttribute":
        val = self.value
        if isinstance(val, list):
            val = [v.copy() if hasattr(v, "copy") and hasattr(v, "to_dict") and not isinstance(v, (str, int, float, bool, dict)) else (list(v) if isinstance(v, list) else v) for v in val]
        return TechnicalAttribute(
            key=self.key,
            value=val,
            unit=self.unit,
            original_value=self.original_value,
            source=self.source,
            confidence=self.confidence,
            verification_status=self.verification_status,
            evidence_ref=self.evidence_ref,
            verified_at=self.verified_at,
            collection_completeness=self.collection_completeness,
            completeness_scope=self.completeness_scope,
        )

    def to_dict(self) -> dict[str, Any]:
        val = self.value
        if isinstance(val, list):
            val = [v.to_dict() if hasattr(v, "to_dict") and not isinstance(v, (str, int, float, bool, dict)) else v for v in val]
        return {
            "key": self.key,
            "value": val,
            "unit": self.unit,
            "original_value": self.original_value,
            "source": self.source,
            "confidence": self.confidence,
            "verification_status": self.verification_status,
            "evidence_ref": self.evidence_ref,
            "verified_at": self.verified_at,
            "collection_completeness": self.collection_completeness,
            "completeness_scope": self.completeness_scope,
        }


@dataclass
class TechnicalProfile:
    component_id: str | UUID
    attributes: list[TechnicalAttribute] | tuple[TechnicalAttribute, ...] | None = field(default_factory=list)
    profile_version: int = PROFILE_VERSION

    def __post_init__(self) -> None:
        self.component_id = _normalize_uuid(self.component_id, "component_id")
        if isinstance(self.profile_version, bool) or not isinstance(self.profile_version, int) or self.profile_version not in SUPPORTED_PROFILE_STRUCTURAL_VERSIONS:
            raise TechnicalProfileValidationError(
                f"profile_version must be one of {SUPPORTED_PROFILE_STRUCTURAL_VERSIONS}."
            )
        self.profile_version = int(self.profile_version)
        attrs = self.attributes if self.attributes is not None else []
        if not isinstance(attrs, (list, tuple)):
            raise TechnicalProfileValidationError("attributes must be a list.")
        normalized: list[TechnicalAttribute] = []
        seen: set[str] = set()
        for index, item in enumerate(attrs):
            if not isinstance(item, TechnicalAttribute):
                raise TechnicalProfileValidationError(f"attributes[{index}] must be a TechnicalAttribute.")
            if item.key in seen:
                raise TechnicalProfileValidationError(f"attributes contains duplicate key: {item.key}")
            seen.add(item.key)
            normalized.append(item.copy())
        # deterministic order by key
        normalized.sort(key=lambda a: a.key)
        self.attributes = normalized

    def copy(self) -> "TechnicalProfile":
        return TechnicalProfile(
            component_id=self.component_id,
            profile_version=self.profile_version,
            attributes=[a.copy() for a in self.attributes],
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "component_id": self.component_id,
            "profile_version": self.profile_version,
            "attributes": [a.to_dict() for a in self.attributes],
        }


def _attr_value(attrs: list[TechnicalAttribute], key: str):
    for a in attrs:
        if a.key == key:
            return a.value
    return None


def _validate_profile_cross_attributes(category: str, attrs: list[TechnicalAttribute]) -> None:
    if category == "Storage":
        form_factor = _attr_value(attrs, "storage_form_factor")
        interface = _attr_value(attrs, "storage_interface")
        command_set = _attr_value(attrs, "storage_command_set")
        # Interface/command set coherence for supported modalities. Values 'other' do not
        # allow confirmed compatibility, but do not create a hard contradiction here.
        if isinstance(interface, str) and isinstance(command_set, str):
            if interface in ("sata", "pcie") and command_set in ("ata", "nvme"):
                if (interface, command_set) not in (("sata", "ata"), ("pcie", "nvme")):
                    raise TechnicalProfileValidationError(
                        "Storage interface/command set combination is not coherent for supported modalities."
                    )
        # M.2-specific attributes only when form factor is M.2; reject if another known format declared.
        has_m2_attrs = _attr_value(attrs, "m2_keying") is not None or _attr_value(attrs, "m2_length_code") is not None
        if has_m2_attrs and isinstance(form_factor, str) and form_factor in ("2_5_in", "3_5_in", "pcie_addin"):
            raise TechnicalProfileValidationError("M.2 keying/length attributes are only valid when storage_form_factor is m2.")
        # PCIe characteristics are only meaningful for PCIe interface; reject when interface explicitly SATA.
        has_pcie_attrs = _attr_value(attrs, "pcie_generation") is not None or _attr_value(attrs, "pcie_lanes") is not None
        if has_pcie_attrs and interface == "sata":
            raise TechnicalProfileValidationError("PCIe generation/lanes attributes are not valid when storage_interface is sata.")
        return
    if category == "Motherboard":
        sata_count = _attr_value(attrs, "sata_port_count")
        sata_ids = _attr_value(attrs, "sata_port_identifiers")
        if isinstance(sata_ids, (list, tuple)) and isinstance(sata_count, int):
            # sata_port_identifiers represents all known ports on the board when provided with count coherence expectation.
            # A partial inventory is explicitly incomplete, so its length may differ from the scalar total.
            ids_attr = next((a for a in attrs if a.key == "sata_port_identifiers"), None)
            ids_partial = ids_attr is not None and getattr(ids_attr, "collection_completeness", "unknown") == "partial"
            if not ids_partial and len(sata_ids) != sata_count:
                raise TechnicalProfileValidationError("sata_port_identifiers count must match sata_port_count when both are provided.")
        known_ids = set(sata_ids) if isinstance(sata_ids, (list, tuple)) else None
        m2_slots = _attr_value(attrs, "m2_slots")
        if known_ids is not None and isinstance(m2_slots, (list, tuple)):
            ids_attr = next((a for a in attrs if a.key == "sata_port_identifiers"), None)
            ids_complete = ids_attr is not None and getattr(ids_attr, "collection_completeness", "unknown") == "complete"
            if ids_complete:
                for slot in m2_slots:
                    for pid in getattr(slot, "disables_sata_port_ids", ()) or ():
                        if pid not in known_ids:
                            raise TechnicalProfileValidationError(f"M.2 slot disables unknown SATA port identifier: {pid!r}")
        return


# --- T17.7b typed object schemas (immutable, strict, no arbitrary dicts) ---

MAX_ID_LENGTH = 64
MAX_NOTES_LENGTH = 500
M2_MODULE_KEYINGS = ("B", "M", "B_M")
M2_MODULE_KEYING_MAP = {v.casefold().replace("+", "_").replace("-", "_"): v for v in M2_MODULE_KEYINGS}
M2_SLOT_LENGTHS = ("2230", "2242", "2260", "2280", "22110", "other")
M2_SLOT_LENGTH_MAP = {v.casefold(): v for v in M2_SLOT_LENGTHS}
M2_SUPPORTED_MODES = ("sata_ata", "pcie_nvme")
M2_SUPPORTED_MODE_MAP = {v.casefold().replace(" ", "_").replace("-", "_"): v for v in M2_SUPPORTED_MODES}
M2_ROUTED_TO = ("unknown", "cpu", "chipset")
M2_ROUTED_TO_MAP = {v.casefold(): v for v in M2_ROUTED_TO}
M2_PCIE_LANES_MAX = ("x1", "x2", "x4")
M2_PCIE_LANES_MAX_MAP = {v.casefold().replace("×", "x"): v for v in M2_PCIE_LANES_MAX}
POWER_CONNECTOR_KINDS = ("ATX_20", "ATX_24", "EPS_4", "EPS_8", "PCIE_6", "PCIE_8", "12VHPWR", "12V_2x6")
_POWER_CONNECTOR_KIND_MAP = {v.casefold().replace("-", "_"): v for v in POWER_CONNECTOR_KINDS}
CABLE_ASSEMBLY_TYPES = ("fixed_native", "modular_native", "manufacturer_approved_adapter", "third_party_adapter", "unknown")
_CABLE_ASSEMBLY_TYPE_MAP = {v.casefold(): v for v in CABLE_ASSEMBLY_TYPES}


def _typed_keys(item: object, index: int, schema: str, allowed: set[str], required: set[str] | None = None) -> dict:
    if not isinstance(item, dict):
        raise TechnicalProfileValidationError(f"{schema} at index {index} must be an object.")
    unknown = set(item) - allowed
    if unknown:
        raise TechnicalProfileValidationError(f"{schema} at index {index} has unknown keys: {', '.join(sorted(unknown))}.")
    missing = (required or set()) - set(item)
    if missing:
        raise TechnicalProfileValidationError(f"{schema} at index {index} is missing required keys: {', '.join(sorted(missing))}.")
    return item


def _normalize_exact_identifier(value: object, field: str, *, max_len: int = MAX_ID_LENGTH) -> str:
    if not isinstance(value, str):
        raise TechnicalProfileValidationError(f"{field} must be a string.")
    raw = value.strip()
    if not raw:
        raise TechnicalProfileValidationError(f"{field} is required.")
    if len(raw) > max_len:
        raise TechnicalProfileValidationError(f"{field} must be at most {max_len} characters.")
    if any((not ch.isprintable()) or ord(ch) < 32 for ch in raw):
        raise TechnicalProfileValidationError(f"{field} contains invalid control characters.")
    return raw


def _normalize_exact_identifier_list(value: object, field: str, *, allow_empty: bool = False) -> tuple[str, ...]:
    if not isinstance(value, (list, tuple)):
        raise TechnicalProfileValidationError(f"{field} must be a list.")
    out: list[str] = []
    seen: set[str] = set()
    for i, item in enumerate(value):
        v = _normalize_exact_identifier(item, f"{field}[{i}]")
        if v in seen:
            raise TechnicalProfileValidationError(f"{field} must not contain duplicates.")
        seen.add(v)
        out.append(v)
    if not allow_empty and not out:
        raise TechnicalProfileValidationError(f"{field} must not be empty.")
    return tuple(sorted(out))


def _normalize_enum_str(value: object, field: str, mapping: dict[str, str]) -> str:
    if not isinstance(value, str):
        raise TechnicalProfileValidationError(f"{field} must be a string.")
    canonical = mapping.get(value.strip().casefold())
    if canonical is None:
        raise TechnicalProfileValidationError(f"Invalid {field}: {value!r}")
    return canonical


def _normalize_enum_str_list(value: object, field: str, mapping: dict[str, str], *, allow_empty: bool = False) -> tuple[str, ...]:
    if not isinstance(value, (list, tuple)):
        raise TechnicalProfileValidationError(f"{field} must be a list.")
    out: list[str] = []
    seen: set[str] = set()
    for i, item in enumerate(value):
        v = _normalize_enum_str(item, f"{field}[{i}]", mapping)
        if v in seen:
            raise TechnicalProfileValidationError(f"{field} must not contain duplicates.")
        seen.add(v)
        out.append(v)
    if not allow_empty and not out:
        raise TechnicalProfileValidationError(f"{field} must not be empty.")
    return tuple(sorted(out))


def _normalize_optional_positive_int(value: object, field: str) -> int | None:
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise TechnicalProfileValidationError(f"{field} must be a positive integer or null.")
    return int(value)


def _normalize_optional_notes(value: object, field: str = "notes") -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise TechnicalProfileValidationError(f"{field} must be a string or null.")
    raw = value.strip()
    if not raw:
        return None
    if len(raw) > MAX_NOTES_LENGTH:
        raise TechnicalProfileValidationError(f"{field} must be at most {MAX_NOTES_LENGTH} characters.")
    return raw


@dataclass(frozen=True)
class M2SlotSpec:
    slot_id: str
    accepted_module_keyings: tuple[str, ...]
    supported_lengths: tuple[str, ...]
    supported_modes: tuple[str, ...]
    pcie_generation_max: int | None = None
    pcie_lanes_max: str | None = None
    routed_to: str = "unknown"
    shared_resource_group_id: str | None = None
    disables_sata_port_ids: tuple[str, ...] = ()
    notes: str | None = None
    evidence_ref: str | None = None
    schema_version: int = 1

    def __post_init__(self) -> None:
        object.__setattr__(self, "slot_id", _normalize_exact_identifier(self.slot_id, "slot_id"))
        object.__setattr__(self, "accepted_module_keyings", _normalize_enum_str_list(self.accepted_module_keyings, "accepted_module_keyings", M2_MODULE_KEYING_MAP))
        object.__setattr__(self, "supported_lengths", _normalize_enum_str_list(self.supported_lengths, "supported_lengths", M2_SLOT_LENGTH_MAP))
        object.__setattr__(self, "supported_modes", _normalize_enum_str_list(self.supported_modes, "supported_modes", M2_SUPPORTED_MODE_MAP))
        object.__setattr__(self, "pcie_generation_max", _normalize_optional_positive_int(self.pcie_generation_max, "pcie_generation_max"))
        if self.pcie_lanes_max is not None:
            object.__setattr__(self, "pcie_lanes_max", _normalize_enum_str(self.pcie_lanes_max, "pcie_lanes_max", M2_PCIE_LANES_MAX_MAP))
        object.__setattr__(self, "routed_to", _normalize_enum_str(self.routed_to, "routed_to", M2_ROUTED_TO_MAP))
        if self.shared_resource_group_id is not None:
            object.__setattr__(self, "shared_resource_group_id", _normalize_exact_identifier(self.shared_resource_group_id, "shared_resource_group_id"))
        object.__setattr__(self, "disables_sata_port_ids", _normalize_exact_identifier_list(self.disables_sata_port_ids, "disables_sata_port_ids", allow_empty=True))
        object.__setattr__(self, "notes", _normalize_optional_notes(self.notes))
        if self.evidence_ref is not None:
            object.__setattr__(self, "evidence_ref", _normalize_exact_identifier(self.evidence_ref, "evidence_ref", max_len=MAX_EVIDENCE_REF_LENGTH))
        if isinstance(self.schema_version, bool) or not isinstance(self.schema_version, int) or self.schema_version != 1:
            raise TechnicalProfileValidationError("M2SlotSpec.schema_version must be 1.")

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version, "slot_id": self.slot_id,
            "accepted_module_keyings": list(self.accepted_module_keyings),
            "supported_lengths": list(self.supported_lengths), "supported_modes": list(self.supported_modes),
            "pcie_generation_max": self.pcie_generation_max, "pcie_lanes_max": self.pcie_lanes_max,
            "routed_to": self.routed_to, "shared_resource_group_id": self.shared_resource_group_id,
            "disables_sata_port_ids": list(self.disables_sata_port_ids), "notes": self.notes, "evidence_ref": self.evidence_ref,
        }

    def copy(self) -> "M2SlotSpec":
        return M2SlotSpec.from_dict(self.to_dict())

    @classmethod
    def from_dict(cls, item: object, index: int = 0) -> "M2SlotSpec":
        d = _typed_keys(item, index, "M2SlotSpec", {
            "schema_version","slot_id","accepted_module_keyings","supported_lengths","supported_modes",
            "pcie_generation_max","pcie_lanes_max","routed_to","shared_resource_group_id","disables_sata_port_ids","notes","evidence_ref",
        }, {"slot_id","accepted_module_keyings","supported_lengths","supported_modes"})
        return cls(
            slot_id=d["slot_id"], accepted_module_keyings=d["accepted_module_keyings"],
            supported_lengths=d["supported_lengths"], supported_modes=d["supported_modes"],
            pcie_generation_max=d.get("pcie_generation_max"), pcie_lanes_max=d.get("pcie_lanes_max"),
            routed_to=d.get("routed_to", "unknown"), shared_resource_group_id=d.get("shared_resource_group_id"),
            disables_sata_port_ids=d.get("disables_sata_port_ids", ()), notes=d.get("notes"), evidence_ref=d.get("evidence_ref"),
            schema_version=d.get("schema_version", 1),
        )


@dataclass(frozen=True)
class PowerConnectorRequirement:
    connector_kind: str
    quantity: int
    required: bool = True
    notes: str | None = None
    schema_version: int = 1

    def __post_init__(self) -> None:
        object.__setattr__(self, "connector_kind", _normalize_enum_str(self.connector_kind, "connector_kind", _POWER_CONNECTOR_KIND_MAP))
        if isinstance(self.quantity, bool) or not isinstance(self.quantity, int) or self.quantity <= 0:
            raise TechnicalProfileValidationError("quantity must be a positive integer.")
        if not isinstance(self.required, bool):
            raise TechnicalProfileValidationError("required must be a boolean.")
        object.__setattr__(self, "notes", _normalize_optional_notes(self.notes))
        if isinstance(self.schema_version, bool) or not isinstance(self.schema_version, int) or self.schema_version != 1:
            raise TechnicalProfileValidationError("PowerConnectorRequirement.schema_version must be 1.")

    def to_dict(self) -> dict[str, Any]:
        return {"schema_version": self.schema_version, "connector_kind": self.connector_kind, "quantity": self.quantity, "required": self.required, "notes": self.notes}

    def copy(self) -> "PowerConnectorRequirement":
        return PowerConnectorRequirement.from_dict(self.to_dict())

    @classmethod
    def from_dict(cls, item: object, index: int = 0) -> "PowerConnectorRequirement":
        d = _typed_keys(item, index, "PowerConnectorRequirement", {"schema_version","connector_kind","quantity","required","notes"}, {"connector_kind","quantity"})
        return cls(connector_kind=d["connector_kind"], quantity=d["quantity"], required=d.get("required", True), notes=d.get("notes"), schema_version=d.get("schema_version", 1))


@dataclass(frozen=True)
class PowerCableEndSpec:
    end_id: str
    connector_kind: str
    split_group_id: str | None = None
    schema_version: int = 1

    def __post_init__(self) -> None:
        object.__setattr__(self, "end_id", _normalize_exact_identifier(self.end_id, "end_id"))
        object.__setattr__(self, "connector_kind", _normalize_enum_str(self.connector_kind, "connector_kind", _POWER_CONNECTOR_KIND_MAP))
        if self.split_group_id is not None:
            object.__setattr__(self, "split_group_id", _normalize_exact_identifier(self.split_group_id, "split_group_id"))
        if isinstance(self.schema_version, bool) or not isinstance(self.schema_version, int) or self.schema_version != 1:
            raise TechnicalProfileValidationError("PowerCableEndSpec.schema_version must be 1.")

    def to_dict(self) -> dict[str, Any]:
        return {"schema_version": self.schema_version, "end_id": self.end_id, "connector_kind": self.connector_kind, "split_group_id": self.split_group_id}

    def copy(self) -> "PowerCableEndSpec":
        return PowerCableEndSpec.from_dict(self.to_dict())

    @classmethod
    def from_dict(cls, item: object, index: int = 0) -> "PowerCableEndSpec":
        d = _typed_keys(item, index, "PowerCableEndSpec", {"schema_version","end_id","connector_kind","split_group_id"}, {"end_id","connector_kind"})
        return cls(end_id=d["end_id"], connector_kind=d["connector_kind"], split_group_id=d.get("split_group_id"), schema_version=d.get("schema_version", 1))


@dataclass(frozen=True)
class PowerCableAssembly:
    cable_id: str
    assembly_type: str
    component_side_ends: tuple[PowerCableEndSpec, ...]
    psu_side_connector_id: str | None = None
    approved_psu_model: str | None = None
    approval_reference: str | None = None
    notes: str | None = None
    schema_version: int = 1

    def __post_init__(self) -> None:
        object.__setattr__(self, "cable_id", _normalize_exact_identifier(self.cable_id, "cable_id"))
        object.__setattr__(self, "assembly_type", _normalize_enum_str(self.assembly_type, "assembly_type", _CABLE_ASSEMBLY_TYPE_MAP))
        ends = self.component_side_ends
        if not isinstance(ends, (list, tuple)) or len(ends) == 0:
            raise TechnicalProfileValidationError("component_side_ends must be a non-empty list.")
        norm_ends = []
        seen: set[str] = set()
        for i, e in enumerate(ends):
            if not isinstance(e, PowerCableEndSpec):
                e = PowerCableEndSpec.from_dict(e, i)
            if e.end_id in seen:
                raise TechnicalProfileValidationError(f"component_side_ends has duplicate end_id: {e.end_id}")
            seen.add(e.end_id)
            norm_ends.append(e)
        object.__setattr__(self, "component_side_ends", tuple(norm_ends))
        if self.psu_side_connector_id is not None:
            object.__setattr__(self, "psu_side_connector_id", _normalize_exact_identifier(self.psu_side_connector_id, "psu_side_connector_id"))
        if self.assembly_type == "modular_native" and not self.psu_side_connector_id:
            raise TechnicalProfileValidationError("modular_native cable requires psu_side_connector_id.")
        if self.approved_psu_model is not None:
            object.__setattr__(self, "approved_psu_model", _normalize_exact_identifier(self.approved_psu_model, "approved_psu_model", max_len=MAX_NOTES_LENGTH))
        if self.approval_reference is not None:
            object.__setattr__(self, "approval_reference", _normalize_exact_identifier(self.approval_reference, "approval_reference", max_len=MAX_EVIDENCE_REF_LENGTH))
        if self.assembly_type == "manufacturer_approved_adapter":
            if not self.approved_psu_model or not self.approval_reference:
                raise TechnicalProfileValidationError("manufacturer_approved_adapter requires approved_psu_model and approval_reference.")
        object.__setattr__(self, "notes", _normalize_optional_notes(self.notes))
        if isinstance(self.schema_version, bool) or not isinstance(self.schema_version, int) or self.schema_version != 1:
            raise TechnicalProfileValidationError("PowerCableAssembly.schema_version must be 1.")

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version, "cable_id": self.cable_id, "assembly_type": self.assembly_type,
            "psu_side_connector_id": self.psu_side_connector_id, "component_side_ends": [e.to_dict() for e in self.component_side_ends],
            "approved_psu_model": self.approved_psu_model, "approval_reference": self.approval_reference, "notes": self.notes,
        }

    def copy(self) -> "PowerCableAssembly":
        return PowerCableAssembly.from_dict(self.to_dict())

    @classmethod
    def from_dict(cls, item: object, index: int = 0) -> "PowerCableAssembly":
        d = _typed_keys(item, index, "PowerCableAssembly", {
            "schema_version","cable_id","assembly_type","psu_side_connector_id","component_side_ends","approved_psu_model","approval_reference","notes",
        }, {"cable_id","assembly_type","component_side_ends"})
        ends = d.get("component_side_ends")
        if not isinstance(ends, (list, tuple)):
            raise TechnicalProfileValidationError(f"PowerCableAssembly at index {index}: component_side_ends must be a list.")
        return cls(
            cable_id=d["cable_id"], assembly_type=d["assembly_type"],
            psu_side_connector_id=d.get("psu_side_connector_id"),
            component_side_ends=tuple(PowerCableEndSpec.from_dict(e, i) for i, e in enumerate(ends)),
            approved_psu_model=d.get("approved_psu_model"), approval_reference=d.get("approval_reference"),
            notes=d.get("notes"), schema_version=d.get("schema_version", 1),
        )


def _normalize_typed_object_list(value: object, key: str, cls) -> tuple[Any, ...]:
    if not isinstance(value, (list, tuple)):
        raise TechnicalProfileValidationError(f"{key} must be a list.")
    items = []
    seen_ids: set[str] = set()
    id_field = "slot_id" if cls is M2SlotSpec else ("connector_kind" if cls is PowerConnectorRequirement else "cable_id")
    # PowerConnectorRequirement: reject duplicate connector_kind (ambiguous); use quantity
    for i, item in enumerate(value):
        obj = item if isinstance(item, cls) else cls.from_dict(item, i)
        if cls is PowerConnectorRequirement:
            uid = obj.connector_kind
        else:
            uid = getattr(obj, id_field)
        if uid in seen_ids:
            raise TechnicalProfileValidationError(f"{key} has duplicate identifier: {uid}")
        seen_ids.add(uid)
        items.append(obj)
    # deterministic order
    if cls is M2SlotSpec:
        items.sort(key=lambda o: o.slot_id)
    elif cls is PowerConnectorRequirement:
        items.sort(key=lambda o: (o.connector_kind, 0 if o.required else 1, o.quantity))
    else:
        items.sort(key=lambda o: o.cable_id)
    return tuple(items)


def validate_profile_for_category(profile: TechnicalProfile, category: str) -> TechnicalProfile:
    """Validate attribute keys/values/units against category registry; returns defensive-normalized copy."""
    if not isinstance(profile, TechnicalProfile):
        raise TechnicalProfileValidationError("profile must be a TechnicalProfile instance.")
    specs = ATTRIBUTE_REGISTRY.get(category)
    if specs is None:
        raise TechnicalProfileValidationError(f"Category has no technical attribute registry: {category!r}")
    seen: set[str] = set()
    normalized_attrs: list[TechnicalAttribute] = []
    for attr in profile.attributes:
        if attr.key in seen:
            raise TechnicalProfileValidationError(f"attributes contains duplicate key: {attr.key}")
        seen.add(attr.key)
        normalized_value, normalized_unit = validate_attribute_value(category, attr.key, attr.value, attr.unit)
        normalized_attrs.append(
            TechnicalAttribute(
                key=attr.key,
                value=normalized_value,
                unit=normalized_unit,
                original_value=attr.original_value,
                source=attr.source,
                confidence=attr.confidence,
                verification_status=attr.verification_status,
                evidence_ref=attr.evidence_ref,
                verified_at=attr.verified_at,
                collection_completeness=attr.collection_completeness,
                completeness_scope=attr.completeness_scope,
            )
        )
    normalized_attrs.sort(key=lambda a: a.key)
    _validate_profile_cross_attributes(category, normalized_attrs)
    return TechnicalProfile(component_id=profile.component_id, profile_version=profile.profile_version, attributes=normalized_attrs)


def parse_attribute_dict(item: object, index: int, category: str) -> TechnicalAttribute:
    if not isinstance(item, dict):
        raise TechnicalProfileValidationError(f"Attribute at index {index} must be an object.")
    unknown = set(item) - ATTRIBUTE_KEYS
    if unknown:
        raise TechnicalProfileValidationError(f"Attribute at index {index} has unknown keys: {', '.join(sorted(unknown))}.")
    if "key" not in item:
        raise TechnicalProfileValidationError(f"Attribute at index {index} is missing required key: key.")
    if "value" not in item:
        raise TechnicalProfileValidationError(f"Attribute at index {index} is missing required key: value.")
    key = _normalize_key(item.get("key"))
    normalized_value, normalized_unit = validate_attribute_value(category, key, item.get("value"), item.get("unit"))
    return TechnicalAttribute(
        key=key,
        value=normalized_value,
        unit=normalized_unit,
        original_value=item.get("original_value"),
        source=item.get("source", "user_input"),
        confidence=item.get("confidence", "medium"),
        verification_status=item.get("verification_status", "unverified"),
        evidence_ref=item.get("evidence_ref"),
        verified_at=item.get("verified_at"),
        collection_completeness=item.get("collection_completeness", "unknown"),
        completeness_scope=item.get("completeness_scope"),
    )


def parse_profile_dict(item: object, index: int, category: str) -> TechnicalProfile:
    if not isinstance(item, dict):
        raise TechnicalProfileValidationError(f"Technical profile at index {index} must be an object.")
    unknown = set(item) - PROFILE_KEYS
    if unknown:
        raise TechnicalProfileValidationError(f"Technical profile at index {index} has unknown keys: {', '.join(sorted(unknown))}.")
    if "component_id" not in item:
        raise TechnicalProfileValidationError(f"Technical profile at index {index} is missing required key: component_id.")
    component_id = _normalize_uuid(item.get("component_id"), "component_id")
    profile_version = item.get("profile_version", PROFILE_VERSION)
    if isinstance(profile_version, bool) or not isinstance(profile_version, int) or profile_version not in SUPPORTED_PROFILE_STRUCTURAL_VERSIONS:
        raise TechnicalProfileValidationError(
            f"Technical profile at index {index} has unsupported profile_version: {profile_version!r}."
        )
    attrs_raw = item.get("attributes", [])
    if not isinstance(attrs_raw, list):
        raise TechnicalProfileValidationError(f"Technical profile at index {index}: attributes must be a list.")
    seen: set[str] = set()
    attrs: list[TechnicalAttribute] = []
    for aidx, aitem in enumerate(attrs_raw):
        attr = parse_attribute_dict(aitem, aidx, category)
        if attr.key in seen:
            raise TechnicalProfileValidationError(f"Technical profile at index {index} has duplicate attribute key: {attr.key}")
        seen.add(attr.key)
        attrs.append(attr)
    attrs.sort(key=lambda a: a.key)
    _validate_profile_cross_attributes(category, attrs)
    return TechnicalProfile(component_id=component_id, profile_version=profile_version, attributes=attrs)
