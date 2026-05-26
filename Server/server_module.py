"""Compact sync server module using dict-based Communication protocol.

No asyncio, websockets, TLS/SSL/certs.
"""

from __future__ import annotations

import argparse
import base64
import hashlib
import json
import os
import random
import re
import shutil
import sys
import threading
from dataclasses import asdict, dataclass
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
        if user.verification_code != code:
            return False, "Invalid verification code", None
        if not user.reset_time or datetime.now() >= datetime.fromisoformat(user.reset_time):
            return False, "Code expired", None
        return True, "Code verified", user

    def update_password_by_email(self, email, new_password):
        user = self.get_user_by_email(email)
        if not user:
            return False, "Email not found"
        old_hash = user.password_hash
        user.set_password(new_password)
        self.save_user(user)
        logger.info(f"[update_password] hash changed for {email}: {old_hash[:12]}... -> {user.password_hash[:12]}...")
        return True, "Password updated"


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
        self.client_listener = RSA_Server(self.host, self.port, dir_for_keys="ServerKeys", name="ServerUpdated", peer_label="Client")
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
            "BUY_ASSET": self.handle_buy_asset,
            "BUY_SUCCESS": self.handle_buy_success,
            "BUY_FAILED": self.handle_buy_failed,
            "SELL_SUCCESS": self.handle_sell_success,
            "BLOCK_REJECTED": self.handle_block_rejected,
            "SEND_BALANCE": self.handle_send_balance,
            "GET_ASSETS_IDS": self.handle_get_assets_ids,
            "GET_ASSET_BY_ID": self.handle_get_asset_by_id,
            "DELETE_ACCOUNT": self.handle_delete_account,
            "GET_BALANCE": self.handle_get_balance,
            "FULLY_UPLOAD": self.handle_fully_upload,
            "ASSET_UNLISTED": self.handle_asset_unlisted,
            "MOVE_TO_MARKETPLACE": self.handle_move_to_marketplace,
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

    def _fail(self, *args):
        message = args[-1]
        return {"type": "ERROR", "message": str(message)}

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
        if not user:
            self.logger.warning(f"[login] username '{username}' not found in DB")
            return self._fail("LOGIN_FAILED", f"Username '{username}' not found")
        if not user.verify_password(password):
            self.logger.warning(f"[login] wrong password attempt for '{username}'")
            return self._fail("LOGIN_FAILED", f"Incorrect password for '{username}'")
        if hasattr(comm, "set_user"):
            comm.set_user(user)
        else:
            comm.user = user
        with self.online_users_lock:
            self.online_users[username] = comm
        self._flush_notifications_for_user(username, comm)
        # Proactively push fresh balance from blockchain on every login
        if user.public_key:
            self._notify_gateways({"type": "GET_BALANCE", "userpk": user.public_key})
        return self._success("LOGIN_SUCCESS", username=username)

    def handle_signup(self, comm, msg):
        _ = comm
        username = str(self._param(msg, "username", 0, "")).strip()
        password = str(self._param(msg, "password", 1, ""))
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
        new_password = str(self._param(msg, "new_password", 1, self._param(msg, "password", 1, "")))
        code = str(self._param(msg, "code", 2, "")).strip()
        if not email or not new_password or not code:
            return self._fail("UPDATE_FAILED", "Missing email/code/new_password")
        if len(new_password) < 6:
            return self._fail("UPDATE_FAILED", "Password must be at least 6 characters")
        ok, message, _ = self.db.verify_reset_code(email, code)
        if not ok:
            self.logger.warning(f"[update_password] code check failed for {email}: {message}")
            if "expired" in message.lower():
                return self._fail("UPDATE_FAILED", "Code expired — press 'Send Code' to get a new one")
            return self._fail("UPDATE_FAILED", "Invalid verification code")
        update_ok, update_msg = self.db.update_password_by_email(email, new_password)
        if not update_ok:
            self.logger.error(f"[update_password] DB update failed for {email}: {update_msg}")
            return self._fail("UPDATE_FAILED", update_msg)
        self.logger.info(f"[update_password] password updated successfully for {email}")
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
            content_b64=content_b64,
            storage_path=str(file_path),
            created_at=datetime.now().isoformat(),
        )
        self.db.add_asset(session.username, item)
        return self._success("UPLOAD_SUCCESS", asset_id=item.asset_id)

    def handle_get_items(self, comm, msg):
        _ = comm
        _ = msg
        items = [item.to_dict() for item in self.db.get_all_assets()]
        return self._success("ITEMS_LIST", items=items)

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
        comm.peer_label = "Gateway"
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
        self._notify_gateways({"type": "TX_REQUEST_BUY", "data": data})
        return self._success("BUY_SUBMITTED")

    def handle_buy_success(self, comm, msg):
        _ = comm
        data = msg.get("data") if isinstance(msg.get("data"), dict) else {}

        # sender = buyer PK (paid), receiver = seller PK (received AUR)
        buyer_pk = str(data.get("sender") or data.get("public_key") or "").strip()
        seller_pk = str(data.get("receiver") or "").strip()
        buyer_username = str(data.get("buyer_username") or data.get("buyer") or "").strip()
        asset_id = str(data.get("asset_id") or "").strip()
        price = data.get("price") if data.get("price") is not None else data.get("amount")

        # Resolve usernames from public keys for DB operations
        buyer_user = self.db.get_user_by_public_key(buyer_pk) if buyer_pk else None
        seller_user = self.db.get_user_by_public_key(seller_pk) if seller_pk else None
        buyer_name = (buyer_user.username if buyer_user else None) or buyer_username
        seller_name = seller_user.username if seller_user else ""

        if asset_id and seller_name and buyer_name:
            ok = self.db.transfer_asset(asset_id, seller_name, buyer_name)
            if ok:
                self.logger.info(f"[buy_success] asset {asset_id} transferred {seller_name} -> {buyer_name}")
            else:
                self.logger.warning(f"[buy_success] transfer_asset failed for {asset_id} ({seller_name} -> {buyer_name})")

        # Push BUY_SUCCESS to buyer
        if buyer_name:
            self._push_event(buyer_name, {
                "type": "BUY_SUCCESS",
                "asset_id": asset_id,
                "price": price,
                "msg": f"Purchase confirmed — asset {asset_id} at {price} AUR is now yours!",
            })

        # Push ASSET_SOLD to seller with asset name for a readable notification
        if seller_name:
            asset = self.db.find_asset_by_id(asset_id)
            asset_label = asset.asset_name if asset else asset_id
            self._push_event(seller_name, {
                "type": "ASSET_SOLD",
                "asset_id": asset_id,
                "buyer": buyer_name,
                "price": price,
                "msg": f"Your asset '{asset_label}' was sold to {buyer_name} for {price} AUR",
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
            balance_val = float(balance) if balance is not None else 0.0
            self.logger.info(f"Balance update from blockchain userpk={userpk} balance={balance_val}")
            user = self.db.get_user_by_public_key(userpk)
            if user:
                self._push_event(user.username, {
                    "type": "BALANCE_IS",
                    "balance": balance_val,
                    "msg": f"Your new balance is {balance_val:.2f} AUR",
                })
        return self._success("BALANCE_ACKNOWLEDGED")


    def handle_get_balance(self, comm, msg):
        public_key = str(self._param(msg, "user_public_key", 0, "")).strip()
        if not public_key:
            return self._fail("BALANCE_FAILED", "Missing user_public_key")
        self._notify_gateways({"type": "GET_BALANCE", "userpk": public_key})
        return self._success("BALANCE_REQUESTED")

    def handle_move_to_marketplace(self, comm, msg):
        """Client requests asset be listed on marketplace via blockchain mining."""
        _ = comm
        username = str(self._param(msg, "username", 0, "")).strip()
        asset_id = str(self._param(msg, "asset_id", 1, "")).strip()
        if not username or not asset_id:
            return self._fail("MOVE_FAILED", "Missing username/asset_id")
        asset = self.db.find_asset_by_id(asset_id)
        if not asset:
            return self._fail("MOVE_FAILED", f"Asset {asset_id} not found")
        if asset.owner != username:
            return self._fail("MOVE_FAILED", "Asset does not belong to this user")
        user = self.db.get_user(username)
        public_key = getattr(user, "public_key", "") if user else ""
        file_hash = ""
        try:
            storage_path = Path(asset.storage_path)
            if storage_path.exists():
                file_hash = hashlib.sha256(storage_path.read_bytes()).hexdigest()
        except Exception:
            pass
        self._notify_gateways({
            "type": "UPLOAD_ASSET",
            "data": {
                "asset_id": asset_id,
                "owner": username,
                "public_key": public_key,
                "file_hash": file_hash,
            },
        })
        self.logger.info(f"[move_to_marketplace] asset {asset_id} sent to gateway for mining (owner={username})")
        return self._success("MOVE_PENDING")

    def handle_fully_upload(self, comm, msg):
        """Gateway confirms asset block was mined — mark asset FOR_SALE."""
        _ = comm
        asset_id = str(self._param(msg, "asset_id", 0, "")).strip()
        block_hash = str(self._param(msg, "block_hash", 1, "")).strip()
        if not asset_id:
            return self._fail("FULLY_UPLOAD_FAILED", "Missing asset_id")
        ok = self.db.update_asset_status(asset_id, "FOR_SALE")
        if ok:
            self.logger.info(f"[fully_upload] asset {asset_id} is now FOR_SALE hash={block_hash[:16] if block_hash else '?'}...")
            asset = self.db.find_asset_by_id(asset_id)
            if asset and asset.owner:
                self._push_event(asset.owner, {"type": "FULLY_UPLOADED", "asset_id": asset_id})
                # Refresh balance for owner after blockchain state changes
                user = self.db.get_user(asset.owner)
                owner_pk = getattr(user, "public_key", "") if user else ""
                if owner_pk:
                    self._notify_gateways({"type": "GET_BALANCE", "userpk": owner_pk})
        else:
            self.logger.warning(f"[fully_upload] update_asset_status failed for {asset_id}")
        return self._success("FULLY_UPLOAD_ACKNOWLEDGED")

    def handle_asset_unlisted(self, comm, msg):
        """Gateway confirms unlist block was mined — mark asset UNLISTED."""
        _ = comm
        asset_id = str(self._param(msg, "asset_id", 0, "")).strip()
        block_hash = str(self._param(msg, "block_hash", 1, "")).strip()
        if not asset_id:
            return self._fail("ASSET_UNLISTED_FAILED", "Missing asset_id")
        ok = self.db.update_asset_status(asset_id, "UNLISTED", increment_version=True)
        if ok:
            self.logger.info(f"[asset_unlisted] asset {asset_id} is now UNLISTED hash={block_hash[:16] if block_hash else '?'}...")
            asset = self.db.find_asset_by_id(asset_id)
            if asset and asset.owner:
                self._push_event(asset.owner, {"type": "ASSET_UNLISTED", "asset_id": asset_id})
        else:
            self.logger.warning(f"[asset_unlisted] update_asset_status failed for {asset_id}")
        return self._success("UNLIST_ACKNOWLEDGED")

    def handle_get_assets_ids(self, comm, msg):
        _ = comm
        username = str(msg.get("username") or "").strip()
        if username:
            items = self.db.get_assets_for_user(username)   # owned, NOT for sale
        else:
            items = self.db.get_all_for_sale_assets()        # marketplace: only FOR_SALE
        ids = [{"id": item.asset_id, "version": getattr(item, "version", 1)} for item in items if item.asset_id]
        return self._success("ASSETS_IDS_LIST", ids=ids)

    def handle_get_asset_by_id(self, comm, msg):
        asset_id = str(self._param(msg, "id", 0, "")).strip()
        if not asset_id:
            comm.send_async({"type": "ERROR", "message": "Missing asset id"})
            return None

        item = None
        for a in self.db.get_all_assets():
            if a.asset_id == asset_id:
                item = a
                break

        if not item:
            comm.send_async({"type": "ERROR", "message": "Asset not found"})
            return None

        content_b64 = getattr(item, "content_b64", "") or ""
        if not content_b64:
            try:
                raw = Path(item.storage_path).read_bytes()
                content_b64 = base64.b64encode(raw).decode("ascii")
            except Exception:
                comm.send_async({"type": "ERROR", "message": "Asset file not found"})
                return None

        chunk_size = 32_000
        chunks = [content_b64[i: i + chunk_size] for i in range(0, len(content_b64), chunk_size)] or [""]

        comm.send_async({
            "type": "ASSET_INIT",
            "total_chunks": len(chunks),
            "file_type": item.file_type,
            "version": getattr(item, "version", 1),
            "owner": item.owner,
            "asset_name": item.asset_name,
            "description": item.description,
            "cost": item.cost,
            "created_at": item.created_at,
            "public_key": getattr(item, "public_key", ""),
            "asset_status": getattr(item, "asset_status", "PENDING"),
        })
        for chunk in chunks:
            comm.send_async({"type": "ASSET_CHUNK", "chunk_b64": chunk})
        comm.send_async({"type": "ASSET_END"})
        return None

    def handle_delete_account(self, comm, msg):
        username = str(self._param(msg, "username", 0, "")).strip()
        if not username:
            return self._fail("DELETE_FAILED", "Missing username")

        self.db.delete_user(username)
        self.db.delete_user_assets(username)

        with self.notifications_lock:
            data = self._load_notifications()
            data.pop(username, None)
            self._save_notifications(data)

        uploads_dir = Path(__file__).resolve().parent.parent / "DB" / "uploads" / username
        if uploads_dir.exists():
            shutil.rmtree(uploads_dir, ignore_errors=True)

        with self.online_users_lock:
            self.online_users.pop(username, None)

        self.logger.info(f"Account deleted: {username}")
        return self._success("ACCOUNT_IS_DELETED")


if __name__ == "__main__":
    _parser = argparse.ArgumentParser(description="Aurex marketplace server")
    _parser.add_argument(
        "--debug-level", "--DEBUG_LEVEL",
        default="DEBUG",
        choices=["DEBUG", "INFO", "WARNING", "ERROR"],
    )
    _args = _parser.parse_args()
    from SharedResources.logging import Logger as _Logger
    _Logger.set_level(_args.debug_level)

    server = ServerUpdated()
    print(f"[*] Starting ServerUpdated on {SERVER_IP}:{SERVER_PORT}...")
    server.start()
