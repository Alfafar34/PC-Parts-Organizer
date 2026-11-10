try:
    import tests._pcpo_test_isolation_bootstrap  # noqa: F401
except Exception:
    import _pcpo_test_isolation_bootstrap  # type: ignore  # noqa: F401

import json
import tempfile
import unittest
import uuid
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

from pc_parts_organizer.models import CATEGORIES, Component
from pc_parts_organizer.service import InventoryService, StorageError
from pc_parts_organizer.storage import export_inventory, read_inventory_file


def _comp(**o):
    d = dict(
        category="CPU", manufacturer="AMD", model="Ryzen", specifications="s", notes="n",
        status="stored", location="Desk", purchase_date="2024-01-01", warranty_end_date="2025-01-01",
        purchase_price="99.90", purchase_currency="EUR",
    )
    d.update(o)
    return Component(**d)


class TestBackupStorageExtra(unittest.TestCase):
    def test_export_write_failure_propagates(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            dest = Path(td) / "backup.json"
            with patch("pc_parts_organizer.storage._atomic_write_json", side_effect=StorageError("boom")):
                with self.assertRaises(StorageError):
                    export_inventory([_comp()], dest)
            self.assertFalse(dest.exists())

    def test_preview_read_is_read_only(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / "b.json"
            c = _comp()
            info = export_inventory([c], p)
            before = p.read_bytes()
            with patch("pc_parts_organizer.storage.save_components") as ms, patch("pc_parts_organizer.storage.load_components") as ml:
                info2 = read_inventory_file(p, expected_sha256=info.sha256)
            self.assertEqual(info2.components[0].id, c.id)
            self.assertEqual(p.read_bytes(), before)
            ms.assert_not_called()
            ml.assert_not_called()

    def test_v2_early_variants_accepted(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            uid = str(uuid.uuid4())
            doc = {"schema_version": 2, "components": [{
                "id": uid, "category": "CPU", "manufacturer": "A", "model": "M",
                "specifications": "", "notes": "", "status": "stored", "location": "L",
            }]}
            p = Path(td) / "b.json"
            p.write_text(json.dumps(doc), encoding="utf-8")
            info = read_inventory_file(p)
            self.assertEqual(info.components[0].purchase_price, "")
            self.assertEqual(info.components[0].purchase_date, "")

    def test_corrupt_schema_uuid_dup_invalid_fields_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / "b.json"
            p.write_text("{not json", encoding="utf-8")
            with self.assertRaises(StorageError):
                read_inventory_file(p)
            p.write_text(json.dumps({"schema_version": 9, "components": []}), encoding="utf-8")
            with self.assertRaises(StorageError):
                read_inventory_file(p)
            uid = str(uuid.uuid4())
            base = {"id": uid, "category": "CPU", "manufacturer": "A", "model": "M",
                    "specifications": "", "notes": "", "status": "unspecified", "location": "",
                    "purchase_date": "", "warranty_end_date": "", "purchase_price": "", "purchase_currency": ""}
            p.write_text(json.dumps({"schema_version": 2, "components": [base, {**base, "model": "X"}]}), encoding="utf-8")
            with self.assertRaises(StorageError):
                read_inventory_file(p)
            for bad in [{"category": "Bad"}, {"purchase_date": "2024-02-30"}, {"purchase_price": "1", "purchase_currency": ""}]:
                p.write_text(json.dumps({"schema_version": 2, "components": [{**base, **bad}]}), encoding="utf-8")
                with self.assertRaises(StorageError):
                    read_inventory_file(p)


class TestBackupServiceExtra(unittest.TestCase):
    @patch("pc_parts_organizer.service.create_pre_restore_backup")
    @patch("pc_parts_organizer.service.save_components")
    @patch("pc_parts_organizer.service.load_components")
    def test_restore_rejects_duplicate_uuid_in_candidate(self, mock_load, mock_save, mock_pre) -> None:
        mock_load.return_value = []
        s = InventoryService()
        c = _comp()
        with self.assertRaises(StorageError):
            s.restore_inventory([c, c])
        mock_pre.assert_not_called()
        mock_save.assert_not_called()

    @patch("pc_parts_organizer.service.create_pre_restore_backup")
    @patch("pc_parts_organizer.service.save_components")
    @patch("pc_parts_organizer.service.load_components")
    def test_restore_passes_pre_backup_dir(self, mock_load, mock_save, mock_pre) -> None:
        mock_load.return_value = []
        mock_pre.return_value = SimpleNamespace(path=Path("p"), sha256="x", components=[], schema_version=2)
        s = InventoryService()
        s.restore_inventory([], pre_restore_backup_dir="C:/tmp/backups")
        self.assertEqual(str(mock_pre.call_args[1].get("directory")), "C:/tmp/backups")


class TestBackupUIContracts(unittest.TestCase):
    def test_main_window_has_backup_handlers(self) -> None:
        from pc_parts_organizer.ui import main_window
        self.assertTrue(callable(getattr(main_window.MainWindow, "_on_export_inventory", None)))
        self.assertTrue(callable(getattr(main_window.MainWindow, "_on_restore_inventory", None)))

    def test_inventory_list_view_accepts_backup_callbacks(self) -> None:
        import inspect
        from pc_parts_organizer.ui.inventory_list_view import InventoryListView
        sig = inspect.signature(InventoryListView.__init__)
        self.assertIn("on_export", sig.parameters)
        self.assertIn("on_restore", sig.parameters)


class TestBackupUIFlowMocked(unittest.TestCase):
    def _base_win(self):
        import tkinter as tk
        from pc_parts_organizer.localization import Translator
        from pc_parts_organizer.ui.main_window import MainWindow
        try:
            root = tk.Tk()
            root.withdraw()
        except tk.TclError:
            self.skipTest("Tk unavailable")
        with patch("pc_parts_organizer.localization.load_language_preference", return_value="en"):
            translator = Translator()
        translator.set_language("en")
        win = MainWindow.__new__(MainWindow)
        win.root = root
        win.service = Mock()
        win.catalog_service = Mock()
        win.translator = translator
        win._inventory_list_view = Mock()
        win._builds_list_view = None
        win._builds_detail_view = None
        win._detail_component_id = None
        win._detail_build_id = None
        win.refresh_inventory = Mock()
        win.refresh_builds = Mock()
        win._show_inventory_list = Mock()
        win._update_inventory_actions = Mock()
        return root, win

    def test_export_cancel_no_write(self) -> None:
        root, win = self._base_win()
        try:
            with patch("pc_parts_organizer.ui.main_window.filedialog.asksaveasfilename", return_value=""), \
                 patch("pc_parts_organizer.ui.main_window.export_inventory") as mex:
                win._on_export_inventory()
            mex.assert_not_called()
        finally:
            root.destroy()

    def test_restore_cancel_after_preview_no_restore(self) -> None:
        root, win = self._base_win()
        try:
            info = SimpleNamespace(components=[_comp()], schema_version=2, sha256="abc")
            with patch("pc_parts_organizer.ui.main_window.filedialog.askopenfilename", return_value="C:/tmp/b.json"), \
                 patch("pc_parts_organizer.ui.main_window.read_inventory_file", return_value=info), \
                 patch.object(win, "_show_restore_preview_dialog", return_value=False):
                win._on_restore_inventory()
            win.service.restore_inventory.assert_not_called()
            win.refresh_inventory.assert_not_called()
        finally:
            root.destroy()

    def test_restore_sha_changed_blocks(self) -> None:
        root, win = self._base_win()
        try:
            info = SimpleNamespace(components=[_comp()], schema_version=2, sha256="abc")
            calls = [info, StorageError("changed")]

            def fake_read(*a, **k):
                r = calls.pop(0)
                if isinstance(r, Exception):
                    raise r
                return r

            with patch("pc_parts_organizer.ui.main_window.filedialog.askopenfilename", return_value="C:/tmp/b.json"), \
                 patch("pc_parts_organizer.ui.main_window.read_inventory_file", side_effect=fake_read), \
                 patch.object(win, "_show_restore_preview_dialog", return_value=True), \
                 patch("pc_parts_organizer.ui.main_window.messagebox.showerror") as merr:
                win._on_restore_inventory()
            win.service.restore_inventory.assert_not_called()
            self.assertTrue(merr.called)
        finally:
            root.destroy()

    def test_export_cancel_no_write(self) -> None:
        root, win = self._base_win()
        try:
            with patch("pc_parts_organizer.ui.main_window.filedialog.asksaveasfilename", return_value=""), \
                 patch("pc_parts_organizer.ui.main_window.export_inventory") as mex:
                win._on_export_inventory()
            mex.assert_not_called()
            win.service.get_project_state.assert_not_called()
        finally:
            root.destroy()

    def test_export_complete_state_includes_builds(self) -> None:
        root, win = self._base_win()
        try:
            comp = _comp()
            build = SimpleNamespace(id=str(uuid.uuid4()), name="PC", kind="current", notes="", component_ids=[comp.id])
            win.service.get_project_state.return_value = SimpleNamespace(components=[comp], builds=[build], schema_version=3)
            info = SimpleNamespace(path=Path("C:/tmp/b.json"), components=[comp], builds=[build], schema_version=3, sha256="x")
            with patch("pc_parts_organizer.ui.main_window.filedialog.asksaveasfilename", return_value="C:/tmp/b.json"), \
                 patch("pc_parts_organizer.ui.main_window.export_inventory", return_value=info) as mex, \
                 patch("pc_parts_organizer.ui.main_window.messagebox.showinfo"):
                win._on_export_inventory()
            self.assertTrue(mex.called)
            args, kwargs = mex.call_args
            first = args[0]
            # T17.2 unambiguous complete-state export may pass ProjectState or collections.
            if hasattr(first, "components") and hasattr(first, "builds"):
                self.assertEqual(list(first.components), [comp])
                self.assertEqual(list(getattr(first, "builds", []) or []), [build])
            else:
                self.assertEqual(first, [comp])
                self.assertEqual(kwargs.get("builds"), [build])
        finally:
            root.destroy()

    def test_restore_cancel_after_preview_no_restore(self) -> None:
        root, win = self._base_win()
        try:
            info = SimpleNamespace(components=[_comp()], builds=[], schema_version=3, sha256="abc")
            with patch("pc_parts_organizer.ui.main_window.filedialog.askopenfilename", return_value="C:/tmp/b.json"), \
                 patch("pc_parts_organizer.ui.main_window.read_inventory_file", return_value=info), \
                 patch.object(win, "_show_restore_preview_dialog", return_value=False):
                win._on_restore_inventory()
            win.service.restore_inventory.assert_not_called()
            win.refresh_inventory.assert_not_called()
            win.refresh_builds.assert_not_called()
        finally:
            root.destroy()

    def test_restore_passes_complete_info_not_components_only(self) -> None:
        root, win = self._base_win()
        try:
            comp = _comp()
            build = SimpleNamespace(id=str(uuid.uuid4()), name="PC", kind="current", notes="", component_ids=[comp.id])
            info = SimpleNamespace(components=[comp], builds=[build], schema_version=3, sha256="abc")
            result = SimpleNamespace(restored_count=1, restored_build_count=1, pre_restore_backup=SimpleNamespace(path="C:/tmp/pre.json"))
            win.service.restore_inventory.return_value = result
            with patch("pc_parts_organizer.ui.main_window.filedialog.askopenfilename", return_value="C:/tmp/b.json"), \
                 patch("pc_parts_organizer.ui.main_window.read_inventory_file", return_value=info), \
                 patch.object(win, "_show_restore_preview_dialog", return_value=True), \
                 patch("pc_parts_organizer.ui.main_window.messagebox.showinfo"):
                win._on_restore_inventory()
            win.service.restore_inventory.assert_called_once_with(info)
            win.refresh_inventory.assert_called_once()
            win.refresh_builds.assert_called_once()
        finally:
            root.destroy()

    def test_restore_sha_changed_blocks(self) -> None:
        root, win = self._base_win()
        try:
            info = SimpleNamespace(components=[_comp()], builds=[], schema_version=3, sha256="abc")
            calls = [info, StorageError("changed")]

            def fake_read(*a, **k):
                r = calls.pop(0)
                if isinstance(r, Exception):
                    raise r
                return r

            with patch("pc_parts_organizer.ui.main_window.filedialog.askopenfilename", return_value="C:/tmp/b.json"), \
                 patch("pc_parts_organizer.ui.main_window.read_inventory_file", side_effect=fake_read), \
                 patch.object(win, "_show_restore_preview_dialog", return_value=True), \
                 patch("pc_parts_organizer.ui.main_window.messagebox.showerror") as merr:
                win._on_restore_inventory()
            win.service.restore_inventory.assert_not_called()
            self.assertTrue(merr.called)
        finally:
            root.destroy()

    def test_restore_success_refreshes_views_clears_selection(self) -> None:
        root, win = self._base_win()
        try:
            comp = _comp()
            info = SimpleNamespace(components=[comp], builds=[], schema_version=3, sha256="abc")
            result = SimpleNamespace(restored_count=1, restored_build_count=0, pre_restore_backup=SimpleNamespace(path="C:/tmp/pre.json"))
            win.service.restore_inventory.return_value = result
            win._detail_component_id = "stale"
            with patch("pc_parts_organizer.ui.main_window.filedialog.askopenfilename", return_value="C:/tmp/b.json"), \
                 patch("pc_parts_organizer.ui.main_window.read_inventory_file", return_value=info), \
                 patch.object(win, "_show_restore_preview_dialog", return_value=True), \
                 patch("pc_parts_organizer.ui.main_window.messagebox.showinfo") as minfo:
                win._on_restore_inventory()
            win.service.restore_inventory.assert_called_once_with(info)
            self.assertIsNone(win._detail_component_id)
            win.refresh_inventory.assert_called_once()
            win.refresh_builds.assert_called_once()
            win._inventory_list_view.clear_selection.assert_called_once()
            win._show_inventory_list.assert_called_once()
            win._update_inventory_actions.assert_called_once()
            self.assertTrue(minfo.called)
        finally:
            root.destroy()

    def test_restore_pre_backup_failure_reports_error(self) -> None:
        root, win = self._base_win()
        try:
            info = SimpleNamespace(components=[_comp()], schema_version=2, sha256="abc")
            win.service.restore_inventory.side_effect = StorageError("Could not create backup directory: x")
            with patch("pc_parts_organizer.ui.main_window.filedialog.askopenfilename", return_value="C:/tmp/b.json"), \
                 patch("pc_parts_organizer.ui.main_window.read_inventory_file", return_value=info), \
                 patch.object(win, "_show_restore_preview_dialog", return_value=True), \
                 patch("pc_parts_organizer.ui.main_window.messagebox.showerror") as merr:
                win._on_restore_inventory()
            self.assertTrue(merr.called)
            win.refresh_inventory.assert_not_called()
        finally:
            root.destroy()
