"""SQLite persistence for catalog references."""

from __future__ import annotations

import sqlite3
from contextlib import closing
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

from pc_parts_organizer.catalog_models import (
    CatalogEntry,
    CatalogValidationError,
    catalog_duplicate_key,
)
from pc_parts_organizer.models import CATEGORIES
from pc_parts_organizer.storage import StorageError, get_data_directory

CATALOG_FILE_NAME = "catalog.sqlite3"
CATALOG_SCHEMA_VERSION = 1
CATALOG_COLUMNS = (
    "id",
    "category",
    "manufacturer",
    "model",
    "manufacturer_key",
    "model_key",
    "specifications",
    "notes",
    "source",
    "source_url",
    "source_license",
    "attribution",
    "verified_at",
)
_CATEGORY_ORDER_SQL = "CASE category " + " ".join(
    f"WHEN ? THEN {index}" for index, _ in enumerate(CATEGORIES)
) + " ELSE 999 END"


class CatalogStorageError(Exception):
    """Raised for controlled catalog storage errors."""


class CatalogDuplicateError(CatalogStorageError):
    """Raised when a catalog reference duplicates an existing key."""


class CatalogEntryNotFoundError(LookupError):
    """Raised when a catalog entry does not exist."""


@dataclass(frozen=True)
class BatchInsertResult:
    """Result of a batch catalog insert."""

    inserted_count: int
    duplicate_count: int


def get_catalog_file_path() -> Path:
    """Return the catalog SQLite path without creating it."""
    try:
        return get_data_directory() / CATALOG_FILE_NAME
    except StorageError as exc:
        raise CatalogStorageError("Could not resolve catalog data directory.") from exc


def _normalize_like_query(query: str) -> str:
    # Escape LIKE metacharacters; ESCAPE '\\' used in SQL.
    return query.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def _validate_limit(limit: object) -> int | None:
    if limit is None:
        return None
    if isinstance(limit, bool) or not isinstance(limit, int) or not (1 <= limit <= 500):
        raise CatalogStorageError("limit must be an integer between 1 and 500, or None for all results.")
    return limit


def _validate_offset(offset: object) -> int:
    if isinstance(offset, bool) or not isinstance(offset, int) or offset < 0:
        raise CatalogStorageError("offset must be an integer greater than or equal to 0.")
    return offset


def _validate_category_filter(category: str | None) -> str | None:
    if category is None:
        return None
    if not isinstance(category, str):
        raise CatalogStorageError("category filter must be a string or None.")
    # Accept canonical or normalizable input? Safer to normalize via model rules.
    try:
        return CatalogEntry(category=category, manufacturer="X", model="Y").category
    except CatalogValidationError as exc:
        raise CatalogStorageError(f"Invalid category filter: {exc}") from exc


def _row_to_entry(row: sqlite3.Row) -> CatalogEntry:
    return CatalogEntry(
        id=row["id"],
        category=row["category"],
        manufacturer=row["manufacturer"],
        model=row["model"],
        specifications=row["specifications"],
        notes=row["notes"],
        source=row["source"],
        source_url=row["source_url"],
        source_license=row["source_license"],
        attribution=row["attribution"],
        verified_at=row["verified_at"],
    )


class CatalogStorage:
    """Manage catalog SQLite persistence."""

    def __init__(self, database_path: Path | None = None) -> None:
        self._database_path = database_path if database_path is not None else get_catalog_file_path()

    @property
    def database_path(self) -> Path:
        return self._database_path

    def _connect(self) -> sqlite3.Connection:
        try:
            conn = sqlite3.connect(self._database_path)
        except sqlite3.Error as exc:
            raise CatalogStorageError(f"Could not open catalog database: {exc}") from exc
        conn.row_factory = sqlite3.Row
        try:
            conn.execute("PRAGMA foreign_keys = ON")
        except sqlite3.Error:
            pass
        return conn

    def _require_compatible_schema(self, conn: sqlite3.Connection) -> None:
        try:
            version = conn.execute("PRAGMA user_version").fetchone()[0]
        except sqlite3.Error as exc:
            raise CatalogStorageError(f"Could not read catalog schema version: {exc}") from exc
        if version != CATALOG_SCHEMA_VERSION:
            raise CatalogStorageError("Catalog database schema is incompatible.")
        try:
            tables = {
                row[0]
                for row in conn.execute(
                    "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
                ).fetchall()
            }
        except sqlite3.Error as exc:
            raise CatalogStorageError(f"Could not inspect catalog schema: {exc}") from exc
        if "catalog_entries" not in tables:
            raise CatalogStorageError("Catalog database schema is incompatible.")
        try:
            columns = [row[1] for row in conn.execute("PRAGMA table_info(catalog_entries)").fetchall()]
        except sqlite3.Error as exc:
            raise CatalogStorageError(f"Could not inspect catalog columns: {exc}") from exc
        if tuple(columns) != CATALOG_COLUMNS and set(columns) != set(CATALOG_COLUMNS):
            # Accept same column set in any order? spec states columns; require set presence.
            missing = set(CATALOG_COLUMNS) - set(columns)
            if missing:
                raise CatalogStorageError("Catalog database schema is incompatible.")
        try:
            index_rows = conn.execute("PRAGMA index_list(catalog_entries)").fetchall()
            has_unique = False
            for row in index_rows:
                if row["unique"]:
                    idx_name = row["name"]
                    idx_cols = [r[2] for r in conn.execute(f"PRAGMA index_info('{idx_name}')").fetchall()]
                    if idx_cols == ["category", "manufacturer_key", "model_key"]:
                        has_unique = True
                        break
            if not has_unique:
                raise CatalogStorageError("Catalog database schema is incompatible.")
            integrity = conn.execute("PRAGMA integrity_check").fetchone()[0]
            if integrity != "ok":
                raise CatalogStorageError("Catalog database is damaged.")
        except sqlite3.DatabaseError as exc:
            raise CatalogStorageError(f"Catalog database is damaged or incompatible: {exc}") from exc

    def initialize(self) -> None:
        try:
            self._database_path.parent.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            raise CatalogStorageError(f"Could not create catalog data directory: {exc}") from exc

        conn: sqlite3.Connection | None = None
        try:
            conn = self._connect()
            # Detect damaged file early
            conn.execute("PRAGMA integrity_check").fetchone()
            version = conn.execute("PRAGMA user_version").fetchone()[0]
            tables = conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
            ).fetchall()
            if not tables and version == 0:
                self._create_schema(conn)
                return
            self._require_compatible_schema(conn)
        except sqlite3.DatabaseError as exc:
            raise CatalogStorageError(f"Catalog database is damaged or incompatible: {exc}") from exc
        except CatalogStorageError:
            raise
        except OSError as exc:
            raise CatalogStorageError(f"Could not initialize catalog database: {exc}") from exc
        finally:
            if conn is not None:
                conn.close()

    def _create_schema(self, conn: sqlite3.Connection) -> None:
        try:
            conn.execute("BEGIN")
            conn.execute(
                """
                CREATE TABLE catalog_entries (
                    id TEXT PRIMARY KEY,
                    category TEXT NOT NULL,
                    manufacturer TEXT NOT NULL,
                    model TEXT NOT NULL,
                    manufacturer_key TEXT NOT NULL,
                    model_key TEXT NOT NULL,
                    specifications TEXT NOT NULL DEFAULT '',
                    notes TEXT NOT NULL DEFAULT '',
                    source TEXT NOT NULL DEFAULT '',
                    source_url TEXT NOT NULL DEFAULT '',
                    source_license TEXT NOT NULL DEFAULT '',
                    attribution TEXT NOT NULL DEFAULT '',
                    verified_at TEXT NOT NULL DEFAULT '',
                    UNIQUE(category, manufacturer_key, model_key)
                )
                """
            )
            conn.execute(
                "CREATE INDEX idx_catalog_category ON catalog_entries(category)"
            )
            conn.execute(
                "CREATE INDEX idx_catalog_search ON catalog_entries(manufacturer_key, model_key)"
            )
            conn.execute(f"PRAGMA user_version={CATALOG_SCHEMA_VERSION}")
            conn.commit()
        except sqlite3.Error as exc:
            try:
                conn.rollback()
            except sqlite3.Error:
                pass
            raise CatalogStorageError(f"Could not create catalog schema: {exc}") from exc

    def _entry_params(self, entry: CatalogEntry) -> tuple[object, ...]:
        _, mkey, pkey = catalog_duplicate_key(entry)
        return (
            entry.id,
            entry.category,
            entry.manufacturer,
            entry.model,
            mkey,
            pkey,
            entry.specifications,
            entry.notes,
            entry.source,
            entry.source_url,
            entry.source_license,
            entry.attribution,
            entry.verified_at,
        )

    def add_entry(self, entry: CatalogEntry) -> None:
        if not isinstance(entry, CatalogEntry):
            raise CatalogValidationError("entry must be a CatalogEntry.")
        normalized = CatalogEntry(**entry.__dict__)  # revalidate/copy
        with closing(self._connect()) as conn:
            self._require_compatible_schema(conn)
            try:
                conn.execute(
                    """
                    INSERT INTO catalog_entries (
                        id, category, manufacturer, model, manufacturer_key, model_key,
                        specifications, notes, source, source_url, source_license, attribution, verified_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    self._entry_params(normalized),
                )
                conn.commit()
            except sqlite3.IntegrityError as exc:
                msg = str(exc).lower()
                if "category" in msg and ("manufacturer_key" in msg or "model_key" in msg or "unique" in msg):
                    raise CatalogDuplicateError("Catalog reference already exists.") from exc
                if "id" in msg or "primary key" in msg:
                    raise CatalogStorageError(f"Catalog ID collision: {exc}") from exc
                raise CatalogDuplicateError("Catalog reference already exists.") from exc
            except sqlite3.Error as exc:
                raise CatalogStorageError(f"Could not add catalog entry: {exc}") from exc

    def add_entries(self, entries: Iterable[CatalogEntry], skip_duplicates: bool = False) -> BatchInsertResult:
        items = list(entries)
        if not items:
            with closing(self._connect()) as conn:
                self._require_compatible_schema(conn)
            return BatchInsertResult(inserted_count=0, duplicate_count=0)

        normalized_items: list[CatalogEntry] = []
        for item in items:
            if not isinstance(item, CatalogEntry):
                raise CatalogValidationError("entries must contain CatalogEntry objects.")
            normalized_items.append(CatalogEntry(**item.__dict__))

        seen_ref_keys: set[tuple[str, str, str]] = set()
        seen_ids: set[str] = set()
        for entry in normalized_items:
            if entry.id in seen_ids:
                raise CatalogStorageError("Duplicate UUID in batch.")
            seen_ids.add(entry.id)
            rkey = catalog_duplicate_key(entry)
            if rkey in seen_ref_keys and not skip_duplicates:
                raise CatalogDuplicateError("Duplicate catalog reference in batch.")
            seen_ref_keys.add(rkey)

        with closing(self._connect()) as conn:
            self._require_compatible_schema(conn)
            try:
                conn.execute("BEGIN IMMEDIATE")
                existing_ref_keys: set[tuple[str, str, str]] = set()
                if skip_duplicates:
                    # Load existing keys for categories in batch (bounded) to avoid full-table scan in common import use.
                    cats = sorted({e.category for e in normalized_items}, key=lambda c: CATEGORIES.index(c))
                    placeholders = ",".join("?" for _ in cats)
                    rows = conn.execute(
                        f"SELECT category, manufacturer_key, model_key FROM catalog_entries WHERE category IN ({placeholders})",
                        cats,
                    ).fetchall()
                    existing_ref_keys = {(r["category"], r["manufacturer_key"], r["model_key"]) for r in rows}

                inserted = 0
                duplicates = 0
                batch_ref_seen: set[tuple[str, str, str]] = set()
                for entry in normalized_items:
                    rkey = catalog_duplicate_key(entry)
                    if rkey in batch_ref_seen or rkey in existing_ref_keys:
                        if not skip_duplicates:
                            raise CatalogDuplicateError("Duplicate catalog reference in batch.")
                        duplicates += 1
                        continue
                    try:
                        conn.execute(
                            """
                            INSERT INTO catalog_entries (
                                id, category, manufacturer, model, manufacturer_key, model_key,
                                specifications, notes, source, source_url, source_license, attribution, verified_at
                            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                            """,
                            self._entry_params(entry),
                        )
                    except sqlite3.IntegrityError as exc:
                        msg = str(exc).lower()
                        if "id" in msg or "primary key" in msg:
                            raise CatalogStorageError(f"Catalog ID collision: {exc}") from exc
                        if skip_duplicates:
                            duplicates += 1
                            continue
                        raise CatalogDuplicateError("Duplicate catalog reference in batch.") from exc
                    batch_ref_seen.add(rkey)
                    existing_ref_keys.add(rkey)
                    inserted += 1
                conn.commit()
                return BatchInsertResult(inserted_count=inserted, duplicate_count=duplicates)
            except (CatalogDuplicateError, CatalogStorageError, CatalogValidationError):
                try:
                    conn.rollback()
                except sqlite3.Error:
                    pass
                raise
            except sqlite3.Error as exc:
                try:
                    conn.rollback()
                except sqlite3.Error:
                    pass
                raise CatalogStorageError(f"Could not add catalog entries: {exc}") from exc

    def get_entry(self, entry_id: str) -> CatalogEntry | None:
        with closing(self._connect()) as conn:
            self._require_compatible_schema(conn)
            try:
                row = conn.execute(
                    "SELECT * FROM catalog_entries WHERE id = ?",
                    (entry_id,),
                ).fetchone()
            except sqlite3.Error as exc:
                raise CatalogStorageError(f"Could not read catalog entry: {exc}") from exc
        return _row_to_entry(row) if row is not None else None

    def update_entry(self, entry: CatalogEntry) -> None:
        if not isinstance(entry, CatalogEntry):
            raise CatalogValidationError("entry must be a CatalogEntry.")
        normalized = CatalogEntry(**entry.__dict__)
        with closing(self._connect()) as conn:
            self._require_compatible_schema(conn)
            try:
                conn.execute("BEGIN IMMEDIATE")
                current = conn.execute(
                    "SELECT id FROM catalog_entries WHERE id = ?",
                    (normalized.id,),
                ).fetchone()
                if current is None:
                    raise CatalogEntryNotFoundError(f"Catalog entry not found: {normalized.id}")
                _, mkey, pkey = catalog_duplicate_key(normalized)
                conn.execute(
                    """
                    UPDATE catalog_entries
                    SET category = ?, manufacturer = ?, model = ?, manufacturer_key = ?, model_key = ?,
                        specifications = ?, notes = ?, source = ?, source_url = ?, source_license = ?,
                        attribution = ?, verified_at = ?
                    WHERE id = ?
                    """,
                    (
                        normalized.category,
                        normalized.manufacturer,
                        normalized.model,
                        mkey,
                        pkey,
                        normalized.specifications,
                        normalized.notes,
                        normalized.source,
                        normalized.source_url,
                        normalized.source_license,
                        normalized.attribution,
                        normalized.verified_at,
                        normalized.id,
                    ),
                )
                conn.commit()
            except sqlite3.IntegrityError as exc:
                try:
                    conn.rollback()
                except sqlite3.Error:
                    pass
                raise CatalogDuplicateError("Catalog reference already exists.") from exc
            except CatalogEntryNotFoundError:
                try:
                    conn.rollback()
                except sqlite3.Error:
                    pass
                raise
            except sqlite3.Error as exc:
                try:
                    conn.rollback()
                except sqlite3.Error:
                    pass
                raise CatalogStorageError(f"Could not update catalog entry: {exc}") from exc

    def delete_entry(self, entry_id: str) -> None:
        with closing(self._connect()) as conn:
            self._require_compatible_schema(conn)
            try:
                conn.execute("BEGIN IMMEDIATE")
                cursor = conn.execute("DELETE FROM catalog_entries WHERE id = ?", (entry_id,))
                if cursor.rowcount == 0:
                    raise CatalogEntryNotFoundError(f"Catalog entry not found: {entry_id}")
                conn.commit()
            except CatalogEntryNotFoundError:
                try:
                    conn.rollback()
                except sqlite3.Error:
                    pass
                raise
            except sqlite3.Error as exc:
                try:
                    conn.rollback()
                except sqlite3.Error:
                    pass
                raise CatalogStorageError(f"Could not delete catalog entry: {exc}") from exc

    def _build_filters(self, query: str, category: str | None) -> tuple[str, list[object]]:
        clauses: list[str] = []
        params: list[object] = []
        normalized_category = _validate_category_filter(category)
        if normalized_category is not None:
            clauses.append("category = ?")
            params.append(normalized_category)
        if query:
            like = f"%{_normalize_like_query(query.casefold())}%"
            clauses.append("(manufacturer_key LIKE ? ESCAPE '\\' OR model_key LIKE ? ESCAPE '\\')")
            params.extend([like, like])
        where = f" WHERE {' AND '.join(clauses)}" if clauses else ""
        return where, params

    def search_entries(
        self,
        query: str = "",
        category: str | None = None,
        limit: int | None = 100,
        offset: int = 0,
    ) -> list[CatalogEntry]:
        limit_value = _validate_limit(limit)
        offset_value = _validate_offset(offset)
        if limit_value is None and offset_value != 0:
            raise CatalogStorageError("offset must be 0 when requesting all results.")
        where, params = self._build_filters(query, category)
        order = f" ORDER BY {_CATEGORY_ORDER_SQL}, manufacturer_key COLLATE NOCASE, model_key COLLATE NOCASE, id"
        sql = "SELECT * FROM catalog_entries" + where + order
        sql_params = list(params) + list(CATEGORIES)
        if limit_value is not None:
            sql += " LIMIT ? OFFSET ?"
            sql_params.extend([limit_value, offset_value])
        with closing(self._connect()) as conn:
            self._require_compatible_schema(conn)
            try:
                rows = conn.execute(sql, sql_params).fetchall()
            except sqlite3.Error as exc:
                raise CatalogStorageError(f"Could not search catalog entries: {exc}") from exc
        return [_row_to_entry(row) for row in rows]

    def count_entries(self, query: str = "", category: str | None = None) -> int:
        where, params = self._build_filters(query, category)
        sql = "SELECT COUNT(*) FROM catalog_entries" + where
        with closing(self._connect()) as conn:
            self._require_compatible_schema(conn)
            try:
                row = conn.execute(sql, params).fetchone()
            except sqlite3.Error as exc:
                raise CatalogStorageError(f"Could not count catalog entries: {exc}") from exc
        return int(row[0]) if row else 0
