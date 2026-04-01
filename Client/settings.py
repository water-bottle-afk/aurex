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
        icon=ft.Icons.KEY,
        style=ft.ButtonStyle(
            bgcolor=AUREX_GOLD,
            color="#1A1A1B",
            shape=ft.RoundedRectangleBorder(radius=12),
        ),
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

    # ── inline status label shown inside the wallet section ─────────────────
    wallet_status_label = ft.Text(
        "",
        size=12,
        visible=False,
        color="#22C55E",
    )

    def _set_wallet_status(msg: str, *, error: bool = False) -> None:
        wallet_status_label.value = msg
        wallet_status_label.color = "#EF4444" if error else "#22C55E"
        wallet_status_label.visible = bool(msg)
        page.update()

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
                                            icon=ft.Icons.CHECK_CIRCLE_OUTLINE,
                                            style=ft.ButtonStyle(
                                                bgcolor=AUREX_GOLD,
                                                color="#1A1A1B",
                                                shape=ft.RoundedRectangleBorder(radius=12),
                                            ),
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

    def _write_key_backup() -> None:
        """Write aurex_keys_backup.json directly to ~/Downloads."""
        try:
            pub_b64 = _wallet.get_public_key_base64()
            priv_pem = _wallet._KEY_FILE.read_text(encoding="utf-8") if _wallet._KEY_FILE.exists() else ""
            payload = json.dumps({"public_key": pub_b64, "private_key_pem": priv_pem}, indent=2)
            dest = Path.home() / "Downloads" / "aurex_keys_backup.json"
            dest.write_text(payload, encoding="utf-8")
            _set_wallet_status(f"Backup saved: {dest}")
            app.show_message(f"Keys saved to Downloads/aurex_keys_backup.json")
        except Exception as exc:
            _set_wallet_status(f"Save failed: {exc}", error=True)
            app.show_message(f"Save failed: {exc}", error=True)


    def _do_generate(force: bool) -> None:
        try:
            _set_wallet_status("Generating keys…")
            pub_b64, key_path = _wallet.generate_user_keys(force=force)
            priv_pem = _wallet._KEY_FILE.read_text(encoding="utf-8") if _wallet._KEY_FILE.exists() else ""

            # push new public key to server so signatures keep working
            server_sync_msg = ""
            if force and app.session.is_authenticated and app.session.user_data:
                try:
                    ok = app.client.update_public_key(app.session.user_data.username, pub_b64)
                    server_sync_msg = " — new public key synced to server" if ok else " — server sync failed (try reconnecting)"
                except Exception as sync_err:
                    server_sync_msg = f" — server sync error: {sync_err}"

            # refresh UI controls
            pubkey_display.value = pub_b64
            key_status_icon.name = ft.Icons.VERIFIED_OUTLINED
            key_status_icon.color = "#22C55E"
            key_status_text.value = "Wallet keys generated — ready to upload"
            key_status_text.color = "#22C55E"
            download_btn.disabled = False

            action = "regenerated" if force else "generated"
            _set_wallet_status(
                f"Keys {action}. Saved to: {key_path}{server_sync_msg}"
            )
            app.show_message(
                f"Keys {action}! Saved to {key_path}{server_sync_msg}",
                error=bool(server_sync_msg and "fail" in server_sync_msg),
            )
            page.update()
            _show_download_overlay(pub_b64, priv_pem)
        except Exception as exc:
            _set_wallet_status(f"Key generation failed: {exc}", error=True)
            app.show_message(f"Key generation failed: {exc}", error=True)

    # ── danger dialog for key regeneration ───────────────────────────────────
    _regen_dialog_ref: list[ft.Control] = []

    def _dismiss_regen_dialog() -> None:
        if _regen_dialog_ref:
            try:
                page.overlay.remove(_regen_dialog_ref[0])
            except ValueError:
                pass
            _regen_dialog_ref.clear()
            page.update()

    def _show_regen_danger_dialog() -> None:
        def _confirm(_: ft.ControlEvent) -> None:
            _dismiss_regen_dialog()
            threading.Thread(target=_do_generate, args=(True,), daemon=True).start()

        def _cancel(_: ft.ControlEvent) -> None:
            _dismiss_regen_dialog()

        card = ft.Container(
            width=460,
            bgcolor=AUREX_CARD,
            border_radius=20,
            border=ft.border.all(2, "#EF4444"),
            shadow=ft.BoxShadow(spread_radius=2, blur_radius=40, color="#000000BB"),
            padding=ft.padding.symmetric(horizontal=28, vertical=24),
            content=ft.Column(
                spacing=18,
                controls=[
                    ft.Row(
                        spacing=10,
                        vertical_alignment=ft.CrossAxisAlignment.CENTER,
                        controls=[
                            ft.Icon(ft.Icons.WARNING_ROUNDED, color="#EF4444", size=28),
                            ft.Text("Regenerate Keys?", size=20, weight=ft.FontWeight.BOLD, color="#EF4444"),
                        ],
                    ),
                    ft.Container(
                        padding=14,
                        border_radius=12,
                        bgcolor="#1A1D24",
                        border=ft.border.all(1, "#EF444460"),
                        content=ft.Column(
                            spacing=6,
                            controls=[
                                ft.Text(
                                    "⚠  This will permanently replace your current key pair.",
                                    color="#EF4444",
                                    weight=ft.FontWeight.BOLD,
                                    size=13,
                                ),
                                ft.Text(
                                    "• Any assets signed with your OLD key will no longer be "
                                    "verifiable by you.\n"
                                    "• You will LOSE the ability to sell or transfer assets \n"
                                    "  that were minted with the old key.\n"
                                    "• Your new public key will be sent to the server.\n"
                                    "• Make sure you have a backup of your old key first.",
                                    color=AUREX_MUTED,
                                    size=12,
                                ),
                            ],
                        ),
                    ),
                    ft.Row(
                        spacing=12,
                        controls=[
                            ft.FilledButton(
                                content="Cancel",
                                icon=ft.Icons.CLOSE,
                                style=ft.ButtonStyle(
                                    bgcolor="#2B2F36",
                                    color=AUREX_TEXT,
                                    shape=ft.RoundedRectangleBorder(radius=12),
                                ),
                                expand=True,
                                on_click=_cancel,
                            ),
                            ft.FilledButton(
                                content="Yes, Regenerate",
                                icon=ft.Icons.REFRESH,
                                style=ft.ButtonStyle(
                                    bgcolor="#EF4444",
                                    color="white",
                                    shape=ft.RoundedRectangleBorder(radius=12),
                                ),
                                expand=True,
                                on_click=_confirm,
                            ),
                        ],
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
        _regen_dialog_ref.clear()
        _regen_dialog_ref.append(modal)
        page.overlay.append(modal)
        page.update()

    def handle_generate(_: ft.ControlEvent) -> None:
        threading.Thread(target=_do_generate, args=(False,), daemon=True).start()

    def handle_regenerate(_: ft.ControlEvent) -> None:
        _show_regen_danger_dialog()

    def handle_download(_: ft.ControlEvent) -> None:
        threading.Thread(target=_write_key_backup, daemon=True).start()

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
            wallet_status_label,
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
            wallet_status_label,
        ]

    def _section(title: str, icon: str, controls: list) -> ft.Container:
        return ft.Container(
            padding=ft.padding.symmetric(horizontal=24, vertical=20),
            border_radius=20,
            bgcolor=AUREX_CARD,
            border=ft.border.all(1, AUREX_SLATE),
            content=ft.Column(
                spacing=14,
                controls=[
                    ft.Row(
                        spacing=10,
                        vertical_alignment=ft.CrossAxisAlignment.CENTER,
                        controls=[
                            ft.Icon(icon, color=AUREX_GOLD, size=18),
                            ft.Text(title, size=15, weight=ft.FontWeight.BOLD),
                        ],
                    ),
                    ft.Divider(height=1, color=AUREX_SLATE),
                    *controls,
                ],
            ),
        )

    inner = ft.Column(
        spacing=20,
        controls=[
            # ── top bar ──────────────────────────────────────────────────────
            ft.Row(
                alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
                vertical_alignment=ft.CrossAxisAlignment.CENTER,
                controls=[
                    ft.Row(
                        spacing=10,
                        vertical_alignment=ft.CrossAxisAlignment.CENTER,
                        controls=[
                            ft.Icon(ft.Icons.SETTINGS_OUTLINED, color=AUREX_GOLD, size=26),
                            ft.Text("Settings", size=26, weight=ft.FontWeight.BOLD),
                        ],
                    ),
                    ft.IconButton(
                        icon=ft.Icons.ARROW_BACK_IOS_NEW_ROUNDED,
                        icon_color=AUREX_MUTED,
                        tooltip="Back to Marketplace",
                        on_click=lambda _: page.run_task(page.push_route, "/marketplace"),
                    ),
                ],
            ),
            # ── Profile ──────────────────────────────────────────────────────
            _section(
                "User Profile", ft.Icons.PERSON_OUTLINE,
                [
                    ft.Row(
                        spacing=12,
                        vertical_alignment=ft.CrossAxisAlignment.CENTER,
                        controls=[
                            ft.Container(
                                width=48, height=48,
                                border_radius=24,
                                bgcolor=AUREX_SLATE,
                                alignment=ft.Alignment(0, 0),
                                content=ft.Text(
                                    (user.username[0].upper() if user and user.username else "?"),
                                    size=20, weight=ft.FontWeight.BOLD, color=AUREX_GOLD,
                                ),
                            ),
                            ft.Column(
                                spacing=2,
                                controls=[
                                    ft.Text(
                                        user.username if user else "Guest",
                                        size=15, weight=ft.FontWeight.W_600,
                                    ),
                                    ft.Text(
                                        user.email if user else "—",
                                        size=12, color=AUREX_MUTED,
                                    ),
                                ],
                            ),
                        ],
                    ),
                ],
            ),
            # ── Wallet ───────────────────────────────────────────────────────
            _section(
                "Wallet & Identity", ft.Icons.ACCOUNT_BALANCE_WALLET_OUTLINED,
                wallet_controls,
            ),
            # ── Connection ───────────────────────────────────────────────────
            _section(
                "Server Connection", ft.Icons.DNS_OUTLINED,
                [
                    host_field,
                    port_field,
                    ft.FilledButton(
                        content="Save Connection",
                        icon=ft.Icons.SAVE_OUTLINED,
                        style=ft.ButtonStyle(
                            bgcolor=AUREX_GOLD,
                            color="#1A1A1B",
                            shape=ft.RoundedRectangleBorder(radius=12),
                        ),
                        on_click=save_connection,
                    ),
                ],
            ),
            # ── Session ──────────────────────────────────────────────────────
            _section(
                "Session", ft.Icons.MANAGE_ACCOUNTS_OUTLINED,
                [
                    ft.Row(
                        spacing=12,
                        controls=[
                            ft.FilledButton(
                                content="Logout",
                                icon=ft.Icons.LOGOUT,
                                style=ft.ButtonStyle(
                                    bgcolor="#EF4444",
                                    color="white",
                                    shape=ft.RoundedRectangleBorder(radius=12),
                                ),
                                on_click=lambda _: app.logout(),
                            ),
                            ft.OutlinedButton(
                                content="Notifications",
                                icon=ft.Icons.NOTIFICATIONS_OUTLINED,
                                style=ft.ButtonStyle(
                                    shape=ft.RoundedRectangleBorder(radius=12),
                                ),
                                on_click=lambda _: page.run_task(page.push_route, "/notifications"),
                            ),
                        ],
                    ),
                ],
            ),
        ],
    )

    return ft.View(
        route="/settings",
        bgcolor=AUREX_BG,
        scroll=ft.ScrollMode.AUTO,
        controls=[
            ft.Container(
                expand=True,
                padding=ft.padding.symmetric(vertical=32, horizontal=24),
                alignment=ft.Alignment(0, -1),
                content=ft.Container(
                    width=640,
                    content=inner,
                ),
            ),
        ],
    )
