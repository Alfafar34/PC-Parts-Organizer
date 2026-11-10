"""CSV import to inventory (T17.22).

Parser tests use synthetic fixtures only; service tests use isolated TEMP
storage via the fail-closed bootstrap. No real data, no writes to real paths.
"""

from __future__ import annotations

try:
    import tests._pcpo_test_isolation_bootstrap  # noqa: F401
except Exception:
    import _pcpo_test_isolation_bootstrap  # type: ignore  # noqa: F401

import csv
import io
import json
import os
import string
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from pc_parts_organizer.csv_inventory_import import (
    CANONICAL_HEADERS,
    CsvInventoryImportError,
    analyze_csv,
    csv_template_text,
    detect_delimiter,
    detect_encoding,
    normalize_header,
    resolve_columns,
)
from pc_parts_organizer.models import Component
from pc_parts_organizer.service import (
    BatchValidationError,
    InventoryService,
    StorageError,
)
from pc_parts_organizer.storage import save_project_state


def _write(tmp: Path, name: str, data: bytes) -> Path:
    p = tmp / name
    p.write_bytes(data)
    return p


def _csv_bytes(rows: list[list[str]], delim: str = ",", encoding: str = "utf-8") -> bytes:
    buf = io.StringIO()
    writer = csv.writer(buf, delimiter=delim, lineterminator="\n")
    writer.writerows(rows)
    return buf.getvalue().encode(encoding)


class TestCsvParsing(unittest.TestCase):
    def setUp(self):
        self._td = tempfile.TemporaryDirectory()
        self._tmp = Path(self._td.name)

    def tearDown(self):
        self._td.cleanup()

    def test_comma_utf8_canonical(self):
        p = _write(self._tmp, "a.csv", _csv_bytes([
            list(CANONICAL_HEADERS),
            ["CPU", "AMD", "Ryzen 5", "6C/12T", "nota"],
        ]))
        a = analyze_csv(p)
        self.assertEqual(a.valid_count, 1)
        self.assertEqual(a.components[0]["manufacturer"], "AMD")
        self.assertEqual(a.rejected_count, 0)

    def test_semicolon_and_tab(self):
        for delim, name in ((";", "semi.csv"), ("\t", "tab.csv")):
            p = _write(self._tmp, name, _csv_bytes(
                [list(CANONICAL_HEADERS), ["RAM", "Corsair", "16GB", "DDR4", ""]], delim=delim))
            a = analyze_csv(p)
            self.assertEqual(a.delimiter, delim)
            self.assertEqual(a.valid_count, 1, delim)

    def test_utf8_bom(self):
        data = _csv_bytes([list(CANONICAL_HEADERS), ["CPU", "AMD", "Ryzen 7", "", ""]])
        p = _write(self._tmp, "bom.csv", b"\xef\xbb\xbf" + data)
        a = analyze_csv(p)
        self.assertEqual(a.encoding, "utf-8-sig")
        self.assertEqual(a.valid_count, 1)

    def test_utf16_bom(self):
        data = _csv_bytes([list(CANONICAL_HEADERS), ["CPU", "AMD", "Ryzen 9", "", ""]])
        p = _write(self._tmp, "u16.csv", b"\xff\xfe" + data.decode("utf-8").encode("utf-16-le"))
        a = analyze_csv(p)
        self.assertEqual(a.encoding, "utf-16")
        self.assertEqual(a.valid_count, 1)

    def test_cp1252_spanish(self):
        text = 'category,manufacturer,model,specs,notes\nCPU,Intel,Core i5,"3,4 GHz","Ordenador ñandú"\n'
        p = _write(self._tmp, "ansi.csv", text.encode("cp1252"))
        a = analyze_csv(p)
        self.assertEqual(a.encoding, "cp1252")
        self.assertEqual(a.components[0]["notes"], "Ordenador ñandú")

    def test_quoted_separators_and_newlines(self):
        text = ('category,manufacturer,model,specs,notes\n'
                'CPU,AMD,Ryzen,"6C/12T, 3.5GHz","línea1\nlínea2"\n')
        p = _write(self._tmp, "q.csv", text.encode("utf-8"))
        a = analyze_csv(p)
        self.assertEqual(a.valid_count, 1)
        self.assertEqual(a.components[0]["specifications"], "6C/12T, 3.5GHz")
        self.assertIn("línea1", a.components[0]["notes"])

    def test_aliases_es_en_and_reorder(self):
        text = ("modelo,fabricante,categoría,notas,especificaciones\n"
                "X1,Maker,CPU,nota,spec\n")
        p = _write(self._tmp, "alias.csv", text.encode("utf-8"))
        a = analyze_csv(p)
        self.assertEqual(a.valid_count, 1)
        self.assertEqual(a.columns["category"], "categoría")
        self.assertEqual(a.components[0]["model"], "X1")

    def test_duplicate_headers_rejected(self):
        p = _write(self._tmp, "dup.csv", b"category,manufacturer,model,model\nCPU,A,B,C\n")
        with self.assertRaises(CsvInventoryImportError) as ctx:
            analyze_csv(p)
        self.assertIn("duplicate header", str(ctx.exception))

    def test_missing_required_header(self):
        p = _write(self._tmp, "miss.csv", b"manufacturer,model\nAMD,Ryzen\n")
        with self.assertRaises(CsvInventoryImportError) as ctx:
            analyze_csv(p)
        self.assertIn("missing required headers", str(ctx.exception))

    def test_unknown_columns_ignored_and_reported(self):
        p = _write(self._tmp, "unk.csv",
                   b"category,manufacturer,model,specs,notes,verified_at,source\n"
                   b"CPU,AMD,Ryzen,,,verified,shop\n")
        a = analyze_csv(p)
        self.assertEqual(a.valid_count, 1)
        self.assertIn("verified_at", a.ignored_columns)
        self.assertIn("source", a.ignored_columns)
        # provenance/verification columns never become attributes
        self.assertNotIn("verified_at", a.components[0])

    def test_empty_rows_and_short_rows(self):
        text = ("category,manufacturer,model,specs,notes\n"
                "CPU,AMD,Ryzen 5,,\n"
                "\n"
                "GPU,N,X1\n")
        p = _write(self._tmp, "rows.csv", text.encode("utf-8"))
        a = analyze_csv(p)
        self.assertEqual(a.empty_rows, [3])
        self.assertEqual(a.valid_count, 2)
        self.assertTrue(any("padded" in w for w in a.warnings))

    def test_too_many_columns(self):
        p = _write(self._tmp, "wide.csv", b"category,manufacturer,model\nCPU,AMD,Ryzen,extra\n")
        a = analyze_csv(p)
        self.assertEqual(a.rejected_count, 1)
        self.assertIn("too_many_columns", a.rejected[0].reasons[0])

    def test_empty_and_headerless_files(self):
        p = _write(self._tmp, "empty.csv", b"")
        with self.assertRaises(CsvInventoryImportError):
            analyze_csv(p)
        p2 = _write(self._tmp, "headerless.csv", b"\n\n")
        with self.assertRaises(CsvInventoryImportError) as ctx:
            analyze_csv(p2)
        self.assertIn("missing required headers", str(ctx.exception))

    def test_invalid_category_and_missing_fields(self):
        p = _write(self._tmp, "bad.csv", b"category,manufacturer,model\nNope,A,B\nCPU,,B\nCPU,A,\n")
        a = analyze_csv(p)
        self.assertEqual(a.rejected_count, 3)
        self.assertEqual(a.valid_count, 0)

    def test_encoding_override_and_delimiter_override(self):
        text = "category;manufacturer;model\nCPU;AMD;Ryzen\n"
        p = _write(self._tmp, "semi.csv", text.encode("utf-8"))
        a = analyze_csv(p, encoding="utf-8", delimiter=";")
        self.assertEqual(a.valid_count, 1)

    def test_detect_helpers(self):
        self.assertEqual(detect_encoding(b"\xef\xbb\xbfabc"), "utf-8-sig")
        self.assertEqual(detect_encoding("ñ".encode("utf-8")), "utf-8")
        self.assertEqual(detect_encoding("ñ".encode("cp1252")), "cp1252")
        self.assertEqual(detect_delimiter("a,b,c\n1,2,3", "utf-8"), ",")
        self.assertEqual(detect_delimiter("a;b;c\n1;2;3", "utf-8"), ";")
        self.assertEqual(normalize_header("  Fabricante "), "fabricante")

    def test_resolve_columns_problems(self):
        cols, ignored, problems = resolve_columns(["category", "manufacturer", "model"])
        self.assertEqual(problems, [])
        self.assertEqual(cols["category"], "category")
        _, _, problems = resolve_columns(["category", "categoria", "model"])
        self.assertIn("duplicate header", problems[0])

    def test_template_is_valid_and_ignores_examples(self):
        text = csv_template_text()
        rows = list(csv.reader(io.StringIO(text)))
        self.assertEqual(rows[0], list(CANONICAL_HEADERS))
        self.assertTrue(all(r[0] for r in rows[1:]))

    def test_total_rows_counts_data_lines(self):
        p = _write(self._tmp, "n.csv", _csv_bytes([
            list(CANONICAL_HEADERS),
            ["CPU", "AMD", "A", "", ""],
            ["", "", "", "", ""],
            ["GPU", "N", "X1", "", ""],
        ]))
        a = analyze_csv(p)
        self.assertEqual(a.total_rows, 3)
        self.assertEqual(a.empty_rows, [3])

    def test_limits(self):
        big = b"category,manufacturer,model\n" + b"CPU,A,B\n" * 60_000
        p = _write(self._tmp, "big.csv", big)
        with self.assertRaises(CsvInventoryImportError) as ctx:
            analyze_csv(p)
        self.assertIn("too_many_rows", str(ctx.exception))


class TestCsvDuplicates(unittest.TestCase):
    def setUp(self):
        self._td = tempfile.TemporaryDirectory()
        self._tmp = Path(self._td.name)

    def tearDown(self):
        self._td.cleanup()

    def test_inventory_and_internal_duplicates(self):
        p = _write(self._tmp, "d.csv", _csv_bytes([
            list(CANONICAL_HEADERS),
            ["CPU", "AMD", "Ryzen 9", "", ""],
            ["CPU", "amd", "  ryzen   9 ", "", ""],
            ["CPU", "AMD", "Ryzen 5", "", ""],
            ["CPU", "Intel", "i5", "", ""],
        ]))
        inv = [Component(category="CPU", manufacturer="AMD", model="Ryzen 5")]
        a = analyze_csv(p, inventory_components=inv)
        self.assertEqual(a.valid_count, 2)
        self.assertEqual(a.inventory_duplicate_count, 1)
        self.assertEqual(a.internal_duplicate_count, 1)
        self.assertEqual(a.internal_duplicates[0].duplicate_lines, [2, 3])
        self.assertEqual(a.inventory_duplicates[0].duplicate_of, "AMD Ryzen 5")

    def test_lowercase_category_matches_canonical_duplicate(self):
        p = _write(self._tmp, "case.csv", _csv_bytes([
            list(CANONICAL_HEADERS),
            ["cpu", "AMD", "Ryzen 9", "", ""],
            ["CPU", "amd", "RYZEN 9", "", ""],
        ]))
        inv = [Component(category="CPU", manufacturer="AMD", model="Ryzen 9")]
        a = analyze_csv(p, inventory_components=inv)
        # both rows collapse onto the same canonical identity: inventory dups
        self.assertEqual(a.valid_count, 0)
        self.assertEqual(a.inventory_duplicate_count, 2)
        self.assertEqual(a.internal_duplicate_count, 0)

    def test_internal_duplicate_case_insensitive(self):
        p = _write(self._tmp, "case2.csv", _csv_bytes([
            list(CANONICAL_HEADERS),
            ["ram", "Corsair", "Vengeance 16GB", "", ""],
            ["RAM", "CORSAIR", "vengeance  16gb", "", ""],
        ]))
        a = analyze_csv(p)
        self.assertEqual(a.valid_count, 1)
        self.assertEqual(a.internal_duplicate_count, 1)

    def test_line_numbers_preserved(self):
        p = _write(self._tmp, "l.csv", _csv_bytes([
            list(CANONICAL_HEADERS),
            ["CPU", "AMD", "A", "", ""],
            ["", "", "", "", ""],
            ["CPU", "AMD", "B", "", ""],
        ]))
        a = analyze_csv(p)
        self.assertEqual([e.line for e in a.valid_new], [2, 4])


class _ServiceCase(unittest.TestCase):
    def setUp(self):
        self._td = tempfile.TemporaryDirectory()
        self._base = Path(self._td.name)
        with patch.dict(os.environ, {"LOCALAPPDATA": str(self._base)}):
            save_project_state([], [], [])

    def tearDown(self):
        self._td.cleanup()

    def _service(self):
        with patch.dict(os.environ, {"LOCALAPPDATA": str(self._base)}):
            return InventoryService()

    def _env(self):
        return patch.dict(os.environ, {"LOCALAPPDATA": str(self._base)})


class TestCsvServiceIntegration(_ServiceCase):
    def test_preview_matches_commit_and_no_write(self):
        s = self._service()
        items = [{"category": "CPU", "manufacturer": "AMD", "model": "Ryzen"}]
        before = len(s.get_components())
        with patch("pc_parts_organizer.service.save_project_state") as sp:
            preview = s.preview_add_components(items)
        self.assertEqual(len(preview.created), 1)
        self.assertEqual(len(s.get_components()), before)
        sp.assert_not_called()

    def test_preview_aborts_on_invalid(self):
        s = self._service()
        with self._env():
            with self.assertRaises(BatchValidationError):
                s.preview_add_components([{"category": "Nope", "manufacturer": "", "model": ""}])

    def test_commit_single_commit_and_profiles_preserved(self):
        s = self._service()
        c = s.add_component("RAM", "Keep", "K-1")
        from pc_parts_organizer.technical_profiles import TechnicalAttribute, TechnicalProfile

        s.set_technical_profile(TechnicalProfile(component_id=c.id, attributes=[
            TechnicalAttribute(key="memory_generation", value="DDR4")]))
        items = [{"category": "CPU", "manufacturer": f"M{i}", "model": f"X{i}"} for i in range(5)]
        with patch("pc_parts_organizer.service.save_project_state",
                   wraps=__import__("pc_parts_organizer.service", fromlist=["save_project_state"]).save_project_state) as sp:
            with self._env():
                result = s.add_components(items)
        self.assertEqual(sp.call_count, 1)
        self.assertEqual(len(result.created), 5)
        self.assertEqual(len(s.get_technical_profiles()), 1)

    def test_no_commit_when_all_duplicates(self):
        s = self._service()
        s.add_component("CPU", "AMD", "Ryzen")
        with patch("pc_parts_organizer.service.save_project_state") as sp:
            with self._env():
                result = s.add_components([{"category": "CPU", "manufacturer": "amd", "model": "ryzen"}])
        sp.assert_not_called()
        self.assertEqual(result.created, [])
        self.assertEqual(len(result.duplicates), 1)

    def test_persistence_failure_keeps_memory(self):
        s = self._service()
        before = len(s.get_components())
        with patch("pc_parts_organizer.service.save_project_state", side_effect=StorageError("disk")):
            with self._env():
                with self.assertRaises(StorageError):
                    s.add_components([{"category": "CPU", "manufacturer": "A", "model": "M"}])
        self.assertEqual(len(s.get_components()), before)

    def test_end_to_end_csv_to_commit(self):
        p = Path(self._td.name) / "e2e.csv"
        buf = io.StringIO()
        writer = csv.writer(buf, lineterminator="\n")
        writer.writerow(CANONICAL_HEADERS)
        writer.writerow(["CPU", "AMD", "Ryzen 5", "6C", ""])
        writer.writerow(["CPU", "amd", "  ryzen   5 ", "", ""])
        writer.writerow(["GPU", "N", "X1", "", ""])
        writer.writerow(["Nope", "", "", "", ""])
        p.write_bytes(buf.getvalue().encode("utf-8"))
        s = self._service()
        s.add_component("CPU", "AMD", "Ryzen 5")
        analysis = analyze_csv(p, inventory_components=s.get_components())
        self.assertEqual(analysis.valid_count, 1)
        self.assertEqual(analysis.inventory_duplicate_count, 2)
        self.assertEqual(analysis.internal_duplicate_count, 0)
        self.assertEqual(analysis.rejected_count, 1)
        with patch("pc_parts_organizer.service.save_project_state",
                   wraps=__import__("pc_parts_organizer.service", fromlist=["save_project_state"]).save_project_state) as sp:
            with self._env():
                result = s.add_components(analysis.components)
        self.assertEqual(sp.call_count, 1)
        self.assertEqual(len(result.created), 1)
        self.assertEqual(len(s.get_components()), 2)


class TestCsvEpistemology(unittest.TestCase):
    def setUp(self):
        self._td = tempfile.TemporaryDirectory()
        self._tmp = Path(self._td.name)

    def tearDown(self):
        self._td.cleanup()

    def test_no_profiles_evidence_or_provenance_in_import(self):
        p = _write(self._tmp, "e.csv", b"category,manufacturer,model,specs,notes,verified_at,source\n"
                                     b"CPU,AMD,Ryzen,,,2026-01-01,Shop\n")
        a = analyze_csv(p)
        comp = a.components[0]
        self.assertEqual(set(comp.keys()), {"category", "manufacturer", "model", "specifications", "notes"})
        for forbidden in ("verified_at", "source", "source_url", "license", "attribution",
                          "profile", "verified", "evidence"):
            self.assertNotIn(forbidden, comp)
        self.assertEqual(comp["notes"], "")


class TestCsvLocales(unittest.TestCase):
    def test_parity_and_placeholders(self):
        repo = Path(__file__).resolve().parents[1] / "pc_parts_organizer" / "locales"
        es = json.load(open(repo / "es.json", encoding="utf-8"))
        en = json.load(open(repo / "en.json", encoding="utf-8"))
        self.assertIn("csv_import", es)
        self.assertIn("csv_import", en)
        for key in es["csv_import"]:
            self.assertIn(key, en["csv_import"])
        for key in en["csv_import"]:
            self.assertIn(key, es["csv_import"])
        for key, val in en["csv_import"].items():
            if not isinstance(val, str):
                continue
            pe = {f for _, f, _, _ in string.Formatter().parse(val) if f}
            ps = {f for _, f, _, _ in string.Formatter().parse(es["csv_import"][key]) if f}
            self.assertEqual(pe, ps, key)


if __name__ == "__main__":
    unittest.main()
