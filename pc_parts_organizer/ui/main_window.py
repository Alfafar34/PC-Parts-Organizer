"""Main application window."""

from __future__ import annotations

import tkinter as tk
from datetime import datetime
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

from pc_parts_organizer.catalog_service import CatalogService, CatalogStorageError
from pc_parts_organizer.localization import LANGUAGE_NAMES, SUPPORTED_LANGUAGES, LocalizationError, Translator
from pc_parts_organizer.service import (
    BatchValidationError,
    BuildNameConflictError,
    BuildNotFoundError,
    ComponentAlreadyAssignedError,
    ComponentInUseError,
    ComponentNotFoundError,
    ComponentValidationError,
    InventoryService,
    InventorySummary,
    StorageError,
    TechnicalProfileCategoryConflictError,
)
from pc_parts_organizer.technical_profiles import ATTRIBUTE_REGISTRY, TechnicalProfileValidationError
from pc_parts_organizer.storage import export_inventory, export_project_state, get_components_file_path, read_inventory_file
from pc_parts_organizer.ui.build_compare_view import BuildCompareView
from pc_parts_organizer.ui.build_detail_view import BuildDetailView
from pc_parts_organizer.ui.build_form import BuildForm
from pc_parts_organizer.ui.build_list_view import BuildListView
from pc_parts_organizer.ui.catalog_manager import CatalogManagerView
from pc_parts_organizer.ui.component_form import ComponentForm
from pc_parts_organizer.ui.dashboard_view import DashboardView
from pc_parts_organizer.ui.inventory_detail_view import InventoryDetailView
from pc_parts_organizer.ui.quality_center_view import QualityCenterView
from pc_parts_organizer.ui.inventory_list_view import InventoryListView
from pc_parts_organizer.ui.technical_profile_form import TechnicalProfileForm
from pc_parts_organizer.ui.theme import PALETTE

TABLE_COLUMNS = ("category", "manufacturer", "model")
NAV_HOME = "home"
NAV_INVENTORY = "inventory"
NAV_BUILDS = "builds"
NAV_CATALOG = "catalog"


class MainWindow:
    """Tkinter/ttk main window with integrated navigation."""

    def __init__(
        self,
        root: tk.Tk,
        service: InventoryService,
        catalog_service: CatalogService,
        translator: Translator,
    ) -> None:
        self.root = root
        self.service = service
        self.catalog_service = catalog_service
        self.translator = translator
        self._catalog_view: CatalogManagerView | None = None
        self._catalog_initialized = False
        self._components_cache: list = []
        self._summary_cache = InventorySummary(total_count=0, category_counts={})
        self._tab_index_by_id: dict[str, int] = {}
        self._detail_component_id: str | None = None

        self.header_title: ttk.Label | None = None
        self.header_subtitle: ttk.Label | None = None
        self.notebook: ttk.Notebook | None = None
        self.home_frame: ttk.Frame | None = None
        self.inventory_frame: ttk.Frame | None = None
        self.catalog_frame: ttk.Frame | None = None
        self._inventory_list_view: InventoryListView | None = None
        self.inventory_detail_view: InventoryDetailView | None = None
        self._quality_center_view: QualityCenterView | None = None
        self._inventory_detail_view: InventoryDetailView | None = None
        self.language_label: ttk.Label | None = None
        self.language_combo: ttk.Combobox | None = None
        self.dashboard_view: DashboardView | None = None

        self._configure_root()
        self._build_ui()
        self.refresh_inventory()
        self.apply_translations()

    def _configure_root(self) -> None:
        self.root.minsize(900, 620)
        self.root.geometry("1120x720")
        self.root.configure(background=PALETTE["background"])
        self.root.columnconfigure(0, weight=1)
        self.root.rowconfigure(0, weight=1)
        self.root.protocol("WM_DELETE_WINDOW", self._on_close)

    def _on_close(self) -> None:
        if self._catalog_view is not None:
            try:
                self._catalog_view.cancel_pending()
            except Exception:
                pass
        self.root.destroy()

    def _build_ui(self) -> None:
        container = ttk.Frame(self.root, style="App.TFrame", padding=24)
        container.grid(row=0, column=0, sticky="nsew")
        container.columnconfigure(0, weight=1)
        container.rowconfigure(1, weight=1)

        header = ttk.Frame(container, style="Header.TFrame", padding=(20, 16))
        header.grid(row=0, column=0, sticky="ew", pady=(0, 16))
        header.columnconfigure(0, weight=1)
        header.columnconfigure(1, weight=0)

        header_text = ttk.Frame(header, style="Header.TFrame")
        header_text.grid(row=0, column=0, sticky="w")
        self.header_title = ttk.Label(header_text, style="HeaderTitle.TLabel")
        self.header_title.grid(row=0, column=0, sticky="w")
        self.header_subtitle = ttk.Label(header_text, style="HeaderSubtitle.TLabel")
        self.header_subtitle.grid(row=1, column=0, sticky="w", pady=(4, 0))

        language_frame = ttk.Frame(header, style="Header.TFrame")
        language_frame.grid(row=0, column=1, sticky="e")
        self.language_label = ttk.Label(language_frame, style="HeaderLanguage.TLabel")
        self.language_label.grid(row=0, column=0, sticky="e", padx=(0, 8))
        self.language_combo = ttk.Combobox(
            language_frame,
            state="readonly",
            width=12,
            style="Header.TCombobox",
        )
        self.language_combo.grid(row=0, column=1, sticky="e")
        self.language_combo.bind("<<ComboboxSelected>>", self._on_language_change)

        self.notebook = ttk.Notebook(container)
        self.notebook.grid(row=1, column=0, sticky="nsew")
        self.notebook.bind("<<NotebookTabChanged>>", self._on_tab_changed)

        self.home_frame = ttk.Frame(self.notebook, style="App.TFrame", padding=(0, 8, 0, 0))
        self.inventory_frame = ttk.Frame(self.notebook, style="App.TFrame", padding=(0, 8, 0, 0))
        self.builds_frame = ttk.Frame(self.notebook, style="App.TFrame", padding=(0, 8, 0, 0))
        self.catalog_frame = ttk.Frame(self.notebook, style="App.TFrame", padding=0)
        self.notebook.add(self.home_frame, text="")
        self.notebook.add(self.inventory_frame, text="")
        self.notebook.add(self.builds_frame, text="")
        self.notebook.add(self.catalog_frame, text="")
        self._tab_index_by_id = {NAV_HOME: 0, NAV_INVENTORY: 1, NAV_BUILDS: 2, NAV_CATALOG: 3}
        self._builds_list_view: BuildListView | None = None
        self._builds_compare_view = None
        self._compare_build_ids: tuple | None = None
        self._builds_detail_view: BuildDetailView | None = None
        self._detail_build_id: str | None = None

        self._build_home_view(self.home_frame)
        self._build_inventory_view(self.inventory_frame)
        self._build_builds_view(self.builds_frame)
        self._build_catalog_placeholder(self.catalog_frame)

    def _build_catalog_placeholder(self, parent: ttk.Frame) -> None:
        parent.columnconfigure(0, weight=1)
        parent.rowconfigure(0, weight=1)
        placeholder = ttk.Frame(parent, style="App.TFrame")
        placeholder.grid(row=0, column=0, sticky="nsew")
        placeholder.columnconfigure(0, weight=1)

    def _build_home_view(self, parent: ttk.Frame) -> None:
        parent.columnconfigure(0, weight=1)
        self.dashboard_view = DashboardView(parent, self.translator)

    def _build_inventory_view(self, parent: ttk.Frame) -> None:
        parent.columnconfigure(0, weight=1)
        parent.rowconfigure(0, weight=1)

        self._inventory_list_view = InventoryListView(
            parent,
            self.translator,
            on_add=self._on_add_component,
            on_edit=self._edit_component_by_id,
            on_view_details=self._show_inventory_detail,
            on_delete=self._on_delete_component_by_id_callback,
            on_manage_catalog=self._show_catalog_tab,
            on_export=self._on_export_inventory,
            on_restore=self._on_restore_inventory,
            on_quality=self._show_quality_center,
            on_add_from_catalog=self._on_add_from_catalog,
            on_bulk_delete=self._on_bulk_delete,
            on_import_csv=self._on_import_csv,
            on_export_csv_template=self._on_export_csv_template_action,
        )
        self._inventory_list_view.grid(row=0, column=0, sticky="nsew")

        self.inventory_detail_view = InventoryDetailView(
            parent,
            self.translator,
            on_back=self._show_inventory_list,
            on_edit=self._on_edit_detail_by_id,
            on_delete=self._on_delete_detail_by_id,
            on_add_technical_profile=self._on_add_technical_profile,
            on_edit_technical_profile=self._on_edit_technical_profile,
            on_delete_technical_profile=self._on_delete_technical_profile,
        )
        self._inventory_detail_view = self.inventory_detail_view
        self.inventory_detail_view.grid(row=0, column=0, sticky="nsew")
        self.inventory_detail_view.grid_remove()

        self._quality_center_view = QualityCenterView(
            parent,
            self.translator,
            on_back=self._show_inventory_list,
            on_edit_profile=self._on_edit_technical_profile,
        )
        self._quality_center_view.grid(row=0, column=0, sticky="nsew")
        self._quality_center_view.grid_remove()



    def _show_inventory_list(self) -> None:
        self._detail_component_id = None
        if self._quality_center_view is not None:
            self._quality_center_view.grid_remove()
            self._quality_center_view.clear()
        if self.inventory_detail_view is not None:
            self.inventory_detail_view.clear_component()
            self.inventory_detail_view.grid_remove()
        if self._inventory_list_view is not None:
            self._inventory_list_view.grid()

    def _show_quality_center(self) -> None:
        if self._quality_center_view is None:
            return
        from pc_parts_organizer.data_quality import audit_inventory
        comps = self.service.get_components()
        profs = {p.component_id: p for p in self.service.get_technical_profiles()}
        self._quality_center_view.set_translator(self.translator)
        self._quality_center_view.set_data(
            audit_inventory(comps, profs), {c.id: c for c in comps})
        if self._inventory_list_view is not None:
            self._inventory_list_view.grid_remove()
        if self.inventory_detail_view is not None:
            self.inventory_detail_view.grid_remove()
        self._quality_center_view.grid()

    def _show_inventory_detail(self, component_id: str) -> None:
        component = self.service.get_component(component_id)
        if component is None:
            messagebox.showerror(
                self.translator.t("messages.component_not_found_title"),
                self.translator.t("messages.component_not_found"),
                parent=self.root,
            )
            self.refresh_inventory()
            self._show_inventory_list()
            return
        self._detail_component_id = component.id
        profile = None
        try:
            profile = self.service.get_technical_profile(component.id)
        except Exception:
            profile = None
        if self.inventory_detail_view is not None:
            self.inventory_detail_view.set_component(component)
            self.inventory_detail_view.set_technical_profile(profile)
        if self._inventory_list_view is not None:
            self._inventory_list_view.grid_remove()
        if self.inventory_detail_view is not None:
            self.inventory_detail_view.grid()


    def _apply_notebook_tab_labels(self) -> None:
        if self.notebook is None:
            return
        self.notebook.tab(self._tab_index_by_id[NAV_HOME], text=self.translator.t("nav.home"))
        self.notebook.tab(self._tab_index_by_id[NAV_INVENTORY], text=self.translator.t("nav.inventory"))
        self.notebook.tab(self._tab_index_by_id[NAV_BUILDS], text=self.translator.t("nav.builds"))
        self.notebook.tab(self._tab_index_by_id[NAV_CATALOG], text=self.translator.t("nav.catalog"))

    def _apply_language_selector(self) -> None:
        if self.language_combo is None:
            return
        labels = [LANGUAGE_NAMES[code] for code in SUPPORTED_LANGUAGES]
        self.language_combo.configure(values=labels)
        self.language_combo.set(LANGUAGE_NAMES.get(self.translator.language, LANGUAGE_NAMES[SUPPORTED_LANGUAGES[0]]))

    def _apply_detail_translations(self) -> None:
        if self.inventory_detail_view is not None:
            self.inventory_detail_view.set_translator(self.translator)
        if self._detail_component_id is not None and self.inventory_detail_view is not None and self.inventory_detail_view.winfo_ismapped():
            self._show_inventory_detail(self._detail_component_id)

    def apply_translations(self) -> None:
        self.root.title(self.translator.t("app.window_title"))
        if self.header_title is not None:
            self.header_title.configure(text=self.translator.t("app.window_title"))
        if self.header_subtitle is not None:
            self.header_subtitle.configure(text=self.translator.t("app.header_subtitle"))
        if self.language_label is not None:
            self.language_label.configure(text=self.translator.t("app.language_label"))
        if self.dashboard_view is not None:
            self.dashboard_view.set_translator(self.translator)
        if self._inventory_list_view is not None:
            self._inventory_list_view.set_translator(self.translator)
        if self._quality_center_view is not None:
            self._quality_center_view.set_translator(self.translator)
        self._apply_notebook_tab_labels()
        self._apply_language_selector()
        self._apply_detail_translations()
        if self._catalog_view is not None:
            self._catalog_view.set_translator(self.translator)
        if self._builds_list_view is not None:
            self._builds_list_view.set_translator(self.translator)
        if self._builds_detail_view is not None:
            self._builds_detail_view.set_translator(self.translator)
        if self._builds_compare_view is not None:
            self._builds_compare_view.set_translator(self.translator)
        if self.dashboard_view is not None:
            self.dashboard_view.update_summary(self._summary_cache)
        if self._components_cache and self._inventory_list_view is not None:
            self._inventory_list_view.set_components(self._components_cache)
        if self._inventory_list_view is not None:
            self._inventory_list_view.update_action_states()

    def refresh_inventory(self) -> None:
        components = self.service.get_components()
        summary = self.service.get_summary()
        self._components_cache = list(components)
        self._summary_cache = summary
        if self.dashboard_view is not None:
            self.dashboard_view.update_summary(summary)
        self._refresh_table(self._components_cache)
        self._refresh_detail_if_visible()
        self._refresh_quality_if_visible()

    def _refresh_quality_if_visible(self) -> None:
        if self._quality_center_view is None:
            return
        try:
            visible = self._quality_center_view.winfo_ismapped()
        except Exception:
            visible = False
        if not visible:
            return
        # Recompute from current state; hidden view defers (stays stale-free
        # because set_data only runs on explicit show/refresh).
        from pc_parts_organizer.data_quality import audit_inventory
        comps = self.service.get_components()
        profs = {p.component_id: p for p in self.service.get_technical_profiles()}
        self._quality_center_view.set_data(
            audit_inventory(comps, profs), {c.id: c for c in comps})

    def _refresh_detail_if_visible(self) -> None:
        if not self._detail_component_id:
            return
        if self.inventory_detail_view is None or not self.inventory_detail_view.winfo_ismapped():
            self._detail_component_id = None
            return
        component = self.service.get_component(self._detail_component_id)
        if component is None:
            self._show_inventory_list()
            return
        self._show_inventory_detail(self._detail_component_id)

    def _refresh_table(self, components: list) -> None:
        if self._inventory_list_view is not None:
            self._inventory_list_view.set_components(components)


    def _on_language_change(self, _event: object) -> None:
        if self.language_combo is None:
            return
        selected_label = self.language_combo.get()
        selected_code = None
        for code in SUPPORTED_LANGUAGES:
            if LANGUAGE_NAMES.get(code) == selected_label:
                selected_code = code
                break
        if selected_code is None or selected_code == self.translator.language:
            return
        try:
            self.translator.change_language(selected_code)
        except (LocalizationError, StorageError):
            messagebox.showerror(
                self.translator.t("app.window_title"),
                self.translator.t("app.language_save_error"),
                parent=self.root,
            )
            self._apply_language_selector()
            return
        self.apply_translations()

    def _on_tree_select(self, _event: object = None) -> None:
        self._update_inventory_actions()

    def _on_tree_double_click(self, _event: object = None) -> None:
        if self._inventory_list_view is not None:
            self._inventory_list_view._on_tree_double_click(_event)

    def _update_inventory_actions(self) -> None:
        if self._inventory_list_view is not None:
            self._inventory_list_view.update_action_states()


    def _on_view_details(self) -> None:
        component_id = self.get_selected_component_id()
        if not component_id:
            return
        self._show_inventory_detail(component_id)

    def _confirm_delete(self, component) -> bool:
        """Show explicit delete confirmation; returns True only on explicit confirmation."""
        dialog = tk.Toplevel(self.root)
        dialog.title(self.translator.t("messages.delete_title"))
        dialog.transient(self.root)
        dialog.configure(background=PALETTE["surface"])
        dialog.resizable(False, False)
        result = {"confirmed": False}

        def cancel() -> None:
            dialog.destroy()

        def confirm() -> None:
            result["confirmed"] = True
            dialog.destroy()

        dialog.protocol("WM_DELETE_WINDOW", cancel)
        frame = ttk.Frame(dialog, style="Form.TFrame", padding=16)
        frame.grid(row=0, column=0, sticky="nsew")
        frame.columnconfigure(0, weight=1)

        category = self.translator.translate_category(component.category)
        info = f"{self.translator.t('table.category')}: {category}\n{self.translator.t('table.manufacturer')}: {component.manufacturer}\n{self.translator.t('table.model')}: {component.model}"
        ttk.Label(frame, text=info, style="Form.TLabel", justify="left").grid(row=0, column=0, sticky="w")
        ttk.Label(
            frame,
            text=self.translator.t("messages.delete_confirm_warning"),
            style="Form.TLabel",
            wraplength=420,
            justify="left",
        ).grid(row=1, column=0, sticky="w", pady=(12, 16))

        actions = ttk.Frame(frame, style="Form.TFrame")
        actions.grid(row=2, column=0, sticky="e")
        cancel_btn = ttk.Button(actions, text=self.translator.t("messages.delete_cancel_button"), style="Secondary.TButton", command=cancel)
        cancel_btn.grid(row=0, column=0, padx=(0, 8))
        delete_btn = ttk.Button(actions, text=self.translator.t("messages.delete_confirm_button"), style="Primary.TButton", command=confirm)
        delete_btn.grid(row=0, column=1)
        cancel_btn.focus_set()
        dialog.bind("<Escape>", lambda _e: cancel())

        dialog.update_idletasks()
        try:
            x = self.root.winfo_rootx() + max(0, (self.root.winfo_width() - dialog.winfo_width()) // 2)
            y = self.root.winfo_rooty() + max(0, (self.root.winfo_height() - dialog.winfo_height()) // 2)
            dialog.geometry(f"+{x}+{y}")
        except Exception:
            pass
        dialog.grab_set()
        self.root.wait_window(dialog)
        return result["confirmed"]

    def _delete_component_by_id(self, component_id: str, from_detail: bool = False) -> bool:
        """Delete a specific component by UUID after explicit confirmation. Returns True if deleted."""
        component = self.service.get_component(component_id)
        if component is None:
            messagebox.showerror(
                self.translator.t("messages.component_not_found_title"),
                self.translator.t("messages.component_not_found"),
                parent=self.root,
            )
            self.refresh_inventory()
            self._show_inventory_list()
            return False
        if not self._confirm_delete(component):
            return False
        try:
            self.service.delete_component(component_id)
        except ComponentInUseError:
            messagebox.showerror(
                self.translator.t("messages.delete_component_in_use_title"),
                self.translator.t("messages.delete_component_in_use"),
                parent=self.root,
            )
            return False
        except ComponentNotFoundError:
            messagebox.showerror(
                self.translator.t("messages.component_not_found_title"),
                self.translator.t("messages.component_not_found"),
                parent=self.root,
            )
            self.refresh_inventory()
            self._show_inventory_list()
            return False
        except StorageError:
            messagebox.showerror(
                self.translator.t("messages.delete_error_title"),
                self.translator.t("messages.delete_error"),
                parent=self.root,
            )
            return False
        self._detail_component_id = None
        self.refresh_inventory()
        if self._inventory_list_view is not None:
            self._inventory_list_view.clear_selection()
        self._show_inventory_list()
        self._update_inventory_actions()
        self._refresh_compare_if_visible()
        return True

    def _on_delete_component(self) -> None:
        component_id = self.get_selected_component_id()
        if not component_id:
            return
        self._delete_component_by_id(component_id, from_detail=False)

    def _on_delete_detail_by_id(self, component_id: str) -> bool:
        return self._delete_component_by_id(component_id, from_detail=True)

    def _on_delete_detail(self) -> None:
        if not self._detail_component_id:
            return
        self._on_delete_detail_by_id(self._detail_component_id)

    def _on_add_component(self) -> None:
        form = ComponentForm(self.root, self.translator, self.catalog_service)
        self.root.wait_window(form.window)
        result = form.result
        if result is None:
            return
        try:
            self.service.add_component(
                category=result.category,
                manufacturer=result.manufacturer,
                model=result.model,
                specifications=result.specifications,
                notes=result.notes,
                status=result.status,
                location=result.location,
                purchase_date=result.purchase_date,
                warranty_end_date=result.warranty_end_date,
                purchase_price=result.purchase_price,
                purchase_currency=result.purchase_currency,
            )
        except ComponentValidationError:
            messagebox.showerror(
                self.translator.t("messages.validation_title"),
                self.translator.t("messages.validation_error"),
                parent=self.root,
            )
            return
        except StorageError:
            messagebox.showerror(
                self.translator.t("messages.save_error_title"),
                self.translator.t("messages.save_error"),
                parent=self.root,
            )
            return
        self.refresh_inventory()
        self._refresh_compare_if_visible()

    @staticmethod
    def _catalog_entry_to_component_dict(entry) -> dict:
        # Only fields with a real Component counterpart travel: category,
        # manufacturer, model, specifications, notes. Commercial provenance
        # (source, source_url, license, attribution, verified_at) never
        # becomes technical verification; new items start unverified.
        return {
            "category": entry.category,
            "manufacturer": entry.manufacturer,
            "model": entry.model,
            "specifications": entry.specifications or "",
            "notes": entry.notes or "",
        }

    def _on_add_from_catalog(self) -> None:
        from pc_parts_organizer.ui.catalog_selector import CatalogSelectorWindow

        try:
            self.catalog_service.initialize()
        except CatalogStorageError:
            messagebox.showerror(
                self.translator.t("messages.catalog_error_title"),
                self.translator.t("catalog_selector.initialization_error"),
                parent=self.root,
            )
            return
        selector = CatalogSelectorWindow(self.root, self.catalog_service, self.translator, multi=True)
        self.root.wait_window(selector.window)
        entries = list(getattr(selector, "results", []) or [])
        if not entries:
            return
        items = [self._catalog_entry_to_component_dict(e) for e in entries]
        try:
            result = self.service.add_components(items)
        except BatchValidationError as exc:
            self.refresh_inventory()
            self._show_bulk_result(
                self.translator.t("catalog_bulk.validation_title"),
                self.translator.t("catalog_bulk.validation_error"),
                self._catalog_rejection_lines(exc.rejected),
                self.translator.t("catalog_bulk.close"),
            )
            return
        except StorageError:
            messagebox.showerror(
                self.translator.t("catalog_bulk.error_title"),
                self.translator.t("catalog_bulk.error"),
                parent=self.root,
            )
            return
        self.refresh_inventory()
        self._refresh_compare_if_visible()
        add_lines = self._catalog_add_result_lines(result)
        self._show_bulk_result(
            self.translator.t("catalog_bulk.result_title"),
            add_lines[0],
            add_lines,
            self.translator.t("catalog_bulk.close"),
        )

    def _show_bulk_result(self, title: str, summary: str, lines: list[str], close_label: str):
        """Scrollable result dialog: compact summary plus the complete list.

        Replaces truncated messagebox reports so no created, duplicate,
        rejected, deleted or skipped name is ever inaccessible.
        """
        dialog = tk.Toplevel(self.root)
        dialog.title(title)
        dialog.transient(self.root)
        dialog.configure(background=PALETTE["surface"])
        dialog.minsize(560, 420)
        dialog.geometry("620x480")
        dialog.protocol("WM_DELETE_WINDOW", dialog.destroy)
        dialog.columnconfigure(0, weight=1)
        dialog.rowconfigure(0, weight=1)
        frame = ttk.Frame(dialog, style="Form.TFrame", padding=16)
        frame.grid(row=0, column=0, sticky="nsew")
        frame.columnconfigure(0, weight=1)
        frame.rowconfigure(1, weight=1)
        ttk.Label(frame, text=summary, style="Form.TLabel",
                  wraplength=560, justify="left").grid(row=0, column=0, sticky="w", pady=(0, 8))
        text = tk.Text(frame, wrap="word", height=16, background=PALETTE["surface"],
                       foreground=PALETTE["text"], highlightthickness=1,
                       highlightbackground=PALETTE["border"], bd=0, padx=6, pady=6)
        scroll = ttk.Scrollbar(frame, orient="vertical", command=text.yview)
        text.configure(yscrollcommand=scroll.set)
        text.grid(row=1, column=0, sticky="nsew")
        scroll.grid(row=1, column=1, sticky="ns")
        text.insert("1.0", "\n".join(lines) if lines else summary)
        text.configure(state="disabled")
        actions = ttk.Frame(frame, style="Form.TFrame")
        actions.grid(row=2, column=0, columnspan=2, sticky="e", pady=(12, 0))
        close_btn = ttk.Button(actions, text=close_label, style="Primary.TButton", command=dialog.destroy)
        close_btn.grid(row=0, column=0)
        close_btn.focus_set()
        dialog.bind("<Escape>", lambda _e: dialog.destroy())
        dialog.update_idletasks()
        try:
            x = self.root.winfo_rootx() + max(0, (self.root.winfo_width() - dialog.winfo_width()) // 2)
            y = self.root.winfo_rooty() + max(0, (self.root.winfo_height() - dialog.winfo_height()) // 2)
            dialog.geometry(f"+{x}+{y}")
        except Exception:
            pass
        dialog.grab_set()
        return dialog

    def _catalog_add_result_lines(self, result) -> list[str]:
        lines = [self.translator.t("catalog_bulk.result").format(
            created=len(result.created), duplicates=len(result.duplicates), rejected=0)]
        for comp in result.created:
            maker = str(getattr(comp, "manufacturer", "") or "").strip()
            model = str(getattr(comp, "model", "") or "").strip()
            name = " ".join(p for p in (maker, model) if p) or getattr(comp, "id", "?")
            lines.append(self.translator.t("catalog_bulk.created_line").format(name=name))
        for dup in result.duplicates:
            lines.append(self.translator.t("catalog_bulk.duplicate_line").format(
                name=dup.name, matched=dup.matched_name))
        return lines

    def _catalog_rejection_lines(self, rejected) -> list[str]:
        return [self.translator.t("catalog_bulk.rejected_line").format(
            name=r.name or "?", reason=r.reason) for r in rejected]

    def _bulk_delete_result_lines(self, result) -> list[str]:
        lines = [self.translator.t("bulk.result").format(
            deleted=len(result.deleted), skipped=len(result.skipped_in_use), not_found=len(result.not_found))]
        for comp in result.deleted:
            maker = str(getattr(comp, "manufacturer", "") or "").strip()
            model = str(getattr(comp, "model", "") or "").strip()
            name = " ".join(p for p in (maker, model) if p) or getattr(comp, "id", "?")
            lines.append(self.translator.t("bulk.deleted_line").format(name=name))
        for skip in result.skipped_in_use:
            lines.append(self.translator.t("bulk.skipped_line").format(name=skip.name, build=skip.build_name))
        for missing in result.not_found:
            lines.append(self.translator.t("bulk.not_found_line").format(component_id=missing))
        return lines

    def _show_csv_import_result(self, analysis, result) -> None:
        """Scrollable result for the CSV import: full lists, no truncation."""
        lines = [self.translator.t("csv_import.result_summary").format(
            created=len(result.created), inventory=len(analysis.inventory_duplicates),
            internal=len(analysis.internal_duplicates), rejected=len(analysis.rejected),
            empty=len(analysis.empty_rows))]
        for comp in result.created:
            maker = str(getattr(comp, "manufacturer", "") or "").strip()
            model = str(getattr(comp, "model", "") or "").strip()
            name = " ".join(p for p in (maker, model) if p) or getattr(comp, "id", "?")
            lines.append(self.translator.t("csv_import.created_line").format(name=name))
        for entry in analysis.inventory_duplicates:
            cand = entry.component or {}
            name = " ".join(str(cand.get(k, "") or "").strip() for k in ("manufacturer", "model")).strip()
            lines.append(self.translator.t("csv_import.dup_inventory_line").format(
                name=name or f"línea {entry.line}", matched=entry.duplicate_of))
        for entry in analysis.internal_duplicates:
            cand = entry.component or {}
            name = " ".join(str(cand.get(k, "") or "").strip() for k in ("manufacturer", "model")).strip()
            lines.append(self.translator.t("csv_import.dup_internal_line").format(
                name=name or f"línea {entry.line}", line=entry.line))
        for entry in analysis.rejected:
            cand = entry.component or {}
            name = " ".join(str(cand.get(k, "") or "").strip() for k in ("manufacturer", "model")).strip()
            reason = "; ".join(entry.reasons)
            lines.append(self.translator.t("csv_import.rejected_line").format(
                line=entry.line, name=name or "?", reason=reason))
        for line in analysis.empty_rows:
            lines.append(self.translator.t("csv_import.empty_line").format(line=line))
        self._show_bulk_result(
            self.translator.t("csv_import.result_title"),
            lines[0], lines, self.translator.t("csv_import.close"))

    def _open_csv_import(self) -> None:
        from pc_parts_organizer.csv_inventory_import import (
            CsvInventoryImportError,
            analyze_csv,
            csv_template_text,
            DELIMITERS,
            SUPPORTED_ENCODINGS,
        )
        from pc_parts_organizer.models import Component

        dest = filedialog.askopenfilename(
            parent=self.root,
            title=self.translator.t("csv_import.select_dialog_title"),
            filetypes=[(self.translator.t("csv_import.csv_file_type"), "*.csv")],
        )
        if not dest:
            return
        analysis = None
        error_detail = ""
        try:
            analysis = analyze_csv(dest, inventory_components=self.service.get_components())
        except CsvInventoryImportError as exc:
            error_detail = str(exc)
        if analysis is None:
            messagebox.showerror(
                self.translator.t("csv_import.error_title"),
                self.translator.t("csv_import.error").format(detail=error_detail),
                parent=self.root,
            )
            return

        t = self.translator
        dialog = tk.Toplevel(self.root)
        dialog.title(t.t("csv_import.preview_title"))
        dialog.transient(self.root)
        dialog.configure(background=PALETTE["surface"])
        dialog.minsize(760, 560)
        dialog.geometry("900x640")
        dialog.protocol("WM_DELETE_WINDOW", dialog.destroy)
        dialog.grab_set()
        frame = ttk.Frame(dialog, style="Form.TFrame", padding=14)
        frame.grid(row=0, column=0, sticky="nsew")
        dialog.columnconfigure(0, weight=1)
        dialog.rowconfigure(0, weight=1)
        frame.columnconfigure(0, weight=1)
        frame.rowconfigure(3, weight=1)

        # options row (encoding/delimiter override, re-analyze)
        opts = ttk.Frame(frame, style="Form.TFrame")
        opts.grid(row=0, column=0, sticky="ew", pady=(0, 8))
        opts.columnconfigure(3, weight=1)
        ttk.Label(opts, text=t.t("csv_import.encoding_label"), style="Form.TLabel").grid(
            row=0, column=0, padx=(0, 6))
        enc_var = tk.StringVar(value=analysis.encoding)
        enc_combo = ttk.Combobox(opts, values=list(SUPPORTED_ENCODINGS), state="readonly",
                                 width=14, textvariable=enc_var)
        enc_combo.grid(row=0, column=1, padx=(0, 12))
        ttk.Label(opts, text=t.t("csv_import.delimiter_label"), style="Form.TLabel").grid(
            row=0, column=2, padx=(0, 6))
        delim_display = {",": "comas (,)", ";": "punto y coma (;)", "\t": "tabulador (\\t)"}
        delim_var = tk.StringVar(value=delim_display.get(analysis.delimiter, analysis.delimiter))
        delim_combo = ttk.Combobox(opts, values=list(delim_display.values()), state="readonly",
                                   width=18, textvariable=delim_var)
        delim_combo.grid(row=0, column=3, sticky="w")
        reanalyze_btn = ttk.Button(opts, style="Secondary.TButton", text=t.t("csv_import.reanalyze"))
        reanalyze_btn.grid(row=0, column=4, padx=(12, 0))

        summary = ttk.Label(frame, style="Form.TLabel", justify="left", wraplength=820)
        summary.grid(row=1, column=0, sticky="w", pady=(0, 8))

        # full rows table
        table_frame = ttk.Frame(frame, style="Surface.TFrame")
        table_frame.grid(row=3, column=0, sticky="nsew", pady=(0, 8))
        table_frame.columnconfigure(0, weight=1)
        table_frame.rowconfigure(0, weight=1)
        tree = ttk.Treeview(table_frame, columns=("line", "status", "name", "reason", "dup"),
                            show="headings", style="Inventory.Treeview", selectmode="browse")
        tree.heading("line", text=t.t("csv_import.line"), anchor="w")
        tree.heading("status", text=t.t("csv_import.status"), anchor="w")
        tree.heading("name", text=t.t("table.manufacturer") + " / " + t.t("table.model"), anchor="w")
        tree.heading("reason", text=t.t("csv_import.reason"), anchor="w")
        tree.heading("dup", text=t.t("csv_import.duplicate_of"), anchor="w")
        tree.column("line", width=60, minwidth=50)
        tree.column("status", width=160, minwidth=120)
        tree.column("name", width=260, minwidth=160)
        tree.column("reason", width=280, minwidth=160)
        tree.column("dup", width=160, minwidth=120)
        vsb = ttk.Scrollbar(table_frame, orient="vertical", command=tree.yview)
        tree.configure(yscrollcommand=vsb.set)
        tree.grid(row=0, column=0, sticky="nsew")
        vsb.grid(row=0, column=1, sticky="ns")

        actions = ttk.Frame(frame, style="Form.TFrame")
        actions.grid(row=4, column=0, sticky="e")
        import_btn = ttk.Button(actions, style="Primary.TButton",
                                text=t.t("csv_import.import_valid"), state="disabled")
        import_btn.grid(row=0, column=1)
        ttk.Button(actions, style="Secondary.TButton", text=t.t("csv_import.cancel"),
                   command=dialog.destroy).grid(row=0, column=0, padx=(0, 8))

        def render(rows) -> None:
            for item in tree.get_children():
                tree.delete(item)
            for entry, status_key, reason, dup in rows:
                cand = entry.component or {}
                name = " ".join(str(cand.get(k, "") or "").strip()
                                for k in ("manufacturer", "model")).strip() or "?"
                tree.insert("", "end", values=(
                    entry.line, t.t(f"csv_import.state_{status_key}"), name, reason, dup))

        def refresh(analysis_obj) -> None:
            rows = []
            for e in analysis_obj.valid_new:
                rows.append((e, "valid", "", ""))
            for e in analysis_obj.inventory_duplicates:
                rows.append((e, "inventory_duplicate", "", e.duplicate_of))
            for e in analysis_obj.internal_duplicates:
                rows.append((e, "internal_duplicate", "", e.duplicate_of))
            for e in analysis_obj.rejected:
                rows.append((e, "rejected", "; ".join(e.reasons), ""))
            for line in analysis_obj.empty_rows:
                dummy = type("Row", (), {"line": line, "component": None})()
                rows.append((dummy, "empty", "", ""))
            rows.sort(key=lambda r: (r[0].line, 0 if r[1] != "empty" else 1))
            render(rows)
            summary.configure(text=(
                f"{t.t('csv_import.file_label')}: {Path(analysis_obj.path).name}\n"
                f"{t.t('csv_import.encoding_detected')}: {analysis_obj.encoding} · "
                f"{t.t('csv_import.delimiter_detected')}: {analysis_obj.delimiter!r}\n"
                f"{t.t('csv_import.total_rows')}: {analysis_obj.total_rows} · "
                f"{t.t('csv_import.valid_rows')}: {analysis_obj.valid_count} · "
                f"{t.t('csv_import.inventory_duplicates')}: {analysis_obj.inventory_duplicate_count} · "
                f"{t.t('csv_import.internal_duplicates')}: {analysis_obj.internal_duplicate_count} · "
                f"{t.t('csv_import.rejected_rows')}: {analysis_obj.rejected_count} · "
                f"{t.t('csv_import.empty_rows')}: {len(analysis_obj.empty_rows)}\n"
                + (f"{t.t('csv_import.ignored_columns')}: {', '.join(analysis_obj.ignored_columns)}"
                   if analysis_obj.ignored_columns else "")))
            import_btn.configure(state="normal" if analysis_obj.components else "disabled")

        refresh(analysis)

        def on_reanalyze() -> None:
            nonlocal analysis
            enc = enc_var.get()
            delim = next((k for k, v in delim_display.items() if v == delim_var.get()), ",")
            try:
                analysis = analyze_csv(dest, encoding=enc, delimiter=delim,
                                       inventory_components=self.service.get_components())
            except CsvInventoryImportError as exc:
                messagebox.showerror(
                    t.t("csv_import.error_title"),
                    t.t("csv_import.error").format(detail=str(exc)),
                    parent=dialog,
                )
                return
            refresh(analysis)

        reanalyze_btn.configure(command=on_reanalyze)

        def on_import() -> None:
            try:
                preview = self.service.preview_add_components(analysis.components)
            except BatchValidationError as exc:
                messagebox.showerror(
                    t.t("csv_import.error_title"),
                    t.t("csv_import.error").format(detail="; ".join(
                        f"[{r.index}] {r.name}: {r.reason}" for r in exc.rejected)),
                    parent=dialog,
                )
                return
            try:
                result = self.service.add_components(analysis.components)
            except StorageError:
                messagebox.showerror(
                    t.t("csv_import.save_error_title"),
                    t.t("csv_import.save_error"),
                    parent=dialog,
                )
                return
            dialog.destroy()
            self.refresh_inventory()
            self._refresh_compare_if_visible()
            self._show_csv_import_result(analysis, result)

        import_btn.configure(command=on_import)

    def _on_export_csv_template(self) -> None:
        from pc_parts_organizer.csv_inventory_import import csv_template_text

        dest = filedialog.asksaveasfilename(
            parent=self.root,
            title=self.translator.t("csv_import.template_title"),
            initialfile="pc-parts-organizer-inventory-template.csv",
            defaultextension=".csv",
            filetypes=[(self.translator.t("csv_import.csv_file_type"), "*.csv")],
        )
        if not dest:
            return
        try:
            with open(dest, "w", encoding="utf-8-sig", newline="") as fh:
                fh.write(csv_template_text())
        except OSError:
            messagebox.showerror(
                self.translator.t("csv_import.template_title"),
                self.translator.t("csv_import.template_error"),
                parent=self.root,
            )
            return
        messagebox.showinfo(
            self.translator.t("csv_import.template_success_title"),
            self.translator.t("csv_import.template_success").format(path=dest),
            parent=self.root,
        )

    def _on_import_csv(self) -> None:
        self._open_csv_import()

    def _on_export_csv_template_action(self) -> None:
        self._on_export_csv_template()

    def _bulk_owner_by_component(self) -> dict[str, str]:
        owners: dict[str, str] = {}
        try:
            builds = self.service.get_builds()
        except Exception:
            return owners
        for build in builds:
            for cid in list(getattr(build, "component_ids", []) or []):
                owners.setdefault(str(cid), str(getattr(build, "name", "") or getattr(build, "id", "")))
        return owners

    def _confirm_bulk_delete(self, selected: int, deletable: int, protected_lines: list[str]) -> bool:
        result = {"confirmed": False}
        dialog = tk.Toplevel(self.root)
        dialog.title(self.translator.t("bulk.delete_title"))
        dialog.transient(self.root)
        dialog.configure(background=PALETTE["surface"])
        dialog.resizable(True, True)
        dialog.minsize(520, 300)
        dialog.protocol("WM_DELETE_WINDOW", dialog.destroy)
        dialog.columnconfigure(0, weight=1)
        dialog.rowconfigure(0, weight=1)
        frame = ttk.Frame(dialog, style="Form.TFrame", padding=16)
        frame.grid(row=0, column=0, sticky="nsew")
        frame.columnconfigure(0, weight=1)
        frame.rowconfigure(1, weight=1)
        ttk.Label(
            frame,
            text=self.translator.t("bulk.delete_confirm").format(
                selected=selected, deletable=deletable, protected=selected - deletable),
            style="Form.TLabel", wraplength=520, justify="left",
        ).grid(row=0, column=0, sticky="w")
        if protected_lines:
            # shortcut: full protected list in a scrollable box; the counts
            # above stay exact and the service re-validates at execution.
            text = tk.Text(frame, wrap="word", height=8, background=PALETTE["surface"],
                           foreground=PALETTE["text"], highlightthickness=1,
                           highlightbackground=PALETTE["border"], bd=0, padx=6, pady=6)
            scroll = ttk.Scrollbar(frame, orient="vertical", command=text.yview)
            text.configure(yscrollcommand=scroll.set)
            text.grid(row=1, column=0, sticky="nsew", pady=(8, 0))
            scroll.grid(row=1, column=1, sticky="ns", pady=(8, 0))
            text.insert("1.0", "\n".join(protected_lines))
            text.configure(state="disabled")
        actions = ttk.Frame(frame, style="Form.TFrame")
        actions.grid(row=2, column=0, sticky="e", pady=(12, 0))

        def cancel() -> None:
            dialog.destroy()

        def confirm() -> None:
            result["confirmed"] = True
            dialog.destroy()

        dialog.bind("<Escape>", lambda _e: cancel())
        ttk.Button(actions, text=self.translator.t("bulk.delete_cancel_button"),
                   style="Secondary.TButton", command=cancel).grid(row=0, column=0, padx=(0, 8))
        confirm_btn = ttk.Button(actions, text=self.translator.t("bulk.delete_confirm_button"),
                                 style="Primary.TButton", command=confirm)
        confirm_btn.grid(row=0, column=1)
        if deletable <= 0:
            confirm_btn.configure(state="disabled")
        confirm_btn.focus_set()
        dialog.update_idletasks()
        try:
            x = self.root.winfo_rootx() + max(0, (self.root.winfo_width() - dialog.winfo_width()) // 2)
            y = self.root.winfo_rooty() + max(0, (self.root.winfo_height() - dialog.winfo_height()) // 2)
            dialog.geometry(f"+{x}+{y}")
        except Exception:
            pass
        dialog.grab_set()
        self.root.wait_window(dialog)
        return result["confirmed"]

    def _on_bulk_delete(self) -> None:
        if self._inventory_list_view is None:
            return
        ids = self._inventory_list_view.get_selected_component_ids()
        if not ids:
            return
        by_id = {c.id: c for c in self.service.get_components()}
        owners = self._bulk_owner_by_component()
        protected_lines: list[str] = []
        deletable = 0
        for cid in ids:
            comp = by_id.get(cid)
            owner = owners.get(cid)
            if comp is None:
                continue
            maker = str(getattr(comp, "manufacturer", "") or "").strip()
            model = str(getattr(comp, "model", "") or "").strip()
            name = " ".join(p for p in (maker, model) if p) or cid
            if owner is not None:
                protected_lines.append(self.translator.t("bulk.delete_protected_line").format(name=name, build=owner))
            else:
                deletable += 1
        # Service re-validates everything at execution time; preview never substitutes it.
        if not self._confirm_bulk_delete(len(ids), deletable, protected_lines):
            return
        try:
            result = self.service.delete_components(ids)
        except StorageError:
            messagebox.showerror(
                self.translator.t("bulk.error_title"),
                self.translator.t("bulk.error"),
                parent=self.root,
            )
            return
        self.refresh_inventory()
        if self._inventory_list_view is not None:
            self._inventory_list_view.clear_selection()
        self._show_inventory_list()
        self._refresh_compare_if_visible()
        del_lines = self._bulk_delete_result_lines(result)
        self._show_bulk_result(
            self.translator.t("bulk.result_title"),
            del_lines[0],
            del_lines,
            self.translator.t("bulk.close"),
        )

    def _on_export_build_sheet(self, build_id: str) -> None:
        from pc_parts_organizer.build_audit import build_audit
        from pc_parts_organizer.build_sheet import export_build_sheet, sanitize_build_sheet_filename

        build = self.service.get_build(build_id)
        if build is None:
            messagebox.showerror(
                self.translator.t("builds.not_found_title"),
                self.translator.t("builds.not_found"),
                parent=self.root,
            )
            self.refresh_builds()
            self._show_builds_list()
            return
        components_by_id = self._components_by_id()
        try:
            report = self.service.analyze_build_compatibility(build_id)
            profiles = {p.component_id: p for p in self.service.get_technical_profiles()}
            audit = build_audit(build, components_by_id, profiles, report)
        except BuildNotFoundError:
            messagebox.showerror(self.translator.t("compatibility.error_title"),
                                 self.translator.t("compatibility.not_found"), parent=self.root)
            return
        except Exception:
            messagebox.showerror(self.translator.t("build_sheet.error_title"),
                                 self.translator.t("build_sheet.error"), parent=self.root)
            return
        stem = sanitize_build_sheet_filename(getattr(build, "name", "") or "build")
        dest = filedialog.asksaveasfilename(
            parent=self.root,
            title=self.translator.t("build_sheet.dialog_title"),
            initialfile=f"{stem}.md",
            defaultextension=".md",
            filetypes=[
                (self.translator.t("build_sheet.filetype_md"), "*.md"),
                (self.translator.t("build_sheet.filetype_txt"), "*.txt"),
            ],
        )
        if not dest:
            return
        flavor = "text" if str(dest).lower().endswith(".txt") else "markdown"
        # shortcut: keep extension and content consistent (dialog filter only
        # suggests .md/.txt; a foreign suffix is replaced, never mismatched).
        suffix = Path(dest).suffix.lower()
        if suffix not in (".md", ".markdown", ".txt"):
            dest = str(Path(dest).with_suffix(".txt" if flavor == "text" else ".md"))
        # shortcut: refuse the active inventory path up front so a render
        # ValueError can never be misreported as an overwrite refusal.
        try:
            if Path(dest).resolve(strict=False) == get_components_file_path().resolve(strict=False):
                raise ValueError("refusing to export over the active inventory file")
        except ValueError:
            messagebox.showerror(self.translator.t("build_sheet.error_title"),
                                 self.translator.t("build_sheet.active_file_error"), parent=self.root)
            return
        except OSError:
            pass
        try:
            info = export_build_sheet(
                build, components_by_id, report, audit, self.translator, dest,
                flavor=flavor, active_inventory_path=get_components_file_path())
        except ValueError:
            messagebox.showerror(self.translator.t("build_sheet.error_title"),
                                 self.translator.t("build_sheet.active_file_error"), parent=self.root)
            return
        except Exception:
            messagebox.showerror(self.translator.t("build_sheet.error_title"),
                                 self.translator.t("build_sheet.error"), parent=self.root)
            return
        messagebox.showinfo(
            self.translator.t("build_sheet.success_title"),
            self.translator.t("build_sheet.success").format(path=str(info)),
            parent=self.root,
        )

    def _edit_component_by_id(self, component_id: str) -> bool:
        component = self.service.get_component(component_id)
        if component is None:
            messagebox.showerror(
                self.translator.t("messages.component_not_found_title"),
                self.translator.t("messages.component_not_found"),
                parent=self.root,
            )
            self.refresh_inventory()
            self._show_inventory_list()
            return False
        form = ComponentForm(self.root, self.translator, self.catalog_service, component=component)
        self.root.wait_window(form.window)
        result = form.result
        if result is None:
            return False
        try:
            self.service.update_component(
                component_id,
                category=result.category,
                manufacturer=result.manufacturer,
                model=result.model,
                specifications=result.specifications,
                notes=result.notes,
                status=result.status,
                location=result.location,
                purchase_date=result.purchase_date,
                warranty_end_date=result.warranty_end_date,
                purchase_price=result.purchase_price,
                purchase_currency=result.purchase_currency,
            )
        except ComponentValidationError:
            messagebox.showerror(
                self.translator.t("messages.validation_title"),
                self.translator.t("messages.validation_error"),
                parent=self.root,
            )
            return False
        except ComponentNotFoundError:
            messagebox.showerror(
                self.translator.t("messages.component_not_found_title"),
                self.translator.t("messages.component_not_found"),
                parent=self.root,
            )
            self.refresh_inventory()
            self._show_inventory_list()
            return False
        except StorageError:
            messagebox.showerror(
                self.translator.t("messages.save_error_title"),
                self.translator.t("messages.save_error"),
                parent=self.root,
            )
            return False
        self.refresh_inventory()
        self._refresh_compare_if_visible()
        return True

    def _on_edit_component(self) -> None:
        component_id = self.get_selected_component_id()
        if not component_id:
            return
        self._edit_component_by_id(component_id)

    def _on_edit_detail_by_id(self, component_id: str) -> bool:
        component_id = self._detail_component_id or component_id
        if self._edit_component_by_id(component_id):
            if self._detail_component_id == component_id and self.inventory_detail_view is not None and self.inventory_detail_view.winfo_ismapped():
                self._show_inventory_detail(component_id)
            return True
        return False

    def _on_edit_detail(self) -> None:
        if not self._detail_component_id:
            return
        self._on_edit_detail_by_id(self._detail_component_id)

    def _on_delete_component_by_id_callback(self, component_id: str) -> bool:
        return self._delete_component_by_id(component_id, from_detail=False)

    # Compatibility seams for refactored inventory list view
    @property
    def tree(self):
        return None if self._inventory_list_view is None else self._inventory_list_view.tree

    @property
    def add_button(self):
        return None if self._inventory_list_view is None else self._inventory_list_view.add_button

    @property
    def edit_button(self):
        return None if self._inventory_list_view is None else self._inventory_list_view.edit_button

    @property
    def delete_button(self):
        return None if self._inventory_list_view is None else self._inventory_list_view.delete_button

    @property
    def view_details_button(self):
        return None if self._inventory_list_view is None else self._inventory_list_view.view_details_button

    @property
    def manage_catalog_button(self):
        return None if self._inventory_list_view is None else self._inventory_list_view.manage_catalog_button

    @property
    def inventory_title_label(self):
        return None if self._inventory_list_view is None else self._inventory_list_view.inventory_title_label

    @property
    def table_frame(self):
        return None if self._inventory_list_view is None else self._inventory_list_view.table_frame

    @property
    def _component_ids_by_item(self):
        return {} if self._inventory_list_view is None else self._inventory_list_view._component_ids_by_item

    def get_selected_component_id(self) -> str | None:
        if self._inventory_list_view is None:
            return None
        return self._inventory_list_view.get_selected_component_id()

    # Compatibility seams for refactored detail view
    @property
    def detail_title_label(self):
        return None if self.inventory_detail_view is None else self.inventory_detail_view.detail_title_label

    @property
    def detail_back_button(self):
        return None if self.inventory_detail_view is None else self.inventory_detail_view.detail_back_button

    @property
    def detail_edit_button(self):
        return None if self.inventory_detail_view is None else self.inventory_detail_view.detail_edit_button

    @property
    def detail_delete_button(self):
        return None if self.inventory_detail_view is None else self.inventory_detail_view.detail_delete_button

    @property
    def _detail_fields(self):
        return {} if self.inventory_detail_view is None else self.inventory_detail_view._detail_fields

    def _select_notebook_tab(self, tab_id: str) -> None:
        if self.notebook is None:
            return
        self.notebook.select(self._tab_index_by_id[tab_id])

    def _show_catalog_tab(self) -> None:
        self._select_notebook_tab(NAV_CATALOG)
        self._ensure_catalog_view()

    def _on_tab_changed(self, _event: object = None) -> None:
        if self.notebook is None:
            return
        selected = self.notebook.select()
        if selected == str(self.catalog_frame):
            self._ensure_catalog_view()
        elif selected == str(self.builds_frame):
            self.refresh_builds()

    def _ensure_catalog_view(self) -> None:
        if self._catalog_view is not None:
            return
        if self.catalog_frame is None:
            return
        try:
            if not self._catalog_initialized:
                self.catalog_service.initialize()
                self._catalog_initialized = True
        except CatalogStorageError:
            messagebox.showerror(
                self.translator.t("messages.catalog_error_title"),
                self.translator.t("messages.catalog_unavailable_error"),
                parent=self.root,
            )
            self._select_notebook_tab(NAV_INVENTORY)
            return
        for child in self.catalog_frame.winfo_children():
            child.destroy()
        self.catalog_frame.columnconfigure(0, weight=1)
        self.catalog_frame.rowconfigure(0, weight=1)
        self._catalog_view = CatalogManagerView(
            self.catalog_frame,
            catalog_service=self.catalog_service,
            translator=self.translator,
        )
        self._catalog_view.grid(row=0, column=0, sticky="nsew")
        self._catalog_view.refresh_results(reset_page=True)

    # --- T15/T16 backup (export / validate-preview / restore complete state) ---
    def _default_export_filename(self) -> str:
        stamp = datetime.now().strftime("%Y-%m-%d-%H%M%S")
        return f"pc-parts-organizer-inventory-{stamp}.json"

    def _on_export_inventory(self) -> None:
        dest = filedialog.asksaveasfilename(
            parent=self.root,
            title=self.translator.t("backup.export_dialog_title"),
            initialfile=self._default_export_filename(),
            defaultextension=".json",
            filetypes=[(self.translator.t("backup.json_file_type"), "*.json")],
        )
        if not dest:
            return
        try:
            state = self.service.get_project_state()
            info = export_inventory(state, dest, active_path=get_components_file_path())
        except StorageError as exc:
            msg = str(exc)
            if "active inventory file" in msg.lower():
                user_msg = self.translator.t("backup.active_file_destination_error")
            else:
                user_msg = self.translator.t("backup.export_error")
            messagebox.showerror(self.translator.t("backup.error_title"), user_msg, parent=self.root)
            return
        messagebox.showinfo(
            self.translator.t("backup.export_success_title"),
            f"{self.translator.t('backup.export_success')}\n{info.path}",
            parent=self.root,
        )

    def _backup_preview_lines(self, components: list) -> tuple[list[str], list[str]]:
        cat_counts: dict[str, int] = {}
        status_counts: dict[str, int] = {}
        for c in components:
            cat_counts[c.category] = cat_counts.get(c.category, 0) + 1
            status_counts[c.status] = status_counts.get(c.status, 0) + 1
        from pc_parts_organizer.models import CATEGORIES, COMPONENT_STATUSES
        cats = [f"{self.translator.translate_category(k)}: {cat_counts[k]}" for k in CATEGORIES if k in cat_counts]
        statuses = [f"{self.translator.translate_status(k)}: {status_counts[k]}" for k in COMPONENT_STATUSES if k in status_counts]
        if not statuses:
            statuses = [self.translator.t("backup.preview_no_statuses")]
        return cats, statuses

    def _show_restore_preview_dialog(self, info, path: Path) -> bool:
        result = {"confirmed": False}
        dialog = tk.Toplevel(self.root)
        dialog.title(self.translator.t("backup.preview_title"))
        dialog.transient(self.root)
        dialog.configure(background=PALETTE["surface"])
        dialog.resizable(True, True)
        dialog.geometry("660x620")
        dialog.minsize(560, 500)
        dialog.protocol("WM_DELETE_WINDOW", dialog.destroy)
        frame = ttk.Frame(dialog, style="Form.TFrame", padding=16)
        frame.grid(row=0, column=0, sticky="nsew")
        dialog.columnconfigure(0, weight=1)
        dialog.rowconfigure(0, weight=1)
        frame.columnconfigure(0, weight=1)
        frame.rowconfigure(10, weight=1)
        cats, statuses = self._backup_preview_lines(info.components)
        builds = list(getattr(info, "builds", []) or [])
        profiles = list(getattr(info, "technical_profiles", []) or [])
        schema_version = int(getattr(info, "schema_version", 0) or 0)
        is_legacy_builds = schema_version < 3
        is_legacy_profiles = schema_version < 4
        ttk.Label(frame, text=f"{self.translator.t('backup.preview_file')}: {path.name}", style="Form.TLabel").grid(row=0, column=0, sticky="w")
        ttk.Label(frame, text=f"{self.translator.t('backup.preview_location')}: {path}", style="Form.TLabel", wraplength=600).grid(row=1, column=0, sticky="w")
        ttk.Label(frame, text=f"{self.translator.t('backup.preview_component_count')}: {len(info.components)}", style="Form.TLabel").grid(row=2, column=0, sticky="w")
        ttk.Label(frame, text=f"{self.translator.t('backup.preview_build_count')}: {len(builds)}", style="Form.TLabel").grid(row=3, column=0, sticky="w")
        ttk.Label(frame, text=f"{self.translator.t('backup.preview_technical_profile_count')}: {len(profiles)}", style="Form.TLabel").grid(row=4, column=0, sticky="w")
        ttk.Label(frame, text=f"{self.translator.t('backup.preview_schema_version')}: {getattr(info, 'schema_version', '?')}", style="Form.TLabel").grid(row=5, column=0, sticky="w", pady=(0, 8))
        row = 6
        if len(info.components) == 0:
            ttk.Label(frame, text=self.translator.t("backup.empty_backup_warning"), style="Form.TLabel", wraplength=600).grid(row=row, column=0, sticky="w", pady=(0, 4)); row += 1
        if is_legacy_builds:
            ttk.Label(frame, text=self.translator.t("backup.preview_legacy_no_builds_warning"), style="Form.TLabel", wraplength=600).grid(row=row, column=0, sticky="w", pady=(0, 4)); row += 1
        if is_legacy_profiles:
            ttk.Label(frame, text=self.translator.t("backup.preview_legacy_no_technical_profiles_warning"), style="Form.TLabel", wraplength=600).grid(row=row, column=0, sticky="w", pady=(0, 4)); row += 1
        ttk.Label(frame, text=self.translator.t("backup.preview_replace_warning"), style="Form.TLabel", wraplength=600).grid(row=row, column=0, sticky="w", pady=(0, 8)); row += 1
        text = tk.Text(frame, height=10, wrap="word", background=PALETTE["surface"], relief="flat", highlightthickness=0)
        text.grid(row=10, column=0, sticky="nsew")
        body = f"{self.translator.t('backup.preview_categories')}:\n" + ("\n".join(f"- {x}" for x in cats) if cats else f"- {self.translator.t('backup.empty_inventory')}")
        body += f"\n\n{self.translator.t('backup.preview_statuses')}:\n" + "\n".join(f"- {x}" for x in statuses)
        body += f"\n\n{self.translator.t('backup.preview_build_count')}: {len(builds)}"
        body += f"\n{self.translator.t('backup.preview_technical_profile_count')}: {len(profiles)}"
        text.insert("1.0", body)
        text.configure(state="disabled")
        actions = ttk.Frame(frame, style="Form.TFrame")
        actions.grid(row=11, column=0, sticky="e", pady=(10, 0))
        def on_cancel(): dialog.destroy()
        def on_confirm(): result["confirmed"] = True; dialog.destroy()
        ttk.Button(actions, text=self.translator.t("backup.cancel"), style="Secondary.TButton", command=on_cancel).grid(row=0, column=0, padx=(0, 8))
        ttk.Button(actions, text=self.translator.t("backup.restore_confirm_action"), style="Primary.TButton", command=on_confirm).grid(row=0, column=1)
        dialog.grab_set()
        self.root.wait_window(dialog)
        return result["confirmed"]

    def _on_restore_inventory(self) -> None:
        selected = filedialog.askopenfilename(
            parent=self.root,
            title=self.translator.t("backup.restore_select_dialog_title"),
            filetypes=[(self.translator.t("backup.json_file_type"), "*.json")],
        )
        if not selected:
            return
        path = Path(selected)
        try:
            info = read_inventory_file(path)
        except StorageError as exc:
            messagebox.showerror(
                self.translator.t("backup.error_title"),
                self.translator.t("backup.validation_error").format(detail=str(exc)),
                parent=self.root,
            )
            return
        if not self._show_restore_preview_dialog(info, path):
            return
        try:
            # recheck file unchanged (protect preview-to-confirm)
            read_inventory_file(path, expected_sha256=info.sha256)
        except StorageError:
            messagebox.showerror(
                self.translator.t("backup.error_title"),
                self.translator.t("backup.preview_changed_error"),
                parent=self.root,
            )
            return
        try:
            # CRITICAL: pass complete state (components + builds). Never discard builds.
            result = self.service.restore_inventory(info)
        except StorageError as exc:
            low = str(exc).lower()
            if "pre-restore backup preserved at" in low:
                user_msg = self.translator.t("backup.write_error").format(path=str(exc).rsplit(" at ", 1)[-1].rstrip(")"))
            elif "pre-restore backup" in low or "backup directory" in low or "verify pre-restore" in low or "allocate a pre-restore" in low:
                user_msg = self.translator.t("backup.pre_restore_backup_error")
            else:
                user_msg = self.translator.t("backup.restore_error")
            messagebox.showerror(self.translator.t("backup.error_title"), user_msg, parent=self.root)
            return
        # refresh all views; clear stale detail/selection
        self._detail_component_id = None
        self.refresh_inventory()
        self.refresh_builds()
        if self._inventory_list_view is not None:
            self._inventory_list_view.clear_selection()
        self._show_inventory_list()
        self._update_inventory_actions()
        messagebox.showinfo(
            self.translator.t("backup.restore_success_title"),
            self.translator.t("backup.restore_success").format(
                count=result.restored_count,
                build_count=getattr(result, "restored_build_count", len(getattr(info, "builds", []) or [])),
                profile_count=getattr(result, "restored_technical_profile_count", len(getattr(info, "technical_profiles", []) or [])),
                path=result.pre_restore_backup.path,
            ),
            parent=self.root,
        )

    # --- Equipos / Builds (T16.3) ---
    def _build_builds_view(self, parent: ttk.Frame) -> None:
        parent.columnconfigure(0, weight=1)
        parent.rowconfigure(0, weight=1)
        self._builds_list_view = BuildListView(
            parent,
            self.translator,
            on_add=self._on_add_build,
            on_edit=self._edit_build_by_id,
            on_view_details=self._show_build_detail,
            on_delete=self._delete_build_by_id,
            on_compare=self._on_compare_builds,
        )
        self._builds_list_view.grid(row=0, column=0, sticky="nsew")
        self._builds_compare_view = BuildCompareView(
            parent,
            self.translator,
            on_back=self._show_builds_list,
        )
        self._builds_compare_view.grid(row=0, column=0, sticky="nsew")
        self._builds_compare_view.grid_remove()
        self._builds_detail_view = BuildDetailView(
            parent,
            self.translator,
            on_back=self._show_builds_list,
            on_edit=self._edit_build_by_id,
            on_delete=self._delete_build_by_id,
            on_view_component=self._show_component_from_build,
            on_analyze=self._analyze_build_compatibility,
            on_open_quality=self._show_quality_center,
            on_export_sheet=self._on_export_build_sheet,
        )
        self._builds_detail_view.grid(row=0, column=0, sticky="nsew")
        self._builds_detail_view.grid_remove()

    def _show_builds_list(self) -> None:
        if self._builds_compare_view is not None:
            self._builds_compare_view.grid_remove()
            self._builds_compare_view.clear()
        self._compare_build_ids = None
        if self._builds_detail_view is not None:
            self._builds_detail_view.grid_remove()
        if self._builds_list_view is not None:
            self._builds_list_view.grid()
        self._detail_build_id = None

    def _show_builds_detail_view(self) -> None:
        if self._builds_compare_view is not None:
            self._builds_compare_view.grid_remove()
        if self._builds_list_view is not None:
            self._builds_list_view.grid_remove()
        if self._builds_detail_view is not None:
            self._builds_detail_view.grid()

    def refresh_builds(self) -> None:
        if self._builds_list_view is None:
            return
        try:
            builds = self.service.get_builds()
        except Exception:
            builds = []
        self._builds_list_view.set_translator(self.translator)
        self._builds_list_view.set_builds(builds)
        if self._builds_detail_view is not None:
            self._builds_detail_view.set_translator(self.translator)
            if self._detail_build_id is not None:
                self._render_build_detail(self._detail_build_id)
        if self._builds_compare_view is not None:
            self._builds_compare_view.set_translator(self.translator)
        self._refresh_compare_if_visible()

    def _components_by_id(self) -> dict:
        return {c.id: c for c in self.service.get_components()}

    def _show_component_from_build(self, component_id: str) -> None:
        self._select_notebook_tab(NAV_INVENTORY)
        self._show_inventory_detail(component_id)

    def _analyze_build_compatibility(self, build_id: str) -> None:
        if self._builds_detail_view is None:
            return
        try:
            report = self.service.analyze_build_compatibility(build_id)
            profiles = {p.component_id: p for p in self.service.get_technical_profiles()}
            self._builds_detail_view.set_compatibility_report(report, profiles)
        except BuildNotFoundError:
            self._builds_detail_view.set_compatibility_error("compatibility.not_found")
            self.refresh_builds()
            self._show_builds_list()
            messagebox.showerror(self.translator.t("compatibility.error_title"), self.translator.t("compatibility.not_found"), parent=self.root)
        except StorageError:
            self._builds_detail_view.set_compatibility_error("compatibility.error")
            messagebox.showerror(self.translator.t("compatibility.error_title"), self.translator.t("compatibility.error"), parent=self.root)
        except Exception:
            self._builds_detail_view.set_compatibility_error("compatibility.error")
            messagebox.showerror(self.translator.t("compatibility.error_title"), self.translator.t("compatibility.error"), parent=self.root)

    def _on_add_build(self) -> None:
        form = BuildForm(
            self.root,
            self.translator,
            build=None,
            available_components=self.service.get_available_components(),
            associated_components=[],
            all_components_by_id=self._components_by_id(),
        )
        self.root.wait_window(form.window)
        if form.result is None:
            return
        try:
            build = self.service.add_build(
                form.result.name, notes=form.result.notes, kind=form.result.kind, component_ids=form.result.component_ids,
            )
        except BuildNameConflictError:
            messagebox.showerror(self.translator.t("builds.validation_title"), self.translator.t("builds.name_conflict"), parent=self.root)
            return
        except (ComponentNotFoundError, ComponentAlreadyAssignedError):
            messagebox.showerror(self.translator.t("builds.component_unavailable_title"), self.translator.t("builds.component_unavailable"), parent=self.root)
            return
        except (StorageError, ValueError) as exc:
            messagebox.showerror(self.translator.t("builds.save_error_title"), self.translator.t("builds.save_error"), parent=self.root)
            return
        self.refresh_builds()
        self._show_build_detail(build.id)

    def _edit_build_by_id(self, build_id: str) -> None:
        build = self.service.get_build(build_id)
        if build is None:
            self.refresh_builds()
            self._show_builds_list()
            messagebox.showerror(self.translator.t("builds.not_found_title"), self.translator.t("builds.not_found"), parent=self.root)
            return
        components_by_id = self._components_by_id()
        associated = [components_by_id[cid] for cid in build.component_ids if cid in components_by_id]
        form = BuildForm(
            self.root,
            self.translator,
            build=build,
            available_components=self.service.get_available_components(),
            associated_components=associated,
            all_components_by_id=components_by_id,
        )
        self.root.wait_window(form.window)
        if form.result is None:
            return
        try:
            updated = self.service.update_build(
                build_id,
                name=form.result.name,
                notes=form.result.notes,
                kind=form.result.kind,
                component_ids=form.result.component_ids,
            )
        except BuildNotFoundError:
            self.refresh_builds()
            self._show_builds_list()
            messagebox.showerror(self.translator.t("builds.not_found_title"), self.translator.t("builds.not_found"), parent=self.root)
            return
        except BuildNameConflictError:
            messagebox.showerror(self.translator.t("builds.validation_title"), self.translator.t("builds.name_conflict"), parent=self.root)
            return
        except (ComponentNotFoundError, ComponentAlreadyAssignedError):
            messagebox.showerror(self.translator.t("builds.component_unavailable_title"), self.translator.t("builds.component_unavailable"), parent=self.root)
            return
        except (StorageError, ValueError):
            messagebox.showerror(self.translator.t("builds.save_error_title"), self.translator.t("builds.save_error"), parent=self.root)
            return
        self.refresh_builds()
        self._show_build_detail(updated.id)

    def _render_build_detail(self, build_id: str) -> bool:
        build = self.service.get_build(build_id)
        if build is None or self._builds_detail_view is None:
            return False
        self._builds_detail_view.set_translator(self.translator)
        self._builds_detail_view.set_build(build, self._components_by_id())
        self._detail_build_id = build_id
        self._show_builds_detail_view()
        return True

    def _show_build_detail(self, build_id: str) -> None:
        if not self._render_build_detail(build_id):
            self.refresh_builds()
            self._show_builds_list()
            messagebox.showerror(self.translator.t("builds.not_found_title"), self.translator.t("builds.not_found"), parent=self.root)

    def _show_build_compare_view(self) -> None:
        if self._builds_list_view is not None:
            self._builds_list_view.grid_remove()
        if self._builds_detail_view is not None:
            self._builds_detail_view.grid_remove()
        if self._builds_compare_view is not None:
            self._builds_compare_view.grid()

    def _on_compare_builds(self) -> None:
        try:
            builds = self.service.get_builds()
        except Exception:
            builds = []
        if len(builds) < 2:
            messagebox.showinfo(self.translator.t("build_compare.title"),
                                self.translator.t("build_compare.need_two_builds"), parent=self.root)
            return
        ordered = sorted(builds, key=lambda b: str(getattr(b, "name", "")).casefold())
        names = [getattr(b, "name", b.id) for b in ordered]
        by_name = {n: b.id for n, b in zip(names, ordered)}
        dialog = tk.Toplevel(self.root)
        dialog.title(self.translator.t("build_compare.select_title"))
        dialog.transient(self.root)
        dialog.configure(background=PALETTE["surface"])
        dialog.resizable(False, False)
        dialog.geometry("480x240")
        frame = ttk.Frame(dialog, style="Form.TFrame", padding=20)
        frame.grid(row=0, column=0, sticky="nsew")
        frame.columnconfigure(1, weight=1)
        ttk.Label(frame, text=self.translator.t("build_compare.select_a"), style="Form.TLabel").grid(row=0, column=0, sticky="w", pady=(0, 8))
        var_a = tk.StringVar(value=names[0])
        ttk.Combobox(frame, textvariable=var_a, values=names, state="readonly", width=32).grid(row=0, column=1, sticky="ew", pady=(0, 8))
        ttk.Label(frame, text=self.translator.t("build_compare.select_b"), style="Form.TLabel").grid(row=1, column=0, sticky="w", pady=(0, 8))
        var_b = tk.StringVar(value=names[1] if len(names) > 1 else names[0])
        ttk.Combobox(frame, textvariable=var_b, values=names, state="readonly", width=32).grid(row=1, column=1, sticky="ew", pady=(0, 8))
        err = ttk.Label(frame, text="", style="Form.TLabel")
        err.grid(row=2, column=0, columnspan=2, sticky="w", pady=(0, 8))
        chosen: dict[str, str | None] = {"a": None, "b": None}

        def on_ok() -> None:
            ida, idb = by_name.get(var_a.get()), by_name.get(var_b.get())
            if not ida or not idb or ida == idb:
                err.configure(text=self.translator.t("build_compare.same_build_selected"))
                return
            chosen["a"], chosen["b"] = ida, idb
            dialog.destroy()

        def on_cancel() -> None:
            dialog.destroy()

        actions = ttk.Frame(frame, style="Form.TFrame")
        actions.grid(row=3, column=0, columnspan=2, sticky="e")
        ttk.Button(actions, text=self.translator.t("build_compare.back"), style="Secondary.TButton", command=on_cancel).grid(row=0, column=0, padx=(0, 8))
        ttk.Button(actions, text=self.translator.t("build_compare.compare_action"), style="Primary.TButton", command=on_ok).grid(row=0, column=1)
        dialog.protocol("WM_DELETE_WINDOW", on_cancel)
        dialog.bind("<Escape>", lambda _e: on_cancel())
        self.root.wait_window(dialog)
        if chosen["a"] and chosen["b"]:
            self._show_build_compare(chosen["a"], chosen["b"])

    def _show_build_compare(self, build_a_id: str, build_b_id: str) -> None:
        if self._builds_compare_view is None:
            return
        try:
            from pc_parts_organizer.build_compare import compare_hardware, compare_reports
            build_a = self.service.get_build(build_a_id)
            build_b = self.service.get_build(build_b_id)
            if build_a is None or build_b is None:
                self.refresh_builds()
                self._show_builds_list()
                messagebox.showerror(self.translator.t("builds.not_found_title"),
                                     self.translator.t("build_compare.missing_build"), parent=self.root)
                return
            components = {c.id: c for c in self.service.get_components()}
            profiles = {p.component_id: p for p in self.service.get_technical_profiles()}
            hardware = compare_hardware(build_a, build_b, components, profiles)
            from pc_parts_organizer.build_compare import correspondence_from_hardware
            corr = correspondence_from_hardware(hardware)
            report_a = self.service.analyze_build_compatibility(build_a.id)
            report_b = self.service.analyze_build_compatibility(build_b.id)
            compat = compare_reports(report_a, report_b, corr)
        except (BuildNotFoundError, StorageError):
            self.refresh_builds()
            self._show_builds_list()
            messagebox.showerror(self.translator.t("builds.not_found_title"),
                                 self.translator.t("build_compare.missing_build"), parent=self.root)
            return
        self._compare_build_ids = (build_a_id, build_b_id)
        self._builds_compare_view.set_comparison({
            "build_a": build_a, "build_b": build_b, "hardware": hardware,
            "report_a": report_a, "report_b": report_b, "compat": compat,
            "components_by_id": components,
        })
        self._show_build_compare_view()

    def _refresh_compare_if_visible(self) -> None:
        if self._compare_build_ids is None or self._builds_compare_view is None:
            return
        try:
            managed = bool(self._builds_compare_view.grid_info())
        except Exception:
            managed = False
        try:
            on_builds_tab = (self.notebook is not None
                             and self.notebook.index("current") == self._tab_index_by_id.get(NAV_BUILDS))
        except Exception:
            on_builds_tab = False
        if not (managed and on_builds_tab):
            return
        aid, bid = self._compare_build_ids
        if self.service.get_build(aid) is None or self.service.get_build(bid) is None:
            self._show_builds_list()
            return
        self._compare_build_ids = None  # avoid recursion via refresh paths
        self._show_build_compare(aid, bid)

    def _confirm_delete_build(self, build: Any) -> bool:
        dialog = tk.Toplevel(self.root)
        dialog.title(self.translator.t("builds.delete_title"))
        dialog.transient(self.root)
        dialog.configure(background=PALETTE["surface"])
        dialog.resizable(False, False)
        dialog.geometry("520x220")
        dialog.minsize(480, 200)
        result = {"confirmed": False}

        def on_cancel() -> None:
            result["confirmed"] = False
            dialog.destroy()

        def on_confirm() -> None:
            result["confirmed"] = True
            dialog.destroy()

        dialog.protocol("WM_DELETE_WINDOW", on_cancel)
        dialog.bind("<Escape>", lambda _e: on_cancel())
        frame = ttk.Frame(dialog, style="Form.TFrame", padding=20)
        frame.grid(row=0, column=0, sticky="nsew")
        dialog.columnconfigure(0, weight=1)
        dialog.rowconfigure(0, weight=1)
        frame.columnconfigure(0, weight=1)
        name = getattr(build, "name", "")
        ttk.Label(frame, text=f"{name}", style="Form.TLabel", wraplength=460).grid(row=0, column=0, sticky="w", pady=(0, 8))
        ttk.Label(frame, text=self.translator.t("builds.delete_confirm"), style="Form.TLabel", wraplength=460).grid(row=1, column=0, sticky="w", pady=(0, 14))
        actions = ttk.Frame(frame, style="Form.TFrame")
        actions.grid(row=2, column=0, sticky="e")
        cancel_btn = ttk.Button(actions, text=self.translator.t("builds.delete_cancel_button"), style="Secondary.TButton", command=on_cancel)
        cancel_btn.grid(row=0, column=0, padx=(0, 8))
        ttk.Button(actions, text=self.translator.t("builds.delete_confirm_button"), style="Primary.TButton", command=on_confirm).grid(row=0, column=1)
        dialog.grab_set()
        cancel_btn.focus_set()
        self.root.wait_window(dialog)
        return bool(result["confirmed"])

    def _delete_build_by_id(self, build_id: str) -> bool:
        build = self.service.get_build(build_id)
        if build is None:
            self.refresh_builds()
            self._show_builds_list()
            messagebox.showerror(self.translator.t("builds.not_found_title"), self.translator.t("builds.not_found"), parent=self.root)
            return False
        if not self._confirm_delete_build(build):
            return False
        try:
            self.service.delete_build(build_id)
        except BuildNotFoundError:
            self.refresh_builds()
            self._show_builds_list()
            messagebox.showerror(self.translator.t("builds.not_found_title"), self.translator.t("builds.not_found"), parent=self.root)
            return False
        except StorageError:
            messagebox.showerror(self.translator.t("builds.delete_error_title"), self.translator.t("builds.delete_error"), parent=self.root)
            return False
        self.refresh_builds()
        self._show_builds_list()
        if self._builds_list_view is not None:
            self._builds_list_view.clear_selection()
        return True


    def _on_add_technical_profile(self, component_id: str) -> None:
        component = self.service.get_component(component_id)
        if component is None:
            return
        if getattr(component, "category", "") not in ATTRIBUTE_REGISTRY:
            messagebox.showinfo(self.translator.t("technical_profile.section_title"), self.translator.t("technical_profile.unsupported"), parent=self.root)
            return
        form = TechnicalProfileForm(self.root, self.translator, component_id=component.id, category=component.category, profile=None)
        self.root.wait_window(form.window)
        if form.result is None:
            return
        try:
            self.service.set_technical_profile(form.result)
        except TechnicalProfileCategoryConflictError:
            messagebox.showerror(self.translator.t("technical_profile.errors.validation_title"), self.translator.t("technical_profile.errors.category_conflict"), parent=self.root)
            return
        except (TechnicalProfileValidationError, ComponentValidationError) as exc:
            messagebox.showerror(self.translator.t("technical_profile.errors.validation_title"), str(exc), parent=self.root)
            return
        except StorageError:
            messagebox.showerror(self.translator.t("technical_profile.errors.save_error_title"), self.translator.t("technical_profile.errors.save_error"), parent=self.root)
            return
        if self._detail_component_id == component_id:
            self._show_inventory_detail(component_id)
        self._refresh_quality_if_visible()
        self._refresh_compare_if_visible()

    def _on_edit_technical_profile(self, component_id: str) -> None:
        component = self.service.get_component(component_id)
        if component is None:
            return
        if getattr(component, "category", "") not in ATTRIBUTE_REGISTRY:
            messagebox.showinfo(self.translator.t("technical_profile.section_title"), self.translator.t("technical_profile.unsupported"), parent=self.root)
            return
        profile = self.service.get_technical_profile(component_id)
        if profile is None:
            self._on_add_technical_profile(component_id)
            return
        form = TechnicalProfileForm(self.root, self.translator, component_id=component.id, category=component.category, profile=profile)
        self.root.wait_window(form.window)
        if form.result is None:
            return
        try:
            self.service.set_technical_profile(form.result)
        except TechnicalProfileCategoryConflictError:
            messagebox.showerror(self.translator.t("technical_profile.errors.validation_title"), self.translator.t("technical_profile.errors.category_conflict"), parent=self.root)
            return
        except (TechnicalProfileValidationError, ComponentValidationError) as exc:
            messagebox.showerror(self.translator.t("technical_profile.errors.validation_title"), str(exc), parent=self.root)
            return
        except StorageError:
            messagebox.showerror(self.translator.t("technical_profile.errors.save_error_title"), self.translator.t("technical_profile.errors.save_error"), parent=self.root)
            return
        if self._detail_component_id == component_id:
            self._show_inventory_detail(component_id)
        self._refresh_quality_if_visible()
        self._refresh_compare_if_visible()

    def _on_delete_technical_profile(self, component_id: str) -> None:
        profile = self.service.get_technical_profile(component_id)
        if profile is None:
            return
        if not messagebox.askyesno(self.translator.t("technical_profile.delete_confirm_title"), self.translator.t("technical_profile.delete_confirm"), parent=self.root):
            return
        try:
            self.service.delete_technical_profile(component_id)
        except (ComponentNotFoundError, StorageError):
            messagebox.showerror(self.translator.t("technical_profile.errors.delete_error_title"), self.translator.t("technical_profile.errors.delete_error"), parent=self.root)
            return
        if self._detail_component_id == component_id:
            self._show_inventory_detail(component_id)
        self._refresh_quality_if_visible()
        self._refresh_compare_if_visible()
