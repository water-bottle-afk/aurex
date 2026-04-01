from __future__ import annotations

from typing import TYPE_CHECKING

import flet as ft

from .theme import (
    AUREX_BG,
    AUREX_CARD,
    AUREX_GOLD,
    AUREX_GOLD_SOFT,
    AUREX_MUTED,
    AUREX_SLATE,
    AUREX_TEXT,
)

if TYPE_CHECKING:
    from .app import AurexFletApp

# In-process notification store (survives route changes in same session)
_NOTIFICATIONS: list[dict] = []


def push_notification(title: str, body: str, notif_type: str = "info") -> None:
    """Add a notification to the in-process store. Called from anywhere."""
    import time
    _NOTIFICATIONS.append({
        "title": title,
        "body": body,
        "type": notif_type,
        "time": time.time(),
        "read": False,
    })


def unread_count() -> int:
    return sum(1 for n in _NOTIFICATIONS if not n.get("read"))


def _icon_for_type(notif_type: str):
    return {
        "blockchain": ft.Icons.CURRENCY_BITCOIN,
        "mint":       ft.Icons.VERIFIED_OUTLINED,
        "transfer":   ft.Icons.SWAP_HORIZ,
        "purchase":   ft.Icons.SHOPPING_CART_CHECKOUT,
        "error":      ft.Icons.ERROR_OUTLINE,
        "success":    ft.Icons.CHECK_CIRCLE_OUTLINE,
    }.get(notif_type, ft.Icons.NOTIFICATIONS_OUTLINED)


def _color_for_type(notif_type: str) -> str:
    return {
        "blockchain": AUREX_GOLD,
        "mint":       "#22C55E",
        "transfer":   "#60A5FA",
        "purchase":   "#A78BFA",
        "error":      "#EF4444",
        "success":    "#22C55E",
    }.get(notif_type, AUREX_GOLD_SOFT)


def _time_label(ts: float) -> str:
    import time
    diff = time.time() - ts
    if diff < 60:
        return "just now"
    if diff < 3600:
        return f"{int(diff // 60)}m ago"
    if diff < 86400:
        return f"{int(diff // 3600)}h ago"
    return f"{int(diff // 86400)}d ago"


def build_notifications_view(app: "AurexFletApp") -> ft.View:
    page = app.page

    # Mark all as read when opening
    for n in _NOTIFICATIONS:
        n["read"] = True

    def _clear_all(_: ft.ControlEvent) -> None:
        _NOTIFICATIONS.clear()
        page.run_task(page.push_route, "/notifications")

    def _build_card(n: dict) -> ft.Container:
        ntype = n.get("type", "info")
        color = _color_for_type(ntype)
        icon = _icon_for_type(ntype)
        return ft.Container(
            padding=ft.padding.symmetric(horizontal=20, vertical=14),
            border_radius=16,
            bgcolor=AUREX_CARD,
            border=ft.border.all(1, AUREX_SLATE),
            content=ft.Row(
                spacing=16,
                vertical_alignment=ft.CrossAxisAlignment.START,
                controls=[
                    ft.Container(
                        width=40, height=40,
                        border_radius=20,
                        bgcolor=f"{color}22",
                        alignment=ft.Alignment(0, 0),
                        content=ft.Icon(icon, color=color, size=20),
                    ),
                    ft.Column(
                        expand=True,
                        spacing=4,
                        controls=[
                            ft.Row(
                                alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
                                controls=[
                                    ft.Text(
                                        n.get("title", ""),
                                        size=14,
                                        weight=ft.FontWeight.W_600,
                                        color=AUREX_TEXT,
                                    ),
                                    ft.Text(
                                        _time_label(n.get("time", 0)),
                                        size=11,
                                        color=AUREX_MUTED,
                                    ),
                                ],
                            ),
                            ft.Text(
                                n.get("body", ""),
                                size=13,
                                color=AUREX_MUTED,
                            ),
                        ],
                    ),
                ],
            ),
        )

    if _NOTIFICATIONS:
        items = list(reversed(_NOTIFICATIONS))  # newest first
        content = ft.Column(
            spacing=10,
            controls=[_build_card(n) for n in items],
        )
    else:
        content = ft.Container(
            padding=60,
            alignment=ft.Alignment(0, 0),
            content=ft.Column(
                horizontal_alignment=ft.CrossAxisAlignment.CENTER,
                spacing=14,
                controls=[
                    ft.Container(
                        width=72, height=72,
                        border_radius=36,
                        bgcolor=AUREX_CARD,
                        alignment=ft.Alignment(0, 0),
                        content=ft.Icon(
                            ft.Icons.NOTIFICATIONS_NONE_OUTLINED,
                            size=36, color=AUREX_MUTED,
                        ),
                    ),
                    ft.Text("No notifications yet", size=16, color=AUREX_MUTED),
                    ft.Text(
                        "Blockchain confirmations, uploads and\ntransaction updates will appear here.",
                        size=12,
                        color=AUREX_MUTED,
                        text_align=ft.TextAlign.CENTER,
                    ),
                ],
            ),
        )

    return ft.View(
        route="/notifications",
        bgcolor=AUREX_BG,
        scroll=ft.ScrollMode.AUTO,
        controls=[
            ft.Container(
                expand=True,
                padding=ft.padding.symmetric(vertical=32, horizontal=24),
                alignment=ft.Alignment(0, -1),
                content=ft.Container(
                    width=660,
                    content=ft.Column(
                        spacing=20,
                        controls=[
                            # ── header ───────────────────────────────────────
                            ft.Row(
                                alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
                                vertical_alignment=ft.CrossAxisAlignment.CENTER,
                                controls=[
                                    ft.Row(
                                        spacing=10,
                                        vertical_alignment=ft.CrossAxisAlignment.CENTER,
                                        controls=[
                                            ft.Icon(
                                                ft.Icons.NOTIFICATIONS_OUTLINED,
                                                color=AUREX_GOLD, size=26,
                                            ),
                                            ft.Text(
                                                "Notifications",
                                                size=26,
                                                weight=ft.FontWeight.BOLD,
                                            ),
                                            ft.Container(
                                                visible=len(_NOTIFICATIONS) > 0,
                                                padding=ft.padding.symmetric(horizontal=8, vertical=2),
                                                border_radius=10,
                                                bgcolor=AUREX_GOLD,
                                                content=ft.Text(
                                                    str(len(_NOTIFICATIONS)),
                                                    size=12,
                                                    weight=ft.FontWeight.BOLD,
                                                    color="#1A1A1B",
                                                ),
                                            ),
                                        ],
                                    ),
                                    ft.Row(
                                        spacing=8,
                                        controls=[
                                            ft.TextButton(
                                                content="Clear all",
                                                icon=ft.Icons.DELETE_SWEEP_OUTLINED,
                                                visible=len(_NOTIFICATIONS) > 0,
                                                on_click=_clear_all,
                                            ),
                                            ft.IconButton(
                                                icon=ft.Icons.ARROW_BACK_IOS_NEW_ROUNDED,
                                                icon_color=AUREX_MUTED,
                                                tooltip="Back to Marketplace",
                                                on_click=lambda _: page.run_task(
                                                    page.push_route, "/marketplace"
                                                ),
                                            ),
                                        ],
                                    ),
                                ],
                            ),
                            # ── info banner ───────────────────────────────────
                            ft.Container(
                                padding=ft.padding.symmetric(horizontal=16, vertical=10),
                                border_radius=12,
                                bgcolor="#101216",
                                border=ft.border.all(1, AUREX_SLATE),
                                content=ft.Row(
                                    spacing=10,
                                    controls=[
                                        ft.Icon(ft.Icons.INFO_OUTLINE, color=AUREX_GOLD_SOFT, size=16),
                                        ft.Text(
                                            "Blockchain confirmations for uploads and purchases appear here automatically.",
                                            size=12,
                                            color=AUREX_MUTED,
                                        ),
                                    ],
                                ),
                            ),
                            # ── list ─────────────────────────────────────────
                            content,
                        ],
                    ),
                ),
            ),
        ],
    )
