"""Safe CSV import to inventory (T17.22).

Pure analysis layer: reads a user-selected CSV, validates each row against
the real Component contract, and classifies duplicates using
``catalog_duplicate_key``. It never writes to the inventory and never
invents technical profiles, evidence, confidence or provenance.
"""

from __future__ import annotations

import csv
import io
from dataclasses import dataclass, field
from pathlib import Path
from types import SimpleNamespace

from pc_parts_organizer.catalog_models import catalog_duplicate_key

CANONICAL_HEADERS = ("category", "manufacturer", "model", "specs", "notes")
REQUIRED_HEADERS = ("category", "manufacturer", "model")

_HEADER_ALIASES = {
    "category": ("categoria", "categoría", "tipo"),
    "manufacturer": ("fabricante", "marca", "maker", "make", "brand"),
    "model": ("modelo", "model"),
    "specs": ("specs", "specifications", "especificaciones", "especificacion", "especificación"),
    "notes": ("notes", "notas", "note", "comentarios"),
}

SUPPORTED_ENCODINGS = ("utf-8-sig", "utf-8", "utf-16", "cp1252")
DETECTORS = ("utf-8-sig", "utf-16", "cp1252")
DELIMITERS = (",", ";", "\t")
DIALECTS = {",": "excel", ";": "excel-semicolon", "\t": "excel-tab"}

MAX_FILE_BYTES = 5 * 1024 * 1024
MAX_ROWS = 50_000


class CsvInventoryImportError(ValueError):
    """Raised when a CSV cannot be analyzed (header/encoding/limits)."""


@dataclass
class CsvRowAnalysis:
    """Structured outcome for one source row."""

    line: int
    raw: list[str]
    component: dict | None = None
    status: str = "rejected"
    reasons: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    duplicate_of: str = ""       # name of the matched component (inventory or file)
    duplicate_kind: str = ""     # "inventory" | "internal"
    duplicate_lines: list[int] = field(default_factory=list)


@dataclass
class CsvImportAnalysis:
    """Complete analysis result for one file."""

    path: str
    encoding: str
    delimiter: str
    columns: dict[str, str]
    ignored_columns: list[str]
    total_rows: int = 0
    valid_new: list[CsvRowAnalysis] = field(default_factory=list)
    inventory_duplicates: list[CsvRowAnalysis] = field(default_factory=list)
    internal_duplicates: list[CsvRowAnalysis] = field(default_factory=list)
    rejected: list[CsvRowAnalysis] = field(default_factory=list)
    empty_rows: list[int] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    components: list[dict] = field(default_factory=list)

    @property
    def valid_count(self) -> int:
        return len(self.valid_new)

    @property
    def inventory_duplicate_count(self) -> int:
        return len(self.inventory_duplicates)

    @property
    def internal_duplicate_count(self) -> int:
        return len(self.internal_duplicates)

    @property
    def rejected_count(self) -> int:
        return len(self.rejected)


def normalize_header(value: str) -> str:
    return "".join(ch for ch in str(value).strip().casefold() if ch.isalnum() or ch == "_")


def resolve_columns(header: list[str]) -> tuple[dict[str, str], list[str], list[str]]:
    """Map canonical fields to source columns. Returns (columns, ignored, problems)."""
    problems: list[str] = []
    used: set[int] = set()
    columns: dict[str, str] = {}
    ignored: list[str] = []
    seen: dict[str, int] = {}
    for index, raw in enumerate(header):
        norm = normalize_header(raw)
        if norm in seen:
            problems.append(f"duplicate header: {raw!r}")
            continue
        seen[norm] = index
        for canonical, aliases in _HEADER_ALIASES.items():
            if norm == canonical or norm in aliases:
                if canonical in columns:
                    problems.append(f"duplicate header: {raw!r}")
                    continue
                columns[canonical] = raw
                used.add(index)
                break
    for index, raw in enumerate(header):
        if index not in used:
            ignored.append(str(raw))
    missing = [name for name in REQUIRED_HEADERS if name not in columns]
    if missing:
        problems.append(f"missing required headers: {', '.join(missing)}")
    return columns, ignored, problems


def detect_encoding(data: bytes) -> str:
    """Deterministic encoding detection (BOM first)."""
    if data.startswith(b"\xef\xbb\xbf"):
        return "utf-8-sig"
    if data.startswith(b"\xff\xfe") or data.startswith(b"\xfe\xff"):
        return "utf-16"
    try:
        data.decode("utf-8")
        return "utf-8"
    except UnicodeDecodeError:
        try:
            data.decode("cp1252")
            return "cp1252"
        except UnicodeDecodeError:
            raise CsvInventoryImportError("encoding_not_detected")


def detect_delimiter(text: str, encoding: str) -> str:
    """Prefer a comma, then semicolon, then tab, by structural column counts."""
    header_line = text.splitlines()[0] if text.splitlines() else ""
    if not header_line.strip():
        return ","
    best = (0, ",")
    for delim in DELIMITERS:
        try:
            first = next(csv.reader(io.StringIO(header_line), delimiter=delim))
            rest = [r for r in csv.reader(io.StringIO(text), delimiter=delim)]
            width = len(first)
            consistent = sum(1 for row in rest if len(row) == width)
            score = width * 10 + consistent
            if score > best[0]:
                best = (score, delim)
        except csv.Error:
            continue
    return best[1]


def _clean(value: str) -> str:
    return str(value).strip()


def _duplicate_key(category: str, manufacturer: str, model: str) -> tuple[str, str, str]:
    """Same normalized identity as the service (attribute-style entry)."""
    return catalog_duplicate_key(SimpleNamespace(
        category=category, manufacturer=manufacturer, model=model))


def _display_name(candidate: dict) -> str:
    parts = [str(candidate.get("manufacturer", "") or "").strip(),
             str(candidate.get("model", "") or "").strip()]
    return " ".join(p for p in parts if p)


def analyze_csv(
    source: str | Path,
    *,
    encoding: str | None = None,
    delimiter: str | None = None,
    inventory_components: list | None = None,
) -> CsvImportAnalysis:
    """Analyze a CSV without writing anything.

    ``inventory_components`` provides the current inventory (Component objects
    or dicts) used only for duplicate classification.
    """
    path = Path(source)
    try:
        raw = path.read_bytes()
    except OSError as exc:
        raise CsvInventoryImportError(f"unreadable_file: {exc}") from exc
    if not raw:
        raise CsvInventoryImportError("empty_file")
    if len(raw) > MAX_FILE_BYTES:
        raise CsvInventoryImportError(f"file_too_large: {len(raw)} > {MAX_FILE_BYTES}")

    enc = encoding if encoding is not None else detect_encoding(raw)
    try:
        text = raw.decode(enc)
    except (UnicodeDecodeError, LookupError):
        raise CsvInventoryImportError(f"encoding_invalid: {enc}")

    delim = delimiter if delimiter is not None else detect_delimiter(text, enc)
    if delim not in DELIMITERS:
        raise CsvInventoryImportError(f"unsupported_delimiter: {delim!r}")

    try:
        rows = list(csv.reader(io.StringIO(text), delimiter=delim))
    except csv.Error as exc:
        raise CsvInventoryImportError(f"malformed_csv: {exc}") from exc
    if not rows:
        raise CsvInventoryImportError("empty_file")
    if len(rows) - 1 > MAX_ROWS:
        raise CsvInventoryImportError(f"too_many_rows: {len(rows) - 1} > {MAX_ROWS}")

    header = [_clean(h) for h in rows[0]]
    columns, ignored, problems = resolve_columns(header)
    if problems:
        raise CsvInventoryImportError("; ".join(problems))

    analysis = CsvImportAnalysis(
        path=str(path), encoding=enc, delimiter=delim,
        columns=columns, ignored_columns=ignored,
        total_rows=len(rows) - 1,
    )

    def value(row: list[str], canonical: str) -> str:
        raw_name = columns.get(canonical)
        if raw_name is None:
            return ""
        for index, name in enumerate(header):
            if name == raw_name:
                return _clean(row[index]) if index < len(row) else ""
        return ""

    existing_keys: dict[tuple, str] = {}
    if inventory_components:
        for comp in inventory_components:
            if isinstance(comp, dict):
                category = str(comp.get("category", ""))
                manufacturer = str(comp.get("manufacturer", ""))
                model = str(comp.get("model", ""))
            else:
                category = str(getattr(comp, "category", ""))
                manufacturer = str(getattr(comp, "manufacturer", ""))
                model = str(getattr(comp, "model", ""))
            try:
                key = _duplicate_key(category, manufacturer, model)
            except Exception:
                continue
            existing_keys.setdefault(key, _display_name(
                {"manufacturer": manufacturer, "model": model}))

    seen_internal: dict[tuple, int] = {}
    for offset, row in enumerate(rows[1:]):
        line = offset + 2  # header is line 1
        if not row or all(not cell.strip() for cell in row):
            analysis.empty_rows.append(line)
            continue
        if len(row) > len(header):
            entry = CsvRowAnalysis(line=line, raw=list(row), status="rejected")
            entry.reasons.append(f"too_many_columns: {len(row)} > {len(header)}")
            analysis.rejected.append(entry)
            continue
        if len(row) < len(header):
            row = row + [""] * (len(header) - len(row))
            analysis.warnings.append(f"row {line}: padded to {len(header)} columns")

        candidate = {
            "category": value(row, "category"),
            "manufacturer": value(row, "manufacturer"),
            "model": value(row, "model"),
            "specifications": value(row, "specs"),
            "notes": value(row, "notes"),
        }
        entry = CsvRowAnalysis(line=line, raw=list(row), component=candidate)

        # Reuse the real model validation through the real service contract:
        # build the Component candidate with the same normalizers.
        from pc_parts_organizer.models import Component, ComponentValidationError

        try:
            validated = Component(**candidate)
        except ComponentValidationError as exc:
            entry.reasons.append(str(exc))
            analysis.rejected.append(entry)
            continue
        except (ValueError, TypeError) as exc:
            entry.reasons.append(str(exc))
            analysis.rejected.append(entry)
            continue

        # Identity uses the canonical (validated) fields, exactly like the
        # service: a lowercase category must key the same as its canonical form.
        try:
            key = _duplicate_key(validated.category, validated.manufacturer, validated.model)
        except Exception as exc:  # identity not computable -> not a fake duplicate
            entry.warnings.append(f"identity_unavailable: {exc}")
            analysis.valid_new.append(entry)
            continue

        if key in existing_keys:
            entry.status = "duplicate"
            entry.duplicate_kind = "inventory"
            entry.duplicate_of = existing_keys[key]
            analysis.inventory_duplicates.append(entry)
            continue
        if key in seen_internal:
            entry.status = "duplicate"
            entry.duplicate_kind = "internal"
            entry.duplicate_of = _display_name(candidate)
            entry.duplicate_lines = [seen_internal[key], line]
            analysis.internal_duplicates.append(entry)
            continue
        seen_internal[key] = line
        entry.status = "valid_new"
        analysis.valid_new.append(entry)
        analysis.components.append(candidate)

    return analysis


def csv_template_text() -> str:
    """Canonical template with clearly-marked example rows (UTF-8 text)."""
    return (
        "category,manufacturer,model,specs,notes\n"
        "CPU,AMD,Ryzen 5 5600,6C/12T 3.5GHz,Ejemplo: sustituir por tu componente\n"
        "RAM,Corsair,Vengeance 16GB,DDR4-3200 DIMM,Ejemplo: notas opcionales\n"
        "GPU,NVIDIA,RTX 3060,12GB GDDR6,\"Ejemplo: separador, dentro de comillas\"\n"
    )
