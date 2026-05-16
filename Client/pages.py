"""Elegant Aurex UI pages (UI-only)."""

from __future__ import annotations

import flet as ft

BG = "#090B0F"
SCRIM = "#C814161B"
CARD = "#E2121310"
CARD_SOFT = "#CC17120E"
BORDER = "#4A3620"
TEXT = "#F3F6FA"
MUTED = "#A8B1C2"
GOLD = "#E9BD4B"
GOLD_SOFT = "#F4D78A"
SUCCESS = "#3FB170"
ERROR = "#D05757"


def _bg(content):
    return ft.Container(
        expand=True,
        image=ft.DecorationImage(src="images/gold_bg.png", fit=ft.BoxFit.COVER),
        content=ft.Container(expand=True, bgcolor=SCRIM, content=content),
    )


def _logo_block(title="AUREX"):
    return ft.Column(
        spacing=8,
        horizontal_alignment=ft.CrossAxisAlignment.CENTER,
        controls=[
            ft.Image(src="images/gold_icon.png", width=70, height=70, fit=ft.BoxFit.CONTAIN),
            ft.Text(title, size=30, weight=ft.FontWeight.BOLD, color=GOLD, style=ft.TextStyle(letter_spacing=4)),
        ],
    )


def _auth_shell(route, body):
    return ft.View(route=route, bgcolor=BG, padding=0, controls=[_bg(ft.Container(expand=True, alignment=ft.Alignment(0, 0), content=body))])


def _main_shell(app, route, title, body):
    nav = ft.Row(
        wrap=True,
        run_spacing=8,
        spacing=8,
        controls=[
            _nav_btn(app, "Marketplace", "/marketplace"),
            _nav_btn(app, "Upload", "/upload"),
            _nav_btn(app, "My Assets", "/my_assets"),
            _nav_btn(app, "Wallet", "/wallet"),
            _nav_btn(app, "Notifications", "/notifications"),
            ft.FilledButton("Logout", bgcolor="#7D2032", color="white", on_click=lambda _: _logout(app)),
        ],
    )
    back_to_market = ft.IconButton(icon=ft.Icons.ARROW_BACK_IOS_NEW_ROUNDED, icon_color=GOLD_SOFT, tooltip="Back", visible=route != "/marketplace", on_click=lambda _: app.page.go("/marketplace"))
    head = ft.Container(
        border_radius=16,
        bgcolor="#BF0F141B",
        border=ft.border.all(1, "#6C522F"),
        padding=16,
        content=ft.Row(
            alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
            vertical_alignment=ft.CrossAxisAlignment.CENTER,
            controls=[
                ft.Row(spacing=6, controls=[back_to_market, ft.Image(src="images/gold_icon.png", width=34, height=34), ft.Column(spacing=0, controls=[ft.Text("Aurex", color=GOLD, size=22, weight=ft.FontWeight.BOLD), ft.Text(title, color=MUTED, size=12)])]),
                nav,
            ],
        ),
    )
    return ft.View(route=route, bgcolor=BG, padding=0, controls=[_bg(ft.Container(expand=True, padding=ft.padding.symmetric(horizontal=24, vertical=20), content=ft.Column(scroll=ft.ScrollMode.AUTO, spacing=14, controls=[head, body])))])


def _nav_btn(app, text, route):
    active = app.page.route == route
    return ft.OutlinedButton(text, on_click=lambda _: app.page.go(route), style=ft.ButtonStyle(color=GOLD if active else TEXT, side=ft.BorderSide(1, GOLD if active else BORDER), bgcolor="#3A3020" if active else "#1A202A"))


def _logout(app):
    try:
        app.logout()
        app.notify("Logged out")
    except Exception as e:
        app.notify(str(e), error=True)
    app.page.go("/login")


def _input(label, password=False):
    return ft.TextField(label=label, password=password, can_reveal_password=password, border_radius=14, bgcolor="#070809", border_color="#6B4E29", focused_border_color=GOLD, color=TEXT, cursor_color=GOLD, label_style=ft.TextStyle(color=MUTED))


def build_login_view(app):
    username, password = _input("Username"), _input("Password", True)

    def on_login(_):
        try:
            app.login((username.value or "").strip(), password.value or "")
            app.notify("Welcome back")
            app.page.go("/wallet")
        except Exception as e:
            app.notify(str(e), error=True)

    card = ft.Container(
        width=500,
        padding=26,
        border_radius=22,
        bgcolor=CARD,
        border=ft.border.all(1, BORDER),
        content=ft.Column(
            spacing=14,
            horizontal_alignment=ft.CrossAxisAlignment.CENTER,
            controls=[
                _logo_block(),
                ft.Text("Secure marketplace access", color=MUTED, size=12),
                ft.Divider(color="#5B4328", height=8),
                username,
                password,
                ft.FilledButton("Login", width=448, height=46, bgcolor=GOLD, color="#1A1A1B", on_click=on_login),
                ft.Row(alignment=ft.MainAxisAlignment.SPACE_BETWEEN, controls=[ft.TextButton("Create account", on_click=lambda _: app.page.go("/signup")), ft.TextButton("Forgot password", on_click=lambda _: app.page.go("/forgot"))]),
            ],
        ),
    )
    return _auth_shell("/login", card)


def build_signup_view(app):
    username, password, email = _input("Username"), _input("Password", True), _input("Email")

    def on_signup(_):
        try:
            app.signup((username.value or "").strip(), password.value or "", (email.value or "").strip())
            app.notify("Account created")
            app.page.go("/login")
        except Exception as e:
            app.notify(str(e), error=True)

    card = ft.Container(width=560, padding=24, border_radius=20, bgcolor=CARD, border=ft.border.all(1, BORDER), content=ft.Column(spacing=12, controls=[ft.Row(alignment=ft.MainAxisAlignment.SPACE_BETWEEN, controls=[ft.IconButton(icon=ft.Icons.ARROW_BACK_IOS_NEW_ROUNDED, icon_color=GOLD_SOFT, on_click=lambda _: app.page.go("/login")), ft.Text("Back to Login", color=MUTED, size=12)]), _logo_block("JOIN AUREX"), username, password, email, ft.FilledButton("Create Account", bgcolor=GOLD, color="#191919", on_click=on_signup)]))
    return _auth_shell("/signup", card)


def build_forgot_view(app):
    email, code, new_pass = _input("Email"), _input("Verification Code"), _input("New Password", True)

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

    card = ft.Container(width=600, padding=24, border_radius=20, bgcolor=CARD, border=ft.border.all(1, BORDER), content=ft.Column(spacing=12, controls=[ft.Row(alignment=ft.MainAxisAlignment.SPACE_BETWEEN, controls=[ft.IconButton(icon=ft.Icons.ARROW_BACK_IOS_NEW_ROUNDED, icon_color=GOLD_SOFT, on_click=lambda _: app.page.go("/login")), ft.Text("Back to Login", color=MUTED, size=12)]), _logo_block("RESET ACCESS"), email, ft.Row(spacing=8, controls=[ft.FilledButton("Send Code", on_click=do_send), ft.TextButton("Back", on_click=lambda _: app.page.go("/login"))]), code, ft.FilledButton("Verify", on_click=do_verify), new_pass, ft.FilledButton("Update Password", bgcolor=GOLD, color="#191919", on_click=do_reset)]))
    return _auth_shell("/forgot", card)


def _asset_card(item):
    return ft.Container(
        bgcolor=CARD_SOFT,
        border_radius=14,
        border=ft.border.all(1, BORDER),
        padding=14,
        content=ft.Column(
            spacing=6,
            controls=[
                ft.Text(item.title, color=TEXT, size=16, weight=ft.FontWeight.BOLD, max_lines=1, overflow=ft.TextOverflow.ELLIPSIS),
                ft.Text(f"Owner: {item.owner}", color=MUTED, size=12),
                ft.Text(item.description or "-", color=MUTED, size=12, max_lines=2, overflow=ft.TextOverflow.ELLIPSIS),
                ft.Row(alignment=ft.MainAxisAlignment.SPACE_BETWEEN, controls=[ft.Text(f"${item.price:.2f}", color=SUCCESS, size=15, weight=ft.FontWeight.BOLD), ft.Text(item.created_at, color=MUTED, size=11)]),
            ],
        ),
    )


def build_marketplace_view(app):
    try:
        items = app.refresh_market_items()
    except Exception as e:
        app.notify(str(e), error=True)
        items = []
    grid = ft.ResponsiveRow(spacing=10, run_spacing=10, controls=[ft.Container(col={"xs": 12, "sm": 6, "md": 4, "lg": 3}, content=_asset_card(it)) for it in items]) if items else ft.Container(padding=20, content=ft.Text("No assets yet", color=MUTED))
    body = ft.Column(spacing=12, controls=[ft.Row(alignment=ft.MainAxisAlignment.SPACE_BETWEEN, controls=[ft.Text("Marketplace Assets", color=TEXT, size=20, weight=ft.FontWeight.BOLD), ft.FilledButton("Refresh", bgcolor=GOLD_SOFT, color="#161616", on_click=lambda _: app.page.go("/marketplace"))]), grid])
    return _main_shell(app, "/marketplace", "Trade digital ownership", body)


def build_upload_view(app):
    picked = {"path": ""}
    selected = ft.Text("No file selected", color=MUTED)
    asset_name, description = _input("Asset Name"), ft.TextField(label="Description", multiline=True, min_lines=2, max_lines=4, border_radius=14, bgcolor="#0E1218", border_color=BORDER, focused_border_color=GOLD, color=TEXT)
    file_type = ft.Dropdown(label="File Type", value="jpg", options=[ft.dropdown.Option("jpg"), ft.dropdown.Option("png")], border_radius=14, bgcolor="#070809", border_color="#6B4E29", focused_border_color=GOLD)
    cost = _input("Price")

    def on_pick(e):
        if e.files:
            picked["path"] = e.files[0].path
            selected.value = e.files[0].name
            selected.color = TEXT
            app.page.update()

    picker = getattr(app.page, "_upload_picker", None)
    if picker is None:
        picker = ft.FilePicker(on_result=on_pick)
        app.page.services.append(picker)
        setattr(app.page, "_upload_picker", picker)
    else:
        picker.on_result = on_pick

    def do_upload(_):
        try:
            if not picked["path"]:
                raise RuntimeError("Choose a file first")
            app.upload_asset(picked["path"], asset_name.value, description.value, file_type.value, float(cost.value or 0))
            app.notify("Upload complete")
            app.page.go("/marketplace")
        except Exception as e:
            app.notify(str(e), error=True)

    body = ft.Container(width=680, bgcolor=CARD, border_radius=18, border=ft.border.all(1, BORDER), padding=20, content=ft.Column(spacing=12, controls=[ft.Row(spacing=10, controls=[ft.FilledButton("Choose File", on_click=lambda _: picker.pick_files(allow_multiple=False)), selected]), asset_name, description, file_type, cost, ft.FilledButton("Upload Asset", bgcolor=GOLD, color="#171717", on_click=do_upload)]))
    return _main_shell(app, "/upload", "Mint a new asset", body)


def build_wallet_settings_view(app):
    status = ft.Text("Wallet not loaded", color=ERROR, size=13)
    preview = ft.Text("", color=MUTED, selectable=True, size=12)
    local_wallet_path = "Client/wallets/{username}/wallet.json".format(username=app.state.username or "")

    import_picker = getattr(app.page, "_wallet_import_picker", None)
    export_picker = getattr(app.page, "_wallet_export_picker", None)

    def refresh_wallet_ui():
        if app.state.wallet_loaded and app.wallet_session:
            status.value = "Wallet ready for this session"
            status.color = SUCCESS
            preview.value = app.wallet_preview()
        else:
            status.value = "Wallet not loaded"
            status.color = ERROR
            preview.value = ""
        app.page.update()

    def on_import_result(e):
        try:
            if not e.files:
                return
            app.load_wallet_from_file(e.files[0].path)
            app.notify("Wallet imported and loaded")
            refresh_wallet_ui()
        except Exception as exc:
            app.notify(str(exc), error=True)

    def on_export_result(e):
        try:
            if not e.path:
                return
            app.export_wallet(e.path)
            app.notify("Wallet exported")
        except Exception as exc:
            app.notify(str(exc), error=True)

    if import_picker is None:
        import_picker = ft.FilePicker(on_result=on_import_result)
        app.page.services.append(import_picker)
        setattr(app.page, "_wallet_import_picker", import_picker)
    else:
        import_picker.on_result = on_import_result

    if export_picker is None:
        export_picker = ft.FilePicker(on_result=on_export_result)
        app.page.services.append(export_picker)
        setattr(app.page, "_wallet_export_picker", export_picker)
    else:
        export_picker.on_result = on_export_result

    def generate_wallet(_):
        try:
            app.generate_new_wallet()
            app.notify("New wallet generated on client and public key updated")
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

    def import_wallet(_):
        import_picker.pick_files(allow_multiple=False, allowed_extensions=["json"])

    def export_wallet(_):
        if not app.state.wallet_loaded:
            app.notify("Load or generate wallet first", error=True)
            return
        export_picker.save_file(
            dialog_title="Save wallet.json",
            file_name=f"wallet_{app.state.username}.json",
            allowed_extensions=["json"],
        )

    def continue_market(_):
        if not app.state.wallet_loaded:
            app.notify("Wallet setup is required before marketplace", error=True)
            return
        app.page.go("/marketplace")

    refresh_wallet_ui()

    body = ft.Container(
        width=860,
        bgcolor=CARD,
        border_radius=22,
        border=ft.border.all(1, BORDER),
        padding=24,
        content=ft.Column(
            spacing=14,
            controls=[
                ft.Text("Wallet Settings", color=TEXT, size=24, weight=ft.FontWeight.BOLD),
                ft.Text("Private key stays local only. Public key is sent to server.", color=MUTED, size=12),
                ft.Container(
                    bgcolor="#141A22",
                    border=ft.border.all(1, "#2D3A4A"),
                    border_radius=14,
                    padding=12,
                    content=ft.Column(
                        spacing=8,
                        controls=[
                            ft.Text(f"User: {app.state.username}", color=GOLD_SOFT, size=13),
                            ft.Text(f"Default local wallet: {local_wallet_path}", color=MUTED, size=11),
                            status,
                        ],
                    ),
                ),
                ft.Row(
                    wrap=True,
                    spacing=10,
                    run_spacing=10,
                    controls=[
                        ft.FilledButton("Generate New Wallet", bgcolor=GOLD, color="#171717", on_click=generate_wallet),
                        ft.OutlinedButton("Load Local Wallet", on_click=load_default),
                        ft.OutlinedButton("Import Wallet (.json)", on_click=import_wallet),
                        ft.OutlinedButton("Download Wallet", on_click=export_wallet),
                    ],
                ),
                ft.Container(
                    bgcolor="#0C1017",
                    border=ft.border.all(1, "#26303F"),
                    border_radius=14,
                    padding=12,
                    content=preview,
                ),
                ft.Row(
                    alignment=ft.MainAxisAlignment.END,
                    controls=[ft.FilledButton("Continue to Marketplace", bgcolor=SUCCESS, color="white", on_click=continue_market)],
                ),
            ],
        ),
    )
    return _main_shell(app, "/wallet", "Mandatory wallet identity", body)


def build_notifications_view(app):
    rows = [ft.Container(bgcolor=CARD_SOFT, border_radius=12, border=ft.border.all(1, BORDER), padding=12, content=ft.Text(msg, color=TEXT, size=13)) for msg in app.state.notifications] or [ft.Text("No notifications", color=MUTED)]
    return _main_shell(app, "/notifications", "System updates", ft.Column(spacing=10, controls=rows))


def build_my_assets_view(app):
    mine = [it for it in app.state.market_items if it.owner == (app.state.username or "")]
    cards = [ft.Container(col={"xs": 12, "sm": 6, "md": 4}, content=_asset_card(it)) for it in mine]
    body = ft.Column(spacing=12, controls=[ft.Text("Your collection", color=TEXT, size=20, weight=ft.FontWeight.BOLD), ft.ResponsiveRow(spacing=10, run_spacing=10, controls=cards) if cards else ft.Container(padding=20, content=ft.Text("You don't own assets yet.", color=MUTED))])
    return _main_shell(app, "/my_assets", "Personal portfolio", body)
