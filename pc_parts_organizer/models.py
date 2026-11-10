"""Data models for PC Parts Organizer."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal, InvalidOperation
from uuid import UUID, uuid4

CATEGORIES: tuple[str, ...] = (
    "CPU",
    "GPU",
    "Motherboard",
    "RAM",
    "Storage",
    "PSU",
    "Case",
    "Cooling",
    "Monitor",
    "Peripheral",
    "Other",
)

_CATEGORY_MAP = {category.casefold(): category for category in CATEGORIES}

COMPONENT_STATUSES: tuple[str, ...] = (
    "unspecified",
    "installed",
    "stored",
    "faulty",
    "under_repair",
    "loaned",
    "retired",
)

_STATUS_MAP = {status.casefold(): status for status in COMPONENT_STATUSES}
MAX_LOCATION_LENGTH = 120


class ComponentValidationError(ValueError):
    """Raised when component data is invalid."""


def _normalize_required_text(value: object, field_name: str) -> str:
    if not isinstance(value, str):
        raise ComponentValidationError(f"{field_name} must be a string.")
    normalized = value.strip()
    if not normalized:
        raise ComponentValidationError(f"{field_name} is required.")
    return normalized


def _normalize_optional_text(value: object, field_name: str) -> str:
    if value is None:
        return ""
    if not isinstance(value, str):
        raise ComponentValidationError(f"{field_name} must be a string or None.")
    return value


def _normalize_category(value: object) -> str:
    if not isinstance(value, str):
        raise ComponentValidationError("category must be a string.")
    normalized = value.strip()
    if not normalized:
        raise ComponentValidationError("category is required.")
    canonical = _CATEGORY_MAP.get(normalized.casefold())
    if canonical is None:
        raise ComponentValidationError(f"Unknown category: {normalized}")
    return canonical


def _normalize_status(value: object) -> str:
    if not isinstance(value, str):
        raise ComponentValidationError("status must be a string.")
    normalized = value.strip()
    if not normalized:
        raise ComponentValidationError("status is required.")
    canonical = _STATUS_MAP.get(normalized.casefold())
    if canonical is None:
        raise ComponentValidationError(f"Unknown status: {normalized}")
    return canonical


def _normalize_location(value: object) -> str:
    if value is None:
        return ""
    if not isinstance(value, str):
        raise ComponentValidationError("location must be a string or None.")
    normalized = value.strip()
    if len(normalized) > MAX_LOCATION_LENGTH:
        raise ComponentValidationError(f"location must be at most {MAX_LOCATION_LENGTH} characters.")
    return normalized


_ISO_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_CURRENCY_RE = re.compile(r"^[A-Za-z]{3}$")


def _normalize_iso_date(value: object, field_name: str) -> str:
    if value is None:
        return ""
    if not isinstance(value, str):
        raise ComponentValidationError(f"{field_name} must be a string or None.")
    normalized = value.strip()
    if not normalized:
        return ""
    if not _ISO_DATE_RE.fullmatch(normalized):
        raise ComponentValidationError(f"{field_name} must be in YYYY-MM-DD format.")
    try:
        date.fromisoformat(normalized)
    except ValueError as exc:
        raise ComponentValidationError(f"{field_name} must be a valid calendar date.") from exc
    return normalized


def _normalize_purchase_price(value: object) -> str:
    if value is None:
        return ""
    if not isinstance(value, str):
        raise ComponentValidationError("purchase_price must be a string or None.")
    raw = value.strip()
    if not raw:
        return ""
    if "e" in raw.lower():
        raise ComponentValidationError("purchase_price must not use scientific notation.")
    if raw.count(",") + raw.count(".") > 1:
        raise ComponentValidationError("purchase_price must not include thousands separators.")
    if "," in raw and "." in raw:
        raise ComponentValidationError("purchase_price must not include both comma and period.")
    sep = "," if "," in raw else ("." if "." in raw else None)
    if sep:
        int_part, frac_part = raw.split(sep)
    else:
        int_part, frac_part = raw, ""
    if not int_part and not frac_part:
        raise ComponentValidationError("purchase_price must be a valid decimal number.")
    if not int_part:
        int_part = "0"
    if not int_part.isdigit() or (frac_part and not frac_part.isdigit()):
        raise ComponentValidationError("purchase_price must be a valid decimal number.")
    if len(frac_part) > 4:
        raise ComponentValidationError("purchase_price must have at most 4 decimal places.")
    int_canonical = str(int(int_part)) if int_part else "0"
    if len(int_canonical) > 12:
        raise ComponentValidationError("purchase_price must have at most 12 integer digits.")
    decimal_text = int_canonical + ("." + frac_part if frac_part else "")
    try:
        dec = Decimal(decimal_text)
    except InvalidOperation as exc:
        raise ComponentValidationError("purchase_price must be a valid decimal number.") from exc
    if not dec.is_finite() or dec.is_nan():
        raise ComponentValidationError("purchase_price must be a valid decimal number.")
    if dec < 0:
        raise ComponentValidationError("purchase_price must not be negative.")
    return decimal_text


def _normalize_purchase_currency(value: object) -> str:
    if value is None:
        return ""
    if not isinstance(value, str):
        raise ComponentValidationError("purchase_currency must be a string or None.")
    normalized = value.strip()
    if not normalized:
        return ""
    if not _CURRENCY_RE.fullmatch(normalized):
        raise ComponentValidationError("purchase_currency must be a 3-letter code.")
    return normalized.upper()


def _validate_price_currency_pair(price: str, currency: str) -> None:
    if bool(price) != bool(currency):
        raise ComponentValidationError("purchase_price and purchase_currency must both be set or both be empty.")


def _normalize_id(value: object) -> str:
    if isinstance(value, UUID):
        candidate = value
    elif isinstance(value, str):
        try:
            candidate = UUID(value)
        except (ValueError, AttributeError, TypeError) as exc:
            raise ComponentValidationError("id must be a valid UUID v4.") from exc
    else:
        raise ComponentValidationError("id must be a UUID v4 string or UUID object.")
    if candidate.version != 4:
        raise ComponentValidationError("id must be a valid UUID v4.")
    return str(candidate)


class BuildValidationError(ValueError):
    """Raised when build data is invalid."""


BUILD_KINDS: tuple[str, ...] = ("current", "planned")
_BUILD_KIND_MAP = {kind.casefold(): kind for kind in BUILD_KINDS}
MAX_BUILD_NAME_LENGTH = 120
MAX_BUILD_NOTES_LENGTH = 2000


def _normalize_build_name(value: object) -> str:
    if not isinstance(value, str):
        raise BuildValidationError("name must be a string.")
    normalized = value.strip()
    if not normalized:
        raise BuildValidationError("name is required.")
    if len(normalized) > MAX_BUILD_NAME_LENGTH:
        raise BuildValidationError(f"name must be at most {MAX_BUILD_NAME_LENGTH} characters.")
    return normalized


def _normalize_build_notes(value: object) -> str:
    if value is None:
        return ""
    if not isinstance(value, str):
        raise BuildValidationError("notes must be a string or None.")
    normalized = value.strip()
    if len(normalized) > MAX_BUILD_NOTES_LENGTH:
        raise BuildValidationError(f"notes must be at most {MAX_BUILD_NOTES_LENGTH} characters.")
    return normalized


def _normalize_build_kind(value: object) -> str:
    if not isinstance(value, str):
        raise BuildValidationError("kind must be a string.")
    normalized = value.strip()
    if not normalized:
        raise BuildValidationError("kind is required.")
    canonical = _BUILD_KIND_MAP.get(normalized.casefold())
    if canonical is None:
        raise BuildValidationError(f"Unknown kind: {normalized}")
    return canonical


def _normalize_build_id(value: object) -> str:
    if isinstance(value, UUID):
        candidate = value
    elif isinstance(value, str):
        try:
            candidate = UUID(value)
        except (ValueError, AttributeError, TypeError) as exc:
            raise BuildValidationError("id must be a valid UUID v4.") from exc
    else:
        raise BuildValidationError("id must be a UUID v4 string or UUID object.")
    if candidate.version != 4:
        raise BuildValidationError("id must be a valid UUID v4.")
    return str(candidate)


def _normalize_component_ids(value: object) -> tuple[str, ...]:
    if value is None:
        return ()
    if not isinstance(value, (list, tuple)):
        raise BuildValidationError("component_ids must be a list.")
    normalized: list[str] = []
    seen: set[str] = set()
    for index, item in enumerate(value):
        try:
            cid = _normalize_build_id(item) if not isinstance(item, UUID) else str(item)
            # normalize via UUID parse for strictness (accept UUID v4)
            cid = _normalize_build_id(cid)
        except BuildValidationError as exc:
            raise BuildValidationError(f"component_ids[{index}] is invalid: {exc}") from exc
        if cid in seen:
            raise BuildValidationError(f"component_ids contains duplicate id: {cid}")
        seen.add(cid)
        normalized.append(cid)
    return tuple(normalized)


@dataclass
class Build:
    """A PC build/configuration that references inventory components by UUID."""

    name: str
    notes: str | None = ""
    kind: str = "current"
    component_ids: list[str] | tuple[str, ...] | None = field(default_factory=list)
    id: str | UUID = field(default_factory=lambda: str(uuid4()))

    def __post_init__(self) -> None:
        self.id = _normalize_build_id(self.id)
        self.name = _normalize_build_name(self.name)
        self.notes = _normalize_build_notes(self.notes)
        self.kind = _normalize_build_kind(self.kind)
        # defensive copy; store as list for compatibility/JSON serialization convenience
        self.component_ids = list(_normalize_component_ids(self.component_ids))


@dataclass
class Component:
    """A PC component in the inventory."""

    category: str
    manufacturer: str
    model: str
    specifications: str | None = ""
    notes: str | None = ""
    id: str | UUID = field(default_factory=lambda: str(uuid4()))
    status: str = "unspecified"
    location: str | None = ""
    purchase_date: str | None = ""
    warranty_end_date: str | None = ""
    purchase_price: str | None = ""
    purchase_currency: str | None = ""

    def __post_init__(self) -> None:
        self.category = _normalize_category(self.category)
        self.manufacturer = _normalize_required_text(self.manufacturer, "manufacturer")
        self.model = _normalize_required_text(self.model, "model")
        self.specifications = _normalize_optional_text(self.specifications, "specifications")
        self.notes = _normalize_optional_text(self.notes, "notes")
        self.id = _normalize_id(self.id)
        self.status = _normalize_status(self.status)
        self.location = _normalize_location(self.location)
        self.purchase_date = _normalize_iso_date(self.purchase_date, "purchase_date")
        self.warranty_end_date = _normalize_iso_date(self.warranty_end_date, "warranty_end_date")
        self.purchase_price = _normalize_purchase_price(self.purchase_price)
        self.purchase_currency = _normalize_purchase_currency(self.purchase_currency)
        _validate_price_currency_pair(self.purchase_price, self.purchase_currency)
