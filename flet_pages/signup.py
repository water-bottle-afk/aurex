from __future__ import annotations

import threading
from typing import TYPE_CHECKING

import flet as ft

if TYPE_CHECKING:
    from .app import AurexFletApp


_CARD_WIDTH = 460


def build_signup_view(app: "AurexFletApp") -> ft.View:
    page = app.page
    username_field = ft.TextField(label="Username", border_radius=12)
    email_field = ft.TextField(label="Email", keyboard_type=ft.KeyboardType.EMAIL, border_radius=12)
    password_field = ft.TextField(
        label="Password",
        password=True,
        can_reveal_password=True,
        border_radius=12,
    )
    status_text = ft.Text(color="#cbd5e1", size=12, visible=False)
    progress = ft.ProgressRing(width=18, height=18, stroke_width=2, visible=False)

    def set_busy(is_busy: bool, message: str = "") -> None:
        username_field.disabled = is_busy
        email_field.disabled = is_busy
        password_field.disabled = is_busy
        sign_up_button.disabled = is_busy
        back_button.disabled = is_busy
        progress.visible = is_busy
        status_text.visible = bool(message)
        status_text.value = message
        page.update()

    def handle_signup(_: ft.ControlEvent) -> None:
        username = username_field.value.strip()
        email = email_field.value.strip()
        password = password_field.value

        if not username or not email or not password:
            app.show_message("Please fill in all fields", error=True)
            return
        if "@" not in email:
            app.show_message("Please enter a valid email", error=True)
            return
        if len(password) < 6:
            app.show_message("Password must be at least 6 characters", error=True)
            return

        def worker() -> None:
            try:
                set_busy(True, "Creating your Aurex account...")
                app.connect_if_needed(discover_first=True)
                app.client.signup(username, password, email)
                app.show_message("Account created successfully!")
                page.go("/login")
            except Exception as exc:
                app.show_message(f"Signup failed: {exc}", error=True)
            finally:
                set_busy(False)

        threading.Thread(target=worker, daemon=True).start()

    sign_up_button = ft.ElevatedButton(
        text="Sign Up",
        on_click=handle_signup,
        bgcolor="#2563eb",
        color="white",
        height=48,
        width=_CARD_WIDTH,
    )
    back_button = ft.TextButton(text="Back to login", on_click=lambda _: page.go("/login"))

    return ft.View(
        route="/signup",
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
                                    ft.Text("Create Account", size=30, weight=ft.FontWeight.BOLD),
                                    ft.Text("Sign up to get started", color="#94a3b8"),
                                    ft.Divider(color="#1f2937", height=24),
                                    username_field,
                                    email_field,
                                    password_field,
                                    ft.Row(
                                        alignment=ft.MainAxisAlignment.CENTER,
                                        controls=[progress, status_text],
                                    ),
                                    sign_up_button,
                                    back_button,
                                ],
                            ),
                        )
                    ],
                ),
            )
        ],
    )
