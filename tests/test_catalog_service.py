"""Unit tests for CatalogService."""

try:
    import tests._pcpo_test_isolation_bootstrap  # noqa: F401
except Exception:
    import _pcpo_test_isolation_bootstrap  # type: ignore  # noqa: F401

import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from pc_parts_organizer.catalog_io import CatalogFileService, CatalogImportResult
from pc_parts_organizer.catalog_models import CatalogEntry
from pc_parts_organizer.catalog_service import (
    CatalogDuplicateError,
    CatalogEntryNotFoundError,
    CatalogFileError,
    CatalogImportError,
    CatalogService,
    CatalogStorageError,
    CatalogValidationError,
)
from pc_parts_organizer.catalog_storage import CatalogStorage


class TestCatalogServiceConstruction(unittest.TestCase):
    def test_uses_injected_storage_and_shares_with_file_service(self) -> None:
        storage = Mock(spec=CatalogStorage)
        service = CatalogService(storage)
        self.assertIs(service._storage, storage)
        self.assertIsInstance(service._file_service, CatalogFileService)
        self.assertIs(service._file_service._storage, storage)

    def test_constructor_does_not_initialize_or_touch_filesystem(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            db_path = Path(temp_dir) / "nested" / "catalog.sqlite3"
            storage = Mock(spec=CatalogStorage)
            CatalogService(storage)
            storage.initialize.assert_not_called()
            self.assertFalse(db_path.parent.exists())


class TestCatalogServiceDelegation(unittest.TestCase):
    def setUp(self) -> None:
        self.storage = Mock(spec=CatalogStorage)
        self.service = CatalogService(self.storage)
        self.entry = CatalogEntry(category="CPU", manufacturer="AMD", model="Ryzen")

    def test_initialize_delegates_once_and_propagates(self) -> None:
        self.service.initialize()
        self.storage.initialize.assert_called_once_with()
        self.storage.initialize.side_effect = CatalogStorageError("boom")
        with self.assertRaises(CatalogStorageError):
            self.service.initialize()

    def test_crud_delegation(self) -> None:
        self.service.add_entry(self.entry)
        self.storage.add_entry.assert_called_once_with(self.entry)

        self.storage.get_entry.return_value = self.entry
        result = self.service.get_entry("id-1")
        self.storage.get_entry.assert_called_once_with("id-1")
        self.assertIs(result, self.entry)

        self.service.update_entry(self.entry)
        self.storage.update_entry.assert_called_once_with(self.entry)

        self.service.delete_entry("id-2")
        self.storage.delete_entry.assert_called_once_with("id-2")

    def test_crud_exceptions_propagate(self) -> None:
        cases = [
            (self.storage.add_entry, CatalogValidationError("x")),
            (self.storage.add_entry, CatalogDuplicateError("x")),
            (self.storage.update_entry, CatalogEntryNotFoundError("x")),
            (self.storage.delete_entry, CatalogStorageError("x")),
        ]
        for method, exc in cases:
            with self.subTest(exc=type(exc).__name__):
                method.side_effect = exc
                with self.assertRaises(type(exc)):
                    if method is self.storage.add_entry:
                        self.service.add_entry(self.entry)
                    elif method is self.storage.update_entry:
                        self.service.update_entry(self.entry)
                    else:
                        self.service.delete_entry("id")
                method.side_effect = None

    def test_search_and_count_delegate_without_modification(self) -> None:
        expected = [self.entry]
        self.storage.search_entries.return_value = expected
        self.storage.count_entries.return_value = 7
        result = self.service.search_entries(query="amd", category="CPU", limit=10, offset=5)
        self.storage.search_entries.assert_called_once_with(query="amd", category="CPU", limit=10, offset=5)
        self.assertIs(result, expected)
        count = self.service.count_entries(query="amd", category="CPU")
        self.storage.count_entries.assert_called_once_with(query="amd", category="CPU")
        self.assertEqual(count, 7)

    def test_search_all_delegates_limit_none(self) -> None:
        expected = [self.entry]
        self.storage.search_entries.return_value = expected
        result = self.service.search_entries(query="", category=None, limit=None, offset=0)
        self.storage.search_entries.assert_called_once_with(query="", category=None, limit=None, offset=0)
        self.assertIs(result, expected)

    def test_import_export_delegate_to_file_service(self) -> None:
        import_result = CatalogImportResult(total_entries=2, inserted_count=1, duplicate_count=1)
        with patch.object(self.service._file_service, "import_file", return_value=import_result) as imp:
            with patch.object(self.service._file_service, "export_file", return_value=3) as exp:
                result = self.service.import_file(Path("in.csv"), file_format="csv", skip_duplicates=False)
                count = self.service.export_file(Path("out.json"), file_format="json")
        imp.assert_called_once_with(Path("in.csv"), file_format="csv", skip_duplicates=False)
        exp.assert_called_once_with(Path("out.json"), file_format="json")
        self.assertIs(result, import_result)
        self.assertEqual(count, 3)

    def test_file_service_uses_same_storage_instance(self) -> None:
        with patch("pc_parts_organizer.catalog_service.CatalogFileService") as mocked:
            storage = Mock(spec=CatalogStorage)
            CatalogService(storage)
            mocked.assert_called_once_with(storage)


class TestCatalogServiceArchitecture(unittest.TestCase):
    def test_module_has_no_ui_sql_or_direct_file_access(self) -> None:
        from pathlib import Path as P

        source = P("pc_parts_organizer/catalog_service.py").read_text(encoding="utf-8")
        self.assertNotIn("tkinter", source.lower())
        self.assertNotIn("messagebox", source)
        self.assertNotIn("sqlite3", source)
        self.assertNotIn("components.json", source)
        self.assertNotIn("settings.json", source)
        self.assertNotIn("open(", source)

    def test_reexports(self) -> None:
        from pc_parts_organizer.catalog_service import CatalogImportResult as CIR

        self.assertIs(CIR, CatalogImportResult)
        self.assertTrue(issubclass(CatalogFileError, Exception))
        self.assertTrue(issubclass(CatalogImportError, CatalogFileError))


class TestCatalogServiceIntegration(unittest.TestCase):
    def test_end_to_end_with_temporary_sqlite(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            db_path = Path(temp_dir) / "catalog.sqlite3"
            components = Path(temp_dir) / "components.json"
            components.write_text('{"schema_version":1,"components":[]}', encoding="utf-8")
            before = components.read_bytes()
            storage = CatalogStorage(db_path)
            service = CatalogService(storage)
            service.initialize()
            entry = CatalogEntry(category="CPU", manufacturer="AMD", model="Ryzen 5")
            service.add_entry(entry)
            found = service.search_entries(query="Ryzen")
            self.assertEqual(len(found), 1)
            loaded = service.get_entry(entry.id)
            self.assertIsNotNone(loaded)
            again = CatalogService(CatalogStorage(db_path))
            persisted = again.get_entry(entry.id)
            self.assertIsNotNone(persisted)
            self.assertEqual(components.read_bytes(), before)


if __name__ == "__main__":
    unittest.main()
