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
import uuid
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta
from pathlib import Path

# Adds the root folder to enable imports from SharedResources
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

try:
    from Server.DB_ORM import ORM, send_reset_email
except Exception:
    from DB_ORM import ORM, send_reset_email
from SharedResources.config import SERVER_IP, SERVER_PORT
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
            "UPDATE_PUBLIC_KEY": self.handle_update_public_key,
            "REGISTER_GATEWAY": self.handle_register_gateway,
            "CREATE_WALLET": self.handle_create_wallet,
            "BUY_ASSET": self.handle_buy_asset,
        }

    def start(self):
        self.client_listener.start()

    def handle_client(self, comm):
        self.logger.info("Client connected")
        while True:
            msg = comm.recv_one_message()
            if not msg:
                self.logger.info("Client disconnected")
                with self.gateway_lock:
                    self.gateway_clients.discard(comm)
                break
            try:
                response = self.dispatch(comm, msg)
            except Exception as e:
                self.logger.error(f"Unhandled server error: {e}")
                response = {"type": "ERROR", "message": str(e)}
            comm.send_one_message(response)

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

    def _ok(self, **extra):
        payload = {"type": "OK"}
        payload.update(extra)
        return payload

    def _error(self, e):
        return {"type": "ERROR", "message": str(e)}

    def _notify_gateways(self, payload):
        with self.gateway_lock:
            targets = list(self.gateway_clients)
        for gw_comm in targets:
            try:
                gw_comm.send_one_message(payload)
            except Exception:
                with self.gateway_lock:
                    self.gateway_clients.discard(gw_comm)

    def handle_start(self, comm, msg):
        _ = comm
        _ = msg
        return self._ok()

    def handle_login(self, comm, msg):
        username, password = str(self._param(msg, "username", 0, "")).strip(), str(self._param(msg, "password", 1, ""))
        if not username or not password:
            return self._error("Missing username/password")
        user = self.db.get_user(username)
        if not user or not user.verify_password(password):
            return self._error("Invalid username or password")
        if hasattr(comm, "set_user"):
            comm.set_user(user)
        else:
            comm.user = user
        return self._ok(username=username)

    def handle_signup(self, comm, msg):
        _ = comm
        username, password, email = (
            str(self._param(msg, "username", 0, "")).strip(),
            str(self._param(msg, "password", 1, "")).strip(),
            str(self._param(msg, "email", 2, "")).strip().lower(),
        )
        if not username or not password or not email:
            return self._error("Missing required fields")
        if not re.match(r"^[a-zA-Z0-9_]{3,20}$", username):
            return self._error("Username must be 3-20 alnum/underscore")
        if len(password) < 6:
            return self._error("Password must be at least 6 characters")
        if "@" not in email or " " in email:
            return self._error("Invalid email format")
        ok, message = self.db.add_user(username, password, email)
        if not ok:
            return self._error(message)
        return self._ok(username=username)

    def handle_send_code(self, comm, msg):
        _ = comm
        email = str(self._param(msg, "email", 0, "")).strip().lower()
        if not email:
            return self._error("Missing email")
        ok, message, code = self.db.issue_reset_code(email)
        if not ok:
            return self._error(message)
        threading.Thread(target=send_reset_email, args=(email, code), daemon=True).start()
        return self._ok()

    def handle_verify_code(self, comm, msg):
        _ = comm
        email, code = str(self._param(msg, "email", 0, "")).strip().lower(), str(self._param(msg, "code", 1, "")).strip()
        if not email or not code:
            return self._error("Missing email/code")
        ok, message, user = self.db.verify_reset_code(email, code)
        if not ok:
            return self._error(message)
        return self._ok(username=user.username)

    def handle_update_password(self, comm, msg):
        _ = comm
        email, new_password = (
            str(self._param(msg, "email", 0, "")).strip().lower(),
            str(self._param(msg, "new_password", 1, self._param(msg, "password", 1, ""))).strip(),
        )
        if not email or not new_password:
            return self._error("Missing email/new_password")
        if len(new_password) < 6:
            return self._error("Password must be at least 6 characters")
        ok, message = self.db.update_password_by_email(email, new_password)
        if not ok:
            return self._error(message)
        return self._ok()

    def handle_logout(self, comm, msg):
        _ = msg
        if hasattr(comm, "set_user"):
            comm.set_user(None)
        else:
            comm.user = None
        return self._ok()

    def handle_upload_init(self, comm, msg):
        _ = comm
        username = str(self._param(msg, "username", 0, "")).strip()
        asset_name = str(self._param(msg, "asset_name", 1, "")).strip()
        description = str(self._param(msg, "description", 2, "")).strip()
        file_type = str(self._param(msg, "file_type", 3, "")).strip().lower()
        cost_raw = self._param(msg, "cost", 4, 0)
        try:
            cost = float(cost_raw)
        except Exception:
            cost = -1
        if not username or not asset_name or file_type not in {"jpg", "jpeg", "png"} or cost < 0:
            return self._error("Invalid upload_init fields")
        if file_type == "jpeg":
            file_type = "jpg"
        upload_id = uuid.uuid4().hex
        session = UploadSession(
            upload_id=upload_id,
            username=username,
            asset_name=asset_name,
            description=description,
            file_type=file_type,
            cost=cost,
            chunks_b64=[],
            created_at=datetime.now().isoformat(),
        )
        with self.upload_lock:
            self.upload_sessions[upload_id] = session
        return self._ok(upload_id=upload_id)

    def handle_upload(self, comm, msg):
        _ = comm
        upload_id = str(self._param(msg, "upload_id", 0, "")).strip()
        chunk_b64 = str(self._param(msg, "chunk_b64", 1, self._param(msg, "chunk", 1, ""))).strip()
        if not upload_id or not chunk_b64:
            return self._error("Missing upload_id/chunk_b64")
        with self.upload_lock:
            session = self.upload_sessions.get(upload_id)
            if not session:
                return self._error("Upload session not found")
            session.chunks_b64.append(chunk_b64)
        return self._ok()

    def handle_upload_finish(self, comm, msg):
        _ = comm
        upload_id = str(self._param(msg, "upload_id", 0, "")).strip()
        if not upload_id:
            return self._error("Missing upload_id")
        with self.upload_lock:
            session = self.upload_sessions.pop(upload_id, None)
        if not session:
            return self._error("Upload session not found")
        content_b64 = "".join(session.chunks_b64)
        try:
            raw = base64.b64decode(content_b64.encode("utf-8"), validate=True)
        except Exception:
            return self._error("Invalid upload payload")
        asset_hash = hashlib.sha256(raw).hexdigest()
        item = MarketplaceItem(
            asset_id=asset_hash[:16],
            owner=session.username,
            asset_name=session.asset_name,
            description=session.description,
            file_type=session.file_type,
            cost=session.cost,
            content_b64=content_b64,
            created_at=datetime.now().isoformat(),
        )
        self.db.add_asset(session.username, item)
        return self._ok(asset_id=item.asset_id)

    def handle_get_items(self, comm, msg):
        _ = comm
        _ = msg
        items = [item.to_dict() for item in self.db.get_all_assets()]
        return self._ok(items=items)

    def handle_update_public_key(self, comm, msg):
        _ = comm
        username = str(self._param(msg, "username", 0, "")).strip()
        public_key = str(self._param(msg, "public_key", 1, "")).strip()
        if not username or not public_key:
            return self._error("Missing username/public_key")
        ok = self.db.set_user_public_key(username, public_key)
        if not ok:
            return self._error("User not found")
        self._notify_gateways({"type": "CREATE_WALLET", "data": {"username": username, "public_key": public_key}})
        return self._ok()

    def handle_register_gateway(self, comm, msg):
        _ = msg
        with self.gateway_lock:
            self.gateway_clients.add(comm)
        return self._ok()

    def handle_create_wallet(self, comm, msg):
        _ = comm
        username = str(self._param(msg, "username", 0, "")).strip()
        public_key = str(self._param(msg, "public_key", 1, "")).strip()
        if not username or not public_key:
            return self._error("Missing username/public_key")
        self._notify_gateways({"type": "CREATE_WALLET", "data": {"username": username, "public_key": public_key}})
        return self._ok()

    def handle_buy_asset(self, comm, msg):
        _ = comm
        data = msg.get("data") if isinstance(msg.get("data"), dict) else {}
        buyer = str(data.get("buyer", "")).strip()
        public_key = str(data.get("public_key", "")).strip()
        signature = str(data.get("signature", "")).strip()
        if not buyer or not public_key or not signature:
            return self._error("Missing buyer/public_key/signature")
        self._notify_gateways({"type": "tx_request_buy", "data": data})
        return self._ok(status="submitted")


if __name__ == "__main__":
    server = ServerUpdated()
    print(f"[*] Starting ServerUpdated on {SERVER_IP}:{SERVER_PORT}...")
    server.start()
