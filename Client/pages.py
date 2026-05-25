"""Elegant Aurex UI pages (UI-only)."""
from __future__ import annotations
import flet as ft
import logging
import threading
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
    nav = ft.Row(wrap=True, run_spacing=6, spacing=6, controls=[
        _nav_btn(app, "Market", "/marketplace"),
        _nav_btn(app, "Upload", "/upload"),
        _nav_btn(app, "My Assets", "/my_assets"),
        _nav_btn(app, "Wallet", "/wallet"),
        _nav_btn(app, "Alerts", "/notifications"),
        ft.FilledButton("Logout", bgcolor="#3A0C14", color="#FF8A8A",
            style=ft.ButtonStyle(shape=ft.RoundedRectangleBorder(radius=9), padding=ft.padding.symmetric(horizontal=14, vertical=7)),
            on_click=lambda _: _logout(app)),
    ])
    back_btn = ft.IconButton(icon=ft.Icons.ARROW_BACK_IOS_NEW_ROUNDED, icon_color=GOLD_SOFT, icon_size=15,
        tooltip="Back", visible=route != "/marketplace", on_click=lambda _: app.page.go("/marketplace"))
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
            nav,
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
            app.page.go("/wallet")
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
            app.update_password((email.value or "").strip(), new_pass.value or "")
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


def _asset_card(app, item):
    def do_buy(_):
        try:
            app.buy_asset(item)
            app.notify("Purchase request signed and sent")
        except Exception as e:
            app.notify(str(e), error=True)

    def on_hover(e):
        e.control.border = ft.border.all(1, GOLD_DIM if e.data == "true" else BORDER_DIM)
        e.control.shadow = _SHADOW if e.data == "true" else []
        e.control.update()

    type_badge = ft.Container(border_radius=6, bgcolor="#120F00", border=ft.border.all(1, BORDER),
        padding=ft.padding.symmetric(horizontal=8, vertical=3),
        content=ft.Text((item.file_type or "?").upper(), color=GOLD_DIM, size=10, weight=ft.FontWeight.BOLD))

    return ft.Container(bgcolor=CARD_SOFT, border_radius=14, border=ft.border.all(1, BORDER_DIM),
        padding=14, on_hover=on_hover,
        content=ft.Column(spacing=8, controls=[
            ft.Row(alignment=ft.MainAxisAlignment.SPACE_BETWEEN, vertical_alignment=ft.CrossAxisAlignment.START, controls=[
                ft.Text(item.title, color=TEXT, size=14, weight=ft.FontWeight.BOLD, max_lines=1, overflow=ft.TextOverflow.ELLIPSIS, expand=True),
                type_badge,
            ]),
            ft.Text(f"by {item.owner}", color=MUTED, size=11),
            ft.Text(item.description or "—", color=MUTED, size=12, max_lines=2, overflow=ft.TextOverflow.ELLIPSIS),
            ft.Container(height=1, bgcolor=BORDER_DIM, margin=ft.margin.symmetric(vertical=2)),
            ft.Row(alignment=ft.MainAxisAlignment.SPACE_BETWEEN, vertical_alignment=ft.CrossAxisAlignment.CENTER, controls=[
                ft.Column(spacing=0, tight=True, controls=[
                    ft.Text(f"{item.price:.2f}", color=GOLD, size=18, weight=ft.FontWeight.BOLD),
                    ft.Text("AUR", color=GOLD_DIM, size=10),
                ]),
                ft.FilledButton("Buy Now", bgcolor=GOLD, color="#130E00", on_click=do_buy,
                    style=ft.ButtonStyle(shape=ft.RoundedRectangleBorder(radius=8),
                        padding=ft.padding.symmetric(horizontal=18, vertical=8))),
            ]),
        ]))


def build_marketplace_view(app):
    try:
        items = app.refresh_market_items()
    except Exception as e:
        app.notify(str(e), error=True)
        items = []

    grid = ft.ResponsiveRow(spacing=10, run_spacing=10,
        controls=[ft.Container(col={"xs": 12, "sm": 6, "md": 4, "lg": 3}, content=_asset_card(app, it)) for it in items]
    ) if items else ft.Container(padding=60, alignment=ft.Alignment(0, 0),
        content=ft.Column(horizontal_alignment=ft.CrossAxisAlignment.CENTER, spacing=12, controls=[
            ft.Icon(ft.Icons.STORE_MALL_DIRECTORY_OUTLINED, color="#2A2A3A", size=64),
            ft.Text("No assets listed yet", color=MUTED, size=15),
        ]))

    body = ft.Column(spacing=14, controls=[
        ft.Row(alignment=ft.MainAxisAlignment.SPACE_BETWEEN, vertical_alignment=ft.CrossAxisAlignment.CENTER, controls=[
            ft.Column(spacing=2, tight=True, controls=[
                ft.Text("Marketplace", color=TEXT, size=22, weight=ft.FontWeight.BOLD),
                ft.Text(f"{len(items)} asset{'s' if len(items) != 1 else ''} listed", color=MUTED, size=12),
            ]),
            ft.FilledButton("↺  Refresh", bgcolor="#0E1018", color=GOLD_SOFT,
                style=ft.ButtonStyle(shape=ft.RoundedRectangleBorder(radius=9), side=ft.BorderSide(1, BORDER)),
                on_click=lambda _: app.page.go("/marketplace")),
        ]),
        grid,
    ])
    return _main_shell(app, "/marketplace", "Trade digital ownership", body)


def build_upload_view(app):
    picked = {"path": ""}
    selected = ft.Text("No file selected", color=MUTED, size=12)
    asset_name = _input("Asset Name", icon=ft.Icons.TITLE_ROUNDED)
    description = ft.TextField(label="Description", multiline=True, min_lines=2, max_lines=4,
        border_radius=11, bgcolor="#060709", border_color="#2E2218", focused_border_color=GOLD,
        color=TEXT, label_style=ft.TextStyle(color=MUTED, size=12))
    cost = _input("Price (AUR)", icon=ft.Icons.CURRENCY_EXCHANGE_ROUNDED)
    upload_btn = ft.FilledButton("Upload Asset", height=46, bgcolor=GOLD, color="#130E00",
        style=ft.ButtonStyle(shape=ft.RoundedRectangleBorder(radius=12)),
        disabled=True)

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
        # Snapshot everything from UI controls before entering the thread
        path_snap = picked["path"]
        desc_snap = (description.value or "").strip()

        upload_btn.disabled = True
        status_text.value = "Uploading..."
        status_text.color = GOLD_SOFT
        app.page.update()

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
                _logger.info(f"[upload] start  path={path_snap!r}  name={name_val!r}  type={file_type}  cost={cost_val}")
                _set_status("Sending UPLOAD_INIT...")
                app.upload_asset(path_snap, name_val, desc_snap, file_type, cost_val)
                _logger.info("[upload] UPLOAD_SUCCESS — asset saved")
                status_text.value = ""
                app.page.snack_bar = ft.SnackBar(
                    content=ft.Text("Upload complete!"), bgcolor="#136F3A")
                app.page.snack_bar.open = True
                app.page.update()
                async def _nav():
                    await app.page.go("/marketplace")
                app.page.run_task(_nav)
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
                    ft.Text("List an image on the Aurex marketplace.", color=MUTED, size=11),
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
            status_text,
            upload_btn,
        ]))
    return _main_shell(app, "/upload", "Mint a new asset", body)


def build_wallet_settings_view(app):
    status = ft.Text("Wallet not loaded", color=ERROR, size=13)
    preview = ft.Text("", color="#5A6A7A", selectable=True, size=11, font_family="monospace")
    local_wallet_path = "Client/wallets/{}/wallet.json".format(app.state.username or "")

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

    refresh_wallet_ui()

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
        ]))
    return _main_shell(app, "/wallet", "Identity & keys", body)


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
    try:
        mine = app.fetch_my_assets()
    except Exception as e:
        app.notify(str(e), error=True)
        mine = []
    body = ft.Column(spacing=14, controls=[
        ft.Row(controls=[
            ft.Column(spacing=2, tight=True, controls=[
                ft.Text("My Collection", color=TEXT, size=22, weight=ft.FontWeight.BOLD),
                ft.Text(f"{len(mine)} asset{'s' if len(mine) != 1 else ''} owned", color=MUTED, size=12),
            ]),
        ]),
        ft.ResponsiveRow(spacing=10, run_spacing=10,
            controls=[ft.Container(col={"xs": 12, "sm": 6, "md": 4}, content=_asset_card(app, it)) for it in mine]
        ) if mine else ft.Container(padding=60, alignment=ft.Alignment(0, 0),
            content=ft.Column(horizontal_alignment=ft.CrossAxisAlignment.CENTER, spacing=12, controls=[
                ft.Icon(ft.Icons.COLLECTIONS_OUTLINED, color="#2A2A3A", size=64),
                ft.Text("You don't own any assets yet.", color=MUTED, size=14),
            ])),
    ])
    return _main_shell(app, "/my_assets", "Personal portfolio", body)
