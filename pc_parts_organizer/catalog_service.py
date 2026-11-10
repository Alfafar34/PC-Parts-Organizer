"""Application service facade for catalog operations.

This layer centralizes catalog access for future UI code so it depends on a
stable service contract instead of SQLite details or file import/export internals.
It delegates persistence and file handling to injected/catalog components and
propagates public errors unchanged.
"""

from __future__ import annotations

from pathlib import Path

from pc_parts_organizer.catalog_io import (
    CatalogFileError,
    CatalogFileService,
    CatalogImportError,
    CatalogImportResult,
)
from pc_parts_organizer.catalog_models import CatalogEntry, CatalogValidationError
from pc_parts_organizer.catalog_storage import (
    CatalogDuplicateError,
    CatalogEntryNotFoundError,
    CatalogStorage,
    CatalogStorageError,
)

__all__ = [
    "CatalogService",
    "CatalogValidationError",
    "CatalogStorageError",
    "CatalogDuplicateError",
    "CatalogEntryNotFoundError",
    "CatalogFileError",
    "CatalogImportError",
    "CatalogImportResult",
]


class CatalogService:
    """Facade for catalog CRUD, search, and file import/export."""

    def __init__(self, storage: CatalogStorage) -> None:
        self._storage = storage
        self._file_service = CatalogFileService(storage)

    def initialize(self) -> None:
        self._storage.initialize()

    def add_entry(self, entry: CatalogEntry) -> None:
        self._storage.add_entry(entry)

    def get_entry(self, entry_id: str) -> CatalogEntry | None:
        return self._storage.get_entry(entry_id)

    def update_entry(self, entry: CatalogEntry) -> None:
        self._storage.update_entry(entry)

    def delete_entry(self, entry_id: str) -> None:
        self._storage.delete_entry(entry_id)

    def search_entries(
        self,
        query: str = "",
        category: str | None = None,
        limit: int | None = 100,
        offset: int = 0,
    ) -> list[CatalogEntry]:
        return self._storage.search_entries(
            query=query,
            category=category,
            limit=limit,
            offset=offset,
        )

    def count_entries(self, query: str = "", category: str | None = None) -> int:
        return self._storage.count_entries(query=query, category=category)

    def import_file(
        self,
        source_path: Path,
        file_format: str | None = None,
        skip_duplicates: bool = True,
    ) -> CatalogImportResult:
        return self._file_service.import_file(
            source_path,
            file_format=file_format,
            skip_duplicates=skip_duplicates,
        )

    def export_file(self, destination_path: Path, file_format: str | None = None) -> int:
        return self._file_service.export_file(destination_path, file_format=file_format)
