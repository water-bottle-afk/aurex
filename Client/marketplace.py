from __future__ import annotations

import threading
from typing import TYPE_CHECKING

import flet as ft

from .models import MarketplaceItem
from . import notifications as _notif
from .theme import (
    AUREX_BG,
    AUREX_CARD,
    AUREX_GOLD,
    AUREX_GOLD_SOFT,
    AUREX_MUTED,
    AUREX_SLATE,
    AUREX_TEXT,
    AUREX_SURFACE,
)

if TYPE_CHECKING:
    from .app import AurexFletApp


_IMAGE_HEIGHT = 200  # image area height inside each card (pixels)


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
        br = ft.border_radius.only(top_left=16, top_right=16)
        if cached:
            return ft.Image(
                src=f"data:{_mime(item.image_url)};base64,{cached}",
                height=_IMAGE_HEIGHT,
                fit=ft.BoxFit.COVER,
                expand=True,
                border_radius=br,
            )
        if cached == "":
            return ft.Container(
                height=_IMAGE_HEIGHT, expand=True,
                bgcolor="#0C0E12",
                alignment=ft.Alignment(0, 0),
                border_radius=br,
                content=ft.Column(
                    horizontal_alignment=ft.CrossAxisAlignment.CENTER,
                    alignment=ft.MainAxisAlignment.CENTER,
                    spacing=6,
                    controls=[
                        ft.Icon(ft.Icons.BROKEN_IMAGE_OUTLINED, color=AUREX_SLATE, size=32),
                        ft.Text("Image unavailable", size=11, color=AUREX_SLATE),
                    ],
                ),
            )
        return ft.Container(
            height=_IMAGE_HEIGHT, expand=True,
            bgcolor="#131720",
            border_radius=br,
            alignment=ft.Alignment(0, 0),
            content=ft.ProgressRing(width=26, height=26, stroke_width=2, color=AUREX_GOLD),
        )

    # ── modal helpers ─────────────────────────────────────────────────────────
    def _show_modal(content: ft.Control, overlay_ref: list) -> None:
        modal = ft.Container(
            expand=True, bgcolor="#000000CC",
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

    # ── buy worker ────────────────────────────────────────────────────────────
    def _buy_item(item: MarketplaceItem) -> None:
        if not app.session.is_authenticated:
            app.show_message("Please log in to buy", error=True)
            return
        username = app.session.user_data.username if app.session.user_data else ""
        def _worker() -> None:
            try:
                app.client.buy_asset(
                    asset_id=str(item.id),
                    username=username,
                    amount=item.price,
                    asset_name=item.title,
                    seller=item.author,
                    asset_hash=item.asset_hash or "",
                )
                app.show_message(f"'{item.title}' purchase initiated!")
            except Exception as exc:
                app.show_message(f"Purchase failed: {exc}", error=True)
        threading.Thread(target=_worker, daemon=True).start()

    # ── detail popup ──────────────────────────────────────────────────────────
    def show_item_detail(item: MarketplaceItem) -> None:
        overlay_ref: list[ft.Control] = []
        cached = app.session.image_cache.get(item.image_url)

        img: ft.Control = ft.Image(
            src=f"data:{_mime(item.image_url)};base64,{cached}",
            width=500, height=320,
            fit=ft.BoxFit.COVER,
            border_radius=ft.border_radius.only(top_left=20, top_right=20),
        ) if cached else ft.Container(
            width=500, height=320, bgcolor="#0C0E12",
            alignment=ft.Alignment(0, 0),
            border_radius=ft.border_radius.only(top_left=20, top_right=20),
            content=ft.Icon(ft.Icons.IMAGE_OUTLINED, size=64, color=AUREX_SLATE),
        )

        def _close(_: ft.ControlEvent) -> None:
            _remove_modal(overlay_ref)

        def _handle_buy(_: ft.ControlEvent) -> None:
            _remove_modal(overlay_ref)
            _buy_item(item)

        hash_row = ft.Row(
            spacing=6,
            controls=[
                ft.Icon(ft.Icons.VERIFIED_OUTLINED, color=AUREX_GOLD, size=14),
                ft.Text(
                    f"Hash: {(item.asset_hash or 'N/A')[:20]}…" if item.asset_hash else "Not yet on blockchain",
                    size=11, color=AUREX_MUTED,
                ),
            ],
        )

        card = ft.Container(
            width=500,
            bgcolor=AUREX_CARD,
            border_radius=20,
            border=ft.border.all(1, AUREX_SLATE),
            shadow=ft.BoxShadow(spread_radius=4, blur_radius=48, color="#000000CC"),
            content=ft.Stack(
                controls=[
                    ft.Column(
                        spacing=0,
                        controls=[
                            img,
                            ft.Container(
                                padding=ft.padding.symmetric(horizontal=24, vertical=20),
                                content=ft.Column(
                                    spacing=10,
                                    controls=[
                                        ft.Row(
                                            alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
                                            vertical_alignment=ft.CrossAxisAlignment.START,
                                            controls=[
                                                ft.Text(
                                                    item.title, size=20,
                                                    weight=ft.FontWeight.BOLD,
                                                    color=AUREX_TEXT, expand=True,
                                                ),
                                                ft.Container(
                                                    padding=ft.padding.symmetric(horizontal=14, vertical=6),
                                                    border_radius=20,
                                                    bgcolor=AUREX_GOLD,
                                                    content=ft.Text(
                                                        f"${item.price:.2f}",
                                                        size=16,
                                                        weight=ft.FontWeight.BOLD,
                                                        color="#1A1A1B",
                                                    ),
                                                ),
                                            ],
                                        ),
                                        ft.Text(
                                            f"by {item.author}",
                                            size=12, color=AUREX_GOLD_SOFT,
                                        ),
                                        ft.Text(
                                            item.description,
                                            size=13, color=AUREX_MUTED,
                                            max_lines=4,
                                            overflow=ft.TextOverflow.ELLIPSIS,
                                        ),
                                        hash_row,
                                        ft.Divider(height=1, color=AUREX_SLATE),
                                        ft.FilledButton(
                                            content=f"Buy for ${item.price:.2f}",
                                            icon=ft.Icons.SHOPPING_CART_OUTLINED,
                                            style=ft.ButtonStyle(
                                                bgcolor=AUREX_GOLD,
                                                color="#1A1A1B",
                                                shape=ft.RoundedRectangleBorder(radius=12),
                                            ),
                                            width=452,
                                            height=46,
                                            on_click=_handle_buy,
                                        ),
                                    ],
                                ),
                            ),
                        ],
                    ),
                    ft.Container(
                        top=10, right=10,
                        content=ft.IconButton(
                            icon=ft.Icons.CLOSE,
                            icon_color="white",
                            icon_size=20,
                            style=ft.ButtonStyle(
                                bgcolor={ft.ControlState.DEFAULT: "#000000AA"},
                                shape=ft.CircleBorder(),
                            ),
                            on_click=_close,
                        ),
                    ),
                ],
            ),
        )
        _show_modal(card, overlay_ref)

    # ── card builder ──────────────────────────────────────────────────────────
    def build_item_card(item: MarketplaceItem) -> ft.Control:
        image_stack = ft.Stack(
            controls=[
                build_image(item),
                ft.Container(
                    bottom=8, right=10,
                    padding=ft.padding.symmetric(horizontal=10, vertical=4),
                    border_radius=20,
                    bgcolor="#000000BB",
                    content=ft.Text(
                        f"${item.price:.2f}",
                        size=13,
                        weight=ft.FontWeight.BOLD,
                        color=AUREX_GOLD,
                    ),
                ),
            ],
        )

        card = ft.Container(
            bgcolor=AUREX_CARD,
            border_radius=16,
            border=ft.border.all(1, AUREX_SLATE),
            shadow=ft.BoxShadow(spread_radius=0, blur_radius=16, color="#00000055"),
            clip_behavior=ft.ClipBehavior.ANTI_ALIAS,
            expand=True,
            content=ft.Column(
                spacing=0,
                controls=[
                    image_stack,
                    ft.Container(
                        padding=ft.padding.symmetric(horizontal=14, vertical=12),
                        content=ft.Column(
                            spacing=4,
                            controls=[
                                ft.Text(
                                    item.title,
                                    size=15,
                                    weight=ft.FontWeight.BOLD,
                                    max_lines=1,
                                    overflow=ft.TextOverflow.ELLIPSIS,
                                    color=AUREX_TEXT,
                                ),
                                ft.Text(
                                    f"by {item.author}",
                                    size=11,
                                    color=AUREX_GOLD_SOFT,
                                ),
                                ft.Text(
                                    item.description,
                                    size=11,
                                    color=AUREX_MUTED,
                                    max_lines=2,
                                    overflow=ft.TextOverflow.ELLIPSIS,
                                ),
                                ft.Container(height=4),
                                ft.Row(
                                    spacing=6,
                                    controls=[
                                        ft.Container(
                                            expand=True, height=36,
                                            bgcolor=AUREX_SURFACE,
                                            border_radius=10,
                                            border=ft.border.all(1, AUREX_SLATE),
                                            alignment=ft.Alignment(0, 0),
                                            on_click=lambda _, i=item: show_item_detail(i),
                                            content=ft.Row(
                                                alignment=ft.MainAxisAlignment.CENTER,
                                                spacing=4,
                                                controls=[
                                                    ft.Icon(ft.Icons.OPEN_IN_NEW, size=13, color=AUREX_MUTED),
                                                    ft.Text("Details", size=12,
                                                            weight=ft.FontWeight.W_500,
                                                            color=AUREX_TEXT),
                                                ],
                                            ),
                                        ),
                                        ft.Container(
                                            expand=True, height=36,
                                            bgcolor=AUREX_GOLD,
                                            border_radius=10,
                                            alignment=ft.Alignment(0, 0),
                                            on_click=lambda _, i=item: _buy_item(i),
                                            content=ft.Row(
                                                alignment=ft.MainAxisAlignment.CENTER,
                                                spacing=4,
                                                controls=[
                                                    ft.Icon(ft.Icons.SHOPPING_CART_OUTLINED,
                                                            size=13, color="#1A1A1B"),
                                                    ft.Text("Buy", size=12,
                                                            weight=ft.FontWeight.BOLD,
                                                            color="#1A1A1B"),
                                                ],
                                            ),
                                        ),
                                    ],
                                ),
                            ],
                        ),
                    ),
                ],
            ),
        )
        return ft.Container(
            col={"xs": 12, "sm": 6, "md": 4, "lg": 4, "xl": 3},
            content=card,
            padding=ft.padding.all(8),
        )

    username = app.session.user_data.username if app.session.user_data else "Guest"
    item_count = len(app.session.market_items)
    _bal = app.session.wallet_balance
    _balance_text = f"${_bal:.2f}" if isinstance(_bal, (int, float)) else "—"

    # ── grid / state area ─────────────────────────────────────────────────────
    if app.market_error and not app.session.market_items:
        grid: ft.Control = ft.Container(
            padding=40,
            border_radius=20,
            bgcolor=AUREX_CARD,
            border=ft.border.all(1, "#EF444440"),
            content=ft.Column(
                horizontal_alignment=ft.CrossAxisAlignment.CENTER,
                spacing=16,
                controls=[
                    ft.Icon(ft.Icons.CLOUD_OFF_OUTLINED, size=56, color="#EF4444"),
                    ft.Text("Failed to load marketplace", size=16,
                            weight=ft.FontWeight.BOLD, color="#EF4444"),
                    ft.Text(app.market_error, text_align=ft.TextAlign.CENTER,
                            color=AUREX_MUTED, size=13),
                    ft.FilledButton(
                        content="Try Again",
                        icon=ft.Icons.REFRESH,
                        style=ft.ButtonStyle(
                            bgcolor=AUREX_GOLD, color="#1A1A1B",
                            shape=ft.RoundedRectangleBorder(radius=12),
                        ),
                        on_click=lambda _: app.load_marketplace_async(reset=True),
                    ),
                ],
            ),
        )
    elif not app.session.market_items and app.market_loading:
        grid = ft.Container(
            padding=60,
            alignment=ft.Alignment(0, 0),
            content=ft.Column(
                horizontal_alignment=ft.CrossAxisAlignment.CENTER,
                spacing=16,
                controls=[
                    ft.ProgressRing(width=48, height=48, stroke_width=3, color=AUREX_GOLD),
                    ft.Text("Loading assets…", size=14, color=AUREX_MUTED),
                ],
            ),
        )
    elif not app.session.market_items:
        grid = ft.Container(
            padding=60,
            border_radius=20,
            bgcolor=AUREX_CARD,
            border=ft.border.all(1, AUREX_SLATE),
            alignment=ft.Alignment(0, 0),
            content=ft.Column(
                horizontal_alignment=ft.CrossAxisAlignment.CENTER,
                spacing=14,
                controls=[
                    ft.Icon(ft.Icons.INVENTORY_2_OUTLINED, size=56, color=AUREX_SLATE),
                    ft.Text("No assets listed yet", size=16,
                            weight=ft.FontWeight.BOLD, color=AUREX_MUTED),
                    ft.Text("Be the first to upload an asset to the marketplace.",
                            size=13, color=AUREX_MUTED,
                            text_align=ft.TextAlign.CENTER),
                    ft.Row(
                        alignment=ft.MainAxisAlignment.CENTER,
                        spacing=10,
                        controls=[
                            ft.FilledButton(
                                content="Upload Asset",
                                icon=ft.Icons.CLOUD_UPLOAD_OUTLINED,
                                style=ft.ButtonStyle(
                                    bgcolor=AUREX_GOLD, color="#1A1A1B",
                                    shape=ft.RoundedRectangleBorder(radius=12),
                                ),
                                on_click=lambda _: page.run_task(page.push_route, "/upload"),
                            ),
                            ft.OutlinedButton(
                                content="Refresh",
                                icon=ft.Icons.REFRESH,
                                style=ft.ButtonStyle(
                                    shape=ft.RoundedRectangleBorder(radius=12),
                                ),
                                on_click=lambda _: app.load_marketplace_async(reset=True),
                            ),
                        ],
                    ),
                ],
            ),
        )
    else:
        load_more_btn = ft.Container(
            alignment=ft.Alignment(0, 0),
            padding=ft.padding.symmetric(vertical=8),
            content=ft.OutlinedButton(
                content="Load More",
                icon=ft.Icons.EXPAND_MORE,
                style=ft.ButtonStyle(shape=ft.RoundedRectangleBorder(radius=12)),
                visible=not app.market_loading and bool(app.session.last_market_cursor),
                on_click=lambda _: app.load_marketplace_async(reset=False),
            ),
        )
        grid = ft.Column(
            spacing=0,
            controls=[
                ft.ResponsiveRow(
                    spacing=0, run_spacing=0,
                    controls=[build_item_card(item) for item in app.session.market_items],
                ),
                load_more_btn,
            ],
        )

    # ── top navbar ────────────────────────────────────────────────────────────
    unread = _notif.unread_count()
    notif_bell = ft.Stack(
        width=40, height=40,
        controls=[
            ft.IconButton(
                icon=ft.Icons.NOTIFICATIONS_OUTLINED,
                icon_color=AUREX_MUTED,
                tooltip="Notifications",
                icon_size=22,
                on_click=lambda _: page.run_task(page.push_route, "/notifications"),
            ),
            ft.Container(
                visible=unread > 0,
                right=4, top=4,
                width=16, height=16,
                border_radius=8,
                bgcolor="#EF4444",
                alignment=ft.Alignment(0, 0),
                content=ft.Text(str(min(unread, 99)), size=9,
                                weight=ft.FontWeight.BOLD, color="white"),
            ),
        ],
    )

    nav_row = ft.Row(
        alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
        vertical_alignment=ft.CrossAxisAlignment.CENTER,
        controls=[
            # brand
            ft.Row(
                spacing=12,
                vertical_alignment=ft.CrossAxisAlignment.CENTER,
                controls=[
                    ft.Container(
                        width=36, height=36,
                        border_radius=10,
                        bgcolor="#FFD70020",
                        alignment=ft.Alignment(0, 0),
                        content=ft.Icon(ft.Icons.DIAMOND_OUTLINED, color=AUREX_GOLD, size=20),
                    ),
                    ft.Column(
                        spacing=0,
                        controls=[
                            ft.Text("Aurex", size=18, weight=ft.FontWeight.BOLD, color=AUREX_GOLD),
                            ft.Text("Marketplace", size=10, color=AUREX_MUTED),
                        ],
                    ),
                ],
            ),
            # actions
            ft.Row(
                spacing=6,
                vertical_alignment=ft.CrossAxisAlignment.CENTER,
                controls=[
                    ft.FilledButton(
                        content="Upload",
                        icon=ft.Icons.CLOUD_UPLOAD_OUTLINED,
                        style=ft.ButtonStyle(
                            bgcolor=AUREX_GOLD, color="#1A1A1B",
                            shape=ft.RoundedRectangleBorder(radius=10),
                        ),
                        height=36,
                        on_click=lambda _: page.run_task(page.push_route, "/upload"),
                    ),
                    ft.OutlinedButton(
                        content="My Assets",
                        icon=ft.Icons.COLLECTIONS_OUTLINED,
                        height=36,
                        style=ft.ButtonStyle(shape=ft.RoundedRectangleBorder(radius=10)),
                        on_click=lambda _: page.run_task(page.push_route, "/my_assets"),
                    ),
                    # ── wallet balance chip ───────────────────────────────────
                    ft.Container(
                        height=36,
                        padding=ft.padding.symmetric(horizontal=12, vertical=0),
                        border_radius=10,
                        bgcolor="#FFD70018",
                        border=ft.border.all(1, "#FFD70055"),
                        tooltip="Your wallet balance",
                        alignment=ft.Alignment(0, 0),
                        content=ft.Row(
                            spacing=6,
                            vertical_alignment=ft.CrossAxisAlignment.CENTER,
                            controls=[
                                ft.Icon(ft.Icons.TOLL_OUTLINED, size=15, color=AUREX_GOLD),
                                ft.Text(
                                    _balance_text,
                                    size=13,
                                    weight=ft.FontWeight.BOLD,
                                    color=AUREX_GOLD,
                                ),
                            ],
                        ),
                    ),
                    notif_bell,
                    ft.IconButton(
                        icon=ft.Icons.SETTINGS_OUTLINED,
                        icon_color=AUREX_MUTED,
                        tooltip="Settings",
                        on_click=lambda _: page.run_task(page.push_route, "/settings"),
                    ),
                    ft.Container(
                        padding=ft.padding.symmetric(horizontal=10, vertical=6),
                        border_radius=8,
                        bgcolor=AUREX_SLATE,
                        content=ft.Row(
                            spacing=6,
                            vertical_alignment=ft.CrossAxisAlignment.CENTER,
                            controls=[
                                ft.Container(
                                    width=24, height=24, border_radius=12,
                                    bgcolor="#FFD70030",
                                    alignment=ft.Alignment(0, 0),
                                    content=ft.Text(
                                        username[0].upper() if username else "?",
                                        size=11, weight=ft.FontWeight.BOLD, color=AUREX_GOLD,
                                    ),
                                ),
                                ft.Text(username, size=12, color=AUREX_TEXT),
                            ],
                        ),
                        on_click=lambda _: app.logout(),
                        tooltip="Click to logout",
                    ),
                ],
            ),
        ],
    )

    # ── stats bar ─────────────────────────────────────────────────────────────
    stats_bar = ft.Container(
        padding=ft.padding.symmetric(horizontal=20, vertical=12),
        border_radius=14,
        bgcolor=AUREX_CARD,
        border=ft.border.all(1, AUREX_SLATE),
        content=ft.Row(
            alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
            vertical_alignment=ft.CrossAxisAlignment.CENTER,
            controls=[
                ft.Row(
                    spacing=20,
                    controls=[
                        ft.Row(
                            spacing=6,
                            controls=[
                                ft.Icon(ft.Icons.STOREFRONT_OUTLINED, color=AUREX_GOLD, size=16),
                                ft.Text(
                                    f"{item_count} asset{'s' if item_count != 1 else ''} listed",
                                    size=13, color=AUREX_TEXT,
                                ),
                            ],
                        ),
                        ft.Row(
                            spacing=6,
                            controls=[
                                ft.Icon(ft.Icons.LINK_OUTLINED, color=AUREX_MUTED, size=14),
                                ft.Text("Blockchain-verified NFTs",
                                        size=12, color=AUREX_MUTED),
                            ],
                        ),
                    ],
                ),
                ft.Row(
                    spacing=8,
                    controls=[
                        ft.ProgressRing(
                            width=14, height=14, stroke_width=2, color=AUREX_GOLD,
                            visible=app.market_loading,
                        ),
                        ft.Text(
                            "Loading…" if app.market_loading else "Live",
                            size=12,
                            color=AUREX_GOLD_SOFT if not app.market_loading else AUREX_MUTED,
                        ),
                        ft.OutlinedButton(
                            content="Refresh",
                            icon=ft.Icons.REFRESH,
                            height=32,
                            style=ft.ButtonStyle(
                                shape=ft.RoundedRectangleBorder(radius=8),
                                padding=ft.padding.symmetric(horizontal=10),
                            ),
                            on_click=lambda _: app.load_marketplace_async(reset=True),
                        ),
                    ],
                ),
            ],
        ),
    )

    return ft.View(
        route="/marketplace",
        bgcolor=AUREX_BG,
        scroll=ft.ScrollMode.AUTO,
        padding=0,
        controls=[
            ft.Container(
                expand=True,
                padding=ft.padding.symmetric(horizontal=32, vertical=24),
                content=ft.Column(
                    spacing=20,
                    controls=[
                        nav_row,
                        stats_bar,
                        grid,
                    ],
                ),
            ),
        ],
    )
