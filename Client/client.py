"""Aurex desktop client heart: protocol + routing + app state."""

from __future__ import annotations

import base64
import json
import os
import sys
import threading
from dataclasses import dataclass, field
from pathlib import Path

import flet as ft

# Adds the root folder to enable imports from SharedResources
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from SharedResources.classes import RSA_Client
from SharedResources.config import SERVER_IP, SERVER_PORT
try:
    from Client.wallet_manager import WalletData, WalletManager
    from Client.pages import (
        build_forgot_view,
        build_login_view,
        build_marketplace_view,
        build_my_assets_view,
        build_notifications_view,
        build_wallet_settings_view,
        build_signup_view,
        build_upload_view,
    )
except Exception:
    from wallet_manager import WalletData, WalletManager
    from pages import (
        build_forgot_view,
        build_login_view,
        build_marketplace_view,
        build_my_assets_view,
        build_notifications_view,
        build_wallet_settings_view,
        build_signup_view,
        build_upload_view,
    )

PROJECT_ROOT = Path(__file__).resolve().parent.parent
ASSETS_DIR = PROJECT_ROOT / "assets"
ICON_PATH = ASSETS_DIR / "images" / "gold_icon.png"

@dataclass
class MarketItem:
    """UI-friendly marketplace item."""

    asset_id: str
    owner: str
    title: str
    description: str
    file_type: str
    price: float
    created_at: str
    #TODO: add a pk value for easier handling of purchases


@dataclass
class ClientState:
    """In-memory UI/session state."""

    username: str | None = None
    email: str | None = None
    is_authenticated: bool = False
    verified_reset_user: str | None = None
    market_items: list[MarketItem] = field(default_factory=list)
    notifications: list[str] = field(default_factory=list)
    wallet_loaded: bool = False
    wallet_public_key: str | None = None
    wallet_username: str | None = None


class ServerClient:
    """Sync dict-protocol wrapper over RSA_Client/Communication."""

    def __init__(self, host=SERVER_IP, port=SERVER_PORT):
        self.host = host
        self.port = int(port)
        self._lock = threading.RLock()
        self._transport = None
        self._comm = None

    def connect(self):
        """Open TCP + RSA/AES session once."""
        with self._lock:
            if self._comm is not None:
                return
            self._transport = RSA_Client(self.host, self.port, name="ClientUI")
            self._transport.sock.connect((self.host, self.port))
            self._transport.contact_with_RSA()
            self._comm = self._transport.communication

    def close(self):
        """Close transport safely."""
        with self._lock:
            if self._comm is not None:
                try:
                    self._comm.close()
                except Exception:
                    pass
            self._comm = None
            self._transport = None

    def _request(self, payload):
        """Send one dict request and receive dict response."""
        self.connect()
        with self._lock:
            self._comm.send_one_message(payload)
            resp = self._comm.recv_one_message()
        if not isinstance(resp, dict):
            raise RuntimeError("Invalid server response")
        if resp.get("type") != "OK":
            raise RuntimeError(str(resp.get("message", "Unknown server error")))
        return resp

    def login(self, username, password):
        return self._request({"type": "LOGIN", "username": username, "password": password})

    def signup(self, username, password, email):
        return self._request({"type": "SIGNUP", "username": username, "password": password, "email": email})

    def send_code(self, email):
        return self._request({"type": "SEND_CODE", "email": email})

    def verify_code(self, email, code):
        return self._request({"type": "VERIFY_CODE", "email": email, "code": code})

    def update_password(self, email, new_password):
        return self._request({"type": "UPDATE_PASSWORD", "email": email, "new_password": new_password})

    def logout(self):
        return self._request({"type": "LOGOUT"})

    def update_public_key(self, username, public_key):
        return self._request({"type": "UPDATE_PUBLIC_KEY", "username": username, "public_key": public_key})

    def get_items(self):
        return self._request({"type": "GET_ITEMS"})

    def upload_file(self, username, file_path, asset_name, description, file_type, cost):
        """Upload file with UPLOAD_INIT -> UPLOAD chunks -> UPLOAD_FINISH."""
        upload_init = self._request(
            {
                "type": "UPLOAD_INIT",
                "username": username,
                "asset_name": asset_name,
                "description": description,
                "file_type": file_type,
                "cost": cost,
            }
        )
        upload_id = str(upload_init.get("upload_id", ""))
        if not upload_id:
            raise RuntimeError("Missing upload_id")
        raw = Path(file_path).read_bytes()
        b64 = base64.b64encode(raw).decode("ascii")
        chunk_size = 120_000
        for i in range(0, len(b64), chunk_size):
            self._request({"type": "UPLOAD", "upload_id": upload_id, "chunk_b64": b64[i : i + chunk_size]})
        return self._request({"type": "UPLOAD_FINISH", "upload_id": upload_id})


class ClientApp:
    """Flet app controller: state, actions, and routing."""

    def __init__(self, page):
        self.page = page
        self.client = ServerClient()
        self.wallet_manager = WalletManager()
        self.state = ClientState()
        self.wallet_session: WalletData | None = None
        self.page.title = "Aurex"
        self.page.theme_mode = ft.ThemeMode.DARK
        self.page.theme = ft.Theme(font_family="Trebuchet MS")
        self.page.padding = 0
        self.page.bgcolor = "#090B0F"
        try:
            self.page.window.icon = str(ICON_PATH)
            self.page.window.min_width = 1000
            self.page.window.min_height = 680
        except Exception:
            pass
        self.page.on_route_change = self._on_route_change
        self.page.on_view_pop = self._on_view_pop

    def start(self):
        """Render first route."""
        self.page.go("/login")

    def notify(self, message, error=False):
        """Show snackbar notification."""
        if error:
            self.page.dialog = ft.AlertDialog(
                modal=False,
                title=ft.Text("Error", color="#F6D2D2"),
                content=ft.Text(str(message), color="#F1F4F8"),
                bgcolor="#2A0E12",
                actions=[ft.TextButton("Close", on_click=lambda e: self._close_error_dialog())],
                actions_alignment=ft.MainAxisAlignment.END,
            )
            self.page.dialog.open = True
        else:
            self.page.snack_bar = ft.SnackBar(content=ft.Text(message), bgcolor="#136F3A")
            self.page.snack_bar.open = True
        self.page.update()

    def _close_error_dialog(self):
        if self.page.dialog:
            self.page.dialog.open = False
            self.page.update()

    def _on_route_change(self, _):
        route = self.page.route or "/login"
        private_routes = {"/wallet", "/marketplace", "/upload", "/my_assets", "/notifications"}
        if route in private_routes and not self.state.is_authenticated:
            route = "/login"
            self.page.route = route
        if self.state.is_authenticated and route in {"/marketplace", "/upload", "/my_assets", "/notifications"} and not self.state.wallet_loaded:
            route = "/wallet"
            self.page.route = route
        builders = {
            "/login": build_login_view,
            "/signup": build_signup_view,
            "/forgot": build_forgot_view,
            "/wallet": build_wallet_settings_view,
            "/marketplace": build_marketplace_view,
            "/upload": build_upload_view,
            "/notifications": build_notifications_view,
            "/my_assets": build_my_assets_view,
        }
        try:
            view = builders.get(route, build_login_view)(self)
        except Exception as e:
            view = ft.View(
                route=route,
                bgcolor="#101317",
                controls=[
                    ft.Container(
                        expand=True,
                        alignment=ft.Alignment(0, 0),
                        content=ft.Text(f"UI error: {e}", color="red"),
                    )
                ],
            )
        self.page.views.clear()
        self.page.views.append(view)
        self.page.update()

    def _on_view_pop(self, _):
        if len(self.page.views) > 1:
            self.page.views.pop()
            self.page.go(self.page.views[-1].route)
        else:
            self.page.go("/login")

    def login(self, username, password):
        resp = self.client.login(username, password)
        self.state.username = str(resp.get("username") or username)
        self.state.is_authenticated = True
        self._load_wallet_session_from_default()
        self.state.notifications.append("Logged in successfully")
        return resp

    def signup(self, username, password, email):
        resp = self.client.signup(username, password, email)
        self.state.username = str(resp.get("username") or username)
        self.state.email = email
        return resp

    def send_code(self, email):
        return self.client.send_code(email)

    def verify_code(self, email, code):
        resp = self.client.verify_code(email, code)
        self.state.verified_reset_user = str(resp.get("username", ""))
        self.state.email = email
        return resp

    def update_password(self, email, new_password):
        return self.client.update_password(email, new_password)

    def logout(self):
        self.client.logout()
        self.client.close()
        self.state = ClientState()
        self.wallet_session = None

    def refresh_market_items(self):
        resp = self.client.get_items()
        items = []
        for raw in resp.get("items", []):
            items.append(
                MarketItem(
                    asset_id=str(raw.get("asset_id", "")),
                    owner=str(raw.get("owner", "")),
                    title=str(raw.get("asset_name", "")),
                    description=str(raw.get("description", "")),
                    file_type=str(raw.get("file_type", "")),
                    price=float(raw.get("cost", 0.0)),
                    created_at=str(raw.get("created_at", "")),
                )
            )
        self.state.market_items = items
        return items

    def upload_asset(self, file_path, asset_name, description, file_type, cost):
        if not self.state.username:
            raise RuntimeError("Not authenticated")
        tx_payload = {
            "username": self.state.username,
            "asset_name": asset_name,
            "description": description,
            "file_type": file_type,
            "cost": float(cost),
        }
        signature = self.sign_payload(tx_payload) if self.wallet_session else ""
        resp = self.client.upload_file(
            self.state.username,
            file_path,
            asset_name,
            description,
            file_type,
            cost,
        )
        self.state.notifications.append(f"Uploaded asset: {asset_name}")
        if signature:
            self.state.notifications.append("Upload payload signed locally")
        return resp

    def update_public_key(self, public_key):
        if not self.state.username:
            raise RuntimeError("Not authenticated")
        return self.client.update_public_key(self.state.username, public_key)

    # ----- wallet session + actions -----

    def sign_payload(self, payload: dict) -> str:
        if not self.wallet_session:
            raise RuntimeError("Wallet not loaded")
        return self.wallet_session.sign_payload(payload)

    def _set_wallet_session(self, wallet: WalletData):
        if not self.state.username:
            raise RuntimeError("Not authenticated")
        if wallet.username != self.state.username:
            raise RuntimeError("Wallet username does not match logged-in user")
        self.wallet_session = wallet
        self.state.wallet_loaded = True
        self.state.wallet_public_key = wallet.public_key
        self.state.wallet_username = wallet.username
        self.update_public_key(wallet.public_key)

    def _load_wallet_session_from_default(self):
        if not self.state.username:
            return None
        try:
            wallet = self.wallet_manager.load_wallet_for_user(self.state.username)
        except Exception:
            return None
        if wallet:
            self._set_wallet_session(wallet)
        return wallet

    def load_wallet_from_file(self, file_path: str):
        wallet = self.wallet_manager.load_wallet_from_path(Path(file_path))
        self._set_wallet_session(wallet)
        self.wallet_manager.save_wallet(wallet, self.wallet_manager.wallet_path_for_user(self.state.username or wallet.username))
        return wallet

    def generate_new_wallet(self):
        if not self.state.username:
            raise RuntimeError("Not authenticated")
        wallet = self.wallet_manager.generate_wallet(self.state.username)
        self._set_wallet_session(wallet)
        self.state.notifications.append("Generated new wallet. Previous assets remain tied to old public key.")
        return wallet

    def load_default_wallet(self):
        wallet = self._load_wallet_session_from_default()
        if not wallet:
            raise RuntimeError("No local wallet found for this user")
        return wallet

    def export_wallet(self, output_path: str):
        if not self.wallet_session:
            raise RuntimeError("Wallet not loaded")
        self.wallet_manager.save_wallet(self.wallet_session, Path(output_path))

    def wallet_preview(self) -> str:
        if not self.wallet_session:
            return ""
        return json.dumps(
            {
                "username": self.wallet_session.username,
                "public_key": self.wallet_session.public_key,
                "private_key": self.wallet_session.private_key[:16] + "...",
            },
            ensure_ascii=False,
            indent=2,
        )


def main(page):
    """Desktop entrypoint."""
    app = ClientApp(page)
    app.start()


if __name__ == "__main__":
    ft.app(target=main, view=ft.AppView.FLET_APP, assets_dir=str(ASSETS_DIR))
