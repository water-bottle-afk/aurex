from __future__ import annotations

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
    AUREX_TEXT,
)

if TYPE_CHECKING:
    from .app import AurexFletApp


_CARD_WIDTH = 480


def build_login_view(app: "AurexFletApp") -> ft.View:
    page = app.page
    username_field = ft.TextField(
        label="Username",
        autofocus=True,
        border_radius=16,
    )
    password_field = ft.TextField(
        label="Password",
        password=True,
        can_reveal_password=True,
        border_radius=16,
    )
    status_text = ft.Text(color=AUREX_MUTED, size=12, visible=False)
    progress = ft.ProgressRing(width=18, height=18, stroke_width=2, visible=False)

    def set_busy(is_busy: bool, message: str = "") -> None:
        username_field.disabled = is_busy
        password_field.disabled = is_busy
        login_button.disabled = is_busy
        signup_button.disabled = is_busy
        forgot_button.disabled = is_busy
        google_button.disabled = is_busy
        progress.visible = is_busy
        status_text.visible = bool(message)
        status_text.value = message
        page.update()

    def handle_login(_: ft.ControlEvent) -> None:
        username = username_field.value.strip()
        password = password_field.value
        if not username:
            app.show_message("Username cannot be empty", error=True)
            return
        if not password:
            app.show_message("Password cannot be empty", error=True)
            return
        if "|" in username or " " in username:
            app.show_message("Invalid username format", error=True)
            return

        def worker() -> None:
            try:
                set_busy(True, "Connecting to Aurex server...")
                app.connect_if_needed(discover_first=True)
                returned_username = app.client.login(username, password)
                if app.session.user_data is not None:
                    app.session.user_data.email = ""
                app.show_message(f"Welcome, {returned_username}!")
                app.load_marketplace_async(reset=True)
                page.run_task(page.push_route, "/marketplace")
            except Exception as exc:
                app.show_message(f"Login failed: {exc}", error=True)
            finally:
                set_busy(False)

        threading.Thread(target=worker, daemon=True).start()

    def handle_google(_: ft.ControlEvent) -> None:
        app.show_message("Google sign-in is not configured yet", error=True)

    brand = ft.Column(
        horizontal_alignment=ft.CrossAxisAlignment.CENTER,
        spacing=6,
        controls=[
            ft.Image(src="images/gold_icon.png", width=64, height=64, fit=ft.BoxFit.CONTAIN),
            ft.ShaderMask(
                blend_mode=ft.BlendMode.SRC_IN,
                shader=ft.LinearGradient(
                    begin=ft.Alignment(-1, -1),
                    end=ft.Alignment(1, 1),
                    colors=[AUREX_GOLD, AUREX_GOLD_SOFT, "#C0841B"],
                ),
                content=ft.Text(
                    "AUREX",
                    size=32,
                    weight=ft.FontWeight.BOLD,
                    style=ft.TextStyle(letter_spacing=5),
                ),
            ),
        ],
    )

    google_button = ft.OutlinedButton(
        on_click=handle_google,
        disabled=True,
        tooltip="Google sign-in is not available in this version",
        content=ft.Row(
            alignment=ft.MainAxisAlignment.CENTER,
            controls=[
                ft.Icon(ft.Icons.G_MOBILEDATA, size=20, color=AUREX_MUTED),
                ft.Text("Continue with Google", color=AUREX_MUTED),
            ],
        ),
        style=ft.ButtonStyle(
            side={ft.ControlState.DEFAULT: ft.BorderSide(1, AUREX_SLATE)},
            shape=ft.RoundedRectangleBorder(radius=14),
        ),
        width=_CARD_WIDTH,
        height=46,
    )

    login_button = ft.FilledButton(
        content="Login",
        on_click=handle_login,
        bgcolor=AUREX_GOLD,
        color="#1A1A1B",
        height=48,
        width=_CARD_WIDTH,
    )
    signup_button = ft.TextButton(
        content="Create account",
        on_click=lambda _: page.run_task(page.push_route, "/signup"),
    )
    forgot_button = ft.TextButton(
        content="Forgot Password?",
        on_click=lambda _: page.run_task(page.push_route, "/forgot"),
    )

    return ft.View(
        route="/login",
        bgcolor="#080A0E",  # matches scrim so any gap is invisible
        padding=0,
        controls=[
            ft.Container(
                expand=True,
                image=ft.DecorationImage(
                    src="images/gold_bg.png",
                    fit=ft.BoxFit.COVER,
                ),
                gradient=ft.LinearGradient(
                    begin=ft.Alignment(0, 0),
                    end=ft.Alignment(0, 0),
                    colors=["#CC080A0E", "#CC080A0E"],
                ),
                alignment=ft.Alignment(0, 0),
                padding=ft.padding.symmetric(vertical=32, horizontal=32),
                content=ft.Container(
                    width=_CARD_WIDTH,
                    padding=30,
                    bgcolor="#EE0D0F13",
                    border_radius=20,
                    border=ft.border.all(1, AUREX_SLATE),
                    content=ft.Column(
                        tight=True,
                        horizontal_alignment=ft.CrossAxisAlignment.CENTER,
                        controls=[
                            brand,
                            ft.Text("Welcome back", color=AUREX_MUTED),
                            ft.Divider(color=AUREX_SLATE, height=24),
                            google_button,
                            ft.Row(
                                alignment=ft.MainAxisAlignment.CENTER,
                                controls=[
                                    ft.Container(height=1, width=80, bgcolor=AUREX_SLATE),
                                    ft.Text("or", color=AUREX_MUTED, size=12),
                                    ft.Container(height=1, width=80, bgcolor=AUREX_SLATE),
                                ],
                            ),
                            username_field,
                            password_field,
                            ft.Row(
                                alignment=ft.MainAxisAlignment.CENTER,
                                controls=[progress, status_text],
                            ),
                            login_button,
                            ft.Row(
                                alignment=ft.MainAxisAlignment.CENTER,
                                controls=[
                                    ft.Text("New to Aurex?", color=AUREX_MUTED),
                                    signup_button,
                                ],
                            ),
                            forgot_button,
                        ],
                    ),
                ),
            )
        ],
    )
