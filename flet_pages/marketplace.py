from __future__ import annotations

import threading
from typing import TYPE_CHECKING

import flet as ft

from .models import MarketplaceItem

if TYPE_CHECKING:
    from .app import AurexFletApp


_IMAGE_HEIGHT = 180


def build_marketplace_view(app: "AurexFletApp") -> ft.View:
    page = app.page

    if not app.session.market_items and not app.market_loading and not app._market_bootstrap_requested:
        app.market_loading = True
        app._market_bootstrap_requested = True
        threading.Thread(
            target=app._load_marketplace_worker,
            args=(True,),
            daemon=True,
        ).start()

    def build_item_card(item: MarketplaceItem) -> ft.Control:
        cached = app.session.image_cache.get(item.image_url)
        if not cached and item.image_url:
            app.prefetch_image_async(item.image_url)

        image_control: ft.Control
        if cached:
            image_control = ft.Image(
                src_base64=cached,
                height=_IMAGE_HEIGHT,
                fit=ft.ImageFit.COVER,
                border_radius=ft.border_radius.only(top_left=18, top_right=18),
            )
        else:
            image_control = ft.Container(
                height=_IMAGE_HEIGHT,
                bgcolor="#cbd5e1",
                alignment=ft.alignment.center,
                border_radius=ft.border_radius.only(top_left=18, top_right=18),
                content=ft.Icon(ft.Icons.IMAGE, size=44, color="#64748b"),
            )

        return ft.Container(
            width=260,
            border_radius=18,
            bgcolor="#111827",
            border=ft.border.all(1, "#1f2937"),
            content=ft.Column(
                spacing=0,
                controls=[
                    image_control,
                    ft.Container(
                        padding=16,
                        content=ft.Column(
                            spacing=8,
                            controls=[
                                ft.Text(item.title, size=16, weight=ft.FontWeight.BOLD, max_lines=2),
                                ft.Text(
                                    item.description,
                                    size=12,
                                    color="#94a3b8",
                                    max_lines=2,
                                    overflow=ft.TextOverflow.ELLIPSIS,
                                ),
                                ft.Row(
                                    alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
                                    controls=[
                                        ft.Text(
                                            f"${item.price:.2f}",
                                            color="#22c55e",
                                            weight=ft.FontWeight.BOLD,
                                        ),
                                        ft.Container(
                                            padding=ft.padding.symmetric(horizontal=10, vertical=4),
                                            bgcolor="#1d4ed8",
                                            border_radius=999,
                                            content=ft.Text("View", size=11, color="white"),
                                        ),
                                    ],
                                ),
                                ft.Text(f"by {item.author}", size=11, color="#64748b"),
                            ],
                        ),
                    ),
                ],
            ),
        )

    item_controls: list[ft.Control]
    if app.market_error and not app.session.market_items:
        item_controls = [
            ft.Container(
                padding=24,
                border_radius=18,
                bgcolor="#111827",
                content=ft.Column(
                    horizontal_alignment=ft.CrossAxisAlignment.CENTER,
                    controls=[
                        ft.Icon(ft.Icons.ERROR_OUTLINE, size=48, color="#ef4444"),
                        ft.Text(app.market_error, text_align=ft.TextAlign.CENTER),
                        ft.ElevatedButton(
                            text="Retry",
                            on_click=lambda _: app.load_marketplace_async(reset=True),
                        ),
                    ],
                ),
            )
        ]
    elif not app.session.market_items and app.market_loading:
        item_controls = [
            ft.Container(
                padding=24,
                content=ft.Column(
                    horizontal_alignment=ft.CrossAxisAlignment.CENTER,
                    controls=[
                        ft.ProgressRing(),
                        ft.Text("Loading marketplace items..."),
                    ],
                ),
            )
        ]
    elif not app.session.market_items:
        item_controls = [
            ft.Container(
                padding=24,
                border_radius=18,
                bgcolor="#111827",
                content=ft.Column(
                    horizontal_alignment=ft.CrossAxisAlignment.CENTER,
                    controls=[
                        ft.Icon(ft.Icons.INVENTORY_2_OUTLINED, size=48, color="#94a3b8"),
                        ft.Text("No assets available"),
                        ft.ElevatedButton(
                            text="Refresh",
                            on_click=lambda _: app.load_marketplace_async(reset=True),
                        ),
                    ],
                ),
            )
        ]
    else:
        item_controls = [build_item_card(item) for item in app.session.market_items]

    username = app.session.user_data.username if app.session.user_data else "Guest"

    return ft.View(
        route="/marketplace",
        bgcolor="#0f172a",
        controls=[
            ft.Container(
                expand=True,
                padding=24,
                content=ft.Column(
                    expand=True,
                    spacing=18,
                    controls=[
                        ft.Row(
                            alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
                            vertical_alignment=ft.CrossAxisAlignment.CENTER,
                            controls=[
                                ft.Column(
                                    spacing=4,
                                    controls=[
                                        ft.Text("Aurex Marketplace", size=28, weight=ft.FontWeight.BOLD),
                                        ft.Text(f"Welcome, {username}", color="#94a3b8"),
                                    ],
                                ),
                                ft.Row(
                                    controls=[
                                        ft.OutlinedButton(
                                            text="Refresh",
                                            icon=ft.Icons.REFRESH,
                                            on_click=lambda _: app.load_marketplace_async(reset=True),
                                        ),
                                        ft.OutlinedButton(
                                            text="Load more",
                                            icon=ft.Icons.EXPAND_MORE,
                                            on_click=lambda _: app.load_marketplace_async(reset=False),
                                            disabled=app.market_loading or not bool(app.session.last_market_cursor),
                                        ),
                                        ft.FilledButton(
                                            text="Logout",
                                            icon=ft.Icons.LOGOUT,
                                            on_click=lambda _: app.logout(),
                                        ),
                                    ]
                                ),
                            ],
                        ),
                        ft.Container(
                            padding=16,
                            border_radius=18,
                            bgcolor="#111827",
                            content=ft.Row(
                                alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
                                controls=[
                                    ft.Text(
                                        "Discover newly uploaded blockchain-backed assets.",
                                        color="#cbd5e1",
                                    ),
                                    ft.Row(
                                        controls=[
                                            ft.Text(
                                                "Loading..." if app.market_loading else f"{len(app.session.market_items)} items",
                                                color="#93c5fd",
                                            ),
                                            ft.ProgressRing(width=16, height=16, stroke_width=2, visible=app.market_loading),
                                        ]
                                    ),
                                ],
                            ),
                        ),
                        ft.GridView(
                            expand=True,
                            max_extent=320,
                            child_aspect_ratio=0.68,
                            spacing=16,
                            run_spacing=16,
                            controls=item_controls,
                        ),
                    ],
                ),
            )
        ],
    )
