from __future__ import annotations

"""
pages.py — all Flet UI pages for the Aurex client.

Each build_*_view(app) function returns a ft.View ready to be pushed onto
app.page.views.  They are pure UI — no business logic, no direct server calls.
All actions go through the ClientApp methods in client.py.
"""
__author__ = "Nadav"
import base64
import flet as ft
import logging
import threading
import time
from pathlib import Path

logger = logging.getLogger("aurex.pages")

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

GLOW = [ft.BoxShadow(blur_radius=40, spread_radius=-4, color="#55E9BD4B", offset=ft.Offset(0, 8))]
SHADOW = [ft.BoxShadow(blur_radius=16, color="#50000000", offset=ft.Offset(0, 4))]


def bg(content):
    return ft.Container(expand=True,
        image=ft.DecorationImage(src="images/gold_bg.png", fit=ft.BoxFit.COVER),
        content=ft.Container(expand=True, bgcolor=SCRIM, content=content))


def logo_block(title="AUREX"):
    return ft.Column(spacing=8, horizontal_alignment=ft.CrossAxisAlignment.CENTER, controls=[
        ft.Container(padding=12, border_radius=20, bgcolor="#120F00",
            border=ft.border.all(1.5, GOLD_DIM),
            shadow=[ft.BoxShadow(blur_radius=20, color="#60E9BD4B", offset=ft.Offset(0, 0))],
            content=ft.Image(src="images/gold_icon.png", width=52, height=52, fit=ft.BoxFit.CONTAIN)),
        ft.Text(title, size=26, weight=ft.FontWeight.BOLD, color=GOLD, style=ft.TextStyle(letter_spacing=7)),
        ft.Container(width=48, height=1.5, bgcolor=GOLD_DIM, border_radius=2),
    ])


def divider():
    return ft.Row(spacing=8, controls=[
        ft.Container(expand=True, height=1, bgcolor="#1E1810"),
        ft.Text("◆", color="#3A2C10", size=8),
        ft.Container(expand=True, height=1, bgcolor="#1E1810"),
    ])


def auth_shell(route, body):
    return ft.View(route=route, bgcolor=BG, padding=0,
        controls=[bg(ft.Container(expand=True, alignment=ft.Alignment(0, 0), content=body))])


def nav_btn(app, text, route):
    active = app.page.route == route
    return ft.OutlinedButton(text, on_click=lambda _: app.page.go(route),
        style=ft.ButtonStyle(
            color=GOLD if active else MUTED,
            side=ft.BorderSide(1.5 if active else 1, GOLD if active else "#252535"),
            bgcolor="#1E1800" if active else "#0A0C14",
            shape=ft.RoundedRectangleBorder(radius=9),
            padding=ft.padding.symmetric(horizontal=14, vertical=7),
        ))


def logout(app):
    try:
        app.logout()
        app.notify("Logged out")
    except Exception as e:
        app.notify(str(e), error=True)
    app.page.go("/login")


def main_shell(app, route, title, body):
    # Notification button with red badge overlay
    notif_count = app.state.unseen_notifications
    badge = ft.Container(
        content=ft.Text(str(min(notif_count, 99)), color="white", size=8, weight=ft.FontWeight.BOLD,
            text_align=ft.TextAlign.CENTER),
        bgcolor=ERROR,
        width=16, height=16,
        border_radius=8,
        alignment=ft.Alignment(0, 0),
        top=1, right=1,
        visible=notif_count > 0,
    )
    app.notification_badge = badge
    notif_btn = nav_btn(app, "Notifications", "/notifications")
    notif_with_badge = ft.Stack(
        controls=[notif_btn, badge],
        clip_behavior=ft.ClipBehavior.NONE,
    )

    nav = ft.Row(wrap=True, run_spacing=6, spacing=6, controls=[
        nav_btn(app, "Market", "/marketplace"),
        nav_btn(app, "My Assets", "/my_assets"),
        nav_btn(app, "Upload", "/upload"),
        nav_btn(app, "Settings", "/settings"),
        notif_with_badge,
        ft.FilledButton("Logout", bgcolor="#3A0C14", color="#FF8A8A",
            style=ft.ButtonStyle(shape=ft.RoundedRectangleBorder(radius=9), padding=ft.padding.symmetric(horizontal=14, vertical=7)),
            on_click=lambda _: logout(app)),
    ])
    back_btn = ft.IconButton(icon=ft.Icons.ARROW_BACK_IOS_NEW_ROUNDED, icon_color=GOLD_SOFT, icon_size=15,
        tooltip="Back", visible=route != "/marketplace", on_click=lambda _: app.page.go("/marketplace"))

    # Balance display — reference stored on app so the balance monitor can update it
    balance_text = ft.Text(f"{app.state.balance:.2f} AUR", color=GOLD_SOFT, size=11,
        weight=ft.FontWeight.W_600)
    app._balance_text = balance_text

    username = app.state.username or ""
    head = ft.Container(
        border_radius=16, bgcolor=GLASS, border=ft.border.all(1, "#5C4220"),
        padding=ft.padding.symmetric(horizontal=20, vertical=13), shadow=SHADOW,
        content=ft.Row(alignment=ft.MainAxisAlignment.SPACE_BETWEEN, vertical_alignment=ft.CrossAxisAlignment.CENTER, controls=[
            ft.Row(spacing=10, controls=[
                back_btn,
                ft.Container(padding=6, border_radius=10, bgcolor="#120F00", border=ft.border.all(1, GOLD_DIM),
                    content=ft.Image(src="images/gold_icon.png", width=26, height=26, fit=ft.BoxFit.CONTAIN)),
                ft.Column(spacing=0, tight=True, controls=[
                    ft.Text("AUREX", color=GOLD, size=17, weight=ft.FontWeight.BOLD, style=ft.TextStyle(letter_spacing=3)),
                    ft.Text(title, color=MUTED, size=11),
                ]),
                ft.Container(width=8),
                ft.Container(
                    bgcolor="#0A0C12", border=ft.border.all(1, BORDER_DIM), border_radius=8,
                    padding=ft.padding.symmetric(horizontal=10, vertical=5),
                    content=ft.Text(f"Hello, {username}", color=GOLD_SOFT, size=17,
                        weight=ft.FontWeight.W_600),
                ),
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
        bg(ft.Container(expand=True, padding=ft.padding.symmetric(horizontal=20, vertical=16),
            content=ft.Column(scroll=ft.ScrollMode.AUTO, spacing=12, controls=[head, body])))
    ])


def input(label, password=False, icon=None):
    return ft.TextField(label=label, password=password, can_reveal_password=password,
        border_radius=11, bgcolor="#060709", border_color="#2E2218",
        focused_border_color=GOLD, color=TEXT, cursor_color=GOLD, text_size=15,
        label_style=ft.TextStyle(color=MUTED, size=14),
        prefix_icon=icon, content_padding=ft.padding.symmetric(horizontal=16, vertical=13))


def build_login_view(app):
    username = input("Username", icon=ft.Icons.PERSON_OUTLINE_ROUNDED)
    password = input("Password", True, icon=ft.Icons.LOCK_OUTLINE_ROUNDED)
    err_label = ft.Text("", color=ERROR, size=12, visible=False, text_align=ft.TextAlign.CENTER)

    def clear():
        err_label.value = ""; err_label.visible = False
        username.error_text = None; password.error_text = None

    def on_login(_):
        clear()
        u = (username.value or "").strip()
        p = password.value or ""
        valid = True
        if not u:
            username.error_text = "Username is required"; valid = False
        if not p:
            password.error_text = "Password is required"; valid = False
        if not valid:
            app.page.update(); return
        try:
            app.login(u, p)
            app.page.go("/settings")
        except Exception as e:
            msg = str(e)
            err_label.value = msg
            err_label.visible = True
            # Also hint on the offending field when identifiable
            lmsg = msg.lower()
            if "not found" in lmsg or "username" in lmsg:
                username.error_text = "Unknown username"
            elif "password" in lmsg or "incorrect" in lmsg:
                password.error_text = "Incorrect password"
            app.page.update()

    card = ft.Container(width=440, padding=ft.padding.symmetric(horizontal=36, vertical=32),
        border_radius=24, bgcolor=CARD, border=ft.border.all(1, BORDER), shadow=GLOW,
        content=ft.Column(spacing=18, horizontal_alignment=ft.CrossAxisAlignment.CENTER, controls=[
            logo_block(),
            ft.Text("Secure marketplace access", color=MUTED, size=12, style=ft.TextStyle(letter_spacing=1.5)),
            divider(),
            username, password,
            err_label,
            ft.FilledButton("Sign In", width=368, height=46, bgcolor=GOLD, color="#130E00",
                style=ft.ButtonStyle(shape=ft.RoundedRectangleBorder(radius=12)), on_click=on_login),
            ft.Row(alignment=ft.MainAxisAlignment.SPACE_BETWEEN, controls=[
                ft.TextButton("Create account", style=ft.ButtonStyle(color=MUTED), on_click=lambda _: app.page.go("/signup")),
                ft.TextButton("Forgot password?", style=ft.ButtonStyle(color=GOLD_DIM), on_click=lambda _: app.page.go("/forgot")),
            ]),
        ]))
    return auth_shell("/login", card)


def build_signup_view(app):
    username = input("Username", icon=ft.Icons.PERSON_OUTLINE_ROUNDED)
    password = input("Password", True, icon=ft.Icons.LOCK_OUTLINE_ROUNDED)
    email = input("Email address", icon=ft.Icons.EMAIL_OUTLINED)
    err_label = ft.Text("", color=ERROR, size=12, visible=False, text_align=ft.TextAlign.CENTER)

    def clear():
        err_label.value = ""; err_label.visible = False
        username.error_text = None; password.error_text = None; email.error_text = None

    def on_signup(_):
        clear()
        u = (username.value or "").strip()
        p = password.value or ""
        e_val = (email.value or "").strip()
        valid = True
        if not u:
            username.error_text = "Username is required"; valid = False
        if not p:
            password.error_text = "Password is required"; valid = False
        elif len(p) < 6:
            password.error_text = "Minimum 6 characters"; valid = False
        _parts = e_val.split("@")
        if not e_val or len(_parts) != 2 or not _parts[0] or "." not in _parts[1]:
            email.error_text = "Enter a valid email address (e.g. user@example.com)"; valid = False
        if not valid:
            app.page.update(); return
        try:
            app.signup(u, p, e_val)
            app.notify("Account created")
            app.page.go("/login")
        except Exception as e:
            msg = str(e)
            err_label.value = msg; err_label.visible = True
            lmsg = msg.lower()
            if "username" in lmsg or "already exists" in lmsg:
                username.error_text = "Already taken"
            elif "email" in lmsg:
                email.error_text = "Email already registered"
            app.page.update()

    card = ft.Container(width=460, padding=ft.padding.symmetric(horizontal=36, vertical=28),
        border_radius=24, bgcolor=CARD, border=ft.border.all(1, BORDER), shadow=GLOW,
        content=ft.Column(spacing=15, horizontal_alignment=ft.CrossAxisAlignment.CENTER, controls=[
            ft.Row(controls=[ft.IconButton(icon=ft.Icons.ARROW_BACK_IOS_NEW_ROUNDED, icon_color=MUTED, icon_size=15,
                on_click=lambda _: app.page.go("/login"))]),
            logo_block("JOIN AUREX"),
            username, password, email,
            err_label,
            ft.FilledButton("Create Account", width=388, height=46, bgcolor=GOLD, color="#130E00",
                style=ft.ButtonStyle(shape=ft.RoundedRectangleBorder(radius=12)), on_click=on_signup),
        ]))
    return auth_shell("/signup", card)


def build_forgot_view(app):
    # ── Fields ───────────────────────────────────────────────────────────────
    email    = input("Email address", icon=ft.Icons.EMAIL_OUTLINED)
    code     = input("Verification code", icon=ft.Icons.VERIFIED_OUTLINED)
    new_pass = input("New password", True, icon=ft.Icons.LOCK_RESET_OUTLINED)

    err_label = ft.Text("", color=ERROR,   size=12, visible=False, text_align=ft.TextAlign.CENTER)
    ok_label  = ft.Text("", color=SUCCESS, size=12, visible=False, text_align=ft.TextAlign.CENTER)

    def show_err(msg):
        ok_label.visible = False; err_label.value = msg; err_label.visible = True
        app.page.update()

    def show_ok(msg):
        err_label.visible = False; ok_label.value = msg; ok_label.visible = True
        app.page.update()

    def clear_msg():
        err_label.visible = False; ok_label.visible = False

    # ── Stage 2: code section (locked until code is sent) ────────────────────
    code_section = ft.Container(
        visible=False,
        content=ft.Column(spacing=10, horizontal_alignment=ft.CrossAxisAlignment.STRETCH, controls=[
            ft.Container(height=1, bgcolor=BORDER_DIM),
            ft.Text("Step 2 — Enter the code from your email", color=MUTED, size=11),
            code,
            ft.FilledButton("Verify Code", bgcolor="#0E1C0E", color=SUCCESS,
                style=ft.ButtonStyle(shape=ft.RoundedRectangleBorder(radius=9),
                    side=ft.BorderSide(1, "#2A4A2A")),
                on_click=lambda _: do_verify()),
        ]),
    )

    # ── Stage 3: password section (locked until code verified) ───────────────
    password_section = ft.Container(
        visible=False,
        content=ft.Column(spacing=10, horizontal_alignment=ft.CrossAxisAlignment.STRETCH, controls=[
            ft.Container(height=1, bgcolor=BORDER_DIM),
            ft.Text("Step 3 — Set your new password", color=MUTED, size=11),
            new_pass,
            ft.FilledButton("Update Password", height=44, bgcolor=GOLD, color="#130E00",
                style=ft.ButtonStyle(shape=ft.RoundedRectangleBorder(radius=12)),
                on_click=lambda _: do_reset()),
        ]),
    )

    # ── Handlers ─────────────────────────────────────────────────────────────
    def do_send(_=None):
        clear_msg()
        e = (email.value or "").strip()
        _ep = e.split("@")
        if not e or len(_ep) != 2 or not _ep[0] or "." not in _ep[1]:
            email.error_text = "Enter a valid email address (e.g. user@example.com)"; app.page.update(); return
        email.error_text = None
        try:
            app.send_code(e)
            show_ok("Code sent — check your email")
            code_section.visible = True
            code.error_text = None
            app.page.update()
        except Exception as ex:
            show_err(str(ex))

    def do_verify(_=None):
        clear_msg()
        e = (email.value or "").strip()
        c = (code.value or "").strip()
        if not c:
            code.error_text = "Enter the verification code"; app.page.update(); return
        code.error_text = None
        try:
            app.verify_code(e, c)
            show_ok("Code verified — set your new password below")
            password_section.visible = True
            new_pass.error_text = None
            app.page.update()
        except Exception as ex:
            code.error_text = str(ex); show_err(str(ex))

    def do_reset(_=None):
        clear_msg()
        e = (email.value or "").strip()
        c = (code.value or "").strip()
        p = new_pass.value or ""
        if not p:
            new_pass.error_text = "Required"; app.page.update(); return
        if len(p) < 6:
            new_pass.error_text = "Minimum 6 characters"; app.page.update(); return
        new_pass.error_text = None
        try:
            app.update_password(e, p, c)
            show_ok("Password updated! Redirecting...")
            app.page.go("/login")
        except Exception as ex:
            show_err(str(ex))

    # ── Card ─────────────────────────────────────────────────────────────────
    card = ft.Container(width=480, padding=ft.padding.symmetric(horizontal=36, vertical=28),
        border_radius=24, bgcolor=CARD, border=ft.border.all(1, BORDER), shadow=GLOW,
        content=ft.Column(spacing=14, horizontal_alignment=ft.CrossAxisAlignment.CENTER, controls=[
            ft.Row(controls=[ft.IconButton(icon=ft.Icons.ARROW_BACK_IOS_NEW_ROUNDED, icon_color=MUTED, icon_size=15,
                on_click=lambda _: app.page.go("/login"))]),
            logo_block("RESET ACCESS"),
            # Step 1 — always visible
            ft.Text("Step 1 — Enter your email", color=MUTED, size=11),
            email,
            ft.FilledButton("Send Code", bgcolor="#1C1400", color=GOLD_SOFT,
                width=408, height=42,
                style=ft.ButtonStyle(shape=ft.RoundedRectangleBorder(radius=9), side=ft.BorderSide(1, BORDER)),
                on_click=do_send),
            err_label, ok_label,
            # Steps 2 & 3 — revealed progressively
            code_section,
            password_section,
        ]))
    return auth_shell("/forgot", card)


STATUS_COLOR = {
    "FOR_SALE": SUCCESS,
    "PENDING":  GOLD_DIM,
    "UNLISTED": MUTED,
    "SOLD":     ERROR,
}
STATUS_LABEL = {
    "FOR_SALE": "For Sale",
    "PENDING":  "Pending",
    "UNLISTED": "Unlisted",
    "SOLD":     "Sold",
}


def open_zoomed_card(app, item, context="marketplace"):
    """Open an elegant full-detail asset dialog — the 'zoomed card'."""
    is_own_username = item.owner == (app.state.username or "")
    # Blockchain-signed actions (Unlist, Upload to Market) require the CURRENT
    # wallet key to match the key used at upload time.  Username alone is not
    # sufficient — a new wallet means a new key and the old asset can't be signed.
    _wallet_pk = app.state.wallet_public_key or ""
    _item_pk   = getattr(item, "public_key", "") or ""
    is_pk_owner = is_own_username and bool(_wallet_pk) and _wallet_pk == _item_pk
    is_own = is_own_username  # kept for Buy/display guards (can't buy own asset)
    s_color   = STATUS_COLOR.get(item.asset_status, MUTED)
    s_label   = STATUS_LABEL.get(item.asset_status, item.asset_status)

    # _overlay_ref is populated in do_open() so close() can remove the right object.
    _overlay_ref: list = []

    def close(_=None):
        async def _do():
            try:
                if _overlay_ref and _overlay_ref[0] in app.page.overlay:
                    app.page.overlay.remove(_overlay_ref[0])
                app.page.on_keyboard_event = None
                app.page.update()
            except Exception:
                pass
        app.page.run_task(_do)

    # ── Action buttons (same logic as the small card) ────────────────────────
    def do_buy(_):
        close()
        if app.gateway_online is False:
            app.notify("Gateway server is unreachable. Buying assets is currently unavailable.", error=True)
            return
        try:
            app.buy_asset(item)
            app.notify("Purchase request signed and sent")
        except Exception as e:
            app.notify(str(e), error=True)

    def do_upload_to_market(_):
        close()
        if app.gateway_online is False:
            app.notify("Gateway server is unreachable. Upload to marketplace is currently unavailable.", error=True)
            return
        try:
            resp = app.move_to_marketplace(item.asset_id)
            if str(resp.get("type", "")).upper() in ("MOVE_PENDING", "MOVE_SUCCESS"):
                app.notify(f"'{item.asset_name}' sent to mining — will appear on marketplace once confirmed")
            app.page.go("/marketplace")
        except Exception as e:
            app.notify(str(e), error=True)

    def do_delete(_):
        close()
        try:
            app.delete_asset(item.asset_id)
            app.notify("Asset deleted")
            app.page.go("/my_assets")
        except Exception as e:
            app.notify(str(e), error=True)

    def do_unlist(_):
        close()
        if app.gateway_online is False:
            app.notify("Gateway server is unreachable. Unlisting is currently unavailable.", error=True)
            return
        try:
            app.unlist_asset(item.asset_id)
            app.notify("Unlist request submitted — will update once confirmed")
            app.page.go("/marketplace")
        except Exception as e:
            app.notify(str(e), error=True)

    actions = []
    if context == "my_assets":
        actions.append(ft.OutlinedButton("Delete", on_click=do_delete,
            style=ft.ButtonStyle(color=ERROR, side=ft.BorderSide(1, ERROR),
                shape=ft.RoundedRectangleBorder(radius=8),
                padding=ft.padding.symmetric(horizontal=14, vertical=8))))
        # Upload To Market requires the current wallet key to match the asset's key
        if is_pk_owner and item.asset_status in ("PENDING", "UNLISTED"):
            actions.append(ft.FilledButton("→ Upload To Market", bgcolor="#0E1C0E", color=SUCCESS,
                style=ft.ButtonStyle(shape=ft.RoundedRectangleBorder(radius=8),
                    side=ft.BorderSide(1, SUCCESS), padding=ft.padding.symmetric(horizontal=14, vertical=8)),
                on_click=do_upload_to_market))
    elif context == "marketplace":
        # Unlist requires current wallet key to match the key that uploaded the asset
        if is_pk_owner:
            actions.append(ft.OutlinedButton("Unlist", on_click=do_unlist,
                style=ft.ButtonStyle(color=GOLD_DIM, side=ft.BorderSide(1, GOLD_DIM),
                    shape=ft.RoundedRectangleBorder(radius=8),
                    padding=ft.padding.symmetric(horizontal=16, vertical=8))))
        elif not is_own:
            actions.append(ft.FilledButton("Buy Now", bgcolor=GOLD, color="#130E00", on_click=do_buy,
                style=ft.ButtonStyle(shape=ft.RoundedRectangleBorder(radius=8),
                    padding=ft.padding.symmetric(horizontal=20, vertical=8))))

    # ── Image ────────────────────────────────────────────────────────────────
    img_box = ft.Container(
        width=520, height=300, bgcolor="#07080C",
        border_radius=ft.border_radius.only(top_left=20, top_right=20),
        clip_behavior=ft.ClipBehavior.ANTI_ALIAS,
        alignment=ft.Alignment(0, 0),
        content=ft.Icon(ft.Icons.IMAGE_OUTLINED, color="#1E2030", size=60),
    )

    def _load_zoomed_image():
        try:
            path = app.image_cache.get_path(item.asset_id)
            if path and path.exists():
                img_box.content = ft.Image(
                    src=str(path),
                    fit=ft.BoxFit.CONTAIN,
                    width=520, height=300,
                )
                async def _upd():
                    try:
                        app.page.update()
                    except Exception:
                        pass
                app.page.run_task(_upd)
        except Exception:
            pass

    threading.Thread(target=_load_zoomed_image, daemon=True).start()

    close_btn = ft.Container(
        width=36, height=36, border_radius=18,
        bgcolor="#1A1200",
        border=ft.border.all(1.5, GOLD),
        alignment=ft.Alignment(0, 0),
        on_click=close,
        tooltip="Close (Esc)",
        content=ft.Icon(ft.Icons.CLOSE_ROUNDED, color=GOLD, size=18),
    )

    img_section = ft.Stack(controls=[
        img_box,
        ft.Container(content=close_btn, right=10, top=10),
    ])

    # ── Badges ───────────────────────────────────────────────────────────────
    def badge(label, text_color, border_color, bg="#08090D"):
        return ft.Container(border_radius=6, bgcolor=bg, border=ft.border.all(1, border_color),
            padding=ft.padding.symmetric(horizontal=9, vertical=4),
            content=ft.Text(label, color=text_color, size=10, weight=ft.FontWeight.BOLD))

    # ── Date ─────────────────────────────────────────────────────────────────
    try:
        from datetime import datetime as dt
        date_str = dt.fromisoformat(item.created_at).strftime("%d %b %Y") if item.created_at else ""
    except Exception:
        date_str = str(item.created_at or "")

    # ── Details pane ─────────────────────────────────────────────────────────
    details = ft.Container(
        padding=ft.padding.only(left=26, right=26, top=22, bottom=22),
        content=ft.Column(spacing=12, controls=[
            # Title
            ft.Text(item.asset_name, color=TEXT, size=21, weight=ft.FontWeight.BOLD, selectable=True),
            # Meta row
            ft.Row(spacing=8, vertical_alignment=ft.CrossAxisAlignment.CENTER, wrap=True, controls=[
                ft.Text(f"by {item.owner}", color=MUTED, size=12),
                *([ ft.Text("·", color=BORDER, size=12),
                    ft.Text(date_str, color=MUTED, size=11) ] if date_str else []),
                badge(s_label, s_color, s_color),
                badge((item.file_type or "?").upper(), GOLD_DIM, BORDER, bg="#120F00"),
            ]),
            # Description box
            ft.Container(
                bgcolor="#07080C", border_radius=10,
                border=ft.border.all(1, "#141820"),
                padding=ft.padding.symmetric(horizontal=16, vertical=12),
                visible=bool(item.description),
                content=ft.Text(item.description or "", color="#8A9AAA", size=13,
                    selectable=True),
            ),
            ft.Container(height=1, bgcolor=BORDER_DIM),
            # Price + action row
            ft.Row(alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
                vertical_alignment=ft.CrossAxisAlignment.CENTER,
                controls=[
                    ft.Row(spacing=4, vertical_alignment=ft.CrossAxisAlignment.BASELINE, controls=[
                        ft.Text(f"{item.cost:.2f}", color=GOLD, size=30,
                            weight=ft.FontWeight.BOLD),
                        ft.Text("AUR", color=GOLD_DIM, size=13),
                    ]),
                    ft.Row(spacing=8, controls=actions),
                ]),
        ]),
    )

    # ── Compose the card ─────────────────────────────────────────────────────
    card = ft.Container(
        width=520,
        bgcolor="#0D0F14",
        border_radius=20,
        clip_behavior=ft.ClipBehavior.ANTI_ALIAS,
        shadow=ft.BoxShadow(
            blur_radius=48, spread_radius=2,
            color="#88000000", offset=ft.Offset(0, 12),
        ),
        content=ft.Column(spacing=0, tight=True, controls=[img_section, details]),
    )

    # ── Full-screen overlay: backdrop (clickable to close) + centred card ────
    # We build this ourselves instead of using ft.AlertDialog because AlertDialog
    # collapses its content in newer Flet versions when content_padding=0 or when
    # no title/actions are supplied.  Adding a plain Stack to page.overlay is
    # rock-solid across all Flet versions.
    backdrop = ft.Container(
        expand=True,
        bgcolor="#CC000000",
        on_click=close,   # click outside card → close
    )

    # Container that fills the screen and centres the card.
    # We do NOT put on_click here — clicks on the card itself don't bubble up
    # to the backdrop in Flet, so the backdrop handler only fires on empty space.
    centre = ft.Container(
        expand=True,
        alignment=ft.alignment.center,
        content=card,
    )

    overlay = ft.Stack(
        expand=True,
        controls=[backdrop, centre],
    )

    def _on_key(e: ft.KeyboardEvent):
        if e.key == "Escape":
            close()

    async def do_open():
        _overlay_ref.append(overlay)   # let the single close() find the overlay
        if overlay not in app.page.overlay:
            app.page.overlay.append(overlay)
        app.page.on_keyboard_event = _on_key
        app.page.update()

    app.page.run_task(do_open)


def asset_card(app, item, context="marketplace"):
    is_own_username = item.owner == (app.state.username or "")
    _wallet_pk = app.state.wallet_public_key or ""
    _item_pk   = getattr(item, "public_key", "") or ""
    is_pk_owner = is_own_username and bool(_wallet_pk) and _wallet_pk == _item_pk
    is_own = is_own_username  # kept for Buy guard (can't buy your own asset)
    status_color = STATUS_COLOR.get(item.asset_status, MUTED)
    status_label = STATUS_LABEL.get(item.asset_status, item.asset_status)

    # ── Action callbacks ────────────────────────────────────────────────────────

    def do_buy(_):
        if app.gateway_online is False:
            app.notify("Gateway server is unreachable. Buying assets is currently unavailable.", error=True)
            return
        try:
            app.buy_asset(item)
            app.notify("Purchase request signed and sent")
        except Exception as e:
            app.notify(str(e), error=True)

    def do_upload_to_market(_):
        if app.gateway_online is False:
            app.notify("Gateway server is unreachable. Upload to marketplace is currently unavailable.", error=True)
            return
        try:
            resp = app.move_to_marketplace(item.asset_id)
            resp_type = str(resp.get("type", "")).upper()
            if resp_type in ("MOVE_PENDING", "MOVE_SUCCESS"):
                app.notify(f"'{item.asset_name}' sent to mining — will appear on marketplace once confirmed")
            app.page.go("/marketplace")
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
        if app.gateway_online is False:
            app.notify("Gateway server is unreachable. Unlisting is currently unavailable.", error=True)
            return
        try:
            app.unlist_asset(item.asset_id)
            app.notify("Unlist request submitted — will update once confirmed")
            app.page.go("/marketplace")
        except Exception as e:
            app.notify(str(e), error=True)

    def on_hover(e):
        e.control.border = ft.border.all(1, GOLD_DIM if e.data == "true" else BORDER_DIM)
        e.control.shadow = SHADOW if e.data == "true" else []
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
        on_click=lambda _: open_zoomed_card(app, item, context),
        tooltip="Click to enlarge",
        content=ft.Stack(controls=[
            ft.Container(
                expand=True, height=160,
                alignment=ft.Alignment(0, 0),
                content=ft.Icon(ft.Icons.IMAGE_OUTLINED, color="#1E2030", size=40),
            ),
            # Subtle magnifier hint
            ft.Container(
                content=ft.Icon(ft.Icons.ZOOM_IN_ROUNDED, color="#44FFFFFF", size=16),
                bottom=6, right=6,
            ),
        ]),
    )

    def load_image():
        try:
            path = app.image_cache.get_path(item.asset_id)
            if path and path.exists():
                img_node = ft.Image(src=str(path), fit=ft.BoxFit.COVER, expand=True, height=160)
                # Keep zoom hint in a Stack over the loaded image
                img_container.content = ft.Stack(controls=[
                    ft.Container(expand=True, height=160,
                        clip_behavior=ft.ClipBehavior.ANTI_ALIAS,
                        content=img_node),
                    ft.Container(
                        content=ft.Icon(ft.Icons.ZOOM_IN_ROUNDED, color="#44FFFFFF", size=16),
                        bottom=6, right=6,
                    ),
                ])
                async def upd():
                    try:
                        img_container.update()
                    except Exception:
                        pass
                app.page.run_task(upd)
        except Exception as exc:
            logger.warning(f"Card image load error {item.asset_id}: {exc}")

    threading.Thread(target=load_image, daemon=True).start()

    # ── Action buttons ──────────────────────────────────────────────────────────
    action_controls = []

    if context == "my_assets":
        # Delete is always available — username ownership is enough (server-side op)
        action_controls.append(
            ft.OutlinedButton("Delete", on_click=do_delete,
                style=ft.ButtonStyle(
                    color=ERROR,
                    side=ft.BorderSide(1, ERROR),
                    shape=ft.RoundedRectangleBorder(radius=8),
                    padding=ft.padding.symmetric(horizontal=12, vertical=8),
                ))
        )
        # Upload To Market requires the current wallet key to match the asset's key
        if is_pk_owner and item.asset_status in ("PENDING", "UNLISTED"):
            action_controls.append(
                ft.FilledButton("→ Upload To Market", bgcolor="#0E1C0E", color=SUCCESS,
                    style=ft.ButtonStyle(shape=ft.RoundedRectangleBorder(radius=8),
                        side=ft.BorderSide(1, SUCCESS),
                        padding=ft.padding.symmetric(horizontal=12, vertical=8)),
                    on_click=do_upload_to_market)
            )

    elif context == "marketplace":
        # Unlist requires current wallet key to match the key that uploaded the asset
        if is_pk_owner:
            action_controls.append(
                ft.OutlinedButton("Unlist", on_click=do_unlist,
                    style=ft.ButtonStyle(
                        color=GOLD_DIM,
                        side=ft.BorderSide(1, GOLD_DIM),
                        shape=ft.RoundedRectangleBorder(radius=8),
                        padding=ft.padding.symmetric(horizontal=14, vertical=8),
                    ))
            )
        elif not is_own:
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
                ft.Text(f"{item.cost:.2f}", color=GOLD, size=18, weight=ft.FontWeight.BOLD),
                ft.Text("AUR", color=GOLD_DIM, size=10),
            ]),
            ft.Row(spacing=6, controls=action_controls),
        ])

    return ft.Container(
        bgcolor=CARD_SOFT, border_radius=14, border=ft.border.all(1, BORDER_DIM),
        padding=0, on_hover=on_hover,
        clip_behavior=ft.ClipBehavior.ANTI_ALIAS,
        content=ft.Column(spacing=0, controls=[
            img_container,
            ft.Container(padding=14, content=ft.Column(spacing=8, controls=[
                ft.Row(alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
                    vertical_alignment=ft.CrossAxisAlignment.START, controls=[
                    ft.Text(item.asset_name, color=TEXT, size=14, weight=ft.FontWeight.BOLD,
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
    # Clear stale removal sets — listed_asset_ids is NOT cleared here so that
    # events drained by _on_route_change before this call aren't lost.
    app.sold_asset_ids.clear()
    app.removed_asset_ids.clear()
    app.unlisted_asset_ids.clear()

    gateway_banner = ft.Container(
        visible=app.gateway_online is False,
        bgcolor="#1A0C00", border_radius=10,
        border=ft.border.all(1, "#6B3A00"),
        padding=ft.padding.symmetric(horizontal=14, vertical=10),
        content=ft.Row(spacing=10, vertical_alignment=ft.CrossAxisAlignment.CENTER, controls=[
            ft.Icon(ft.Icons.WIFI_OFF_ROUNDED, color="#E9883A", size=18),
            ft.Text(
                "Gateway server is unreachable. Buying assets is currently unavailable.",
                color="#E9883A", size=12,
            ),
        ]),
    )

    grid = ft.ResponsiveRow(spacing=10, run_spacing=10)
    status_text = ft.Text("Loading...", color=MUTED, size=12)
    card_map: dict[str, ft.Container] = {}
    active = [True]

    def load():
        try:
            id_entries = app.get_market_asset_ids()
        except Exception as exc:
            _msg = str(exc)  # capture before Python deletes exc on except-block exit
            async def err():
                status_text.value = f"Error: {_msg}"
                app.page.update()
            app.page.run_task(err)
            app.notify(_msg, error=True)
            return

        if not id_entries:
            async def empty():
                status_text.value = "No assets listed yet"
                app.page.update()
            app.page.run_task(empty)
            return

        async def init():
            status_text.value = f"Loading {len(id_entries)} asset(s)…"
            app.page.update()
        app.page.run_task(init)

        loaded = 0
        for entry in id_entries:
            if not active[0]:
                return
            asset_id = entry.get("id", "") if isinstance(entry, dict) else str(entry)
            version = entry.get("version", 1) if isinstance(entry, dict) else 1
            if not asset_id:
                continue
            item = app.load_asset_by_id(asset_id, version)  # network I/O in background thread
            if not item:
                continue
            card = asset_card(app, item)
            wrapper = ft.Container(col={"xs": 12, "sm": 6, "md": 4, "lg": 3}, content=card)
            card_map[asset_id] = wrapper
            loaded += 1
            n, total = loaded, len(id_entries)
            async def add(w=wrapper, n=n, total=total):
                if not active[0]:
                    return
                grid.controls.append(w)
                status_text.value = f"{n} / {total} loaded"
                app.page.update()
            app.page.run_task(add)

        final = loaded
        async def done():
            status_text.value = f"{final} asset{'s' if final != 1 else ''} listed"
            app.page.update()
        app.page.run_task(done)

    def monitor():
        prev_gateway_online = app.gateway_online
        while active[0]:
            time.sleep(2)
            if not active[0]:
                return
            app.drain_asset_events()

            # Add assets that just became FOR_SALE (FULLY_UPLOADED push event)
            new_ids = list(app.listed_asset_ids - set(card_map.keys()))
            for asset_id in new_ids:
                if not active[0]:
                    return
                app.listed_asset_ids.discard(asset_id)
                item = app.load_asset_by_id(asset_id)
                if not item:
                    continue
                card = asset_card(app, item)
                wrapper = ft.Container(col={"xs": 12, "sm": 6, "md": 4, "lg": 3}, content=card)
                card_map[asset_id] = wrapper
                n = len(card_map)
                async def _add_card(w=wrapper, n=n):
                    if not active[0]:
                        return
                    if w not in grid.controls:
                        grid.controls.append(w)
                    status_text.value = f"{n} asset{'s' if n != 1 else ''} listed"
                    app.page.update()
                app.page.run_task(_add_card)

            # Remove assets that left the marketplace (sold, unlisted, deleted)
            removed_ids = list(app.sold_asset_ids | app.removed_asset_ids | app.unlisted_asset_ids)
            changed = False
            for asset_id in removed_ids:
                wrapper = card_map.pop(asset_id, None)
                if wrapper and wrapper in grid.controls:
                    grid.controls.remove(wrapper)
                    changed = True
            if changed:
                n = len(card_map)
                async def remove_update(n=n):
                    status_text.value = f"{n} asset{'s' if n != 1 else ''} listed"
                    app.page.update()
                app.page.run_task(remove_update)
            # Update gateway banner if state changed
            if app.gateway_online != prev_gateway_online:
                prev_gateway_online = app.gateway_online
                async def update_banner(gw=app.gateway_online):
                    gateway_banner.visible = gw is False
                    try:
                        gateway_banner.update()
                    except Exception:
                        pass
                app.page.run_task(update_banner)

    def do_refresh(_):
        active[0] = False
        async def clear():
            grid.controls.clear()
            card_map.clear()
            status_text.value = "Loading..."
            status_text.color = MUTED
            app.page.update()
        app.page.run_task(clear)
        try:
            app.request_balance()
        except Exception as e:
            app.notify(str(e), error=True)
        active[0] = True
        threading.Thread(target=load, daemon=True).start()
        threading.Thread(target=monitor, daemon=True).start()

    threading.Thread(target=load, daemon=True).start()
    threading.Thread(target=monitor, daemon=True).start()

    body = ft.Column(spacing=14, controls=[
        gateway_banner,
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
    return main_shell(app, "/marketplace", "Trade digital ownership", body)


def build_upload_view(app):
    picked = {"path": "", "for_sale": True}
    selected = ft.Text("No file selected", color=MUTED, size=12)
    asset_name = input("Asset Name", icon=ft.Icons.TITLE_ROUNDED)
    description = ft.TextField(label="Description", multiline=True, min_lines=2, max_lines=4,
        border_radius=11, bgcolor="#060709", border_color="#2E2218", focused_border_color=GOLD,
        color=TEXT, label_style=ft.TextStyle(color=MUTED, size=12))
    cost = input("Price (AUR)", icon=ft.Icons.CURRENCY_EXCHANGE_ROUNDED)
    file_hint   = ft.Text("Select a file above to enable upload", color=MUTED, size=11, italic=True)
    upload_err  = ft.Text("", color=ERROR, size=12, visible=False)   # inline error below status
    upload_btn  = ft.FilledButton("Upload Asset", height=46, bgcolor=GOLD, color="#130E00",
        style=ft.ButtonStyle(shape=ft.RoundedRectangleBorder(radius=12)),
        disabled=True)

    def set_file_hint_error(msg):
        file_hint.value = msg
        file_hint.color = ERROR
        file_hint.italic = False
        file_hint.visible = True
        app.page.update()

    def clear_upload_err():
        upload_err.value = ""; upload_err.visible = False

    def btn_style(active):
        return ft.ButtonStyle(
            color=GOLD if active else MUTED,
            side=ft.BorderSide(1.5 if active else 1, GOLD if active else "#252535"),
            bgcolor="#1E1800" if active else "#0A0C14",
            shape=ft.RoundedRectangleBorder(radius=9),
            padding=ft.padding.symmetric(horizontal=18, vertical=9),
        )

    btn_marketplace = ft.OutlinedButton("Marketplace", style=btn_style(True))
    btn_my_assets = ft.OutlinedButton("My Assets", style=btn_style(False))

    def select_marketplace(_):
        picked["for_sale"] = True
        btn_marketplace.style = btn_style(True)
        btn_my_assets.style = btn_style(False)
        btn_marketplace.update()
        btn_my_assets.update()

    def select_my_assets(_):
        picked["for_sale"] = False
        btn_marketplace.style = btn_style(False)
        btn_my_assets.style = btn_style(True)
        btn_marketplace.update()
        btn_my_assets.update()

    btn_marketplace.on_click = select_marketplace
    btn_my_assets.on_click = select_my_assets

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

    async def choose_file_async():
        files = await picker.pick_files(
            allow_multiple=False,
            file_type=ft.FilePickerFileType.CUSTOM,
            allowed_extensions=["png", "jpg", "jpeg"],
        )
        if not files:
            return
        f = files[0]
        if not f.path:
            set_file_hint_error("Could not read file path — try again")
            return
        try:
            size = Path(f.path).stat().st_size
            if size == 0:
                set_file_hint_error("File is empty (0 bytes) — choose a valid image")
                return
            if size > 5 * 1024 * 1024:
                set_file_hint_error(f"File is too large ({size / 1024 / 1024:.1f} MB). Maximum is 5 MB.")
                return
        except Exception:
            set_file_hint_error("Cannot read the selected file")
            return
        picked["path"] = f.path
        selected.value = f.name
        selected.color = GOLD_SOFT
        file_hint.value = "Select a file above to enable upload"
        file_hint.color = MUTED
        file_hint.italic = True
        file_hint.visible = False
        upload_btn.disabled = False
        app.page.update()

    def choose_file(_):
        app.page.run_task(choose_file_async)

    status_text = ft.Text("", size=11, color=MUTED)

    def do_upload(_):
        clear_upload_err()
        asset_name.error_text = None
        cost.error_text = None
        # ── Gateway check for marketplace upload ───────────────────────────
        if picked["for_sale"] and app.gateway_online is False:
            upload_err.value = "Gateway server is unreachable. Switch to 'My Assets' to upload without the marketplace."
            upload_err.visible = True
            app.page.update()
            return
        # ── File validation ────────────────────────────────────────────────
        if not picked["path"]:
            set_file_hint_error("No file selected — click Choose File first")
            return
        try:
            file_size = Path(picked["path"]).stat().st_size
            if file_size == 0:
                set_file_hint_error("File is empty (0 bytes) — choose a valid image")
                return
            if file_size > 5 * 1024 * 1024:
                set_file_hint_error(f"File too large ({file_size / 1024 / 1024:.1f} MB). Maximum is 5 MB.")
                return
        except Exception:
            set_file_hint_error("Cannot read the selected file")
            return
        # ── Field validation ───────────────────────────────────────────────
        name_val = (asset_name.value or "").strip()
        if not name_val:
            asset_name.error_text = "Asset name is required"
            app.page.update()
            return
        try:
            cost_val = float(cost.value or 0)
            if cost_val < 0:
                raise ValueError
            cost.error_text = None
        except ValueError:
            cost.error_text = "Enter a valid non-negative price"
            app.page.update()
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
        async def initial_update():
            app.page.update()
        app.page.run_task(initial_update)

        for_sale_snap = picked["for_sale"]

        def upload_thread():
            def set_status(msg, color=MUTED):
                async def do():
                    status_text.value = msg
                    status_text.color = color
                    app.page.update()
                app.page.run_task(do)

            def show_error(msg):
                logger.error(f"[upload] {msg}")
                async def do():
                    status_text.value = ""
                    upload_err.value = str(msg)
                    upload_err.visible = True
                    upload_btn.disabled = False
                    app.page.update()
                app.page.run_task(do)

            try:
                logger.info(f"[upload] start path={path_snap!r} name={name_val!r} type={file_type} cost={cost_val} for_sale={for_sale_snap}")
                set_status("Uploading asset...")
                app.upload_asset(path_snap, name_val, desc_snap, file_type, cost_val, for_sale=for_sale_snap)
                logger.info("[upload] UPLOAD_SUCCESS — asset saved")
                async def success():
                    status_text.value = ""
                    app.page.snack_bar = ft.SnackBar(content=ft.Text("Upload complete!"), bgcolor="#136F3A")
                    app.page.snack_bar.open = True
                    app.page.update()
                app.page.run_task(success)
                # Always land on My Assets so the user sees the pending asset.
                # Once mining completes (FULLY_UPLOADED), the card auto-leaves My Assets
                # and the asset appears in the Marketplace for all online users.
                async def navigate():
                    app.page.go("/my_assets")
                app.page.run_task(navigate)
            except Exception as exc:
                show_error(str(exc))

        threading.Thread(target=upload_thread, daemon=True).start()

    upload_btn.on_click = do_upload

    body = ft.Container(width=640, bgcolor=CARD, border_radius=20, border=ft.border.all(1, BORDER),
        shadow=GLOW, padding=26,
        content=ft.Column(spacing=14, controls=[
            ft.Row(spacing=10, vertical_alignment=ft.CrossAxisAlignment.CENTER, controls=[
                ft.Icon(ft.Icons.ADD_PHOTO_ALTERNATE_OUTLINED, color=GOLD, size=22),
                ft.Column(spacing=0, tight=True, controls=[
                    ft.Text("Mint New Asset", color=TEXT, size=20, weight=ft.FontWeight.BOLD),
                    ft.Text("Upload an image asset to Aurex.", color=MUTED, size=11),
                ]),
            ]),
            divider(),
            ft.Row(spacing=10, vertical_alignment=ft.CrossAxisAlignment.CENTER, controls=[
                ft.FilledButton("Choose File", bgcolor="#1C1400", color=GOLD_SOFT,
                    style=ft.ButtonStyle(shape=ft.RoundedRectangleBorder(radius=9), side=ft.BorderSide(1, BORDER)),
                    on_click=choose_file),
                ft.Icon(ft.Icons.IMAGE_OUTLINED, color=MUTED, size=15),
                selected,
            ]),
            asset_name, description, cost,
            upload_to_row,
            file_hint,
            status_text,
            upload_err,
            upload_btn,
        ]))
    return main_shell(app, "/upload", "Mint a new asset",
        ft.Row(alignment=ft.MainAxisAlignment.CENTER,
               vertical_alignment=ft.CrossAxisAlignment.START,
               controls=[body]))


def build_settings_view(app):
    status     = ft.Text("Wallet not loaded", color=ERROR, size=13)
    wallet_err = ft.Text("", color=ERROR, size=12, visible=False)   # inline error for all wallet ops
    preview    = ft.Text("", color="#5A6A7A", selectable=True, size=11, font_family="monospace")
    local_wallet_path = "Client/{}/wallet.json".format(app.state.username or "")

    def show_wallet_err(msg):
        wallet_err.value = str(msg)
        wallet_err.visible = True
        app.page.update()

    def clear_wallet_err():
        wallet_err.value = ""
        wallet_err.visible = False

    def refresh_wallet_ui():
        clear_wallet_err()
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
        def _close_dlg(dlg):
            dlg.open = False
            app.page.update()

        def _on_confirm(e):
            _close_dlg(dlg)

            def _worker():
                try:
                    app.generate_new_wallet()
                    refresh_wallet_ui()
                except Exception as exc:
                    show_wallet_err(str(exc))

            threading.Thread(target=_worker, daemon=True).start()

        def _on_cancel(e):
            _close_dlg(dlg)

        dlg = ft.AlertDialog(
            modal=True,
            title=ft.Text("Generate New Wallet?", color=GOLD),
            content=ft.Text(
                "A new wallet means a new identity.\n\n"
                "All assets you currently own will no longer be yours — "
                "your ownership and access to them will be permanently lost. "
                "This action cannot be undone.",
                color=TEXT,
            ),
            bgcolor="#12100A",
            actions=[
                ft.TextButton("Cancel", on_click=_on_cancel,
                    style=ft.ButtonStyle(color=MUTED)),
                ft.FilledButton("OK — Generate New Wallet", bgcolor=GOLD, color="#130E00",
                    on_click=_on_confirm,
                    style=ft.ButtonStyle(shape=ft.RoundedRectangleBorder(radius=9))),
            ],
            actions_alignment=ft.MainAxisAlignment.END,
        )
        if dlg not in app.page.overlay:
            app.page.overlay.append(dlg)
        dlg.open = True
        app.page.update()

    def load_default(_):
        try:
            app.load_default_wallet()
            refresh_wallet_ui()
        except Exception as exc:
            show_wallet_err(str(exc))

    async def import_wallet_async():
        files = await import_picker.pick_files(
            allow_multiple=False,
            file_type=ft.FilePickerFileType.CUSTOM,
            allowed_extensions=["json"],
        )
        if not files or not files[0].path:
            return
        try:
            app.load_wallet_from_file(files[0].path)
            refresh_wallet_ui()
        except Exception as exc:
            show_wallet_err(str(exc))

    def import_wallet(_):
        app.page.run_task(import_wallet_async)

    async def export_wallet_async():
        if not app.state.wallet_loaded:
            show_wallet_err("Load or generate a wallet before exporting")
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
                clear_wallet_err()
                app.notify("Wallet exported")
            except Exception as exc:
                show_wallet_err(str(exc))

    def export_wallet(_):
        app.page.run_task(export_wallet_async)

    def continue_market(_):
        if not app.state.wallet_loaded:
            show_wallet_err("You must load or generate a wallet before accessing the marketplace")
            return
        app.page.go("/marketplace")

    def do_delete_account(_):
        def _close_dlg(dlg):
            dlg.open = False
            app.page.update()

        def on_confirm(e):
            _close_dlg(dlg)

            def _worker():
                try:
                    app.delete_account()
                except Exception as exc:
                    app.notify(str(exc), error=True)
                    return
                app.page.go("/login")

            threading.Thread(target=_worker, daemon=True).start()

        def on_cancel(e):
            _close_dlg(dlg)

        dlg = ft.AlertDialog(
            modal=True,
            title=ft.Text("Delete Account", color=ERROR),
            content=ft.Text(
                "Are you sure you want to delete your account? This action cannot be undone.",
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
        if dlg not in app.page.overlay:
            app.page.overlay.append(dlg)
        dlg.open = True
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
        shadow=GLOW, padding=28,
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
            wallet_err,
            ft.Container(bgcolor="#060709", border=ft.border.all(1, "#141820"), border_radius=12, padding=14, content=preview),
            ft.Row(alignment=ft.MainAxisAlignment.END, controls=[
                ft.FilledButton("Continue to Marketplace  →", bgcolor=SUCCESS, color="white",
                    style=ft.ButtonStyle(shape=ft.RoundedRectangleBorder(radius=10)), on_click=continue_market),
            ]),
            ft.Container(height=1, bgcolor=BORDER_DIM, margin=ft.margin.symmetric(vertical=4)),
            danger_section,
        ]))
    return main_shell(app, "/settings", "Identity & settings",
        ft.Row(alignment=ft.MainAxisAlignment.CENTER,
               vertical_alignment=ft.CrossAxisAlignment.START,
               controls=[body]))


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

    return main_shell(app, "/notifications", "System updates",
        ft.Column(spacing=12, controls=[
            ft.Text("Notifications", color=TEXT, size=22, weight=ft.FontWeight.BOLD),
            *rows,
        ]))


def build_my_assets_view(app):
    app.unlisted_asset_ids.clear()
    app.removed_asset_ids.clear()
    # listed_asset_ids intentionally NOT cleared — preserves FULLY_UPLOADED events for
    # the marketplace monitor. We only pop IDs that are already in this page's card_map.
    app.recently_bought_ids.clear()   # initial load() covers assets bought before page opened

    grid = ft.ResponsiveRow(spacing=10, run_spacing=10)
    status_text = ft.Text("Loading...", color=MUTED, size=12)
    card_map: dict[str, ft.Container] = {}
    active = [True]

    def load():
        try:
            id_entries = app.get_my_asset_ids()
        except Exception as exc:
            _msg = str(exc)
            async def err():
                status_text.value = f"Error: {_msg}"
                app.page.update()
            app.page.run_task(err)
            app.notify(_msg, error=True)
            return

        if not id_entries:
            async def empty():
                status_text.value = "No assets yet"
                app.page.update()
            app.page.run_task(empty)
            return

        async def init():
            status_text.value = f"Loading {len(id_entries)} asset(s)..."
            app.page.update()
        app.page.run_task(init)

        loaded = 0
        for entry in id_entries:
            if not active[0]:
                return
            asset_id = entry.get("id", "") if isinstance(entry, dict) else str(entry)
            version = entry.get("version", 1) if isinstance(entry, dict) else 1
            if not asset_id:
                continue
            item = app.load_asset_by_id(asset_id, version)
            if not item:
                continue
            card = asset_card(app, item, context="my_assets")
            wrapper = ft.Container(col={"xs": 12, "sm": 6, "md": 4}, content=card)
            card_map[asset_id] = wrapper
            loaded += 1
            n, total = loaded, len(id_entries)
            async def add(w=wrapper, n=n, total=total):
                if not active[0]:
                    return
                grid.controls.append(w)
                status_text.value = f"{n} / {total} loaded"
                app.page.update()
            app.page.run_task(add)

        final = loaded
        async def done():
            status_text.value = f"{final} asset{'s' if final != 1 else ''} owned"
            app.page.update()
        app.page.run_task(done)

    def monitor():
        """Add newly bought assets; remove assets that moved away (deleted or PENDING→FOR_SALE)."""
        while active[0]:
            time.sleep(2)
            if not active[0]:
                return
            app.drain_asset_events()

            # Add newly purchased assets (bought while this page is open)
            new_buys = list(app.recently_bought_ids - set(card_map.keys()))
            for asset_id in new_buys:
                if not active[0]:
                    return
                app.recently_bought_ids.discard(asset_id)
                item = app.load_asset_by_id(asset_id)
                if not item:
                    continue
                card = asset_card(app, item, context="my_assets")
                wrapper = ft.Container(col={"xs": 12, "sm": 6, "md": 4}, content=card)
                card_map[asset_id] = wrapper
                n = len(card_map)
                async def add_new(w=wrapper, n=n):
                    if not active[0]:
                        return
                    grid.controls.insert(0, w)
                    status_text.value = f"{n} asset{'s' if n != 1 else ''} owned"
                    app.page.update()
                app.page.run_task(add_new)

            # Assets that went FOR_SALE leave my_assets; deleted/removed too
            gone = list(
                app.listed_asset_ids    # PENDING → FOR_SALE: no longer in my_assets
                | app.removed_asset_ids
                | app.sold_asset_ids
            )
            changed = False
            for asset_id in gone:
                wrapper = card_map.pop(asset_id, None)
                if wrapper and wrapper in grid.controls:
                    grid.controls.remove(wrapper)
                    changed = True
            if changed:
                n = len(card_map)
                async def upd(n=n):
                    status_text.value = f"{n} asset{'s' if n != 1 else ''} owned"
                    app.page.update()
                app.page.run_task(upd)

    def do_refresh(_):
        active[0] = False
        async def clear():
            grid.controls.clear()
            card_map.clear()
            status_text.value = "Loading..."
            status_text.color = MUTED
            app.page.update()
        app.page.run_task(clear)
        try:
            app.request_balance()
        except Exception as e:
            app.notify(str(e), error=True)
        active[0] = True
        threading.Thread(target=load, daemon=True).start()
        threading.Thread(target=monitor, daemon=True).start()

    threading.Thread(target=load, daemon=True).start()
    threading.Thread(target=monitor, daemon=True).start()

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
    return main_shell(app, "/my_assets", "Personal portfolio", body)
