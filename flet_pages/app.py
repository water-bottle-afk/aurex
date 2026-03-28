from __future__ import annotations

import base64
import threading

import flet as ft

from .protocol_client import AurexProtocolClient
from .session import UserSession
from .forgot import build_forgot_view
from .login import build_login_view
from .marketplace import build_marketplace_view
from .signup import build_signup_view


class AurexFletApp:
    def __init__(self, page: ft.Page) -> None:
        self.page = page
        self.session = UserSession()
        self.client = AurexProtocolClient(self.session)
        self.market_loading = False
        self.market_error: str | None = None
        self._market_bootstrap_requested = False
        self._render_lock = threading.RLock()

        self.page.title = "Aurex Marketplace"
        self.page.theme_mode = ft.ThemeMode.DARK
        self.page.bgcolor = "#0f172a"
        self.page.padding = 0
        self.page.spacing = 0
        self.page.scroll = ft.ScrollMode.AUTO
        self.page.on_route_change = self._on_route_change
        self.page.on_view_pop = self._on_view_pop

    def start(self) -> None:
        self.page.go(self.page.route or "/login")

    def show_message(self, message: str, *, error: bool = False) -> None:
        self.page.snack_bar = ft.SnackBar(
            content=ft.Text(message, color="white"),
            bgcolor="#dc2626" if error else "#16a34a",
        )
        self.page.snack_bar.open = True
        self.page.update()

    def connect_if_needed(self, *, discover_first: bool = True) -> None:
        self.client.connect(discover_first=discover_first)

    def logout(self) -> None:
        try:
            self.client.logout()
        finally:
            self.market_error = None
            self.market_loading = False
            self._market_bootstrap_requested = False
            self.page.go("/login")

    def load_marketplace_async(self, *, reset: bool, refresh_now: bool = True) -> None:
        if self.market_loading:
            return
        self.market_loading = True
        if reset:
            self.market_error = None
            self._market_bootstrap_requested = True
        if refresh_now:
            self.refresh_marketplace_view()
        threading.Thread(
            target=self._load_marketplace_worker,
            args=(reset,),
            daemon=True,
        ).start()

    def _load_marketplace_worker(self, reset: bool) -> None:
        try:
            self.connect_if_needed(discover_first=not self.session.is_authenticated)
            previous_items = list(self.session.market_items)
            cursor = None if reset else self.session.last_market_cursor
            fetched = self.client.get_market_data(limit=12, last_timestamp=cursor)
            if reset:
                self.session.market_items = fetched
            else:
                existing = {item.id for item in previous_items}
                merged = previous_items + [item for item in fetched if item.id not in existing]
                self.session.market_items = merged
            self.market_error = None
        except Exception as exc:
            self.market_error = str(exc)
        finally:
            self.market_loading = False
            self.refresh_marketplace_view()

        for item in list(self.session.market_items):
            self.prefetch_image_async(item.image_url)

    def prefetch_image_async(self, rel_path: str) -> None:
        if not rel_path:
            return
        with self.session.lock:
            if rel_path in self.session.image_cache or rel_path in self.session.loading_images:
                return
            self.session.loading_images.add(rel_path)
        threading.Thread(
            target=self._prefetch_image_worker,
            args=(rel_path,),
            daemon=True,
        ).start()

    def _prefetch_image_worker(self, rel_path: str) -> None:
        try:
            self.connect_if_needed(discover_first=False)
            image_bytes = self.client.download_asset(rel_path)
            if image_bytes:
                self.session.image_cache[rel_path] = base64.b64encode(image_bytes).decode("ascii")
        except Exception as exc:
            self.session.remember(f"image download failed for {rel_path}: {exc}")
        finally:
            with self.session.lock:
                self.session.loading_images.discard(rel_path)
            self.refresh_marketplace_view()

    def refresh_marketplace_view(self) -> None:
        if self.page.route == "/marketplace":
            self._render_current_route()
        else:
            self.page.update()

    def _on_route_change(self, _: ft.RouteChangeEvent) -> None:
        self._render_current_route()

    def _on_view_pop(self, _: ft.ViewPopEvent) -> None:
        if len(self.page.views) > 1:
            self.page.views.pop()
            self.page.go(self.page.views[-1].route)
        else:
            self.page.go("/login")

    def _render_current_route(self) -> None:
        route = self.page.route or "/login"
        if route == "/marketplace" and not self.session.is_authenticated:
            route = "/login"
            self.page.route = route

        builders = {
            "/login": build_login_view,
            "/signup": build_signup_view,
            "/forgot": build_forgot_view,
            "/marketplace": build_marketplace_view,
        }
        builder = builders.get(route, build_login_view)
        with self._render_lock:
            self.page.views.clear()
            self.page.views.append(builder(self))
            self.page.update()
