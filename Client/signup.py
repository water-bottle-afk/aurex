from __future__ import annotations

import threading
from typing import TYPE_CHECKING

import flet as ft

from aurex_logging import AurexLogger
from .theme import (
    AUREX_GOLD,
    AUREX_GOLD_SOFT,
    AUREX_MUTED,
    AUREX_SLATE,
)
from .wallet import activate_wallet_user, generate_user_keys

if TYPE_CHECKING:
    from .app import AurexFletApp


_CARD_WIDTH = 480
logger = AurexLogger.get_logger(__name__)


def build_signup_view(app: "AurexFletApp") -> ft.View:
    page = app.page
    logger.debug("[aurex][signup] build_signup_view")
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

    def show_status(message: str = "", *, error: bool = False) -> None:
        status_text.value = f"Error: {message}" if error and message else message
        status_text.color = "#FF6B6B" if error else AUREX_MUTED
        status_text.visible = bool(message)
        page.update()

    def set_busy(is_busy: bool, message: str = "") -> None:
        logger.debug("[aurex][signup] set_busy is_busy=%s message=%r", is_busy, message)
        async def _apply() -> None:
            username_field.disabled = is_busy
            email_field.disabled = is_busy
            password_field.disabled = is_busy
            sign_up_button.disabled = is_busy
            back_button.disabled = is_busy
            progress.visible = is_busy
            if message:
                show_status(message, error=False)
            elif is_busy:
                status_text.visible = False
            page.update()
        page.run_task(_apply)

    def handle_signup(_: ft.ControlEvent) -> None:
        logger.debug("[aurex][signup] Create Account clicked")
        username = username_field.value.strip()
        email = email_field.value.strip().lower()
        password = password_field.value or ""
        logger.debug(
            f"[aurex][signup] form username={username!r} email={email!r} "
            f"password_len={len(password)}"
        )

        if not username or not email or not password:
            logger.debug("[aurex][signup] validation failed: missing fields")
            show_status("Please fill in all fields", error=True)
            app.show_message("Please fill in all fields", error=True)
            return
        if "@" not in email:
            logger.debug("[aurex][signup] validation failed: invalid email")
            show_status("Please enter a valid email", error=True)
            app.show_message("Please enter a valid email", error=True)
            return
        if " " in username or "|" in username:
            logger.debug("[aurex][signup] validation failed: invalid username chars")
            show_status("Username cannot contain spaces or |", error=True)
            app.show_message("Username cannot contain spaces or |", error=True)
            return
        if len(password) < 6:
            logger.debug("[aurex][signup] validation failed: password too short")
            show_status("Password must be at least 6 characters", error=True)
            app.show_message("Password must be at least 6 characters", error=True)
            return

        def worker() -> None:
            try:
                logger.debug("[aurex][signup] worker start for username=%r", username)
                set_busy(True, "Creating your Aurex account...")
                logger.debug("[aurex][signup] connecting to server")
                app.connect_if_needed(discover_first=True)
                logger.debug("[aurex][signup] generating or loading local keys")
                activate_wallet_user(username, password=password)
                public_key_b64, _ = generate_user_keys(
                    username=username,
                    password_material=password,
                    force=True,
                )
                logger.debug("[aurex][signup] public key ready len=%s", len(public_key_b64))
                app.client.signup(username, password, email, public_key_b64=public_key_b64)
                logger.debug("[aurex][signup] signup request completed for %r", username)
                show_status("Account created successfully!", error=False)
                app.show_message("Account created successfully!")
                page.run_task(page.push_route, "/login")
            except Exception as exc:
                logger.warning("[aurex][signup] worker error: %s", exc)
                msg = str(exc)
                if "Username already exists" in msg:
                    show_status("Username already exists", error=True)
                    app.show_message("Username already exists", error=True)
                elif "Email already exists" in msg:
                    show_status("Email already exists", error=True)
                    app.show_message("Email already exists", error=True)
                else:
                    show_status(msg, error=True)
                    app.show_message(f"Signup failed: {msg}", error=True)
            finally:
                logger.debug("[aurex][signup] worker done for username=%r", username)
                set_busy(False)

        threading.Thread(target=worker, daemon=True).start()

    sign_up_button = ft.FilledButton(
        content=ft.Text("Create Account"),
        on_click=handle_signup,
        bgcolor=AUREX_GOLD,
        color="#1A1A1B",
        height=48,
        width=_CARD_WIDTH,
    )
    back_button = ft.TextButton(
        content=ft.Text("Back to login"),
        on_click=lambda _: page.run_task(page.push_route, "/login"),
    )
    username_field.on_submit = handle_signup
    email_field.on_submit = handle_signup
    password_field.on_submit = handle_signup

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
                            ft.Text("Create your account", color=AUREX_MUTED),
                            ft.Divider(color=AUREX_SLATE, height=24),
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
            )
        ],
    )

