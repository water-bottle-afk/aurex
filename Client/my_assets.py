from __future__ import annotations

import base64
import threading
from typing import TYPE_CHECKING

import flet as ft

from .theme import (
    AUREX_BG,
    AUREX_CARD,
    AUREX_GOLD,
    AUREX_GOLD_SOFT,
    AUREX_MUTED,
    AUREX_SLATE,
    AUREX_SURFACE,
    AUREX_TEXT,
)

if TYPE_CHECKING:
    from .app import AurexFletApp

_IMAGE_HEIGHT = 180


def build_my_assets_view(app: "AurexFletApp") -> ft.View:
    page = app.page
    username = app.session.user_data.username if app.session.user_data else ""

    # ── state ─────────────────────────────────────────────────────────────────
    assets_ref: list = []        # filled by _load_worker
    loading_ref: list = [True]   # [0] = bool
    error_ref:   list = [None]   # [0] = str|None

    # ── image helper ──────────────────────────────────────────────────────────
    def _mime(url: str) -> str:
        return "image/png" if url.endswith(".png") else "image/jpeg"

    def _build_image(image_url: str) -> ft.Control:
        cached = app.session.image_cache.get(image_url)
        br = ft.border_radius.only(top_left=14, top_right=14)
        if cached:
            return ft.Image(
                src=f"data:{_mime(image_url)};base64,{cached}",
                height=_IMAGE_HEIGHT, fit=ft.BoxFit.COVER, expand=True,
                border_radius=br,
            )
        if cached == "":
            return ft.Container(
                height=_IMAGE_HEIGHT, expand=True, bgcolor="#0C0E12",
                border_radius=br, alignment=ft.Alignment(0, 0),
                content=ft.Icon(ft.Icons.BROKEN_IMAGE_OUTLINED, color=AUREX_SLATE, size=28),
            )
        app.prefetch_image_async(image_url)
        return ft.Container(
            height=_IMAGE_HEIGHT, expand=True, bgcolor="#131720",
            border_radius=br, alignment=ft.Alignment(0, 0),
            content=ft.ProgressRing(width=24, height=24, stroke_width=2, color=AUREX_GOLD),
        )

    # ── body placeholder (mutated after load) ─────────────────────────────────
    body = ft.Column(
        spacing=16,
        controls=[
            ft.Container(
                padding=40,
                alignment=ft.Alignment(0, 0),
                content=ft.Column(
                    horizontal_alignment=ft.CrossAxisAlignment.CENTER,
                    spacing=12,
                    controls=[
                        ft.ProgressRing(width=40, height=40, stroke_width=3, color=AUREX_GOLD),
                        ft.Text("Loading your assets…", color=AUREX_MUTED, size=13),
                    ],
                ),
            )
        ],
    )

    def _rebuild_body() -> None:
        """Rebuild body.controls from current state."""
        body.controls.clear()

        if error_ref[0]:
            body.controls.append(
                ft.Container(
                    padding=40,
                    border_radius=20,
                    bgcolor=AUREX_CARD,
                    border=ft.border.all(1, "#EF444440"),
                    content=ft.Column(
                        horizontal_alignment=ft.CrossAxisAlignment.CENTER,
                        spacing=14,
                        controls=[
                            ft.Icon(ft.Icons.CLOUD_OFF_OUTLINED, size=48, color="#EF4444"),
                            ft.Text("Failed to load assets", size=15, weight=ft.FontWeight.BOLD, color="#EF4444"),
                            ft.Text(str(error_ref[0]), color=AUREX_MUTED, size=12, text_align=ft.TextAlign.CENTER),
                            ft.FilledButton(
                                content="Retry",
                                icon=ft.Icons.REFRESH,
                                style=ft.ButtonStyle(bgcolor=AUREX_GOLD, color="#1A1A1B",
                                                     shape=ft.RoundedRectangleBorder(radius=10)),
                                on_click=lambda _: _start_load(),
                            ),
                        ],
                    ),
                )
            )
            page.update()
            return

        if loading_ref[0]:
            body.controls.append(
                ft.Container(
                    padding=40, alignment=ft.Alignment(0, 0),
                    content=ft.Column(
                        horizontal_alignment=ft.CrossAxisAlignment.CENTER, spacing=12,
                        controls=[
                            ft.ProgressRing(width=40, height=40, stroke_width=3, color=AUREX_GOLD),
                            ft.Text("Loading your assets…", color=AUREX_MUTED, size=13),
                        ],
                    ),
                )
            )
            page.update()
            return

        items = assets_ref
        if not items:
            body.controls.append(
                ft.Container(
                    padding=60, border_radius=20,
                    bgcolor=AUREX_CARD, border=ft.border.all(1, AUREX_SLATE),
                    alignment=ft.Alignment(0, 0),
                    content=ft.Column(
                        horizontal_alignment=ft.CrossAxisAlignment.CENTER, spacing=14,
                        controls=[
                            ft.Icon(ft.Icons.INVENTORY_2_OUTLINED, size=56, color=AUREX_SLATE),
                            ft.Text("You don't own any assets yet", size=15,
                                    weight=ft.FontWeight.BOLD, color=AUREX_MUTED),
                            ft.Text("Upload an asset or buy one from the marketplace.",
                                    size=12, color=AUREX_MUTED, text_align=ft.TextAlign.CENTER),
                            ft.FilledButton(
                                content="Browse Marketplace",
                                icon=ft.Icons.STOREFRONT_OUTLINED,
                                style=ft.ButtonStyle(bgcolor=AUREX_GOLD, color="#1A1A1B",
                                                     shape=ft.RoundedRectangleBorder(radius=10)),
                                on_click=lambda _: page.run_task(page.push_route, "/marketplace"),
                            ),
                        ],
                    ),
                )
            )
            page.update()
            return

        # build responsive grid of asset cards
        def _build_card(item) -> ft.Control:
            img = _build_image(item.image_url)

            img_stack = ft.Stack(controls=[
                img,
                ft.Container(
                    bottom=8, right=10,
                    padding=ft.padding.symmetric(horizontal=10, vertical=4),
                    border_radius=20, bgcolor="#000000BB",
                    content=ft.Text(f"${item.price:.2f}", size=12,
                                    weight=ft.FontWeight.BOLD, color=AUREX_GOLD),
                ),
            ])

            listed_badge = ft.Container(
                padding=ft.padding.symmetric(horizontal=8, vertical=3),
                border_radius=8,
                bgcolor="#22C55E20",
                border=ft.border.all(1, "#22C55E"),
                content=ft.Text("Listed", size=10, color="#22C55E", weight=ft.FontWeight.BOLD),
                visible=item.is_listed,
            )
            unlisted_badge = ft.Container(
                padding=ft.padding.symmetric(horizontal=8, vertical=3),
                border_radius=8,
                bgcolor="#9CA3AF20",
                border=ft.border.all(1, AUREX_SLATE),
                content=ft.Text("Unlisted", size=10, color=AUREX_MUTED),
                visible=not item.is_listed,
            )

            card = ft.Container(
                bgcolor=AUREX_CARD,
                border_radius=16,
                border=ft.border.all(1, AUREX_SLATE),
                clip_behavior=ft.ClipBehavior.ANTI_ALIAS,
                expand=True,
                content=ft.Column(
                    spacing=0,
                    controls=[
                        img_stack,
                        ft.Container(
                            padding=ft.padding.symmetric(horizontal=14, vertical=12),
                            content=ft.Column(
                                spacing=5,
                                controls=[
                                    ft.Row(
                                        alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
                                        controls=[
                                            ft.Text(
                                                item.title, size=14,
                                                weight=ft.FontWeight.BOLD,
                                                max_lines=1,
                                                overflow=ft.TextOverflow.ELLIPSIS,
                                                color=AUREX_TEXT, expand=True,
                                            ),
                                            listed_badge,
                                            unlisted_badge,
                                        ],
                                    ),
                                    ft.Text(item.description, size=11, color=AUREX_MUTED,
                                            max_lines=2, overflow=ft.TextOverflow.ELLIPSIS),
                                    ft.Container(height=4),
                                    ft.Row(
                                        spacing=6,
                                        controls=[
                                            ft.Container(
                                                expand=True, height=34,
                                                bgcolor=AUREX_SURFACE,
                                                border_radius=10,
                                                border=ft.border.all(1, AUREX_SLATE),
                                                alignment=ft.Alignment(0, 0),
                                                on_click=lambda _, i=item: _show_detail(i),
                                                content=ft.Text("Details", size=11,
                                                                color=AUREX_TEXT),
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

        body.controls.append(
            ft.ResponsiveRow(
                spacing=0, run_spacing=0,
                controls=[_build_card(it) for it in items],
            )
        )
        page.update()

    def _show_detail(item) -> None:
        overlay_ref: list = []
        cached = app.session.image_cache.get(item.image_url)
        img: ft.Control = ft.Image(
            src=f"data:{_mime(item.image_url)};base64,{cached}",
            width=480, height=280, fit=ft.BoxFit.COVER,
            border_radius=ft.border_radius.only(top_left=20, top_right=20),
        ) if cached else ft.Container(
            width=480, height=280, bgcolor="#0C0E12",
            alignment=ft.Alignment(0, 0),
            border_radius=ft.border_radius.only(top_left=20, top_right=20),
            content=ft.Icon(ft.Icons.IMAGE_OUTLINED, size=56, color=AUREX_SLATE),
        )

        def _close(_=None) -> None:
            if overlay_ref:
                try:
                    page.overlay.remove(overlay_ref[0])
                except ValueError:
                    pass
                overlay_ref.clear()
                page.update()

        hash_text = (item.asset_hash or "")[:24] + "…" if item.asset_hash else "Not yet on blockchain"
        card = ft.Container(
            width=480, bgcolor=AUREX_CARD,
            border_radius=20, border=ft.border.all(1, AUREX_SLATE),
            shadow=ft.BoxShadow(spread_radius=4, blur_radius=48, color="#000000CC"),
            content=ft.Stack(controls=[
                ft.Column(spacing=0, controls=[
                    img,
                    ft.Container(
                        padding=ft.padding.symmetric(horizontal=24, vertical=20),
                        content=ft.Column(spacing=10, controls=[
                            ft.Row(
                                alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
                                controls=[
                                    ft.Text(item.title, size=18, weight=ft.FontWeight.BOLD,
                                            color=AUREX_TEXT, expand=True),
                                    ft.Container(
                                        padding=ft.padding.symmetric(horizontal=12, vertical=5),
                                        border_radius=16, bgcolor=AUREX_GOLD,
                                        content=ft.Text(f"${item.price:.2f}", size=14,
                                                        weight=ft.FontWeight.BOLD, color="#1A1A1B"),
                                    ),
                                ],
                            ),
                            ft.Text(item.description, size=12, color=AUREX_MUTED,
                                    max_lines=3, overflow=ft.TextOverflow.ELLIPSIS),
                            ft.Row(spacing=6, controls=[
                                ft.Icon(ft.Icons.VERIFIED_OUTLINED, color=AUREX_GOLD, size=13),
                                ft.Text(hash_text, size=11, color=AUREX_MUTED),
                            ]),
                            ft.Divider(height=1, color=AUREX_SLATE),
                            ft.FilledButton(
                                content="Close",
                                icon=ft.Icons.CLOSE,
                                style=ft.ButtonStyle(
                                    bgcolor=AUREX_SLATE, color=AUREX_TEXT,
                                    shape=ft.RoundedRectangleBorder(radius=10),
                                ),
                                width=432, height=40,
                                on_click=_close,
                            ),
                        ]),
                    ),
                ]),
                ft.Container(
                    top=10, right=10,
                    content=ft.IconButton(
                        icon=ft.Icons.CLOSE, icon_color="white", icon_size=18,
                        style=ft.ButtonStyle(
                            bgcolor={ft.ControlState.DEFAULT: "#000000AA"},
                            shape=ft.CircleBorder(),
                        ),
                        on_click=_close,
                    ),
                ),
            ]),
        )
        modal = ft.Container(
            expand=True, bgcolor="#000000CC",
            alignment=ft.Alignment(0, 0), content=card,
        )
        overlay_ref.append(modal)
        page.overlay.append(modal)
        page.update()

    def _load_worker() -> None:
        try:
            app.connect_if_needed(discover_first=False)
            items = app.client.get_user_assets(username)
            assets_ref.clear()
            assets_ref.extend(items)
            error_ref[0] = None
        except Exception as exc:
            error_ref[0] = str(exc)
        finally:
            loading_ref[0] = False
            _rebuild_body()
            for it in assets_ref:
                app.prefetch_image_async(it.image_url)

    def _start_load() -> None:
        loading_ref[0] = True
        error_ref[0] = None
        _rebuild_body()
        threading.Thread(target=_load_worker, daemon=True).start()

    _start_load()

    # ── nav row ───────────────────────────────────────────────────────────────
    nav_row = ft.Row(
        alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
        vertical_alignment=ft.CrossAxisAlignment.CENTER,
        controls=[
            ft.Row(
                spacing=10,
                vertical_alignment=ft.CrossAxisAlignment.CENTER,
                controls=[
                    ft.IconButton(
                        icon=ft.Icons.ARROW_BACK_IOS_NEW_ROUNDED,
                        icon_color=AUREX_MUTED,
                        tooltip="Back to Marketplace",
                        on_click=lambda _: page.run_task(page.push_route, "/marketplace"),
                    ),
                    ft.Container(
                        width=36, height=36, border_radius=10,
                        bgcolor="#FFD70020", alignment=ft.Alignment(0, 0),
                        content=ft.Icon(ft.Icons.COLLECTIONS_OUTLINED, color=AUREX_GOLD, size=20),
                    ),
                    ft.Column(
                        spacing=0,
                        controls=[
                            ft.Text("My Assets", size=20, weight=ft.FontWeight.BOLD),
                            ft.Text(f"@{username}", size=11, color=AUREX_MUTED),
                        ],
                    ),
                ],
            ),
            ft.FilledButton(
                content="Upload New",
                icon=ft.Icons.CLOUD_UPLOAD_OUTLINED,
                style=ft.ButtonStyle(
                    bgcolor=AUREX_GOLD, color="#1A1A1B",
                    shape=ft.RoundedRectangleBorder(radius=10),
                ),
                height=36,
                on_click=lambda _: page.run_task(page.push_route, "/upload"),
            ),
        ],
    )

    return ft.View(
        route="/my_assets",
        bgcolor=AUREX_BG,
        scroll=ft.ScrollMode.AUTO,
        padding=0,
        controls=[
            ft.Container(
                expand=True,
                padding=ft.padding.symmetric(horizontal=32, vertical=24),
                content=ft.Column(
                    spacing=20,
                    controls=[nav_row, body],
                ),
            ),
        ],
    )
