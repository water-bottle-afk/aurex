from __future__ import annotations

import threading
from typing import TYPE_CHECKING

import flet as ft

from .models import MarketplaceItem
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


_IMAGE_HEIGHT = 190


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

    def _mime(url: str) -> str:
        ext = url.rsplit(".", 1)[-1].lower() if "." in url else ""
        return "image/png" if ext == "png" else "image/jpeg"

    def build_image(item: MarketplaceItem) -> ft.Control:
        cached = app.session.image_cache.get(item.image_url)
        if cached is None and item.image_url:
            app.prefetch_image_async(item.image_url)
        if cached:
            return ft.Image(
                src=f"data:{_mime(item.image_url)};base64,{cached}",
                height=_IMAGE_HEIGHT,
                fit=ft.BoxFit.COVER,
                border_radius=ft.border_radius.only(top_left=20, top_right=20),
            )
        if cached == "":
            return ft.Container(
                height=_IMAGE_HEIGHT,
                bgcolor="#0F1115",
                alignment=ft.Alignment(0, 0),
                border_radius=ft.border_radius.only(top_left=20, top_right=20),
                content=ft.Icon(ft.Icons.BROKEN_IMAGE_OUTLINED, color=AUREX_MUTED),
            )
        return ft.Shimmer(
            base_color="#1F232B",
            highlight_color="#2C313B",
            content=ft.Container(
                height=_IMAGE_HEIGHT,
                bgcolor="#1F232B",
                border_radius=ft.border_radius.only(top_left=20, top_right=20),
            ),
        )

    def show_item_detail(item: MarketplaceItem) -> None:
        cached = app.session.image_cache.get(item.image_url)
        img = ft.Image(
            src=f"data:{_mime(item.image_url)};base64,{cached}",
            height=220,
            fit=ft.BoxFit.COVER,
            border_radius=12,
        ) if cached else ft.Container(
            height=220,
            bgcolor="#0F1115",
            border_radius=12,
            alignment=ft.Alignment(0, 0),
            content=ft.Icon(ft.Icons.IMAGE_OUTLINED, size=64, color=AUREX_MUTED),
        )

        def close_dlg(_: ft.ControlEvent) -> None:
            dlg.open = False
            page.update()

        def handle_buy(_: ft.ControlEvent) -> None:
            dlg.open = False
            page.update()
            if not app.session.is_authenticated:
                app.show_message("Please log in to buy", error=True)
                return
            username = app.session.user_data.username if app.session.user_data else ""
            def worker() -> None:
                try:
                    app.client.buy_asset(
                        asset_id=str(item.id),
                        username=username,
                        amount=item.price,
                        asset_name=item.title,
                        seller=item.author,
                        asset_hash=item.asset_hash,
                    )
                    app.show_message(f"Purchase of '{item.title}' successful!")
                except Exception as exc:
                    app.show_message(f"Purchase failed: {exc}", error=True)
            threading.Thread(target=worker, daemon=True).start()

        dlg = ft.AlertDialog(
            modal=True,
            title=ft.Text(item.title, weight=ft.FontWeight.BOLD),
            content=ft.Container(
                width=380,
                content=ft.Column(
                    tight=True,
                    spacing=12,
                    controls=[
                        img,
                        ft.Text(item.description, color=AUREX_MUTED, size=13),
                        ft.Row(
                            alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
                            controls=[
                                ft.Text(f"${item.price:.2f}", color=AUREX_GOLD_SOFT, weight=ft.FontWeight.BOLD, size=18),
                                ft.Text(f"by {item.author}", color=AUREX_MUTED, size=12),
                            ],
                        ),
                    ],
                ),
            ),
            actions=[
                ft.TextButton(content="Close", on_click=close_dlg),
                ft.FilledButton(
                    content=f"Buy ${item.price:.2f}",
                    bgcolor=AUREX_GOLD,
                    color="#1A1A1B",
                    on_click=handle_buy,
                ),
            ],
        )
        page.overlay.append(dlg)
        dlg.open = True
        page.update()

    def build_item_card(item: MarketplaceItem) -> ft.Control:
        image_control = build_image(item)
        card = ft.Card(
            bgcolor=AUREX_CARD,
            elevation=2,
            shape=ft.RoundedRectangleBorder(radius=20),
            content=ft.Column(
                spacing=0,
                controls=[
                    image_control,
                    ft.Container(
                        padding=16,
                        content=ft.Column(
                            spacing=6,
                            controls=[
                                ft.Text(
                                    item.title,
                                    size=16,
                                    weight=ft.FontWeight.BOLD,
                                    max_lines=2,
                                    color=AUREX_TEXT,
                                ),
                                ft.Text(
                                    item.description,
                                    size=12,
                                    color=AUREX_MUTED,
                                    max_lines=2,
                                    overflow=ft.TextOverflow.ELLIPSIS,
                                ),
                                ft.Row(
                                    alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
                                    controls=[
                                        ft.Text(
                                            f"${item.price:.2f}",
                                            color=AUREX_GOLD_SOFT,
                                            weight=ft.FontWeight.BOLD,
                                        ),
                                        ft.Container(
                                            padding=ft.padding.symmetric(horizontal=10, vertical=4),
                                            bgcolor="#21252D",
                                            border_radius=999,
                                            on_click=lambda _, i=item: show_item_detail(i),
                                            content=ft.Text("View", size=11, color=AUREX_TEXT),
                                        ),
                                    ],
                                ),
                                ft.Text(f"by {item.author}", size=11, color=AUREX_MUTED),
                            ],
                        ),
                    ),
                ],
            ),
        )
        return ft.Container(
            col={
                ft.ResponsiveRowBreakpoint.XS: 12,
                ft.ResponsiveRowBreakpoint.MD: 6,
                ft.ResponsiveRowBreakpoint.LG: 4,
                ft.ResponsiveRowBreakpoint.XL: 3,
            },
            content=card,
        )

    if app.market_error and not app.session.market_items:
        item_controls = [
            ft.Container(
                padding=24,
                border_radius=18,
                bgcolor=AUREX_CARD,
                content=ft.Column(
                    horizontal_alignment=ft.CrossAxisAlignment.CENTER,
                    controls=[
                        ft.Icon(ft.Icons.ERROR_OUTLINE, size=48, color="#EF4444"),
                        ft.Text(app.market_error, text_align=ft.TextAlign.CENTER),
                        ft.FilledButton(
                            content="Retry",
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
                bgcolor=AUREX_CARD,
                content=ft.Column(
                    horizontal_alignment=ft.CrossAxisAlignment.CENTER,
                    controls=[
                        ft.Icon(ft.Icons.INVENTORY_2_OUTLINED, size=48, color=AUREX_MUTED),
                        ft.Text("No assets available"),
                        ft.FilledButton(
                            content="Refresh",
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
        bgcolor=AUREX_BG,
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
                                        ft.Text(f"Welcome, {username}", color=AUREX_MUTED),
                                    ],
                                ),
                                ft.Row(
                                    spacing=10,
                                    controls=[
                                        ft.OutlinedButton(
                                            content="Refresh",
                                            icon=ft.Icons.REFRESH,
                                            on_click=lambda _: app.load_marketplace_async(reset=True),
                                        ),
                                        ft.FilledButton(
                                            content="Upload",
                                            icon=ft.Icons.CLOUD_UPLOAD,
                                            bgcolor=AUREX_GOLD,
                                            color="#1A1A1B",
                                            on_click=lambda _: page.run_task(page.push_route, "/upload"),
                                        ),
                                        ft.IconButton(
                                            icon=ft.Icons.SETTINGS,
                                            on_click=lambda _: page.run_task(page.push_route, "/settings"),
                                        ),
                                        ft.FilledButton(
                                            content="Logout",
                                            icon=ft.Icons.LOGOUT,
                                            on_click=lambda _: app.logout(),
                                        ),
                                    ],
                                ),
                            ],
                        ),
                        ft.Container(
                            padding=16,
                            border_radius=18,
                            bgcolor=AUREX_CARD,
                            border=ft.border.all(1, AUREX_SLATE),
                            content=ft.Row(
                                alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
                                controls=[
                                    ft.Text(
                                        "Discover newly uploaded blockchain-backed assets.",
                                        color=AUREX_MUTED,
                                    ),
                                    ft.Row(
                                        controls=[
                                            ft.Text(
                                                "Loading..." if app.market_loading else f"{len(app.session.market_items)} items",
                                                color=AUREX_GOLD_SOFT,
                                            ),
                                            ft.ProgressRing(width=16, height=16, stroke_width=2, visible=app.market_loading),
                                        ],
                                    ),
                                ],
                            ),
                        ),
                        ft.ResponsiveRow(
                            columns=12,
                            spacing=16,
                            run_spacing=16,
                            controls=item_controls,
                        ),
                    ],
                ),
            )
        ],
    )
