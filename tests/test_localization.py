"""Unit tests for localization and language preferences."""

try:
    import tests._pcpo_test_isolation_bootstrap  # noqa: F401
except Exception:
    import _pcpo_test_isolation_bootstrap  # type: ignore  # noqa: F401

import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from pc_parts_organizer.localization import (
    DEFAULT_LANGUAGE,
    LANGUAGE_NAMES,
    LocalizationError,
    SUPPORTED_LANGUAGES,
    Translator,
)
from pc_parts_organizer.models import CATEGORIES
from pc_parts_organizer.storage import StorageError, get_settings_file_path


class TestLocalizationResources(unittest.TestCase):
    def _set_base(self, base_dir: Path):
        return patch.dict(os.environ, {"LOCALAPPDATA": str(base_dir)}, clear=False)

    def test_loads_spanish_and_english(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            with self._set_base(Path(temp_dir) / "LocalAppData"):
                translator = Translator()
                self.assertEqual(translator.current_language, "es")
                translator.set_language("en")
                self.assertEqual(translator.current_language, "en")

    def test_resource_keys_match_and_not_empty(self) -> None:
        locales = Path(__file__).resolve().parents[1] / "pc_parts_organizer" / "locales"
        es = json.loads((locales / "es.json").read_text(encoding="utf-8"))
        en = json.loads((locales / "en.json").read_text(encoding="utf-8"))

        def collect(data, prefix=""):
            if isinstance(data, dict):
                result = set()
                for key, value in data.items():
                    full = f"{prefix}.{key}" if prefix else key
                    if isinstance(value, dict):
                        result.update(collect(value, full))
                    else:
                        result.add(full)
                return result
            return {prefix}

        self.assertEqual(collect(es), collect(en))
        for data in (es, en):
            for key in collect(data):
                current = data
                for part in key.split("."):
                    current = current[part]
                if key == "schema_version":
                    self.assertIsInstance(current, int)
                    self.assertGreaterEqual(current, 1)
                else:
                    self.assertIsInstance(current, str)
                    self.assertTrue(current.strip())

    def test_all_categories_present_in_both_languages(self) -> None:
        locales = Path(__file__).resolve().parents[1] / "pc_parts_organizer" / "locales"
        for name in ("es.json", "en.json"):
            data = json.loads((locales / name).read_text(encoding="utf-8"))
            self.assertEqual(set(data["categories"].keys()), set(CATEGORIES))
            self.assertEqual(len(data["categories"]), 11)

    def test_translates_texts_and_categories(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            with self._set_base(Path(temp_dir) / "LocalAppData"):
                translator = Translator()
                self.assertEqual(translator.t("app.section_title"), "Inventario")
                self.assertEqual(translator.translate_category("Motherboard"), "Placa base")
                translator.set_language("en")
                self.assertEqual(translator.t("app.section_title"), "Inventory")
                self.assertEqual(translator.translate_category("Motherboard"), "Motherboard")

    def test_unknown_key_raises_controlled_error(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            with self._set_base(Path(temp_dir) / "LocalAppData"):
                translator = Translator()
                with self.assertRaises(LocalizationError):
                    translator.t("app.does_not_exist")

    def test_unsupported_language_raises_controlled_error(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            with self._set_base(Path(temp_dir) / "LocalAppData"):
                translator = Translator()
                with self.assertRaises(LocalizationError):
                    translator.set_language("fr")

    def test_localized_label_to_canonical_category(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            with self._set_base(Path(temp_dir) / "LocalAppData"):
                translator = Translator()
                self.assertEqual(translator.category_from_label("Placa base"), "Motherboard")
                translator.set_language("en")
                self.assertEqual(translator.category_from_label("Graphics card"), "GPU")


class TestLanguagePreferences(unittest.TestCase):
    def _set_base(self, base_dir: Path):
        return patch.dict(os.environ, {"LOCALAPPDATA": str(base_dir)}, clear=False)

    def _settings_path(self, base_dir: Path) -> Path:
        return base_dir / "PCPartsOrganizer" / "settings.json"

    def test_missing_settings_defaults_to_spanish_and_creates_nothing(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            base = Path(temp_dir) / "LocalAppData"
            with self._set_base(base):
                translator = Translator()
            self.assertEqual(translator.current_language, DEFAULT_LANGUAGE)
            self.assertFalse(self._settings_path(base).exists())
            self.assertFalse(self._settings_path(base).parent.exists())

    def test_valid_spanish_and_english_preferences_load(self) -> None:
        for language in ("es", "en"):
            with self.subTest(language=language):
                with tempfile.TemporaryDirectory() as temp_dir:
                    base = Path(temp_dir) / "LocalAppData"
                    path = self._settings_path(base)
                    path.parent.mkdir(parents=True)
                    path.write_text(json.dumps({"schema_version": 1, "language": language}), encoding="utf-8")
                    with self._set_base(base):
                        translator = Translator()
                    self.assertEqual(translator.current_language, language)

    def test_invalid_or_corrupt_preferences_fallback_to_spanish_without_repair(self) -> None:
        cases = [
            (b"", "empty"),
            (b"{bad", "corrupt"),
            (b"\xff\xfe", "invalid utf8"),
            (json.dumps({"schema_version": 1, "language": "fr"}).encode("utf-8"), "unknown"),
            (json.dumps({"schema_version": 2, "language": "en"}).encode("utf-8"), "schema"),
            (json.dumps([]).encode("utf-8"), "structure"),
        ]
        for raw, name in cases:
            with self.subTest(case=name):
                with tempfile.TemporaryDirectory() as temp_dir:
                    base = Path(temp_dir) / "LocalAppData"
                    path = self._settings_path(base)
                    path.parent.mkdir(parents=True)
                    path.write_bytes(raw)
                    before = path.read_bytes()
                    with self._set_base(base):
                        translator = Translator()
                    self.assertEqual(translator.current_language, "es")
                    self.assertEqual(path.read_bytes(), before)

    def test_startup_does_not_create_settings_or_components(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            base = Path(temp_dir) / "LocalAppData"
            with self._set_base(base):
                Translator()
                from pc_parts_organizer.service import InventoryService

                InventoryService()
            app_dir = base / "PCPartsOrganizer"
            self.assertFalse((app_dir / "settings.json").exists())
            self.assertFalse((app_dir / "components.json").exists())

    def test_change_language_persists_and_new_instance_recovers(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            base = Path(temp_dir) / "LocalAppData"
            with self._set_base(base):
                translator = Translator()
                translator.change_language("en")
                document = json.loads(self._settings_path(base).read_text(encoding="utf-8"))
                self.assertEqual(document, {"schema_version": 1, "language": "en"})
                recovered = Translator()
            self.assertEqual(recovered.current_language, "en")

    def test_save_failure_keeps_previous_language_and_cleans_temp(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            base = Path(temp_dir) / "LocalAppData"
            with self._set_base(base):
                translator = Translator()
                with patch("pc_parts_organizer.storage.os.replace", side_effect=OSError("boom")):
                    with self.assertRaises(StorageError):
                        translator.change_language("en")
            self.assertEqual(translator.current_language, "es")
            settings = self._settings_path(base)
            if settings.parent.exists():
                leftovers = [p for p in settings.parent.iterdir() if p.name != "settings.json"]
                self.assertEqual(leftovers, [])

    def test_does_not_touch_components_json(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            base = Path(temp_dir) / "LocalAppData"
            components = base / "PCPartsOrganizer" / "components.json"
            components.parent.mkdir(parents=True)
            components.write_text('{"schema_version": 1, "components": []}', encoding="utf-8")
            before = components.read_bytes()
            with self._set_base(base):
                translator = Translator()
                translator.change_language("en")
            self.assertEqual(components.read_bytes(), before)

    def test_settings_path_uses_localappdata_without_creating(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            base = Path(temp_dir) / "LocalAppData"
            with self._set_base(base):
                path = get_settings_file_path()
            self.assertEqual(path, base / "PCPartsOrganizer" / "settings.json")
            self.assertFalse(path.parent.exists())

    def test_public_constants(self) -> None:
        self.assertEqual(DEFAULT_LANGUAGE, "es")
        self.assertEqual(SUPPORTED_LANGUAGES, ("es", "en"))
        self.assertIn("es", LANGUAGE_NAMES)
        self.assertIn("en", LANGUAGE_NAMES)


if __name__ == "__main__":
    unittest.main()
