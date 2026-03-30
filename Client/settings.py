from __future__ import annotations

from typing import TYPE_CHECKING

import flet as ft

from .theme import AUREX_BG, AUREX_CARD, AUREX_GOLD, AUREX_MUTED, AUREX_SLATE

if TYPE_CHECKING:
    from .app import AurexFletApp


def build_settings_view(app: "AurexFletApp") -> ft.View:
    page = app.page
    user = app.session.user_data

    host_field = ft.TextField(
        label="Server IP",
        border_radius=16,
        value=app.session.host or app.client.host,
    )
    port_field = ft.TextField(
        label="Port",
        border_radius=16,
        value=str(app.session.port or app.client.port),
    )

    def save_connection(_: ft.ControlEvent) -> None:
        host = host_field.value.strip()
        try:
            port = int(port_field.value.strip())
        except Exception:
            app.show_message("Invalid port value", error=True)
            return
        if not host:
            app.show_message("Server IP is required", error=True)
            return
        app.client.set_server_address(host, port)
        app.show_message("Server settings updated")

    return ft.View(
        route="/settings",
        bgcolor=AUREX_BG,
        controls=[
            ft.Container(
                expand=True,
                padding=24,
                content=ft.Column(
                    spacing=18,
                    controls=[
                        ft.Row(
                            alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
                            controls=[
                                ft.Text("Settings", size=26, weight=ft.FontWeight.BOLD),
                                ft.IconButton(
                                    icon=ft.Icons.CLOSE,
                                    on_click=lambda _: page.run_task(page.push_route, "/marketplace"),
                                ),
                            ],
                        ),
                        ft.Container(
                            padding=20,
                            border_radius=20,
                            bgcolor=AUREX_CARD,
                            border=ft.border.all(1, AUREX_SLATE),
                            content=ft.Column(
                                spacing=12,
                                controls=[
                                    ft.Text("User Profile", weight=ft.FontWeight.BOLD),
                                    ft.Text(f"Username: {user.username if user else 'Guest'}"),
                                    ft.Text(f"Email: {user.email if user else '—'}", color=AUREX_MUTED),
                                ],
                            ),
                        ),
                        ft.Container(
                            padding=20,
                            border_radius=20,
                            bgcolor=AUREX_CARD,
                            border=ft.border.all(1, AUREX_SLATE),
                            content=ft.Column(
                                spacing=12,
                                controls=[
                                    ft.Text("Server Connection", weight=ft.FontWeight.BOLD),
                                    host_field,
                                    port_field,
                                    ft.FilledButton(
                                        content="Save Connection",
                                        bgcolor=AUREX_GOLD,
                                        color="#1A1A1B",
                                        on_click=save_connection,
                                    ),
                                ],
                            ),
                        ),
                        ft.Container(
                            padding=20,
                            border_radius=20,
                            bgcolor=AUREX_CARD,
                            border=ft.border.all(1, AUREX_SLATE),
                            content=ft.Column(
                                spacing=12,
                                controls=[
                                    ft.Text("Session", weight=ft.FontWeight.BOLD),
                                    ft.FilledButton(
                                        content="Logout",
                                        icon=ft.Icons.LOGOUT,
                                        on_click=lambda _: app.logout(),
                                    ),
                                ],
                            ),
                        ),
                    ],
                ),
            )
        ],
    )
