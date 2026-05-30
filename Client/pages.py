"""Elegant Aurex UI pages (UI-only)."""
from __future__ import annotations
import flet as ft
import logging
import threading
import time
from pathlib import Path

_logger = logging.getLogger("aurex.pages")

BG = "#090B0F"
SCRIM = "#C814161B"
CARD = "#0E1016"
CARD_SOFT = "#0B0D11"
BORDER = "#4A3620"
BORDER_DIM = "#1E2030"
TEXT = "#F3F6FA"
MUTED = "#7A8799"
GOLD = "#E9BD4B"
GOLD_SOFT = "#F4D78A"
GOLD_DIM = "#B8922A"
SUCCESS = "#3FB170"
ERROR = "#D05757"
GLASS = "#BF080B11"

_GLOW = [ft.BoxShadow(blur_radius=40, spread_radius=-4, color="#55E9BD4B", offset=ft.Offset(0, 8))]
_SHADOW = [ft.BoxShadow(blur_radius=16, color="#50000000", offset=ft.Offset(0, 4))]


def _bg(content):
    return ft.Container(expand=True,
        image=ft.DecorationImage(src="images/gold_bg.png", fit=ft.BoxFit.COVER),
        content=ft.Container(expand=True, bgcolor=SCRIM, content=content))


def _logo_block(title="AUREX"):
    return ft.Column(spacing=8, horizontal_alignment=ft.CrossAxisAlignment.CENTER, controls=[
        ft.Container(padding=12, border_radius=20, bgcolor="#120F00",
            border=ft.border.all(1.5, GOLD_DIM),
            shadow=[ft.BoxShadow(blur_radius=20, color="#60E9BD4B", offset=ft.Offset(0, 0))],
            content=ft.Image(src="images/gold_icon.png", width=52, height=52, fit=ft.BoxFit.CONTAIN)),
        ft.Text(title, size=26, weight=ft.FontWeight.BOLD, color=GOLD, style=ft.TextStyle(letter_spacing=7)),
        ft.Container(width=48, height=1.5, bgcolor=GOLD_DIM, border_radius=2),
    ])


def _divider():
    return ft.Row(spacing=8, controls=[
        ft.Container(expand=True, height=1, bgcolor="#1E1810"),
        ft.Text("◆", color="#3A2C10", size=8),
        ft.Container(expand=True, height=1, bgcolor="#1E1810"),
    ])


def _auth_shell(route, body):
    return ft.View(route=route, bgcolor=BG, padding=0,
        controls=[_bg(ft.Container(expand=True, alignment=ft.Alignment(0, 0), content=body))])


def _nav_btn(app, text, route):
    active = app.page.route == route
    return ft.OutlinedButton(text, on_click=lambda _: app.page.go(route),
        style=ft.ButtonStyle(
            color=GOLD if active else MUTED,
            side=ft.BorderSide(1.5 if active else 1, GOLD if active else "#252535"),
            bgcolor="#1E1800" if active else "#0A0C14",
            shape=ft.RoundedRectangleBorder(radius=9),
            padding=ft.padding.symmetric(horizontal=14, vertical=7),
        ))


def _logout(app):
    try:
        app.logout()
        app.notify("Logged out")
    except Exception as e:
        app.notify(str(e), error=True)
    app.page.go("/login")


def _main_shell(app, route, title, body):
    # Notification button with red badge overlay
    _notif_count = app.state.unseen_notifications
    _badge = ft.Container(
        content=ft.Text(str(min(_notif_count, 99)), color="white", size=8, weight=ft.FontWeight.BOLD,
            text_align=ft.TextAlign.CENTER),
        bgcolor=ERROR,
        width=16, height=16,
        border_radius=8,
        alignment=ft.Alignment(0, 0),
        top=1, right=1,
        visible=_notif_count > 0,
    )
    app._notification_badge = _badge
    _notif_btn = _nav_btn(app, "Notifications", "/notifications")
    _notif_with_badge = ft.Stack(
        controls=[_notif_btn, _badge],
        clip_behavior=ft.ClipBehavior.NONE,
    )

    nav = ft.Row(wrap=True, run_spacing=6, spacing=6, controls=[
        _nav_btn(app, "Market", "/marketplace"),
        _nav_btn(app, "My Assets", "/my_assets"),
        _nav_btn(app, "Upload", "/upload"),
        _nav_btn(app, "Settings", "/settings"),
        _notif_with_badge,
        ft.FilledButton("Logout", bgcolor="#3A0C14", color="#FF8A8A",
            style=ft.ButtonStyle(shape=ft.RoundedRectangleBorder(radius=9), padding=ft.padding.symmetric(horizontal=14, vertical=7)),
            on_click=lambda _: _logout(app)),
    ])
    back_btn = ft.IconButton(icon=ft.Icons.ARROW_BACK_IOS_NEW_ROUNDED, icon_color=GOLD_SOFT, icon_size=15,
        tooltip="Back", visible=route != "/marketplace", on_click=lambda _: app.page.go("/marketplace"))

    # Balance display — reference stored on app so the balance monitor can update it
    balance_text = ft.Text(f"{app.state.balance:.2f} AUR", color=GOLD_SOFT, size=11,
        weight=ft.FontWeight.W_600)
    app._balance_text = balance_text

    head = ft.Container(
        border_radius=16, bgcolor=GLASS, border=ft.border.all(1, "#5C4220"),
        padding=ft.padding.symmetric(horizontal=20, vertical=13), shadow=_SHADOW,
        content=ft.Row(alignment=ft.MainAxisAlignment.SPACE_BETWEEN, vertical_alignment=ft.CrossAxisAlignment.CENTER, controls=[
            ft.Row(spacing=10, controls=[
                back_btn,
                ft.Container(padding=6, border_radius=10, bgcolor="#120F00", border=ft.border.all(1, GOLD_DIM),
                    content=ft.Image(src="images/gold_icon.png", width=26, height=26, fit=ft.BoxFit.CONTAIN)),
                ft.Column(spacing=0, tight=True, controls=[
                    ft.Text("AUREX", color=GOLD, size=17, weight=ft.FontWeight.BOLD, style=ft.TextStyle(letter_spacing=3)),
                    ft.Text(title, color=MUTED, size=11),
                ]),
            ]),
            ft.Row(spacing=12, vertical_alignment=ft.CrossAxisAlignment.CENTER, controls=[
                ft.Container(
                    bgcolor="#0A0C12", border=ft.border.all(1, BORDER_DIM), border_radius=8,
                    padding=ft.padding.symmetric(horizontal=10, vertical=5),
                    content=ft.Row(spacing=5, controls=[
                        ft.Icon(ft.Icons.ACCOUNT_BALANCE_WALLET_OUTLINED, color=GOLD_DIM, size=13),
                        balance_text,
                    ]),
                ),
                nav,
            ]),
        ]))
    return ft.View(route=route, bgcolor=BG, padding=0, controls=[
        _bg(ft.Container(expand=True, padding=ft.padding.symmetric(horizontal=20, vertical=16),
            content=ft.Column(scroll=ft.ScrollMode.AUTO, spacing=12, controls=[head, body])))
    ])


def _input(label, password=False, icon=None):
    return ft.TextField(label=label, password=password, can_reveal_password=password,
        border_radius=11, bgcolor="#060709", border_color="#2E2218",
        focused_border_color=GOLD, color=TEXT, cursor_color=GOLD, text_size=15,
        label_style=ft.TextStyle(color=MUTED, size=14),
        prefix_icon=icon, content_padding=ft.padding.symmetric(horizontal=16, vertical=13))


def build_login_view(app):
    username = _input("Username", icon=ft.Icons.PERSON_OUTLINE_ROUNDED)
    password = _input("Password", True, icon=ft.Icons.LOCK_OUTLINE_ROUNDED)

    def on_login(_):
        try:
            app.login((username.value or "").strip(), password.value or "")
            app.notify("Welcome back")
            app.page.go("/settings")
        except Exception as e:
            app.notify(str(e), error=True)

    card = ft.Container(width=440, padding=ft.padding.symmetric(horizontal=36, vertical=32),
        border_radius=24, bgcolor=CARD, border=ft.border.all(1, BORDER), shadow=_GLOW,
        content=ft.Column(spacing=18, horizontal_alignment=ft.CrossAxisAlignment.CENTER, controls=[
            _logo_block(),
            ft.Text("Secure marketplace access", color=MUTED, size=12, style=ft.TextStyle(letter_spacing=1.5)),
            _divider(),
            username, password,
            ft.FilledButton("Sign In", width=368, height=46, bgcolor=GOLD, color="#130E00",
                style=ft.ButtonStyle(shape=ft.RoundedRectangleBorder(radius=12)), on_click=on_login),
            ft.Row(alignment=ft.MainAxisAlignment.SPACE_BETWEEN, controls=[
                ft.TextButton("Create account", style=ft.ButtonStyle(color=MUTED), on_click=lambda _: app.page.go("/signup")),
                ft.TextButton("Forgot password?", style=ft.ButtonStyle(color=GOLD_DIM), on_click=lambda _: app.page.go("/forgot")),
            ]),
        ]))
    return _auth_shell("/login", card)


def build_signup_view(app):
    username = _input("Username", icon=ft.Icons.PERSON_OUTLINE_ROUNDED)
    password = _input("Password", True, icon=ft.Icons.LOCK_OUTLINE_ROUNDED)
    email = _input("Email address", icon=ft.Icons.EMAIL_OUTLINED)

    def on_signup(_):
        try:
            app.signup((username.value or "").strip(), password.value or "", (email.value or "").strip())
            app.notify("Account created")
            app.page.go("/login")
        except Exception as e:
            app.notify(str(e), error=True)

    card = ft.Container(width=460, padding=ft.padding.symmetric(horizontal=36, vertical=28),
        border_radius=24, bgcolor=CARD, border=ft.border.all(1, BORDER), shadow=_GLOW,
        content=ft.Column(spacing=15, horizontal_alignment=ft.CrossAxisAlignment.CENTER, controls=[
            ft.Row(controls=[ft.IconButton(icon=ft.Icons.ARROW_BACK_IOS_NEW_ROUNDED, icon_color=MUTED, icon_size=15,
                on_click=lambda _: app.page.go("/login"))]),
            _logo_block("JOIN AUREX"),
            username, password, email,
            ft.FilledButton("Create Account", width=388, height=46, bgcolor=GOLD, color="#130E00",
                style=ft.ButtonStyle(shape=ft.RoundedRectangleBorder(radius=12)), on_click=on_signup),
        ]))
    return _auth_shell("/signup", card)


def build_forgot_view(app):
    email = _input("Email address", icon=ft.Icons.EMAIL_OUTLINED)
    code = _input("Verification code", icon=ft.Icons.VERIFIED_OUTLINED)
    new_pass = _input("New password", True, icon=ft.Icons.LOCK_RESET_OUTLINED)

    def do_send(_):
        try:
            app.send_code((email.value or "").strip())
            app.notify("Code sent")
        except Exception as e:
            app.notify(str(e), error=True)

    def do_verify(_):
        try:
            app.verify_code((email.value or "").strip(), (code.value or "").strip())
            app.notify("Code verified")
        except Exception as e:
            app.notify(str(e), error=True)

    def do_reset(_):
        try:
            app.update_password(
                (email.value or "").strip(),
                new_pass.value or "",
                (code.value or "").strip(),
            )
            app.notify("Password updated")
            app.page.go("/login")
        except Exception as e:
            app.notify(str(e), error=True)

    card = ft.Container(width=480, padding=ft.padding.symmetric(horizontal=36, vertical=28),
        border_radius=24, bgcolor=CARD, border=ft.border.all(1, BORDER), shadow=_GLOW,
        content=ft.Column(spacing=14, horizontal_alignment=ft.CrossAxisAlignment.CENTER, controls=[
            ft.Row(controls=[ft.IconButton(icon=ft.Icons.ARROW_BACK_IOS_NEW_ROUNDED, icon_color=MUTED, icon_size=15,
                on_click=lambda _: app.page.go("/login"))]),
            _logo_block("RESET ACCESS"),
            email,
            ft.Row(spacing=8, controls=[
                ft.FilledButton("Send Code", bgcolor="#1C1400", color=GOLD_SOFT, on_click=do_send,
                    style=ft.ButtonStyle(shape=ft.RoundedRectangleBorder(radius=9), side=ft.BorderSide(1, BORDER))),
            ]),
            code,
            ft.FilledButton("Verify Code", bgcolor="#0E1C0E", color=SUCCESS, on_click=do_verify,
                style=ft.ButtonStyle(shape=ft.RoundedRectangleBorder(radius=9), side=ft.BorderSide(1, "#2A4A2A"))),
            new_pass,
            ft.FilledButton("Update Password", width=408, height=44, bgcolor=GOLD, color="#130E00",
                style=ft.ButtonStyle(shape=ft.RoundedRectangleBorder(radius=12)), on_click=do_reset),
        ]))
    return _auth_shell("/forgot", card)


_STATUS_COLOR = {
    "FOR_SALE": SUCCESS,
    "PENDING":  GOLD_DIM,
    "UNLISTED": MUTED,
    "SOLD":     ERROR,
}
_STATUS_LABEL = {
    "FOR_SALE": "For Sale",
    "PENDING":  "Pending",
    "UNLISTED": "Unlisted",
    "SOLD":     "Sold",
}


def _asset_card(app, item, context="marketplace"):
    is_own = item.owner == (app.state.username or "")
    status_color = _STATUS_COLOR.get(item.asset_status, MUTED)
    status_label = _STATUS_LABEL.get(item.asset_status, item.asset_status)

    # ── Action callbacks ────────────────────────────────────────────────────────

    def do_buy(_):
        try:
            app.buy_asset(item)
            app.notify("Purchase request signed and sent")
        except Exception as e:
            app.notify(str(e), error=True)

    def do_upload_to_market(_):
        try:
            resp = app.move_to_marketplace(item.asset_id)
            resp_type = str(resp.get("type", "")).upper()
            if resp_type == "MOVE_PENDING":
                app.notify("Asset sent to mining — will appear on marketplace once confirmed")
            elif resp_type == "MOVE_SUCCESS":
                app.notify("Asset listed on marketplace!")
            app.page.go("/my_assets")
        except Exception as e:
            app.notify(str(e), error=True)

    def do_delete(_):
        try:
            app.delete_asset(item.asset_id)
            app.notify("Asset deleted")
            app.page.go("/my_assets")
        except Exception as e:
            app.notify(str(e), error=True)

    def do_unlist(_):
        try:
            app.unlist_asset(item.asset_id)
            app.notify("Unlist request submitted — will update once confirmed")
            app.page.go("/marketplace")
        except Exception as e:
            app.notify(str(e), error=True)

    def on_hover(e):
        e.control.border = ft.border.all(1, GOLD_DIM if e.data == "true" else BORDER_DIM)
        e.control.shadow = _SHADOW if e.data == "true" else []
        e.control.update()

    type_badge = ft.Container(border_radius=6, bgcolor="#120F00", border=ft.border.all(1, BORDER),
        padding=ft.padding.symmetric(horizontal=8, vertical=3),
        content=ft.Text((item.file_type or "?").upper(), color=GOLD_DIM, size=10, weight=ft.FontWeight.BOLD))

    status_badge = ft.Container(
        border_radius=6, bgcolor="#08090D",
        border=ft.border.all(1, status_color),
        padding=ft.padding.symmetric(horizontal=8, vertical=3),
        content=ft.Text(status_label, color=status_color, size=9, weight=ft.FontWeight.BOLD),
        visible=context == "my_assets",
    )

    img_container = ft.Container(
        height=160,
        bgcolor="#08090E",
        clip_behavior=ft.ClipBehavior.ANTI_ALIAS,
        alignment=ft.Alignment(0, 0),
        content=ft.Icon(ft.Icons.IMAGE_OUTLINED, color="#1E2030", size=40),
    )

    def _load_image():
        try:
            path = app.image_cache.get_path(item.asset_id)
            if path and path.exists():
                img_container.content = ft.Image(
                    src=str(path),
                    fit=ft.BoxFit.COVER,
                    expand=True,
                    height=160,
                )
                try:
                    img_container.update()
                except Exception:
                    pass
        except Exception as exc:
            _logger.warning(f"Card image load error {item.asset_id}: {exc}")

    threading.Thread(target=_load_image, daemon=True).start()

    # ── Action buttons ──────────────────────────────────────────────────────────
    action_controls = []

    if context == "my_assets":
        # Delete always available in My Assets
        action_controls.append(
            ft.OutlinedButton("Delete", on_click=do_delete,
                style=ft.ButtonStyle(
                    color=ERROR,
                    side=ft.BorderSide(1, ERROR),
                    shape=ft.RoundedRectangleBorder(radius=8),
                    padding=ft.padding.symmetric(horizontal=12, vertical=8),
                ))
        )
        # Upload To Market for PENDING / UNLISTED
        if item.asset_status in ("PENDING", "UNLISTED"):
            action_controls.append(
                ft.FilledButton("→ Upload To Market", bgcolor="#0E1C0E", color=SUCCESS,
                    style=ft.ButtonStyle(shape=ft.RoundedRectangleBorder(radius=8),
                        side=ft.BorderSide(1, SUCCESS),
                        padding=ft.padding.symmetric(horizontal=12, vertical=8)),
                    on_click=do_upload_to_market)
            )

    elif context == "marketplace":
        if is_own:
            # User's own FOR_SALE asset: offer Unlist
            action_controls.append(
                ft.OutlinedButton("Unlist", on_click=do_unlist,
                    style=ft.ButtonStyle(
                        color=GOLD_DIM,
                        side=ft.BorderSide(1, GOLD_DIM),
                        shape=ft.RoundedRectangleBorder(radius=8),
                        padding=ft.padding.symmetric(horizontal=14, vertical=8),
                    ))
            )
        else:
            action_controls.append(
                ft.FilledButton("Buy Now", bgcolor=GOLD, color="#130E00", on_click=do_buy,
                    style=ft.ButtonStyle(shape=ft.RoundedRectangleBorder(radius=8),
                        padding=ft.padding.symmetric(horizontal=18, vertical=8)))
            )

    price_row = ft.Row(
        alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
        vertical_alignment=ft.CrossAxisAlignment.CENTER,
        controls=[
            ft.Column(spacing=0, tight=True, controls=[
                ft.Text(f"{item.price:.2f}", color=GOLD, size=18, weight=ft.FontWeight.BOLD),
                ft.Text("AUR", color=GOLD_DIM, size=10),
            ]),
            ft.Row(spacing=6, controls=action_controls),
        ])

    return ft.Container(
        bgcolor=CARD_SOFT, border_radius=14, border=ft.border.all(1, BORDER_DIM),
        padding=0, on_hover=on_hover, clip_behavior=ft.ClipBehavior.ANTI_ALIAS,
        content=ft.Column(spacing=0, controls=[
            img_container,
            ft.Container(padding=14, content=ft.Column(spacing=8, controls=[
                ft.Row(alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
                    vertical_alignment=ft.CrossAxisAlignment.START, controls=[
                    ft.Text(item.title, color=TEXT, size=14, weight=ft.FontWeight.BOLD,
                        max_lines=1, overflow=ft.TextOverflow.ELLIPSIS, expand=True),
                    ft.Row(spacing=4, controls=[status_badge, type_badge]),
                ]),
                ft.Text(f"by {item.owner}", color=MUTED, size=11),
                ft.Text(item.description or "—", color=MUTED, size=12,
                    max_lines=2, overflow=ft.TextOverflow.ELLIPSIS),
                ft.Container(height=1, bgcolor=BORDER_DIM, margin=ft.margin.symmetric(vertical=2)),
                price_row,
            ])),
        ]))


def build_marketplace_view(app):
    # Clear stale event sets so assets just loaded aren't immediately removed
    app._sold_asset_ids.clear()
    app._removed_asset_ids.clear()
    app._unlisted_asset_ids.clear()

    grid = ft.ResponsiveRow(spacing=10, run_spacing=10)
    status_text = ft.Text("Loading...", color=MUTED, size=12)
    card_map: dict[str, ft.Container] = {}
    _active = [True]

    def _load():
        try:
            id_entries = app.get_market_asset_ids()
        except Exception as exc:
            status_text.value = f"Error: {exc}"
            app.notify(str(exc), error=True)
            try:
                status_text.update()
            except Exception:
                pass
            return

        if not id_entries:
            status_text.value = "No assets listed yet"
            try:
                status_text.update()
            except Exception:
                pass
            return

        status_text.value = f"Loading {len(id_entries)} asset(s)…"
        try:
            status_text.update()
        except Exception:
            return

        loaded = 0
        for entry in id_entries:
            if not _active[0]:
                return
            asset_id = entry.get("id", "") if isinstance(entry, dict) else str(entry)
            version = entry.get("version", 1) if isinstance(entry, dict) else 1
            if not asset_id:
                continue
            item = app.load_asset_by_id(asset_id, version)
            if not item:
                continue
            card = _asset_card(app, item)
            wrapper = ft.Container(col={"xs": 12, "sm": 6, "md": 4, "lg": 3}, content=card)
            card_map[asset_id] = wrapper
            grid.controls.append(wrapper)
            loaded += 1
            try:
                grid.update()
                status_text.value = f"{loaded} / {len(id_entries)} loaded"
                status_text.update()
            except Exception:
                _active[0] = False
                return

        n = loaded
        status_text.value = f"{n} asset{'s' if n != 1 else ''} listed"
        try:
            status_text.update()
        except Exception:
            pass

    def _monitor():
        while _active[0]:
            time.sleep(2)
            if not _active[0]:
                return
            app._drain_asset_events()
            removed_ids = list(app._sold_asset_ids | app._removed_asset_ids | app._unlisted_asset_ids)
            changed = False
            for asset_id in removed_ids:
                wrapper = card_map.pop(asset_id, None)
                if wrapper and wrapper in grid.controls:
                    grid.controls.remove(wrapper)
                    changed = True
            if changed:
                try:
                    grid.update()
                    n = len(card_map)
                    status_text.value = f"{n} asset{'s' if n != 1 else ''} listed"
                    status_text.update()
                except Exception:
                    _active[0] = False
                    return

    def do_refresh(_):
        _active[0] = False
        grid.controls.clear()
        card_map.clear()
        try:
            grid.update()
        except Exception:
            pass
        try:
            app.request_balance()
        except Exception as e:
            app.notify(str(e), error=True)
        app.page.go("/marketplace")

    threading.Thread(target=_load, daemon=True).start()
    threading.Thread(target=_monitor, daemon=True).start()

    body = ft.Column(spacing=14, controls=[
        ft.Row(alignment=ft.MainAxisAlignment.SPACE_BETWEEN, vertical_alignment=ft.CrossAxisAlignment.CENTER, controls=[
            ft.Column(spacing=2, tight=True, controls=[
                ft.Text("Marketplace", color=TEXT, size=22, weight=ft.FontWeight.BOLD),
                status_text,
            ]),
            ft.FilledButton("↺  Refresh", bgcolor="#0E1018", color=GOLD_SOFT,
                style=ft.ButtonStyle(shape=ft.RoundedRectangleBorder(radius=9), side=ft.BorderSide(1, BORDER)),
                on_click=do_refresh),
        ]),
        grid,
    ])
    return _main_shell(app, "/marketplace", "Trade digital ownership", body)


def build_upload_view(app):
    picked = {"path": "", "for_sale": True}
    selected = ft.Text("No file selected", color=MUTED, size=12)
    asset_name = _input("Asset Name", icon=ft.Icons.TITLE_ROUNDED)
    description = ft.TextField(label="Description", multiline=True, min_lines=2, max_lines=4,
        border_radius=11, bgcolor="#060709", border_color="#2E2218", focused_border_color=GOLD,
        color=TEXT, label_style=ft.TextStyle(color=MUTED, size=12))
    cost = _input("Price (AUR)", icon=ft.Icons.CURRENCY_EXCHANGE_ROUNDED)
    upload_btn = ft.FilledButton("Upload Asset", height=46, bgcolor=GOLD, color="#130E00",
        style=ft.ButtonStyle(shape=ft.RoundedRectangleBorder(radius=12)),
        disabled=True)

    def _btn_style(active):
        return ft.ButtonStyle(
            color=GOLD if active else MUTED,
            side=ft.BorderSide(1.5 if active else 1, GOLD if active else "#252535"),
            bgcolor="#1E1800" if active else "#0A0C14",
            shape=ft.RoundedRectangleBorder(radius=9),
            padding=ft.padding.symmetric(horizontal=18, vertical=9),
        )

    btn_marketplace = ft.OutlinedButton("Marketplace", style=_btn_style(True))
    btn_my_assets = ft.OutlinedButton("My Assets", style=_btn_style(False))

    def _select_marketplace(_):
        picked["for_sale"] = True
        btn_marketplace.style = _btn_style(True)
        btn_my_assets.style = _btn_style(False)
        btn_marketplace.update()
        btn_my_assets.update()

    def _select_my_assets(_):
        picked["for_sale"] = False
        btn_marketplace.style = _btn_style(False)
        btn_my_assets.style = _btn_style(True)
        btn_marketplace.update()
        btn_my_assets.update()

    btn_marketplace.on_click = _select_marketplace
    btn_my_assets.on_click = _select_my_assets

    upload_to_row = ft.Row(spacing=0, vertical_alignment=ft.CrossAxisAlignment.CENTER, controls=[
        ft.Text("Upload To:", color=MUTED, size=12),
        ft.Container(width=10),
        btn_marketplace,
        ft.Container(width=6),
        btn_my_assets,
    ])

    picker = getattr(app.page, "_upload_picker", None)
    if picker is None:
        picker = ft.FilePicker()
        app.page.services.append(picker)
        setattr(app.page, "_upload_picker", picker)

    async def _choose_file_async():
        files = await picker.pick_files(
            allow_multiple=False,
            file_type=ft.FilePickerFileType.CUSTOM,
            allowed_extensions=["png", "jpg", "jpeg"],
        )
        if not files:
            return
        f = files[0]
        if not f.path:
            app.notify("Cannot determine file path", error=True)
            return
        picked["path"] = f.path
        selected.value = f.name
        selected.color = GOLD_SOFT
        upload_btn.disabled = False
        app.page.update()

    def choose_file(_):
        app.page.run_task(_choose_file_async)

    status_text = ft.Text("", size=11, color=MUTED)

    def do_upload(_):
        if not picked["path"]:
            app.notify("Choose a file first", error=True)
            return
        name_val = (asset_name.value or "").strip()
        if not name_val:
            app.notify("Asset name is required", error=True)
            return
        try:
            cost_val = float(cost.value or 0)
        except ValueError:
            app.notify("Enter a valid price", error=True)
            return
        ext = Path(picked["path"]).suffix.lower().lstrip(".")
        if ext not in {"png", "jpg", "jpeg"}:
            app.notify("Only .png, .jpg, .jpeg are allowed", error=True)
            return
        file_type = "jpg" if ext == "jpeg" else ext
        path_snap = picked["path"]
        desc_snap = (description.value or "").strip()

        upload_btn.disabled = True
        status_text.value = "Uploading..."
        status_text.color = GOLD_SOFT
        app.page.update()

        for_sale_snap = picked["for_sale"]

        def _upload_thread():
            def _set_status(msg, color=MUTED):
                status_text.value = msg
                status_text.color = color
                app.page.update()

            def _show_error(msg):
                _logger.error(f"[upload] {msg}")
                _set_status(f"Error: {msg}", ERROR)
                app.page.snack_bar = ft.SnackBar(
                    content=ft.Text(msg), bgcolor="#7D2032")
                app.page.snack_bar.open = True
                upload_btn.disabled = False
                app.page.update()

            try:
                _logger.info(f"[upload] start  path={path_snap!r}  name={name_val!r}  type={file_type}  cost={cost_val}  for_sale={for_sale_snap}")
                _set_status("Sending UPLOAD_INIT...")
                app.upload_asset(path_snap, name_val, desc_snap, file_type, cost_val, for_sale=for_sale_snap)
                _logger.info("[upload] UPLOAD_SUCCESS — asset saved")
                status_text.value = ""
                app.page.snack_bar = ft.SnackBar(
                    content=ft.Text("Upload complete!"), bgcolor="#136F3A")
                app.page.snack_bar.open = True
                app.page.update()
                dest = "/marketplace" if for_sale_snap else "/my_assets"
                app.page.go(dest)
            except Exception as exc:
                _show_error(str(exc))

        threading.Thread(target=_upload_thread, daemon=True).start()

    upload_btn.on_click = do_upload

    body = ft.Container(width=640, bgcolor=CARD, border_radius=20, border=ft.border.all(1, BORDER),
        shadow=_GLOW, padding=26,
        content=ft.Column(spacing=14, controls=[
            ft.Row(spacing=10, vertical_alignment=ft.CrossAxisAlignment.CENTER, controls=[
                ft.Icon(ft.Icons.ADD_PHOTO_ALTERNATE_OUTLINED, color=GOLD, size=22),
                ft.Column(spacing=0, tight=True, controls=[
                    ft.Text("Mint New Asset", color=TEXT, size=20, weight=ft.FontWeight.BOLD),
                    ft.Text("Upload an image asset to Aurex.", color=MUTED, size=11),
                ]),
            ]),
            _divider(),
            ft.Row(spacing=10, vertical_alignment=ft.CrossAxisAlignment.CENTER, controls=[
                ft.FilledButton("Choose File", bgcolor="#1C1400", color=GOLD_SOFT,
                    style=ft.ButtonStyle(shape=ft.RoundedRectangleBorder(radius=9), side=ft.BorderSide(1, BORDER)),
                    on_click=choose_file),
                ft.Icon(ft.Icons.IMAGE_OUTLINED, color=MUTED, size=15),
                selected,
            ]),
            asset_name, description, cost,
            upload_to_row,
            status_text,
            upload_btn,
        ]))
    return _main_shell(app, "/upload", "Mint a new asset", body)


def build_settings_view(app):
    status = ft.Text("Wallet not loaded", color=ERROR, size=13)
    preview = ft.Text("", color="#5A6A7A", selectable=True, size=11, font_family="monospace")
    local_wallet_path = "Client/{}/wallet.json".format(app.state.username or "")

    def refresh_wallet_ui():
        if app.state.wallet_loaded and app.wallet_session:
            status.value = app.state.wallet_status_message or "Wallet ready"
            status.color = SUCCESS
            preview.value = app.wallet_preview()
        else:
            status.value = "Wallet not loaded"
            status.color = ERROR
            preview.value = ""
        app.page.update()

    import_picker = getattr(app.page, "_wallet_import_picker", None)
    if import_picker is None:
        import_picker = ft.FilePicker()
        app.page.services.append(import_picker)
        setattr(app.page, "_wallet_import_picker", import_picker)

    export_picker = getattr(app.page, "_wallet_export_picker", None)
    if export_picker is None:
        export_picker = ft.FilePicker()
        app.page.services.append(export_picker)
        setattr(app.page, "_wallet_export_picker", export_picker)

    def generate_wallet(_):
        try:
            app.generate_new_wallet()
            app.notify("New wallet generated")
            refresh_wallet_ui()
        except Exception as exc:
            app.notify(str(exc), error=True)

    def load_default(_):
        try:
            app.load_default_wallet()
            app.notify("Local wallet loaded")
            refresh_wallet_ui()
        except Exception as exc:
            app.notify(str(exc), error=True)

    async def _import_wallet_async():
        files = await import_picker.pick_files(
            allow_multiple=False,
            file_type=ft.FilePickerFileType.CUSTOM,
            allowed_extensions=["json"],
        )
        if not files or not files[0].path:
            return
        try:
            app.load_wallet_from_file(files[0].path)
            app.notify("Wallet imported")
            refresh_wallet_ui()
        except Exception as exc:
            app.notify(str(exc), error=True)

    def import_wallet(_):
        app.page.run_task(_import_wallet_async)

    async def _export_wallet_async():
        if not app.state.wallet_loaded:
            app.notify("Load or generate wallet first", error=True)
            return
        save_path = await export_picker.save_file(
            dialog_title="Save wallet.json",
            file_name=f"wallet_{app.state.username}.json",
            file_type=ft.FilePickerFileType.CUSTOM,
            allowed_extensions=["json"],
        )
        if save_path:
            try:
                app.export_wallet(save_path)
                app.notify("Wallet exported")
            except Exception as exc:
                app.notify(str(exc), error=True)

    def export_wallet(_):
        app.page.run_task(_export_wallet_async)

    def continue_market(_):
        if not app.state.wallet_loaded:
            app.notify("Wallet required before marketplace", error=True)
            return
        app.page.go("/marketplace")

    def do_delete_account(_):
        def on_confirm(e):
            app.page.dialog.open = False
            app.page.update()
            try:
                app.delete_account()
            except Exception as exc:
                app.notify(str(exc), error=True)
                return
            app.page.go("/login")

        def on_cancel(e):
            app.page.dialog.open = False
            app.page.update()

        app.page.dialog = ft.AlertDialog(
            modal=True,
            title=ft.Text("Delete Account", color=ERROR),
            content=ft.Text(
                "By clicking OK you agree to delete your account and all your assets. "
                "This action cannot be undone.",
                color=TEXT,
            ),
            bgcolor="#1A0808",
            actions=[
                ft.TextButton("Cancel", on_click=on_cancel,
                    style=ft.ButtonStyle(color=MUTED)),
                ft.FilledButton("OK — Delete My Account", bgcolor=ERROR, color="white",
                    on_click=on_confirm,
                    style=ft.ButtonStyle(shape=ft.RoundedRectangleBorder(radius=9))),
            ],
            actions_alignment=ft.MainAxisAlignment.END,
        )
        app.page.dialog.open = True
        app.page.update()

    refresh_wallet_ui()

    danger_section = ft.Container(
        bgcolor="#0D0808", border=ft.border.all(1, "#5A1010"), border_radius=14, padding=20,
        content=ft.Column(spacing=12, controls=[
            ft.Row(spacing=8, controls=[
                ft.Icon(ft.Icons.WARNING_ROUNDED, color=ERROR, size=18),
                ft.Text("Danger Zone", color=ERROR, size=15, weight=ft.FontWeight.BOLD),
            ]),
            ft.Text(
                "Permanently delete your account, all your assets, and marketplace listings.",
                color=MUTED, size=12,
            ),
            ft.OutlinedButton(
                "Delete Account",
                on_click=do_delete_account,
                style=ft.ButtonStyle(
                    color=ERROR,
                    side=ft.BorderSide(1, ERROR),
                    shape=ft.RoundedRectangleBorder(radius=9),
                    padding=ft.padding.symmetric(horizontal=16, vertical=9),
                ),
            ),
        ]),
    )

    body = ft.Container(width=800, bgcolor=CARD, border_radius=22, border=ft.border.all(1, BORDER),
        shadow=_GLOW, padding=28,
        content=ft.Column(spacing=18, controls=[
            ft.Row(spacing=12, vertical_alignment=ft.CrossAxisAlignment.CENTER, controls=[
                ft.Icon(ft.Icons.ACCOUNT_BALANCE_WALLET_OUTLINED, color=GOLD, size=24),
                ft.Column(spacing=0, tight=True, controls=[
                    ft.Text("Wallet & Identity", color=TEXT, size=22, weight=ft.FontWeight.BOLD),
                    ft.Text("Private key stays local. Public key synced to server.", color=MUTED, size=11),
                ]),
            ]),
            ft.Container(bgcolor="#080A0E", border=ft.border.all(1, "#181E28"), border_radius=14, padding=14,
                content=ft.Column(spacing=8, controls=[
                    ft.Row(spacing=8, controls=[ft.Icon(ft.Icons.PERSON_OUTLINE_ROUNDED, color=MUTED, size=15),
                        ft.Text(app.state.username or "—", color=GOLD_SOFT, size=13, weight=ft.FontWeight.W_600)]),
                    ft.Row(spacing=8, controls=[ft.Icon(ft.Icons.FOLDER_OUTLINED, color=MUTED, size=15),
                        ft.Text(local_wallet_path, color=MUTED, size=11)]),
                    ft.Container(height=1, bgcolor="#181E28"),
                    ft.Row(spacing=8, controls=[
                        ft.Container(width=8, height=8, border_radius=4,
                            bgcolor=SUCCESS if app.state.wallet_loaded else ERROR),
                        status,
                    ]),
                ])),
            ft.Row(wrap=True, spacing=8, run_spacing=8, controls=[
                ft.FilledButton("Generate New Wallet", bgcolor=GOLD, color="#130E00",
                    style=ft.ButtonStyle(shape=ft.RoundedRectangleBorder(radius=9)), on_click=generate_wallet),
                ft.OutlinedButton("Load Local Wallet", on_click=load_default,
                    style=ft.ButtonStyle(shape=ft.RoundedRectangleBorder(radius=9), color=TEXT, side=ft.BorderSide(1, BORDER))),
                ft.OutlinedButton("Import (.json)", on_click=import_wallet,
                    style=ft.ButtonStyle(shape=ft.RoundedRectangleBorder(radius=9), color=TEXT, side=ft.BorderSide(1, BORDER))),
                ft.OutlinedButton("Export Wallet", on_click=export_wallet,
                    style=ft.ButtonStyle(shape=ft.RoundedRectangleBorder(radius=9), color=TEXT, side=ft.BorderSide(1, BORDER))),
            ]),
            ft.Container(bgcolor="#060709", border=ft.border.all(1, "#141820"), border_radius=12, padding=14, content=preview),
            ft.Row(alignment=ft.MainAxisAlignment.END, controls=[
                ft.FilledButton("Continue to Marketplace  →", bgcolor=SUCCESS, color="white",
                    style=ft.ButtonStyle(shape=ft.RoundedRectangleBorder(radius=10)), on_click=continue_market),
            ]),
            ft.Container(height=1, bgcolor=BORDER_DIM, margin=ft.margin.symmetric(vertical=4)),
            danger_section,
        ]))
    return _main_shell(app, "/settings", "Identity & settings", body)


def build_notifications_view(app):
    if app.state.notifications:
        rows = [ft.Container(bgcolor="#08090D", border_radius=11, border=ft.border.all(1, "#181E2A"), padding=14,
            content=ft.Row(spacing=10, controls=[
                ft.Container(width=6, height=6, border_radius=3, bgcolor=GOLD_DIM,
                    margin=ft.margin.only(top=4)),
                ft.Text(msg, color=TEXT, size=13, expand=True),
            ])) for msg in app.state.notifications]
    else:
        rows = [ft.Container(padding=60, alignment=ft.Alignment(0, 0),
            content=ft.Column(horizontal_alignment=ft.CrossAxisAlignment.CENTER, spacing=12, controls=[
                ft.Icon(ft.Icons.NOTIFICATIONS_NONE_ROUNDED, color="#2A2A3A", size=56),
                ft.Text("No notifications yet", color=MUTED, size=14),
            ]))]

    return _main_shell(app, "/notifications", "System updates",
        ft.Column(spacing=12, controls=[
            ft.Text("Notifications", color=TEXT, size=22, weight=ft.FontWeight.BOLD),
            *rows,
        ]))


def build_my_assets_view(app):
    grid = ft.ResponsiveRow(spacing=10, run_spacing=10)
    status_text = ft.Text("Loading...", color=MUTED, size=12)
    _active = [True]

    def _load():
        try:
            id_entries = app.get_my_asset_ids()
        except Exception as exc:
            status_text.value = f"Error: {exc}"
            app.notify(str(exc), error=True)
            try:
                status_text.update()
            except Exception:
                pass
            return

        if not id_entries:
            status_text.value = "No assets yet"
            try:
                status_text.update()
            except Exception:
                pass
            return

        status_text.value = f"Loading {len(id_entries)} asset(s)..."
        try:
            status_text.update()
        except Exception:
            return

        loaded = 0
        for entry in id_entries:
            if not _active[0]:
                return
            asset_id = entry.get("id", "") if isinstance(entry, dict) else str(entry)
            version = entry.get("version", 1) if isinstance(entry, dict) else 1
            if not asset_id:
                continue
            item = app.load_asset_by_id(asset_id, version)
            if not item:
                continue
            card = _asset_card(app, item, context="my_assets")
            wrapper = ft.Container(col={"xs": 12, "sm": 6, "md": 4}, content=card)
            grid.controls.append(wrapper)
            loaded += 1
            try:
                grid.update()
                status_text.value = f"{loaded} / {len(id_entries)} loaded"
                status_text.update()
            except Exception:
                _active[0] = False
                return

        n = loaded
        status_text.value = f"{n} asset{'s' if n != 1 else ''} owned"
        try:
            status_text.update()
        except Exception:
            pass

    def do_refresh(_):
        _active[0] = False
        grid.controls.clear()
        try:
            grid.update()
        except Exception:
            pass
        try:
            app.request_balance()
        except Exception as e:
            app.notify(str(e), error=True)
        app.page.go("/my_assets")

    threading.Thread(target=_load, daemon=True).start()

    body = ft.Column(spacing=14, controls=[
        ft.Row(alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
            vertical_alignment=ft.CrossAxisAlignment.CENTER, controls=[
            ft.Column(spacing=2, tight=True, controls=[
                ft.Text("My Collection", color=TEXT, size=22, weight=ft.FontWeight.BOLD),
                status_text,
            ]),
            ft.FilledButton("↺  Refresh", bgcolor="#0E1018", color=GOLD_SOFT,
                style=ft.ButtonStyle(shape=ft.RoundedRectangleBorder(radius=9), side=ft.BorderSide(1, BORDER)),
                on_click=do_refresh),
        ]),
        grid,
    ])
    return _main_shell(app, "/my_assets", "Personal portfolio", body)
