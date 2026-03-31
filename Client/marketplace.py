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


_CARD_WIDTH  = 220   # fixed card width
_IMAGE_HEIGHT = 180  # image area height — taller than wide for portrait feel


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
                width=_CARD_WIDTH,
                height=_IMAGE_HEIGHT,
                fit=ft.BoxFit.COVER,
                border_radius=ft.border_radius.only(top_left=14, top_right=14),
            )
        if cached == "":
            return ft.Container(
                width=_CARD_WIDTH,
                height=_IMAGE_HEIGHT,
                bgcolor="#0F1115",
                alignment=ft.Alignment(0, 0),
                border_radius=ft.border_radius.only(top_left=14, top_right=14),
                content=ft.Icon(ft.Icons.BROKEN_IMAGE_OUTLINED, color=AUREX_MUTED, size=36),
            )
        # still loading — plain placeholder (Shimmer removed; no flet.Shimmer in all versions)
        return ft.Container(
            width=_CARD_WIDTH,
            height=_IMAGE_HEIGHT,
            bgcolor="#1F232B",
            border_radius=ft.border_radius.only(top_left=14, top_right=14),
            alignment=ft.Alignment(0, 0),
            content=ft.ProgressRing(width=28, height=28, stroke_width=2, color=AUREX_GOLD),
        )

    # ── Centered modal overlay helper ────────────────────────────────────────
    def _show_modal(content: ft.Control, overlay_ref: list) -> None:
        """Wrap `content` in a dimmed backdrop and push to page.overlay."""
        def _close_bg(e: ft.ControlEvent) -> None:
            # only close when clicking the backdrop itself (not the card)
            pass

        modal = ft.Container(
            expand=True,
            bgcolor="#000000CC",
            alignment=ft.Alignment(0, 0),
            content=content,
        )
        overlay_ref.clear()
        overlay_ref.append(modal)
        page.overlay.append(modal)
        page.update()

    def _remove_modal(overlay_ref: list) -> None:
        if overlay_ref:
            try:
                page.overlay.remove(overlay_ref[0])
            except ValueError:
                pass
            overlay_ref.clear()
            page.update()

    # ── Asset detail popup ───────────────────────────────────────────────────
    def show_item_detail(item: MarketplaceItem) -> None:
        cached = app.session.image_cache.get(item.image_url)
        img: ft.Control = ft.Image(
            src=f"data:{_mime(item.image_url)};base64,{cached}",
            width=480,
            height=340,
            fit=ft.BoxFit.CONTAIN,
            border_radius=ft.border_radius.only(top_left=20, top_right=20),
        ) if cached else ft.Container(
            width=480,
            height=340,
            bgcolor="#0F1115",
            alignment=ft.Alignment(0, 0),
            border_radius=ft.border_radius.only(top_left=20, top_right=20),
            content=ft.Icon(ft.Icons.IMAGE_OUTLINED, size=80, color=AUREX_MUTED),
        )

        overlay_ref: list[ft.Control] = []

        def close_detail(_: ft.ControlEvent) -> None:
            _remove_modal(overlay_ref)

        def handle_buy(_: ft.ControlEvent) -> None:
            _remove_modal(overlay_ref)
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

        card = ft.Container(
            width=500,
            bgcolor=AUREX_CARD,
            border_radius=20,
            border=ft.border.all(1, AUREX_SLATE),
            shadow=ft.BoxShadow(spread_radius=2, blur_radius=32, color="#000000AA"),
            content=ft.Stack(
                controls=[
                    ft.Column(
                        spacing=0,
                        controls=[
                            # large image
                            img,
                            # info + buy
                            ft.Container(
                                padding=ft.padding.symmetric(horizontal=24, vertical=18),
                                content=ft.Column(
                                    spacing=8,
                                    controls=[
                                        ft.Text(item.title, size=20, weight=ft.FontWeight.BOLD, color=AUREX_TEXT),
                                        ft.Text(item.description, size=13, color=AUREX_MUTED,
                                                max_lines=3, overflow=ft.TextOverflow.ELLIPSIS),
                                        ft.Text(f"by {item.author}", size=12, color=AUREX_MUTED),
                                        ft.Container(height=8),
                                        ft.Row(
                                            alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
                                            vertical_alignment=ft.CrossAxisAlignment.CENTER,
                                            controls=[
                                                ft.Text(f"${item.price:.2f}", size=22,
                                                        weight=ft.FontWeight.BOLD, color=AUREX_GOLD),
                                                ft.FilledButton(
                                                    content=f"Buy  ${item.price:.2f}",
                                                    bgcolor=AUREX_GOLD,
                                                    color="#1A1A1B",
                                                    on_click=handle_buy,
                                                    height=44,
                                                ),
                                            ],
                                        ),
                                    ],
                                ),
                            ),
                        ],
                    ),
                    # X button top-right
                    ft.Container(
                        top=10,
                        right=10,
                        content=ft.IconButton(
                            icon=ft.Icons.CLOSE,
                            icon_color=AUREX_GOLD,
                            icon_size=22,
                            style=ft.ButtonStyle(
                                bgcolor={ft.ControlState.DEFAULT: "#000000BB"},
                                shape=ft.CircleBorder(),
                            ),
                            on_click=close_detail,
                        ),
                    ),
                ],
            ),
        )
        _show_modal(card, overlay_ref)

    def _do_buy_from_card(item: MarketplaceItem) -> None:
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

    def build_item_card(item: MarketplaceItem) -> ft.Control:
        image_control = build_image(item)
        return ft.Container(
            width=_CARD_WIDTH,
            bgcolor=AUREX_CARD,
            border_radius=14,
            border=ft.border.all(1, AUREX_SLATE),
            shadow=ft.BoxShadow(spread_radius=0, blur_radius=12, color="#00000066"),
            clip_behavior=ft.ClipBehavior.ANTI_ALIAS,
            content=ft.Column(
                spacing=0,
                controls=[
                    image_control,
                    ft.Container(
                        padding=ft.padding.symmetric(horizontal=12, vertical=10),
                        content=ft.Column(
                            spacing=5,
                            controls=[
                                ft.Text(
                                    item.title,
                                    size=14,
                                    weight=ft.FontWeight.BOLD,
                                    max_lines=1,
                                    overflow=ft.TextOverflow.ELLIPSIS,
                                    color=AUREX_TEXT,
                                ),
                                ft.Text(
                                    f"by {item.author}",
                                    size=11,
                                    color=AUREX_MUTED,
                                ),
                                ft.Text(
                                    f"${item.price:.2f}",
                                    size=14,
                                    weight=ft.FontWeight.BOLD,
                                    color=AUREX_GOLD_SOFT,
                                ),
                                ft.Row(
                                    spacing=6,
                                    controls=[
                                        ft.Container(
                                            expand=True,
                                            height=34,
                                            bgcolor="#2B2F36",
                                            border_radius=8,
                                            alignment=ft.Alignment(0, 0),
                                            on_click=lambda _, i=item: show_item_detail(i),
                                            content=ft.Text("View", size=12,
                                                            weight=ft.FontWeight.W_600,
                                                            color=AUREX_TEXT),
                                        ),
                                        ft.Container(
                                            expand=True,
                                            height=34,
                                            bgcolor=AUREX_GOLD,
                                            border_radius=8,
                                            alignment=ft.Alignment(0, 0),
                                            on_click=lambda _, i=item: _do_buy_from_card(i),
                                            content=ft.Text("Buy", size=12,
                                                            weight=ft.FontWeight.W_600,
                                                            color="#1A1A1B"),
                                        ),
                                    ],
                                ),
                            ],
                        ),
                    ),
                ],
            ),
        )

    username = app.session.user_data.username if app.session.user_data else "Guest"

    # cards grid: Wrap so they sit naturally at fixed widths
    if app.market_error and not app.session.market_items:
        grid: ft.Control = ft.Container(
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
    elif not app.session.market_items and app.market_loading:
        grid = ft.Container(
            padding=24,
            content=ft.Column(
                horizontal_alignment=ft.CrossAxisAlignment.CENTER,
                controls=[
                    ft.ProgressRing(),
                    ft.Text("Loading marketplace items..."),
                ],
            ),
        )
    elif not app.session.market_items:
        grid = ft.Container(
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
    else:
        grid = ft.Row(
            wrap=True,
            spacing=16,
            run_spacing=16,
            controls=[build_item_card(item) for item in app.session.market_items],
        )

    return ft.View(
        route="/marketplace",
        bgcolor=AUREX_BG,
        scroll=ft.ScrollMode.AUTO,
        controls=[
            ft.Container(
                expand=True,
                padding=ft.padding.symmetric(horizontal=28, vertical=20),
                content=ft.Column(
                    spacing=18,
                    controls=[
                        # header
                        ft.Row(
                            alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
                            vertical_alignment=ft.CrossAxisAlignment.CENTER,
                            controls=[
                                ft.Column(
                                    spacing=2,
                                    controls=[
                                        ft.Text("Aurex Marketplace", size=26, weight=ft.FontWeight.BOLD),
                                        ft.Text(f"Welcome, {username}", color=AUREX_MUTED, size=13),
                                    ],
                                ),
                                ft.Row(
                                    spacing=8,
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
                                            tooltip="Settings",
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
                        # subtitle bar
                        ft.Container(
                            padding=ft.padding.symmetric(horizontal=16, vertical=10),
                            border_radius=12,
                            bgcolor=AUREX_CARD,
                            border=ft.border.all(1, AUREX_SLATE),
                            content=ft.Row(
                                alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
                                controls=[
                                    ft.Text(
                                        "Blockchain-backed digital assets",
                                        color=AUREX_MUTED,
                                        size=13,
                                    ),
                                    ft.Row(
                                        spacing=8,
                                        controls=[
                                            ft.Text(
                                                "Loading..." if app.market_loading
                                                else f"{len(app.session.market_items)} item(s)",
                                                color=AUREX_GOLD_SOFT,
                                                size=13,
                                            ),
                                            ft.ProgressRing(
                                                width=14, height=14, stroke_width=2,
                                                visible=app.market_loading,
                                            ),
                                        ],
                                    ),
                                ],
                            ),
                        ),
                        # card grid
                        grid,
                    ],
                ),
            )
        ],
    )
