"""CSV/JSON import and export for catalog references."""

from __future__ import annotations

import csv
import json
import os
import tempfile
from dataclasses import dataclass
from pathlib import Path

from pc_parts_organizer.catalog_models import CatalogEntry, CatalogValidationError
from pc_parts_organizer.catalog_storage import CatalogStorage

CSV_FIELDS = (
    "id",
    "category",
    "manufacturer",
    "model",
    "specifications",
    "notes",
    "source",
    "source_url",
    "source_license",
    "attribution",
    "verified_at",
)
REQUIRED_IMPORT_FIELDS = {"category", "manufacturer", "model"}
OPTIONAL_IMPORT_FIELDS = set(CSV_FIELDS) - REQUIRED_IMPORT_FIELDS
JSON_SCHEMA_VERSION = 1
EXPORT_PAGE_SIZE = 500


class CatalogFileError(Exception):
    """Raised for controlled catalog file errors."""


class CatalogImportError(CatalogFileError):
    """Raised when import data is invalid."""

    def __init__(
        self,
        message: str,
        *,
        row_number: int | None = None,
        field: str | None = None,
    ) -> None:
        super().__init__(message)
        self.row_number = row_number
        self.field = field


@dataclass(frozen=True)
class CatalogImportResult:
    """Result of a catalog import."""

    total_entries: int
    inserted_count: int
    duplicate_count: int


def _detect_duplicate_json_keys(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise CatalogFileError(f"Duplicate JSON key: {key}")
        result[key] = value
    return result


class CatalogFileService:
    """Import and export catalog references."""

    def __init__(self, storage: CatalogStorage) -> None:
        self._storage = storage

    def _resolve_format(self, path: Path, file_format: str | None) -> str:
        fmt = file_format if file_format is not None else path.suffix.lstrip(".")
        if not fmt:
            raise CatalogFileError("Unknown catalog file format.")
        fmt = fmt.lower()
        if fmt not in {"csv", "json"}:
            raise CatalogFileError(f"Unsupported catalog file format: {fmt}")
        return fmt

    def _check_source(self, source_path: Path) -> None:
        if not source_path.exists() or not source_path.is_file():
            raise CatalogFileError(f"Import file not found: {source_path}")

    def import_file(
        self,
        source_path: Path,
        file_format: str | None = None,
        skip_duplicates: bool = True,
    ) -> CatalogImportResult:
        self._check_source(source_path)
        fmt = self._resolve_format(source_path, file_format)
        if fmt == "csv":
            entries = self._read_csv(source_path)
        else:
            entries = self._read_json(source_path)
        result = self._storage.add_entries(entries, skip_duplicates=skip_duplicates)
        return CatalogImportResult(
            total_entries=len(entries),
            inserted_count=result.inserted_count,
            duplicate_count=result.duplicate_count,
        )

    def _read_csv(self, source_path: Path) -> list[CatalogEntry]:
        try:
            with source_path.open("r", encoding="utf-8-sig", newline="") as f:
                reader = csv.DictReader(f)
                if reader.fieldnames is None:
                    raise CatalogImportError("CSV file is missing a header row.")
                fieldnames = [name if name is not None else "" for name in reader.fieldnames]
                if len(fieldnames) != len(set(fieldnames)):
                    raise CatalogImportError("CSV header contains duplicate columns.")
                unknown = set(fieldnames) - set(CSV_FIELDS)
                if unknown:
                    raise CatalogImportError(f"CSV header has unknown columns: {', '.join(sorted(unknown))}.")
                missing = REQUIRED_IMPORT_FIELDS - set(fieldnames)
                if missing:
                    raise CatalogImportError(f"CSV header is missing required columns: {', '.join(sorted(missing))}.")
                entries: list[CatalogEntry] = []
                for row_number, row in enumerate(reader, start=2):
                    if row is None:
                        continue
                    if all((value is None or str(value).strip() == "") for value in row.values()):
                        continue
                    # Detect irregular rows: DictReader puts extra values under None key
                    if None in row and row[None]:
                        raise CatalogImportError("CSV row has an invalid structure.", row_number=row_number)
                    data: dict[str, object] = {}
                    for field in CSV_FIELDS:
                        if field not in row or row[field] is None:
                            if field == "id":
                                continue
                            data[field] = ""
                            continue
                        value = row[field]
                        if field == "id" and str(value).strip() == "":
                            continue
                        data[field] = value
                    try:
                        entries.append(CatalogEntry(**data))
                    except CatalogValidationError as exc:
                        raise CatalogImportError(
                            f"Invalid catalog entry at row {row_number}.",
                            row_number=row_number,
                        ) from exc
                return entries
        except UnicodeDecodeError as exc:
            raise CatalogFileError("CSV file is not valid UTF-8.") from exc
        except csv.Error as exc:
            raise CatalogFileError(f"Could not read CSV file: {exc}") from exc
        except OSError as exc:
            raise CatalogFileError(f"Could not read CSV file: {exc}") from exc

    def _read_json(self, source_path: Path) -> list[CatalogEntry]:
        try:
            with source_path.open("r", encoding="utf-8") as f:
                document = json.load(f, object_pairs_hook=_detect_duplicate_json_keys)
        except UnicodeDecodeError as exc:
            raise CatalogFileError("JSON file is not valid UTF-8.") from exc
        except json.JSONDecodeError as exc:
            raise CatalogFileError(f"JSON file is not valid: {exc.msg}.") from exc
        except OSError as exc:
            raise CatalogFileError(f"Could not read JSON file: {exc}") from exc

        if not isinstance(document, dict):
            raise CatalogImportError("JSON root must be an object.")
        if "schema_version" not in document:
            raise CatalogImportError("JSON schema_version is required.", field="schema_version")
        version = document["schema_version"]
        if isinstance(version, bool) or not isinstance(version, int) or version != JSON_SCHEMA_VERSION:
            raise CatalogImportError("JSON schema_version must be the integer 1.", field="schema_version")
        if "entries" not in document:
            raise CatalogImportError("JSON entries are required.", field="entries")
        entries_data = document["entries"]
        if not isinstance(entries_data, list):
            raise CatalogImportError("JSON entries must be a list.", field="entries")
        unknown_root = set(document.keys()) - {"schema_version", "entries"}
        if unknown_root:
            raise CatalogImportError(f"JSON root has unknown keys: {', '.join(sorted(unknown_root))}.")

        entries: list[CatalogEntry] = []
        for index, item in enumerate(entries_data):
            if not isinstance(item, dict):
                raise CatalogImportError("JSON entry must be an object.", row_number=index)
            unknown = set(item.keys()) - set(CSV_FIELDS)
            if unknown:
                raise CatalogImportError(
                    f"JSON entry has unknown keys: {', '.join(sorted(unknown))}.",
                    row_number=index,
                )
            missing = REQUIRED_IMPORT_FIELDS - set(item.keys())
            if missing:
                field = sorted(missing)[0]
                raise CatalogImportError(
                    f"JSON entry is missing required field: {field}.",
                    row_number=index,
                    field=field,
                )
            data: dict[str, object] = {}
            for field in CSV_FIELDS:
                if field not in item:
                    if field == "id":
                        continue
                    data[field] = ""
                    continue
                value = item[field]
                if field == "id":
                    if value is None or (isinstance(value, str) and not value.strip()):
                        raise CatalogImportError(
                            "JSON entry id must be a valid UUID v4 when present.",
                            row_number=index,
                            field="id",
                        )
                data[field] = value
            try:
                entries.append(CatalogEntry(**data))
            except CatalogValidationError as exc:
                raise CatalogImportError(
                    f"Invalid catalog entry at index {index}.",
                    row_number=index,
                ) from exc
        return entries

    def export_file(self, destination_path: Path, file_format: str | None = None) -> int:
        fmt = self._resolve_format(destination_path, file_format)
        if not destination_path.parent.exists() or not destination_path.parent.is_dir():
            raise CatalogFileError(f"Destination directory does not exist: {destination_path.parent}")
        total = self._storage.count_entries()
        temp_path: Path | None = None
        try:
            fd, temp_name = tempfile.mkstemp(dir=destination_path.parent, prefix=".catalog_tmp_", suffix=f".{fmt}")
            temp_path = Path(temp_name)
            with os.fdopen(fd, "w", encoding="utf-8", newline="" if fmt == "csv" else "\n") as f:
                if fmt == "csv":
                    self._write_csv(f, total)
                else:
                    self._write_json(f, total)
                f.flush()
                os.fsync(f.fileno())
            os.replace(temp_path, destination_path)
            temp_path = None
            return total
        except CatalogFileError:
            raise
        except OSError as exc:
            raise CatalogFileError(f"Could not export catalog file: {exc}") from exc
        finally:
            if temp_path is not None:
                try:
                    temp_path.unlink(missing_ok=True)
                except OSError:
                    pass

    def _entry_to_dict(self, entry: CatalogEntry) -> dict[str, str]:
        return {field: getattr(entry, field) for field in CSV_FIELDS}

    def _iter_entries(self, total: int):
        offset = 0
        while offset < total:
            page = self._storage.search_entries(limit=EXPORT_PAGE_SIZE, offset=offset)
            if not page:
                break
            for entry in page:
                yield entry
            offset += len(page)

    def _write_csv(self, f, total: int) -> None:
        writer = csv.DictWriter(f, fieldnames=list(CSV_FIELDS))
        writer.writeheader()
        for entry in self._iter_entries(total):
            writer.writerow(self._entry_to_dict(entry))

    def _write_json(self, f, total: int) -> None:
        f.write('{\n  "schema_version": 1,\n  "entries": [')
        first = True
        for entry in self._iter_entries(total):
            if not first:
                f.write(",")
            f.write("\n")
            dumped = json.dumps(self._entry_to_dict(entry), ensure_ascii=False, indent=2)
            indented = "\n".join("    " + line for line in dumped.splitlines())
            f.write(indented)
            first = False
        if not first:
            f.write("\n  ")
        f.write("]\n}\n")
