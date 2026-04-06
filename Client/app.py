from __future__ import annotations

import base64
import threading
import time
import flet as ft
from .protocol_client import AurexProtocolClient
from .session import UserSession
from .theme import AUREX_BG, AUREX_ERROR, AUREX_SUCCESS, build_aurex_theme
from .forgot import build_forgot_view
from .login import build_login_view
from .marketplace import build_marketplace_view
from .signup import build_signup_view
from .settings import build_settings_view
from .upload import build_upload_view
from .notifications import build_notifications_view
from .my_assets import build_my_assets_view
import Client.notifications as _notif_store


class AurexFletApp:
    def __init__(self, page: ft.Page) -> None:
        print("[aurex] AurexFletApp.__init__ start")
        self.page = page
        self.session = UserSession()
        print("[aurex] UserSession created")
        self.client = AurexProtocolClient(self.session)
        print("[aurex] AurexProtocolClient created")
        self.client.on_server_event = self._on_server_event

        self.market_loading = False
        self.market_error: str | None = None
        self._market_bootstrap_requested = False
        self._render_lock = threading.RLock()
        self._market_refresh_lock = threading.Lock()
        self._market_refresh_timer: threading.Timer | None = None
        self._last_market_refresh = 0.0

        self.page.title = "Aurex Marketplace"
        self.page.theme_mode = ft.ThemeMode.DARK
        self.page.theme = build_aurex_theme()
        self.page.bgcolor = AUREX_BG
        self.page.padding = 0
        self.page.scroll = ft.ScrollMode.AUTO
        self.page.on_route_change = self._on_route_change
        self.page.on_view_pop = self._on_view_pop

        print("[aurex] AurexFletApp.__init__ done")

    def start(self) -> None:
        route = self.page.route or "/login"
        print(f"[aurex] start() -> going to {route!r}")
        self._render_current_route()
        print(f"[aurex] start() -> initial render done")

    def show_message(self, message: str, *, error: bool = False) -> None:
        """Show a snackbar message from any thread (UI or background worker).

        Direct page.update() from a background thread is silently ignored by
        Flet, so protocol errors (ERR02|Cannot buy your own asset, etc.) never
        appeared in the UI.  page.run_task schedules the update on the event
        loop so it always fires correctly.
        """
        async def _show() -> None:
            self.page.snack_bar = ft.SnackBar(
                content=ft.Text(message, color="white"),
                bgcolor=AUREX_ERROR if error else AUREX_SUCCESS,
            )
            self.page.snack_bar.open = True
            self.page.update()

        self.page.run_task(_show)

    def connect_if_needed(self, *, discover_first: bool = True) -> None:
        self.client.connect(discover_first=discover_first)

    def logout(self) -> None:
        try:
            self.client.logout()
        finally:
            self.market_error = None
            self.market_loading = False
            self._market_bootstrap_requested = False
            self.page.run_task(self.page.push_route, "/login")

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

        # Fetch wallet AFTER market items, BEFORE image prefetch threads.
        # Must be sequential — prefetch threads share the same socket and
        # will corrupt interleaved reads if wallet fetch overlaps them.
        if self.session.user_data:
            try:
                balance = self.client.get_wallet(self.session.user_data.username)
                print(f"[aurex] wallet fetch -> {balance!r}")
                if balance is not None:
                    self.session.wallet_balance = balance
            except Exception as exc:
                print(f"[aurex] wallet fetch failed: {exc}")

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
            else:
                self.session.image_cache[rel_path] = ""
        except Exception as exc:
            self.session.remember(f"image download failed for {rel_path}: {exc}")
            self.session.image_cache[rel_path] = ""
        finally:
            with self.session.lock:
                self.session.loading_images.discard(rel_path)
            self.refresh_marketplace_view()

    def refresh_marketplace_view(self) -> None:
        if self.page.route == "/marketplace":
            self._schedule_marketplace_refresh()
        else:
            self.page.run_task(self._noop_update_async)

    def _schedule_marketplace_refresh(self, min_interval: float = 0.25) -> None:
        """Coalesce rapid refresh calls to avoid UI thrash on initial load."""
        now = time.monotonic()
        with self._market_refresh_lock:
            if now - self._last_market_refresh >= min_interval:
                self._last_market_refresh = now
                self.page.run_task(self._render_current_route_async)
                return
            if self._market_refresh_timer and self._market_refresh_timer.is_alive():
                return
            delay = max(0.01, min_interval - (now - self._last_market_refresh))
            self._market_refresh_timer = threading.Timer(delay, self._trigger_marketplace_refresh)
            self._market_refresh_timer.daemon = True
            self._market_refresh_timer.start()

    def _trigger_marketplace_refresh(self) -> None:
        with self._market_refresh_lock:
            self._last_market_refresh = time.monotonic()
        self.page.run_task(self._render_current_route_async)

    async def _render_current_route_async(self) -> None:
        self._render_current_route()

    async def _noop_update_async(self) -> None:
        self.page.update()

    def _on_route_change(self, _: ft.RouteChangeEvent) -> None:
        self._render_current_route()

    def _on_view_pop(self, _: ft.ViewPopEvent) -> None:
        if len(self.page.views) > 1:
            self.page.views.pop()
            self.page.run_task(self.page.push_route, self.page.views[-1].route)
        else:
            self.page.run_task(self.page.push_route, "/login")

    def _render_current_route(self) -> None:
        route = self.page.route or "/login"
        print(f"[aurex] _render_current_route: {route!r}")
        protected = {"/marketplace", "/settings", "/upload", "/my_assets"}
        if route in protected and not self.session.is_authenticated:
            route = "/login"
            self.page.route = route

        builders = {
            "/login": build_login_view,
            "/signup": build_signup_view,
            "/forgot": build_forgot_view,
            "/marketplace": build_marketplace_view,
            "/settings": build_settings_view,
            "/upload": build_upload_view,
            "/notifications": build_notifications_view,
            "/my_assets": build_my_assets_view,
        }
        builder = builders.get(route, build_login_view)
        try:
            view = builder(self)
        except Exception as exc:
            import traceback
            traceback.print_exc()
            view = ft.View(
                route=route,
                bgcolor="#1A1A1B",
                controls=[ft.Text(f"Error loading page: {exc}", color="red", size=14)],
            )
        with self._render_lock:
            self.page.views.clear()
            self.page.views.append(view)
            self.page.update()

    def push_notification(self, title: str, body: str, notif_type: str = "info") -> None:
        """Add a notification and refresh the bell badge if on marketplace."""
        _notif_store.push_notification(title, body, notif_type)
        self.page.run_task(self._noop_update_async)

    def _on_server_event(self, event) -> None:
        pass  # pubsub not used in Flet 0.83
