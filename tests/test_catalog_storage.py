"""Unit tests for catalog SQLite storage."""

try:
    import tests._pcpo_test_isolation_bootstrap  # noqa: F401
except Exception:
    import _pcpo_test_isolation_bootstrap  # type: ignore  # noqa: F401

import json
import os
import sqlite3
import tempfile
import unittest
import uuid
from contextlib import closing
from pathlib import Path
from unittest.mock import patch

from pc_parts_organizer.catalog_models import CatalogEntry, CatalogValidationError
from pc_parts_organizer.catalog_storage import (
    BatchInsertResult,
    CatalogDuplicateError,
    CatalogEntryNotFoundError,
    CatalogStorage,
    CatalogStorageError,
    get_catalog_file_path,
)


class TestCatalogPathsAndInit(unittest.TestCase):
    def _set_base(self, base_dir: Path):
        return patch.dict(os.environ, {"LOCALAPPDATA": str(base_dir)}, clear=False)

    def test_get_catalog_file_path_uses_localappdata(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            local = Path(temp_dir) / "LocalAppData"
            with self._set_base(local):
                result = get_catalog_file_path()
        self.assertEqual(result, local / "PCPartsOrganizer" / "catalog.sqlite3")

    def test_resolving_path_does_not_create_anything(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            local = Path(temp_dir) / "LocalAppData"
            target = local / "PCPartsOrganizer"
            with self._set_base(local):
                path = get_catalog_file_path()
            self.assertFalse(target.exists())
            self.assertFalse(path.exists())

    def test_constructor_does_not_create_folders_or_files(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            db_path = Path(temp_dir) / "LocalAppData" / "PCPartsOrganizer" / "catalog.sqlite3"
            with self._set_base(Path(temp_dir) / "LocalAppData"):
                CatalogStorage()
                CatalogStorage(db_path)
            self.assertFalse(db_path.parent.exists())
            self.assertFalse(db_path.exists())

    def test_initialize_creates_database_and_structure(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            db_path = Path(temp_dir) / "catalog.sqlite3"
            storage = CatalogStorage(db_path)
            storage.initialize()
            self.assertTrue(db_path.exists())
            with closing(sqlite3.connect(db_path)) as conn:
                self.assertEqual(conn.execute("PRAGMA user_version").fetchone()[0], 1)
                columns = {row[1] for row in conn.execute("PRAGMA table_info(catalog_entries)")}
                self.assertIn("manufacturer_key", columns)
                indexes = [row[1] for row in conn.execute("PRAGMA index_list(catalog_entries)")]
                self.assertTrue(any("unique" in i.lower() or "sqlite_autoindex" in i.lower() or i for i in indexes))

    def test_initialize_is_idempotent(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            db_path = Path(temp_dir) / "catalog.sqlite3"
            storage = CatalogStorage(db_path)
            storage.initialize()
            storage.add_entry(CatalogEntry(category="CPU", manufacturer="AMD", model="Ryzen 5"))
            storage.initialize()
            self.assertEqual(storage.count_entries(), 1)

    def test_operations_require_initialized_schema(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            db_path = Path(temp_dir) / "catalog.sqlite3"
            storage = CatalogStorage(db_path)
            with self.assertRaises(CatalogStorageError):
                storage.count_entries()
            with self.assertRaises(CatalogStorageError):
                storage.add_entry(CatalogEntry(category="CPU", manufacturer="A", model="B"))

    def test_does_not_modify_components_json(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            base = Path(temp_dir) / "LocalAppData"
            app_dir = base / "PCPartsOrganizer"
            app_dir.mkdir(parents=True)
            components = app_dir / "components.json"
            original = json.dumps({"schema_version": 1, "components": []}, ensure_ascii=False)
            components.write_text(original, encoding="utf-8")
            with self._set_base(base):
                storage = CatalogStorage()
                storage.initialize()
                storage.add_entry(CatalogEntry(category="CPU", manufacturer="A", model="B"))
            self.assertEqual(components.read_text(encoding="utf-8"), original)

    def test_incompatible_version_not_repaired(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            db_path = Path(temp_dir) / "catalog.sqlite3"
            with closing(sqlite3.connect(db_path)) as conn:
                conn.execute("CREATE TABLE catalog_entries(id TEXT PRIMARY KEY)")
                conn.execute("PRAGMA user_version=99")
                conn.commit()
            before = db_path.read_bytes()
            storage = CatalogStorage(db_path)
            with self.assertRaises(CatalogStorageError):
                storage.initialize()
            self.assertEqual(db_path.read_bytes(), before)

    def test_damaged_sqlite_raises(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            db_path = Path(temp_dir) / "catalog.sqlite3"
            db_path.write_bytes(b"not a sqlite database")
            storage = CatalogStorage(db_path)
            with self.assertRaises(CatalogStorageError):
                storage.initialize()

    def test_path_resolution_failure_raises_catalog_error(self) -> None:
        with patch.dict(os.environ, {"LOCALAPPDATA": "   "}, clear=False):
            with self.assertRaises(CatalogStorageError):
                get_catalog_file_path()


class TestCatalogStorageOperations(unittest.TestCase):
    def _storage(self, temp_dir: str) -> CatalogStorage:
        storage = CatalogStorage(Path(temp_dir) / "catalog.sqlite3")
        storage.initialize()
        return storage

    def test_add_and_get_entry(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            storage = self._storage(temp_dir)
            entry = CatalogEntry(
                category="CPU",
                manufacturer="AMD",
                model="Ryzen 7 7800X3D",
                specifications="spec\nline",
                notes="note",
                source="Vendor",
                source_url="https://example.com/x",
                source_license="MIT",
                attribution="attr\nline",
                verified_at="2026-01-01",
            )
            storage.add_entry(entry)
            loaded = storage.get_entry(entry.id)
            self.assertIsNotNone(loaded)
            assert loaded is not None
            self.assertEqual(loaded.id, entry.id)
            self.assertEqual(loaded.specifications, "spec\nline")
            self.assertEqual(loaded.attribution, "attr\nline")
            self.assertIsNone(storage.get_entry(str(uuid.uuid4())))

    def test_update_entry(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            storage = self._storage(temp_dir)
            entry = CatalogEntry(category="CPU", manufacturer="AMD", model="Ryzen 5")
            storage.add_entry(entry)
            updated = CatalogEntry(
                id=entry.id,
                category="CPU",
                manufacturer="AMD",
                model="Ryzen 5 7600",
                notes="updated",
            )
            storage.update_entry(updated)
            loaded = storage.get_entry(entry.id)
            assert loaded is not None
            self.assertEqual(loaded.model, "Ryzen 5 7600")
            self.assertEqual(loaded.notes, "updated")

    def test_update_nonexistent_raises(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            storage = self._storage(temp_dir)
            entry = CatalogEntry(category="CPU", manufacturer="AMD", model="Ryzen 5")
            with self.assertRaises(CatalogEntryNotFoundError):
                storage.update_entry(entry)

    def test_update_duplicate_key_raises(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            storage = self._storage(temp_dir)
            a = CatalogEntry(category="CPU", manufacturer="AMD", model="A")
            b = CatalogEntry(category="CPU", manufacturer="AMD", model="B")
            storage.add_entry(a)
            storage.add_entry(b)
            with self.assertRaises(CatalogDuplicateError):
                storage.update_entry(CatalogEntry(id=b.id, category="CPU", manufacturer="amd", model="  a  "))

    def test_delete_entry(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            storage = self._storage(temp_dir)
            entry = CatalogEntry(category="GPU", manufacturer="NVIDIA", model="RTX")
            storage.add_entry(entry)
            storage.delete_entry(entry.id)
            self.assertIsNone(storage.get_entry(entry.id))
            with self.assertRaises(CatalogEntryNotFoundError):
                storage.delete_entry(entry.id)

    def test_duplicate_reference_detection(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            storage = self._storage(temp_dir)
            storage.add_entry(CatalogEntry(category="GPU", manufacturer="  Nvidia  ", model="RTX  4070"))
            with self.assertRaises(CatalogDuplicateError):
                storage.add_entry(CatalogEntry(category="gpu", manufacturer="NVIDIA", model="rtx 4070"))

    def test_rejects_incorrect_type(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            storage = self._storage(temp_dir)
            with self.assertRaises(CatalogValidationError):
                storage.add_entry("bad")  # type: ignore[arg-type]

    def test_persists_across_instances(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            db_path = Path(temp_dir) / "catalog.sqlite3"
            storage = CatalogStorage(db_path)
            storage.initialize()
            entry = CatalogEntry(category="RAM", manufacturer="Corsair", model="Vengeance")
            storage.add_entry(entry)
            again = CatalogStorage(db_path)
            loaded = again.get_entry(entry.id)
            self.assertIsNotNone(loaded)
            assert loaded is not None
            self.assertEqual(loaded.id, entry.id)


class TestCatalogBatchInsert(unittest.TestCase):
    def _storage(self, temp_dir: str) -> CatalogStorage:
        storage = CatalogStorage(Path(temp_dir) / "catalog.sqlite3")
        storage.initialize()
        return storage

    def test_valid_batch_and_empty(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            storage = self._storage(temp_dir)
            result = storage.add_entries([])
            self.assertEqual(result, BatchInsertResult(inserted_count=0, duplicate_count=0))
            entries = [
                CatalogEntry(category="CPU", manufacturer="A", model="1"),
                CatalogEntry(category="CPU", manufacturer="A", model="2"),
            ]
            result = storage.add_entries(entries)
            self.assertEqual(result.inserted_count, 2)
            self.assertEqual(result.duplicate_count, 0)
            self.assertEqual(storage.count_entries(), 2)

    def test_internal_duplicates_skip(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            storage = self._storage(temp_dir)
            entries = [
                CatalogEntry(category="CPU", manufacturer="A", model="X"),
                CatalogEntry(category="cpu", manufacturer="a", model=" x "),
            ]
            result = storage.add_entries(entries, skip_duplicates=True)
            self.assertEqual(result.inserted_count, 1)
            self.assertEqual(result.duplicate_count, 1)
            self.assertEqual(storage.count_entries(), 1)

    def test_existing_duplicates_skip(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            storage = self._storage(temp_dir)
            storage.add_entry(CatalogEntry(category="CPU", manufacturer="A", model="X"))
            result = storage.add_entries(
                [CatalogEntry(category="CPU", manufacturer="A", model="X")],
                skip_duplicates=True,
            )
            self.assertEqual(result.inserted_count, 0)
            self.assertEqual(result.duplicate_count, 1)
            self.assertEqual(storage.count_entries(), 1)

    def test_duplicate_without_skip_rolls_back_entire_batch(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            storage = self._storage(temp_dir)
            storage.add_entry(CatalogEntry(category="CPU", manufacturer="A", model="Existing"))
            entries = [
                CatalogEntry(category="CPU", manufacturer="A", model="New1"),
                CatalogEntry(category="CPU", manufacturer="A", model="Existing"),
            ]
            with self.assertRaises(CatalogDuplicateError):
                storage.add_entries(entries, skip_duplicates=False)
            self.assertEqual(storage.count_entries(), 1)
            self.assertEqual(storage.search_entries(query="New1"), [])

    def test_uuid_collision_cancels_batch(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            storage = self._storage(temp_dir)
            same_id = str(uuid.uuid4())
            storage.add_entry(CatalogEntry(id=same_id, category="CPU", manufacturer="A", model="Keep"))
            entries = [
                CatalogEntry(category="GPU", manufacturer="B", model="New"),
                CatalogEntry(id=same_id, category="GPU", manufacturer="C", model="Collision"),
            ]
            with self.assertRaises(CatalogStorageError):
                storage.add_entries(entries, skip_duplicates=True)
            self.assertEqual(storage.count_entries(), 1)
            self.assertEqual(storage.search_entries(query="New"), [])

    def test_invalid_element_cancels_before_write(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            storage = self._storage(temp_dir)
            with self.assertRaises(CatalogValidationError):
                storage.add_entries([CatalogEntry(category="CPU", manufacturer="A", model="1"), "bad"])  # type: ignore[list-item]
            self.assertEqual(storage.count_entries(), 0)


class TestCatalogSearch(unittest.TestCase):
    def _storage(self, temp_dir: str) -> CatalogStorage:
        storage = CatalogStorage(Path(temp_dir) / "catalog.sqlite3")
        storage.initialize()
        data = [
            CatalogEntry(category="GPU", manufacturer="NVIDIA", model="RTX 4070"),
            CatalogEntry(category="CPU", manufacturer="AMD", model="Ryzen 5"),
            CatalogEntry(category="CPU", manufacturer="Intel", model="Core i5"),
            CatalogEntry(category="GPU", manufacturer="AMD", model="RX 7800"),
            CatalogEntry(category="RAM", manufacturer="Corsair", model="Vengeance_Pro"),
            CatalogEntry(category="RAM", manufacturer="Kingston", model="100% Ready"),
        ]
        storage.add_entries(data)
        return storage

    def test_search_by_manufacturer_model_partial_case_insensitive(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            storage = self._storage(temp_dir)
            self.assertEqual(len(storage.search_entries(query="amd")), 2)
            self.assertEqual(len(storage.search_entries(query="core")), 1)
            self.assertEqual(len(storage.search_entries(query="ryz")), 1)

    def test_like_special_chars_are_literal(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            storage = self._storage(temp_dir)
            self.assertEqual(len(storage.search_entries(query="vengeance_pro")), 1)
            self.assertEqual(len(storage.search_entries(query="vengeanceXpro")), 0)
            self.assertEqual(len(storage.search_entries(query="100%")), 1)
            self.assertEqual(len(storage.search_entries(query="100X")), 0)

    def test_category_filter_and_canonical_order(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            storage = self._storage(temp_dir)
            cpus = storage.search_entries(category="CPU")
            self.assertEqual([e.category for e in cpus], ["CPU", "CPU"])
            all_entries = storage.search_entries()
            categories = [e.category for e in all_entries]
            # CPU before GPU before RAM in canonical order
            self.assertLess(categories.index("CPU"), categories.index("GPU"))
            self.assertLess(categories.index("GPU"), categories.index("RAM"))

    def test_pagination_and_count(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            storage = self._storage(temp_dir)
            total = storage.count_entries()
            page1 = storage.search_entries(limit=2, offset=0)
            page2 = storage.search_entries(limit=2, offset=2)
            self.assertEqual(total, 6)
            self.assertEqual(len(page1), 2)
            self.assertEqual(len(page2), 2)
            self.assertNotEqual([e.id for e in page1], [e.id for e in page2])
            self.assertEqual(storage.count_entries(query="amd"), 2)

    def test_validates_limit_offset(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            storage = self._storage(temp_dir)
            with self.assertRaises(CatalogStorageError):
                storage.search_entries(limit=0)
            with self.assertRaises(CatalogStorageError):
                storage.search_entries(limit=501)
            with self.assertRaises(CatalogStorageError):
                storage.search_entries(limit=True)  # type: ignore[arg-type]
            with self.assertRaises(CatalogStorageError):
                storage.search_entries(offset=-1)
            with self.assertRaises(CatalogStorageError):
                storage.search_entries(offset=True)  # type: ignore[arg-type]
            with self.assertRaises(CatalogStorageError):
                storage.search_entries(limit=None, offset=1)


class TestCatalogSearchAllMode(unittest.TestCase):
    def _storage(self, temp_dir: str, count: int = 125) -> tuple[CatalogStorage, list[CatalogEntry]]:
        storage = CatalogStorage(Path(temp_dir) / "catalog.sqlite3")
        storage.initialize()
        entries = [
            CatalogEntry(
                category="CPU" if i % 3 == 0 else ("GPU" if i % 3 == 1 else "RAM"),
                manufacturer=f"Maker{i % 10}",
                model=f"Model {i:04d}",
            )
            for i in range(count)
        ]
        storage.add_entries(entries)
        return storage, entries

    def test_limit_none_returns_all_more_than_100(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            storage, entries = self._storage(temp_dir, count=125)
            result = storage.search_entries(limit=None)
            self.assertEqual(len(result), 125)
            self.assertGreater(len(result), 100)
            self.assertEqual(storage.count_entries(), 125)

    def test_limit_none_no_duplicates_no_missing_preserves_order(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            storage, _ = self._storage(temp_dir, count=125)
            result = storage.search_entries(limit=None)
            ids = [e.id for e in result]
            self.assertEqual(len(ids), len(set(ids)))
            paged_ids: list[str] = []
            offset = 0
            while True:
                page = storage.search_entries(limit=50, offset=offset)
                if not page:
                    break
                paged_ids.extend(e.id for e in page)
                offset += len(page)
            self.assertEqual(ids, paged_ids)

    def test_limit_none_with_filters_and_search(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            storage, _ = self._storage(temp_dir, count=125)
            cpu_total = storage.count_entries(category="CPU")
            cpu_all = storage.search_entries(category="CPU", limit=None)
            self.assertEqual(len(cpu_all), cpu_total)
            self.assertTrue(all(e.category == "CPU" for e in cpu_all))
            q_total = storage.count_entries(query="Model 000")
            q_all = storage.search_entries(query="Model 000", limit=None)
            self.assertEqual(len(q_all), q_total)
            self.assertTrue(all("model 000" in e.model.casefold() for e in q_all))

    def test_limit_none_empty_result(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            storage = CatalogStorage(Path(temp_dir) / "catalog.sqlite3")
            storage.initialize()
            self.assertEqual(storage.search_entries(limit=None), [])
            self.assertEqual(storage.count_entries(), 0)


if __name__ == "__main__":
    unittest.main()
