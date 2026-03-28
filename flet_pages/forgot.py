from __future__ import annotations

import threading
from typing import TYPE_CHECKING

import flet as ft

if TYPE_CHECKING:
    from .app import AurexFletApp


_CARD_WIDTH = 460


def build_forgot_view(app: "AurexFletApp") -> ft.View:
    page = app.page
    email_field = ft.TextField(label="Email", keyboard_type=ft.KeyboardType.EMAIL, border_radius=12)
    code_field = ft.TextField(label="Verification Code", max_length=6, border_radius=12)
    new_password_field = ft.TextField(
        label="New Password",
        password=True,
        can_reveal_password=True,
        border_radius=12,
    )
    confirm_password_field = ft.TextField(
        label="Confirm Password",
        password=True,
        can_reveal_password=True,
        border_radius=12,
    )
    dev_code_text = ft.Text(color="#fbbf24", visible=False)
    status_text = ft.Text(color="#cbd5e1", size=12, visible=False)
    progress = ft.ProgressRing(width=18, height=18, stroke_width=2, visible=False)

    email_step = ft.Column(visible=True, tight=True)
    code_step = ft.Column(visible=False, tight=True)
    password_step = ft.Column(visible=False, tight=True)

    def set_busy(is_busy: bool, message: str = "") -> None:
        for field in (email_field, code_field, new_password_field, confirm_password_field):
            field.disabled = is_busy
        send_code_button.disabled = is_busy
        verify_code_button.disabled = is_busy
        reset_password_button.disabled = is_busy
        back_button.disabled = is_busy
        progress.visible = is_busy
        status_text.visible = bool(message)
        status_text.value = message
        page.update()

    def show_step(step_name: str) -> None:
        email_step.visible = step_name == "email"
        code_step.visible = step_name == "code"
        password_step.visible = step_name == "password"
        page.update()

    def handle_send_code(_: ft.ControlEvent) -> None:
        email = email_field.value.strip()
        if not email:
            app.show_message("Please enter your email", error=True)
            return

        def worker() -> None:
            try:
                set_busy(True, "Requesting reset code...")
                app.connect_if_needed(discover_first=True)
                maybe_dev_code = app.client.request_password_reset(email)
                if maybe_dev_code:
                    dev_code_text.value = f"Dev OTP: {maybe_dev_code}"
                    dev_code_text.visible = True
                    code_field.value = maybe_dev_code
                app.show_message("Reset code sent")
                show_step("code")
            except Exception as exc:
                app.show_message(f"Failed to send code: {exc}", error=True)
            finally:
                set_busy(False)

        threading.Thread(target=worker, daemon=True).start()

    def handle_verify_code(_: ft.ControlEvent) -> None:
        code = code_field.value.strip()
        if not code:
            app.show_message("Please enter the verification code", error=True)
            return

        def worker() -> None:
            try:
                set_busy(True, "Verifying code...")
                app.connect_if_needed(discover_first=False)
                app.client.verify_password_reset_code(email_field.value.strip(), code)
                app.show_message("Code verified")
                show_step("password")
            except Exception as exc:
                app.show_message(f"Code verification failed: {exc}", error=True)
            finally:
                set_busy(False)

        threading.Thread(target=worker, daemon=True).start()

    def handle_reset_password(_: ft.ControlEvent) -> None:
        password = new_password_field.value
        confirmation = confirm_password_field.value
        if not password or not confirmation:
            app.show_message("Please enter both passwords", error=True)
            return
        if password != confirmation:
            app.show_message("Passwords do not match", error=True)
            return
        if len(password) < 6:
            app.show_message("Password must be at least 6 characters", error=True)
            return

        def worker() -> None:
            try:
                set_busy(True, "Updating password...")
                app.connect_if_needed(discover_first=False)
                app.client.update_password(email_field.value.strip(), password)
                app.show_message("Password updated successfully")
                page.go("/login")
            except Exception as exc:
                app.show_message(f"Password reset failed: {exc}", error=True)
            finally:
                set_busy(False)

        threading.Thread(target=worker, daemon=True).start()

    send_code_button = ft.ElevatedButton(
        text="Send Code",
        on_click=handle_send_code,
        bgcolor="#2563eb",
        color="white",
        width=_CARD_WIDTH,
        height=48,
    )
    verify_code_button = ft.ElevatedButton(
        text="Verify Code",
        on_click=handle_verify_code,
        bgcolor="#2563eb",
        color="white",
        width=_CARD_WIDTH,
        height=48,
    )
    reset_password_button = ft.ElevatedButton(
        text="Reset Password",
        on_click=handle_reset_password,
        bgcolor="#16a34a",
        color="white",
        width=_CARD_WIDTH,
        height=48,
    )
    back_button = ft.TextButton(text="Back to login", on_click=lambda _: page.go("/login"))

    email_step.controls = [
        ft.Text("Enter your email", size=24, weight=ft.FontWeight.BOLD),
        ft.Text("We\'ll send a reset code to your email", color="#94a3b8"),
        email_field,
        send_code_button,
    ]
    code_step.controls = [
        ft.Text("Enter verification code", size=24, weight=ft.FontWeight.BOLD),
        dev_code_text,
        code_field,
        verify_code_button,
        ft.OutlinedButton(text="Back", on_click=lambda _: show_step("email"), width=_CARD_WIDTH),
    ]
    password_step.controls = [
        ft.Text("Create new password", size=24, weight=ft.FontWeight.BOLD),
        new_password_field,
        confirm_password_field,
        reset_password_button,
    ]

    return ft.View(
        route="/forgot",
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
                                    email_step,
                                    code_step,
                                    password_step,
                                    ft.Row(
                                        alignment=ft.MainAxisAlignment.CENTER,
                                        controls=[progress, status_text],
                                    ),
                                    back_button,
                                ],
                            ),
                        )
                    ],
                ),
            )
        ],
    )
