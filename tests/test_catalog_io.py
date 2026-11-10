"""Unit tests for catalog CSV/JSON import and export."""

try:
    import tests._pcpo_test_isolation_bootstrap  # noqa: F401
except Exception:
    import _pcpo_test_isolation_bootstrap  # type: ignore  # noqa: F401

import csv
import json
import os
import tempfile
import unittest
from contextlib import closing
from pathlib import Path
from unittest.mock import patch

from pc_parts_organizer.catalog_io import (
    CatalogFileError,
    CatalogFileService,
    CatalogImportError,
    CatalogImportResult,
)
from pc_parts_organizer.catalog_models import CatalogEntry
from pc_parts_organizer.catalog_storage import CatalogDuplicateError, CatalogStorage

CSV_FIELDS = [
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
]


class CatalogIOTestCase(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.base = Path(self._tmp.name)
        self.db_path = self.base / "catalog.sqlite3"
        self.storage = CatalogStorage(self.db_path)
        self.storage.initialize()
        self.service = CatalogFileService(self.storage)
        self.components_path = self.base / "components.json"
        self.components_path.write_text('{"schema_version":1,"components":[]}', encoding="utf-8")

    def assert_components_unchanged(self) -> None:
        self.assertEqual(
            self.components_path.read_text(encoding="utf-8"),
            '{"schema_version":1,"components":[]}',
        )

    def _write_csv(self, name: str, rows: list[dict], fieldnames=None, raw: bytes | None = None) -> Path:
        path = self.base / name
        if raw is not None:
            path.write_bytes(raw)
            return path
        with path.open("w", encoding="utf-8", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames or CSV_FIELDS)
            writer.writeheader()
            for row in rows:
                writer.writerow(row)
        return path

    def _write_json(self, name: str, data, raw: bytes | None = None) -> Path:
        path = self.base / name
        if raw is not None:
            path.write_bytes(raw)
            return path
        path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        return path

    def _json_doc(self, entries):
        return {"schema_version": 1, "entries": entries}


class TestImportCSV(CatalogIOTestCase):
    def test_import_valid_single_and_multiple(self) -> None:
        path = self._write_csv("a.csv", [{"category": "CPU", "manufacturer": "AMD", "model": "R5"}])
        result = self.service.import_file(path)
        self.assertEqual(result, CatalogImportResult(total_entries=1, inserted_count=1, duplicate_count=0))
        path2 = self._write_csv("b.csv", [
            {"category": "CPU", "manufacturer": "Intel", "model": "i5"},
            {"category": "GPU", "manufacturer": "NVIDIA", "model": "4070"},
        ])
        result2 = self.service.import_file(path2)
        self.assertEqual(result2.inserted_count, 2)
        self.assertEqual(self.storage.count_entries(), 3)

    def test_bom_different_order_optional_absent_multiline_unicode_empty_rows(self) -> None:
        raw = ("\ufeffmodel,manufacturer,category,notes\n"
               "Ryzen,AMD,CPU,\"line1\nline2\"\n"
               ",,\n"
               "Predator,OEM \u00e1\u00e9\u00ed\u00f3\u00fa,Monitor,\n").encode("utf-8")
        path = self._write_csv("bom.csv", [], raw=raw)
        result = self.service.import_file(path)
        self.assertEqual(result.inserted_count, 2)
        entries = self.storage.search_entries()
        self.assertTrue(any("\u00e1\u00e9\u00ed\u00f3\u00fa" in e.manufacturer for e in entries))
        self.assertTrue(any("line1\nline2" in e.notes for e in entries))

    def test_missing_required_header_duplicate_unknown_irregular(self) -> None:
        with self.assertRaises(CatalogImportError):
            self.service.import_file(self._write_csv("h.csv", [], fieldnames=["category", "manufacturer"]))
        dup = self.base / "dup.csv"
        dup.write_text("category,category,manufacturer,model\nCPU,CPU,A,B\n", encoding="utf-8")
        with self.assertRaises(CatalogImportError):
            self.service.import_file(dup)
        unk = self.base / "unk.csv"
        unk.write_text("category,manufacturer,model,extra\nCPU,A,B,X\n", encoding="utf-8")
        with self.assertRaises(CatalogImportError):
            self.service.import_file(unk)
        irr = self.base / "irr.csv"
        irr.write_text("category,manufacturer,model\nCPU,A\n", encoding="utf-8")
        with self.assertRaises((CatalogImportError, CatalogFileError)):
            self.service.import_file(irr)

    def test_invalid_data_utf8_and_missing_file(self) -> None:
        self._write_csv("c.csv", [{"category": "SoundCard", "manufacturer": "A", "model": "B"}])
        with self.assertRaises(CatalogImportError):
            self.service.import_file(self.base / "c.csv")
        self._write_csv("id.csv", [{"id": "bad", "category": "CPU", "manufacturer": "A", "model": "B"}])
        with self.assertRaises(CatalogImportError):
            self.service.import_file(self.base / "id.csv")
        self._write_csv("date.csv", [{"category": "CPU", "manufacturer": "A", "model": "B", "verified_at": "2024/01/01"}])
        with self.assertRaises(CatalogImportError):
            self.service.import_file(self.base / "date.csv")
        self._write_csv("url.csv", [{"category": "CPU", "manufacturer": "A", "model": "B", "source_url": "ftp://x"}])
        with self.assertRaises(CatalogImportError):
            self.service.import_file(self.base / "url.csv")
        self._write_csv("badutf.csv", [], raw=b"\xff\xfe\x00")
        with self.assertRaises(CatalogFileError):
            self.service.import_file(self.base / "badutf.csv")
        with self.assertRaises(CatalogFileError):
            self.service.import_file(self.base / "missing.csv")


class TestImportJSON(CatalogIOTestCase):
    def test_valid_multiple_optional_absent_omitted_uuid_unicode(self) -> None:
        path = self._write_json("ok.json", self._json_doc([
            {"category": "CPU", "manufacturer": "AMD", "model": "R5"},
            {"category": "GPU", "manufacturer": "Ñvidia", "model": "X", "notes": "línea"},
        ]))
        result = self.service.import_file(path)
        self.assertEqual(result.inserted_count, 2)
        self.assertTrue(all(e.id for e in self.storage.search_entries()))

    def test_root_schema_entries_and_record_errors(self) -> None:
        cases = [
            ([], "root"),
            ({"schema_version": 1}, "entries missing"),
            ({"schema_version": 2, "entries": []}, "schema"),
            ({"schema_version": True, "entries": []}, "bool"),
            ({"schema_version": 1.0, "entries": []}, "float"),
            ({"schema_version": 1, "entries": {}}, "entries type"),
            ({"schema_version": 1, "entries": ["x"]}, "record type"),
            ({"schema_version": 1, "entries": [{"manufacturer": "A", "model": "B"}]}, "missing field"),
            ({"schema_version": 1, "entries": [{"category": "CPU", "manufacturer": "A", "model": "B", "extra": 1}]}, "unknown"),
            ({"schema_version": 1, "entries": [{"category": "CPU", "manufacturer": 1, "model": "B"}]}, "type"),
            ({"schema_version": 1, "entries": [{"id": "", "category": "CPU", "manufacturer": "A", "model": "B"}]}, "empty id"),
        ]
        for data, name in cases:
            with self.subTest(name=name):
                path = self._write_json(f"{name}.json", data)
                with self.assertRaises((CatalogImportError, CatalogFileError)):
                    self.service.import_file(path)

    def test_duplicate_json_keys_malformed_empty(self) -> None:
        path = self.base / "dupkeys.json"
        path.write_text('{"schema_version":1,"schema_version":1,"entries":[]}', encoding="utf-8")
        with self.assertRaises(CatalogFileError):
            self.service.import_file(path)
        self._write_json("bad.json", None, raw=b"{bad")
        with self.assertRaises(CatalogFileError):
            self.service.import_file(self.base / "bad.json")
        self._write_json("empty.json", None, raw=b"")
        with self.assertRaises(CatalogFileError):
            self.service.import_file(self.base / "empty.json")

    def test_invalid_record_has_context(self) -> None:
        path = self._write_json("ctx.json", self._json_doc([
            {"category": "CPU", "manufacturer": "A", "model": "B"},
            {"category": "CPU", "manufacturer": "A", "model": ""},
        ]))
        with self.assertRaises(CatalogImportError) as ctx:
            self.service.import_file(path)
        self.assertIsNotNone(ctx.exception.row_number)


class TestDuplicatesAndTransactions(CatalogIOTestCase):
    def test_skip_duplicates_counts(self) -> None:
        self.storage.add_entry(CatalogEntry(category="CPU", manufacturer="A", model="X"))
        path = self._write_json("d.json", self._json_doc([
            {"category": "CPU", "manufacturer": "A", "model": "X"},
            {"category": "CPU", "manufacturer": "A", "model": " x "},
            {"category": "CPU", "manufacturer": "A", "model": "Y"},
        ]))
        result = self.service.import_file(path, skip_duplicates=True)
        self.assertEqual(result, CatalogImportResult(total_entries=3, inserted_count=1, duplicate_count=2))
        self.assertEqual(self.storage.count_entries(), 2)

    def test_skip_false_rolls_back(self) -> None:
        path = self._write_json("r.json", self._json_doc([
            {"category": "CPU", "manufacturer": "A", "model": "1"},
            {"category": "CPU", "manufacturer": "A", "model": "1"},
        ]))
        with self.assertRaises(CatalogDuplicateError):
            self.service.import_file(path, skip_duplicates=False)
        self.assertEqual(self.storage.count_entries(), 0)

    def test_uuid_collision_aborts(self) -> None:
        import uuid
        same = str(uuid.uuid4())
        self.storage.add_entry(CatalogEntry(id=same, category="CPU", manufacturer="A", model="Keep"))
        path = self._write_json("u.json", self._json_doc([
            {"category": "GPU", "manufacturer": "B", "model": "New"},
            {"id": same, "category": "GPU", "manufacturer": "C", "model": "Collision"},
        ]))
        with self.assertRaises(Exception):
            self.service.import_file(path, skip_duplicates=True)
        self.assertEqual(self.storage.count_entries(), 1)
        self.assertEqual(self.storage.search_entries(query="New"), [])

    def test_invalid_record_leaves_catalog_unchanged(self) -> None:
        path = self._write_json("inv.json", self._json_doc([
            {"category": "CPU", "manufacturer": "A", "model": "B"},
            {"category": "Nope", "manufacturer": "A", "model": "B"},
        ]))
        with self.assertRaises(CatalogImportError):
            self.service.import_file(path)
        self.assertEqual(self.storage.count_entries(), 0)
        self.assert_components_unchanged()


class TestExportCSV(CatalogIOTestCase):
    def test_export_empty_one_many_and_round_trip(self) -> None:
        out = self.base / "out.csv"
        self.assertEqual(self.service.export_file(out), 0)
        with out.open(encoding="utf-8", newline="") as f:
            reader = csv.DictReader(f)
            self.assertEqual(reader.fieldnames, CSV_FIELDS)
            self.assertEqual(list(reader), [])

        entry = CatalogEntry(
            category="CPU", manufacturer="AMD á", model="Ryzen", specifications="a\nb",
            notes="n", source="s", source_url="https://example.com/x", source_license="L",
            attribution="at", verified_at="2026-01-01",
        )
        self.storage.add_entry(entry)
        out2 = self.base / "out2.csv"
        self.assertEqual(self.service.export_file(out2), 1)
        with out2.open(encoding="utf-8", newline="") as f:
            rows = list(csv.DictReader(f))
        self.assertEqual(rows[0]["manufacturer"], "AMD á")
        self.assertEqual(rows[0]["specifications"], "a\nb")

        self.storage.add_entry(CatalogEntry(category="GPU", manufacturer="N", model="M"))
        out3 = self.base / "out3.csv"
        self.service.export_file(out3)
        fresh_db = self.base / "fresh.sqlite3"
        fresh = CatalogStorage(fresh_db)
        fresh.initialize()
        fresh_service = CatalogFileService(fresh)
        fresh_service.import_file(out3)
        self.assertEqual(fresh.count_entries(), 2)


class TestExportJSON(CatalogIOTestCase):
    def test_export_structure_and_round_trip(self) -> None:
        out = self.base / "out.json"
        self.assertEqual(self.service.export_file(out), 0)
        data = json.loads(out.read_text(encoding="utf-8"))
        self.assertEqual(data, {"schema_version": 1, "entries": []})

        self.storage.add_entry(CatalogEntry(category="CPU", manufacturer="AMD á", model="R", source="src"))
        out2 = self.base / "out2.json"
        self.service.export_file(out2)
        data = json.loads(out2.read_text(encoding="utf-8"))
        self.assertEqual(data["schema_version"], 1)
        self.assertEqual(set(data["entries"][0].keys()), set(CSV_FIELDS))
        self.assertEqual(data["entries"][0]["manufacturer"], "AMD á")

        self.storage.add_entry(CatalogEntry(category="GPU", manufacturer="N", model="M"))
        out3 = self.base / "out3.json"
        self.service.export_file(out3)
        fresh = CatalogStorage(self.base / "f2.sqlite3")
        fresh.initialize()
        CatalogFileService(fresh).import_file(out3)
        self.assertEqual(fresh.count_entries(), 2)


class TestPaginationAndSafety(CatalogIOTestCase):
    def test_exports_over_500_in_pages(self) -> None:
        entries = [CatalogEntry(category="CPU", manufacturer="M", model=f"Model {i:04d}") for i in range(501)]
        self.storage.add_entries(entries)
        out = self.base / "many.csv"
        with patch.object(self.storage, "search_entries", wraps=self.storage.search_entries) as mocked:
            count = self.service.export_file(out)
        self.assertEqual(count, 501)
        self.assertGreaterEqual(mocked.call_count, 2)
        self.assertEqual(self.storage.count_entries(), 501)

    def test_failure_preserves_previous_and_cleans_temp(self) -> None:
        dest = self.base / "dest.json"
        dest.write_text("original", encoding="utf-8")
        self.storage.add_entry(CatalogEntry(category="CPU", manufacturer="A", model="B"))
        for target in ("pc_parts_organizer.catalog_io.os.fsync", "pc_parts_organizer.catalog_io.os.replace"):
            with self.subTest(target=target):
                with patch(target, side_effect=OSError("boom")):
                    with self.assertRaises(CatalogFileError):
                        self.service.export_file(dest)
                self.assertEqual(dest.read_text(encoding="utf-8"), "original")
                leftovers = [p for p in self.base.iterdir() if p.name.startswith(".catalog_tmp") or p.suffix == ".tmp"]
                self.assertEqual(leftovers, [])

        # simulated write failure
        with patch("pc_parts_organizer.catalog_io.json.dumps", side_effect=OSError("boom")):
            with self.assertRaises(CatalogFileError):
                self.service.export_file(dest)
        self.assertEqual(dest.read_text(encoding="utf-8"), "original")

    def test_unknown_format_missing_dir_and_components_unchanged(self) -> None:
        with self.assertRaises(CatalogFileError):
            self.service.export_file(self.base / "x.txt")
        with self.assertRaises(CatalogFileError):
            self.service.export_file(self.base / "missing" / "x.csv")
        self._write_json("x.json", self._json_doc([{"category": "CPU", "manufacturer": "A", "model": "B"}]))
        self.service.import_file(self.base / "x.json")
        self.assert_components_unchanged()


if __name__ == "__main__":
    unittest.main()
