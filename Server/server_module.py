"""
server_module.py — the Aurex marketplace server.
"""
from __future__ import annotations # for the hints of parameters 

__author__ = "Nadav"

import argparse
import base64
import hashlib
import json
import os
import re
import shutil
import sys
import threading
import uuid
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

# Adds the root folder to enable imports from SharedResources
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

try:
    from Server.DB_ORM import ORM, send_reset_email
except Exception:
    from DB_ORM import ORM, send_reset_email

from SharedResources.config import SERVER_IP, SERVER_PORT, INITIAL_BALANCE
from SharedResources.classes import (
    RSA_Server, MarketplaceItem,
    ASSET_STATUS_UPLOADED, ASSET_STATUS_MINTED, ASSET_STATUS_LISTED,
    ASSET_STATUS_UNLISTED,
)
from SharedResources.logging import Logger
from SharedResources.exceptions import (
    AurexError,
    ValidationError,
    AuthError,
    NotFoundError,
    DuplicateError,
    GatewayError,
    TransferError,
    BlockchainError,
    UploadError,
    SessionError,
)

logger = Logger(__file__)


class _ProtocolError(Exception):
    """Internal exception used by _require() to abort a handler early."""
    def __init__(self, fail_type: str, message: str):
        super().__init__(message)
        self.fail_type = fail_type
        self.message = message


# Keys are stored in Server/ServerKeys/ — always relative to this file.
_SERVER_KEYS_DIR = str(Path(__file__).resolve().parent / "ServerKeys")

_MAX_UPLOAD_BYTES = 5 * 1024 * 1024  # 5 MB hard limit

try:
    from PIL import Image as _PILImage
    import io as _io
    _PIL_AVAILABLE = True
except ImportError:
    _PILImage = None
    _io = None
    _PIL_AVAILABLE = False
    logger.warning("[security] Pillow not installed — image sanitization disabled. pip install Pillow")


def sanitize_and_save_image(file_bytes: bytes, output_path: str, file_format: str) -> bool:
    """
    Sanitize an uploaded image by re-rendering it from raw pixel data only.

    Args:
        file_bytes:  Raw (decoded) image bytes received from the upload.
        output_path: Absolute path where the sanitized file will be written.
        file_format: Claimed format string ('jpg', 'jpeg', or 'png').

    Returns:
        True  — sanitization and save succeeded.
        False — file is structurally invalid or appears malicious.
    """
    pil_fmt = "JPEG" if file_format.lower() in ("jpg", "jpeg") else "PNG"

    if not _PIL_AVAILABLE:
        # Fallback: magic-bytes only
        sigs = {"jpg": b"\xFF\xD8\xFF", "jpeg": b"\xFF\xD8\xFF", "png": b"\x89PNG\r\n\x1a\n"}
        if not file_bytes[:8].startswith(sigs.get(file_format.lower(), b"")):
            logger.warning("[security] magic-byte check failed (Pillow unavailable)")
            return False
        try:
            Path(output_path).write_bytes(file_bytes)
            return True
        except Exception as exc:
            logger.error(f"[security] write failed: {exc}")
            return False

    try:
        buf = _io.BytesIO(file_bytes)

        # Structural integrity check (closes internal stream — re-open afterwards)
        probe = _PILImage.open(buf)
        probe.verify()

        # Re-open after verify()
        buf.seek(0)
        raw_img = _PILImage.open(buf)

        # JPEG does not support alpha or palette modes — normalise to RGB
        if pil_fmt == "JPEG" and raw_img.mode not in ("RGB", "L"):
            raw_img = raw_img.convert("RGB")

        # Build a new image from pixels ONLY — strips every byte of metadata
        clean = _PILImage.new(raw_img.mode, raw_img.size)
        clean.putdata(list(raw_img.getdata()))

        clean.save(output_path, format=pil_fmt)
        logger.info(f"[security] Image sanitized and saved to {output_path}")
        return True

    except Exception as exc:
        logger.warning(f"[SECURITY ALERT] Image sanitization failed — possible exploit attempt: {exc}")
        return False


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
    for_sale: bool = False


class Server:
    """Main marketplace server.

    Accepts client and gateway TCP connections, authenticates users, manages
    asset uploads / purchases, and relays blockchain operations to the gateway.
    All communication uses the RSA_Server handshake + AES-CBC message framing
    defined in SharedResources/classes.py.
    """

    def __init__(self, host=SERVER_IP, port=SERVER_PORT):
        self.host = host
        self.port = int(port)
        self.db = ORM()
        self.upload_sessions = {}
        self.upload_lock = threading.Lock()
        self.gateway_comm = None          # single gateway connection
        self.gateway_lock = threading.RLock()
        self.online_users: dict[str, object] = {}
        self.online_users_lock = threading.RLock()
        self._active_buys: dict[str, str] = {}       # asset_id -> buyer; one BUY in flight per asset
        self._active_buys_lock = threading.Lock()
        self.client_listener = RSA_Server(
            self.host, self.port,
            dir_for_keys=_SERVER_KEYS_DIR,
            name="Server",
            peer_label="Client",
        )
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
            "DELETE_ASSET": self.handle_delete_asset,
            "GET_BALANCE": self.handle_get_balance,
            "FULLY_UPLOAD": self.handle_fully_upload,
            "ASSET_UNLISTED": self.handle_asset_unlisted,
            "MOVE_TO_MARKETPLACE": self.handle_move_to_marketplace,
            "UNLIST_ASSET": self.handle_unlist_asset,
            "CLEAR_NOTIFICATIONS": self.handle_clear_notifications,
        }

    def start(self):
        """Start the RSA server — blocks until the server stops."""
        self.client_listener.start()


    def handle_client(self, comm):
        """
        Entry point for every new TCP connection (client or gateway).

        Starts async message reading, then loops dispatching messages to
        ``dispatch()`` until the connection closes.  Cleans up online-user
        and gateway-comm state on disconnect.

        Args:
            comm: Communication object for the connected peer.
        """
        self.logger.info("Client connected")
        comm.start_async(default_encryption=True)
        while True:
            msg = comm.recv_async(timeout=0.25)
            if msg is None:
                continue
            if comm.is_close_marker(msg):
                self.logger.info("Client disconnected")
                with self.gateway_lock:
                    if self.gateway_comm is comm:
                        self.gateway_comm = None
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
        """
        Route an incoming message dict to the correct handler.

        Looks up ``msg["type"]`` in ``self.handlers`` and calls the matching
        method.  Returns an error dict for unknown or malformed messages.

        Args:
            comm: The sender's communication object.
            msg:  Decoded message dictionary.

        Returns:
            A response dict to send back, or None if the handler already
            sent its own response (e.g. chunked asset download).
        """
        if not isinstance(msg, dict):
            return {"type": "ERROR", "message": "Invalid message format"}
        action = str(msg.get("type", "")).strip().upper()
        handler = self.handlers.get(action)
        if not handler:
            return {"type": "ERROR", "message": f"Unknown operation: {action}"}
        return handler(comm, msg)

    # ── Helpers ───────────────────────────────────────────────────────────────

    def _param(self, msg, key, index, default=""):
        _ = index
        return msg.get(key, default)

    def _success(self, event_type, **extra):
        payload = {"type": event_type}
        payload.update(extra)
        return payload

    def _fail(self, *args):
        message = args[-1]
        return {"type": "ERROR", "message": str(message)}

    def _gateway_required(self):
        """
        Guard helper — returns an error response dict when the gateway is
        offline, or None when it is connected.

        Use this at the top of any handler that must forward work to the
        blockchain network.  The returned dict can be returned directly from
        the handler so the client sees a clear "Gateway Server isn't online."
        error message.

        Returns:
            None if the gateway is connected and ready.
            dict {"type": "ERROR", "message": "Gateway Server isn't online."} otherwise.
        """
        with self.gateway_lock:
            if self.gateway_comm is None:
                return self._fail("GATEWAY_OFFLINE", "Gateway Server isn't online.")
        return None

    def _notify_gateway(self, payload):
        """
        Forward a message dict to the single connected gateway.

        Thread-safe.  Clears ``self.gateway_comm`` if the send fails so
        subsequent ``_gateway_required()`` calls correctly report offline.

        Args:
            payload: Message dict to forward (will be encrypted in transit).

        Returns:
            True if the message was sent successfully, False otherwise.
        """
        with self.gateway_lock:
            comm = self.gateway_comm
        if comm is None:
            return False
        try:
            comm.send_async(payload)
            return True
        except Exception as exc:
            self.logger.warning(f"Gateway send failed: {exc}")
            with self.gateway_lock:
                if self.gateway_comm is comm:
                    self.gateway_comm = None
            return False


    def _flush_notifications_for_user(self, username: str, comm):
        msgs = self.db.peek_notifications(username)
        for msg in msgs:
            if not msg:
                continue
            try:
                comm.send_async({"type": "NOTIFICATION", "msg": msg})
            except Exception:
                return

    def _push_to_all_online(self, event: dict):

        with self.online_users_lock:
            targets = list(self.online_users.items())
        for _username, comm in targets:
            try:
                comm.send_async(event)
            except Exception:
                pass

    def _push_event(self, username: str, event: dict, persist: bool = False):
        """
        Send a typed protocol event to a specific user.

        If persist=True the message is always written to notifications.json so it
        survives the session and appears in the user's notification history even if
        they were online and received the live push.  Use this for blockchain errors
        (BUY_FAILED, BLOCK_REJECTED) that the user must be able to review later.
        """
        username = str(username or "").strip()
        if not username or not event:
            return
        msg_text = event.get("msg") or "; ".join(f"{k}={v}" for k, v in event.items() if k != "type")
        if persist:
            self.db.queue_notification(username, msg_text)
        with self.online_users_lock:
            online_comm = self.online_users.get(username)
        if online_comm is None:
            if not persist:
                self.db.queue_notification(username, msg_text)
            return
        try:
            online_comm.send_async(event)
        except Exception:
            with self.online_users_lock:
                if self.online_users.get(username) == online_comm:
                    self.online_users.pop(username, None)
            if not persist:
                self.db.queue_notification(username, msg_text)


    # ── Fail-fast helpers ─────────────────────────────────────────────────────

    def _require(self, condition: bool, fail_type: str, message: str):
        """Raise a ProtocolError if condition is False (fail-fast guard)."""
        if not condition:
            raise _ProtocolError(fail_type, message)

    def _resolve_buyer(self, data: dict) -> str:
        """Return buyer username from data, resolving by public_key if needed."""
        buyer = str(data.get("buyer") or data.get("buyer_username") or data.get("sender") or "").strip()
        if not buyer:
            pk = str(data.get("user_public_key") or data.get("public_key") or "").strip()
            if pk:
                user = self.db.get_user_by_public_key(pk)
                if user:
                    buyer = user.username
        return buyer

    def _parse_buy_parties(self, data: dict):
        """Extract and resolve all parties involved in a BUY transaction."""
        buyer_pk = str(data.get("user_public_key") or data.get("sender") or data.get("public_key") or "").strip()
        seller_pk = str(data.get("seller_public_key") or data.get("receiver") or "").strip()
        buyer_username = str(data.get("buyer_username") or data.get("buyer") or "").strip()
        asset_id = str(data.get("asset_id") or "").strip()
        price = data.get("price") if data.get("price") is not None else data.get("amount")
        buyer_user = self.db.get_user_by_public_key(buyer_pk) if buyer_pk else None
        seller_user = self.db.get_user_by_public_key(seller_pk) if seller_pk else None
        buyer_name = (buyer_user.username if buyer_user else None) or buyer_username
        seller_name = seller_user.username if seller_user else ""
        return buyer_name, seller_name, asset_id, price

    def _push_buy_notifications(self, buyer_name: str, seller_name: str, asset_id: str, price):
        """Push BUY_SUCCESS to buyer and ASSET_SOLD to seller after a successful transfer."""
        asset = self.db.find_asset_by_id(asset_id)
        asset_label = asset.asset_name if asset else asset_id
        if buyer_name:
            self._push_event(buyer_name, {
                "type": "BUY_SUCCESS",
                "asset_id": asset_id,
                "price": price,
                "msg": f"Purchase confirmed — '{asset_label}' at {price} AUR is now yours!",
            })
        if seller_name:
            self._push_event(seller_name, {
                "type": "ASSET_SOLD",
                "asset_id": asset_id,
                "buyer": buyer_name,
                "price": price,
                "msg": f"Your asset '{asset_label}' was sold to {buyer_name} for {price:.2f} AUR",
            }, persist=True)

    # ── Fail-fast micro-helpers ───────────────────────────────────────────────

    def _require_fields(self, *values, fail_type="VALIDATION_ERROR", msg="Missing required fields"):
        _ = fail_type
        if not all(values):
            raise ValidationError(msg)

    def _find_user(self, username: str):
        user = self.db.get_user(username)
        if not user:
            raise NotFoundError(f"User '{username}' not found")
        return user

    def _find_active_user(self, username: str):
        user = self._find_user(username)
        if user.is_deleted():
            raise AuthError(f"Account '{username}' has been deleted")
        return user

    def _find_asset(self, asset_id: str) -> MarketplaceItem:
        asset = self.db.find_asset_by_id(asset_id)
        if not asset:
            raise NotFoundError(f"Asset '{asset_id}' not found")
        return asset

    def _require_asset_owner(self, asset: MarketplaceItem, username: str):
        if asset.owner != username:
            raise AuthError(f"Asset '{asset.asset_id}' does not belong to '{username}'")

    def _require_asset_key(self, asset: MarketplaceItem, public_key: str):
        """Reject blockchain-signed operations when the current wallet key doesn't
        match the key that originally uploaded/minted the asset."""
        asset_pk = getattr(asset, "public_key", "") or ""
        if asset_pk and public_key and asset_pk != public_key:
            raise AuthError(
                f"Asset '{asset.asset_id}' was minted with a different wallet key — "
                "generate a new asset or restore your original wallet to manage this one"
            )

    def _require_gateway(self):
        with self.gateway_lock:
            if self.gateway_comm is None:
                raise GatewayError("Gateway Server isn't online.")

    def _get_session(self, upload_id: str) -> UploadSession:
        with self.upload_lock:
            session = self.upload_sessions.pop(upload_id, None)
        if not session:
            raise SessionError(f"Upload session '{upload_id}' not found or expired")
        return session

    def _decode_upload(self, chunks_b64: list) -> bytes:
        try:
            return base64.b64decode("".join(chunks_b64).encode("utf-8"), validate=True)
        except Exception as e:
            raise UploadError(f"Invalid upload payload: {e}") from e

    def _enforce_size_limit(self, raw: bytes):
        if len(raw) > _MAX_UPLOAD_BYTES:
            raise UploadError(
                f"File exceeds 5 MB limit ({len(raw) / 1024 / 1024:.1f} MB received)"
            )

    def _sanitize_image(self, raw: bytes, file_path: Path, file_type: str):
        if not sanitize_and_save_image(raw, str(file_path), file_type):
            raise UploadError(
                "File is invalid or contains unsupported content — "
                "only clean PNG/JPEG images are accepted"
            )

    def _transfer_asset(self, asset_id: str, seller: str, buyer: str, buyer_public_key: str = ""):
        if not self.db.transfer_asset(asset_id, seller, buyer, buyer_public_key):
            raise TransferError(f"Asset '{asset_id}' was already purchased by someone else")

    def _set_comm_user(self, comm, user):
        if hasattr(comm, "set_user"):
            comm.set_user(user)
        else:
            comm.user = user
        with self.online_users_lock:
            self.online_users[user.username] = comm

    def _validate_signup_fields(self, username: str, password: str, email: str):
        self._require_fields(username, password, email, msg="Missing required fields")
        if not re.match(r"^[a-zA-Z0-9_]{3,20}$", username):
            raise ValidationError("Username must be 3-20 alphanumeric/underscore characters")
        if len(password) < 6:
            raise ValidationError("Password must be at least 6 characters")
        if "@" not in email or " " in email:
            raise ValidationError("Invalid email format")

    def _parse_cost(self, raw) -> float:
        try:
            cost = float(raw)
        except Exception:
            raise ValidationError("Invalid cost value")
        if cost < 0:
            raise ValidationError("Cost cannot be negative")
        return cost

    def _validate_upload_init(self, upload_id, username, asset_name, file_type, cost):
        _ = cost
        self._require_fields(upload_id, msg="Missing upload_id")
        self._require_fields(username, asset_name, msg="Missing username or asset_name")
        if file_type not in {"jpg", "jpeg", "png"}:
            raise ValidationError(f"Unsupported file type '{file_type}' — use jpg or png")

    def _build_upload_path(self, session: UploadSession, asset_hash: str) -> Path:
        uploads_dir = Path(__file__).resolve().parent.parent / "DB" / "uploads" / session.username
        uploads_dir.mkdir(parents=True, exist_ok=True)
        return uploads_dir / f"{asset_hash}.{session.file_type}"

    def _create_asset_item(self, session: UploadSession, asset_hash: str, file_path: Path) -> MarketplaceItem:
        user = self.db.get_user(session.username)
        public_key = getattr(user, "public_key", "") if user else ""
        return MarketplaceItem(
            asset_id=asset_hash[:16],
            owner=session.username,
            asset_name=session.asset_name,
            description=session.description,
            file_type=session.file_type,
            cost=session.cost,
            storage_path=str(file_path),
            created_at=datetime.now().isoformat(),
            public_key=public_key,
        )

    def _resolve_user_key(self, msg, username: str, param_index: int) -> str:
        key = str(self._param(msg, "public_key", param_index, "")).strip()
        if not key:
            user = self.db.get_user(username)
            key = getattr(user, "public_key", "") if user else ""
        return key

    def _compute_file_hash(self, asset: MarketplaceItem) -> str:
        try:
            path = Path(asset.storage_path)
            if path.exists():
                return hashlib.sha256(path.read_bytes()).hexdigest()
        except Exception:
            pass
        return ""

    def _mark_asset_for_sale(self, asset_id: str, asset: MarketplaceItem, block_hash: str):
        # Determine new status from current: UPLOADED→MINTED (first mint), UNLISTED→LISTED (re-list)
        new_status = ASSET_STATUS_MINTED if asset.asset_status == ASSET_STATUS_UPLOADED else ASSET_STATUS_LISTED
        if not self.db.update_asset_status(asset_id, new_status):
            raise BlockchainError(f"Failed to update asset {asset_id} to {new_status}")
        self.logger.info(
            f"[fully_upload] {asset_id} is now {new_status} hash={block_hash[:16] if block_hash else '?'}"
        )
        asset = self.db.find_asset_by_id(asset_id)
        if asset and asset.owner:
            self._push_event(asset.owner, {
                "type": "FULLY_UPLOADED", "asset_id": asset_id,
                "msg": f"'{asset.asset_name or asset_id}' is now live on the marketplace!",
            }, persist=True)
        # Tell all online clients a new asset appeared so their marketplace grids auto-refresh
        self._push_to_all_online({"type": "ASSET_LISTED", "asset_id": asset_id})

    def _verify_reset_code_or_raise(self, email: str, code: str):
        ok, message, _ = self.db.verify_reset_code(email, code)
        if not ok:
            if "expired" in message.lower():
                raise ValidationError("Code expired — press 'Send Code' to get a new one")
            raise ValidationError("Invalid verification code")

    # ── Handlers ──────────────────────────────────────────────────────────────

    def handle_start(self, comm, msg):
        _ = comm, msg
        return self._success("READY")

    def handle_login(self, comm, msg):
        try:
            username = str(self._param(msg, "username", 0, "")).strip()
            password = str(self._param(msg, "password", 1, ""))
            self._require_fields(username, password, msg="Missing username/password")
            user = self._find_active_user(username)
            if not user.verify_password(password):
                raise AuthError(f"Incorrect password for '{username}'")
            
            self._set_comm_user(comm, user)
            self._flush_notifications_for_user(username, comm)
            if user.public_key:
                self._notify_gateway({"type": "GET_BALANCE", "userpk": user.public_key})
            return self._success("LOGIN_SUCCESS", username=username)
        except AurexError as e:
            return self._fail("LOGIN_FAILED", str(e))

    def handle_signup(self, comm, msg):
        _ = comm
        try:
            username = str(self._param(msg, "username", 0, "")).strip()
            password = str(self._param(msg, "password", 1, ""))
            email = str(self._param(msg, "email", 2, "")).strip().lower()
            self._validate_signup_fields(username, password, email)
            ok, message = self.db.add_user(username, password, email)
            if not ok:
                raise DuplicateError(message)
            return self._success("SIGNUP_SUCCESS", username=username)
        except AurexError as e:
            return self._fail("SIGNUP_FAILED", str(e))

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
        try:
            email = str(self._param(msg, "email", 0, "")).strip().lower()
            new_password = str(self._param(msg, "new_password", 1, self._param(msg, "password", 1, "")))
            code = str(self._param(msg, "code", 2, "")).strip()
            self._require_fields(email, new_password, code, msg="Missing email/code/new_password")
            if len(new_password) < 6:
                raise ValidationError("Password must be at least 6 characters")
            self._verify_reset_code_or_raise(email, code)
            ok, update_msg = self.db.update_password_by_email(email, new_password)
            if not ok:
                raise ValidationError(update_msg)
            return self._success("PASSWORD_UPDATED")
        except AurexError as e:
            return self._fail("UPDATE_FAILED", str(e))

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
        try:
            upload_id = str(self._param(msg, "upload_id", 0, "")).strip()
            username = str(self._param(msg, "username", 1, "")).strip()
            asset_name = str(self._param(msg, "asset_name", 2, "")).strip()
            description = str(self._param(msg, "description", 3, "")).strip()
            file_type = str(self._param(msg, "file_type", 4, "")).strip().lower()
            cost = self._parse_cost(self._param(msg, "cost", 5, 0))
            for_sale = bool(msg.get("for_sale", False))
            self._validate_upload_init(upload_id, username, asset_name, file_type, cost)
            if file_type == "jpeg":
                file_type = "jpg"
            session = UploadSession(
                upload_id=upload_id, username=username, asset_name=asset_name,
                description=description, file_type=file_type, cost=cost,
                chunks_b64=[], created_at=datetime.now().isoformat(),
                for_sale=for_sale,
            )
            with self.upload_lock:
                self.upload_sessions[upload_id] = session
            return self._success("UPLOAD_READY")
        except AurexError as e:
            return self._fail("UPLOAD_FAILED", str(e))

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
        """
        Finalise an in-progress upload: decode chunks, enforce limits,
        sanitize the image via PIL, and register the asset in the ORM.

        """
        _ = comm
        try:
            upload_id = str(self._param(msg, "upload_id", 0, "")).strip()
            self._require_fields(upload_id, msg="Missing upload_id")
            session = self._get_session(upload_id)
            raw = self._decode_upload(session.chunks_b64)
            self._enforce_size_limit(raw)
            asset_hash = hashlib.sha256(raw).hexdigest()
            file_path = self._build_upload_path(session, asset_hash)
            self._sanitize_image(raw, file_path, session.file_type)
            item = self._create_asset_item(session, asset_hash, file_path)
            self.db.add_asset(session.username, item)
            if session.for_sale:
                notif_msg = f"'{session.asset_name}' uploaded — mining MINT block, will appear on marketplace once confirmed"
            else:
                notif_msg = f"Asset '{session.asset_name}' uploaded to My Assets"
            self._push_event(session.username, {
                "type": "NOTIFICATION",
                "msg": notif_msg,
            }, persist=True)
            return self._success("UPLOAD_SUCCESS", asset_id=item.asset_id)
        except AurexError as e:
            return self._fail("UPLOAD_FAILED", str(e))

    def handle_get_items(self, comm, msg):
        _ = comm, msg
        items = [item.to_dict() for item in self.db.get_all_assets()]
        return self._success("ITEMS_LIST", items=items)

    def handle_update_public_key(self, comm, msg):
        _ = comm
        username = str(self._param(msg, "username", 0, "")).strip()
        public_key = str(self._param(msg, "public_key", 1, "")).strip()
        if not username or not public_key:
            return self._fail("KEY_FAILED", "Missing username/public_key")
        if self.db.is_public_key_taken(public_key, exclude_username=username):
            return self._fail("KEY_FAILED", "Public key update failed: another user has this public key")
        ok = self.db.set_user_public_key(username, public_key)
        if not ok:
            return self._fail("KEY_FAILED", "User not found")
        err = self._gateway_required()
        if err:
            return self._success("KEY_UPDATED")  # key saved locally. balance will sync when gateway comes online
        self._notify_gateway({
            "type": "CREATE_BALANCE",
            "data": {
                "username": username,
                "public_key": public_key,
                "balance": float(INITIAL_BALANCE),
            },
        })
        return self._success("KEY_UPDATED")

    def handle_register_gateway(self, comm, msg):
        _ = msg
        comm.peer_label = "Gateway"
        with self.gateway_lock:
            self.gateway_comm = comm
        self.logger.info("Gateway registered")
        # Tell every logged-in client the gateway is now reachable so they can
        # hide the "gateway unavailable" banner without waiting for a page reload.
        self._push_to_all_online({"type": "GATEWAY_ONLINE"})
        return self._success("GATEWAY_REGISTERED")

    def handle_buy_asset(self, comm, msg):
        """Forward a signed buy request from the client to the gateway."""
        _ = comm
        asset_id = ""
        _claimed = False  # True only if THIS call successfully added to _active_buys
        try:
            data = msg.get("data") if isinstance(msg.get("data"), dict) else {}
            buyer = str(data.get("buyer", "")).strip()
            public_key = str(data.get("public_key", "")).strip()
            signature = str(data.get("signature", "")).strip()
            asset_id = str(data.get("asset_id", "")).strip()
            self._require_fields(buyer, public_key, signature, msg="Missing buyer/public_key/signature")
            self._require_gateway()
            # One BUY in flight per asset — prevents balance drain from double-click or concurrent buyers.
            # _claimed tracks whether WE set the entry so the except block doesn't accidentally
            # clear a lock that belongs to a different concurrent request.
            with self._active_buys_lock:
                existing = self._active_buys.get(asset_id)
                if existing is not None:
                    raise ValidationError(
                        "Your purchase is already being processed — please wait"
                        if existing == buyer else
                        "This asset is currently being purchased by another user"
                    )
                self._active_buys[asset_id] = buyer
                _claimed = True
            # Inject seller's public key so the node can credit them on the blockchain.
            if asset_id and "seller_public_key" not in data:
                asset = self.db.find_asset_by_id(asset_id)
                if asset and asset.owner:
                    seller_user = self.db.get_user(asset.owner)
                    if seller_user and getattr(seller_user, "public_key", ""):
                        data = dict(data)
                        data["seller_public_key"] = seller_user.public_key
            self._notify_gateway({"type": "TX_REQUEST_BUY", "data": data})
            return self._success("BUY_SUBMITTED")
        except AurexError as e:
            if _claimed:  # only release the lock if WE acquired it
                with self._active_buys_lock:
                    self._active_buys.pop(asset_id, None)
            return self._fail("BUY_FAILED", str(e))

    def handle_buy_success(self, comm, msg):
        """Process a confirmed purchase from the gateway/node."""
        _ = comm
        data = msg.get("data") if isinstance(msg.get("data"), dict) else {}
        buyer_name, seller_name, asset_id, price = self._parse_buy_parties(data)
        buyer_pk = str(data.get("user_public_key") or data.get("sender") or data.get("public_key") or "").strip()
        # Seller not resolved via PK (e.g. old client) — look it up from DB
        if not seller_name and asset_id:
            asset = self.db.find_asset_by_id(asset_id)
            if asset and asset.owner:
                seller_name = asset.owner
        try:
            self._transfer_asset(asset_id, seller_name, buyer_name, buyer_pk)
        except TransferError:
            self.logger.info(f"[buy_success] race — {asset_id} already transferred")
            with self._active_buys_lock:
                self._active_buys.pop(asset_id, None)
            # Harmless duplicate: same buyer, second node confirmed the same tx
            asset = self.db.find_asset_by_id(asset_id) if asset_id else None
            if asset and asset.owner == buyer_name:
                return self._success("BUY_ACKNOWLEDGED")
            # Real race: a different buyer won — notify loser and refresh their balance
            if buyer_name:
                self._push_event(buyer_name, {
                    "type": "BUY_FAILED", "asset_id": asset_id,
                    "message": "This asset was just purchased by someone else",
                    "msg": f"Purchase failed — asset was just bought by someone else",
                }, persist=True)
            if buyer_pk:
                self._notify_gateway({"type": "GET_BALANCE", "userpk": buyer_pk})
            return self._success("BUY_ACKNOWLEDGED")
        with self._active_buys_lock:
            self._active_buys.pop(asset_id, None)
        self.logger.info(f"[buy_success] {asset_id} transferred {seller_name} -> {buyer_name}")
        self._push_buy_notifications(buyer_name, seller_name, asset_id, price)
        if asset_id:
            self._push_to_all_online({"type": "ASSET_REMOVED", "asset_id": asset_id})
        # Refresh balances for both parties so their UI shows the updated amount instantly
        seller_pk = str(data.get("seller_public_key") or "").strip()
        for pk in filter(None, [buyer_pk, seller_pk]):
            self._notify_gateway({"type": "GET_BALANCE", "userpk": pk})
        return self._success("BUY_ACKNOWLEDGED")

    def handle_buy_failed(self, comm, msg):
        _ = comm
        data = msg.get("data") if isinstance(msg.get("data"), dict) else {}
        buyer = self._resolve_buyer(data)
        asset_id = str(data.get("asset_id") or "").strip()
        buyer_pk = str(data.get("user_public_key") or data.get("public_key") or "").strip()
        message = str(data.get("message") or data.get("reason") or "Transaction rejected").strip()
        with self._active_buys_lock:
            self._active_buys.pop(asset_id, None)
        if buyer:
            self._push_event(buyer, {
                "type": "BUY_FAILED",
                "asset_id": asset_id,
                "message": message,
                "msg": f"Purchase failed for asset {asset_id}: {message}",
            }, persist=True)
        if buyer_pk:
            self._notify_gateway({"type": "GET_BALANCE", "userpk": buyer_pk})
        return self._success("BUY_FAILED_ACKNOWLEDGED")

    def handle_sell_success(self, comm, msg):
        _ = comm
        data = msg.get("data") if isinstance(msg.get("data"), dict) else {}
        seller = str(data.get("seller") or data.get("sender") or "").strip()
        asset_id = str(data.get("asset_id") or "").strip()
        if seller:
            self._push_event(seller, {"type": "BLOCK_ACCEPTED", "asset_id": asset_id})
        return self._success("SELL_ACKNOWLEDGED")

    def handle_block_rejected(self, comm, msg):
        _ = comm
        data = msg.get("data") if isinstance(msg.get("data"), dict) else {}
        username = str(data.get("username") or data.get("owner") or data.get("sender") or "").strip()
        asset_id = str(data.get("asset_id") or "").strip()
        reason = str(data.get("reason") or "").strip()
        message = str(data.get("message") or reason or "Block rejected").strip()

        # Second node detecting DUPLICATE_MINT for an asset that's already on the marketplace is
        # a harmless race — the first node already accepted the block. Don't alarm the client.
        if reason == "DUPLICATE_MINT" and asset_id:
            asset = self.db.find_asset_by_id(asset_id)
            if asset and asset.asset_status in (ASSET_STATUS_MINTED, ASSET_STATUS_LISTED):
                self.logger.info(f"[block_rejected] suppressed spurious DUPLICATE_MINT for {asset_id} (already {asset.asset_status})")
                return self._success("BLOCK_REJECTED_ACKNOWLEDGED")

        # Fall back to the asset's owner if username not in the payload
        if not username and asset_id:
            asset = self.db.find_asset_by_id(asset_id)
            if asset:
                username = asset.owner
        if username:
            self._push_event(username, {
                "type": "BLOCK_REJECTED",
                "asset_id": asset_id,
                "message": message,
                "msg": f"Blockchain error for asset {asset_id}: {message}",
            }, persist=True)
        return self._success("BLOCK_REJECTED_ACKNOWLEDGED")

    def handle_send_balance(self, comm, msg):
        _ = comm
        data = msg.get("data") if isinstance(msg.get("data"), dict) else {}
        userpk = str(msg.get("userpk") or data.get("userpk") or "").strip()
        balance = data.get("balance")
        if userpk:
            balance_val = float(balance) if balance is not None else 0.0
            self.logger.info(f"Balance update userpk={userpk[:12]}... balance={balance_val}")
            user = self.db.get_user_by_public_key(userpk)
            if user:
                with self.online_users_lock:
                    online_comm = self.online_users.get(user.username)
                if online_comm:
                    try:
                        online_comm.send_async({"type": "BALANCE_IS", "balance": balance_val})
                    except Exception:
                        pass
        return self._success("BALANCE_ACKNOWLEDGED")

    def handle_get_balance(self, comm, msg):
        _ = comm
        public_key = str(self._param(msg, "user_public_key", 0, "")).strip()
        if not public_key:
            return self._fail("BALANCE_FAILED", "Missing user_public_key")
        err = self._gateway_required()
        if err:
            return err
        self._notify_gateway({"type": "GET_BALANCE", "userpk": public_key})
        return self._success("BALANCE_REQUESTED")

    def handle_move_to_marketplace(self, comm, msg):
        """List an asset on the marketplace.

        UPLOADED → first time: sends UPLOAD_ASSET (MINT tx on blockchain).
        UNLISTED → re-listing:  sends LIST_ASSET  (LIST tx on blockchain).
        Both paths complete when the gateway responds with FULLY_UPLOAD,
        which sets the asset status to MINTED or LISTED respectively.
        """
        _ = comm
        try:
            username = str(self._param(msg, "username", 0, "")).strip()
            asset_id = str(self._param(msg, "asset_id", 1, "")).strip()
            tx_id = str(self._param(msg, "tx_id", 2, "")).strip() or uuid.uuid4().hex
            signature = str(self._param(msg, "signature", 3, "")).strip()
            self._require_fields(username, asset_id, msg="Missing username/asset_id")
            self._require_gateway()
            asset = self._find_asset(asset_id)
            self._require_asset_owner(asset, username)
            public_key = self._resolve_user_key(msg, username, param_index=4)
            self._require_asset_key(asset, public_key)

            status = asset.asset_status
            if status == ASSET_STATUS_UPLOADED:
                # First time: mine a MINT block
                file_hash = self._compute_file_hash(asset)
                self._notify_gateway({
                    "type": "UPLOAD_ASSET",
                    "data": {
                        "asset_id": asset_id, "owner": username, "public_key": public_key,
                        "file_hash": file_hash, "tx_id": tx_id, "signature": signature,
                    },
                })
                self.logger.info(f"[move_to_marketplace] MINT {asset_id} (owner={username})")
            elif status == ASSET_STATUS_UNLISTED:
                # Re-listing after an UNLIST: mine a LIST block (no re-mint)
                self._notify_gateway({
                    "type": "LIST_ASSET",
                    "data": {
                        "asset_id": asset_id, "owner": username, "public_key": public_key,
                        "tx_id": tx_id, "signature": signature,
                    },
                })
                self.logger.info(f"[move_to_marketplace] LIST {asset_id} (owner={username})")
            else:
                raise ValidationError(
                    f"Asset '{asset_id}' has status '{status}' — "
                    "only UPLOADED or UNLISTED assets can be moved to the marketplace"
                )

            return self._success("MOVE_PENDING", asset_id=asset_id)
        except AurexError as e:
            return self._fail("MOVE_FAILED", str(e))

    def handle_unlist_asset(self, comm, msg):
        """Client requests asset be unlisted from marketplace via blockchain mining."""
        _ = comm
        try:
            username = str(self._param(msg, "username", 0, "")).strip()
            asset_id = str(self._param(msg, "asset_id", 1, "")).strip()
            public_key = str(self._param(msg, "public_key", 2, "")).strip()
            signature = str(self._param(msg, "signature", 3, "")).strip()
            tx_id = str(self._param(msg, "tx_id", 4, "")).strip() or uuid.uuid4().hex
            self._require_fields(username, asset_id, msg="Missing username/asset_id")
            self._require_gateway()
            asset = self._find_asset(asset_id)
            self._require_asset_owner(asset, username)
            self._require_asset_key(asset, public_key)
            self._notify_gateway({
                "type": "UNLIST_ASSET",
                "data": {
                    "asset_id": asset_id, "owner": username,
                    "public_key": public_key, "signature": signature, "tx_id": tx_id,
                },
            })
            self.logger.info(f"[unlist_asset] {asset_id} sent to gateway (owner={username})")
            return self._success("UNLIST_PENDING")
        except AurexError as e:
            return self._fail("UNLIST_FAILED", str(e))

    def handle_fully_upload(self, comm, msg):
        """Gateway confirms asset block was mined — mark asset MINTED or LISTED."""
        _ = comm
        try:
            asset_id = str(self._param(msg, "asset_id", 0, "")).strip()
            block_hash = str(self._param(msg, "block_hash", 1, "")).strip()
            self._require_fields(asset_id, msg="Missing asset_id")
            asset = self._find_asset(asset_id)
            if asset.asset_status in (ASSET_STATUS_MINTED, ASSET_STATUS_LISTED):
                self.logger.info(f"[fully_upload] {asset_id} already {asset.asset_status}, skipping")
                return self._success("FULLY_UPLOAD_ACKNOWLEDGED")
            self._mark_asset_for_sale(asset_id, asset, block_hash)
            return self._success("FULLY_UPLOAD_ACKNOWLEDGED")
        except AurexError as e:
            return self._fail("FULLY_UPLOAD_FAILED", str(e))

    def handle_asset_unlisted(self, comm, msg):
        """Gateway confirms unlist block was mined — mark asset UNLISTED."""
        _ = comm
        asset_id = str(self._param(msg, "asset_id", 0, "")).strip()
        block_hash = str(self._param(msg, "block_hash", 1, "")).strip()
        if not asset_id:
            return self._fail("ASSET_UNLISTED_FAILED", "Missing asset_id")
        asset = self.db.find_asset_by_id(asset_id)
        if asset and asset.asset_status == "UNLISTED":
            self.logger.info(f"[asset_unlisted] asset {asset_id} already UNLISTED, skipping duplicate")
            return self._success("UNLIST_ACKNOWLEDGED")
        ok = self.db.update_asset_status(asset_id, "UNLISTED", increment_version=True)
        if ok:
            self.logger.info(f"[asset_unlisted] asset {asset_id} is now UNLISTED hash={block_hash[:16] if block_hash else '?'}...")
            asset = self.db.find_asset_by_id(asset_id)
            if asset and asset.owner:
                asset_name = asset.asset_name or asset_id
                self._push_event(asset.owner, {
                    "type": "ASSET_UNLISTED",
                    "asset_id": asset_id,
                    "msg": f"'{asset_name}' has been unlisted from the marketplace",
                })
            # Remove from every user's marketplace view
            self._push_to_all_online({"type": "ASSET_REMOVED", "asset_id": asset_id})
        else:
            self.logger.warning(f"[asset_unlisted] update_asset_status failed for {asset_id}")
        return self._success("UNLIST_ACKNOWLEDGED")

    def handle_get_assets_ids(self, comm, msg):
        _ = comm
        username = str(msg.get("username") or "").strip()
        if username:
            items = self.db.get_assets_for_user(username)
        else:
            items = self.db.get_all_for_sale_assets()
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

        content_b64 = ""
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
            "asset_status": getattr(item, "asset_status", ASSET_STATUS_UPLOADED),
        })
        for chunk in chunks:
            comm.send_async({"type": "ASSET_CHUNK", "chunk_b64": chunk})
        comm.send_async({"type": "ASSET_END"})
        return None

    def handle_delete_asset(self, comm, msg):
        """Delete an asset from the marketplace — removes DB entry, file, and notifies all users."""
        _ = comm
        try:
            username = str(self._param(msg, "owner", 0, "")).strip()
            asset_id = str(self._param(msg, "asset_id", 1, "")).strip()
            self._require_fields(username, asset_id, msg="Missing owner or asset_id")
            asset = self._find_asset(asset_id)
            self._require_asset_owner(asset, username)
            if asset.storage_path:
                try:
                    Path(asset.storage_path).unlink(missing_ok=True)
                except Exception:
                    pass
            if not self.db.delete_asset(asset_id, username):
                raise BlockchainError(f"Failed to delete asset '{asset_id}'")
            self._push_to_all_online({"type": "ASSET_REMOVED", "asset_id": asset_id})
            self.logger.info(f"[delete_asset] {asset_id} deleted by {username}")
            return self._success("DELETE_ASSET_SUCCESS")
        except AurexError as e:
            return self._fail("DELETE_ASSET_FAILED", str(e))

    def handle_delete_account(self, comm, msg):
        username = str(self._param(msg, "username", 0, "")).strip()
        if not username:
            return self._fail("DELETE_FAILED", "Missing username")

        self.db.delete_user(username)
        self.db.delete_user_assets(username)

        # Clear queued notifications
        self.db.flush_notifications(username)

        uploads_dir = Path(__file__).resolve().parent.parent / "DB" / "uploads" / username
        if uploads_dir.exists():
            shutil.rmtree(uploads_dir, ignore_errors=True)

        with self.online_users_lock:
            self.online_users.pop(username, None)

        self.logger.info(f"Account deleted: {username}")
        return self._success("ACCOUNT_IS_DELETED")

    def handle_clear_notifications(self, comm, msg):
        _ = comm
        username = str(self._param(msg, "username", 0, "")).strip()
        if username:
            self.db.flush_notifications(username)
        return self._success("NOTIFICATIONS_CLEARED")


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

    server = Server()
    print(f"[*] Starting ServerUpdated on {SERVER_IP}:{SERVER_PORT}...")
    server.start()
