"""Centralized ttk theme for PC Parts Organizer."""

from __future__ import annotations

import tkinter as tk
from tkinter import font as tkfont
from tkinter import ttk

PALETTE = {
    "primary": "#193D32",
    "primary_dark": "#112D26",
    "accent": "#789681",
    "background": "#F3F4EF",
    "surface": "#FFFFFF",
    "border": "#DCE2DA",
    "text": "#26342D",
    "text_muted": "#718077",
    "header_text": "#F3F4EF",
    "header_subtitle": "#DCE2DA",
}

HEADING_FONT_CANDIDATES = ("Bahnschrift", "Segoe UI", "Arial", "Helvetica", "sans-serif")
BODY_FONT_CANDIDATES = ("Segoe UI", "Arial", "Helvetica", "sans-serif")


def _select_font_family(root: tk.Tk, candidates: tuple[str, ...]) -> str:
    available = {name.lower() for name in tkfont.families(root)}
    for candidate in candidates:
        if candidate.lower() in available:
            return candidate
    return "TkDefaultFont"


def configure_theme(root: tk.Tk) -> None:
    """Configure a reusable ttk theme for the application."""
    style = ttk.Style(root)
    if "clam" in style.theme_names():
        style.theme_use("clam")

    heading_family = _select_font_family(root, HEADING_FONT_CANDIDATES)
    body_family = _select_font_family(root, BODY_FONT_CANDIDATES)
    root.configure(background=PALETTE["background"])
    root.option_add("*Font", (body_family, 11))

    style.configure("App.TFrame", background=PALETTE["background"])
    style.configure("Surface.TFrame", background=PALETTE["surface"])
    style.configure("Header.TFrame", background=PALETTE["primary"])
    style.configure(
        "HeaderLanguage.TLabel",
        background=PALETTE["primary"],
        foreground=PALETTE["header_subtitle"],
        font=(body_family, 10),
    )
    style.configure(
        "Header.TCombobox",
        padding=(6, 2),
        font=(body_family, 10),
    )

    style.configure(
        "Inventory.Treeview",
        background=PALETTE["surface"],
        fieldbackground=PALETTE["surface"],
        foreground=PALETTE["text"],
        bordercolor=PALETTE["border"],
        lightcolor=PALETTE["border"],
        darkcolor=PALETTE["border"],
        rowheight=30,
        font=(body_family, 11),
    )
    style.configure(
        "Inventory.Treeview.Heading",
        background=PALETTE["background"],
        foreground=PALETTE["text"],
        font=(heading_family, 11, "bold"),
        relief="flat",
    )
    style.map(
        "Inventory.Treeview",
        background=[("selected", PALETTE["primary"])],
        foreground=[("selected", PALETTE["header_text"])],
    )
    style.map(
        "Inventory.Treeview.Heading",
        background=[("active", PALETTE["border"])],
    )

    style.configure(
        "HeaderTitle.TLabel",
        background=PALETTE["primary"],
        foreground=PALETTE["header_text"],
        font=(heading_family, 20, "bold"),
    )
    style.configure(
        "HeaderSubtitle.TLabel",
        background=PALETTE["primary"],
        foreground=PALETTE["header_subtitle"],
        font=(body_family, 11),
    )
    style.configure(
        "SectionTitle.TLabel",
        background=PALETTE["background"],
        foreground=PALETTE["text"],
        font=(heading_family, 16, "bold"),
    )
    style.configure(
        "Body.TLabel",
        background=PALETTE["background"],
        foreground=PALETTE["text_muted"],
        font=(body_family, 11),
    )
    style.configure(
        "SurfaceTitle.TLabel",
        background=PALETTE["surface"],
        foreground=PALETTE["text"],
        font=(heading_family, 12, "bold"),
    )
    style.configure(
        "SurfaceBody.TLabel",
        background=PALETTE["surface"],
        foreground=PALETTE["text_muted"],
        font=(body_family, 11),
    )
    style.configure(
        "Placeholder.TLabel",
        background=PALETTE["surface"],
        foreground=PALETTE["accent"],
        font=(body_family, 11, "italic"),
    )
    style.configure("Dashboard.TFrame", background=PALETTE["background"])
    style.configure("DashboardCard.TFrame", background=PALETTE["surface"])
    style.configure(
        "DashboardTitle.TLabel",
        background=PALETTE["background"],
        foreground=PALETTE["text"],
        font=(heading_family, 13, "bold"),
    )
    style.configure(
        "DashboardLabel.TLabel",
        background=PALETTE["surface"],
        foreground=PALETTE["text_muted"],
        font=(body_family, 10),
    )
    style.configure(
        "DashboardTotal.TLabel",
        background=PALETTE["surface"],
        foreground=PALETTE["primary"],
        font=(heading_family, 28, "bold"),
    )
    style.configure(
        "DashboardCategory.TLabel",
        background=PALETTE["surface"],
        foreground=PALETTE["text"],
        font=(body_family, 10),
    )
    style.configure(
        "DashboardCount.TLabel",
        background=PALETTE["surface"],
        foreground=PALETTE["primary"],
        font=(heading_family, 11, "bold"),
    )
    style.configure(
        "DashboardEmpty.TLabel",
        background=PALETTE["surface"],
        foreground=PALETTE["text_muted"],
        font=(body_family, 10, "italic"),
    )
    style.configure(
        "Primary.TButton",
        background=PALETTE["primary"],
        foreground=PALETTE["header_text"],
        font=(body_family, 10, "bold"),
        padding=(12, 6),
        borderwidth=0,
    )
    style.map(
        "Primary.TButton",
        background=[("active", PALETTE["primary_dark"]), ("pressed", PALETTE["primary_dark"])],
        foreground=[("active", PALETTE["header_text"]), ("pressed", PALETTE["header_text"])],
    )
    style.configure(
        "Secondary.TButton",
        background=PALETTE["background"],
        foreground=PALETTE["text"],
        font=(body_family, 10),
        padding=(12, 6),
    )
    style.configure("Form.TFrame", background=PALETTE["surface"])
    style.configure(
        "Form.TLabel",
        background=PALETTE["surface"],
        foreground=PALETTE["text"],
        font=(body_family, 10),
    )
    style.configure("Form.TEntry", font=(body_family, 10), padding=4)
    style.configure("Form.TCombobox", font=(body_family, 10), padding=4)
