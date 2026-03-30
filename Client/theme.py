from __future__ import annotations

import flet as ft


AUREX_GOLD = "#FFD700"
AUREX_GOLD_SOFT = "#F5C542"
AUREX_BG = "#1A1A1B"
AUREX_SURFACE = "#121318"
AUREX_CARD = "#16181F"
AUREX_SLATE = "#2B2F36"
AUREX_MUTED = "#9CA3AF"
AUREX_TEXT = "#E5E7EB"
AUREX_ERROR = "#EF4444"
AUREX_SUCCESS = "#22C55E"


def build_aurex_theme() -> ft.Theme:
    return ft.Theme(
        color_scheme=ft.ColorScheme(
            primary=AUREX_GOLD,
            on_primary="#1A1A1B",
            secondary=AUREX_GOLD_SOFT,
#            background=AUREX_BG,
            surface=AUREX_SURFACE,
            on_surface=AUREX_TEXT,
            outline=AUREX_SLATE,
            error=AUREX_ERROR,
            on_error="#111111",
        ),
        scaffold_bgcolor=AUREX_BG,
        card_bgcolor=AUREX_CARD,
        divider_color=AUREX_SLATE,
        text_theme=ft.TextTheme(
            headline_large=ft.TextStyle(
                size=32,
                weight=ft.FontWeight.BOLD,
                color=AUREX_TEXT,
                font_family="Georgia",
            ),
            headline_medium=ft.TextStyle(
                size=24,
                weight=ft.FontWeight.BOLD,
                color=AUREX_TEXT,
                font_family="Georgia",
            ),
            title_medium=ft.TextStyle(
                size=16,
                weight=ft.FontWeight.W_600,
                color=AUREX_TEXT,
                font_family="Georgia",
            ),
            body_medium=ft.TextStyle(
                size=14,
                color=AUREX_TEXT,
                font_family="Georgia",
            ),
            label_medium=ft.TextStyle(
                size=12,
                color=AUREX_TEXT,
                font_family="Georgia",
            ),
        ),
        progress_indicator_theme=ft.ProgressIndicatorTheme(color=AUREX_GOLD),
        scrollbar_theme=ft.ScrollbarTheme(
            thumb_visibility=True,
            radius=8,
            thickness=6,
            thumb_color={ft.ControlState.DEFAULT: "#3A3F48"},
            track_color={ft.ControlState.DEFAULT: "#1D1F24"},
        ),
    )
