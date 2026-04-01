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
from . import notifications as _notif

if TYPE_CHECKING:
    from .app import AurexFletApp


# NOTE: upload_asset(file_path=...) was removed — it called upload_asset_chunked
# which sent UPLOAD_START (no server handler). Desktop uploads also go through
# upload_marketplace_item_from_bytes by reading the file into bytes first.


def _sha256_bytes(data: bytes) -> str:
    import hashlib
    return hashlib.sha256(data).hexdigest()


def upload_marketplace_item_from_bytes(
    app: "AurexFletApp",
    *,
    file_bytes: bytes,
    file_name: str,
    asset_name: str,
    description: str,
    username: str,
    file_type: str,
    cost: float,
    on_progress: Callable[[float], None] | None = None,
) -> str:
    asset_hash = _sha256_bytes(file_bytes)
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
    return app.client.upload_marketplace_item_from_bytes(
        file_bytes=file_bytes,
        file_name=file_name,
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

    # ── state held in closures ────────────────────────────────────────────────
    selected_bytes: list[bytes] = []     # [0] = raw file bytes when chosen
    selected_name: list[str]  = []       # [0] = original filename
    selected_ext:  list[str]  = []       # [0] = 'jpg' or 'png'

    file_name_text = ft.Text("No file selected", color=AUREX_MUTED, size=12)
    preview_image = ft.Image(
        src="",          # required by Flet; set to data URI in on_file_picked
        visible=False,
        width=200, height=140,
        fit=ft.BoxFit.COVER,
        border_radius=10,
    )
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

    def set_status(message: str, *, error: bool = False, show: bool = True) -> None:
        status_text.value = message
        status_text.color = "#EF4444" if error else AUREX_MUTED
        status_text.visible = show
        page.update()

    def set_busy(is_busy: bool) -> None:
        for control in (name_field, description_field, price_field, pick_button, upload_button):
            control.disabled = is_busy
        progress.visible = is_busy
        page.update()

    def on_file_picked(e: ft.FilePickerResultEvent) -> None:
        if not e.files:
            return
        f = e.files[0]
        name = f.name or ""
        extension = os.path.splitext(name)[1].lower().lstrip(".")
        if extension not in {"jpg", "jpeg", "png"}:
            app.show_message("Only JPG and PNG images are supported", error=True)
            return

        # Web mode: f.path is empty; bytes come via f.bytes (base64 str in Flet web)
        raw: bytes | None = None
        if f.path and os.path.isfile(f.path):
            with open(f.path, "rb") as fh:
                raw = fh.read()
        elif hasattr(f, "bytes") and f.bytes:
            import base64 as _b64
            try:
                raw = _b64.b64decode(f.bytes) if isinstance(f.bytes, str) else bytes(f.bytes)
            except Exception:
                raw = bytes(f.bytes) if f.bytes else None

        if not raw:
            app.show_message("Could not read file data — try a different browser", error=True)
            return

        ext = "jpg" if extension == "jpeg" else extension
        selected_bytes.clear(); selected_bytes.append(raw)
        selected_name.clear();  selected_name.append(name)
        selected_ext.clear();   selected_ext.append(ext)

        file_name_text.value = name
        file_name_text.color = AUREX_TEXT

        # Show inline preview
        import base64 as _b64
        mime = "image/png" if ext == "png" else "image/jpeg"
        preview_image.src = f"data:{mime};base64,{_b64.b64encode(raw).decode()}"
        preview_image.visible = True
        page.update()

    # Create picker but do NOT add to overlay yet — only add right before use
    # so it never appears as a stray "unknown control" on other pages.
    # NOTE: on_result must be set as attribute, not constructor kwarg (Flet compat).
    picker = ft.FilePicker()
    picker.on_result = on_file_picked

    def pick_file(_: ft.ControlEvent) -> None:
        # Add picker to overlay only if not already present
        if picker not in page.overlay:
            page.overlay.append(picker)
            page.update()
        picker.pick_files(
            dialog_title="Choose image to upload",
            allow_multiple=False,
            allowed_extensions=["jpg", "jpeg", "png"],
        )

    def handle_upload(_: ft.ControlEvent) -> None:
        if not app.session.is_authenticated:
            app.show_message("Please log in before uploading", error=True)
            return
        if not selected_bytes:
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
        file_bytes_snap = selected_bytes[0]
        file_name_snap  = selected_name[0] if selected_name else "asset.jpg"
        file_ext_snap   = selected_ext[0]  if selected_ext  else "jpg"

        def worker() -> None:
            try:
                set_busy(True)
                set_status("Connecting to server…")
                app.connect_if_needed(discover_first=False)
                set_status(f"Uploading {len(file_bytes_snap):,} bytes…")

                def on_progress(value: float) -> None:
                    progress.value = value
                    pct = int(value * 100)
                    set_status(f"Uploading… {pct}%")

                result = upload_marketplace_item_from_bytes(
                    app,
                    file_bytes=file_bytes_snap,
                    file_name=file_name_snap,
                    asset_name=asset_name,
                    description=description,
                    username=username,
                    file_type=file_ext_snap,
                    cost=price,
                    on_progress=on_progress,
                )
                if result == "success":
                    set_status("Upload complete! ✓")
                    app.load_marketplace_async(reset=True)
                    _notif.push_notification(
                        title="Asset sent to blockchain",
                        body=(
                            f"\u201c{asset_name}\u201d has been uploaded and submitted to the "
                            "PoW nodes for authentication (MINT). "
                            "Check back here for confirmation."
                        ),
                        notif_type="blockchain",
                    )
                    page.run_task(_show_blockchain_popup, asset_name)
                else:
                    set_status(f"Upload failed: {result}", error=True)
                    app.show_message(f"Upload failed: {result}", error=True)
            except Exception as exc:
                set_status(f"Error: {exc}", error=True)
                app.show_message(f"Upload failed: {exc}", error=True)
            finally:
                set_busy(False)

        async def _show_blockchain_popup(name: str) -> None:
            """Show a modal confirming the asset was sent to the blockchain."""
            _ref: list = []

            def _close(_: ft.ControlEvent) -> None:
                if _ref:
                    try:
                        page.overlay.remove(_ref[0])
                    except ValueError:
                        pass
                    _ref.clear()
                    page.update()
                page.run_task(page.push_route, "/marketplace")

            def _go_notif(_: ft.ControlEvent) -> None:
                if _ref:
                    try:
                        page.overlay.remove(_ref[0])
                    except ValueError:
                        pass
                    _ref.clear()
                    page.update()
                page.run_task(page.push_route, "/notifications")

            card = ft.Container(
                width=480,
                bgcolor=AUREX_CARD,
                border_radius=24,
                border=ft.border.all(1, "#2B2F36"),
                shadow=ft.BoxShadow(spread_radius=2, blur_radius=48, color="#000000CC"),
                padding=0,
                content=ft.Column(
                    spacing=0,
                    controls=[
                        # ── top accent strip ──────────────────────────────
                        ft.Container(
                            height=6,
                            border_radius=ft.border_radius.only(top_left=24, top_right=24),
                            bgcolor=AUREX_GOLD,
                        ),
                        # ── body ─────────────────────────────────────────
                        ft.Container(
                            padding=ft.padding.symmetric(horizontal=32, vertical=28),
                            content=ft.Column(
                                spacing=20,
                                horizontal_alignment=ft.CrossAxisAlignment.CENTER,
                                controls=[
                                    ft.Container(
                                        width=72, height=72,
                                        border_radius=36,
                                        bgcolor="#FFD70020",
                                        alignment=ft.Alignment(0, 0),
                                        content=ft.Icon(
                                            ft.Icons.CURRENCY_BITCOIN,
                                            size=36, color=AUREX_GOLD,
                                        ),
                                    ),
                                    ft.Text(
                                        "Sent to Blockchain!",
                                        size=20,
                                        weight=ft.FontWeight.BOLD,
                                        text_align=ft.TextAlign.CENTER,
                                    ),
                                    ft.Container(
                                        padding=ft.padding.symmetric(horizontal=16, vertical=12),
                                        border_radius=14,
                                        bgcolor="#101216",
                                        border=ft.border.all(1, "#2B2F36"),
                                        content=ft.Column(
                                            spacing=8,
                                            horizontal_alignment=ft.CrossAxisAlignment.CENTER,
                                            controls=[
                                                ft.Text(
                                                    f"\u201c{name}\u201d",
                                                    size=14,
                                                    weight=ft.FontWeight.W_600,
                                                    color=AUREX_GOLD_SOFT,
                                                    text_align=ft.TextAlign.CENTER,
                                                ),
                                                ft.Text(
                                                    "Your image has been uploaded and submitted "
                                                    "to the PoW nodes for blockchain authentication (MINT).",
                                                    size=13,
                                                    color=AUREX_MUTED,
                                                    text_align=ft.TextAlign.CENTER,
                                                ),
                                            ],
                                        ),
                                    ),
                                    ft.Row(
                                        spacing=6,
                                        alignment=ft.MainAxisAlignment.CENTER,
                                        controls=[
                                            ft.Icon(
                                                ft.Icons.INFO_OUTLINE,
                                                size=14, color=AUREX_GOLD_SOFT,
                                            ),
                                            ft.Text(
                                                "We'll update you in the Notifications page once confirmed.",
                                                size=12,
                                                color=AUREX_MUTED,
                                                text_align=ft.TextAlign.CENTER,
                                            ),
                                        ],
                                    ),
                                    ft.Row(
                                        spacing=10,
                                        alignment=ft.MainAxisAlignment.CENTER,
                                        controls=[
                                            ft.FilledButton(
                                                content="Go to Marketplace",
                                                icon=ft.Icons.STOREFRONT_OUTLINED,
                                                style=ft.ButtonStyle(
                                                    bgcolor=AUREX_GOLD,
                                                    color="#1A1A1B",
                                                    shape=ft.RoundedRectangleBorder(radius=12),
                                                ),
                                                on_click=_close,
                                            ),
                                            ft.OutlinedButton(
                                                content="View Notifications",
                                                icon=ft.Icons.NOTIFICATIONS_OUTLINED,
                                                style=ft.ButtonStyle(
                                                    shape=ft.RoundedRectangleBorder(radius=12),
                                                ),
                                                on_click=_go_notif,
                                            ),
                                        ],
                                    ),
                                ],
                            ),
                        ),
                    ],
                ),
            )

            modal = ft.Container(
                expand=True,
                bgcolor="#000000BB",
                alignment=ft.Alignment(0, 0),
                content=card,
            )
            _ref.append(modal)
            page.overlay.append(modal)
            page.update()

        threading.Thread(target=worker, daemon=True).start()

    pick_button = ft.OutlinedButton(
        content="Choose Image",
        icon=ft.Icons.IMAGE_OUTLINED,
        style=ft.ButtonStyle(shape=ft.RoundedRectangleBorder(radius=12)),
        on_click=pick_file,
    )
    upload_button = ft.FilledButton(
        content="Upload to Blockchain",
        icon=ft.Icons.CLOUD_UPLOAD_OUTLINED,
        style=ft.ButtonStyle(
            bgcolor=AUREX_GOLD,
            color="#1A1A1B",
            shape=ft.RoundedRectangleBorder(radius=12),
        ),
        on_click=handle_upload,
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
                            ft.Icon(ft.Icons.CLOUD_UPLOAD_OUTLINED, color=AUREX_GOLD, size=26),
                            ft.Text("Upload Asset", size=26, weight=ft.FontWeight.BOLD),
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
            # ── form card ────────────────────────────────────────────────────
            ft.Container(
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
                                ft.Icon(ft.Icons.DRIVE_FILE_RENAME_OUTLINE, color=AUREX_GOLD, size=18),
                                ft.Text("Asset Details", size=15, weight=ft.FontWeight.BOLD),
                            ],
                        ),
                        ft.Divider(height=1, color=AUREX_SLATE),
                        name_field,
                        description_field,
                        price_field,
                        ft.Row(
                            alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
                            vertical_alignment=ft.CrossAxisAlignment.CENTER,
                            controls=[
                                ft.Row(
                                    spacing=8,
                                    vertical_alignment=ft.CrossAxisAlignment.CENTER,
                                    controls=[
                                        ft.Icon(ft.Icons.IMAGE_OUTLINED, color=AUREX_MUTED, size=16),
                                        file_name_text,
                                    ],
                                ),
                                pick_button,
                            ],
                        ),
                        preview_image,
                        progress,
                        status_text,
                        upload_button,
                    ],
                ),
            ),
            # ── info strip ───────────────────────────────────────────────────
            ft.Container(
                padding=ft.padding.symmetric(horizontal=16, vertical=12),
                border_radius=14,
                bgcolor="#101216",
                border=ft.border.all(1, AUREX_SLATE),
                content=ft.Row(
                    spacing=10,
                    vertical_alignment=ft.CrossAxisAlignment.CENTER,
                    controls=[
                        ft.Icon(ft.Icons.INFO_OUTLINE, color=AUREX_GOLD_SOFT, size=16),
                        ft.Text(
                            "JPG and PNG only. Metadata is signed using your wallet keys and "
                            "submitted to the blockchain for authentication (MINT).",
                            color=AUREX_MUTED,
                            size=12,
                        ),
                    ],
                ),
            ),
        ],
    )

    return ft.View(
        route="/upload",
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
