"""Application startup."""

from __future__ import annotations

import tkinter as tk

from pc_parts_organizer.catalog_service import CatalogService
from pc_parts_organizer.catalog_storage import CatalogStorage
from pc_parts_organizer.localization import Translator
from pc_parts_organizer.service import InventoryService
from pc_parts_organizer.ui.main_window import MainWindow
from pc_parts_organizer.ui.theme import configure_theme


def run() -> None:
    """Start the PC Parts Organizer desktop application."""
    service = InventoryService()
    catalog_storage = CatalogStorage()
    catalog_service = CatalogService(catalog_storage)
    translator = Translator()
    root = tk.Tk()
    configure_theme(root)
    MainWindow(root, service, catalog_service, translator)
    root.mainloop()
