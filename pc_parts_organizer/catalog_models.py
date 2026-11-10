"""Catalog reference data models."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from urllib.parse import urlparse
from uuid import UUID, uuid4

from pc_parts_organizer.models import CATEGORIES

_CATEGORY_MAP = {category.casefold(): category for category in CATEGORIES}


class CatalogValidationError(ValueError):
    """Raised when catalog reference data is invalid."""


def _normalize_required_text(value: object, field_name: str) -> str:
    if not isinstance(value, str):
        raise CatalogValidationError(f"{field_name} must be a string.")
    normalized = value.strip()
    if not normalized:
        raise CatalogValidationError(f"{field_name} is required.")
    return normalized


def _normalize_optional_text(value: object, field_name: str) -> str:
    if value is None:
        return ""
    if not isinstance(value, str):
        raise CatalogValidationError(f"{field_name} must be a string or None.")
    return value


def _normalize_category(value: object) -> str:
    if not isinstance(value, str):
        raise CatalogValidationError("category must be a string.")
    normalized = value.strip()
    if not normalized:
        raise CatalogValidationError("category is required.")
    canonical = _CATEGORY_MAP.get(normalized.casefold())
    if canonical is None:
        raise CatalogValidationError(f"Unknown category: {normalized}")
    return canonical


def _normalize_id(value: object) -> str:
    if isinstance(value, UUID):
        candidate = value
    elif isinstance(value, str):
        try:
            candidate = UUID(value)
        except (ValueError, AttributeError, TypeError) as exc:
            raise CatalogValidationError("id must be a valid UUID v4.") from exc
    else:
        raise CatalogValidationError("id must be a UUID v4 string or UUID object.")
    if candidate.version != 4:
        raise CatalogValidationError("id must be a valid UUID v4.")
    return str(candidate)


def _normalize_verified_at(value: object) -> str:
    normalized = _normalize_optional_text(value, "verified_at")
    if not normalized:
        return ""
    try:
        parsed = date.fromisoformat(normalized)
    except ValueError as exc:
        raise CatalogValidationError("verified_at must be a real ISO date (YYYY-MM-DD).") from exc
    if parsed.isoformat() != normalized:
        raise CatalogValidationError("verified_at must be a real ISO date (YYYY-MM-DD).")
    return normalized


def _normalize_source_url(value: object) -> str:
    normalized = _normalize_optional_text(value, "source_url")
    if not normalized:
        return ""
    parsed = urlparse(normalized)
    if parsed.scheme not in {"http", "https"}:
        raise CatalogValidationError("source_url must be an absolute HTTP or HTTPS URL.")
    if not parsed.netloc or not parsed.hostname:
        raise CatalogValidationError("source_url must include a valid host.")
    return normalized


def _normalize_comparison_text(value: str) -> str:
    return " ".join(value.strip().split()).casefold()


def catalog_duplicate_key(entry: "CatalogEntry") -> tuple[str, str, str]:
    """Return the duplicate-detection key for a catalog entry."""
    return (
        entry.category,
        _normalize_comparison_text(entry.manufacturer),
        _normalize_comparison_text(entry.model),
    )


@dataclass(frozen=True)
class CatalogEntry:
    """A reusable commercial component reference."""

    category: str
    manufacturer: str
    model: str
    specifications: str | None = ""
    notes: str | None = ""
    source: str | None = ""
    source_url: str | None = ""
    source_license: str | None = ""
    attribution: str | None = ""
    verified_at: str | None = ""
    id: str | UUID = field(default_factory=lambda: str(uuid4()))

    def __post_init__(self) -> None:
        object.__setattr__(self, "category", _normalize_category(self.category))
        object.__setattr__(self, "manufacturer", _normalize_required_text(self.manufacturer, "manufacturer"))
        object.__setattr__(self, "model", _normalize_required_text(self.model, "model"))
        object.__setattr__(self, "specifications", _normalize_optional_text(self.specifications, "specifications"))
        object.__setattr__(self, "notes", _normalize_optional_text(self.notes, "notes"))
        object.__setattr__(self, "source", _normalize_optional_text(self.source, "source"))
        object.__setattr__(self, "source_url", _normalize_source_url(self.source_url))
        object.__setattr__(self, "source_license", _normalize_optional_text(self.source_license, "source_license"))
        object.__setattr__(self, "attribution", _normalize_optional_text(self.attribution, "attribution"))
        object.__setattr__(self, "verified_at", _normalize_verified_at(self.verified_at))
        object.__setattr__(self, "id", _normalize_id(self.id))
