from __future__ import annotations

import threading
from typing import TYPE_CHECKING

import flet as ft

if TYPE_CHECKING:
    from .app import AurexFletApp


_CARD_WIDTH = 420


def build_login_view(app: "AurexFletApp") -> ft.View:
    page = app.page
    username_field = ft.TextField(
        label="Username",
        autofocus=True,
        border_radius=12,
        text_size=14,
    )
    password_field = ft.TextField(
        label="Password",
        password=True,
        can_reveal_password=True,
        border_radius=12,
        text_size=14,
    )
    status_text = ft.Text(color="#cbd5e1", size=12, visible=False)
    progress = ft.ProgressRing(width=18, height=18, stroke_width=2, visible=False)

    def set_busy(is_busy: bool, message: str = "") -> None:
        username_field.disabled = is_busy
        password_field.disabled = is_busy
        login_button.disabled = is_busy
        signup_button.disabled = is_busy
        forgot_button.disabled = is_busy
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
                page.go("/marketplace")
            except Exception as exc:
                app.show_message(f"Login failed: {exc}", error=True)
            finally:
                set_busy(False)

        threading.Thread(target=worker, daemon=True).start()

    login_button = ft.ElevatedButton(
        text="Login",
        on_click=handle_login,
        bgcolor="#2563eb",
        color="white",
        height=48,
        width=_CARD_WIDTH,
    )
    signup_button = ft.TextButton(
        text="Create account",
        on_click=lambda _: page.go("/signup"),
    )
    forgot_button = ft.TextButton(
        text="Forgot Password?",
        on_click=lambda _: page.go("/forgot"),
    )

    return ft.View(
        route="/login",
        bgcolor="#0f172a",
        controls=[
            ft.Container(
                expand=True,
                padding=32,
                gradient=ft.LinearGradient(
                    begin=ft.alignment.top_center,
                    end=ft.alignment.bottom_center,
                    colors=["#1d4ed8", "#0f172a"],
                ),
                content=ft.Column(
                    expand=True,
                    alignment=ft.MainAxisAlignment.CENTER,
                    horizontal_alignment=ft.CrossAxisAlignment.CENTER,
                    controls=[
                        ft.Container(
                            width=_CARD_WIDTH,
                            padding=32,
                            bgcolor="#111827dd",
                            border_radius=24,
                            content=ft.Column(
                                tight=True,
                                horizontal_alignment=ft.CrossAxisAlignment.CENTER,
                                controls=[
                                    ft.Text("Welcome Back", size=30, weight=ft.FontWeight.BOLD),
                                    ft.Text("Sign in to continue", color="#94a3b8"),
                                    ft.Divider(color="#1f2937", height=24),
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
                                            ft.Text("Don\'t have an account?", color="#cbd5e1"),
                                            signup_button,
                                        ],
                                    ),
                                    forgot_button,
                                ],
                            ),
                        )
                    ],
                ),
            )
        ],
    )
