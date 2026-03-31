from __future__ import annotations

import os
import threading
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Callable

import flet as ft

from .wallet import canonical_tx_message, generate_tx_id, get_public_key_base64, sign_message
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


def upload_asset(
    app: "AurexFletApp",
    *,
    file_path: str,
    on_progress: Callable[[float], None] | None = None,
) -> str:
    return app.client.upload_asset_chunked(
        file_path=file_path,
        on_progress=on_progress,
    )


def upload_marketplace_item_binary(
    app: "AurexFletApp",
    *,
    file_path: str,
    asset_name: str,
    description: str,
    username: str,
    file_type: str,
    cost: float,
    on_progress: Callable[[float], None] | None = None,
) -> str:
    asset_hash = app.client.sha256_file(file_path)
    mint_tx_id = generate_tx_id("MINT", username)
    mint_timestamp = datetime.now(timezone.utc).isoformat()
    public_key = get_public_key_base64()
    mint_payload = {
        "action": "asset_mint",
        "tx_id": mint_tx_id,
        "asset_hash": asset_hash,
        "asset_name": asset_name,
        "owner": username,
        "owner_pub": public_key,
        "timestamp": mint_timestamp,
    }
    mint_signature = sign_message(canonical_tx_message(username, mint_payload))
    return app.client.upload_marketplace_item_binary(
        file_path=file_path,
        asset_name=asset_name,
        description=description,
        username=username,
        file_type=file_type,
        cost=cost,
        asset_hash=asset_hash,
        mint_tx_id=mint_tx_id,
        mint_timestamp=mint_timestamp,
        public_key=public_key,
        mint_signature=mint_signature,
        on_progress=on_progress,
    )


def build_upload_view(app: "AurexFletApp") -> ft.View:
    page = app.page

    from . import wallet as _wallet
    if not _wallet._KEY_FILE.exists():
        return ft.View(
            route="/upload",
            bgcolor=AUREX_BG,
            controls=[
                ft.Container(
                    expand=True,
                    padding=40,
                    alignment=ft.Alignment(0, 0),
                    content=ft.Column(
                        horizontal_alignment=ft.CrossAxisAlignment.CENTER,
                        spacing=20,
                        controls=[
                            ft.Icon(ft.Icons.KEY_OFF_OUTLINED, size=64, color=AUREX_GOLD_SOFT),
                            ft.Text(
                                "No Wallet Keys Found",
                                size=24,
                                weight=ft.FontWeight.BOLD,
                            ),
                            ft.Container(
                                padding=20,
                                border_radius=16,
                                bgcolor=AUREX_CARD,
                                border=ft.border.all(1, AUREX_SLATE),
                                content=ft.Column(
                                    spacing=10,
                                    horizontal_alignment=ft.CrossAxisAlignment.CENTER,
                                    controls=[
                                        ft.Text(
                                            "To upload assets on Aurex you need a local Ed25519 key pair.",
                                            text_align=ft.TextAlign.CENTER,
                                            color=AUREX_MUTED,
                                        ),
                                        ft.Text(
                                            "How it works:",
                                            weight=ft.FontWeight.BOLD,
                                        ),
                                        ft.Text(
                                            "1. Go to Settings → Wallet & Identity\n"
                                            "2. Click \"Generate My Keys\"\n"
                                            "3. Save the backup JSON somewhere safe\n"
                                            "4. Your Private Key stays on your device only\n"
                                            "5. The server stores only your Public Key\n"
                                            "6. Every upload is signed — verified by the blockchain nodes",
                                            color=AUREX_MUTED,
                                            size=13,
                                        ),
                                    ],
                                ),
                            ),
                            ft.FilledButton(
                                content="Go to Settings to Generate Keys",
                                bgcolor=AUREX_GOLD,
                                color="#1A1A1B",
                                icon=ft.Icons.SETTINGS,
                                on_click=lambda _: page.run_task(page.push_route, "/settings"),
                            ),
                            ft.TextButton(
                                content="Back to Marketplace",
                                on_click=lambda _: page.run_task(page.push_route, "/marketplace"),
                            ),
                        ],
                    ),
                )
            ],
        )

    selected_path: str | None = None
    selected_ext: str | None = None

    picker = next((c for c in page.overlay if isinstance(c, ft.FilePicker)), None)
    if picker is None:
        picker = ft.FilePicker()
        page.overlay.append(picker)
        page.update()

    file_name_text = ft.Text("No file selected", color=AUREX_MUTED, size=12)
    name_field = ft.TextField(label="Asset Name", border_radius=16)
    description_field = ft.TextField(
        label="Description",
        border_radius=16,
        multiline=True,
        min_lines=3,
        max_lines=4,
    )
    price_field = ft.TextField(label="Price (USD)", border_radius=16)
    status_text = ft.Text(color=AUREX_MUTED, size=12, visible=False)
    progress = ft.ProgressBar(value=0, visible=False, color=AUREX_GOLD)

    def set_status(message: str, *, show: bool = True) -> None:
        status_text.value = message
        status_text.visible = show
        page.update()

    def set_busy(is_busy: bool) -> None:
        for control in (name_field, description_field, price_field, pick_button, upload_button):
            control.disabled = is_busy
        progress.visible = is_busy
        page.update()

    async def pick_file_async(_: ft.ControlEvent) -> None:
        nonlocal selected_path, selected_ext
        files = await picker.pick_files(
            allow_multiple=False,
            allowed_extensions=["jpg", "jpeg", "png"],
        )
        if not files:
            return
        file = files[0]
        if not file.path:
            return
        extension = os.path.splitext(file.path)[1].lower().lstrip(".")
        if extension not in {"jpg", "jpeg", "png"}:
            app.show_message("Only JPG and PNG images are supported", error=True)
            return
        selected_path = file.path
        selected_ext = "jpg" if extension == "jpeg" else extension
        file_name_text.value = os.path.basename(file.path)
        page.update()

    def pick_file(e: ft.ControlEvent) -> None:
        page.run_task(pick_file_async, e)

    def handle_upload(_: ft.ControlEvent) -> None:
        nonlocal selected_path, selected_ext
        if not app.session.is_authenticated:
            app.show_message("Please log in before uploading", error=True)
            return
        if not selected_path:
            app.show_message("Select an image first", error=True)
            return
        asset_name = name_field.value.strip()
        if not asset_name:
            app.show_message("Asset name is required", error=True)
            return
        try:
            price = float(price_field.value.strip())
        except Exception:
            price = 0.0
        if price <= 0:
            app.show_message("Enter a valid price", error=True)
            return
        username = app.session.user_data.username if app.session.user_data else ""
        description = description_field.value.strip()

        def worker() -> None:
            try:
                set_busy(True)
                set_status("Preparing upload...")
                app.connect_if_needed(discover_first=False)

                def on_progress(value: float) -> None:
                    progress.value = value
                    page.update()

                result = upload_marketplace_item_binary(
                    app,
                    file_path=selected_path,
                    asset_name=asset_name,
                    description=description,
                    username=username,
                    file_type=selected_ext or "jpg",
                    cost=price,
                    on_progress=on_progress,
                )
                if result == "success":
                    set_status("Upload complete.", show=True)
                    app.load_marketplace_async(reset=True)
                    app.show_message("Asset uploaded successfully")
                    page.run_task(page.push_route, "/marketplace")
                else:
                    app.show_message(f"Upload failed: {result}", error=True)
            except Exception as exc:
                app.show_message(f"Upload failed: {exc}", error=True)
            finally:
                set_busy(False)

        threading.Thread(target=worker, daemon=True).start()

    pick_button = ft.OutlinedButton(
        content="Choose Image",
        icon=ft.Icons.CLOUD_UPLOAD_OUTLINED,
        on_click=pick_file,
    )
    upload_button = ft.FilledButton(
        content="Upload Asset",
        bgcolor=AUREX_GOLD,
        color="#1A1A1B",
        on_click=handle_upload,
    )

    return ft.View(
        route="/upload",
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
                            controls=[
                                ft.Text("Upload Asset", size=26, weight=ft.FontWeight.BOLD),
                                ft.IconButton(
                                    icon=ft.Icons.CLOSE,
                                    on_click=lambda _: page.run_task(page.push_route, "/marketplace"),
                                ),
                            ],
                        ),
                        ft.Container(
                            padding=20,
                            border_radius=20,
                            bgcolor=AUREX_CARD,
                            border=ft.border.all(1, AUREX_SLATE),
                            content=ft.Column(
                                spacing=14,
                                controls=[
                                    name_field,
                                    description_field,
                                    price_field,
                                    ft.Row(
                                        alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
                                        controls=[file_name_text, pick_button],
                                    ),
                                    progress,
                                    status_text,
                                    upload_button,
                                ],
                            ),
                        ),
                        ft.Container(
                            padding=16,
                            border_radius=18,
                            bgcolor="#101216",
                            border=ft.border.all(1, AUREX_SLATE),
                            content=ft.Row(
                                controls=[
                                    ft.Icon(ft.Icons.INFO_OUTLINE, color=AUREX_GOLD_SOFT),
                                    ft.Text(
                                        "JPG and PNG files only. Metadata is signed using your wallet keys.",
                                        color=AUREX_MUTED,
                                        size=12,
                                    ),
                                ],
                            ),
                        ),
                    ],
                ),
            )
        ],
    )
