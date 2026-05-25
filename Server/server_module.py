"""Compact sync server module using dict-based Communication protocol.

No asyncio, websockets, TLS/SSL/certs.
"""

from __future__ import annotations

import base64
import hashlib
import json
import os
import random
import re
import sys
import threading
from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta
from pathlib import Path

# Adds the root folder to enable imports from SharedResources
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

try:
    from Server.DB_ORM import ORM, send_reset_email
except Exception:
    from DB_ORM import ORM, send_reset_email
from SharedResources.config import SERVER_IP, SERVER_PORT, INITIAL_BALANCE
from SharedResources.classes import RSA_Server
from SharedResources.logging import Logger

logger = Logger(__file__)


@dataclass
class MarketplaceItem:
    """Marketplace asset model stored in marketplace_items.json."""

    asset_id: str
    owner: str
    asset_name: str
    description: str
    file_type: str
    cost: float
    content_b64: str
    storage_path: str
    created_at: str

    def to_dict(self):
        return asdict(self)

    @classmethod
    def from_dict(cls, raw):
        return cls(
            asset_id=str(raw.get("asset_id", "")),
            owner=str(raw.get("owner", "")),
            asset_name=str(raw.get("asset_name", "")),
            description=str(raw.get("description", "")),
            file_type=str(raw.get("file_type", "")),
            cost=float(raw.get("cost", 0.0)),
            content_b64=str(raw.get("content_b64", "")),
            storage_path=str(raw.get("storage_path", "")),
            created_at=str(raw.get("created_at", "")),
        )

    def __repr__(self):
        return (
            "MarketplaceItem("  # explicit for JSON import/debug
            f"asset_id='{self.asset_id}', "
            f"owner='{self.owner}', "
            f"asset_name='{self.asset_name}', "
            f"file_type='{self.file_type}', "
            f"cost={self.cost}, "
            f"storage_path='{self.storage_path}', "
            f"created_at='{self.created_at}'"
            ")"
        )


@dataclass
class UploadSession:
    """In-memory upload session between UPLOAD_INIT and UPLOAD_FINISH."""

    upload_id: str
    username: str
    asset_name: str
    description: str
    file_type: str
    cost: float
    chunks_b64: list[str]
    created_at: str
    public_key: str = ""
    signature: str = ""
    signed_payload: dict = field(default_factory=dict)


class ORMExtended(ORM):
    """ORM facade for users + marketplace JSON database."""

    def __init__(self, users_json_path=None, marketplace_json_path=None):
        super().__init__(users_json_path)
        self.marketplace_json_path = (
            Path(marketplace_json_path)
            if marketplace_json_path
            else (Path(__file__).resolve().parent.parent / "DB" / "marketplace_items.json")
        )
        self.marketplace_pickle_path = Path(__file__).resolve().parent.parent / "DB" / "marketplace.pickle"
        self.marketplace_json_path.parent.mkdir(parents=True, exist_ok=True)
        if not self.marketplace_json_path.exists():
            self.marketplace_json_path.write_text("{}", encoding="utf-8")
        self._lock = threading.RLock()
        self._migrate_marketplace_pickle_once()

    def _migrate_marketplace_pickle_once(self):
        try:
            existing = json.loads(self.marketplace_json_path.read_text(encoding="utf-8"))
            if isinstance(existing, dict) and existing:
                return
        except Exception:
            pass
        if not self.marketplace_pickle_path.exists():
            return
        try:
            import pickle

            with self.marketplace_pickle_path.open("rb") as f:
                old_market = pickle.load(f)
            payload = {}
            if isinstance(old_market, dict):
                for owner, items in old_market.items():
                    out_items = []
                    if isinstance(items, list):
                        for raw in items:
                            if isinstance(raw, MarketplaceItem):
                                out_items.append(raw.to_dict())
                            elif isinstance(raw, dict):
                                out_items.append(MarketplaceItem.from_dict(raw).to_dict())
                            else:
                                out_items.append(MarketplaceItem.from_dict(getattr(raw, "__dict__", {})).to_dict())
                    payload[str(owner)] = out_items
            tmp_path = self.marketplace_json_path.with_suffix(".json.tmp")
            tmp_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
            tmp_path.replace(self.marketplace_json_path)
            logger.info(f"Migrated marketplace.pickle -> marketplace_items.json ({len(payload)} owners)")
        except Exception as exc:
            logger.error(f"Failed marketplace pickle migration: {exc}")

    def _load_marketplace(self):
        try:
            raw = json.loads(self.marketplace_json_path.read_text(encoding="utf-8"))
            if not isinstance(raw, dict):
                return {}
            normalized = {}
            for owner, items in raw.items():
                if not isinstance(items, list):
                    continue
                normalized[str(owner)] = [MarketplaceItem.from_dict(item).to_dict() for item in items if isinstance(item, dict)]
            return normalized
        except Exception:
            return {}

    def _save_marketplace(self, market):
        self.marketplace_json_path.write_text(json.dumps(market, ensure_ascii=False, indent=2), encoding="utf-8")

    def save_user(self, user):
        with self._lock:
            users = self._load_users()
            users[user.username] = user
            self._save_users(users)

    def get_user_by_email(self, email):
        email = (email or "").strip().lower()
        if not email:
            return None
        users = self._load_users()
        for user in users.values():
            if getattr(user, "email", "").lower() == email:
                return user
        return None

    def set_user_public_key(self, username, public_key):
        user = self.get_user(username)
        if not user:
            return False
        user.set_public_key(public_key)
        self.save_user(user)
        return True

    def issue_reset_code(self, email, minutes_valid=5):
        user = self.get_user_by_email(email)
        if not user:
            return False, "Email not found", None
        code = str(random.randint(100000, 999999))
        user.set_verification_code(code)
        user.set_reset_time((datetime.now() + timedelta(minutes=minutes_valid)).isoformat())
        self.save_user(user)
        return True, "Code issued", code

    def verify_reset_code(self, email, code):
        user = self.get_user_by_email(email)
        if not user:
            return False, "Email not found", None
        if user.is_code_match_and_available(datetime.now(), code):
            return True, "Code verified", user
        return False, "Invalid or expired code", None

    def update_password_by_email(self, email, new_password):
        user = self.get_user_by_email(email)
        if not user:
            return False, "Email not found"
        user.set_password(new_password)
        self.save_user(user)
        return True, "Password updated"

    def add_asset(self, username, asset):
        with self._lock:
            market = self._load_marketplace()
            market.setdefault(username, [])
            market[username].append(asset.to_dict() if isinstance(asset, MarketplaceItem) else MarketplaceItem.from_dict(asset).to_dict())
            self._save_marketplace(market)
        return True

    def get_all_assets(self):
        market = self._load_marketplace()
        assets = []
        for owner_assets in market.values():
            for asset in owner_assets:
                assets.append(MarketplaceItem.from_dict(asset))
        assets.sort(key=lambda a: a.created_at, reverse=True)
        return assets

    def get_assets_for_user(self, username):
        username = (username or "").strip()
        if not username:
            return []
        market = self._load_marketplace()
        raw_list = market.get(username, [])
        assets = [MarketplaceItem.from_dict(a) for a in raw_list if isinstance(a, dict)]
        assets.sort(key=lambda a: a.created_at, reverse=True)
        return assets

    def get_all_assets_excluding_user(self, username: str):
        username = (username or "").strip()
        market = self._load_marketplace()
        assets = []
        for owner, owner_assets in market.items():
            if owner == username:
                continue
            for asset in owner_assets:
                if isinstance(asset, dict):
                    assets.append(MarketplaceItem.from_dict(asset))
        assets.sort(key=lambda a: a.created_at, reverse=True)
        return assets

    def find_asset_by_id(self, asset_id: str):
        asset_id = (asset_id or "").strip()
        if not asset_id:
            return None
        market = self._load_marketplace()
        for owner_assets in market.values():
            for asset_dict in owner_assets:
                if isinstance(asset_dict, dict):
                    item = MarketplaceItem.from_dict(asset_dict)
                    if item.asset_id == asset_id:
                        return item
        return None


class ServerUpdated:
    """Sync marketplace server using RSA_Server + Communication dict frames."""

    def __init__(self, host=SERVER_IP, port=SERVER_PORT):
        self.host = host
        self.port = int(port)
        self.db = ORMExtended()
        self.upload_sessions = {}
        self.upload_lock = threading.RLock()
        self.gateway_clients = set()
        self.gateway_lock = threading.RLock()
        self.online_users: dict[str, object] = {}
        self.online_users_lock = threading.RLock()
        self.notifications_path = Path(__file__).resolve().parent.parent / "DB" / "notifications.json"
        self.notifications_lock = threading.RLock()
        self.notifications_path.parent.mkdir(parents=True, exist_ok=True)
        if not self.notifications_path.exists():
            self.notifications_path.write_text("{}", encoding="utf-8")
        self.client_listener = RSA_Server(self.host, self.port, dir_for_keys="ServerKeys", name="ServerUpdated")
        self.logger = logger
        self.client_listener.handle_client = self.handle_client
        self.handlers = {
            "START": self.handle_start,
            "LOGIN": self.handle_login,
            "SIGNUP": self.handle_signup,
            "SEND_CODE": self.handle_send_code,
            "SENDCODE": self.handle_send_code,
            "VERIFY_CODE": self.handle_verify_code,
            "VERFYCODE": self.handle_verify_code,
            "UPDATE_PASSWORD": self.handle_update_password,
            "LOGOUT": self.handle_logout,
            "UPLOAD": self.handle_upload,
            "UPLOAD_INIT": self.handle_upload_init,
            "UPLOAD_FINISH": self.handle_upload_finish,
            "GET_ITEMS": self.handle_get_items,
            "GET_MY_ASSETS": self.handle_get_my_assets,
            "UPDATE_PUBLIC_KEY": self.handle_update_public_key,
            "REGISTER_GATEWAY": self.handle_register_gateway,
            "BUY_ASSET": self.handle_buy_asset,
            "BUY_SUCCESS": self.handle_buy_success,
            "BUY_FAILED": self.handle_buy_failed,
            "SELL_SUCCESS": self.handle_sell_success,
            "BLOCK_REJECTED": self.handle_block_rejected,
            "SEND_BALANCE": self.handle_send_balance,
        }

    def start(self):
        self.client_listener.start()

    def handle_client(self, comm):
        self.logger.info("Client connected")
        comm.start_async(default_encryption=True)
        while True:
            msg = comm.recv_async(timeout=0.25)
            if msg is None:
                continue
            if comm.is_close_marker(msg):
                self.logger.info("Client disconnected")
                with self.gateway_lock:
                    self.gateway_clients.discard(comm)
                user_obj = getattr(comm, "user", None)
                username = getattr(user_obj, "username", "") if user_obj else ""
                if username:
                    with self.online_users_lock:
                        if self.online_users.get(username) == comm:
                            self.online_users.pop(username, None)
                break
            try:
                response = self.dispatch(comm, msg)
            except Exception as e:
                self.logger.error(f"Unhandled server error: {e}")
                response = {"type": "ERROR", "message": str(e)}
            if response is not None:
                comm.send_async(response)

    def dispatch(self, comm, msg):
        if not isinstance(msg, dict):
            return {"type": "ERROR", "message": "Invalid message format"}
        action = str(msg.get("type", "")).strip().upper()
        handler = self.handlers.get(action)
        if not handler:
            return {"type": "ERROR", "message": f"Unknown operation: {action}"}
        return handler(comm, msg)

    def _param(self, msg, key, index, default=""):
        _ = index
        if key in msg:
            return msg.get(key)
        return default

    def _success(self, event_type, **extra):
        payload = {"type": event_type}
        payload.update(extra)
        return payload

    def _fail(self, event_type, message):
        return {"type": event_type, "message": str(message)}

    def _load_notifications(self):
        try:
            data = json.loads(self.notifications_path.read_text(encoding="utf-8"))
            return data if isinstance(data, dict) else {}
        except Exception:
            return {}

    def _save_notifications(self, data):
        self.notifications_path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")

    def _queue_notification(self, username: str, msg: str):
        username = str(username or "").strip()
        if not username:
            return
        with self.notifications_lock:
            data = self._load_notifications()
            items = data.get(username, [])
            if not isinstance(items, list):
                items = []
            items.append({"msg": str(msg)})
            data[username] = items
            self._save_notifications(data)

    def _flush_notifications_for_user(self, username: str, comm):
        username = str(username or "").strip()
        if not username:
            return
        with self.notifications_lock:
            data = self._load_notifications()
            items = data.get(username, [])
            data[username] = []
            self._save_notifications(data)
        if not isinstance(items, list):
            return
        for item in items:
            msg = str(item.get("msg", "")) if isinstance(item, dict) else str(item)
            if not msg:
                continue
            try:
                comm.send_async({"type": "NOTIFICATION", "msg": msg})
            except Exception:
                self._queue_notification(username, msg)
                return

    def _push_event(self, username: str, event: dict):
        """Push a typed protocol event to an online user; queue as notification if offline."""
        username = str(username or "").strip()
        if not username or not event:
            return
        with self.online_users_lock:
            online_comm = self.online_users.get(username)
        if online_comm is None:
            msg_text = event.get("msg") or "; ".join(f"{k}={v}" for k, v in event.items() if k != "type")
            self._queue_notification(username, msg_text)
            return
        try:
            online_comm.send_async(event)
        except Exception:
            with self.online_users_lock:
                if self.online_users.get(username) == online_comm:
                    self.online_users.pop(username, None)
            msg_text = event.get("msg") or "; ".join(f"{k}={v}" for k, v in event.items() if k != "type")
            self._queue_notification(username, msg_text)

    def _notify_gateways(self, payload):
        with self.gateway_lock:
            targets = list(self.gateway_clients)
        for gw_comm in targets:
            try:
                gw_comm.send_async(payload)
            except Exception:
                with self.gateway_lock:
                    self.gateway_clients.discard(gw_comm)

    def handle_start(self, comm, msg):
        _ = comm
        _ = msg
        return self._success("READY")

    def handle_login(self, comm, msg):
        username = str(self._param(msg, "username", 0, "")).strip()
        password = str(self._param(msg, "password", 1, ""))
        if not username or not password:
            return self._fail("LOGIN_FAILED", "Missing username/password")
        user = self.db.get_user(username)
        if not user or not user.verify_password(password):
            return self._fail("LOGIN_FAILED", "Invalid username or password")
        if hasattr(comm, "set_user"):
            comm.set_user(user)
        else:
            comm.user = user
        with self.online_users_lock:
            self.online_users[username] = comm
        self._flush_notifications_for_user(username, comm)
        return self._success("LOGIN_SUCCESS", username=username)

    def handle_signup(self, comm, msg):
        _ = comm
        username = str(self._param(msg, "username", 0, "")).strip()
        password = str(self._param(msg, "password", 1, "")).strip()
        email = str(self._param(msg, "email", 2, "")).strip().lower()
        if not username or not password or not email:
            return self._fail("SIGNUP_FAILED", "Missing required fields")
        if not re.match(r"^[a-zA-Z0-9_]{3,20}$", username):
            return self._fail("SIGNUP_FAILED", "Username must be 3-20 alnum/underscore")
        if len(password) < 6:
            return self._fail("SIGNUP_FAILED", "Password must be at least 6 characters")
        if "@" not in email or " " in email:
            return self._fail("SIGNUP_FAILED", "Invalid email format")
        ok, message = self.db.add_user(username, password, email)
        if not ok:
            return self._fail("SIGNUP_FAILED", message)
        return self._success("SIGNUP_SUCCESS", username=username)

    def handle_send_code(self, comm, msg):
        _ = comm
        email = str(self._param(msg, "email", 0, "")).strip().lower()
        if not email:
            return self._fail("CODE_FAILED", "Missing email")
        ok, message, code = self.db.issue_reset_code(email)
        if not ok:
            return self._fail("CODE_FAILED", message)
        threading.Thread(target=send_reset_email, args=(email, code), daemon=True).start()
        return self._success("CODE_SENT")

    def handle_verify_code(self, comm, msg):
        _ = comm
        email = str(self._param(msg, "email", 0, "")).strip().lower()
        code = str(self._param(msg, "code", 1, "")).strip()
        if not email or not code:
            return self._fail("CODE_FAILED", "Missing email/code")
        ok, message, user = self.db.verify_reset_code(email, code)
        if not ok:
            return self._fail("CODE_FAILED", message)
        return self._success("CODE_VERIFIED", username=user.username)

    def handle_update_password(self, comm, msg):
        _ = comm
        email = str(self._param(msg, "email", 0, "")).strip().lower()
        new_password = str(self._param(msg, "new_password", 1, self._param(msg, "password", 1, ""))).strip()
        if not email or not new_password:
            return self._fail("UPDATE_FAILED", "Missing email/new_password")
        if len(new_password) < 6:
            return self._fail("UPDATE_FAILED", "Password must be at least 6 characters")
        ok, message = self.db.update_password_by_email(email, new_password)
        if not ok:
            return self._fail("UPDATE_FAILED", message)
        return self._success("PASSWORD_UPDATED")

    def handle_logout(self, comm, msg):
        _ = msg
        user_obj = getattr(comm, "user", None)
        username = getattr(user_obj, "username", "") if user_obj else ""
        if username:
            with self.online_users_lock:
                if self.online_users.get(username) == comm:
                    self.online_users.pop(username, None)
        if hasattr(comm, "set_user"):
            comm.set_user(None)
        else:
            comm.user = None
        return self._success("LOGOUT_SUCCESS")

    def handle_upload_init(self, comm, msg):
        _ = comm
        upload_id = str(self._param(msg, "upload_id", 0, "")).strip()
        username = str(self._param(msg, "username", 1, "")).strip()
        asset_name = str(self._param(msg, "asset_name", 2, "")).strip()
        description = str(self._param(msg, "description", 3, "")).strip()
        file_type = str(self._param(msg, "file_type", 4, "")).strip().lower()
        cost_raw = self._param(msg, "cost", 5, 0)
        try:
            cost = float(cost_raw)
        except Exception:
            cost = -1
        public_key = str(self._param(msg, "public_key", 6, "")).strip()
        signature = str(self._param(msg, "signature", 7, "")).strip()
        signed_payload = self._param(msg, "signed_payload", 8, {})
        if not isinstance(signed_payload, dict):
            signed_payload = {}
        if not upload_id:
            return self._fail("UPLOAD_FAILED", "Missing upload_id")
        if not username or not asset_name or file_type not in {"jpg", "jpeg", "png"} or cost < 0:
            return self._fail("UPLOAD_FAILED", "Invalid upload_init fields")
        if file_type == "jpeg":
            file_type = "jpg"
        session = UploadSession(
            upload_id=upload_id,
            username=username,
            asset_name=asset_name,
            description=description,
            file_type=file_type,
            cost=cost,
            chunks_b64=[],
            created_at=datetime.now().isoformat(),
            public_key=public_key,
            signature=signature,
            signed_payload=signed_payload,
        )
        with self.upload_lock:
            self.upload_sessions[upload_id] = session
        return self._success("UPLOAD_READY")

    def handle_upload(self, comm, msg):
        _ = comm
        upload_id = str(self._param(msg, "upload_id", 0, "")).strip()
        chunk_b64 = str(self._param(msg, "chunk_b64", 1, self._param(msg, "chunk", 1, ""))).strip()
        if not upload_id or not chunk_b64:
            return self._fail("UPLOAD_FAILED", "Missing upload_id/chunk_b64")
        with self.upload_lock:
            session = self.upload_sessions.get(upload_id)
            if not session:
                return self._fail("UPLOAD_FAILED", "Upload session not found")
            session.chunks_b64.append(chunk_b64)
        return self._success("CHUNK_RECEIVED")

    def handle_upload_finish(self, comm, msg):
        _ = comm
        upload_id = str(self._param(msg, "upload_id", 0, "")).strip()
        if not upload_id:
            return self._fail("UPLOAD_FAILED", "Missing upload_id")
        with self.upload_lock:
            session = self.upload_sessions.pop(upload_id, None)
        if not session:
            return self._fail("UPLOAD_FAILED", "Upload session not found")
        content_b64 = "".join(session.chunks_b64)
        try:
            raw = base64.b64decode(content_b64.encode("utf-8"), validate=True)
        except Exception:
            return self._fail("UPLOAD_FAILED", "Invalid upload payload")
        asset_hash = hashlib.sha256(raw).hexdigest()
        uploads_dir = Path(__file__).resolve().parent.parent / "DB" / "uploads" / session.username
        uploads_dir.mkdir(parents=True, exist_ok=True)
        file_path = uploads_dir / f"{asset_hash}.{session.file_type}"
        try:
            file_path.write_bytes(raw)
        except Exception as exc:
            return self._fail("UPLOAD_FAILED", f"Failed writing upload file: {exc}")
        item = MarketplaceItem(
            asset_id=asset_hash[:16],
            owner=session.username,
            asset_name=session.asset_name,
            description=session.description,
            file_type=session.file_type,
            cost=session.cost,
            content_b64="",          # file is on disk at storage_path; don't bloat the DB
            storage_path=str(file_path),
            created_at=datetime.now().isoformat(),
        )
        self.db.add_asset(session.username, item)
        self._notify_gateways({
            "type": "UPLOAD_ASSET",
            "data": {
                "asset_id": item.asset_id,
                "owner": session.username,
                "asset_name": session.asset_name,
                "description": session.description,
                "file_type": session.file_type,
                "cost": session.cost,
                "file_hash": asset_hash,
                "storage_path": str(file_path),
                "created_at": item.created_at,
                "public_key": session.public_key,
                "signature": session.signature,
                "signed_payload": session.signed_payload,
            },
        })
        return self._success("UPLOAD_SUCCESS", asset_id=item.asset_id)

    @staticmethod
    def _item_to_wire(item: MarketplaceItem) -> dict:
        """Strip content_b64 — it's large and clients don't need it; file is at storage_path."""
        d = item.to_dict()
        d.pop("content_b64", None)
        return d

    def handle_get_items(self, comm, msg):
        _ = comm
        _ = msg
        items = [self._item_to_wire(item) for item in self.db.get_all_assets()]
        return self._success("ITEMS_LIST", items=items)

    def handle_get_my_assets(self, comm, msg):
        _ = comm
        username = str(self._param(msg, "username", 0, "")).strip()
        if not username:
            return self._fail("FETCH_FAILED", "Missing username")
        items = [self._item_to_wire(item) for item in self.db.get_assets_for_user(username)]
        return self._success("MY_ASSETS_LIST", items=items)

    def handle_update_public_key(self, comm, msg):
        _ = comm
        username = str(self._param(msg, "username", 0, "")).strip()
        public_key = str(self._param(msg, "public_key", 1, "")).strip()
        if not username or not public_key:
            return self._fail("KEY_FAILED", "Missing username/public_key")
        ok = self.db.set_user_public_key(username, public_key)
        if not ok:
            return self._fail("KEY_FAILED", "User not found")
        self._notify_gateways(
            {
                "type": "CREATE_BALANCE",
                "data": {
                    "username": username,
                    "public_key": public_key,
                    "balance": float(INITIAL_BALANCE),
                },
            }
        )
        return self._success("KEY_UPDATED")

    def handle_register_gateway(self, comm, msg):
        _ = msg
        with self.gateway_lock:
            self.gateway_clients.add(comm)
        return self._success("GATEWAY_REGISTERED")

    def handle_buy_asset(self, comm, msg):
        _ = comm
        data = msg.get("data") if isinstance(msg.get("data"), dict) else {}
        buyer = str(data.get("buyer", "")).strip()
        public_key = str(data.get("public_key", "")).strip()
        signature = str(data.get("signature", "")).strip()
        if not buyer or not public_key or not signature:
            return self._fail("BUY_FAILED", "Missing buyer/public_key/signature")
        self._notify_gateways({"type": "tx_request_buy", "data": data})
        return self._success("BUY_SUBMITTED")

    def handle_buy_success(self, comm, msg):
        _ = comm
        data = msg.get("data") if isinstance(msg.get("data"), dict) else {}
        buyer = str(data.get("buyer") or data.get("sender") or "").strip()
        seller = str(data.get("seller") or data.get("receiver") or "").strip()
        asset_id = str(data.get("asset_id") or "").strip()
        price = data.get("price") if data.get("price") is not None else data.get("amount")
        if buyer:
            self._push_event(buyer, {
                "type": "BUY_SUCCESS",
                "asset_id": asset_id,
                "price": price,
            })
        if seller:
            self._push_event(seller, {
                "type": "BUY_SUCCESS",
                "asset_id": asset_id,
                "price": price,
            })
        return self._success("BUY_ACKNOWLEDGED")

    def handle_buy_failed(self, comm, msg):
        _ = comm
        data = msg.get("data") if isinstance(msg.get("data"), dict) else {}
        buyer = str(data.get("buyer") or data.get("sender") or "").strip()
        asset_id = str(data.get("asset_id") or "").strip()
        message = str(data.get("message") or data.get("reason") or "Transaction rejected").strip()
        if buyer:
            self._push_event(buyer, {
                "type": "BUY_FAILED",
                "asset_id": asset_id,
                "message": message,
            })
        return self._success("BUY_FAILED_ACKNOWLEDGED")

    def handle_sell_success(self, comm, msg):
        _ = comm
        data = msg.get("data") if isinstance(msg.get("data"), dict) else {}
        seller = str(data.get("seller") or data.get("sender") or "").strip()
        asset_id = str(data.get("asset_id") or "").strip()
        if seller:
            self._push_event(seller, {
                "type": "BLOCK_ACCEPTED",
                "asset_id": asset_id,
            })
        return self._success("SELL_ACKNOWLEDGED")

    def handle_block_rejected(self, comm, msg):
        _ = comm
        data = msg.get("data") if isinstance(msg.get("data"), dict) else {}
        username = str(data.get("username") or data.get("sender") or "").strip()
        asset_id = str(data.get("asset_id") or "").strip()
        message = str(data.get("message") or data.get("reason") or "Block rejected").strip()
        if username:
            self._push_event(username, {
                "type": "BLOCK_REJECTED",
                "asset_id": asset_id,
                "message": message,
            })
        return self._success("BLOCK_REJECTED_ACKNOWLEDGED")

    def handle_send_balance(self, comm, msg):
        _ = comm
        data = msg.get("data") if isinstance(msg.get("data"), dict) else {}
        userpk = str(msg.get("userpk") or data.get("userpk") or "").strip()
        balance = data.get("balance")
        if userpk:
            self.logger.info(f"Balance update from blockchain userpk={userpk} balance={balance}")
        return self._success("BALANCE_ACKNOWLEDGED")


if __name__ == "__main__":
    server = ServerUpdated()
    print(f"[*] Starting ServerUpdated on {SERVER_IP}:{SERVER_PORT}...")
    server.start()
