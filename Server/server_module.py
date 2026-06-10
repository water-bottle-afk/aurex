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
from SharedResources.classes import RSA_Server, MarketplaceItem, ASSET_STATUS_FOR_SALE
from SharedResources.logging import Logger

logger = Logger(__file__)

# Keys are stored in Server/ServerKeys/ — always relative to this file.
SERVER_KEYS_DIR = str(Path(__file__).resolve().parent / "ServerKeys")

MAX_UPLOAD_BYTES = 5 * 1024 * 1024  # 5 MB hard limit

try:
    from PIL import Image as PILImage
    import io as pil_io
    PIL_AVAILABLE = True
except ImportError:
    PILImage = None
    pil_io = None
    PIL_AVAILABLE = False
    logger.warning("[security] Pillow not installed — image sanitization disabled. pip install Pillow")


def sanitize_and_save_image(file_bytes: bytes, output_path: str, file_format: str) -> bool:
    """
    Sanitize an uploaded image by re-rendering it from raw pixel data only.

    Security model:
      • The file bytes are never executed — PIL decodes them into pixel arrays.
      • ``Image.verify()`` checks structural integrity.
      • A brand-new Image object is built from the pixel data, discarding ALL
        metadata, EXIF, embedded scripts, and steganographic payloads.
      • The clean image is saved to *output_path* from scratch, so the file on
        disk can never contain the original binary payload.

    If Pillow is not installed the function falls back to a magic-bytes check
    only and writes the raw bytes directly (less secure but functional).

    Args:
        file_bytes:  Raw (decoded) image bytes received from the upload.
        output_path: Absolute path where the sanitized file will be written.
        file_format: Claimed format string ('jpg', 'jpeg', or 'png').

    Returns:
        True  — sanitization and save succeeded.
        False — file is structurally invalid or appears malicious.
    """
    pil_fmt = "JPEG" if file_format.lower() in ("jpg", "jpeg") else "PNG"

    if not PIL_AVAILABLE:
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
        buf = pil_io.BytesIO(file_bytes)

        # Structural integrity check (closes internal stream — re-open afterwards)
        probe = PILImage.open(buf)
        probe.verify()

        # Re-open after verify()
        buf.seek(0)
        raw_img = PILImage.open(buf)

        # JPEG does not support alpha or palette modes — normalise to RGB
        if pil_fmt == "JPEG" and raw_img.mode not in ("RGB", "L"):
            raw_img = raw_img.convert("RGB")

        # Build a new image from pixels ONLY — strips every byte of metadata
        clean = PILImage.new(raw_img.mode, raw_img.size)
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
        self.gateway_comm = None          # single gateway connection
        self.gateway_lock = threading.RLock()
        self.online_users: dict[str, object] = {}
        self.online_users_lock = threading.RLock()
        self.client_listener = RSA_Server(
            self.host, self.port,
            dir_for_keys=SERVER_KEYS_DIR,
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
            "GET_BALANCE": self.handle_get_balance,
            "FULLY_UPLOAD": self.handle_fully_upload,
            "ASSET_UNLISTED": self.handle_asset_unlisted,
            "MOVE_TO_MARKETPLACE": self.handle_move_to_marketplace,
            "UNLIST_ASSET": self.handle_unlist_asset,
            "DELETE_ASSET": self.handle_delete_asset,
        }

    def start(self):
        """Start the RSA server — blocks until the server stops."""
        self.client_listener.start()

    # ── Connection handling ───────────────────────────────────────────────────

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

    def param(self, msg, key, index, default=""):
        _ = index
        return msg.get(key, default)

    def success(self, event_type, **extra):
        payload = {"type": event_type}
        payload.update(extra)
        return payload

    def fail(self, *args):
        message = args[-1]
        return {"type": "ERROR", "message": str(message)}

    def gateway_required(self):
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
                return self.fail("GATEWAY_OFFLINE", "Gateway Server isn't online.")
        return None

    def notify_gateway(self, payload):
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

    # ── Notifications (via ORM) ───────────────────────────────────────────────

    def flush_notifications_for_user(self, username: str, comm):
        msgs = self.db.flush_notifications(username)
        for msg in msgs:
            if not msg:
                continue
            try:
                comm.send_async({"type": "NOTIFICATION", "msg": msg})
            except Exception:
                self.db.queue_notification(username, msg)
                return

    def push_to_all_online(self, event: dict):
        """
        Broadcast a real-time event to every currently connected user.

        Unlike ``_push_event``, this never queues the message for offline
        users — it is intended for ephemeral UI updates (e.g. "remove this
        asset from the marketplace grid").

        Args:
            event: Message dict to broadcast (must include a "type" key).
        """
        with self.online_users_lock:
            targets = list(self.online_users.items())
        for username, comm in targets:
            try:
                comm.send_async(event)
            except Exception:
                pass

    def push_event(self, username: str, event: dict):
        """
        Send a typed protocol event to a specific user.

        If the user is currently connected the event is sent immediately over
        their live socket.  If they are offline the ``msg`` field (or a
        key=value summary) is queued in the ORM notifications store so they
        see it on their next login.

        Args:
            username: Target username (must be in the ORM users table).
            event:    Dict with at least ``"type"`` and optionally ``"msg"``.
        """
        username = str(username or "").strip()
        if not username or not event:
            return
        with self.online_users_lock:
            online_comm = self.online_users.get(username)
        if online_comm is None:
            msg_text = event.get("msg") or "; ".join(f"{k}={v}" for k, v in event.items() if k != "type")
            self.db.queue_notification(username, msg_text)
            return
        try:
            online_comm.send_async(event)
        except Exception:
            with self.online_users_lock:
                if self.online_users.get(username) == online_comm:
                    self.online_users.pop(username, None)
            msg_text = event.get("msg") or "; ".join(f"{k}={v}" for k, v in event.items() if k != "type")
            self.db.queue_notification(username, msg_text)

    # ── Handlers ─────────────────────────────────────────────────────────────

    def handle_start(self, comm, msg):
        _ = comm, msg
        return self.success("READY")

    def handle_login(self, comm, msg):
        username = str(self.param(msg, "username", 0, "")).strip()
        password = str(self.param(msg, "password", 1, ""))
        if not username or not password:
            return self.fail("LOGIN_FAILED", "Missing username/password")
        user = self.db.get_user(username)
        if not user:
            return self.fail("LOGIN_FAILED", f"Username '{username}' not found")
        if not user.verify_password(password):
            return self.fail("LOGIN_FAILED", f"Incorrect password for '{username}'")
        if hasattr(comm, "set_user"):
            comm.set_user(user)
        else:
            comm.user = user
        with self.online_users_lock:
            self.online_users[username] = comm
        self.flush_notifications_for_user(username, comm)
        if user.public_key:
            self.notify_gateway({"type": "GET_BALANCE", "userpk": user.public_key})
        return self.success("LOGIN_SUCCESS", username=username)

    def handle_signup(self, comm, msg):
        _ = comm
        username = str(self.param(msg, "username", 0, "")).strip()
        password = str(self.param(msg, "password", 1, ""))
        email = str(self.param(msg, "email", 2, "")).strip().lower()
        if not username or not password or not email:
            return self.fail("SIGNUP_FAILED", "Missing required fields")
        if not re.match(r"^[a-zA-Z0-9_]{3,20}$", username):
            return self.fail("SIGNUP_FAILED", "Username must be 3-20 alnum/underscore")
        if len(password) < 6:
            return self.fail("SIGNUP_FAILED", "Password must be at least 6 characters")
        if "@" not in email or " " in email:
            return self.fail("SIGNUP_FAILED", "Invalid email format")
        ok, message = self.db.add_user(username, password, email)
        if not ok:
            return self.fail("SIGNUP_FAILED", message)
        return self.success("SIGNUP_SUCCESS", username=username)

    def handle_send_code(self, comm, msg):
        _ = comm
        email = str(self.param(msg, "email", 0, "")).strip().lower()
        if not email:
            return self.fail("CODE_FAILED", "Missing email")
        ok, message, code = self.db.issue_reset_code(email)
        if not ok:
            return self.fail("CODE_FAILED", message)
        threading.Thread(target=send_reset_email, args=(email, code), daemon=True).start()
        return self.success("CODE_SENT")

    def handle_verify_code(self, comm, msg):
        _ = comm
        email = str(self.param(msg, "email", 0, "")).strip().lower()
        code = str(self.param(msg, "code", 1, "")).strip()
        if not email or not code:
            return self.fail("CODE_FAILED", "Missing email/code")
        ok, message, user = self.db.verify_reset_code(email, code)
        if not ok:
            return self.fail("CODE_FAILED", message)
        return self.success("CODE_VERIFIED", username=user.username)

    def handle_update_password(self, comm, msg):
        _ = comm
        email = str(self.param(msg, "email", 0, "")).strip().lower()
        new_password = str(self.param(msg, "new_password", 1, self.param(msg, "password", 1, "")))
        code = str(self.param(msg, "code", 2, "")).strip()
        if not email or not new_password or not code:
            return self.fail("UPDATE_FAILED", "Missing email/code/new_password")
        if len(new_password) < 6:
            return self.fail("UPDATE_FAILED", "Password must be at least 6 characters")
        ok, message, _ = self.db.verify_reset_code(email, code)
        if not ok:
            if "expired" in message.lower():
                return self.fail("UPDATE_FAILED", "Code expired — press 'Send Code' to get a new one")
            return self.fail("UPDATE_FAILED", "Invalid verification code")
        update_ok, update_msg = self.db.update_password_by_email(email, new_password)
        if not update_ok:
            return self.fail("UPDATE_FAILED", update_msg)
        return self.success("PASSWORD_UPDATED")

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
        return self.success("LOGOUT_SUCCESS")

    def handle_upload_init(self, comm, msg):
        _ = comm
        upload_id = str(self.param(msg, "upload_id", 0, "")).strip()
        username = str(self.param(msg, "username", 1, "")).strip()
        asset_name = str(self.param(msg, "asset_name", 2, "")).strip()
        description = str(self.param(msg, "description", 3, "")).strip()
        file_type = str(self.param(msg, "file_type", 4, "")).strip().lower()
        cost_raw = self.param(msg, "cost", 5, 0)
        try:
            cost = float(cost_raw)
        except Exception:
            cost = -1
        if not upload_id:
            return self.fail("UPLOAD_FAILED", "Missing upload_id")
        if not username or not asset_name or file_type not in {"jpg", "jpeg", "png"} or cost < 0:
            return self.fail("UPLOAD_FAILED", "Invalid upload_init fields")
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
        return self.success("UPLOAD_READY")

    def handle_upload(self, comm, msg):
        _ = comm
        upload_id = str(self.param(msg, "upload_id", 0, "")).strip()
        chunk_b64 = str(self.param(msg, "chunk_b64", 1, self.param(msg, "chunk", 1, ""))).strip()
        if not upload_id or not chunk_b64:
            return self.fail("UPLOAD_FAILED", "Missing upload_id/chunk_b64")
        with self.upload_lock:
            session = self.upload_sessions.get(upload_id)
            if not session:
                return self.fail("UPLOAD_FAILED", "Upload session not found")
            session.chunks_b64.append(chunk_b64)
        return self.success("CHUNK_RECEIVED")

    def handle_upload_finish(self, comm, msg):
        """
        Finalise an in-progress upload: decode chunks, enforce limits,
        sanitize the image via PIL, and register the asset in the ORM.

        Security steps applied (in order):
          1. Base-64 decode — rejects malformed payloads.
          2. 5 MB hard limit — rejects oversized files before touching disk.
          3. PIL sanitize_and_save_image — re-renders from pixels only,
             stripping metadata and any embedded payload.

        On success returns ``UPLOAD_SUCCESS`` with the new ``asset_id``.
        """
        _ = comm
        upload_id = str(self.param(msg, "upload_id", 0, "")).strip()
        if not upload_id:
            return self.fail("UPLOAD_FAILED", "Missing upload_id")
        with self.upload_lock:
            session = self.upload_sessions.pop(upload_id, None)
        if not session:
            return self.fail("UPLOAD_FAILED", "Upload session not found")
        content_b64 = "".join(session.chunks_b64)
        try:
            raw = base64.b64decode(content_b64.encode("utf-8"), validate=True)
        except Exception:
            return self.fail("UPLOAD_FAILED", "Invalid upload payload")

        # ── 5 MB hard limit ───────────────────────────────────────────────────
        if len(raw) > MAX_UPLOAD_BYTES:
            return self.fail(
                "UPLOAD_FAILED",
                f"File exceeds 5 MB limit ({len(raw) / 1024 / 1024:.1f} MB received)",
            )

        # ── PIL sanitization — re-render from pixels, discard all metadata ───
        asset_hash = hashlib.sha256(raw).hexdigest()
        uploads_dir = Path(__file__).resolve().parent.parent / "DB" / "uploads" / session.username
        uploads_dir.mkdir(parents=True, exist_ok=True)
        file_path = uploads_dir / f"{asset_hash}.{session.file_type}"

        if not sanitize_and_save_image(raw, str(file_path), session.file_type):
            return self.fail(
                "UPLOAD_FAILED",
                f"File is invalid or contains unsupported content — "
                f"only clean PNG/JPEG images are accepted",
            )
        user = self.db.get_user(session.username)
        public_key = getattr(user, "public_key", "") if user else ""
        item = MarketplaceItem(
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
        self.db.add_asset(session.username, item)
        return self.success("UPLOAD_SUCCESS", asset_id=item.asset_id)

    def handle_get_items(self, comm, msg):
        _ = comm, msg
        items = [item.to_dict() for item in self.db.get_all_assets()]
        return self.success("ITEMS_LIST", items=items)

    def handle_update_public_key(self, comm, msg):
        _ = comm
        username = str(self.param(msg, "username", 0, "")).strip()
        public_key = str(self.param(msg, "public_key", 1, "")).strip()
        if not username or not public_key:
            return self.fail("KEY_FAILED", "Missing username/public_key")
        if self.db.is_public_key_taken(public_key, exclude_username=username):
            return self.fail("KEY_FAILED", "Public key update failed: another user has this public key")
        ok = self.db.set_user_public_key(username, public_key)
        if not ok:
            return self.fail("KEY_FAILED", "User not found")
        err = self.gateway_required()
        if err:
            return self.success("KEY_UPDATED")  # key saved locally; balance will sync when gateway comes online
        self.notify_gateway({
            "type": "CREATE_BALANCE",
            "data": {
                "username": username,
                "public_key": public_key,
                "balance": float(INITIAL_BALANCE),
            },
        })
        return self.success("KEY_UPDATED")

    def handle_register_gateway(self, comm, msg):
        _ = msg
        comm.peer_label = "Gateway"
        with self.gateway_lock:
            self.gateway_comm = comm
        self.logger.info("Gateway registered")
        return self.success("GATEWAY_REGISTERED")

    def handle_buy_asset(self, comm, msg):
        """
        Forward a signed buy request from the client to the gateway.

        Validates that the buyer, public key and signature are present, then
        forwards a ``TX_REQUEST_BUY`` message to the gateway which broadcasts
        it to all blockchain nodes for mining.  The actual transfer happens
        asynchronously when a node sends ``BUY_SUCCESS``.

        Returns ``BUY_SUBMITTED`` immediately so the UI stays responsive.
        """
        _ = comm
        err = self.gateway_required()
        if err:
            return err
        data = msg.get("data") if isinstance(msg.get("data"), dict) else {}
        buyer = str(data.get("buyer", "")).strip()
        public_key = str(data.get("public_key", "")).strip()
        signature = str(data.get("signature", "")).strip()
        if not buyer or not public_key or not signature:
            return self.fail("BUY_FAILED", "Missing buyer/public_key/signature")
        self.notify_gateway({"type": "TX_REQUEST_BUY", "data": data})
        return self.success("BUY_SUBMITTED")

    def handle_buy_success(self, comm, msg):
        """
        Process a confirmed purchase from the gateway/node.

        Resolves buyer and seller usernames from their public keys, transfers
        the asset in the ORM, and pushes real-time events:
          • ``BUY_SUCCESS``  → buyer
          • ``ASSET_SOLD``   → seller
          • ``ASSET_REMOVED``→ all online users (removes card from marketplace)

        If ``transfer_asset`` returns False the asset was already transferred
        (race condition — two nodes mined the same tx).  In that case a
        ``BUY_FAILED`` is pushed to the late buyer and the call returns early.
        """
        _ = comm
        data = msg.get("data") if isinstance(msg.get("data"), dict) else {}
        buyer_pk = str(data.get("sender") or data.get("public_key") or "").strip()
        seller_pk = str(data.get("receiver") or "").strip()
        buyer_username = str(data.get("buyer_username") or data.get("buyer") or "").strip()
        asset_id = str(data.get("asset_id") or "").strip()
        price = data.get("price") if data.get("price") is not None else data.get("amount")

        buyer_user = self.db.get_user_by_public_key(buyer_pk) if buyer_pk else None
        seller_user = self.db.get_user_by_public_key(seller_pk) if seller_pk else None
        buyer_name = (buyer_user.username if buyer_user else None) or buyer_username
        seller_name = seller_user.username if seller_user else ""

        transfer_ok = False
        if asset_id and seller_name and buyer_name:
            transfer_ok = self.db.transfer_asset(asset_id, seller_name, buyer_name)
            if transfer_ok:
                self.logger.info(f"[buy_success] asset {asset_id} transferred {seller_name} -> {buyer_name}")
            else:
                self.logger.info(f"[buy_success] transfer failed for {asset_id} — already transferred (race condition or duplicate)")
                # Notify the late buyer their purchase didn't go through
                if buyer_name:
                    self.push_event(buyer_name, {
                        "type": "BUY_FAILED",
                        "asset_id": asset_id,
                        "message": "This asset was just purchased by someone else",
                    })
                return self.success("BUY_ACKNOWLEDGED")

        # First successful transfer — push notifications and remove from all UIs
        if transfer_ok and buyer_name:
            self.push_event(buyer_name, {
                "type": "BUY_SUCCESS",
                "asset_id": asset_id,
                "price": price,
                "msg": f"Purchase confirmed — asset {asset_id} at {price} AUR is now yours!",
            })

        if transfer_ok and seller_name:
            asset = self.db.find_asset_by_id(asset_id)
            asset_label = asset.asset_name if asset else asset_id
            self.push_event(seller_name, {
                "type": "ASSET_SOLD",
                "asset_id": asset_id,
                "buyer": buyer_name,
                "price": price,
                "msg": f"Your asset '{asset_label}' was sold to {buyer_name} for {price} AUR",
            })

        if transfer_ok and asset_id:
            # Tell every browsing user to remove this asset from their marketplace view
            self.push_to_all_online({"type": "ASSET_REMOVED", "asset_id": asset_id})

        return self.success("BUY_ACKNOWLEDGED")

    def handle_buy_failed(self, comm, msg):
        _ = comm
        data = msg.get("data") if isinstance(msg.get("data"), dict) else {}
        buyer = str(data.get("buyer") or data.get("sender") or "").strip()
        asset_id = str(data.get("asset_id") or "").strip()
        message = str(data.get("message") or data.get("reason") or "Transaction rejected").strip()
        if buyer:
            self.push_event(buyer, {
                "type": "BUY_FAILED",
                "asset_id": asset_id,
                "message": message,
            })
        return self.success("BUY_FAILED_ACKNOWLEDGED")

    def handle_sell_success(self, comm, msg):
        _ = comm
        data = msg.get("data") if isinstance(msg.get("data"), dict) else {}
        seller = str(data.get("seller") or data.get("sender") or "").strip()
        asset_id = str(data.get("asset_id") or "").strip()
        if seller:
            self.push_event(seller, {"type": "BLOCK_ACCEPTED", "asset_id": asset_id})
        return self.success("SELL_ACKNOWLEDGED")

    def handle_block_rejected(self, comm, msg):
        _ = comm
        data = msg.get("data") if isinstance(msg.get("data"), dict) else {}
        username = str(data.get("username") or data.get("sender") or "").strip()
        asset_id = str(data.get("asset_id") or "").strip()
        message = str(data.get("message") or data.get("reason") or "Block rejected").strip()
        if username:
            self.push_event(username, {"type": "BLOCK_REJECTED", "asset_id": asset_id, "message": message})
        return self.success("BLOCK_REJECTED_ACKNOWLEDGED")

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
                # Only push to ONLINE users — balance updates are real-time only.
                # Don't queue as text notification: the user will get a fresh balance
                # on their next login, and stale balance strings pollute notifications.
                with self.online_users_lock:
                    online_comm = self.online_users.get(user.username)
                if online_comm:
                    try:
                        online_comm.send_async({"type": "BALANCE_IS", "balance": balance_val})
                    except Exception:
                        pass
        return self.success("BALANCE_ACKNOWLEDGED")

    def handle_get_balance(self, comm, msg):
        _ = comm
        public_key = str(self.param(msg, "user_public_key", 0, "")).strip()
        if not public_key:
            return self.fail("BALANCE_FAILED", "Missing user_public_key")
        err = self.gateway_required()
        if err:
            return err
        self.notify_gateway({"type": "GET_BALANCE", "userpk": public_key})
        return self.success("BALANCE_REQUESTED")

    def handle_move_to_marketplace(self, comm, msg):
        """
        Initiate blockchain mining to list an owned asset on the marketplace.

        Looks up the asset in the ORM, retrieves the owner's public key and
        computes the SHA-256 file hash, then sends an ``UPLOAD_ASSET`` message
        to the gateway.  The asset status is updated to ``FOR_SALE`` only
        after a node successfully mines the block and the gateway confirms it
        via ``FULLY_UPLOAD``.

        Args (from msg):
            username: Owner's username.
            asset_id: Asset to list.
            tx_id:    Client-generated UUID — used by the gateway to deduplicate.
            signature: Owner's private-key signature of {asset_id, owner, tx_id}.
        """
        """Client requests asset be listed on marketplace via blockchain mining."""
        _ = comm
        username = str(self.param(msg, "username", 0, "")).strip()
        asset_id = str(self.param(msg, "asset_id", 1, "")).strip()
        tx_id = str(self.param(msg, "tx_id", 2, "")).strip() or uuid.uuid4().hex
        signature = str(self.param(msg, "signature", 3, "")).strip()
        if not username or not asset_id:
            return self.fail("MOVE_FAILED", "Missing username/asset_id")
        err = self.gateway_required()
        if err:
            return err
        asset = self.db.find_asset_by_id(asset_id)
        if not asset:
            return self.fail("MOVE_FAILED", f"Asset {asset_id} not found")
        if asset.owner != username:
            return self.fail("MOVE_FAILED", "Asset does not belong to this user")
        user = self.db.get_user(username)
        public_key = str(self.param(msg, "public_key", 4, "")).strip() or (getattr(user, "public_key", "") if user else "")
        if asset.asset_status == "UNLISTED":
            # Asset is already on-chain — mine a LIST tx (re-list), not a new MINT.
            self.notify_gateway({
                "type": "LIST_ASSET",
                "data": {
                    "asset_id": asset_id,
                    "owner": username,
                    "public_key": public_key,
                    "tx_id": tx_id,
                    "signature": signature,
                },
            })
            self.logger.info(f"[move_to_marketplace] asset {asset_id} sent to gateway for LIST mining (owner={username})")
        else:
            # PENDING — asset has never been on-chain. Mine an ASSET_MINT tx.
            file_hash = ""
            try:
                storage_path = Path(asset.storage_path)
                if storage_path.exists():
                    file_hash = hashlib.sha256(storage_path.read_bytes()).hexdigest()
            except Exception:
                pass
            self.notify_gateway({
                "type": "UPLOAD_ASSET",
                "data": {
                    "asset_id": asset_id,
                    "owner": username,
                    "public_key": public_key,
                    "file_hash": file_hash,
                    "tx_id": tx_id,
                    "signature": signature,
                },
            })
            self.logger.info(f"[move_to_marketplace] asset {asset_id} sent to gateway for MINT mining (owner={username})")
        return self.success("MOVE_PENDING")

    def handle_unlist_asset(self, comm, msg):
        """Client requests asset be unlisted from marketplace via blockchain mining."""
        _ = comm
        username = str(self.param(msg, "username", 0, "")).strip()
        asset_id = str(self.param(msg, "asset_id", 1, "")).strip()
        public_key = str(self.param(msg, "public_key", 2, "")).strip()
        signature = str(self.param(msg, "signature", 3, "")).strip()
        tx_id = str(self.param(msg, "tx_id", 4, "")).strip() or uuid.uuid4().hex
        if not username or not asset_id:
            return self.fail("UNLIST_FAILED", "Missing username/asset_id")
        err = self.gateway_required()
        if err:
            return err
        self.notify_gateway({
            "type": "UNLIST_ASSET",
            "data": {
                "asset_id": asset_id,
                "owner": username,
                "public_key": public_key,
                "signature": signature,
                "tx_id": tx_id,
            },
        })
        self.logger.info(f"[unlist_asset] asset {asset_id} sent to gateway for unlist mining (owner={username})")
        return self.success("UNLIST_PENDING")

    def handle_fully_upload(self, comm, msg):
        """Gateway confirms asset block was mined — mark asset FOR_SALE."""
        _ = comm
        asset_id = str(self.param(msg, "asset_id", 0, "")).strip()
        block_hash = str(self.param(msg, "block_hash", 1, "")).strip()
        if not asset_id:
            return self.fail("FULLY_UPLOAD_FAILED", "Missing asset_id")
        asset = self.db.find_asset_by_id(asset_id)
        if asset and asset.asset_status == ASSET_STATUS_FOR_SALE:
            self.logger.info(f"[fully_upload] asset {asset_id} already FOR_SALE, skipping duplicate")
            return self.success("FULLY_UPLOAD_ACKNOWLEDGED")
        ok = self.db.update_asset_status(asset_id, "FOR_SALE")
        if ok:
            self.logger.info(f"[fully_upload] asset {asset_id} is now FOR_SALE hash={block_hash[:16] if block_hash else '?'}...")
            asset = self.db.find_asset_by_id(asset_id)
            if asset and asset.owner:
                asset_name = asset.asset_name or asset_id
                self.push_event(asset.owner, {
                    "type": "FULLY_UPLOADED",
                    "asset_id": asset_id,
                    "msg": f"'{asset_name}' is now live on the marketplace!",
                })
                user = self.db.get_user(asset.owner)
                owner_pk = getattr(user, "public_key", "") if user else ""
                if owner_pk:
                    self.notify_gateway({"type": "GET_BALANCE", "userpk": owner_pk})
        else:
            self.logger.warning(f"[fully_upload] update_asset_status failed for {asset_id}")
        return self.success("FULLY_UPLOAD_ACKNOWLEDGED")

    def handle_asset_unlisted(self, comm, msg):
        """Gateway confirms unlist block was mined — mark asset UNLISTED."""
        _ = comm
        asset_id = str(self.param(msg, "asset_id", 0, "")).strip()
        block_hash = str(self.param(msg, "block_hash", 1, "")).strip()
        if not asset_id:
            return self.fail("ASSET_UNLISTED_FAILED", "Missing asset_id")
        asset = self.db.find_asset_by_id(asset_id)
        if asset and asset.asset_status == "UNLISTED":
            self.logger.info(f"[asset_unlisted] asset {asset_id} already UNLISTED, skipping duplicate")
            return self.success("UNLIST_ACKNOWLEDGED")
        ok = self.db.update_asset_status(asset_id, "UNLISTED", increment_version=True)
        if ok:
            self.logger.info(f"[asset_unlisted] asset {asset_id} is now UNLISTED hash={block_hash[:16] if block_hash else '?'}...")
            asset = self.db.find_asset_by_id(asset_id)
            if asset and asset.owner:
                asset_name = asset.asset_name or asset_id
                self.push_event(asset.owner, {
                    "type": "ASSET_UNLISTED",
                    "asset_id": asset_id,
                    "msg": f"'{asset_name}' has been unlisted from the marketplace",
                })
            # Remove from every user's marketplace view
            self.push_to_all_online({"type": "ASSET_REMOVED", "asset_id": asset_id})
        else:
            self.logger.warning(f"[asset_unlisted] update_asset_status failed for {asset_id}")
        return self.success("UNLIST_ACKNOWLEDGED")

    def handle_get_assets_ids(self, comm, msg):
        _ = comm
        username = str(msg.get("username") or "").strip()
        if username:
            items = self.db.get_assets_for_user(username)
        else:
            items = self.db.get_all_for_sale_assets()
        ids = [{"id": item.asset_id, "version": getattr(item, "version", 1)} for item in items if item.asset_id]
        return self.success("ASSETS_IDS_LIST", ids=ids)

    def handle_get_asset_by_id(self, comm, msg):
        asset_id = str(self.param(msg, "id", 0, "")).strip()
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
            "asset_status": getattr(item, "asset_status", "PENDING"),
        })
        for chunk in chunks:
            comm.send_async({"type": "ASSET_CHUNK", "chunk_b64": chunk})
        comm.send_async({"type": "ASSET_END"})
        return None

    def handle_delete_account(self, comm, msg):
        username = str(self.param(msg, "username", 0, "")).strip()
        if not username:
            return self.fail("DELETE_FAILED", "Missing username")

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
        return self.success("ACCOUNT_IS_DELETED")

    def handle_delete_asset(self, comm, msg):
        _ = comm
        asset_id = str(self.param(msg, "asset_id", 0, "")).strip()
        owner = str(self.param(msg, "owner", 1, "")).strip()
        if not asset_id or not owner:
            return self.fail("DELETE_FAILED", "Missing asset_id or owner")
        asset = self.db.find_asset_by_id(asset_id)
        if not asset:
            return self.fail("DELETE_FAILED", f"Asset {asset_id} not found")
        if asset.owner != owner:
            return self.fail("DELETE_FAILED", "Asset does not belong to this user")
        ok = self.db.delete_asset(asset_id, owner)
        if not ok:
            return self.fail("DELETE_FAILED", "Could not delete asset")
        try:
            storage_path = Path(asset.storage_path)
            if storage_path.exists():
                storage_path.unlink()
        except Exception:
            pass
        self.push_to_all_online({"type": "ASSET_REMOVED", "asset_id": asset_id})
        self.logger.info(f"[delete_asset] asset {asset_id} deleted by {owner}")
        return self.success("DELETE_SUCCESS")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Aurex marketplace server")
    parser.add_argument(
        "--debug-level", "--DEBUG_LEVEL",
        default="DEBUG",
        choices=["DEBUG", "INFO", "WARNING", "ERROR"],
    )
    args = parser.parse_args()
    from SharedResources.logging import Logger as Logger
    Logger.set_level(args.debug_level)

    server = Server()
    print(f"[*] Starting ServerUpdated on {SERVER_IP}:{SERVER_PORT}...")
    server.start()
