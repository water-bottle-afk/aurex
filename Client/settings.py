from __future__ import annotations

import json
import threading
from pathlib import Path
from typing import TYPE_CHECKING

import flet as ft

from .theme import AUREX_BG, AUREX_CARD, AUREX_GOLD, AUREX_GOLD_SOFT, AUREX_MUTED, AUREX_SLATE, AUREX_TEXT
from . import wallet as _wallet

if TYPE_CHECKING:
    from .app import AurexFletApp

_KEY_FILE = _wallet._KEY_FILE


def build_settings_view(app: "AurexFletApp") -> ft.View:
    page = app.page
    user = app.session.user_data

    # ── server connection ────────────────────────────────────────────────────
    host_field = ft.TextField(
        label="Server IP",
        border_radius=16,
        value=app.session.host or app.client.host,
    )
    port_field = ft.TextField(
        label="Port",
        border_radius=16,
        value=str(app.session.port or app.client.port),
    )

    def save_connection(_: ft.ControlEvent) -> None:
        host = host_field.value.strip()
        try:
            port = int(port_field.value.strip())
        except Exception:
            app.show_message("Invalid port value", error=True)
            return
        if not host:
            app.show_message("Server IP is required", error=True)
            return
        app.client.set_server_address(host, port)
        app.show_message("Server settings updated")

    # ── wallet section state ─────────────────────────────────────────────────
    has_key = _KEY_FILE.exists()

    pubkey_display = ft.TextField(
        label="Your Public Key",
        read_only=True,
        border_radius=12,
        multiline=True,
        min_lines=2,
        max_lines=3,
        text_size=11,
        value=(_wallet.get_public_key_base64() if has_key else ""),
        color=AUREX_GOLD_SOFT,
    )

    key_status_icon = ft.Icon(
        ft.Icons.VERIFIED_OUTLINED if has_key else ft.Icons.WARNING_AMBER_ROUNDED,
        color="#22C55E" if has_key else "#EAB308",
        size=20,
    )
    key_status_text = ft.Text(
        "Wallet keys found — ready to upload" if has_key else "No wallet keys detected",
        color="#22C55E" if has_key else "#EAB308",
        size=13,
    )

    generate_btn = ft.FilledButton(
        content="Generate My Keys",
        bgcolor=AUREX_GOLD,
        color="#1A1A1B",
        icon=ft.Icons.KEY,
    )
    regenerate_btn = ft.TextButton(
        content="Regenerate Keys (replaces existing)",
        icon=ft.Icons.REFRESH,
    )
    download_btn = ft.OutlinedButton(
        content="Download Key Backup (JSON)",
        icon=ft.Icons.DOWNLOAD,
        disabled=not has_key,
    )

    # overlay container ref
    _overlay_ref: list[ft.Control] = []

    def _show_download_overlay(pub_b64: str, priv_pem: str) -> None:
        """Show a centered modal card with key data."""
        payload = json.dumps(
            {"public_key": pub_b64, "private_key_pem": priv_pem},
            indent=2,
        )

        def close_overlay(_: ft.ControlEvent) -> None:
            if _overlay_ref:
                try:
                    page.overlay.remove(_overlay_ref[0])
                except ValueError:
                    pass
                _overlay_ref.clear()
                page.update()

        card = ft.Container(
            width=520,
            bgcolor=AUREX_CARD,
            border_radius=20,
            border=ft.border.all(1, AUREX_SLATE),
            shadow=ft.BoxShadow(spread_radius=2, blur_radius=40, color="#000000BB"),
            padding=0,
            content=ft.Stack(
                controls=[
                    ft.Column(
                        scroll=ft.ScrollMode.AUTO,
                        height=560,
                        spacing=0,
                        controls=[
                            # header strip
                            ft.Container(
                                padding=ft.padding.symmetric(horizontal=24, vertical=18),
                                border_radius=ft.border_radius.only(top_left=20, top_right=20),
                                bgcolor="#12141A",
                                content=ft.Row(
                                    controls=[
                                        ft.Icon(ft.Icons.KEY, color=AUREX_GOLD, size=22),
                                        ft.Text(
                                            "Your Aurex Wallet Keys",
                                            size=18,
                                            weight=ft.FontWeight.BOLD,
                                        ),
                                    ],
                                    spacing=10,
                                ),
                            ),
                            # body
                            ft.Container(
                                padding=ft.padding.symmetric(horizontal=24, vertical=16),
                                content=ft.Column(
                                    spacing=14,
                                    controls=[
                                        # warning box
                                        ft.Container(
                                            padding=14,
                                            border_radius=12,
                                            bgcolor="#1A1D24",
                                            border=ft.border.all(1, "#EAB30860"),
                                            content=ft.Column(
                                                spacing=6,
                                                controls=[
                                                    ft.Row(
                                                        spacing=8,
                                                        controls=[
                                                            ft.Icon(ft.Icons.WARNING_AMBER_ROUNDED,
                                                                    color="#EAB308", size=18),
                                                            ft.Text(
                                                                "CRITICAL — Read before closing",
                                                                weight=ft.FontWeight.BOLD,
                                                                color="#EAB308",
                                                                size=13,
                                                            ),
                                                        ],
                                                    ),
                                                    ft.Text(
                                                        "• Private Key shown once — copy it now.\n"
                                                        "• Server never stores your private key.\n"
                                                        "• Loss = UNRECOVERABLE assets.\n"
                                                        "• Save the JSON backup offline.",
                                                        color=AUREX_MUTED,
                                                        size=12,
                                                    ),
                                                ],
                                            ),
                                        ),
                                        ft.Text("Public Key (safe to share)",
                                                color=AUREX_MUTED, size=12),
                                        ft.TextField(
                                            read_only=True,
                                            value=pub_b64,
                                            multiline=True,
                                            min_lines=2,
                                            max_lines=3,
                                            text_size=11,
                                            color=AUREX_GOLD_SOFT,
                                            border_radius=10,
                                        ),
                                        ft.Text("Private Key PEM (keep secret)",
                                                color="#EF4444", size=12),
                                        ft.TextField(
                                            read_only=True,
                                            value=priv_pem,
                                            multiline=True,
                                            min_lines=3,
                                            max_lines=5,
                                            text_size=10,
                                            color="#EF4444",
                                            border_radius=10,
                                        ),
                                        ft.Text(
                                            "Full JSON backup — copy & save as .json:",
                                            color=AUREX_MUTED,
                                            size=12,
                                        ),
                                        ft.TextField(
                                            read_only=True,
                                            value=payload,
                                            multiline=True,
                                            min_lines=5,
                                            max_lines=7,
                                            text_size=10,
                                            border_radius=10,
                                        ),
                                        ft.FilledButton(
                                            content="Done — I saved my keys",
                                            bgcolor=AUREX_GOLD,
                                            color="#1A1A1B",
                                            width=480,
                                            on_click=close_overlay,
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
                            icon_size=20,
                            style=ft.ButtonStyle(
                                bgcolor={ft.ControlState.DEFAULT: "#000000AA"},
                                shape=ft.CircleBorder(),
                            ),
                            on_click=close_overlay,
                        ),
                    ),
                ],
            ),
        )

        modal = ft.Container(
            expand=True,
            bgcolor="#000000CC",
            alignment=ft.Alignment(0, 0),
            content=card,
        )
        _overlay_ref.clear()
        _overlay_ref.append(modal)
        page.overlay.append(modal)
        page.update()

    def _do_generate(force: bool) -> None:
        try:
            pub_b64, _ = _wallet.generate_user_keys(force=force)
            priv_pem = _wallet._KEY_FILE.read_text(encoding="utf-8") if _wallet._KEY_FILE.exists() else ""
            # refresh UI
            pubkey_display.value = pub_b64
            key_status_icon.name = ft.Icons.VERIFIED_OUTLINED
            key_status_icon.color = "#22C55E"
            key_status_text.value = "Wallet keys generated — ready to upload"
            key_status_text.color = "#22C55E"
            download_btn.disabled = False
            page.update()
            _show_download_overlay(pub_b64, priv_pem)
        except Exception as exc:
            app.show_message(f"Key generation failed: {exc}", error=True)

    def handle_generate(_: ft.ControlEvent) -> None:
        threading.Thread(target=_do_generate, args=(False,), daemon=True).start()

    def handle_regenerate(_: ft.ControlEvent) -> None:
        threading.Thread(target=_do_generate, args=(True,), daemon=True).start()

    def handle_download(_: ft.ControlEvent) -> None:
        try:
            pub_b64 = _wallet.get_public_key_base64()
            priv_pem = _wallet._KEY_FILE.read_text(encoding="utf-8") if _wallet._KEY_FILE.exists() else "(key file not found)"
            _show_download_overlay(pub_b64, priv_pem)
        except Exception as exc:
            app.show_message(f"Could not load keys: {exc}", error=True)

    generate_btn.on_click = handle_generate
    regenerate_btn.on_click = handle_regenerate
    download_btn.on_click = handle_download

    wallet_controls = [
        ft.Row(
            controls=[key_status_icon, key_status_text],
            vertical_alignment=ft.CrossAxisAlignment.CENTER,
        ),
    ]
    if has_key:
        wallet_controls += [
            pubkey_display,
            ft.Row(spacing=10, controls=[download_btn, regenerate_btn]),
        ]
    else:
        wallet_controls += [
            ft.Text(
                "You need a wallet key pair to upload assets to Aurex.\n"
                "Your private key stays on your device — the server only stores your public key.",
                color=AUREX_MUTED,
                size=13,
            ),
            generate_btn,
        ]

    return ft.View(
        route="/settings",
        bgcolor=AUREX_BG,
        scroll=ft.ScrollMode.AUTO,
        controls=[
            ft.Container(
                expand=True,
                padding=24,
                content=ft.Column(
                    spacing=18,
                    controls=[
                        ft.Row(
                            alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
                            controls=[
                                ft.Text("Settings", size=26, weight=ft.FontWeight.BOLD),
                                ft.IconButton(
                                    icon=ft.Icons.CLOSE,
                                    on_click=lambda _: page.run_task(page.push_route, "/marketplace"),
                                ),
                            ],
                        ),
                        # ── Profile ──
                        ft.Container(
                            padding=20,
                            border_radius=20,
                            bgcolor=AUREX_CARD,
                            border=ft.border.all(1, AUREX_SLATE),
                            content=ft.Column(
                                spacing=12,
                                controls=[
                                    ft.Text("User Profile", weight=ft.FontWeight.BOLD),
                                    ft.Text(f"Username: {user.username if user else 'Guest'}"),
                                    ft.Text(f"Email: {user.email if user else '—'}", color=AUREX_MUTED),
                                ],
                            ),
                        ),
                        # ── Wallet ──
                        ft.Container(
                            padding=20,
                            border_radius=20,
                            bgcolor=AUREX_CARD,
                            border=ft.border.all(1, AUREX_SLATE),
                            content=ft.Column(
                                spacing=14,
                                controls=[
                                    ft.Row(
                                        controls=[
                                            ft.Icon(ft.Icons.ACCOUNT_BALANCE_WALLET_OUTLINED, color=AUREX_GOLD),
                                            ft.Text("Wallet & Identity", weight=ft.FontWeight.BOLD),
                                        ],
                                    ),
                                    *wallet_controls,
                                ],
                            ),
                        ),
                        # ── Connection ──
                        ft.Container(
                            padding=20,
                            border_radius=20,
                            bgcolor=AUREX_CARD,
                            border=ft.border.all(1, AUREX_SLATE),
                            content=ft.Column(
                                spacing=12,
                                controls=[
                                    ft.Text("Server Connection", weight=ft.FontWeight.BOLD),
                                    host_field,
                                    port_field,
                                    ft.FilledButton(
                                        content="Save Connection",
                                        bgcolor=AUREX_GOLD,
                                        color="#1A1A1B",
                                        on_click=save_connection,
                                    ),
                                ],
                            ),
                        ),
                        # ── Session ──
                        ft.Container(
                            padding=20,
                            border_radius=20,
                            bgcolor=AUREX_CARD,
                            border=ft.border.all(1, AUREX_SLATE),
                            content=ft.Column(
                                spacing=12,
                                controls=[
                                    ft.Text("Session", weight=ft.FontWeight.BOLD),
                                    ft.FilledButton(
                                        content="Logout",
                                        icon=ft.Icons.LOGOUT,
                                        on_click=lambda _: app.logout(),
                                    ),
                                ],
                            ),
                        ),
                    ],
                ),
            )
        ],
    )
