"""UI tests for Equipos/builds (T16.3). Uses temp/mocks; no real data."""

from __future__ import annotations
try:
    import tests._pcpo_test_isolation_bootstrap  # noqa: F401
except Exception:
    import _pcpo_test_isolation_bootstrap  # type: ignore  # noqa: F401

import unittest
import uuid
from types import SimpleNamespace
from unittest.mock import Mock, patch

from pc_parts_organizer.models import Build, Component
from pc_parts_organizer.service import (
    BuildNameConflictError,
    BuildNotFoundError,
    ComponentAlreadyAssignedError,
    ComponentNotFoundError,
    StorageError,
)


def _comp(**o):
    d = dict(category="CPU", manufacturer="AMD", model="Ryzen", specifications="", notes="")
    d.update(o)
    return Component(**d)


def _build(**o):
    d = dict(name="PC", notes="", kind="current", component_ids=[])
    d.update(o)
    return Build(**d)


class TestBuildViews(unittest.TestCase):
    def _tk(self):
        import tkinter as tk
        try:
            root = tk.Tk(); root.withdraw()
        except tk.TclError:
            self.skipTest("Tk unavailable")
        return root

    def test_list_view_empty_and_selection(self):
        root = self._tk()
        try:
            from pc_parts_organizer.localization import Translator
            from pc_parts_organizer.ui.build_list_view import BuildListView
            tr = Translator(); tr.set_language("en")
            v = BuildListView(root, tr)
            v.set_builds([])
            self.assertIsNone(v.get_selected_build_id())
            b = _build(name="Alpha")
            v.set_builds([b])
            item = v.tree.get_children()[0]
            v.tree.selection_set(item); v.tree.focus(item)
            self.assertEqual(v.get_selected_build_id(), b.id)
            v.clear_selection()
            self.assertIsNone(v.get_selected_build_id())
        finally:
            root.destroy()

    def test_detail_view_renders_composition(self):
        root = self._tk()
        try:
            from pc_parts_organizer.localization import Translator
            from pc_parts_organizer.ui.build_detail_view import BuildDetailView
            tr = Translator(); tr.set_language("en")
            c = _comp(category="GPU", manufacturer="N", model="X")
            b = _build(name="PC", component_ids=[c.id])
            v = BuildDetailView(root, tr)
            v.set_build(b, {c.id: c})
            self.assertEqual(v.get_build_id(), b.id)
        finally:
            root.destroy()


class TestMainWindowBuildFlows(unittest.TestCase):
    def _win(self):
        import tkinter as tk
        from pc_parts_organizer.localization import Translator
        from pc_parts_organizer.ui.main_window import MainWindow
        try:
            root = tk.Tk(); root.withdraw()
        except tk.TclError:
            self.skipTest("Tk unavailable")
        tr = Translator(); tr.set_language("en")
        win = MainWindow.__new__(MainWindow)
        win.root = root
        win.service = Mock()
        win.catalog_service = Mock()
        win.translator = tr
        win._inventory_list_view = Mock()
        win._builds_list_view = Mock()
        win._builds_detail_view = Mock()
        win._detail_component_id = None
        win._detail_build_id = None
        win.refresh_inventory = Mock()
        win.refresh_builds = Mock()
        win._show_inventory_list = Mock()
        win._show_builds_list = Mock()
        win._show_builds_detail_view = Mock()
        win._update_inventory_actions = Mock()
        return root, win

    def test_add_build_cancel_no_mutation(self):
        root, win = self._win()
        try:
            win.root.wait_window = Mock()
            win.service.get_components.return_value = []
            win.service.get_available_components.return_value = []
            form = Mock(); form.result = None; form.window = Mock()
            with patch("pc_parts_organizer.ui.main_window.BuildForm", return_value=form):
                win._on_add_build()
            win.service.add_build.assert_not_called()
        finally:
            root.destroy()

    def test_add_build_success(self):
        root, win = self._win()
        try:
            win.root.wait_window = Mock()
            b = _build()
            win.service.add_build.return_value = b
            win.service.get_build.return_value = b
            win.service.get_components.return_value = []
            result = SimpleNamespace(name="PC", notes="n", kind="current", component_ids=[])
            form = Mock(); form.result = result; form.window = Mock()
            with patch("pc_parts_organizer.ui.main_window.BuildForm", return_value=form):
                win._on_add_build()
            win.service.add_build.assert_called_once()
            win.refresh_builds.assert_called()
        finally:
            root.destroy()

    def test_add_build_name_conflict_shows_error_no_success(self):
        root, win = self._win()
        try:
            win.root.wait_window = Mock()
            win.service.get_components.return_value = []
            win.service.get_available_components.return_value = []
            win.service.add_build.side_effect = BuildNameConflictError("PC")
            result = SimpleNamespace(name="PC", notes="", kind="current", component_ids=[])
            form = Mock(); form.result = result; form.window = Mock()
            with patch("pc_parts_organizer.ui.main_window.BuildForm", return_value=form), \
                 patch("pc_parts_organizer.ui.main_window.messagebox.showerror") as merr:
                win._on_add_build()
            self.assertTrue(merr.called)
            win.refresh_builds.assert_not_called()
        finally:
            root.destroy()

    def test_add_build_storage_error_no_success(self):
        root, win = self._win()
        try:
            win.root.wait_window = Mock()
            win.service.get_components.return_value = []
            win.service.get_available_components.return_value = []
            win.service.add_build.side_effect = StorageError("disk")
            result = SimpleNamespace(name="PC", notes="", kind="current", component_ids=[])
            form = Mock(); form.result = result; form.window = Mock()
            with patch("pc_parts_organizer.ui.main_window.BuildForm", return_value=form), \
                 patch("pc_parts_organizer.ui.main_window.messagebox.showerror") as merr:
                win._on_add_build()
            self.assertTrue(merr.called)
            win.refresh_builds.assert_not_called()
        finally:
            root.destroy()

    def test_delete_build_cancel_no_mutation(self):
        root, win = self._win()
        try:
            b = _build(); win.service.get_build.return_value = b
            with patch.object(win, "_confirm_delete_build", return_value=False):
                ok = win._delete_build_by_id(b.id)
            self.assertFalse(ok)
            win.service.delete_build.assert_not_called()
        finally:
            root.destroy()

    def test_delete_build_confirm_deletes(self):
        root, win = self._win()
        try:
            b = _build(); win.service.get_build.return_value = b
            with patch.object(win, "_confirm_delete_build", return_value=True):
                ok = win._delete_build_by_id(b.id)
            self.assertTrue(ok)
            win.service.delete_build.assert_called_once_with(b.id)
            win.refresh_builds.assert_called()
        finally:
            root.destroy()

    def test_delete_build_storage_error_no_success(self):
        root, win = self._win()
        try:
            b = _build(); win.service.get_build.return_value = b
            win.service.delete_build.side_effect = StorageError("disk")
            with patch.object(win, "_confirm_delete_build", return_value=True), \
                 patch("pc_parts_organizer.ui.main_window.messagebox.showerror") as merr:
                ok = win._delete_build_by_id(b.id)
            self.assertFalse(ok)
            self.assertTrue(merr.called)
        finally:
            root.destroy()

    def test_edit_component_unavailable_shows_error(self):
        root, win = self._win()
        try:
            win.root.wait_window = Mock()
            c = _comp(); b = _build(component_ids=[c.id])
            win.service.get_build.return_value = b
            win.service.get_components.return_value = [c]
            win.service.get_available_components.return_value = []
            win.service.update_build.side_effect = ComponentAlreadyAssignedError(c.id, b.id)
            result = SimpleNamespace(name="PC", notes="", kind="current", component_ids=[c.id])
            form = Mock(); form.result = result; form.window = Mock()
            with patch("pc_parts_organizer.ui.main_window.BuildForm", return_value=form), \
                 patch("pc_parts_organizer.ui.main_window.messagebox.showerror") as merr:
                win._edit_build_by_id(b.id)
            self.assertTrue(merr.called)
        finally:
            root.destroy()

    def test_refresh_builds_safe_when_no_view(self):
        root, win = self._win()
        try:
            win._builds_list_view = None
            win.refresh_builds = type(win).refresh_builds.__get__(win, type(win))
            win.refresh_builds()  # should not raise
        finally:
            root.destroy()
