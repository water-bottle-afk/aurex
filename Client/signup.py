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


def build_signup_view(app: "AurexFletApp") -> ft.View:
    page = app.page
    username_field = ft.TextField(label="Username", border_radius=16)
    email_field = ft.TextField(label="Email", keyboard_type=ft.KeyboardType.EMAIL, border_radius=16)
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
        email_field.disabled = is_busy
        password_field.disabled = is_busy
        sign_up_button.disabled = is_busy
        back_button.disabled = is_busy
        google_button.disabled = is_busy
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
                page.run_task(page.push_route, "/login")
            except Exception as exc:
                app.show_message(f"Signup failed: {exc}", error=True)
            finally:
                set_busy(False)

        threading.Thread(target=worker, daemon=True).start()

    google_button = ft.OutlinedButton(
        content=ft.Row(
            alignment=ft.MainAxisAlignment.CENTER,
            controls=[
                ft.Image(src="images/google_logo.png", width=18, height=18),
                ft.Text("Continue with Google", color=AUREX_TEXT),
            ],
        ),
        width=_CARD_WIDTH,
        height=46,
    )

    sign_up_button = ft.FilledButton(
        content="Create Account",
        on_click=handle_signup,
        bgcolor=AUREX_GOLD,
        color="#1A1A1B",
        height=48,
        width=_CARD_WIDTH,
    )
    back_button = ft.TextButton(content="Back to login", on_click=lambda _: page.run_task(page.push_route, "/login"))

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
                    "JOIN AUREX",
                    size=28,
                    weight=ft.FontWeight.BOLD,
                    style=ft.TextStyle(letter_spacing=3),
                ),
            ),
        ],
    )

    return ft.View(
        route="/signup",
        bgcolor=AUREX_BG,
        padding=0,
        controls=[
            ft.Stack(
                expand=True,
                controls=[
                    # ── gold_bg.png fills the full screen ──────────────────────
                    ft.Image(
                        src="images/gold_bg.png",
                        expand=True,
                        fit=ft.BoxFit.COVER,
                    ),
                    # ── dark scrim so the bg doesn't compete with the form ──────
                    ft.Container(
                        expand=True,
                        bgcolor="#CC0A0B0F",  # ~80 % opaque near-black
                    ),
                    # ── centred form card ───────────────────────────────────────
                    ft.Container(
                        expand=True,
                        padding=32,
                        alignment=ft.Alignment(0, 0),
                        content=ft.Container(
                            width=_CARD_WIDTH,
                            padding=30,
                            bgcolor="#E6101215",  # semi-transparent card
                            border_radius=20,
                            border=ft.border.all(1, AUREX_SLATE),
                            content=ft.Column(
                                tight=True,
                                horizontal_alignment=ft.CrossAxisAlignment.CENTER,
                                controls=[
                                    brand,
                                    ft.Text("Create your account", color=AUREX_MUTED),
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
                        ),
                    ),
                ],
            )
        ],
    )
