"""Aurex desktop client heart: protocol + routing + app state."""

from __future__ import annotations

import base64
import json
import logging
import os
import shutil
import sys
import threading
import hashlib
import time
import uuid
import queue
from dataclasses import dataclass, field
from pathlib import Path

import flet as ft

# Adds the root folder to enable imports from SharedResources
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from SharedResources.classes import RSA_Client
from SharedResources.config import SERVER_IP, SERVER_PORT
from SharedResources.logging import Logger
logger = Logger(__file__)

try:
    from Client.wallet_manager import WalletData, WalletManager
    from Client.pages import (
        build_forgot_view,
        build_login_view,
        build_marketplace_view,
        build_my_assets_view,
        build_notifications_view,
        build_settings_view,
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
        build_settings_view,
        build_signup_view,
        build_upload_view,
    )

PROJECT_ROOT = Path(__file__).resolve().parent.parent
ASSETS_DIR = PROJECT_ROOT / "assets"
ICON_PATH = ASSETS_DIR / "flet_assets" / "icon.ico"
_ICON_FALLBACK = ASSETS_DIR / "flet_assets" / "aurex_icon.ico"

# Push-only events the server sends proactively — routed away from response_queue.
_PUSH_EVENTS = frozenset({
    "NOTIFICATION",
    "BUY_SUCCESS", "BUY_FAILED",
    "BLOCK_ACCEPTED", "BLOCK_REJECTED",
    "BALANCE_UPDATED", "BALANCE_IS",
    "FULLY_UPLOADED",
    "ASSET_LISTED",
    "ASSET_SOLD",
    "ASSET_REMOVED",
    "ASSET_UNLISTED",
})


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
    public_key_hex: str
    asset_status: str = "PENDING"
    version: int = 1


class ImageCache:
    """Per-user RAM + disk image cache with versioning.

    metadata.json layout:
    {
      "balance": 0.0,
      "<asset_id>": {
        "path": "assets/<asset_id>.<ext>",
        "version": <int>,
        "asset_id": "...",
        "asset_name": "...",
        "description": "...",
        "owner": "...",
        "file_type": "png",
        "cost": 100.0,
        "created_at": "...",
        "asset_status": "FOR_SALE",
        "public_key": "..."
      },
      ...
    }
    """

    def __init__(self, username: str):
        self.username = username
        self._ram: dict[str, bytes] = {}
        self._lock = threading.Lock()
        self._cache_dir = PROJECT_ROOT / "Client" / username / "cache"
        self._assets_dir = self._cache_dir / "assets"
        self._metadata_path = self._cache_dir / "metadata.json"
        self._assets_dir.mkdir(parents=True, exist_ok=True)
        self._metadata: dict = self._load_metadata()
        if "balance" not in self._metadata:
            self._metadata["balance"] = 0.0
        self._validate_and_migrate()

    def _load_metadata(self) -> dict:
        try:
            if self._metadata_path.exists():
                return json.loads(self._metadata_path.read_text(encoding="utf-8"))
        except Exception:
            pass
        return {}

    def _save_metadata(self):
        try:
            self._metadata_path.write_text(
                json.dumps(self._metadata, indent=2, ensure_ascii=False), encoding="utf-8"
            )
        except Exception:
            pass

    def _validate_and_migrate(self):
        """Detect old format (string values or nested 'meta' key) and clear/migrate."""
        needs_clear = False
        for k, v in list(self._metadata.items()):
            if k == "balance":
                continue
            if isinstance(v, str):
                needs_clear = True
                break
            if isinstance(v, dict) and "meta" in v:
                # Old nested format — migrate in place
                old_meta = v.get("meta", {})
                v.update(old_meta)
                del v["meta"]
        if needs_clear:
            self._clear_cache()

    def _clear_cache(self):
        try:
            if self._assets_dir.exists():
                shutil.rmtree(self._assets_dir)
            self._assets_dir.mkdir(parents=True, exist_ok=True)
        except Exception:
            pass
        balance = self._metadata.get("balance", 0.0)
        self._metadata = {"balance": balance}
        self._ram = {}
        self._save_metadata()

    # ── Balance ────────────────────────────────────────────────────────────────

    def get_balance(self) -> float:
        return float(self._metadata.get("balance", 0.0))

    def set_balance(self, amount: float):
        with self._lock:
            self._metadata["balance"] = float(amount)
            self._save_metadata()

    # ── Assets ─────────────────────────────────────────────────────────────────

    def get_raw(self, asset_id: str) -> bytes | None:
        with self._lock:
            if asset_id in self._ram:
                return self._ram[asset_id]
            entry = self._metadata.get(asset_id)
            if isinstance(entry, dict):
                full = self._cache_dir / entry.get("path", "")
                if full.exists():
                    raw = full.read_bytes()
                    self._ram[asset_id] = raw
                    return raw
        return None

    def get_path(self, asset_id: str) -> "Path | None":
        with self._lock:
            entry = self._metadata.get(asset_id)
            if not isinstance(entry, dict):
                return None
            full = self._cache_dir / entry.get("path", "")
            if full.exists():
                return full
        return None

    def get_if_current(self, asset_id: str, server_version: int) -> "tuple[dict, bytes] | None":
        """Return (entry_dict, raw) if cached version >= server_version and entry is non-empty."""
        with self._lock:
            entry = self._metadata.get(asset_id)
            if not isinstance(entry, dict):
                return None
            if int(entry.get("version", 0)) < server_version:
                return None
            if not entry.get("asset_name"):
                return None
            raw = self._ram.get(asset_id)
            if raw is None:
                full = self._cache_dir / entry.get("path", "")
                if not full.exists():
                    return None
                raw = full.read_bytes()
                self._ram[asset_id] = raw
            return entry, raw

    def store(self, asset_id: str, file_type: str, version: int, meta: dict, raw: bytes):
        """Store image bytes and flattened metadata for an asset."""
        with self._lock:
            fname = f"{asset_id}.{file_type}"
            path = self._assets_dir / fname
            path.write_bytes(raw)
            entry = dict(meta)
            entry["path"] = f"assets/{fname}"
            entry["version"] = version
            self._metadata[asset_id] = entry
            self._save_metadata()
            self._ram[asset_id] = raw

    def invalidate(self, asset_id: str):
        with self._lock:
            entry = self._metadata.pop(asset_id, None)
            self._ram.pop(asset_id, None)
            if isinstance(entry, dict):
                try:
                    (self._cache_dir / entry.get("path", "")).unlink(missing_ok=True)
                except Exception:
                    pass
            self._save_metadata()


@dataclass
class ClientState:
    """In-memory UI/session state."""

    username: str | None = None
    email: str | None = None
    is_authenticated: bool = False
    verified_reset_user: str | None = None
    market_items: list[MarketItem] = field(default_factory=list)
    notifications: list[str] = field(default_factory=list)
    unseen_notifications: int = 0
    wallet_loaded: bool = False
    wallet_public_key: str | None = None
    wallet_username: str | None = None
    wallet_status_message: str = ""
    balance: float = 0.0


class ServerClient:
    """Sync dict-protocol wrapper over RSA_Client/Communication."""

    def __init__(self, host=SERVER_IP, port=SERVER_PORT):
        self.host = host
        self.port = int(port)
        self._lock = threading.RLock()
        self._transport = None
        self._comm = None
        self._receiver_thread = None
        self._stop_event = threading.Event()
        self._response_queue: "queue.Queue[dict | None]" = queue.Queue()
        self.notification_queue: "queue.Queue[str]" = queue.Queue()
        self.asset_sold_queue: "queue.Queue[str]" = queue.Queue()
        self.asset_removed_queue: "queue.Queue[str]" = queue.Queue()
        self.asset_unlisted_queue: "queue.Queue[str]" = queue.Queue()
        self.balance_queue: "queue.Queue[float]" = queue.Queue()
        self.bought_asset_queue: "queue.Queue[str]" = queue.Queue()

    def connect(self):
        with self._lock:
            if self._comm is not None:
                return
            self._transport = RSA_Client(self.host, self.port, name="ClientUI", peer_label="Server")
            self._transport.sock.connect((self.host, self.port))
            self._transport.contact_with_RSA()
            self._comm = self._transport.communication
            self._comm.start_async(default_encryption=True)
            self._stop_event.clear()
            self._receiver_thread = threading.Thread(target=self._recv_dispatch_loop, daemon=True)
            self._receiver_thread.start()

    def close(self):
        with self._lock:
            self._stop_event.set()
            if self._comm is not None:
                try:
                    self._comm.close()
                except Exception:
                    pass
            self._comm = None
            self._transport = None

    def _recv_dispatch_loop(self):
        while not self._stop_event.is_set():
            comm = self._comm
            if comm is None:
                break
            msg = comm.recv_async(timeout=0.25)
            if msg is None:
                continue
            if comm.is_close_marker(msg):
                break
            if not isinstance(msg, dict):
                continue
            msg_type = str(msg.get("type", "")).upper()
            if msg_type in _PUSH_EVENTS:
                if msg_type == "NOTIFICATION":
                    self.notification_queue.put(str(msg.get("msg", "")))
                elif msg_type == "BUY_SUCCESS":
                    asset_id = str(msg.get("asset_id", ""))
                    text = str(msg.get("msg") or f"Purchase confirmed — asset {asset_id} at {msg.get('price', '')} AUR is now yours!")
                    self.notification_queue.put(text)
                    if asset_id:
                        self.bought_asset_queue.put(asset_id)
                elif msg_type == "BUY_FAILED":
                    self.notification_queue.put(f"Transaction failed: {msg.get('message', 'Unknown reason')}")
                elif msg_type == "BLOCK_ACCEPTED":
                    self.notification_queue.put(f"Block accepted for asset {msg.get('asset_id', '')}")
                elif msg_type == "BLOCK_REJECTED":
                    self.notification_queue.put(f"Block rejected: {msg.get('message', 'Unknown reason')}")
                elif msg_type in ("BALANCE_UPDATED", "BALANCE_IS"):
                    balance = float(msg.get("balance", 0.0))
                    self.balance_queue.put(balance)
                elif msg_type in ("FULLY_UPLOADED", "ASSET_LISTED"):
                    self.notification_queue.put(str(msg.get("msg", f"Asset {msg.get('asset_id', '')} is now live on the marketplace")))
                elif msg_type == "ASSET_SOLD":
                    asset_id = str(msg.get("asset_id", ""))
                    text = str(msg.get("msg") or f"Your asset {asset_id} was sold")
                    self.notification_queue.put(text)
                    if asset_id:
                        self.asset_sold_queue.put(asset_id)
                elif msg_type in ("ASSET_REMOVED", "ASSET_UNLISTED"):
                    asset_id = str(msg.get("asset_id", ""))
                    msg_text = str(msg.get("msg", f"Asset {asset_id} was unlisted"))
                    self.notification_queue.put(msg_text)
                    if asset_id:
                        self.asset_unlisted_queue.put(asset_id)
                continue
            self._response_queue.put(msg)

    def _request(self, payload, timeout=20):
        self.connect()
        with self._lock:
            self._comm.send_async(payload)
            try:
                resp = self._response_queue.get(timeout=timeout)
            except queue.Empty as exc:
                raise RuntimeError("Server response timeout") from exc
        if not isinstance(resp, dict):
            raise RuntimeError("Invalid server response")
        resp_type = str(resp.get("type", "")).upper()
        if resp_type == "ERROR":
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

    def update_password(self, email, new_password, code):
        return self._request({"type": "UPDATE_PASSWORD", "email": email, "new_password": new_password, "code": code})

    def logout(self):
        return self._request({"type": "LOGOUT"})

    def update_public_key(self, username, public_key):
        return self._request({"type": "UPDATE_PUBLIC_KEY", "username": username, "public_key": public_key})

    def get_assets_ids(self, username: str = ""):
        return self._request({"type": "GET_ASSETS_IDS", "username": username})

    def delete_account(self, username: str):
        return self._request({"type": "DELETE_ACCOUNT", "username": username})

    def move_to_marketplace(self, username: str, asset_id: str):
        return self._request({"type": "MOVE_TO_MARKETPLACE", "username": username, "asset_id": asset_id})

    def buy_asset(self, payload):
        return self._request({"type": "BUY_ASSET", "data": payload})

    def delete_asset(self, asset_id: str, owner: str):
        return self._request({"type": "DELETE_ASSET", "asset_id": asset_id, "owner": owner})

    def unlist_asset(self, username: str, asset_id: str, public_key: str = "", signature: str = ""):
        return self._request({
            "type": "UNLIST_ASSET",
            "username": username,
            "asset_id": asset_id,
            "public_key": public_key,
            "signature": signature,
        })

    def request_balance(self, public_key: str):
        """Fire-and-forget: server acks immediately, result arrives via BALANCE_IS push."""
        return self._request({"type": "GET_BALANCE", "user_public_key": public_key})

    def upload_file(self, username, file_path, asset_name, description, file_type, cost, signature="", public_key="", signed_payload=None, for_sale=True):
        upload_id = uuid.uuid4().hex
        self._request(
            {
                "type": "UPLOAD_INIT",
                "upload_id": upload_id,
                "username": username,
                "asset_name": asset_name,
                "description": description,
                "file_type": file_type,
                "cost": cost,
                "signature": signature,
                "public_key": public_key,
                "signed_payload": signed_payload or {},
                "for_sale": for_sale,
            }
        )
        raw = Path(file_path).read_bytes()
        b64 = base64.b64encode(raw).decode("ascii")
        chunk_size = 32_000
        for i in range(0, len(b64), chunk_size):
            self._request({"type": "UPLOAD", "upload_id": upload_id, "chunk_b64": b64[i : i + chunk_size]})
        return self._request({"type": "UPLOAD_FINISH", "upload_id": upload_id})

    def download_asset(self, asset_id: str, timeout: int = 30) -> tuple[dict, bytes]:
        self.connect()
        with self._lock:
            self._comm.send_async({"type": "GET_ASSET_BY_ID", "id": asset_id})
            try:
                init_msg = self._response_queue.get(timeout=timeout)
            except queue.Empty as exc:
                raise RuntimeError("Download timeout (ASSET_INIT)") from exc
            if not isinstance(init_msg, dict):
                raise RuntimeError("Invalid server response during download")
            if init_msg.get("type") == "ERROR":
                raise RuntimeError(str(init_msg.get("message", "Asset download failed")))
            if init_msg.get("type") != "ASSET_INIT":
                raise RuntimeError(f"Unexpected response: {init_msg.get('type')}")
            total_chunks = int(init_msg.get("total_chunks", 0))
            chunks: list[str] = []
            for _ in range(total_chunks):
                try:
                    chunk_msg = self._response_queue.get(timeout=timeout)
                except queue.Empty as exc:
                    raise RuntimeError("Download timeout (chunk)") from exc
                if not isinstance(chunk_msg, dict) or chunk_msg.get("type") != "ASSET_CHUNK":
                    raise RuntimeError(
                        f"Expected ASSET_CHUNK, got {chunk_msg.get('type') if isinstance(chunk_msg, dict) else '?'}"
                    )
                chunks.append(str(chunk_msg.get("chunk_b64", "")))
            try:
                end_msg = self._response_queue.get(timeout=timeout)
            except queue.Empty as exc:
                raise RuntimeError("Download timeout (ASSET_END)") from exc
            if not isinstance(end_msg, dict) or end_msg.get("type") != "ASSET_END":
                raise RuntimeError(
                    f"Expected ASSET_END, got {end_msg.get('type') if isinstance(end_msg, dict) else '?'}"
                )
        raw = base64.b64decode("".join(chunks).encode("ascii"))
        return init_msg, raw


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
        self.page.on_route_change = self._on_route_change
        self.page.on_view_pop = self._on_view_pop
        self._image_cache: ImageCache | None = None
        self._sold_asset_ids: set[str] = set()
        self._removed_asset_ids: set[str] = set()
        self._unlisted_asset_ids: set[str] = set()
        # Refs to live header controls — updated by background monitors
        self._balance_text: ft.Text | None = None
        self._notification_badge: ft.Container | None = None

    def start(self):
        self.page.go("/login")

    def notify(self, message, error=False):
        if error:
            self.page.dialog = ft.AlertDialog(
                modal=True,
                title=ft.Text("Error", color="#F6D2D2"),
                content=ft.Text(str(message), color="#F1F4F8"),
                bgcolor="#2A0E12",
                actions=[ft.TextButton("Close", on_click=lambda e: self._close_error_dialog())],
                actions_alignment=ft.MainAxisAlignment.END,
            )
            self.page.dialog.open = True
            self.page.snack_bar = ft.SnackBar(content=ft.Text(str(message)), bgcolor="#7D2032")
            self.page.snack_bar.open = True
        else:
            self.page.snack_bar = ft.SnackBar(content=ft.Text(message), bgcolor="#136F3A")
            self.page.snack_bar.open = True
        self.page.update()

    def _drain_server_notifications(self):
        self._consume_notification_queue()

    def _consume_notification_queue(self):
        count = 0
        while True:
            try:
                msg = self.client.notification_queue.get_nowait()
            except queue.Empty:
                break
            if msg:
                self.state.notifications.append(msg)
                count += 1
        if count > 0:
            self.state.unseen_notifications += count
            self._update_notification_badge()

    def _update_notification_badge(self):
        badge = self._notification_badge
        if badge is None:
            return
        count = self.state.unseen_notifications
        badge.visible = count > 0
        label = badge.content
        if label is not None:
            label.value = str(min(count, 99))
        try:
            badge.update()
        except Exception:
            pass

    def _start_notification_monitor(self):
        def _monitor():
            while True:
                time.sleep(0.4)
                self._consume_notification_queue()
        threading.Thread(target=_monitor, daemon=True).start()

    def _drain_asset_events(self):
        while True:
            try:
                asset_id = self.client.asset_sold_queue.get_nowait()
            except queue.Empty:
                break
            self._sold_asset_ids.add(asset_id)
            self.image_cache.invalidate(asset_id)
        while True:
            try:
                asset_id = self.client.asset_removed_queue.get_nowait()
            except queue.Empty:
                break
            self._removed_asset_ids.add(asset_id)
        while True:
            try:
                asset_id = self.client.asset_unlisted_queue.get_nowait()
            except queue.Empty:
                break
            self._unlisted_asset_ids.add(asset_id)

    def _drain_balance_events(self):
        """Drain balance queue, update state, update UI text if visible."""
        while True:
            try:
                balance = self.client.balance_queue.get_nowait()
            except queue.Empty:
                break
            self.state.balance = balance
            if self._image_cache:
                self._image_cache.set_balance(balance)
            if self._balance_text is not None:
                try:
                    self._balance_text.value = f"{balance:.2f} AUR"
                    self._balance_text.update()
                except Exception:
                    pass

    def _start_balance_monitor(self):
        """Background thread that updates the UI balance display as events arrive."""
        def _monitor():
            while True:
                time.sleep(0.5)
                self._drain_balance_events()
        threading.Thread(target=_monitor, daemon=True).start()

    def _start_bought_asset_downloader(self):
        """Background thread that auto-downloads assets the user just purchased."""
        def _worker():
            while True:
                try:
                    asset_id = self.client.bought_asset_queue.get(timeout=10)
                except queue.Empty:
                    continue
                if not self.state.is_authenticated:
                    continue
                try:
                    self.load_asset_by_id(asset_id)
                    logger.info(f"Auto-downloaded bought asset {asset_id}")
                except Exception as exc:
                    logger.warning(f"Auto-download failed for bought asset {asset_id}: {exc}")
        threading.Thread(target=_worker, daemon=True).start()

    def _close_error_dialog(self):
        if self.page.dialog:
            self.page.dialog.open = False
            self.page.update()

    def _on_route_change(self, _):
        self._drain_server_notifications()
        self._drain_asset_events()
        self._drain_balance_events()
        route = self.page.route or "/login"
        if route == "/notifications":
            self.state.unseen_notifications = 0
            self._update_notification_badge()
        private_routes = {"/settings", "/marketplace", "/upload", "/my_assets", "/notifications"}
        if route in private_routes and not self.state.is_authenticated:
            route = "/login"
            self.page.route = route
        if self.state.is_authenticated and route in {"/marketplace", "/upload", "/my_assets", "/notifications"} and not self.state.wallet_loaded:
            route = "/settings"
            self.page.route = route
        builders = {
            "/login": build_login_view,
            "/signup": build_signup_view,
            "/forgot": build_forgot_view,
            "/settings": build_settings_view,
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
        self._drain_server_notifications()
        self.state.notifications.append("Logged in successfully")
        # Load cached balance before requesting fresh one
        if self._image_cache:
            self.state.balance = self._image_cache.get_balance()
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

    def update_password(self, email, new_password, code):
        return self.client.update_password(email, new_password, code)

    @property
    def image_cache(self) -> ImageCache:
        username = self.state.username or "_anonymous"
        if self._image_cache is None or self._image_cache.username != username:
            self._image_cache = ImageCache(username)
            self.state.balance = self._image_cache.get_balance()
        return self._image_cache

    def get_asset_image(self, asset_id: str, file_type: str) -> bytes | None:
        try:
            raw = self.image_cache.get_raw(asset_id)
            if raw:
                return raw
            _, raw = self.client.download_asset(asset_id)
            self.image_cache.store(asset_id, file_type, 0, {}, raw)
            return raw
        except Exception as exc:
            logger.warning(f"Image download failed for {asset_id}: {exc}")
            return None

    def logout(self):
        self.client.logout()
        self.client.close()
        self.state = ClientState()
        self.wallet_session = None
        self._image_cache = None
        self._sold_asset_ids = set()
        self._removed_asset_ids = set()
        self._unlisted_asset_ids = set()
        self._balance_text = None
        self._notification_badge = None

    def delete_account(self):
        if not self.state.username:
            raise RuntimeError("Not authenticated")
        self.client.delete_account(self.state.username)
        try:
            self.client.close()
        except Exception:
            pass
        self.state = ClientState()
        self.wallet_session = None
        self._image_cache = None
        self._sold_asset_ids = set()
        self._removed_asset_ids = set()
        self._unlisted_asset_ids = set()
        self._balance_text = None
        self._notification_badge = None

    def get_market_asset_ids(self) -> list[dict]:
        resp = self.client.get_assets_ids()
        entries = [
            entry if isinstance(entry, dict) else {"id": str(entry), "version": 1}
            for entry in resp.get("ids", [])
        ]
        # Evict cached FOR_SALE assets that are no longer in the server's marketplace list
        server_ids = {e["id"] for e in entries if isinstance(e, dict)}
        cache = self._image_cache
        if cache:
            for aid, meta in list(cache._metadata.items()):
                if aid == "balance":
                    continue
                if isinstance(meta, dict) and meta.get("asset_status") == "FOR_SALE" and aid not in server_ids:
                    cache.invalidate(aid)
        return entries

    def load_asset_by_id(self, asset_id: str, version: int = 1) -> "MarketItem | None":
        try:
            cached = self.image_cache.get_if_current(asset_id, version)
            if cached is not None:
                entry, _ = cached
                return MarketItem(
                    asset_id=asset_id,
                    owner=str(entry.get("owner", "")),
                    title=str(entry.get("asset_name", "")),
                    description=str(entry.get("description", "")),
                    file_type=str(entry.get("file_type", "png")),
                    price=float(entry.get("cost", 0.0)),
                    created_at=str(entry.get("created_at", "")),
                    public_key_hex=str(entry.get("public_key", "")),
                    asset_status=str(entry.get("asset_status", "PENDING")),
                    version=int(entry.get("version", 1)),
                )
            init_meta, raw = self.client.download_asset(asset_id)
            file_type = str(init_meta.get("file_type", "png"))
            server_version = int(init_meta.get("version", version))
            meta_to_store = {
                "asset_id": asset_id,
                "version": server_version,
                "owner": str(init_meta.get("owner", "")),
                "asset_name": str(init_meta.get("asset_name", "")),
                "description": str(init_meta.get("description", "")),
                "file_type": file_type,
                "cost": float(init_meta.get("cost", 0.0)),
                "created_at": str(init_meta.get("created_at", "")),
                "public_key": str(init_meta.get("public_key", "")),
                "asset_status": str(init_meta.get("asset_status", "PENDING")),
            }
            self.image_cache.store(asset_id, file_type, server_version, meta_to_store, raw)
            return MarketItem(
                asset_id=asset_id,
                owner=meta_to_store["owner"],
                title=meta_to_store["asset_name"],
                description=meta_to_store["description"],
                file_type=file_type,
                price=meta_to_store["cost"],
                created_at=meta_to_store["created_at"],
                public_key_hex=meta_to_store["public_key"],
                asset_status=meta_to_store["asset_status"],
                version=server_version,
            )
        except Exception as exc:
            logger.warning(f"Failed to load asset {asset_id}: {exc}")
            return None

    def get_my_asset_ids(self) -> list[dict]:
        if not self.state.username:
            raise RuntimeError("Not authenticated")
        resp = self.client.get_assets_ids(self.state.username)
        return [
            entry if isinstance(entry, dict) else {"id": str(entry), "version": 1}
            for entry in resp.get("ids", [])
        ]

    def move_to_marketplace(self, asset_id: str) -> dict:
        if not self.state.username:
            raise RuntimeError("Not authenticated")
        return self.client.move_to_marketplace(self.state.username, asset_id)

    def delete_asset(self, asset_id: str):
        if not self.state.username:
            raise RuntimeError("Not authenticated")
        resp = self.client.delete_asset(asset_id, self.state.username)
        # Invalidate local cache on success
        self.image_cache.invalidate(asset_id)
        return resp

    def unlist_asset(self, asset_id: str):
        if not self.state.username:
            raise RuntimeError("Not authenticated")
        public_key = self.state.wallet_public_key or ""
        signature = ""
        if self.wallet_session:
            try:
                payload = {"asset_id": asset_id, "owner": self.state.username}
                signature = self.sign_payload(payload)
            except Exception:
                pass
        return self.client.unlist_asset(self.state.username, asset_id, public_key, signature)

    def request_balance(self):
        if not self.state.wallet_public_key:
            return
        try:
            self.client.request_balance(self.state.wallet_public_key)
        except Exception as exc:
            logger.warning(f"GET_BALANCE request failed: {exc}")

    def upload_asset(self, file_path, asset_name, description, file_type, cost, for_sale=True):
        if not self.state.username:
            raise RuntimeError("Not authenticated")
        if not self.wallet_session:
            raise RuntimeError("Wallet not loaded")
        file_bytes = Path(file_path).read_bytes()
        file_hash = hashlib.sha256(file_bytes).hexdigest()
        tx_payload = {
            "username": self.state.username,
            "asset_name": asset_name,
            "description": description,
            "file_type": file_type,
            "cost": float(cost),
            "file_hash": file_hash,
            "timestamp": time.time(),
        }
        signature = self.sign_payload(tx_payload)
        resp = self.client.upload_file(
            self.state.username,
            file_path,
            asset_name,
            description,
            file_type,
            cost,
            signature=signature,
            public_key=self.wallet_session.public_key,
            signed_payload=tx_payload,
            for_sale=for_sale,
        )
        asset_id = str(resp.get("asset_id", ""))
        if asset_id:
            try:
                meta_to_store = {
                    "asset_id": asset_id,
                    "version": 1,
                    "owner": self.state.username,
                    "asset_name": asset_name,
                    "description": description,
                    "file_type": file_type,
                    "cost": float(cost),
                    "asset_status": "PENDING",
                    "public_key": self.wallet_session.public_key,
                }
                self.image_cache.store(asset_id, file_type, 1, meta_to_store, file_bytes)
            except Exception:
                pass
        self.state.notifications.append(f"Uploaded asset: {asset_name}")
        if for_sale and asset_id:
            try:
                self.client.move_to_marketplace(self.state.username, asset_id)
                self.state.notifications.append("Asset sent to mining — will appear on marketplace once confirmed")
            except Exception as exc:
                logger.warning(f"[upload] move_to_marketplace failed: {exc}")
                self.state.notifications.append("Upload complete — go to My Assets to list it on the marketplace")
        return resp

    def buy_asset(self, item: MarketItem):
        if not self.state.username:
            raise RuntimeError("Not authenticated")
        if not self.wallet_session:
            raise RuntimeError("Wallet not loaded")
        payload = {
            "asset_id": item.asset_id,
            "buyer": self.state.username,
            "price": float(item.price),
            "timestamp": time.time(),
        }
        signature = self.sign_payload(payload)
        req = {
            "asset_id": item.asset_id,
            "buyer": self.state.username,
            "price": float(item.price),
            "timestamp": payload["timestamp"],
            "signature": signature,
            "public_key": self.wallet_session.public_key,
            "signed_payload": payload,
        }
        return self.client.buy_asset(req)

    def update_public_key(self, public_key):
        if not self.state.username:
            raise RuntimeError("Not authenticated")
        resp = self.client.update_public_key(self.state.username, public_key)
        # After registering key, request fresh balance
        threading.Thread(target=self.request_balance, daemon=True).start()
        return resp

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
            self.state.wallet_status_message = f"Wallet loaded from {self.wallet_manager.wallet_path_for_user(self.state.username).resolve()}"
        return wallet

    def load_wallet_from_file(self, file_path: str):
        wallet = self.wallet_manager.load_wallet_from_path(Path(file_path))
        self._set_wallet_session(wallet)
        self.wallet_manager.save_wallet(wallet, self.wallet_manager.wallet_path_for_user(self.state.username or wallet.username))
        self.state.wallet_status_message = f"Wallet loaded from {Path(file_path).resolve()}"
        return wallet

    def generate_new_wallet(self):
        if not self.state.username:
            raise RuntimeError("Not authenticated")
        wallet = self.wallet_manager.generate_wallet(self.state.username)
        self._set_wallet_session(wallet)
        self.state.wallet_status_message = f"Wallet loaded from {self.wallet_manager.wallet_path_for_user(self.state.username).resolve()}"
        self.state.notifications.append("Generated new wallet. Previous assets remain tied to old public key.")
        return wallet

    def load_default_wallet(self):
        wallet = self._load_wallet_session_from_default()
        if not wallet:
            raise RuntimeError("No local wallet found for this user")
        self.state.wallet_status_message = f"Wallet loaded from {self.wallet_manager.wallet_path_for_user(self.state.username).resolve()}"
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


def _setup_window(page) -> None:
    try:
        _cwd = Path.cwd()
        _frozen = getattr(sys, "frozen", False)
        logger.info(f"[icon] CWD={_cwd}")
        logger.info(f"[icon] packaged/frozen={_frozen}")
        logger.info(f"[icon] ICON_PATH={ICON_PATH}  exists={ICON_PATH.exists()}")
        logger.info(f"[icon] _ICON_FALLBACK={_ICON_FALLBACK}  exists={_ICON_FALLBACK.exists()}")
        _icon = ICON_PATH if ICON_PATH.exists() else (_ICON_FALLBACK if _ICON_FALLBACK.exists() else None)
        logger.info(f"[icon] selected icon={_icon!r}")
        if _icon is not None:
            icon_str = str(_icon)
            page.window.icon = icon_str
            logger.info(f"[icon] page.window.icon assigned: {icon_str!r}")
        else:
            logger.warning("[icon] no .ico file found — window icon will not be set")
        page.window.min_width = 1000
        page.window.min_height = 680
        page.window.update()
        logger.info("[icon] page.window.update() called")
    except Exception as _exc:
        logger.error(f"[icon] setup failed: {_exc}", exc_info=True)


def main(page):
    """Desktop entrypoint."""
    _setup_window(page)
    app = ClientApp(page)
    app._start_balance_monitor()
    app._start_notification_monitor()
    app._start_bought_asset_downloader()
    app.start()


if __name__ == "__main__":
    import argparse as _argparse
    _parser = _argparse.ArgumentParser(add_help=False)
    _parser.add_argument("--debug-level", "--DEBUG_LEVEL", default="DEBUG",
                         choices=["DEBUG", "INFO", "WARNING", "ERROR"])
    _args, _ = _parser.parse_known_args()
    Logger.set_level(_args.debug_level)
    ft.app(target=main, view=ft.AppView.FLET_APP, assets_dir=str(ASSETS_DIR))
