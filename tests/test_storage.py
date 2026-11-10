"""Unit tests for PC Parts Organizer storage path resolution and JSON loading."""

try:
    import tests._pcpo_test_isolation_bootstrap  # noqa: F401
except Exception:
    import _pcpo_test_isolation_bootstrap  # type: ignore  # noqa: F401

import hashlib
import json
import os
import tempfile
import unittest
import uuid
from pathlib import Path
from unittest.mock import patch

from pc_parts_organizer.models import Component
from pc_parts_organizer.storage import (
    StorageError,
    get_components_file_path,
    get_data_directory,
    get_settings_file_path,
    load_components,
    load_language_preference,
    save_components,
    save_language_preference,
    read_inventory_file,
    export_inventory,
    create_pre_restore_backup,
    get_components_file_path,
)


class TestStoragePaths(unittest.TestCase):
    def test_resolves_data_directory_from_valid_localappdata(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            local_app_data = Path(temp_dir) / "LocalAppData"
            with patch.dict(os.environ, {"LOCALAPPDATA": str(local_app_data)}, clear=False):
                result = get_data_directory()
            self.assertEqual(result, local_app_data / "PCPartsOrganizer")

    def test_resolves_components_json_path(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            local_app_data = Path(temp_dir) / "LocalAppData"
            with patch.dict(os.environ, {"LOCALAPPDATA": str(local_app_data)}, clear=False):
                result = get_components_file_path()
            self.assertEqual(
                result,
                local_app_data / "PCPartsOrganizer" / "components.json",
            )

    def test_does_not_depend_on_current_working_directory(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            local_app_data = Path(temp_dir) / "LocalAppData"
            other_cwd = Path(temp_dir) / "other-cwd"
            other_cwd.mkdir()
            original_cwd = Path.cwd()
            try:
                os.chdir(other_cwd)
                with patch.dict(
                    os.environ, {"LOCALAPPDATA": str(local_app_data)}, clear=False
                ):
                    result = get_components_file_path()
            finally:
                os.chdir(original_cwd)
            self.assertEqual(
                result,
                local_app_data / "PCPartsOrganizer" / "components.json",
            )
            self.assertNotIn("other-cwd", str(result))

    def test_does_not_depend_on_specific_user_path(self) -> None:
        custom_base = Path("C:/Temp/AnyBase/LocalAppData")
        with patch.dict(os.environ, {"LOCALAPPDATA": str(custom_base)}, clear=False):
            result = get_components_file_path()
        self.assertEqual(result, custom_base / "PCPartsOrganizer" / "components.json")
        self.assertNotIn("Users", result.parts)

    def test_raises_controlled_error_when_localappdata_missing(self) -> None:
        env = os.environ.copy()
        env.pop("LOCALAPPDATA", None)
        with patch.dict(os.environ, env, clear=True):
            with self.assertRaises(StorageError):
                get_data_directory()

    def test_raises_controlled_error_when_localappdata_empty(self) -> None:
        with patch.dict(os.environ, {"LOCALAPPDATA": "   "}, clear=False):
            with self.assertRaises(StorageError):
                get_data_directory()

    def test_raises_controlled_error_when_localappdata_relative(self) -> None:
        with patch.dict(os.environ, {"LOCALAPPDATA": "relative/path"}, clear=False):
            with self.assertRaises(StorageError):
                get_data_directory()

    def test_resolving_paths_does_not_create_directories_or_files(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            local_app_data = Path(temp_dir) / "LocalAppData"
            components_path = local_app_data / "PCPartsOrganizer" / "components.json"
            self.assertFalse(local_app_data.exists())
            self.assertFalse(components_path.parent.exists())
            self.assertFalse(components_path.exists())
            with patch.dict(os.environ, {"LOCALAPPDATA": str(local_app_data)}, clear=False):
                directory = get_data_directory()
                file_path = get_components_file_path()
            self.assertEqual(directory, components_path.parent)
            self.assertEqual(file_path, components_path)
            self.assertFalse(local_app_data.exists())
            self.assertFalse(components_path.parent.exists())
            self.assertFalse(components_path.exists())


class TestLoadComponents(unittest.TestCase):
    def _write_inventory(self, base_dir: Path, data: object, *, raw: bytes | None = None) -> Path:
        app_dir = base_dir / "PCPartsOrganizer"
        app_dir.mkdir(parents=True, exist_ok=True)
        path = app_dir / "components.json"
        if raw is not None:
            path.write_bytes(raw)
        else:
            path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
        return path

    def _load(self, base_dir: Path):
        with patch.dict(os.environ, {"LOCALAPPDATA": str(base_dir)}, clear=False):
            return load_components()

    def _valid_payload(self, *components):
        return {"schema_version": 1, "components": list(components)}

    def _valid_component(self, **overrides):
        component = {
            "id": str(uuid.uuid4()),
            "category": "CPU",
            "manufacturer": "AMD",
            "model": "Ryzen 7 7800X3D",
            "specifications": "",
            "notes": "",
        }
        component.update(overrides)
        return component

    def test_missing_file_returns_empty_list(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            base = Path(temp_dir) / "LocalAppData"
            path = base / "PCPartsOrganizer" / "components.json"
            self.assertFalse(path.exists())
            result = self._load(base)
            self.assertEqual(result, [])
            self.assertFalse(path.exists())
            self.assertFalse(path.parent.exists())

    def test_loads_valid_inventory_with_one_component(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            base = Path(temp_dir) / "LocalAppData"
            component = self._valid_component()
            self._write_inventory(base, self._valid_payload(component))
            result = self._load(base)
        self.assertEqual(len(result), 1)
        self.assertIsInstance(result[0], Component)
        self.assertEqual(result[0].id, component["id"])
        self.assertEqual(result[0].category, "CPU")

    def test_loads_valid_inventory_with_multiple_components(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            base = Path(temp_dir) / "LocalAppData"
            c1 = self._valid_component(category="CPU")
            c2 = self._valid_component(category="GPU")
            self._write_inventory(base, self._valid_payload(c1, c2))
            result = self._load(base)
        self.assertEqual(len(result), 2)
        self.assertTrue(all(isinstance(item, Component) for item in result))

    def test_missing_optional_fields_normalize_to_empty_string(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            base = Path(temp_dir) / "LocalAppData"
            component = self._valid_component()
            component.pop("specifications")
            component.pop("notes")
            self._write_inventory(base, self._valid_payload(component))
            result = self._load(base)
        self.assertEqual(result[0].specifications, "")
        self.assertEqual(result[0].notes, "")
        self.assertEqual(result[0].status, "unspecified")
        self.assertEqual(result[0].location, "")
        self.assertEqual(result[0].purchase_date, "")
        self.assertEqual(result[0].warranty_end_date, "")

    def test_null_optional_fields_normalize_correctly(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            base = Path(temp_dir) / "LocalAppData"
            component = self._valid_component(specifications=None, notes=None)
            self._write_inventory(base, self._valid_payload(component))
            result = self._load(base)
        self.assertEqual(result[0].specifications, "")
        self.assertEqual(result[0].notes, "")
        self.assertEqual(result[0].status, "unspecified")
        self.assertEqual(result[0].location, "")
        self.assertEqual(result[0].purchase_date, "")
        self.assertEqual(result[0].warranty_end_date, "")

    def test_empty_file_raises_storage_error(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            base = Path(temp_dir) / "LocalAppData"
            self._write_inventory(base, None, raw=b"")
            with self.assertRaises(StorageError):
                self._load(base)

    def test_malformed_json_raises_storage_error(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            base = Path(temp_dir) / "LocalAppData"
            self._write_inventory(base, None, raw=b"{not json")
            with self.assertRaises(StorageError):
                self._load(base)

    def test_invalid_utf8_raises_storage_error(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            base = Path(temp_dir) / "LocalAppData"
            self._write_inventory(base, None, raw=b"\xff\xfe\xfa")
            with self.assertRaises(StorageError):
                self._load(base)

    def test_root_must_be_object(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            base = Path(temp_dir) / "LocalAppData"
            self._write_inventory(base, [])
            with self.assertRaises(StorageError):
                self._load(base)

    def test_schema_version_missing_raises(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            base = Path(temp_dir) / "LocalAppData"
            self._write_inventory(base, {"components": []})
            with self.assertRaises(StorageError):
                self._load(base)

    def test_schema_version_not_one_raises(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            base = Path(temp_dir) / "LocalAppData"
            self._write_inventory(base, {"schema_version": 3, "components": []})
            with self.assertRaises(StorageError):
                self._load(base)
            self._write_inventory(base, {"schema_version": 2, "components": []})
            # schema 2 is now supported
            self._load(base)

    def test_schema_version_bool_raises(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            base = Path(temp_dir) / "LocalAppData"
            self._write_inventory(base, {"schema_version": True, "components": []})
            with self.assertRaises(StorageError):
                self._load(base)

    def test_schema_version_float_raises(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            base = Path(temp_dir) / "LocalAppData"
            self._write_inventory(base, {"schema_version": 1.0, "components": []})
            with self.assertRaises(StorageError):
                self._load(base)

    def test_components_missing_raises(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            base = Path(temp_dir) / "LocalAppData"
            self._write_inventory(base, {"schema_version": 1})
            with self.assertRaises(StorageError):
                self._load(base)

    def test_components_not_list_raises(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            base = Path(temp_dir) / "LocalAppData"
            self._write_inventory(base, {"schema_version": 1, "components": {}})
            with self.assertRaises(StorageError):
                self._load(base)

    def test_unknown_root_keys_raise(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            base = Path(temp_dir) / "LocalAppData"
            self._write_inventory(base, {"schema_version": 1, "components": [], "extra": 1})
            with self.assertRaises(StorageError):
                self._load(base)

    def test_component_not_object_raises(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            base = Path(temp_dir) / "LocalAppData"
            self._write_inventory(base, self._valid_payload("bad"))
            with self.assertRaises(StorageError):
                self._load(base)

    def test_missing_required_component_field_raises(self) -> None:
        for field in ("id", "category", "manufacturer", "model"):
            with self.subTest(field=field):
                with tempfile.TemporaryDirectory() as temp_dir:
                    base = Path(temp_dir) / "LocalAppData"
                    component = self._valid_component()
                    component.pop(field)
                    self._write_inventory(base, self._valid_payload(component))
                    with self.assertRaises(StorageError):
                        self._load(base)

    def test_unknown_component_keys_raise(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            base = Path(temp_dir) / "LocalAppData"
            component = self._valid_component(extra="nope")
            self._write_inventory(base, self._valid_payload(component))
            with self.assertRaises(StorageError):
                self._load(base)

    def test_id_wrong_type_raises(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            base = Path(temp_dir) / "LocalAppData"
            component = self._valid_component(id=123)
            self._write_inventory(base, self._valid_payload(component))
            with self.assertRaises(StorageError):
                self._load(base)

    def test_invalid_uuid_raises(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            base = Path(temp_dir) / "LocalAppData"
            component = self._valid_component(id="not-a-uuid")
            self._write_inventory(base, self._valid_payload(component))
            with self.assertRaises(StorageError):
                self._load(base)

    def test_non_v4_uuid_raises(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            base = Path(temp_dir) / "LocalAppData"
            component = self._valid_component(id=str(uuid.uuid1()))
            self._write_inventory(base, self._valid_payload(component))
            with self.assertRaises(StorageError):
                self._load(base)

    def test_duplicate_ids_raise(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            base = Path(temp_dir) / "LocalAppData"
            same_id = str(uuid.uuid4())
            c1 = self._valid_component(id=same_id)
            c2 = self._valid_component(id=same_id)
            self._write_inventory(base, self._valid_payload(c1, c2))
            with self.assertRaises(StorageError):
                self._load(base)

    def test_unknown_category_raises(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            base = Path(temp_dir) / "LocalAppData"
            component = self._valid_component(category="SoundCard")
            self._write_inventory(base, self._valid_payload(component))
            with self.assertRaises(StorageError):
                self._load(base)

    def test_empty_or_wrong_type_manufacturer_raises(self) -> None:
        for value in ("   ", 123):
            with self.subTest(value=value):
                with tempfile.TemporaryDirectory() as temp_dir:
                    base = Path(temp_dir) / "LocalAppData"
                    component = self._valid_component(manufacturer=value)
                    self._write_inventory(base, self._valid_payload(component))
                    with self.assertRaises(StorageError):
                        self._load(base)

    def test_empty_or_wrong_type_model_raises(self) -> None:
        for value in ("   ", 123):
            with self.subTest(value=value):
                with tempfile.TemporaryDirectory() as temp_dir:
                    base = Path(temp_dir) / "LocalAppData"
                    component = self._valid_component(model=value)
                    self._write_inventory(base, self._valid_payload(component))
                    with self.assertRaises(StorageError):
                        self._load(base)

    def test_wrong_type_optional_fields_raise(self) -> None:
        for field in ("specifications", "notes"):
            with self.subTest(field=field):
                with tempfile.TemporaryDirectory() as temp_dir:
                    base = Path(temp_dir) / "LocalAppData"
                    component = self._valid_component(**{field: 123})
                    self._write_inventory(base, self._valid_payload(component))
                    with self.assertRaises(StorageError):
                        self._load(base)

    def test_invalid_json_leaves_file_unchanged(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            base = Path(temp_dir) / "LocalAppData"
            original = b"{not json"
            path = self._write_inventory(base, None, raw=original)
            with self.assertRaises(StorageError):
                self._load(base)
            self.assertEqual(path.read_bytes(), original)

    def test_non_filenotfound_errors_are_not_treated_as_empty_inventory(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            base = Path(temp_dir) / "LocalAppData"
            app_dir = base / "PCPartsOrganizer"
            app_dir.mkdir(parents=True, exist_ok=True)
            path = app_dir / "components.json"
            path.write_text('{"schema_version": 1, "components": []}', encoding="utf-8")
            with patch.dict(os.environ, {"LOCALAPPDATA": str(base)}, clear=False):
                with patch("pathlib.Path.read_text", side_effect=PermissionError("denied")):
                    with self.assertRaises(StorageError):
                        load_components()




    # --- T14.4 schema evolution ---
    def test_load_v1_does_not_rewrite_file(self) -> None:
        component = self._valid_component()
        with tempfile.TemporaryDirectory() as temp_dir:
            base = Path(temp_dir) / "LocalAppData"
            path = self._write_inventory(base, {"schema_version": 1, "components": [component]})
            original = path.read_text(encoding="utf-8")
            loaded = self._load(base)
            self.assertEqual(path.read_text(encoding="utf-8"), original)
        self.assertEqual(loaded[0].status, "unspecified")
        self.assertEqual(loaded[0].location, "")

    def test_v1_rejects_new_keys(self) -> None:
        component = self._valid_component()
        component["status"] = "unspecified"
        with tempfile.TemporaryDirectory() as temp_dir:
            base = Path(temp_dir) / "LocalAppData"
            self._write_inventory(base, {"schema_version": 1, "components": [component]})
            with self.assertRaises(StorageError):
                self._load(base)

    def test_unknown_schema_version_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            base = Path(temp_dir) / "LocalAppData"
            self._write_inventory(base, {"schema_version": 99, "components": []})
            with self.assertRaises(StorageError):
                self._load(base)

    def test_load_v1_gives_date_defaults(self) -> None:
        component = self._valid_component()
        with tempfile.TemporaryDirectory() as temp_dir:
            base = Path(temp_dir) / "LocalAppData"
            self._write_inventory(base, {"schema_version": 1, "components": [component]})
            loaded = self._load(base)
        self.assertEqual(loaded[0].purchase_date, "")
        self.assertEqual(loaded[0].warranty_end_date, "")

    def test_load_t14_4_v2_without_dates_gives_date_defaults(self) -> None:
        component = self._valid_component()
        component["status"] = "stored"
        component["location"] = "Caja"
        # T14.4-era v2: 8 keys, no purchase/warranty dates
        with tempfile.TemporaryDirectory() as temp_dir:
            base = Path(temp_dir) / "LocalAppData"
            self._write_inventory(base, {"schema_version": 2, "components": [component]})
            loaded = self._load(base)
        self.assertEqual(loaded[0].status, "stored")
        self.assertEqual(loaded[0].location, "Caja")
        self.assertEqual(loaded[0].purchase_date, "")
        self.assertEqual(loaded[0].warranty_end_date, "")
        self.assertEqual(loaded[0].purchase_price, "")
        self.assertEqual(loaded[0].purchase_currency, "")

    def test_load_t14_5_v2_ten_keys_gives_price_currency_defaults(self) -> None:
        component = self._valid_component()
        component.update({"status": "stored", "location": "Caja", "purchase_date": "2024-01-01", "warranty_end_date": "2025-01-01"})
        with tempfile.TemporaryDirectory() as temp_dir:
            base = Path(temp_dir) / "LocalAppData"
            self._write_inventory(base, {"schema_version": 2, "components": [component]})
            loaded = self._load(base)
        self.assertEqual(loaded[0].purchase_date, "2024-01-01")
        self.assertEqual(loaded[0].purchase_price, "")
        self.assertEqual(loaded[0].purchase_currency, "")

class TestSaveComponents(unittest.TestCase):
    def test_v2_twelve_keys_round_trip_price_currency(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            base = Path(temp_dir) / "LocalAppData"
            with self._set_base(base):
                save_components([
                    self._component(category="GPU", manufacturer="N", model="X", purchase_price="149.90", purchase_currency="EUR")
                ])
                loaded = load_components()
                doc = json.loads(self._inventory_path(base).read_text(encoding="utf-8"))
        self.assertEqual(doc["schema_version"], 4)
        self.assertEqual(doc.get("builds"), [])
        c = doc["components"][0]
        self.assertEqual(c["purchase_price"], "149.90")
        self.assertEqual(c["purchase_currency"], "EUR")
        self.assertEqual(len(c.keys()), 12)
        self.assertEqual(loaded[0].purchase_price, "149.90")
        self.assertEqual(loaded[0].purchase_currency, "EUR")


    def test_v2_round_trip_preserves_status_and_location(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            base = Path(temp_dir) / "LocalAppData"
            with self._set_base(base):
                save_components([
                    self._component(
                        category="CPU",
                        manufacturer="AMD",
                        model="Ryzen",
                        status="loaned",
                        location="Lab",
                        purchase_date="2024-01-15",
                        warranty_end_date="2027-01-15",
                    )
                ])
                loaded = load_components()
                doc = json.loads(self._inventory_path(base).read_text(encoding="utf-8"))
        self.assertEqual(doc["schema_version"], 4)
        self.assertEqual(doc.get("builds"), [])
        self.assertEqual(loaded[0].status, "loaned")
        self.assertEqual(loaded[0].location, "Lab")
        self.assertEqual(loaded[0].purchase_date, "2024-01-15")
        self.assertEqual(loaded[0].warranty_end_date, "2027-01-15")
        c = doc["components"][0]
        self.assertEqual(
            set(c.keys()),
            {"id","category","manufacturer","model","specifications","notes","status","location","purchase_date","warranty_end_date","purchase_price","purchase_currency"},
        )


    def _set_base(self, base_dir: Path):
        return patch.dict(os.environ, {"LOCALAPPDATA": str(base_dir)}, clear=False)

    def _inventory_path(self, base_dir: Path) -> Path:
        return base_dir / "PCPartsOrganizer" / "components.json"

    def _component(self, **overrides):
        data = {
            "category": "CPU",
            "manufacturer": "AMD",
            "model": "Ryzen 7 7800X3D",
            "specifications": "",
            "notes": "",
        }
        data.update(overrides)
        return Component(**data)

    def test_saves_empty_list(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            base = Path(temp_dir) / "LocalAppData"
            with self._set_base(base):
                save_components([])
                document = json.loads(self._inventory_path(base).read_text(encoding="utf-8"))
        self.assertEqual(document, {"schema_version": 4, "components": [], "builds": [], "technical_profiles": []})

    def test_saves_one_component(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            base = Path(temp_dir) / "LocalAppData"
            component = self._component()
            with self._set_base(base):
                save_components([component])
                document = json.loads(self._inventory_path(base).read_text(encoding="utf-8"))
        self.assertEqual(len(document["components"]), 1)
        self.assertEqual(document["components"][0]["id"], component.id)

    def test_saves_multiple_components(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            base = Path(temp_dir) / "LocalAppData"
            components = [self._component(category="CPU"), self._component(category="GPU")]
            with self._set_base(base):
                save_components(components)
                document = json.loads(self._inventory_path(base).read_text(encoding="utf-8"))
        self.assertEqual(len(document["components"]), 2)

    def test_all_fields_present_in_json(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            base = Path(temp_dir) / "LocalAppData"
            component = self._component(specifications="spec", notes="note")
            with self._set_base(base):
                save_components([component])
                saved = json.loads(self._inventory_path(base).read_text(encoding="utf-8"))["components"][0]
        self.assertEqual(
            set(saved.keys()),
            {"id", "category", "manufacturer", "model", "specifications", "notes", "status", "location", "purchase_date", "warranty_end_date", "purchase_price", "purchase_currency"},
        )
        self.assertEqual(saved["status"], "unspecified")
        self.assertEqual(saved["location"], "")
        self.assertEqual(saved["purchase_date"], "")
        self.assertEqual(saved["warranty_end_date"], "")
        self.assertEqual(saved["purchase_price"], "")
        self.assertEqual(saved["purchase_currency"], "")

    def test_schema_version_saved_as_integer_one(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            base = Path(temp_dir) / "LocalAppData"
            with self._set_base(base):
                save_components([])
                raw = self._inventory_path(base).read_text(encoding="utf-8")
                document = json.loads(raw)
        self.assertIs(document["schema_version"], 4)
        self.assertIn("builds", document)
        self.assertNotIn("1.0", raw)

    def test_empty_optional_fields_are_present(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            base = Path(temp_dir) / "LocalAppData"
            component = self._component(specifications="", notes="")
            with self._set_base(base):
                save_components([component])
                saved = json.loads(self._inventory_path(base).read_text(encoding="utf-8"))["components"][0]
        self.assertIn("specifications", saved)
        self.assertIn("notes", saved)
        self.assertIn("status", saved)
        self.assertIn("location", saved)
        self.assertIn("purchase_date", saved)
        self.assertIn("warranty_end_date", saved)
        self.assertEqual(saved["specifications"], "")
        self.assertEqual(saved["notes"], "")
        self.assertEqual(saved["status"], "unspecified")
        self.assertEqual(saved["location"], "")
        self.assertEqual(saved["purchase_date"], "")
        self.assertEqual(saved["warranty_end_date"], "")

    def test_unicode_preserved_and_final_newline(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            base = Path(temp_dir) / "LocalAppData"
            component = self._component(manufacturer="Acer áéíóú ñ", notes="línea\ncon ü")
            with self._set_base(base):
                save_components([component])
                raw = self._inventory_path(base).read_text(encoding="utf-8")
        self.assertIn("áéíóú ñ", raw)
        self.assertNotIn("\\u00e1", raw)
        self.assertTrue(raw.endswith("\n"))

    def test_round_trip_with_load_components(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            base = Path(temp_dir) / "LocalAppData"
            components = [
                self._component(category="CPU", manufacturer="Intel", model="i5"),
                self._component(category="RAM", manufacturer="Corsair", model="Vengeance", specifications="32GB", notes="DDR5"),
            ]
            with self._set_base(base):
                save_components(components)
                loaded = load_components()
        self.assertEqual([c.id for c in loaded], [c.id for c in components])
        self.assertEqual(loaded[1].specifications, "32GB")
        self.assertEqual(loaded[1].notes, "DDR5")

    def test_rejects_non_list_argument(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            base = Path(temp_dir) / "LocalAppData"
            with self._set_base(base):
                with self.assertRaises(StorageError):
                    save_components({})  # type: ignore[arg-type]
            self.assertFalse(self._inventory_path(base).exists())
            self.assertFalse(self._inventory_path(base).parent.exists())

    def test_rejects_non_component_elements(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            base = Path(temp_dir) / "LocalAppData"
            with self._set_base(base):
                with self.assertRaises(StorageError):
                    save_components([{"id": "x"}])  # type: ignore[list-item]
            self.assertFalse(self._inventory_path(base).parent.exists())

    def test_rejects_mutated_invalid_component(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            base = Path(temp_dir) / "LocalAppData"
            component = self._component()
            component.manufacturer = "   "
            with self._set_base(base):
                with self.assertRaises(StorageError):
                    save_components([component])
            self.assertFalse(self._inventory_path(base).parent.exists())

    def test_rejects_duplicate_ids(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            base = Path(temp_dir) / "LocalAppData"
            same_id = str(uuid.uuid4())
            c1 = self._component()
            c2 = self._component()
            c1.id = same_id
            c2.id = same_id
            with self._set_base(base):
                with self.assertRaises(StorageError):
                    save_components([c1, c2])
            self.assertFalse(self._inventory_path(base).parent.exists())

    def test_validation_failure_preserves_previous_inventory(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            base = Path(temp_dir) / "LocalAppData"
            original = self._component(manufacturer="Original")
            with self._set_base(base):
                save_components([original])
                before = self._inventory_path(base).read_bytes()
                with self.assertRaises(StorageError):
                    save_components([{"bad": "data"}])  # type: ignore[list-item]
                after = self._inventory_path(base).read_bytes()
        self.assertEqual(before, after)

    def test_creates_data_directory_on_save(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            base = Path(temp_dir) / "LocalAppData"
            self.assertFalse((base / "PCPartsOrganizer").exists())
            with self._set_base(base):
                save_components([])
            self.assertTrue((base / "PCPartsOrganizer").is_dir())

    def test_load_and_path_resolution_still_do_not_create_directory(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            base = Path(temp_dir) / "LocalAppData"
            target = base / "PCPartsOrganizer"
            with self._set_base(base):
                get_data_directory()
                get_components_file_path()
                load_components()
            self.assertFalse(target.exists())

    def test_uses_temp_file_in_same_directory_and_os_replace(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            base = Path(temp_dir) / "LocalAppData"
            component = self._component()
            captured = {}
            real_replace = os.replace

            def capture_replace(src, dst):
                captured["src"] = Path(src)
                captured["dst"] = Path(dst)
                return real_replace(src, dst)

            with self._set_base(base):
                with patch("pc_parts_organizer.storage.os.replace", side_effect=capture_replace):
                    save_components([component])
        self.assertEqual(captured["dst"], self._inventory_path(base))
        self.assertEqual(captured["src"].parent, captured["dst"].parent)
        self.assertNotEqual(captured["src"], captured["dst"])

    def test_os_replace_failure_preserves_previous_inventory(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            base = Path(temp_dir) / "LocalAppData"
            original = self._component(manufacturer="Original")
            with self._set_base(base):
                save_components([original])
                before = self._inventory_path(base).read_bytes()
                with patch("pc_parts_organizer.storage.os.replace", side_effect=OSError("replace failed")):
                    with self.assertRaises(StorageError):
                        save_components([self._component(manufacturer="New")])
                after = self._inventory_path(base).read_bytes()
            leftovers = [p for p in self._inventory_path(base).parent.iterdir() if p.name != "components.json"]
        self.assertEqual(before, after)
        self.assertEqual(leftovers, [])

    def test_write_failure_preserves_previous_inventory_and_cleans_temp(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            base = Path(temp_dir) / "LocalAppData"
            original = self._component(manufacturer="Original")
            with self._set_base(base):
                save_components([original])
                before = self._inventory_path(base).read_bytes()
                with patch("pc_parts_organizer.storage.os.fsync", side_effect=OSError("sync failed")):
                    with self.assertRaises(StorageError):
                        save_components([self._component(manufacturer="New")])
                after = self._inventory_path(base).read_bytes()
            leftovers = [p for p in self._inventory_path(base).parent.iterdir() if p.name != "components.json"]
        self.assertEqual(before, after)
        self.assertEqual(leftovers, [])

    def test_write_errors_are_reported_as_storage_error(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            base = Path(temp_dir) / "LocalAppData"
            with self._set_base(base):
                with patch("pc_parts_organizer.storage.os.replace", side_effect=OSError("boom")):
                    with self.assertRaises(StorageError):
                        save_components([])


class TestSettingsStorage(unittest.TestCase):
    def _set_base(self, base_dir: Path):
        return patch.dict(os.environ, {"LOCALAPPDATA": str(base_dir)}, clear=False)

    def test_resolves_settings_json_path(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            local_app_data = Path(temp_dir) / "LocalAppData"
            with self._set_base(local_app_data):
                result = get_settings_file_path()
        self.assertEqual(result, local_app_data / "PCPartsOrganizer" / "settings.json")

    def test_resolving_settings_path_does_not_create_files(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            local_app_data = Path(temp_dir) / "LocalAppData"
            target = local_app_data / "PCPartsOrganizer"
            with self._set_base(local_app_data):
                path = get_settings_file_path()
            self.assertEqual(path.name, "settings.json")
            self.assertFalse(target.exists())

    def test_load_language_preference_defaults_without_file(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            with self._set_base(Path(temp_dir) / "LocalAppData"):
                self.assertEqual(load_language_preference(("es", "en")), "es")

    def test_save_language_preference_creates_directory_safely(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            base = Path(temp_dir) / "LocalAppData"
            with self._set_base(base):
                save_language_preference("en", ("es", "en"))
                document = json.loads((base / "PCPartsOrganizer" / "settings.json").read_text(encoding="utf-8"))
        self.assertEqual(document, {"schema_version": 1, "language": "en"})


if __name__ == "__main__":
    unittest.main()


class TestInventoryBackupStorage(unittest.TestCase):
    def _comp(self, **o):
        d = dict(category="CPU", manufacturer="AMD", model="Ryzen", specifications="s", notes="n",
                 status="stored", location="Desk", purchase_date="2024-01-01", warranty_end_date="2025-01-01",
                 purchase_price="99.90", purchase_currency="EUR")
        d.update(o); return Component(**d)

    def test_export_empty_and_full_preserves_fields_uuid_utf8_and_verifies(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            dest = Path(td)/"backup.json"
            info = export_inventory([], dest)
            self.assertEqual(info.components, [])
            raw = dest.read_bytes()
            self.assertFalse(raw.startswith(b"\xef\xbb\xbf"))
            # full
            c = self._comp(notes="l?nea\ncon ?")
            dest2 = Path(td)/"backup2.json"
            info2 = export_inventory([c], dest2)
            self.assertEqual(info2.components[0].id, c.id)
            self.assertEqual(info2.components[0].notes, "l?nea\ncon ?")
            self.assertEqual(info2.components[0].purchase_price, "99.90")
            # compatible with reader
            loaded = read_inventory_file(dest2)
            self.assertEqual(loaded.schema_version, 4)
            self.assertEqual(len(loaded.components), 1)
            self.assertEqual(loaded.builds, [])

    def test_export_rejects_active_destination_and_does_not_touch_active(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            active = Path(td)/"active"/"components.json"
            active.parent.mkdir(parents=True)
            active.write_text('{"schema_version":2,"components":[]}\n', encoding="utf-8")
            before = active.read_text(encoding="utf-8")
            with self.assertRaises(StorageError):
                export_inventory([self._comp()], active, active_path=active)
            self.assertEqual(active.read_text(encoding="utf-8"), before)

    def test_read_inventory_file_valid_empty_v1_v2_compat_and_sha_mismatch(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            p = Path(td)/"b.json"
            p.write_text(json.dumps({"schema_version":1,"components":[]}), encoding="utf-8")
            self.assertEqual(read_inventory_file(p).components, [])
            # v1 compat
            c = {"id": str(uuid.uuid4()), "category":"CPU","manufacturer":"A","model":"M","specifications":"","notes":""}
            p.write_text(json.dumps({"schema_version":1,"components":[c]}), encoding="utf-8")
            info = read_inventory_file(p)
            self.assertEqual(info.components[0].status, "unspecified")
            self.assertEqual(info.components[0].purchase_price, "")
            # SHA pin change
            old = info.sha256
            p.write_text(json.dumps({"schema_version":2,"components":[]}), encoding="utf-8")
            with self.assertRaises(StorageError):
                read_inventory_file(p, expected_sha256=old)

    def test_read_inventory_file_rejects_invalid_cases(self) -> None:
        cases = [
            ("{bad json", None),
            (json.dumps({"schema_version":9,"components":[]}), None),
            (json.dumps({"schema_version":2}), None),
            (json.dumps({"schema_version":2,"components":[{"id":"x","category":"CPU","manufacturer":"A","model":"M"}]}), None),
            (json.dumps({"schema_version":2,"components":[1]}), None),
        ]
        with tempfile.TemporaryDirectory() as td:
            p = Path(td)/"b.json"
            for text, _ in cases:
                p.write_text(text, encoding="utf-8")
                with self.assertRaises(StorageError):
                    read_inventory_file(p)
            # duplicate UUID
            uid = str(uuid.uuid4())
            comp = {"id":uid,"category":"CPU","manufacturer":"A","model":"M","specifications":"","notes":"","status":"unspecified","location":"","purchase_date":"","warranty_end_date":"","purchase_price":"","purchase_currency":""}
            p.write_text(json.dumps({"schema_version":2,"components":[comp, {**comp, "category":"GPU","manufacturer":"B","model":"N"}]}), encoding="utf-8")
            with self.assertRaises(StorageError):
                read_inventory_file(p)
            # invalid category/date/price-currency
            bad = {**comp, "category":"Nope"}
            p.write_text(json.dumps({"schema_version":2,"components":[bad]}), encoding="utf-8")
            with self.assertRaises(StorageError): read_inventory_file(p)
            bad = {**comp, "purchase_date":"2024-99-99"}
            p.write_text(json.dumps({"schema_version":2,"components":[bad]}), encoding="utf-8")
            with self.assertRaises(StorageError): read_inventory_file(p)
            bad = {**comp, "purchase_price":"10", "purchase_currency":""}
            p.write_text(json.dumps({"schema_version":2,"components":[bad]}), encoding="utf-8")
            with self.assertRaises(StorageError): read_inventory_file(p)

    def test_create_pre_restore_backup_verified_and_no_overwrite(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            bdir = Path(td)/"pre-restore"
            info = create_pre_restore_backup([self._comp()], directory=bdir)
            self.assertTrue(info.path and info.path.exists())
            loaded = read_inventory_file(info.path)
            self.assertEqual(len(loaded.components), 1)
            self.assertEqual(hashlib.sha256(info.path.read_bytes()).hexdigest(), info.sha256)
            # collision-safe naming (second backup)
            info2 = create_pre_restore_backup([self._comp(model="Other")], directory=bdir)
            self.assertNotEqual(info.path, info2.path)
            self.assertTrue(info.path.exists() and info2.path.exists())
